"""faster-whisper (large-v3-turbo) transcription wrapper.

Produces the **Transcript** schema (CONTRACTS.md §3):

    Word       = {text, start, end}
    Segment    = {start, end, text, words: [Word]}
    Transcript = {language, segments: [Segment], durationSec}

The heavy ``faster_whisper`` import is deferred behind a *loader seam*
(:class:`WhisperLoader`) so this module — and its tests — never import the model
library at import time. Tests inject a fake loader/model; the real loader is
constructed lazily inside :func:`transcribe_file` only when no loader is given.

Lifecycle is **load-use-free, one heavy model at a time** (CONTRACTS.md §7):
the loader is consulted per call and may be released by the caller (the
``models/runner.py`` lifecycle owner) once the job completes.

Device selection follows a **CPU-fallback** policy: prefer the requested device
(default ``cuda`` with ``float16``); if construction raises (no GPU / no CUDA
runtime), fall back to ``cpu`` with ``int8``. Language is auto-detected when the
caller passes no ``language`` (faster-whisper detects + returns it).

Wiring: :func:`register` installs the ``transcribe.start`` method (§2). It is a
*long job* — returns ``{jobId}`` immediately, streams ``job.progress``, and the
final ``job.done.result`` is ``{transcript}``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ..util import clamp, get_logger

log = get_logger("media_studio.features.transcribe")

_cuda_dirs_registered = False


def _register_cuda_dll_dirs() -> None:
    """Make the pip-wheel CUDA runtimes loadable by ctranslate2 (Windows).

    ctranslate2 lazy-loads ``cublas64_12.dll``/``cudnn*.dll`` at first ENCODE
    (not at model construction). The ``nvidia-cublas-cu12``/``nvidia-cudnn-cu12``
    wheels drop those DLLs under ``site-packages/nvidia/*/bin``, which is NOT on
    the DLL search path — without this hook the first transcribe raises
    "Library cublas64_12.dll is not found" (or, in a windowless process, blocks
    on a hidden system error dialog). Idempotent; no-op off-Windows or when the
    wheels are absent (system CUDA on PATH still works).
    """
    global _cuda_dirs_registered
    if _cuda_dirs_registered or sys.platform != "win32":
        return
    _cuda_dirs_registered = True
    for sp in sys.path:
        nvidia_root = Path(sp) / "nvidia"
        if not nvidia_root.is_dir():
            continue
        for bin_dir in sorted(nvidia_root.glob("*/bin")):
            try:
                os.add_dll_directory(str(bin_dir))
                os.environ["PATH"] = f"{bin_dir};{os.environ.get('PATH', '')}"
                log.info("registered CUDA DLL dir: %s", bin_dir)
            except OSError:  # pragma: no cover - defensive
                pass


# CONTRACT-NOTE: §7 names "faster-whisper (large-v3-turbo)" but no compute-type /
# device knobs — these defaults are local to this unit and overridable via the
# loader seam (and the CPU-fallback path) so a CUDA-less box still works.
DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_DEVICE = "cuda"
DEFAULT_GPU_COMPUTE = "float16"
CPU_DEVICE = "cpu"
CPU_COMPUTE = "int8"

# Type aliases matching CONTRACTS.md §3 (plain JSON-able dicts both sides).
Word = dict[str, Any]
Segment = dict[str, Any]
Transcript = dict[str, Any]

# A cooperative cancel probe (returns True once cancellation is requested).
CancelProbe = Callable[[], bool]
# A progress sink: (pct 0..100, message) -> None.
ProgressCb = Callable[[float, str], None]


class WhisperModel(Protocol):
    """The slice of faster-whisper's ``WhisperModel`` API this wrapper uses.

    ``transcribe`` returns ``(segments_iterable, info)`` where ``info`` carries
    ``language`` + ``duration`` and each segment carries ``start/end/text`` and
    (with ``word_timestamps=True``) a ``words`` list of objects with
    ``word/start/end``.
    """

    def transcribe(self, audio: str, **kwargs: Any) -> Any: ...  # pragma: no cover


class WhisperLoader(Protocol):
    """Seam that constructs a :class:`WhisperModel`.

    Injected in tests so no model is ever downloaded. The default production
    loader (:class:`FasterWhisperLoader`) imports ``faster_whisper`` lazily.
    """

    def load(self, model: str, device: str, compute_type: str) -> WhisperModel: ...  # pragma: no cover


class FasterWhisperLoader:
    """Default loader: lazily imports ``faster_whisper`` and builds a model.

    The import lives *inside* :meth:`load` (not at module scope) so importing
    this feature module never pulls in faster-whisper / its native deps. The
    constructed model is cached per (model, device, compute_type) so a job that
    transcribes after a device fallback does not rebuild needlessly.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, WhisperModel] = {}

    def load(self, model: str, device: str, compute_type: str) -> WhisperModel:
        key = (model, device, compute_type)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        _register_cuda_dll_dirs()
        # Local import keeps the seam mockable and the module import-light.
        from faster_whisper import WhisperModel as _WhisperModel  # type: ignore

        built = _WhisperModel(model, device=device, compute_type=compute_type)
        self._cache[key] = built
        return built

    def release(self) -> None:
        """Drop cached models so the single-heavy-model budget is freed (§7)."""
        self._cache.clear()


def load_model_with_cpu_fallback(
    loader: WhisperLoader,
    *,
    model: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_GPU_COMPUTE,
) -> tuple[WhisperModel, str]:
    """Load ``model`` on ``device``; fall back to CPU/int8 on any failure.

    Returns ``(model_instance, device_used)``. If the requested device is
    already ``cpu`` the fallback is skipped (a CPU failure is a hard error, since
    there is nothing further to fall back to).
    """
    try:
        return loader.load(model, device, compute_type), device
    except Exception as exc:  # noqa: BLE001 - any GPU/runtime error -> CPU fallback
        if device == CPU_DEVICE:
            raise
        log.warning(
            "whisper load on %s failed (%s); falling back to CPU/%s",
            device,
            exc,
            CPU_COMPUTE,
        )
        return loader.load(model, CPU_DEVICE, CPU_COMPUTE), CPU_DEVICE


def _word_to_dict(word: Any) -> Word:
    """Normalize a faster-whisper word object/dict into a §3 ``Word``.

    faster-whisper words expose ``word`` (with a leading space), ``start``,
    ``end``. We map ``word`` -> ``text`` (preserving the text verbatim) and coerce
    the times to floats.
    """
    text = _attr(word, "word", "text")
    start = _attr(word, "start")
    end = _attr(word, "end")
    return {
        "text": "" if text is None else str(text),
        "start": float(start or 0.0),
        "end": float(end or 0.0),
    }


def _segment_to_dict(seg: Any) -> Segment:
    """Normalize a faster-whisper segment object/dict into a §3 ``Segment``."""
    raw_words = _attr(seg, "words") or []
    words: list[Word] = [_word_to_dict(w) for w in raw_words]
    return {
        "start": float(_attr(seg, "start") or 0.0),
        "end": float(_attr(seg, "end") or 0.0),
        "text": str(_attr(seg, "text") or ""),
        "words": words,
    }


def _attr(obj: Any, *names: str) -> Any:
    """Read the first present attribute/key from ``names`` (object OR dict).

    faster-whisper yields namedtuple-like objects; tests may pass plain dicts.
    This tolerates both so the normalizers stay test-friendly.
    """
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return None


def transcribe_file(
    audio_path: str,
    *,
    loader: WhisperLoader,
    language: str | None = None,
    model: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_GPU_COMPUTE,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> Transcript:
    """Transcribe ``audio_path`` into a §3 :class:`Transcript`.

    ``loader`` is the (injected/mocked) model loader seam — never imported here.
    When ``language`` is ``None`` the model auto-detects it; the detected code is
    returned in ``Transcript.language``.

    Progress is reported against the media duration that faster-whisper exposes
    on its ``info`` object: as each segment's ``end`` advances we map it to a
    0..100 percentage. ``should_cancel`` is polled per segment so a cancelled job
    stops consuming the (lazy) segment generator promptly.

    CONTRACT-NOTE: faster-whisper's ``transcribe`` returns a *lazy generator* of
    segments; work only happens as we iterate. That is what makes per-segment
    progress + cooperative cancellation possible.
    """
    whisper_model, device_used = load_model_with_cpu_fallback(
        loader, model=model, device=device, compute_type=compute_type
    )
    log.info("transcribing %s on %s (lang=%s)", audio_path, device_used, language or "auto")

    segments_iter, info = whisper_model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
    )

    duration = float(_attr(info, "duration") or 0.0)
    detected_language = _attr(info, "language") or language or ""

    if on_progress is not None:
        on_progress(0.0, "transcribing")

    segments: list[Segment] = []
    for seg in segments_iter:
        if should_cancel is not None and should_cancel():
            log.info("transcription cancelled after %d segment(s)", len(segments))
            break
        norm = _segment_to_dict(seg)
        segments.append(norm)
        if on_progress is not None and duration > 0.0:
            pct = clamp((norm["end"] / duration) * 100.0, 0.0, 99.0)
            on_progress(pct, f"segment {len(segments)}")

    if on_progress is not None:
        on_progress(100.0, "done")

    return {
        "language": str(detected_language),
        "segments": segments,
        "durationSec": duration,
    }


# --------------------------------------------------------------------------- #
# Job handler + RPC registration (transcribe.start, §2)
# --------------------------------------------------------------------------- #

# A video-path resolver: (videoId) -> absolute media path (or None if unknown).
VideoResolver = Callable[[str], str | None]
# A "mark transcribed" hook: (videoId) -> None, called once a transcript exists.
TranscribedHook = Callable[[str], None]


def make_transcribe_handler(
    resolve_video: VideoResolver,
    *,
    loader: WhisperLoader | None = None,
    on_transcribed: TranscribedHook | None = None,
):
    """Build the ``transcribe.start`` RPC handler.

    ``resolve_video`` maps a ``videoId`` to its media path (the library owns the
    mapping; we depend only on this callable so this unit stays decoupled).
    ``loader`` defaults to the real :class:`FasterWhisperLoader` but is injected
    in tests. ``on_transcribed`` (optional) lets the library flip
    ``hasTranscript`` once a transcript is produced.

    The returned handler matches the §2 long-job shape: it creates a job on
    ``ctx.jobs``, returns ``{jobId}`` immediately, streams ``job.progress``, and
    its ``job.done.result`` is ``{transcript}``.
    """
    active_loader: WhisperLoader = loader if loader is not None else FasterWhisperLoader()

    def handler(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
        from ..protocol import ErrorCode, RpcError  # local import: no cycle at import time

        video_id = params.get("videoId")
        if not isinstance(video_id, str) or not video_id:
            raise RpcError("videoId (str) is required", ErrorCode.INVALID_PARAMS)
        language = params.get("language")
        if language is not None and not isinstance(language, str):
            raise RpcError("language must be a string when given", ErrorCode.INVALID_PARAMS)
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)

        audio_path = resolve_video(video_id)
        if not audio_path:
            raise RpcError(f"unknown video: {video_id}", ErrorCode.INVALID_PARAMS)

        def job_body(job_ctx: Any) -> dict[str, Any]:
            transcript = transcribe_file(
                audio_path,
                loader=active_loader,
                language=language,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            if on_transcribed is not None:
                try:
                    on_transcribed(video_id)
                except Exception:  # noqa: BLE001 - flag bookkeeping must not fail the job
                    log.warning("on_transcribed hook failed for %s", video_id)
            # §2: job.done.result == {transcript}
            return {"transcript": transcript}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    return handler


def register(
    resolve_video: VideoResolver,
    *,
    loader: WhisperLoader | None = None,
    on_transcribed: TranscribedHook | None = None,
) -> None:
    """Register ``transcribe.start`` on the shared METHODS registry (§2).

    Called by the sidecar assembly (which owns the library + loader lifecycle)
    after wiring the video resolver. Kept out of import side effects so importing
    this module never registers a half-wired handler.
    """
    from .. import protocol  # local import keeps module import-light / cycle-free

    protocol.register(
        "transcribe.start",
        make_transcribe_handler(resolve_video, loader=loader, on_transcribed=on_transcribed),
    )
