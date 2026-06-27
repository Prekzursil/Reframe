"""SILENCE-TRIM / dead-air removal — ffmpeg ``silencedetect`` -> keep-span re-cut.

Removes long silent gaps ("dead air") from a clip:

  1. **detect** — run ffmpeg ``silencedetect`` (noise floor in dB + a minimum
     silence duration) and parse its stderr ``silence_start``/``silence_end``
     lines into silent SPANS,
  2. **invert** — compute the KEEP spans (the talking parts between the silences),
     optionally leaving a small ``padding`` of silence on each kept edge so the
     cuts don't sound clipped,
  3. **re-cut** — concatenate the keeps with a frame-accurate ``filter_complex``
     trim/concat (reusing :func:`features.fillers.build_segment_cut_argv`).

Wire surface (NET-NEW)::

    silence.trim({videoId|path, noiseDb?, minSilenceSec?, padSec?}) -> {jobId} -> {path, removedSec}

It is ALSO wired into the short-maker EXPORT pipeline as an optional pre-step
(``settings['silenceTrim']``): each cut clip has its dead air removed BEFORE the
filler / reframe / caption stages.

CONTRACTS.md §6/§7: ffmpeg ``silencedetect`` for silence (the §7-named detector);
argv-list subprocess only (never ``shell=True``); the bundled/PATH ffmpeg
resolved by absolute path. Detection + the re-cut both go through injectable seams
so the module is unit-testable with no real ffmpeg.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - argv-list silencedetect only, never shell=True
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import boundary as _boundary
from . import fillers as _fillers

log = get_logger("media_studio.silencetrim")

# Injectable seams (mirror the sibling features):
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
DetectRunner = Callable[..., Any]
Resolver = Callable[[str], str | None]

# A keep / silence span in seconds: [start, end).
Span = tuple[float, float]

# --- tunables (sane defaults) -----------------------------------------------
# Reuse the boundary module's silencedetect defaults so a single noise floor /
# min-duration convention holds across both detectors.
DEFAULT_NOISE_DB = _boundary.DEFAULT_SILENCE_NOISE_DB  # -30.0 dB
DEFAULT_MIN_SILENCE_SEC = _boundary.DEFAULT_SILENCE_MIN_SEC  # 0.5 s
# Leave this much silence on each kept edge so the cut doesn't sound clipped.
DEFAULT_PAD_SEC = 0.1

# WU-3 NO-SILENT-FALLBACK: when silence-trim cannot run its detection (no ffmpeg,
# a silencedetect spawn failure, an unprobeable duration) the step previously
# no-op'd SILENTLY. It now surfaces this typed notice through an ``on_notice`` sink
# so the skip is REPORTED (the orchestrator routes it to job.progress), never
# swallowed. Distinct from a legitimate "no dead air to remove" pass-through.
SILENCE_TRIM_UNAVAILABLE_NOTICE = "silencetrim.unavailable"

# A notice sink mirroring the stabilize pre-step's: receives a {type, message,
# reason} dict the orchestrator surfaces via job.progress.
NoticeSink = Callable[[dict[str, str]], None]


def make_unavailable_notice(reason: str) -> dict[str, str]:
    """Build the typed notice emitted when silence-trim is skipped (``{type, message, reason}``).

    ``message`` is the human line a job surfaces via ``job.progress``; ``reason``
    is the specific cause (no ffmpeg, a detection spawn failure, an unprobeable
    duration) so the skip is actionable instead of silent.
    """
    return {
        "type": SILENCE_TRIM_UNAVAILABLE_NOTICE,
        "message": f"silence-trim skipped: {reason}; the clip was passed through unchanged",
        "reason": reason,
    }


def _notify(on_notice: NoticeSink | None, reason: str) -> None:
    """Surface the silence-trim unavailable notice through ``on_notice`` (when wired)."""
    if on_notice is not None:
        on_notice(make_unavailable_notice(reason))


class SilenceTrimError(RuntimeError):
    """Raised when the silence-trim re-cut ffmpeg pass fails (non-zero exit)."""


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _float(params: dict[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# pure: parse silencedetect into spans + invert to keep spans
# --------------------------------------------------------------------------- #
def parse_silence_spans(stderr: str) -> list[Span]:
    """Parse ffmpeg ``silencedetect`` stderr into ``[(start, end), ...]`` spans.

    Each paired ``silence_start``/``silence_end`` is one silent span. An unpaired
    trailing start (a silence running to EOF with no ``silence_end`` line) is
    ignored — the re-cut keeps that tail rather than guessing its length.
    Returns sorted, non-overlapping spans.
    """
    starts = [float(m.group(1)) for m in _boundary._SILENCE_START_RE.finditer(stderr)]
    ends = [float(m.group(1)) for m in _boundary._SILENCE_END_RE.finditer(stderr)]
    spans: list[Span] = []
    for start, end in zip(starts, ends, strict=False):
        if end > start:
            spans.append((start, end))
    spans.sort()
    return spans


def keep_spans(
    silences: Sequence[Span],
    total_sec: float,
    *,
    pad_sec: float = DEFAULT_PAD_SEC,
) -> list[Span]:
    """Invert ``silences`` over ``[0, total_sec)`` into the KEEP spans.

    A small ``pad_sec`` of silence is left on each kept edge (so the speech
    isn't clipped); padding never crosses into the next/previous keep. Adjacent
    keeps separated by a removed span shorter than ``2*pad_sec`` coalesce (the
    pad would have re-covered the whole gap anyway). Returns the talking spans;
    an empty silence list yields the single full-length span ``[(0, total)]``.
    """
    total = max(0.0, float(total_sec))
    if total <= 0.0:
        return []
    pad = max(0.0, float(pad_sec))
    clean = sorted((max(0.0, float(a)), min(total, float(b))) for a, b in silences if float(b) > float(a))

    keeps: list[Span] = []
    cursor = 0.0
    for sil_start, sil_end in clean:
        # The kept span runs from the cursor up to (silence start + pad), and the
        # next cursor resumes at (silence end - pad) — leaving pad on both edges.
        keep_end = min(total, sil_start + pad)
        if keep_end > cursor:
            keeps.append((cursor, keep_end))
        cursor = max(cursor, sil_end - pad)
    if cursor < total:
        keeps.append((cursor, total))

    # Coalesce keeps whose gap shrank to nothing after padding (overlap/touch).
    merged: list[Span] = []
    for start, end in keeps:
        if merged and start <= merged[-1][1] + 1e-6:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end))
        else:
            merged.append((round(start, 3), round(end, 3)))
    return [(round(a, 3), round(b, 3)) for a, b in merged]


def removed_seconds(keeps: Sequence[Span], total_sec: float) -> float:
    """How much dead air the keep-list removes (total - kept duration)."""
    kept = sum(max(0.0, float(b) - float(a)) for a, b in keeps)
    return round(max(0.0, float(total_sec) - kept), 3)


# --------------------------------------------------------------------------- #
# detection (ffmpeg silencedetect) — reuses the boundary argv builder
# --------------------------------------------------------------------------- #
def detect_silence_spans(
    in_path: str,
    *,
    settings: dict[str, Any] | None = None,
    noise_db: float = DEFAULT_NOISE_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
    run: DetectRunner | None = None,
    on_notice: NoticeSink | None = None,
) -> list[Span]:
    """Detect silent spans in ``in_path`` via ffmpeg ``silencedetect``.

    Reuses :func:`boundary.build_silencedetect_argv` (one noise-floor convention)
    and parses the stderr into SPANS (not midpoints). ``run`` defaults to
    ``subprocess.run`` but is injectable so tests mock the subprocess. A probe
    failure returns ``[]`` (the trim then keeps the whole clip) rather than
    raising — a detection miss must not fail the pipeline.

    WU-3 NO-SILENT-FALLBACK: a detection failure (no resolvable ffmpeg, or a
    ``silencedetect`` spawn failure) is SURFACED through ``on_notice`` so the
    skipped trim is reported, not silently swallowed.
    """
    runner = run if run is not None else subprocess.run
    try:
        ffmpeg_bin = ffmpeg.ffmpeg_path(settings)
    except Exception:  # noqa: BLE001 - no ffmpeg resolvable -> no silences
        log.warning("ffmpeg not found for silencedetect on %s", in_path)
        _notify(on_notice, "ffmpeg not found for silencedetect")
        return []
    argv = _boundary.build_silencedetect_argv(
        in_path,
        ffmpeg_path=ffmpeg_bin,
        noise_db=noise_db,
        min_silence_sec=min_silence_sec,
    )
    try:
        completed = runner(argv, capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001 - a probe failure must not crash trim
        log.warning("silencedetect failed for %s: %s", in_path, exc)
        _notify(on_notice, f"silencedetect failed: {exc}")
        return []
    stderr = getattr(completed, "stderr", "") or ""
    return parse_silence_spans(stderr)


# --------------------------------------------------------------------------- #
# pipeline pre-step adapter (used by the short-maker EXPORT pipeline)
# --------------------------------------------------------------------------- #
def trim_clip(
    in_path: str,
    out_path: str,
    *,
    settings: dict[str, Any] | None = None,
    noise_db: float = DEFAULT_NOISE_DB,
    min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
    pad_sec: float = DEFAULT_PAD_SEC,
    detect_run: DetectRunner | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    on_notice: NoticeSink | None = None,
) -> tuple[str, float, list[Span]]:
    """Trim dead air from ``in_path`` -> ``out_path``; return ``(path, removedSec, keeps)``.

    The pipeline-facing entry point. Detects silent spans, inverts them to keeps,
    and re-cuts via :func:`fillers.build_segment_cut_argv`. When there is nothing
    to remove (no silence detected, or a single full-length keep), the ORIGINAL
    ``in_path`` is returned unchanged with ``removedSec == 0.0`` (no needless
    re-encode). Raises :class:`SilenceTrimError` on a non-zero ffmpeg exit.

    ``keeps`` is the list of clip-local KEEP spans the re-cut concatenated (in the
    SAME timeline as ``in_path``). The export orchestrator feeds it to
    :func:`fillers.remap_cues` so caption cues are re-timed onto the compacted
    timeline (without it, every cue after a removed interior silence drifts late by
    the removed duration). On a pass-through (nothing removed) ``keeps`` is the
    single full-length span ``[(0, total)]`` — an identity remap, so cues map
    through unchanged.

    WU-3 NO-SILENT-FALLBACK: a swallowed failure (an unprobeable duration, or a
    detection miss forwarded from :func:`detect_silence_spans`) is SURFACED
    through ``on_notice`` so the skipped trim is reported, never silent. A
    legitimate "no dead air to remove" pass-through emits NO notice.
    """
    settings = settings or {}
    run = run or ffmpeg.run
    duration = duration or ffmpeg.ffprobe_duration

    # ADV-FIX (caption erasure): a passthrough that returns ``[]`` made the
    # caller's :func:`fillers.remap_cues` collapse EVERY caption cue to length 0
    # (``remap_time`` over an empty keep-list returns 0.0 for all times) — every
    # caption was then dropped, silently. The identity keep ``[(0.0, inf)]`` maps
    # any cue time ``t`` back to ``t`` (cues pass through UNCHANGED), so a clip we
    # could not / need not trim keeps its captions intact.
    identity_keeps: list[Span] = [(0.0, float("inf"))]
    try:
        total = float(duration(in_path, settings))
    except Exception:  # noqa: BLE001 - a probe failure means we can't trim safely
        log.warning("duration probe failed for %s; skipping silence-trim", in_path)
        _notify(on_notice, "duration probe failed")
        return in_path, 0.0, identity_keeps
    if total <= 0.0:
        return in_path, 0.0, identity_keeps

    silences = detect_silence_spans(
        in_path,
        settings=settings,
        noise_db=noise_db,
        min_silence_sec=min_silence_sec,
        run=detect_run,
        on_notice=on_notice,
    )
    keeps = keep_spans(silences, total, pad_sec=pad_sec)
    removed = removed_seconds(keeps, total)
    # Nothing to remove (or a single full-length keep): pass through untouched. The
    # keeps then cover the whole clip (identity remap), so cues map through as-is.
    if removed <= 1e-3 or len(keeps) <= 1:
        return in_path, 0.0, [(0.0, total)]

    argv = _fillers.build_segment_cut_argv(in_path, out_path, keeps, settings)
    code = run(argv, total_sec=total)
    if code != 0:
        raise SilenceTrimError(f"silence-trim re-cut failed (ffmpeg exit {code}) for {in_path}")
    return out_path, removed, keeps


# --------------------------------------------------------------------------- #
# the service (silence.trim -> a job)
# --------------------------------------------------------------------------- #
class SilenceTrim:
    """Owns the ``silence.trim`` RPC over the library/exports seams."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | os.PathLike,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
        detect_run: DetectRunner | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._duration = duration
        self._detect_run = detect_run

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

    def trim(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``silence.trim({videoId|path, noiseDb?, minSilenceSec?, padSec?})``.

        -> ``{jobId}`` -> ``{path, removedSec}``. Removes dead air; the optional
        tunables override the defaults. When nothing is removed the result's
        ``path`` is the source path and ``removedSec`` is 0.0.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        noise_db = _float(params, "noiseDb", DEFAULT_NOISE_DB)
        min_silence_sec = _float(params, "minSilenceSec", DEFAULT_MIN_SILENCE_SEC)
        pad_sec = _float(params, "padSec", DEFAULT_PAD_SEC)
        settings = self._settings()
        run = self._run
        duration = self._duration
        detect_run = self._detect_run
        out_dir = self._out_dir

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            job_ctx.progress(5, "detecting silence")
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(in_path).stem or "clip"
            out_path = str(out_dir / f"{stem}.trimmed.mp4")
            path, removed, _keeps = trim_clip(
                in_path,
                out_path,
                settings=settings,
                noise_db=noise_db,
                min_silence_sec=min_silence_sec,
                pad_sec=pad_sec,
                detect_run=detect_run,
                run=run,
                duration=duration,
                # WU-3: surface a swallowed detect/probe failure via job.progress
                # (the skip is reported, never a silent {removedSec: 0} no-op).
                on_notice=lambda notice: job_ctx.progress(50, notice["message"]),
            )
            job_ctx.progress(100, f"removed {removed:.1f}s of dead air")
            return {"path": path, "removedSec": removed}

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
    detect_run: DetectRunner | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> SilenceTrim:
    """Create the service and register ``silence.trim`` (mirrors shorts.register).

    ``register_fn`` defaults to :func:`protocol.register` (duplicates fail loudly);
    tests inject a fake registrar. Returns the service for the caller to hold.
    """
    service = SilenceTrim(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
        detect_run=detect_run,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("silence.trim", service.trim)
    log.info("registered silence.trim")
    return service


__all__ = [
    "DEFAULT_MIN_SILENCE_SEC",
    "DEFAULT_NOISE_DB",
    "DEFAULT_PAD_SEC",
    "SILENCE_TRIM_UNAVAILABLE_NOTICE",
    "SilenceTrim",
    "SilenceTrimError",
    "detect_silence_spans",
    "keep_spans",
    "make_unavailable_notice",
    "parse_silence_spans",
    "register",
    "removed_seconds",
    "trim_clip",
]
