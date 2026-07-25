"""STUDIO-SOUND speech enhancement (the absent Descript "Studio Sound").

Cleans a clip's spoken audio — neural denoise + dereverb — then optionally lands
it at a broadcast/social loudness target, and muxes the enhanced track back into
the container. The enhancement engine is **ClearerVoice-Studio** (Alibaba
Speech Lab, **Apache-2.0**), whose ``MossFormer2_SE_48K`` speech-enhancement model
is the default (48 kHz, full-band). The whole heavy half lives behind the
:class:`ClearerVoiceBackend` seam; the PURE half — the ffmpeg extract / mux argv
builders and the orchestration/degrade branches — is unit-testable with a fake
``run`` and a fake backend (no model, no real ffmpeg), mirroring ``audiomix`` /
``silencetrim``.

Pipeline (``clearervoice.enhance``)::

    extract mono wav @ model SR  ->  neural enhance (MossFormer2_SE)
      ->  mux enhanced audio back over the clip video
      ->  [optional] EBU R128 loudnorm finishing pass (audiomix seam)

Wire surface (NET-NEW)::

    clearervoice.enhance({videoId|path, modelId?, finishLoudnorm?, loudnessTarget?,
                          platform?}) -> {jobId} -> {path, enhanced}

Missing-modality / degrade contract (mirrors ``silencetrim``): offline AND the
model asset missing, an absent :data:`BACKEND_MODULE` (the heavy sibling is not
part of every build), an extract/mux ffmpeg failure, or ANY backend failure ->
the ORIGINAL clip path is returned with ``enhanced=False`` and a LOUD ``on_notice``
message (surfaced via ``job.progress``) — the audio is never silently degraded,
the skip is never swallowed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .. import ffmpeg, protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import audiomix as _audiomix

if TYPE_CHECKING:
    import numpy as np  # noqa: F401 - typing only

log = get_logger("media_studio.features.clearervoice")

# Injectable seams (mirror the sibling features):
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
Resolver = Callable[[str], str | None]
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]

#: LOUD notice when studio-sound is skipped (vs a genuine pass-through).
STUDIO_SOUND_UNAVAILABLE_NOTICE = "clearervoice.unavailable"

#: the default enhancement model (Apache-2.0, 48 kHz full-band). Real HF pin (2026-07-12).
DEFAULT_MODEL_ID = "MossFormer2_SE_48K"
DEFAULT_MODEL_HF_REPO = "alibabasglab/MossFormer2_SE_48K"
DEFAULT_MODEL_REVISION = "eff8c97925c8bec812af707814b3e5d777fd4503"
ASSET_NAME = "clearervoice-mossformer2-se-48k"
STUDIO_SOUND_SIZE_MB = 220

#: model id -> the sample-rate its checkpoint expects (the extract SR).
MODEL_SAMPLE_RATE: dict[str, int] = {
    "MossFormer2_SE_48K": 48000,
    "MossFormerGAN_SE_16K": 16000,
    "FRCRN_SE_16K": 16000,
}
DEFAULT_SR = 48000

#: a notice sink mirroring silencetrim's ({type, message, reason}).
NoticeSink = Callable[[dict[str, str]], None]


class StudioSoundError(RuntimeError):
    """Raised when a REQUIRED studio-sound ffmpeg pass fails (extract/mux)."""


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _float(params: dict[str, Any], key: str, default: float) -> float:
    """Coerce an optional numeric param to float (default on absent/garbage)."""
    value = params.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def make_unavailable_notice(reason: str) -> dict[str, str]:
    """Build the typed notice emitted when studio-sound is skipped."""
    return {
        "type": STUDIO_SOUND_UNAVAILABLE_NOTICE,
        "message": f"studio-sound skipped: {reason}; the original audio was kept",
        "reason": reason,
    }


def _notify(on_notice: NoticeSink | None, reason: str) -> None:
    if on_notice is not None:
        on_notice(make_unavailable_notice(reason))


def resolve_model_sr(model_id: str) -> int:
    """The sample rate a model checkpoint expects (default :data:`DEFAULT_SR`)."""
    return MODEL_SAMPLE_RATE.get(model_id, DEFAULT_SR)


# --------------------------------------------------------------------------- #
# the heavy backend seam (ClearerVoice-Studio) — never imported at module load
# --------------------------------------------------------------------------- #
class ClearerVoiceBackend(Protocol):
    """The slice of ClearerVoice-Studio the pipeline needs.

    A real impl (built lazily by :func:`_default_backend_factory`, never at
    import) reads ``in_wav`` (mono, model SR), runs the SE model, and writes the
    enhanced mono wav to ``out_wav``. Tests inject a fake that no-ops (or copies)
    — no model, no torch.
    """

    def enhance(
        self,
        in_wav: str,
        out_wav: str,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> None:
        """Enhance ``in_wav`` -> write the cleaned mono wav to ``out_wav``."""
        ...  # pragma: no cover - Protocol method body is never executed


BackendFactory = Callable[[dict[str, Any], str], ClearerVoiceBackend]
ModelsPresent = Callable[[dict[str, Any], str], bool]
#: ``importlib.util.find_spec`` seam: module name -> spec | ``None`` (no import).
SpecFn = Callable[[str], object | None]

#: the sibling module that ships the REAL ClearerVoice-Studio SE engine. It is
#: NOT part of the pure build: when it is absent studio-sound is UNAVAILABLE and
#: :func:`enhance_clip` degrades to the original audio with a LOUD notice.
BACKEND_MODULE = "media_studio.features.clearervoice_backend"


class ClearerVoiceBackendUnavailableError(RuntimeError):
    """:data:`BACKEND_MODULE` (the real ClearerVoice SE engine) is not importable.

    A SETUP/PROVISIONING failure, NOT a per-clip event: without that module no
    speech enhancement can run at all. Raised TYPED and actionable — mirroring
    ``diarize_backend.DiarizeBackendUnavailableError`` — so :func:`enhance_clip`
    degrades on a NAMED cause (surfaced through :func:`make_unavailable_notice`)
    instead of a raw :class:`ModuleNotFoundError` escaping a job thread.
    """


def _default_find_spec(module_name: str) -> object | None:
    """Lazy ``importlib.util.find_spec`` (kept behind a seam for testing)."""
    import importlib.util  # noqa: PLC0415 - stdlib, lazy for symmetry with peers

    return importlib.util.find_spec(module_name)


def backend_available(*, find_spec: SpecFn | None = None) -> bool:
    """True when :data:`BACKEND_MODULE` is IMPORTABLE — WITHOUT importing it.

    Uses ``importlib.util.find_spec`` behind an injectable seam (mirroring
    ``health`` / ``self_test`` / ``system_advisor``) so answering "can this
    feature run at all?" never loads a heavy dependency. A probe failure (a
    broken / partial install) reports ABSENT — the honest answer for a feature
    that cannot run.
    """
    spec_fn = find_spec or _default_find_spec
    try:
        return spec_fn(BACKEND_MODULE) is not None
    except (ImportError, ValueError):  # a broken/partial install probes as absent
        return False


# --------------------------------------------------------------------------- #
# pure: the ffmpeg argv builders (extract mono wav / mux enhanced audio)
# --------------------------------------------------------------------------- #
def build_extract_wav_argv(
    in_path: str,
    wav_path: str,
    *,
    sr: int = DEFAULT_SR,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv to extract ``in_path``'s audio as a mono ``sr``-Hz 16-bit wav.

    The SE model input: one mono channel at the checkpoint's rate (48 kHz for
    MossFormer2_SE_48K). argv LIST only (never ``shell=True``).
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(int(sr)),
        "-c:a",
        "pcm_s16le",
        "-progress",
        "pipe:1",
        "-nostats",
        wav_path,
    ]


def build_mux_argv(
    video_path: str,
    enhanced_wav: str,
    out_path: str,
    *,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv to replace ``video_path``'s audio with ``enhanced_wav`` -> ``out_path``.

    The video is stream-copied (``-map 0:v``, ``-c:v copy``); only the audio is
    taken from the enhanced wav and encoded to AAC. ``-shortest`` keeps the output
    aligned to the (unchanged) video duration.
    """
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        video_path,
        "-i",
        enhanced_wav,
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def _default_backend_factory(
    settings: dict[str, Any],
    model_id: str,
) -> ClearerVoiceBackend:  # pragma: no cover - prod seam (imports the heavy SE stack)
    """Build the real ClearerVoice backend (LAZY import; runtime only).

    Raises :class:`ClearerVoiceBackendUnavailableError` when
    :data:`BACKEND_MODULE` is not part of this build — never a raw
    :class:`ModuleNotFoundError`.
    """
    try:
        from .clearervoice_backend import RealClearerVoiceBackend  # noqa: PLC0415 - heavy seam
    except ImportError as exc:
        raise ClearerVoiceBackendUnavailableError(
            f"studio-sound requires the {BACKEND_MODULE} module (the ClearerVoice-Studio "
            "speech-enhancement engine), which is not part of this build; speech "
            "enhancement is UNAVAILABLE and the original audio is kept"
        ) from exc

    return RealClearerVoiceBackend(settings, model_id)


def default_models_present(
    settings: dict[str, Any],
    model_id: str,
) -> bool:  # pragma: no cover - probes the asset store at runtime
    """True when the ClearerVoice backend module AND its asset are BOTH installed.

    An installed checkpoint alone is NOT enough: without :data:`BACKEND_MODULE`
    the SE engine can never run, so a missing backend module reports ABSENT — the
    UI then shows studio-sound as unavailable instead of appearing ready.
    """
    if not backend_available():
        return False
    try:
        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - any probe failure -> treat as absent
        return False


# --------------------------------------------------------------------------- #
# the pipeline orchestrator (extract -> enhance -> mux -> [loudnorm])
# --------------------------------------------------------------------------- #
def enhance_clip(
    in_path: str,
    out_path: str,
    tmp_wav: str,
    enhanced_wav: str,
    *,
    settings: dict[str, Any] | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    backend_factory: BackendFactory | None = None,
    models_present: ModelsPresent | None = None,
    model_id: str | None = None,
    finish_loudnorm: bool = False,
    loudness_target: float = _audiomix.DEFAULT_LOUDNESS_TARGET,
    on_notice: NoticeSink | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> tuple[str, bool]:
    """Studio-sound ``in_path`` -> ``out_path``; return ``(path, enhanced)``.

    Extracts a mono wav, runs the SE backend, muxes the cleaned audio back, and
    (when ``finish_loudnorm``) applies an EBU R128 loudnorm pass. On any degrade
    (offline+model-missing, an ffmpeg extract/mux failure, or a backend failure)
    the ORIGINAL ``in_path`` is returned with ``enhanced=False`` and a LOUD
    ``on_notice`` — the audio is never silently corrupted. Raises
    :class:`StudioSoundError` only when configured to fail hard is NOT the case:
    here a REQUIRED-stage ffmpeg non-zero exit degrades (notice + passthrough).
    """
    from . import offline as _offline  # noqa: PLC0415 - avoid a heavy import at module load

    settings = settings or {}
    run = run or ffmpeg.run
    duration = duration or ffmpeg.ffprobe_duration
    factory = backend_factory or _default_backend_factory
    present_probe = models_present or default_models_present
    resolved_model = model_id or str(settings.get("studioSoundModelId") or "") or DEFAULT_MODEL_ID
    sr = resolve_model_sr(resolved_model)

    def _progress(pct: float, msg: str) -> None:
        if on_progress is not None:
            on_progress(max(0.0, min(100.0, pct)), msg)

    if not present_probe(settings, resolved_model) and _offline.is_offline(settings):
        log.info("clearervoice: offline + model %s missing — passthrough", resolved_model)
        _notify(on_notice, f"offline and the {resolved_model} model is not installed")
        return in_path, False

    try:
        total = float(duration(in_path, settings))
    except Exception:  # noqa: BLE001 - a probe failure only coarsens progress
        total = 0.0

    _progress(5.0, "extracting audio")
    extract_argv = build_extract_wav_argv(in_path, tmp_wav, sr=sr, settings=settings)
    if run(extract_argv, total_sec=total) != 0:
        log.warning("clearervoice: wav extract failed for %s", in_path)
        _notify(on_notice, "audio extract (ffmpeg) failed")
        return in_path, False

    _progress(25.0, "enhancing speech (ClearerVoice)")
    try:
        backend = factory(settings, resolved_model)
        backend.enhance(
            tmp_wav,
            enhanced_wav,
            on_progress=lambda pct, msg: _progress(max(25.0, min(80.0, pct)), msg),
            should_cancel=should_cancel,
        )
    except Exception as exc:  # noqa: BLE001 - a backend failure must not crash the pipeline
        log.warning("clearervoice: enhancement failed for %s: %s", in_path, exc)
        _notify(on_notice, f"speech enhancement failed: {exc}")
        return in_path, False

    _progress(85.0, "muxing enhanced audio")
    mux_target = out_path if not finish_loudnorm else f"{out_path}.pre-loudnorm.mp4"
    mux_argv = build_mux_argv(in_path, enhanced_wav, mux_target, settings=settings)
    if run(mux_argv, total_sec=total) != 0:
        log.warning("clearervoice: mux failed for %s", in_path)
        _notify(on_notice, "audio mux (ffmpeg) failed")
        return in_path, False

    if finish_loudnorm:
        _progress(92.0, "loudness normalizing")
        ln_argv = _audiomix.build_loudnorm_argv(
            mux_target, out_path, loudness_target=loudness_target, settings=settings
        )
        if run(ln_argv, total_sec=total) != 0:
            log.warning("clearervoice: loudnorm finishing failed for %s — using un-normalized enhance", in_path)
            _notify(on_notice, "loudnorm finishing failed; kept the enhanced (un-normalized) audio")
            return mux_target, True

    _progress(100.0, "done")
    return out_path, True


# --------------------------------------------------------------------------- #
# the service (clearervoice.enhance -> a job)
# --------------------------------------------------------------------------- #
class StudioSound:
    """Owns the ``clearervoice.enhance`` RPC over the library/exports seams."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | os.PathLike,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
        backend_factory: BackendFactory | None = None,
        models_present: ModelsPresent | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._duration = duration
        self._backend_factory = backend_factory
        self._models_present = models_present

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, params: dict[str, Any]) -> str:
        path = params.get("path")
        if isinstance(path, str) and path:
            return path
        video_id = _require_str(params, "videoId")
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        return str(resolved)

    def enhance(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``clearervoice.enhance({videoId|path, modelId?, finishLoudnorm?, ...})``.

        -> ``{jobId}`` -> ``{path, enhanced}``. Cleans the clip's speech (denoise +
        dereverb) and muxes it back; an optional ``finishLoudnorm`` lands the
        export at ``loudnessTarget`` (or a ``platform`` preset). On any degrade the
        result's ``path`` is the source path and ``enhanced`` is ``False``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        model_id = params.get("modelId") if isinstance(params.get("modelId"), str) else None
        finish_loudnorm = bool(params.get("finishLoudnorm", False))
        settings = self._settings()
        loudness_target = _audiomix.DEFAULT_LOUDNESS_TARGET
        platform = params.get("platform")
        if platform is not None:
            loudness_target = _audiomix.resolve_loudness_target(platform)
        loudness_target = _float(params, "loudnessTarget", loudness_target)
        run = self._run
        duration = self._duration
        factory = self._backend_factory
        present = self._models_present
        out_dir = self._out_dir

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(in_path).stem or "clip"
            stamp = int(time.time())
            tmp_wav = str(out_dir / f"{stem}-{stamp}.src.wav")
            enhanced_wav = str(out_dir / f"{stem}-{stamp}.enhanced.wav")
            out_path = str(out_dir / f"{stem}-studio-{stamp}.mp4")
            path, enhanced = enhance_clip(
                in_path,
                out_path,
                tmp_wav,
                enhanced_wav,
                settings=settings,
                run=run,
                duration=duration,
                backend_factory=factory,
                models_present=present,
                model_id=model_id,
                finish_loudnorm=finish_loudnorm,
                loudness_target=loudness_target,
                on_notice=lambda notice: job_ctx.progress(50, notice["message"]),
                on_progress=lambda pct, msg: job_ctx.progress(int(pct), msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            return {"path": path, "enhanced": enhanced}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}


# --------------------------------------------------------------------------- #
# registration (called from handlers.register_all)
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    out_dir: str | os.PathLike,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    backend_factory: BackendFactory | None = None,
    models_present: ModelsPresent | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> StudioSound:
    """Create the service and register ``clearervoice.enhance`` (mirrors audiomix.register)."""
    service = StudioSound(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
        backend_factory=backend_factory,
        models_present=models_present,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("clearervoice.enhance", service.enhance)
    log.info("registered clearervoice.enhance")
    return service


def register_clearervoice_assets() -> None:
    """Register MossFormer2_SE_48K as an on-demand model asset (idempotent).

    ClearerVoice-Studio (Apache-2.0) full-band speech enhancement. Real pinned HF
    revision (F3c). Identical re-registration is a no-op.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=ASSET_NAME,
            kind="model",
            size_mb=STUDIO_SOUND_SIZE_MB,
            label="ClearerVoice MossFormer2_SE_48K (studio-sound speech enhancement, Apache-2.0)",
            tier="optional",
            why="Denoises + dereverbs spoken audio (the missing Descript 'Studio Sound').",
            installer="hf",
            hf_repo=DEFAULT_MODEL_HF_REPO,
            hf_revision=DEFAULT_MODEL_REVISION,
        )
    )


# Register the asset at import (mirrors ctc_align / vlm_backbone).
register_clearervoice_assets()


__all__ = [
    "ASSET_NAME",
    "BACKEND_MODULE",
    "DEFAULT_MODEL_HF_REPO",
    "DEFAULT_MODEL_ID",
    "DEFAULT_SR",
    "MODEL_SAMPLE_RATE",
    "STUDIO_SOUND_SIZE_MB",
    "STUDIO_SOUND_UNAVAILABLE_NOTICE",
    "BackendFactory",
    "ClearerVoiceBackend",
    "ClearerVoiceBackendUnavailableError",
    "ModelsPresent",
    "SpecFn",
    "StudioSound",
    "StudioSoundError",
    "backend_available",
    "build_extract_wav_argv",
    "build_mux_argv",
    "default_models_present",
    "enhance_clip",
    "make_unavailable_notice",
    "register",
    "register_clearervoice_assets",
    "resolve_model_sr",
]
