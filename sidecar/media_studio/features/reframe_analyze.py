"""``reframe.analyze`` + ``reframe.render`` — the trace PRODUCER, its cache, and
the edited-plan re-render (WU-E1 / WU-E2 / WU-E3).

WHAT WAS MISSING. The multi-speaker engine could only ever
:meth:`~media_studio.features.reframe_multispeaker.MultiSpeakerReframeEngine.reframe`
— analyse, build a trace in-process, render a file, throw the trace away. So the
two R2 override RPCs that make an imperfect active-speaker result shippable were
unreachable in the shape the edit loop needs: ``reframe.shotPlan`` consumes a
trace nothing produced over the wire, and an edited :class:`~media_studio.features.reframe_override.ShotPlan`
had no renderer at all. This module adds the three missing pieces, in the spec's
strict order (producer -> cache -> edited-plan render):

* **WU-E1 ``reframe.analyze``** — a GPU job that runs the staged backend and the
  pure director and returns ``{trace, plan, degraded}`` **without rendering**.
* **WU-E2 the analysis cache** — an injectable, size-bounded store keyed by
  ``(videoId, aspect, allowSplit, allowComposite)``, so editing a shot does not
  re-run the multi-minute GPU analysis.
* **WU-E3 ``reframe.render``** — a job that renders an EDITED plan, re-encoding
  only the shots whose decision changed and concat-copying the rest, over the
  cached analysis.

**SCOPE, STATED PLAINLY.** This is the BACKEND only. Both methods are registered
but NOT user-reachable: the UI wave (WU-U1..U4 — the per-shot editable timeline,
the speaker ribbon, the "re-render changed shots" button) is a separate work unit
and is not in this change. Nothing here makes active-speaker editing available to
users. And per the plan's own warning, the 100%-branch unit coverage of this
module is measured entirely against a FAKE backend and a FAKE ffmpeg runner:
**coverage is not integration**, and none of it is evidence that the pipeline
works on real media.
"""

from __future__ import annotations

import shutil
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import clamp, get_logger
from . import aspect as _aspect
from . import offline as _offline
from . import reframe_multispeaker as _ms
from . import reframe_override as _override
from .reframe_eval import ReframeTrace

log = get_logger("media_studio.features.reframe_analyze")

#: The default export aspect (mirrors the engines).
DEFAULT_ASPECT = _ms.DEFAULT_ASPECT

#: How many analysis bundles the default in-memory cache retains. A bundle holds
#: the per-frame arrays for one clip, so the bound is what keeps an edit session
#: over several clips from growing without limit.
DEFAULT_CACHE_ENTRIES = 4

Resolver = Callable[[str], str | None]
EngineFactory = Callable[[dict[str, Any]], Any]


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


# --------------------------------------------------------------------------- #
# WU-E2 — the analysis cache (pure, injectable, size-bounded)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AnalysisKey:
    """What makes two analyses interchangeable.

    ``aspect`` changes the crop geometry and ``allow_split`` / ``allow_composite``
    change the LAYOUT decisions, so all four fields are part of the identity of a
    cached bundle (a trace built with ``allowSplit=False`` is not a valid answer
    for a request that allows splits).
    """

    video_id: str
    aspect: str
    allow_split: bool
    allow_composite: bool


@dataclass(frozen=True)
class AnalysisBundle:
    """One clip's analysis + everything derived from it that the edit loop needs."""

    analysis: _ms.ShotAnalysis
    trace: ReframeTrace
    plan: _override.ShotPlan


class AnalysisStore(Protocol):
    """The cache seam. Production uses :class:`LruAnalysisCache` (in-memory).

    An on-disk store is the DECLARED-OPTIONAL half of WU-E2 and is deliberately
    NOT implemented here — this Protocol is the seam it would slot into. So a
    sidecar restart loses the cache, and the next ``reframe.render`` for that clip
    refuses (loudly) until ``reframe.analyze`` runs again.
    """

    def get(self, key: AnalysisKey) -> AnalysisBundle | None:
        """The bundle stored under ``key``, or ``None``."""
        ...  # pragma: no cover - Protocol stub

    def put(self, key: AnalysisKey, bundle: AnalysisBundle) -> None:
        """Store ``bundle`` under ``key`` (evicting if the store is full)."""
        ...  # pragma: no cover - Protocol stub

    def find(self, video_id: str, aspect: str) -> AnalysisBundle | None:
        """The most recent bundle for ``video_id`` at ``aspect``, ignoring flags."""
        ...  # pragma: no cover - Protocol stub


class LruAnalysisCache:
    """A bounded least-recently-used in-memory :class:`AnalysisStore`.

    NOT internally synchronised. It is safe in THIS wiring because both
    ``reframe.analyze`` and ``reframe.render`` are started with ``gpu=True`` and
    :class:`~media_studio.jobs.JobRegistry` serialises gpu-tagged jobs to
    ``max_gpu_workers`` (default 1), so at most one job body touches the store at a
    time. That is a property of the CALLER, not of this class — wrap it if you ever
    reach it from concurrently-running work.
    """

    def __init__(self, max_entries: int = DEFAULT_CACHE_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max = int(max_entries)
        self._items: OrderedDict[AnalysisKey, AnalysisBundle] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def get(self, key: AnalysisKey) -> AnalysisBundle | None:
        """The bundle under ``key`` (refreshing its recency), or ``None``."""
        bundle = self._items.get(key)
        if bundle is None:
            return None
        self._items.move_to_end(key)
        return bundle

    def put(self, key: AnalysisKey, bundle: AnalysisBundle) -> None:
        """Store ``bundle``, evicting the least-recently-used entries past the bound."""
        self._items[key] = bundle
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def find(self, video_id: str, aspect: str) -> AnalysisBundle | None:
        """The most recent bundle for ``video_id`` at ``aspect``, whatever its flags.

        ``reframe.render``'s params carry ``{videoId, plan, aspect, affectedOnly}``
        and deliberately NOT the layout flags — the caller edits a plan, it does not
        re-declare how the plan was produced. It only needs the TRACE, whose
        per-frame speakers and crops do not depend on ``allow_split`` /
        ``allow_composite`` (those only steer :func:`~media_studio.features.reframe_multispeaker.decide_layout`).
        So a flag-insensitive lookup is both sufficient and correct here, while
        :meth:`get` keeps the full four-field identity for the producer.
        """
        for key in reversed(self._items):
            if key.video_id == video_id and key.aspect == aspect:
                return self.get(key)
        return None


def build_bundle(
    analysis: _ms.ShotAnalysis,
    *,
    aspect: str,
    allow_split: bool,
    allow_composite: bool,
) -> AnalysisBundle:
    """PURE: a :class:`~media_studio.features.reframe_multispeaker.ShotAnalysis` ->
    its trace + the editable per-shot plan derived from it."""
    trace = _ms.build_trace(analysis, aspect=aspect, allow_split=allow_split, allow_composite=allow_composite)
    plan = _override.plan_from_trace(
        trace,
        source_width=analysis.width,
        source_height=analysis.height,
        fps=float(analysis.fps),
    )
    return AnalysisBundle(analysis=analysis, trace=trace, plan=plan)


# --------------------------------------------------------------------------- #
# param helpers (the boundary guard — loud, never a silently-ignored field)
# --------------------------------------------------------------------------- #
def _require_video_id(params: dict[str, Any]) -> str:
    video_id = params.get("videoId")
    if not isinstance(video_id, str) or not video_id:
        raise _invalid("videoId (str) is required")
    return video_id


def _optional_bool(params: dict[str, Any], field: str, default: bool) -> bool:
    value = params.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _invalid(f"{field} must be a boolean when given")
    return value


def _optional_aspect(params: dict[str, Any]) -> str:
    value = params.get("aspect")
    if value is None:
        return DEFAULT_ASPECT
    if not isinstance(value, str):
        raise _invalid("aspect must be a string when given")
    try:
        return _aspect.require_supported_aspect(value)
    except ValueError as exc:
        raise _invalid(f"aspect is not supported: {exc}") from exc


def _default_engine_factory(settings: dict[str, Any]) -> Any:
    """Build the real multi-speaker engine (its own heavy seams stay lazy)."""
    return _ms.MultiSpeakerReframeEngine(settings)


# --------------------------------------------------------------------------- #
# WU-E1 / WU-E3 — the service
# --------------------------------------------------------------------------- #
class ReframeAnalyzeService:
    """Owns ``reframe.analyze`` + ``reframe.render`` over injectable seams.

    Seams: ``resolver`` (videoId -> media path), ``out_dir`` (where a re-render
    lands), ``settings_provider``, ``cache`` (the WU-E2 store), ``engine_factory``
    (builds the engine, whose own ``backend_factory`` / ``runner`` seams the tests
    fake), and ``which`` / ``models_present`` (the cheap host-availability probes).
    """

    def __init__(
        self,
        *,
        resolver: Resolver,
        out_dir: str | Path,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        cache: AnalysisStore | None = None,
        engine_factory: EngineFactory | None = None,
        which: _ms.WhichFn = shutil.which,
        models_present: _ms.ModelsPresent | None = None,
    ) -> None:
        self._resolver = resolver
        self._out_dir = Path(out_dir)
        self._settings_provider = settings_provider or (lambda: {})
        self._cache: AnalysisStore = cache if cache is not None else LruAnalysisCache()
        self._engine_factory: EngineFactory = engine_factory or _default_engine_factory
        self._which = which
        self._models_present = models_present

    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, params: dict[str, Any]) -> tuple[str, str]:
        video_id = _require_video_id(params)
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        return video_id, str(resolved)

    def analyze(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``reframe.analyze({videoId, aspect?, allowSplit?, allowComposite?,
        allowDegrade?, diarizeBackend?})`` -> ``{jobId}`` (a GPU job).

        ``job.done.result`` is ``{trace, plan, degraded}``: the per-frame trace and
        the editable per-shot plan, with **no file rendered**. The typed failure
        contract mirrors the engine's:

        * host cannot run it + EXPLICIT request -> a typed RPC error naming the real
          cause (the engine's :class:`~media_studio.features.reframe_multispeaker.MultiSpeakerUnavailableError`
          message, mapped onto INVALID_PARAMS so it reaches the UI verbatim);
        * offline mode ON + host cannot run it -> :class:`~media_studio.features.offline.OfflineError`
          (the actionable message — a download is what is blocked);
        * ``allowDegrade`` -> ``{trace: null, plan: null, degraded: <notice>}``. There
          is deliberately no claudeshorts fall-back here: the single-speaker engine
          produces no trace, so inventing a plan would be worse than an HONEST empty
          state (the same choice ``reframe.shotPlanFor`` makes for a clip with no
          sidecar).
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id, in_path = self._resolve(params)
        aspect = _optional_aspect(params)
        allow_split = _optional_bool(params, "allowSplit", True)
        allow_composite = _optional_bool(params, "allowComposite", True)
        allow_degrade = _optional_bool(params, "allowDegrade", False)
        settings = self._settings()
        diarize_backend = params.get("diarizeBackend")
        if diarize_backend is not None:
            if not isinstance(diarize_backend, str) or not diarize_backend:
                raise _invalid("diarizeBackend must be a non-empty string when given")
            # The backend selector reads settings['diarizeBackend'] (diarize.py's
            # eager, typed validation), so overlaying it here is the whole wiring.
            settings = {**settings, "diarizeBackend": diarize_backend}

        reason = _ms.availability_reason(settings, which=self._which, models_present=self._models_present)
        if reason is not None:
            # Offline is a DIFFERENT, actionable cause than a missing GPU.
            _offline.guard_network(settings, "the multi-speaker reframe models")
            if not allow_degrade:
                raise _invalid(f"multi-speaker reframe engine requested but unavailable: {reason}")

        key = AnalysisKey(video_id=video_id, aspect=aspect, allow_split=allow_split, allow_composite=allow_composite)
        cache = self._cache
        engine_factory = self._engine_factory

        def job_body(job_ctx: Any) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            if reason is not None:
                notice = _ms.make_engine_degrade_notice(reason)
                job_ctx.progress(100.0, notice["message"])
                return {"trace": None, "plan": None, "degraded": notice}
            cached = cache.get(key)
            if cached is not None:
                job_ctx.progress(100.0, "reused the cached analysis")
                return _analysis_result(cached)
            job_ctx.progress(2.0, "detecting shots")
            analysis = engine_factory(settings).analyze(
                in_path,
                # The staged backend owns the shots -> diarize -> faces/ASD
                # messages; clamping to 90 leaves room for the plan stage so a
                # backend that reports 100% cannot make the job look finished.
                on_progress=lambda pct, msg: job_ctx.progress(clamp(pct, 0.0, 90.0), msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            job_ctx.raise_if_cancelled()
            job_ctx.progress(92.0, "building the shot plan")
            bundle = build_bundle(analysis, aspect=aspect, allow_split=allow_split, allow_composite=allow_composite)
            cache.put(key, bundle)
            job_ctx.progress(100.0, "done")
            return _analysis_result(bundle)

        job = ctx.jobs.start(job_body, feature="reframe", label="reframe.analyze", videoId=video_id, gpu=True)
        return {"jobId": job.id}

    def render(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``reframe.render({videoId, plan, aspect?, affectedOnly?})`` -> ``{jobId}``.

        ``job.done.result`` is ``{outPath, affected, reencoded}``. ``affected`` is
        the shots the caller's plan changed relative to the cached analysis (the
        same set :func:`~media_studio.features.reframe_override.affected_shot_indices`
        computes for ``reframe.applyOverrides``); ``reencoded`` is what actually had
        to be re-encoded, which is a SUPERSET of ``affected`` on a first render
        because no segment pieces exist to reuse yet.

        A cache MISS is loud: without the analysis there is no trace, so the
        split/composite cells could not be placed. It refuses and names
        ``reframe.analyze`` rather than silently re-running a multi-minute GPU pass
        the caller did not ask for.

        An EMPTY ``affected`` set is NOT an error — re-rendering the unedited plan
        is exactly how the first file gets produced after an analyze.

        The output path is composed from ``video_id``, so it is deliberately built
        only AFTER :meth:`_resolve` proved the id is a real library record (the
        library lookup is what keeps a caller-supplied id from steering the write
        outside ``out_dir``); mirrors the ``shorts`` out-dir convention.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id, in_path = self._resolve(params)
        aspect = _optional_aspect(params)
        affected_only = _optional_bool(params, "affectedOnly", True)
        try:
            edited = _override.ShotPlan.from_dict(params.get("plan"))
        except _override.OverrideError as exc:
            raise _invalid(f"plan is not a valid shot plan: {exc}") from exc
        bundle = self._cache.find(video_id, aspect)
        if bundle is None:
            raise _invalid(
                f"no cached reframe analysis for {video_id} at {aspect} — run reframe.analyze before rendering an edit"
            )
        try:
            affected = _override.affected_shot_indices(bundle.plan, edited)
        except _override.OverrideError as exc:
            raise _invalid(f"the edited plan does not describe the analysed shots: {exc}") from exc

        settings = self._settings()
        out_dir = self._out_dir
        engine_factory = self._engine_factory
        trace = bundle.trace

        def job_body(job_ctx: Any) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(out_dir / f"{video_id}.multispeaker.mp4")
            job_ctx.progress(2.0, f"re-rendering {len(affected)} changed shot(s)")
            rendered, reencoded = engine_factory(settings).render_shot_plan(
                in_path,
                out_path,
                edited,
                trace,
                aspect=aspect,
                affected_only=affected_only,
                on_progress=lambda pct, msg: job_ctx.progress(clamp(pct, 0.0, 99.0), msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            job_ctx.progress(100.0, "done")
            return {"outPath": rendered, "affected": list(affected), "reencoded": list(reencoded)}

        job = ctx.jobs.start(job_body, feature="reframe", label="reframe.render", videoId=video_id, gpu=True)
        return {"jobId": job.id}


def _analysis_result(bundle: AnalysisBundle) -> dict[str, Any]:
    """The ``reframe.analyze`` job payload for a successful analysis."""
    return {
        "trace": _override.trace_to_dict(bundle.trace),
        "plan": bundle.plan.to_dict(),
        "degraded": None,
    }


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register(
    *,
    resolver: Resolver,
    out_dir: str | Path,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    cache: AnalysisStore | None = None,
    engine_factory: EngineFactory | None = None,
    which: _ms.WhichFn = shutil.which,
    models_present: _ms.ModelsPresent | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> ReframeAnalyzeService:
    """Create the service and register ``reframe.analyze`` + ``reframe.render``.

    ``register_fn`` defaults to :func:`protocol.register` (a duplicate name fails
    loudly at startup); tests inject a fake registrar + fake seams.
    """
    service = ReframeAnalyzeService(
        resolver=resolver,
        out_dir=out_dir,
        settings_provider=settings_provider,
        cache=cache,
        engine_factory=engine_factory,
        which=which,
        models_present=models_present,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("reframe.analyze", service.analyze)
    reg("reframe.render", service.render)
    log.info("registered reframe.analyze + reframe.render")
    return service


__all__ = [
    "DEFAULT_ASPECT",
    "DEFAULT_CACHE_ENTRIES",
    "AnalysisBundle",
    "AnalysisKey",
    "AnalysisStore",
    "LruAnalysisCache",
    "ReframeAnalyzeService",
    "build_bundle",
    "register",
]
