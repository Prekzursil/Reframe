"""Parakeet-TDT-0.6b-v3 multilingual ASR seam (WU7).

A **drop-in alternative ASR engine** to ``transcribe.FasterWhisperLoader``:
NVIDIA's ``parakeet-tdt-0.6b-v3`` (CC-BY-4.0, 25 European languages incl.
Romanian) produces the **exact same** ``Transcript`` schema (CONTRACTS.md §3)
that :mod:`transcribe` emits, so the handler can pick the ASR engine by
``settings["asrEngine"]`` (``"whisper"`` | ``"parakeet"``) with no downstream
change.

The heavy ``nemo_toolkit['asr']`` / ``torch`` import is deferred behind a
*loader seam* (:class:`ParakeetLoader`) — mirroring :class:`WhisperLoader` — so
this module (and its tests) never import NeMo at import time. Tests inject a
fake loader/model; the real loader (:class:`RealParakeetLoader`) lives in the
sibling :mod:`parakeet_asr_backend` and is constructed lazily only when no
loader is given.

Two hard rules from the SOTA manifest:

* **Audio CHUNKING.** Parakeet's full-context long-attention decode wants an
  A100-80GB; on a 6 GB card it OOMs. So audio is segmented into
  :data:`CHUNK_SEC`-long spans (:func:`chunk_audio_spans`), each transcribed
  independently, then re-stitched with the per-chunk offset folded back into
  every segment/word time (:func:`merge_chunk_transcripts`).
* **CPU fallback.** Like whisper, GPU load failure falls back to CPU
  (OpenVINO/ONNX export) via :func:`load_model_with_cpu_fallback`.

Lifecycle is **load-use-free, one heavy model at a time** (CONTRACTS.md §7).
Offline + weights-missing degrades to an EMPTY transcript (the caller's
whisper-turbo fallback path takes over) — it never raises.

Pure stdlib at import time — no heavy-ML imports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ..util import clamp, get_logger
from . import offline as _offline
from .transcribe import GPU_FALLBACK_NOTICE

log = get_logger("media_studio.features.parakeet_asr")

# CONTRACT-NOTE: manifest #10 pins ``nvidia/parakeet-tdt-0.6b-v3`` (CC-BY-4.0,
# README commit 575de92). Defaults are local to this unit + overridable via the
# loader seam / settings (so a CUDA-less box still works through CPU fallback).
DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v3"
#: asset name the manager looks up (matches the Wave-2 manifest entry +
#: ``system_advisor.ComponentSpec`` key).
ASSET_NAME = "parakeet-tdt-0.6b-v3"
DEFAULT_DEVICE = "cuda"
DEFAULT_GPU_COMPUTE = "float16"
CPU_DEVICE = "cpu"
CPU_COMPUTE = "int8"
#: audio is chunked into spans this many seconds long so each decode fits 6 GB
#: VRAM (full-context wants 80 GB). 300 s ≈ 5 min — comfortably under the limit.
CHUNK_SEC = 300.0

# Type aliases matching CONTRACTS.md §3 (plain JSON-able dicts both sides).
Word = dict[str, Any]
Segment = dict[str, Any]
Transcript = dict[str, Any]

# A cooperative cancel probe (returns True once cancellation is requested).
CancelProbe = Callable[[], bool]
# A progress sink: (pct 0..100, message) -> None.
ProgressCb = Callable[[float, str], None]
# F3b: a one-shot notice sink invoked when a GPU load falls back to CPU.
FallbackNotice = Callable[[str], None]
#: are the model weights installed? (drives the offline degrade).
ModelsPresent = Callable[[dict[str, Any]], bool]


class ParakeetModel(Protocol):
    """The slice of NeMo's ASR model API this wrapper uses.

    ``transcribe`` accepts an audio path (and optional ``offset`` so a chunk's
    absolute start can be folded in, plus a ``language`` hint) and returns an
    iterable of segment-like objects each carrying ``start/end/text`` and
    (optionally) a ``words`` list of objects with ``word/start/end`` —
    structurally identical to faster-whisper segments so the same normalizers
    apply.
    """

    def transcribe(self, audio: str, **kwargs: Any) -> Any: ...  # pragma: no cover - Protocol stub


class ParakeetLoader(Protocol):
    """Seam that constructs a :class:`ParakeetModel` (mirror of WhisperLoader).

    Injected in tests so no model is ever downloaded. The default production
    loader (:class:`RealParakeetLoader`, sibling backend module) imports
    ``nemo_toolkit`` lazily.
    """

    def load(self, model: str, device: str, compute_type: str) -> ParakeetModel: ...  # pragma: no cover - Protocol stub


def _default_loader() -> ParakeetLoader:  # pragma: no cover - prod seam (imports the heavy native stack)
    """Build the real NeMo Parakeet loader (LAZY import inside the function)."""
    from .parakeet_asr_backend import RealParakeetLoader  # noqa: PLC0415 - heavy seam

    return RealParakeetLoader()


def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the Parakeet weights are installed (no heavy import).

    Looks the asset up via the asset manager so an already-cached snapshot
    counts — that is what lets the model run offline. Any lookup failure (asset
    not yet registered in Wave-1/2) degrades to ``False`` (use the whisper
    fallback), never raises.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415 - lazy: avoids a cycle
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        if entry is None:  # pragma: no cover - asset is registered at import (Integrate phase)
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - missing asset machinery -> use whisper fallback  # pragma: no cover - defensive
        return False  # pragma: no cover - defensive


def load_model_with_cpu_fallback(
    loader: ParakeetLoader,
    *,
    model: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_GPU_COMPUTE,
    on_fallback: FallbackNotice | None = None,
) -> tuple[ParakeetModel, str]:
    """Load ``model`` on ``device``; fall back to CPU (OpenVINO/ONNX) on failure.

    Returns ``(model_instance, device_used)``. If the requested device is
    already ``cpu`` the fallback is skipped (a CPU failure is a hard error,
    since there is nothing further to fall back to). Mirrors
    ``transcribe.load_model_with_cpu_fallback`` — incl. the F3b ``on_fallback``
    notice (:data:`GPU_FALLBACK_NOTICE`) fired when a GPU load degrades to CPU.
    """
    try:
        return loader.load(model, device, compute_type), device
    except Exception as exc:  # noqa: BLE001 - any GPU/runtime error -> CPU fallback
        if device == CPU_DEVICE:
            raise
        log.warning(
            "parakeet load on %s failed (%s); falling back to CPU/%s",
            device,
            exc,
            CPU_COMPUTE,
        )
        if on_fallback is not None:
            on_fallback(GPU_FALLBACK_NOTICE)
        return loader.load(model, CPU_DEVICE, CPU_COMPUTE), CPU_DEVICE


# --------------------------------------------------------------------------- #
# Pure: audio chunking + segment merge
# --------------------------------------------------------------------------- #
def chunk_audio_spans(duration: float, chunk_sec: float = CHUNK_SEC) -> tuple[tuple[float, float], ...]:
    """Split ``[0, duration)`` into ``chunk_sec``-long ``(start, end)`` spans.

    The hard 6 GB rule: each span is decoded independently so the model never
    sees the full-context audio. The final span is clamped to ``duration``. A
    non-positive duration yields no spans; a duration shorter than one chunk
    yields a single span.
    """
    if chunk_sec <= 0.0:
        raise ValueError(f"chunk_sec must be positive, got {chunk_sec}")
    d = max(0.0, float(duration))
    if d <= 0.0:
        return ()
    spans: list[tuple[float, float]] = []
    start = 0.0
    while start < d - 1e-9:
        end = min(start + chunk_sec, d)
        spans.append((round(start, 3), round(end, 3)))
        start += chunk_sec
    return tuple(spans)


def _shift_word(word: Word, offset: float) -> Word:
    """Return a copy of ``word`` with its times shifted by ``offset`` seconds."""
    return {
        "text": str(word.get("text", "")),
        "start": round(float(word.get("start", 0.0)) + offset, 3),
        "end": round(float(word.get("end", 0.0)) + offset, 3),
    }


def _shift_segment(seg: Segment, offset: float) -> Segment:
    """Return a copy of ``seg`` (and its words) shifted by ``offset`` seconds."""
    words = [_shift_word(w, offset) for w in seg.get("words", [])]
    return {
        "start": round(float(seg.get("start", 0.0)) + offset, 3),
        "end": round(float(seg.get("end", 0.0)) + offset, 3),
        "text": str(seg.get("text", "")),
        "words": words,
    }


def merge_chunk_transcripts(
    parts: Sequence[tuple[float, Transcript]],
) -> Transcript:
    """Stitch per-chunk ``(offset, Transcript)`` parts into one §3 Transcript.

    Each chunk transcribed from ``chunk_audio_spans`` reports times **relative
    to the chunk start**; ``offset`` is that chunk's absolute start, folded back
    into every segment + word so the merged timeline is absolute. The language
    is taken from the first part that reports a non-empty one (chunks of the same
    media share a language); ``durationSec`` is the max chunk end (the absolute
    end of the last span). An empty ``parts`` yields an empty transcript.
    """
    segments: list[Segment] = []
    language = ""
    duration = 0.0
    for offset, part in parts:
        if not language:
            language = str(part.get("language", "") or "")
        for seg in part.get("segments", []):
            segments.append(_shift_segment(seg, float(offset)))
        part_dur = float(part.get("durationSec", 0.0) or 0.0)
        duration = max(duration, float(offset) + part_dur)
    return {
        "language": language,
        "segments": segments,
        "durationSec": round(duration, 3),
    }


def _attr(obj: Any, *names: str) -> Any:
    """Read the first present attribute/key from ``names`` (object OR dict).

    NeMo may yield namedtuple-like objects; tests pass plain dicts. Tolerates
    both so the normalizers stay test-friendly (mirrors ``transcribe._attr``).
    """
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return None


def _word_to_dict(word: Any) -> Word:
    """Normalize a backend word object/dict into a §3 ``Word``."""
    text = _attr(word, "word", "text")
    start = _attr(word, "start")
    end = _attr(word, "end")
    return {
        "text": "" if text is None else str(text),
        "start": float(start or 0.0),
        "end": float(end or 0.0),
    }


def _segment_to_dict(seg: Any) -> Segment:
    """Normalize a backend segment object/dict into a §3 ``Segment``."""
    raw_words = _attr(seg, "words") or []
    words: list[Word] = [_word_to_dict(w) for w in raw_words]
    return {
        "start": float(_attr(seg, "start") or 0.0),
        "end": float(_attr(seg, "end") or 0.0),
        "text": str(_attr(seg, "text") or ""),
        "words": words,
    }


def _transcribe_chunk(
    model: ParakeetModel,
    audio_path: str,
    span: tuple[float, float],
    *,
    language: str | None,
) -> Transcript:
    """Transcribe ONE chunk span (times relative to the chunk start).

    The backend is handed the ``offset``/``duration`` of the span so it can
    decode only that window; the returned segments are chunk-relative and folded
    to absolute by :func:`merge_chunk_transcripts`.
    """
    start, end = span
    raw = model.transcribe(
        audio_path,
        language=language,
        offset=start,
        duration=round(end - start, 3),
        word_timestamps=True,
    )
    segments_iter = _attr(raw, "segments")
    info = _attr(raw, "info")
    if segments_iter is None:
        # The backend returned a bare iterable of segments (the simple shape).
        segments_iter = raw
    segments = [_segment_to_dict(seg) for seg in segments_iter]
    detected = _attr(info, "language") if info is not None else None
    return {
        "language": str(detected or language or ""),
        "segments": segments,
        "durationSec": round(end - start, 3),
    }


# --------------------------------------------------------------------------- #
# Public runner — sibling of transcribe.transcribe_file (§3 shape)
# --------------------------------------------------------------------------- #
def transcribe_file(
    audio_path: str,
    *,
    loader: ParakeetLoader | None = None,
    language: str | None = None,
    model: str = DEFAULT_MODEL,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_GPU_COMPUTE,
    chunk_sec: float = CHUNK_SEC,
    duration: float | None = None,
    duration_probe: Callable[[str], float] | None = None,
    settings: dict[str, Any] | None = None,
    models_present: ModelsPresent | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> Transcript:
    """Transcribe ``audio_path`` into a §3 :class:`Transcript` via Parakeet.

    A drop-in sibling of ``transcribe.transcribe_file`` (same return schema) so
    the handler can swap ASR engines by settings. Behaviour:

    1. **Offline + weights missing** -> return an EMPTY transcript so the
       caller's whisper-turbo fallback takes over (degrade, never raise).
    2. Load the model with CPU fallback, resolve the media ``duration`` (passed
       in, or via ``duration_probe``), chunk it into :data:`CHUNK_SEC` spans
       (the hard 6 GB rule), transcribe each chunk, and merge with absolute
       offsets.
    3. Per-chunk progress + cooperative cancellation: ``should_cancel`` is
       polled before each chunk so a cancelled job stops promptly with whatever
       chunks completed.

    ``loader`` is the injected/mocked seam; the real loader is built lazily only
    when ``loader is None`` (and never imported at module load).
    """
    settings = settings or {}
    present = models_present or default_models_present
    have_model = present(settings)

    if not have_model and _offline.is_offline(settings):
        log.info("parakeet: weights unavailable offline; degrading to empty (whisper fallback)")
        return {"language": str(language or ""), "segments": [], "durationSec": 0.0}

    active_loader = loader if loader is not None else _default_loader()
    notify = (lambda msg: on_progress(0.0, msg)) if on_progress is not None else None
    parakeet_model, device_used = load_model_with_cpu_fallback(
        active_loader, model=model, device=device, compute_type=compute_type, on_fallback=notify
    )
    media_duration = _resolve_duration(audio_path, duration, duration_probe)
    log.info(
        "parakeet: transcribing %s on %s (lang=%s, dur=%.1fs)",
        audio_path,
        device_used,
        language or "auto",
        media_duration,
    )

    spans = chunk_audio_spans(media_duration, chunk_sec)
    if on_progress is not None:
        on_progress(0.0, "transcribing")

    parts: list[tuple[float, Transcript]] = []
    total = len(spans)
    for idx, span in enumerate(spans):
        if should_cancel is not None and should_cancel():
            log.info("parakeet: cancelled after %d/%d chunk(s)", idx, total)
            break
        chunk = _transcribe_chunk(parakeet_model, audio_path, span, language=language)
        parts.append((span[0], chunk))
        if on_progress is not None and total > 0:
            pct = clamp(((idx + 1) / total) * 100.0, 0.0, 99.0)
            on_progress(pct, f"chunk {idx + 1}/{total}")

    merged = merge_chunk_transcripts(parts)
    if not merged["language"] and language:
        merged["language"] = str(language)
    if on_progress is not None:
        on_progress(100.0, "done")
    return merged


def _resolve_duration(
    audio_path: str,
    duration: float | None,
    duration_probe: Callable[[str], float] | None,
) -> float:
    """Resolve the media duration: explicit value, then probe, else 0.0.

    A 0.0 duration yields no chunk spans (an empty transcript) rather than
    raising — the caller's fallback still applies. The probe seam keeps ffmpeg
    out of this module's import path (tests inject a fake probe).
    """
    if duration is not None and duration > 0.0:
        return float(duration)
    if duration_probe is not None:
        try:
            probed = float(duration_probe(audio_path))
        except Exception as exc:  # noqa: BLE001 - a probe failure -> degrade to 0
            log.warning("parakeet: duration probe failed for %s: %s", audio_path, exc)
            return 0.0
        return max(0.0, probed)
    return 0.0


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / ctc_align / pyannote_backend)
# --------------------------------------------------------------------------- #
#: pinned revision per the SOTA manifest (#10): README commit 575de92.
ASSET_REVISION = "575de92"
ASSET_SIZE_MB = 2400


def register_parakeet_assets() -> None:
    """Register the Parakeet-TDT-0.6b-v3 weights as an on-demand asset (idempotent).

    CC-BY-4.0 (commercial OK with attribution), ungated, ~2.4 GB. The asset name
    matches :data:`ASSET_NAME` (and ``system_advisor.ComponentSpec``'s lookup key)
    so ``default_models_present`` can detect an already-cached snapshot. Identical
    re-registration is a no-op (module re-import safe).
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=ASSET_SIZE_MB,
            label="Parakeet-TDT-0.6b-v3 (multilingual ASR, CC-BY-4.0)",
            installer="hf",
            hf_repo=DEFAULT_MODEL,
            hf_revision=ASSET_REVISION,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_parakeet_assets()


__all__ = [
    "ASSET_NAME",
    "ASSET_REVISION",
    "ASSET_SIZE_MB",
    "CHUNK_SEC",
    "CPU_COMPUTE",
    "CPU_DEVICE",
    "DEFAULT_DEVICE",
    "DEFAULT_GPU_COMPUTE",
    "DEFAULT_MODEL",
    "GPU_FALLBACK_NOTICE",
    "ParakeetLoader",
    "ParakeetModel",
    "chunk_audio_spans",
    "default_models_present",
    "load_model_with_cpu_fallback",
    "merge_chunk_transcripts",
    "register_parakeet_assets",
    "transcribe_file",
]
