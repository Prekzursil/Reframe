"""Constant-factor speed / slow-motion as a FIRST-CLASS RPC (``speed.retime``).

The re-time ENGINE already existed and is sound: ``director_op_engines``
``build_retime_argv`` (``setpts=(1/factor)*PTS`` + a legal ``atempo`` chain, so
picture and sound stay in sync) with ``retime`` in ``WIRED_KINDS``. What did NOT
exist was any way for a USER to reach it: there was no speed RPC and no speed
control in any renderer panel, so the only reachable path was an LLM-planned
Director op — the user had to phrase a prompt and hope the planner emitted a
``retime``. This module is that missing door, and nothing more.

DELIBERATELY A THIN DOOR. The filtergraph is NOT re-implemented here:
:func:`build_speed_argv` delegates to the audited Director builder, and
``tests/test_speed.py::TestArgv::test_delegates_to_the_director_retime_builder``
asserts byte-equality so the two paths can never drift into two different
re-timers. The delegation is a LAZY import because
:mod:`media_studio.features.director_op_engines` pulls the caption/reframe/shorts
chain, which a lean speed call has no reason to load.

SCOPE — read this before citing the module as "speed ramps are done". This is a
**CONSTANT** factor over the whole clip. A keyframed speed RAMP (piecewise
``setpts`` with segment-wise audio resampling) is a DIFFERENT engine and is NOT
implemented here or anywhere else in the tree; ``docs/plans/v1.5/editing-surface-audit-2026-08.md``
records it as a later-stage item. A UI that offers "0.5x / 1.5x / 2x" is honest;
a UI that offers "ramp from 1x to 2x" would not be.

NOT TO BE CONFUSED WITH the two other things in this tree called "retime":
``features/tts/align.py`` runs its own +/-15% ``atempo`` to fit a dub into its
source slot, and ``features/caption_polish.py`` "retime" moves CUE timings on the
subtitle track. Neither changes video playback speed; neither is this.

CONTRACTS.md 4/6/7: argv-list subprocess only (never ``shell=True``); ffmpeg is
resolved by absolute path through :mod:`media_studio.ffmpeg`; the render goes
through the shared, drained ``run`` seam. Every heavy dependency is injectable so
the module unit-tests with no real ffmpeg.

KNOWN LIMIT (inherited, not introduced): ``build_retime_argv`` maps ``[0:a]``
unconditionally, so a clip with NO audio stream fails the ffmpeg invocation
rather than re-timing video-only. That is the Director path's existing behaviour
and is shared, not added, here; fixing it means changing the shared builder for
both callers, which is outside this module's remit. UNVERIFIED whether any
library clip is audio-less in practice — the settling experiment is
``ffprobe -show_streams`` over the library and a ``speed.retime`` call on any hit.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.speed")

# Injectable seams (mirror the sibling features):
#   RunFn   mirrors ffmpeg.run(argv, total_sec, on_progress, should_cancel) -> int
#   ProbeFn mirrors ffmpeg.ffprobe_duration(path, settings) -> float
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]

#: The accepted playback-factor window. Not an ffmpeg limit (``_atempo_chain``
#: decomposes ANY positive factor into legal [0.5, 2.0] stages) but a SANITY one:
#: 0.1x turns a 1-minute clip into 10 minutes and 10x makes a 1-hour lecture a
#: 6-minute blur; beyond that the request is far likelier to be a typo than an
#: edit. Out-of-window is REJECTED, never silently clamped — a user who asks for
#: 100x and gets 10x back has been lied to.
#:
#: MIRRORED in ``app/renderer/src/lib/speedPresets.ts`` (SPEED_MIN / SPEED_MAX):
#: the renderer cannot read Python, so the window is stated twice on purpose. The
#: renderer clamps for a friendly slider; THIS module is the authority and
#: rejects. If you change one, change both.
SPEED_MIN = 0.1
SPEED_MAX = 10.0


class SpeedError(RuntimeError):
    """Raised when the re-time render fails (non-zero ffmpeg exit)."""


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def resolve_factor(raw: Any) -> float:
    """Validate a playback ``factor`` at the wire boundary; return it as a float.

    ``factor`` > 1 speeds up (shorter output), < 1 slows down (longer). Rejects,
    in order: a non-numeric value (``bool`` included — ``isinstance(True, int)``
    is True in Python, and ``speed.retime(factor=true)`` is a caller bug, not a
    request for 1x), a non-positive value, exactly 1.0 (a no-op the engine itself
    refuses), and anything outside [:data:`SPEED_MIN`, :data:`SPEED_MAX`].
    """
    if isinstance(raw, bool):
        raise _invalid("factor must be numeric (got a boolean)")
    try:
        factor = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _invalid(f"factor must be numeric (got {raw!r})") from None
    if factor <= 0.0:
        raise _invalid(f"factor must be greater than 0 (got {factor})")
    if factor == 1.0:
        raise _invalid("factor 1.0 is a no-op — pick a slower or faster speed")
    if not (SPEED_MIN <= factor <= SPEED_MAX):
        raise _invalid(f"factor must be between {SPEED_MIN} and {SPEED_MAX} (got {factor})")
    return factor


def retimed_duration(source_sec: float, factor: float) -> float:
    """The output duration a re-time by ``factor`` produces (``source/factor``).

    Returns 0.0 for a non-positive source duration — that is the "probe failed /
    unknown" signal, and multiplying an unknown by anything is still unknown.
    """
    if source_sec <= 0.0:
        return 0.0
    return source_sec / factor


def speed_output_name(in_path: str, factor: float) -> str:
    """The output basename for a re-time, e.g. ``lecture.speed-1p50x.mp4``.

    The factor is in the NAME (``.`` -> ``p`` so the stem stays extension-safe) so
    two speeds of the same source do not overwrite each other in the exports dir.
    """
    stem = Path(in_path).stem or "clip"
    tag = f"{factor:.2f}".replace(".", "p")
    return f"{stem}.speed-{tag}x.mp4"


def build_speed_argv(
    in_path: str,
    out_path: str,
    factor: float,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv that re-times ``in_path`` -> ``out_path`` by ``factor``.

    Delegates to the audited Director builder rather than re-deriving the
    ``setpts``/``atempo`` graph, so the user-driven RPC and the Director op can
    never render differently. Lazy import: the Director engine module pulls the
    caption/reframe/shorts chain, which this call does not need at import time.
    """
    from . import director_op_engines as _doe

    return _doe.build_retime_argv(in_path, out_path, factor, settings)


class SpeedService:
    """Owns the ``speed.retime`` RPC over the library/exports seams."""

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
        self._run = run
        self._duration = duration

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, params: dict[str, Any]) -> str:
        """Resolve a ``{videoId}`` or ``{path}`` request to a concrete media path."""
        path = params.get("path")
        if isinstance(path, str) and path:
            return path
        video_id = _require_str(params, "videoId")
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        return str(resolved)

    def run(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``speed.retime({videoId|path, factor})`` -> ``{jobId}``.

        ``job.done.result`` is ``{path, factor, sourceDurationSec, durationSec}``:
        the re-timed clip plus the duration arithmetic the UI shows ("6.0s, was
        12.0s"). Both the factor and the source are validated BEFORE the job is
        enqueued, so a bad request fails the call rather than a background job the
        caller then has to poll to discover was never going to work.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        factor = resolve_factor(params.get("factor"))
        settings = self._settings()
        runner: RunFn = self._run if self._run is not None else _default_run()
        probe: ProbeFn = self._duration if self._duration is not None else _default_duration()
        out_dir = self._out_dir

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            try:
                total = float(probe(in_path, settings))
            except Exception:  # noqa: BLE001 - probe failure only coarsens progress
                total = 0.0
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(out_dir / speed_output_name(in_path, factor))
            argv = build_speed_argv(in_path, out_path, factor, settings)
            code = runner(
                argv,
                total_sec=retimed_duration(total, factor),
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            if code != 0:
                raise SpeedError(f"re-time failed (ffmpeg exit {code}) for {in_path}")
            return {
                "path": out_path,
                "factor": factor,
                "sourceDurationSec": total,
                "durationSec": retimed_duration(total, factor),
            }

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}


def _default_run() -> RunFn:
    """The real drained ffmpeg runner (lazy so importing this module is cheap)."""
    from .. import ffmpeg

    return ffmpeg.run


def _default_duration() -> ProbeFn:
    """The real ffprobe duration seam (lazy, same reason as :func:`_default_run`)."""
    from .. import ffmpeg

    return ffmpeg.ffprobe_duration


def register(
    *,
    resolver: Resolver,
    out_dir: str | os.PathLike,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> SpeedService:
    """Create the service and register ``speed.retime`` (mirrors stabilize.register).

    ``register_fn`` defaults to :func:`protocol.register` (duplicates fail loudly);
    tests inject a fake registrar. Returns the service for the caller to hold.
    """
    service = SpeedService(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("speed.retime", service.run)
    log.info("registered speed.retime")
    return service


__all__ = [
    "SPEED_MAX",
    "SPEED_MIN",
    "SpeedError",
    "SpeedService",
    "build_speed_argv",
    "register",
    "resolve_factor",
    "retimed_duration",
    "speed_output_name",
]
