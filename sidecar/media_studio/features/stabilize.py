"""Camera-shake stabilization via ffmpeg **vidstab** (2-pass) — the differentiator.

Stabilization is a TWO-PASS ffmpeg operation (libvidstab):

  PASS 1 (analyze)   ``vidstabdetect``    -> writes a transforms file (.trf)
  PASS 2 (transform) ``vidstabtransform`` -> reads the .trf, renders a steadied clip

This module is the transport-agnostic engine:

  * pure argv builders for each pass (``build_detect_argv`` / ``build_transform_argv``),
  * a :class:`StabilizeEngine` that runs both passes through the shared, drained
    :func:`media_studio.ffmpeg.run` seam (the 29-min-freeze lesson — never a
    re-implemented drain), cleaning up the intermediate .trf,
  * a **libvidstab availability probe** (:func:`vidstab_available`) so a caller
    can detect a bundled ffmpeg built WITHOUT ``--enable-libvidstab`` and surface
    a typed notice (:func:`make_unavailable_notice`) instead of silently skipping,
  * a pipeline pre-step adapter (:func:`stabilize_clip`) the short-maker/reframe
    pipeline calls BEFORE reframe when the ``stabilize`` toggle is on.

CONTRACTS.md §4/§6/§7: argv-list subprocess only (never ``shell=True``); the
bundled/PATH ffmpeg is resolved by absolute path through :mod:`media_studio.ffmpeg`;
both ffmpeg passes go through the drained ``run``. Everything heavy is behind an
injectable seam so the whole module is unit-testable with no real ffmpeg.

BUNDLING NOTE: ``vidstabdetect``/``vidstabtransform`` exist only when ffmpeg was
compiled ``--enable-libvidstab`` (GPL). The dev-host PATH ffmpeg (winget/gyan
build) HAS it; a stripped/LGPL bundle would NOT. :func:`vidstab_available`
gates the feature so a missing filter is reported, never silently ignored.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - argv-list only, never shell=True
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import ffmpeg, protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger

log = get_logger("media_studio.stabilize")

# Injectable seams (mirror the sibling features):
#   RunFn   mirrors ffmpeg.run(argv, total_sec, on_progress, should_cancel) -> int
#   ProbeFn mirrors ffmpeg.ffprobe_duration(path, settings) -> float
RunFn = Callable[..., int]
ProbeFn = Callable[..., float]
# A subprocess seam mirroring ``subprocess.run`` (mocked in tests so the
# vidstab-availability probe never spawns a real ffmpeg).
ProbeRunner = Callable[..., Any]
# videoId -> absolute media path (or None when unknown).
Resolver = Callable[[str], str | None]

# --- vidstab tunables (sane stabilization defaults) -------------------------
# vidstabdetect: shakiness 1-10 (how shaky the input is), accuracy 1-15.
DEFAULT_SHAKINESS = 5
DEFAULT_ACCURACY = 15
# vidstabtransform: smoothing window (frames before+after), optzoom mode
# (1 = adaptive zoom to hide the black borders the warp introduces).
DEFAULT_SMOOTHING = 10
DEFAULT_OPTZOOM = 1

# The filter names libvidstab registers (used by the availability probe).
DETECT_FILTER = "vidstabdetect"
TRANSFORM_FILTER = "vidstabtransform"

# The typed notice discriminator (a `notice["type"]` consumers can match on).
STABILIZE_UNAVAILABLE_NOTICE = "stabilize.unavailable"


class StabilizeError(RuntimeError):
    """Raised when a vidstab pass fails (non-zero ffmpeg exit)."""


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _stab_settings(settings: dict[str, Any] | None) -> dict[str, int]:
    """Resolve the vidstab tunables from ``settings`` (falling back to defaults).

    Keys read (all optional): ``stabShakiness`` / ``stabAccuracy`` /
    ``stabSmoothing`` / ``stabOptzoom``. Each is coerced to an int so a stray
    string from the wire can never reach the filter expression unparsed.
    """
    settings = settings or {}

    def _int(key: str, default: int) -> int:
        try:
            return int(settings.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        "shakiness": _int("stabShakiness", DEFAULT_SHAKINESS),
        "accuracy": _int("stabAccuracy", DEFAULT_ACCURACY),
        "smoothing": _int("stabSmoothing", DEFAULT_SMOOTHING),
        "optzoom": _int("stabOptzoom", DEFAULT_OPTZOOM),
    }


# --------------------------------------------------------------------------- #
# pure argv builders (fully unit-testable, no subprocess)
# --------------------------------------------------------------------------- #
def build_detect_argv(
    in_path: str,
    trf_path: str,
    *,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv for PASS 1 — ``vidstabdetect`` writing the transforms file ``trf_path``.

    Decodes to ``-f null -`` (no output video — only the .trf analysis matters)
    so the analysis is fast. ``result=`` names the .trf file vidstabtransform
    will read. ``-progress pipe:1 -nostats`` lets :func:`ffmpeg.run` drain stdout.
    argv LIST only (paths with spaces are single elements; never ``shell=True``).
    """
    cfg = _stab_settings(settings)
    # The .trf path is embedded INSIDE the -vf filtergraph, where ':' separates
    # filter options. An absolute Windows path (``C:\...``) breaks the parser — the
    # drive colon reads as an option break and NO escaping form works (empirically
    # verified against ffmpeg 8). So we emit the BARE basename and run ffmpeg with
    # cwd=<trf dir> (see StabilizeEngine.stabilize); the .trf lands beside the
    # output, colon-free. On POSIX the basename is equally correct under that cwd.
    trf = Path(trf_path).name
    detect = f"{DETECT_FILTER}=shakiness={cfg['shakiness']}:accuracy={cfg['accuracy']}:result={trf}"
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        detect,
        "-f",
        "null",
        "-progress",
        "pipe:1",
        "-nostats",
        "-",
    ]


def build_transform_argv(
    in_path: str,
    trf_path: str,
    out_path: str,
    *,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """argv for PASS 2 — ``vidstabtransform`` rendering the steadied ``out_path``.

    Reads the .trf from PASS 1 (``input=``), applies the smoothing window +
    adaptive zoom, and re-encodes video as h264 (audio copied through so the
    pre-step never touches the soundtrack). argv LIST only.
    """
    cfg = _stab_settings(settings)
    # Bare basename — the engine runs ffmpeg with cwd=<trf dir>; an absolute Windows
    # path's drive colon breaks the -vf filtergraph parser (see build_detect_argv).
    trf = Path(trf_path).name
    transform = f"{TRANSFORM_FILTER}=input={trf}:smoothing={cfg['smoothing']}:optzoom={cfg['optzoom']}"
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        transform,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def build_filters_probe_argv(settings: dict[str, Any] | None = None) -> list[str]:
    """argv for ``ffmpeg -filters`` (used to detect libvidstab support)."""
    return [ffmpeg.ffmpeg_path(settings), "-hide_banner", "-filters"]


# --------------------------------------------------------------------------- #
# libvidstab availability probe + typed notice
# --------------------------------------------------------------------------- #
def vidstab_available(
    settings: dict[str, Any] | None = None,
    probe_runner: ProbeRunner | None = None,
) -> bool:
    """True when the resolved ffmpeg lists BOTH vidstab filters (``-filters``).

    A bundled ffmpeg built WITHOUT ``--enable-libvidstab`` will not list the
    filters; this returns False so the caller can surface a typed notice rather
    than silently skipping stabilization. Any spawn failure (no ffmpeg, crash,
    timeout) counts as "not available". ``probe_runner`` is injected in tests.
    """
    runner = probe_runner if probe_runner is not None else subprocess.run
    try:
        argv = build_filters_probe_argv(settings)
    except Exception:  # noqa: BLE001 - no ffmpeg resolvable -> not available
        log.warning("ffmpeg not found for the vidstab availability probe")
        return False
    try:
        completed = runner(argv, capture_output=True, text=True, check=False, timeout=15)
    except Exception:  # noqa: BLE001 - any probe failure == not available
        log.warning("vidstab availability probe failed to spawn ffmpeg")
        return False
    out = (getattr(completed, "stdout", "") or "") + (getattr(completed, "stderr", "") or "")
    return DETECT_FILTER in out and TRANSFORM_FILTER in out


def make_unavailable_notice() -> dict[str, str]:
    """Build the typed notice emitted when libvidstab is missing from ffmpeg.

    Shape: ``{type, message}`` — ``message`` is the human line a job surfaces via
    ``job.progress``. Explicitly states the BUNDLING requirement (the task's
    "do NOT silently skip" rule).
    """
    return {
        "type": STABILIZE_UNAVAILABLE_NOTICE,
        "message": (
            "stabilize: the bundled ffmpeg has no libvidstab (vidstabdetect/"
            "vidstabtransform) — rebuild/bundle ffmpeg with --enable-libvidstab; "
            "stabilization was skipped (the clip is passed through unchanged)"
        ),
    }


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
class StabilizeEngine:
    """Camera-shake stabilization via the vidstab 2-pass ffmpeg flow.

    Seams: ``settings`` carries the ffmpeg path + the vidstab tunables; ``run``
    is the drained ffmpeg runner; ``duration`` probes the source so progress is a
    real percentage; ``probe_runner`` backs the availability check. All injectable
    so tests never spawn ffmpeg.
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self._settings = settings or {}
        self._run: RunFn = run or ffmpeg.run
        self._duration: ProbeFn = duration or ffmpeg.ffprobe_duration
        self._probe_runner = probe_runner

    def available(self) -> bool:
        """True when the resolved ffmpeg supports libvidstab (delegates the probe)."""
        return vidstab_available(self._settings, self._probe_runner)

    def _trf_path(self, out_path: str) -> str:
        """The intermediate transforms-file path beside the output (``<out>.trf``)."""
        return str(Path(out_path).with_suffix(".trf"))

    def stabilize(
        self,
        in_path: str,
        out_path: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Run BOTH vidstab passes; write + return ``out_path``.

        PASS 1 (``vidstabdetect``) writes a .trf next to the output; PASS 2
        (``vidstabtransform``) consumes it. Progress is split 0..50 (detect) /
        50..100 (transform). The .trf is cleaned up afterwards (best-effort). A
        non-zero exit from either pass raises :class:`StabilizeError`. Raises
        :class:`StabilizeError` up front if libvidstab is missing (callers that
        want a soft-skip use :func:`stabilize_clip`).
        """
        if not self.available():
            raise StabilizeError(make_unavailable_notice()["message"])

        # Absolutize in/out so running ffmpeg with cwd=<trf dir> (needed for the
        # bare-basename .trf on Windows, see build_detect_argv) can never misresolve
        # a RELATIVE in/out path against that cwd. The .trf is the only filtergraph-
        # embedded path (bare basename under cwd); in/out are argv and must stay
        # absolute regardless of cwd. No-op for the pipeline's already-absolute paths.
        in_path = os.path.abspath(in_path)
        out_path = os.path.abspath(out_path)

        try:
            total = float(self._duration(in_path, self._settings))
        except Exception:  # noqa: BLE001 - probe failure only coarsens progress
            total = 0.0

        trf_path = self._trf_path(out_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        # ffmpeg runs from the .trf's directory so the filtergraph can reference it
        # by BARE basename — an absolute Windows path's drive colon breaks the -vf
        # parser and no escaping works (see build_detect_argv). in/out paths stay
        # absolute (they are argv, not filtergraph, so cwd does not affect them).
        trf_dir = str(Path(trf_path).parent)

        def _half(lo: float, hi: float) -> Callable[[float, str], None] | None:
            if on_progress is None:
                return None
            cb: Callable[[float, str], None] = on_progress
            return lambda pct, msg: cb(lo + (hi - lo) * (pct / 100.0), msg)

        try:
            # PASS 1 — analyze.
            detect_argv = build_detect_argv(in_path, trf_path, settings=self._settings)
            code = self._run(
                detect_argv,
                total_sec=total,
                on_progress=_half(0.0, 50.0),
                should_cancel=should_cancel,
                cwd=trf_dir,
            )
            if code != 0:
                raise StabilizeError(f"vidstabdetect failed (ffmpeg exit {code}) for {in_path}")

            # PASS 2 — transform.
            transform_argv = build_transform_argv(in_path, trf_path, out_path, settings=self._settings)
            code = self._run(
                transform_argv,
                total_sec=total,
                on_progress=_half(50.0, 100.0),
                should_cancel=should_cancel,
                cwd=trf_dir,
            )
            if code != 0:
                raise StabilizeError(f"vidstabtransform failed (ffmpeg exit {code}) for {in_path}")
        finally:
            try:
                Path(trf_path).unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best-effort cleanup
                log.warning("failed to remove vidstab transforms file %s", trf_path)

        return out_path


# --------------------------------------------------------------------------- #
# pipeline pre-step adapter (used by the reframe / short-maker pipeline)
# --------------------------------------------------------------------------- #
def stabilize_clip(
    in_path: str,
    out_path: str,
    *,
    settings: dict[str, Any] | None = None,
    run: RunFn | None = None,
    duration: ProbeFn | None = None,
    probe_runner: ProbeRunner | None = None,
    on_notice: Callable[[dict[str, str]], None] | None = None,
) -> str:
    """Stabilization pre-step: steady ``in_path`` -> ``out_path``, or pass through.

    The pipeline-facing entry point (the short-maker/reframe pipeline calls this
    BEFORE reframe when ``settings['stabilize']`` is on). When libvidstab is
    available it runs the 2-pass flow and returns ``out_path``; when it is NOT
    available it emits the typed unavailable notice (via ``on_notice`` — the
    orchestrator surfaces it through ``job.progress``) and returns the ORIGINAL
    ``in_path`` unchanged. This is the "do NOT silently skip" contract: the skip
    is always reported, never swallowed.
    """
    engine = StabilizeEngine(settings, run=run, duration=duration, probe_runner=probe_runner)
    if not engine.available():
        notice = make_unavailable_notice()
        log.warning(notice["message"])
        if on_notice is not None:
            on_notice(notice)
        return in_path
    return engine.stabilize(in_path, out_path)


# --------------------------------------------------------------------------- #
# the RPC service (stabilize.run -> a job)
# --------------------------------------------------------------------------- #
class StabilizeService:
    """Owns the ``stabilize.run`` RPC over the library/exports seams."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | os.PathLike,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        run: RunFn | None = None,
        duration: ProbeFn | None = None,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._run = run
        self._duration = duration
        self._probe_runner = probe_runner

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
        """``stabilize.run({videoId|path})`` -> ``{jobId}`` (streams to ``{path}``).

        ``job.done.result`` is ``{path, stabilized: bool[, notice]}``: ``path`` is
        the steadied clip when libvidstab is present, else the source path with a
        typed ``notice`` (the unavailable case is REPORTED, never silently
        skipped). Cooperative-cancel aware via the drained ``run`` seam.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve(params)
        settings = self._settings()
        run = self._run
        duration = self._duration
        probe_runner = self._probe_runner
        out_dir = self._out_dir

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            engine = StabilizeEngine(settings, run=run, duration=duration, probe_runner=probe_runner)
            if not engine.available():
                notice = make_unavailable_notice()
                job_ctx.progress(100, notice["message"])
                return {"path": in_path, "stabilized": False, "notice": notice}
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(in_path).stem or "clip"
            out_path = str(out_dir / f"{stem}.stabilized.mp4")
            engine.stabilize(
                in_path,
                out_path,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            return {"path": out_path, "stabilized": True}

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
    probe_runner: ProbeRunner | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> StabilizeService:
    """Create the service and register ``stabilize.run`` (mirrors shorts.register).

    ``register_fn`` defaults to :func:`protocol.register` (duplicates fail loudly);
    tests inject a fake registrar. Returns the service for the caller to hold.
    """
    service = StabilizeService(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        run=run,
        duration=duration,
        probe_runner=probe_runner,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("stabilize.run", service.run)
    log.info("registered stabilize.run")
    return service


__all__ = [
    "DEFAULT_ACCURACY",
    "DEFAULT_OPTZOOM",
    "DEFAULT_SHAKINESS",
    "DEFAULT_SMOOTHING",
    "DETECT_FILTER",
    "STABILIZE_UNAVAILABLE_NOTICE",
    "TRANSFORM_FILTER",
    "StabilizeEngine",
    "StabilizeError",
    "StabilizeService",
    "build_detect_argv",
    "build_filters_probe_argv",
    "build_transform_argv",
    "make_unavailable_notice",
    "register",
    "stabilize_clip",
    "vidstab_available",
]
