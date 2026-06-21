"""A/V merge with auto-DUCKING + EBU R128 LOUDNESS NORMALIZATION (``audiomix.merge``).

Mixes a music-bed / VO track UNDER a clip's own audio and writes a new container:

  1. **sidechain DUCK** — the bg bed is compressed by a ``sidechaincompress``
     keyed off the clip's (foreground) audio, so the bed automatically dips
     whenever the speaker talks and swells back in the gaps,
  2. **mix** — the (full-volume) foreground + the ducked bg are summed with
     ``amix`` (foreground stays dominant),
  3. **EBU R128 LOUDNORM** — the summed mix is run through ``loudnorm`` so the
     export hits a broadcast/social loudness target (default -14 LUFS, the
     YouTube/Spotify-ish integrated target).

Wire surface (NET-NEW)::

    audiomix.merge({videoId|path, bgPath, bgGainDb?, duckThreshold?, duckRatio?,
                    loudnessTarget?, loudnessTp?, loudnessLra?}) -> {jobId} -> {path}

The whole mix is one ffmpeg ``-filter_complex`` graph (two inputs: the clip and
the bg bed). The pure :func:`build_mix_argv` builds that graph; :class:`AudioMix`
runs it through the shared, drained :func:`media_studio.ffmpeg.run` seam.

CONTRACTS.md §4/§6/§7: argv-list subprocess only (never ``shell=True`` — the
filter graph + paths are single argv elements); the bundled/PATH ffmpeg resolved
by absolute path; both pipes drained by the shared ``run``. Everything heavy is
behind an injectable seam so the module is unit-testable with no real ffmpeg.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.audiomix")

# Injectable seams (mirror the sibling features):
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
Resolver = Callable[[str], str | None]

# --- mix tunables (sane defaults) -------------------------------------------
# How much to pre-attenuate the bg bed before ducking (negative dB = quieter).
DEFAULT_BG_GAIN_DB = -10.0
# sidechaincompress: the level the foreground must exceed to trigger ducking
# (0..1 linear) and the gain-reduction ratio applied when it does.
DEFAULT_DUCK_THRESHOLD = 0.03
DEFAULT_DUCK_RATIO = 8.0
# EBU R128 loudnorm targets: integrated loudness (LUFS), true-peak (dBTP),
# loudness-range (LU). -14 LUFS is the de-facto YouTube/Spotify target.
DEFAULT_LOUDNESS_TARGET = -14.0
DEFAULT_LOUDNESS_TP = -1.5
DEFAULT_LOUDNESS_LRA = 11.0


class AudioMixError(RuntimeError):
    """Raised when the audio-mix ffmpeg pass fails (non-zero exit)."""


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


# --------------------------------------------------------------------------- #
# pure: the filter graph + argv builder
# --------------------------------------------------------------------------- #
def build_mix_filter(
    *,
    bg_gain_db: float = DEFAULT_BG_GAIN_DB,
    duck_threshold: float = DEFAULT_DUCK_THRESHOLD,
    duck_ratio: float = DEFAULT_DUCK_RATIO,
    loudness_target: float = DEFAULT_LOUDNESS_TARGET,
    loudness_tp: float = DEFAULT_LOUDNESS_TP,
    loudness_lra: float = DEFAULT_LOUDNESS_LRA,
) -> str:
    """Build the ``-filter_complex`` string for duck -> mix -> loudnorm.

    Input ``0:a`` = the clip's foreground audio, input ``1:a`` = the bg bed.

      [1:a] volume=<bg_gain_db>dB         -> pre-attenuated bed [bg]
      [0:a] asplit                        -> [fg_key] (sidechain key) + [fg_mix]
      [bg][fg_key] sidechaincompress      -> ducked bed [ducked]
      [fg_mix][ducked] amix               -> summed mix [mixed]
      [mixed] loudnorm                    -> EBU R128 normalized [out]

    ``amix`` uses ``dropout_transition=0`` + ``normalize=0`` so the foreground is
    not auto-attenuated by the mixer (the bed is already ducked; loudnorm does
    the final leveling). Returns the graph as a single string (one argv element).
    """
    return (
        f"[1:a]volume={bg_gain_db}dB[bg];"
        f"[0:a]asplit=2[fg_key][fg_mix];"
        f"[bg][fg_key]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}[ducked];"
        f"[fg_mix][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed];"
        f"[mixed]loudnorm=I={loudness_target}:TP={loudness_tp}:LRA={loudness_lra}[out]"
    )


def build_mix_argv(
    clip_path: str,
    bg_path: str,
    out_path: str,
    *,
    bg_gain_db: float = DEFAULT_BG_GAIN_DB,
    duck_threshold: float = DEFAULT_DUCK_THRESHOLD,
    duck_ratio: float = DEFAULT_DUCK_RATIO,
    loudness_target: float = DEFAULT_LOUDNESS_TARGET,
    loudness_tp: float = DEFAULT_LOUDNESS_TP,
    loudness_lra: float = DEFAULT_LOUDNESS_LRA,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv merging ``bg_path`` under ``clip_path``'s audio with duck + loudnorm.

    The clip's VIDEO is kept under stream copy (``-map 0:v``, ``-c:v copy``);
    only the audio is rebuilt from the filter graph and encoded to AAC. The
    output duration follows the clip (``-shortest`` + ``duration=first`` in the
    mix) so a longer bg bed is trimmed to the clip. argv LIST only.
    """
    flt = build_mix_filter(
        bg_gain_db=bg_gain_db,
        duck_threshold=duck_threshold,
        duck_ratio=duck_ratio,
        loudness_target=loudness_target,
        loudness_tp=loudness_tp,
        loudness_lra=loudness_lra,
    )
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        clip_path,
        "-i",
        bg_path,
        "-filter_complex",
        flt,
        "-map",
        "0:v",
        "-map",
        "[out]",
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


def build_loudnorm_argv(
    in_path: str,
    out_path: str,
    *,
    loudness_target: float = DEFAULT_LOUDNESS_TARGET,
    loudness_tp: float = DEFAULT_LOUDNESS_TP,
    loudness_lra: float = DEFAULT_LOUDNESS_LRA,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv applying EBU R128 loudnorm ONLY (no bed) — the "normalize export" path.

    Keeps the video under stream copy and re-encodes the single audio stream
    through ``loudnorm``. Used by :meth:`AudioMix.normalize` / when a caller just
    wants the loudness normalization without a music bed.
    """
    flt = f"loudnorm=I={loudness_target}:TP={loudness_tp}:LRA={loudness_lra}"
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-map",
        "0:v?",
        "-map",
        "0:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-af",
        flt,
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class AudioMix:
    """Owns the ``audiomix.merge`` logic over the library/exports seams."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | os.PathLike,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._run: RunFn = run or ffmpeg.run
        self._duration: ProbeFn = duration or ffmpeg.ffprobe_duration

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

    def _out_path(self, clip_path: str, suffix: str) -> str:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(clip_path).stem or "clip"
        return str(self._out_dir / f"{stem}-{suffix}-{int(time.time())}.mp4")

    def _run_or_raise(self, argv: list[str], in_path: str, what: str, ctx: JobContext) -> None:
        try:
            total = float(self._duration(in_path, self._settings()))
        except Exception:  # noqa: BLE001 - probe failure only coarsens progress
            total = 0.0
        code = self._run(
            argv,
            total_sec=total,
            on_progress=lambda pct, msg: ctx.progress(pct, msg),
            should_cancel=lambda: ctx.cancelled,
        )
        if code != 0:
            raise AudioMixError(f"{what} failed (ffmpeg exit {code}) for {in_path}")

    def merge(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``audiomix.merge({videoId|path, bgPath, ...})`` -> ``{jobId}`` -> ``{path}``.

        Mixes ``bgPath`` (music bed / VO) UNDER the clip's audio with sidechain
        ducking, then EBU R128 loudnorm on the export. The optional tunables
        (``bgGainDb`` / ``duckThreshold`` / ``duckRatio`` / ``loudnessTarget`` /
        ``loudnessTp`` / ``loudnessLra``) override the defaults. Long job ->
        streams progress, ``job.done.result`` is ``{path}``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        clip_path = self._resolve(params)
        bg_path = _require_str(params, "bgPath")
        if not Path(bg_path).is_file():
            raise _invalid(f"background audio not found: {bg_path}")
        opts = {
            "bg_gain_db": _float(params, "bgGainDb", DEFAULT_BG_GAIN_DB),
            "duck_threshold": _float(params, "duckThreshold", DEFAULT_DUCK_THRESHOLD),
            "duck_ratio": _float(params, "duckRatio", DEFAULT_DUCK_RATIO),
            "loudness_target": _float(params, "loudnessTarget", DEFAULT_LOUDNESS_TARGET),
            "loudness_tp": _float(params, "loudnessTp", DEFAULT_LOUDNESS_TP),
            "loudness_lra": _float(params, "loudnessLra", DEFAULT_LOUDNESS_LRA),
        }
        settings = self._settings()
        out_path = self._out_path(clip_path, "mixed")

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            argv = build_mix_argv(clip_path, bg_path, out_path, settings=settings, **opts)
            self._run_or_raise(argv, clip_path, "audio mix", job_ctx)
            return {"path": out_path}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    def normalize(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``audiomix.normalize({videoId|path, ...})`` -> ``{jobId}`` -> ``{path}``.

        EBU R128 loudnorm of the clip's existing audio (no music bed). Same
        loudness tunables as :meth:`merge`.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        clip_path = self._resolve(params)
        opts = {
            "loudness_target": _float(params, "loudnessTarget", DEFAULT_LOUDNESS_TARGET),
            "loudness_tp": _float(params, "loudnessTp", DEFAULT_LOUDNESS_TP),
            "loudness_lra": _float(params, "loudnessLra", DEFAULT_LOUDNESS_LRA),
        }
        settings = self._settings()
        out_path = self._out_path(clip_path, "loudnorm")

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            argv = build_loudnorm_argv(clip_path, out_path, settings=settings, **opts)
            self._run_or_raise(argv, clip_path, "loudnorm", job_ctx)
            return {"path": out_path}

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
    register_fn: Callable[[str, Any], None] | None = None,
) -> AudioMix:
    """Create the service and register ``audiomix.merge`` + ``audiomix.normalize``.

    ``register_fn`` defaults to :func:`protocol.register` (duplicates fail loudly);
    tests inject a fake registrar. Returns the service for the caller to hold.
    """
    service = AudioMix(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("audiomix.merge", service.merge)
    reg("audiomix.normalize", service.normalize)
    log.info("registered audiomix.merge / audiomix.normalize")
    return service


__all__ = [
    "DEFAULT_BG_GAIN_DB",
    "DEFAULT_DUCK_RATIO",
    "DEFAULT_DUCK_THRESHOLD",
    "DEFAULT_LOUDNESS_LRA",
    "DEFAULT_LOUDNESS_TARGET",
    "DEFAULT_LOUDNESS_TP",
    "AudioMix",
    "AudioMixError",
    "build_loudnorm_argv",
    "build_mix_argv",
    "build_mix_filter",
    "register",
]
