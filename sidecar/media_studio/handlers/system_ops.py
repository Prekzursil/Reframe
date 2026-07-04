# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): System probe/advisor/recommend + Phase-8 signal handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from ..features import offline as _offline
from ..protocol import ErrorCode, RpcContext, RpcError
from ._shared import (
    Candidate,
    _invalid,
    _require_str,
)
from ._wire import (
    _COMPONENT_ASSETS,
    _advisor_report_to_wire,
    _coerce_tier,
    _run_phase8_signals,
    _self_ffprobe,
    _self_test_report_to_wire,
    _signals_summary,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def system_probe(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``system.probe()`` -> ``{vramMb, ramMb, cpuCount, gpuPresent}``. Direct-return.

    Probes the host hardware (GPU VRAM / RAM / CPU count) via the injectable
    :class:`~media_studio.features.system_advisor.HardwareProbe` seam. Every
    probe is fail-open (a missing dep degrades to ``None``), so this never
    raises. The default seam lazily tries pynvml -> nvidia-smi -> torch.cuda
    for VRAM and psutil -> os for RAM; tests inject a fake probe.
    """
    probe = self._hardware_probe or self._default_hardware_probe()
    hw = probe.detect()
    return {
        "vramMb": hw.vram_mb,
        "ramMb": hw.ram_mb,
        "cpuCount": hw.cpu_count,
        "gpuPresent": hw.gpu_present,
        # WU-models/device: free disk on the data drive feeds the device+ETA
        # status strip (how much room is left for model downloads).
        "diskFreeMb": hw.disk_free_mb,
    }


def system_advisor(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``system.advisor({commercial?})`` -> AdvisorReport JSON. Direct-return.

    The "Models & System" panel brain: probes hardware + dependency
    availability, checks which model weights are already installed (the asset
    manager), and returns each component's quality-vs-cost verdict + the rolled
    -up runnable tiers + the recommended preset. Honors Offline mode (a missing
    weight that would need a download counts as unavailable). Pure decision
    logic; nothing heavy is imported.
    """
    from ..features import system_advisor as _sa  # local: import-light

    settings = self.settings.get()
    commercial = bool(params.get("commercial", settings.get("commercial")))
    probe = self._hardware_probe or self._default_hardware_probe()
    report = _sa.advise_for_hardware(
        probe=probe,
        commercial=commercial,
        models_present=self._models_present_map(settings),
        offline=_offline.is_offline(settings),
    )
    return _advisor_report_to_wire(report)


def asr_engines(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``asr.engines()`` -> ``{engines:[{id, label, installed}]}``. Direct-return.

    Lists the selectable ASR engines (whisper default / parakeet opt-in) with
    an installed flag per engine (drives the ASR picker UI). Whisper is treated
    as always available (the always-installed default); parakeet's installed
    flag reflects whether its weights are cached.
    """
    settings = self.settings.get()
    installed = self._models_present_map(settings)
    return {
        "engines": [
            {"id": "whisper", "label": "Whisper large-v3-turbo", "installed": True},
            {
                "id": "parakeet",
                "label": "Parakeet-TDT-0.6b-v3 (multilingual)",
                "installed": bool(installed.get("parakeet", False)),
            },
        ]
    }


def _detect_local_servers(self: Services, settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect locally-running Ollama / LM Studio servers (fail-open).

    Uses the injected ``local_detector`` seam when present (tests inject a fake
    returning canned PoolEntry dicts); otherwise runs the real
    :func:`local_detect.detect_local_servers` over the stdlib urllib GET
    transport. Detection is best-effort: it returns ``[]`` (never raises) when
    no local server answers.
    """
    if self._local_detector is not None:
        return list(self._local_detector(settings))
    from ..models import local_detect as _local_detect  # local: import-light
    from ..models import provider as _provider_mod  # local: heavy seam

    return cast(
        "list[dict[str, Any]]",
        list(_local_detect.detect_local_servers(settings, transport=_provider_mod.urllib_get_json)),
    )


def system_recommend(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``system.recommend({commercial?})`` -> ``{recommendation:{...}}``. Direct-return.

    The "Recommended for your machine" brain: composes the EXISTING cheap probes
    — hardware advisor (:func:`system_advisor.advise_for_hardware`), the
    installed-state map (:meth:`_models_present_map`), the detected local servers
    (:func:`local_detect.detect_local_servers`), and the ASR-engine list — then
    runs the PURE :func:`recommender.recommend` over them to produce an
    actionable plan. Composes probes ONLY: NO provider/LLM call is ever made
    here (it is a direct-return RPC, DESIGN §2.3). Honors Offline mode
    (forwarded from :func:`offline.is_offline`) and the ``commercial`` flag.
    A malformed/empty advisor report yields the G-B1 "unavailable"
    recommendation (recommender's typed fallback), never an exception.
    """
    from ..features import recommender as _recommender  # local: import-light pure
    from ..features import system_advisor as _sa  # local: import-light

    settings = self.settings.get()
    commercial = bool(params.get("commercial", settings.get("commercial")))
    offline = _offline.is_offline(settings)
    present = self._models_present_map(settings)
    probe = self._hardware_probe or self._default_hardware_probe()
    report = _advisor_report_to_wire(
        _sa.advise_for_hardware(
            probe=probe,
            commercial=commercial,
            models_present=present,
            offline=offline,
        )
    )
    detected_local = self._detect_local_servers(settings)
    asr_engines = self.asr_engines(params, ctx)
    recommendation = _recommender.recommend(
        report,
        present,
        detected_local,
        asr_engines,
        offline=offline,
        commercial=commercial,
    )
    return {"recommendation": recommendation}


def models_runners(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``models.runners()`` -> ``{whisper, llm, runners:[...]}``. Direct-return.

    The local-model brain for the "Models & System" panel (WU-models/device):
    composes the cheap hardware probe (:meth:`system_probe`) + the detected
    Ollama / LM Studio servers (:meth:`_detect_local_servers`) into a PURE
    :func:`model_recommend.recommend_local_models` plan — a DEVICE-RANKED whisper
    + LLM recommendation ("X because RAM/VRAM Y") and per-runner advice (running?
    which models? the device-fit model to pull + a copy-able pull hint; when
    absent, the official install link — advice only, NEVER an auto-install).
    Composes probes ONLY: no LLM/provider call, no pull is triggered here.
    """
    from ..models import model_recommend as _mr  # local: import-light pure

    hardware = self.system_probe(params, ctx)
    detected_local = self._detect_local_servers(self.settings.get())
    plan = _mr.recommend_local_models(hardware, detected_local)
    return cast("dict[str, Any]", plan)


def models_overview(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``models.overview({commercial?})`` -> the unified Models&System screen. Direct.

    M1a — the THIN compose RPC the "Models & System" panel renders as ONE screen
    (DESIGN §2.3 step 2): it stitches the EXISTING cheap probes/handlers together
    with NO new model logic. The shape is
    ``{hardware, tiers, recommendedPreset, runners, localPlan, providers, keyPool,
    routingPolicy}``:

      * ``hardware`` — :meth:`system_probe` (VRAM/RAM/CPU/GPU/disk).
      * ``tiers`` / ``recommendedPreset`` — the :meth:`system_advisor` report's
        rolled-up tiers + the recommended preset (``commercial`` honored).
      * ``runners`` — the detected Ollama / LM Studio servers (``detect``).
      * ``localPlan`` — the PURE :func:`model_recommend.recommend_local_models`
        device-ranked whisper + LLM + per-runner pull/install advice.
      * ``providers`` — the REDACTED :meth:`providers_list` (last-4 keys only).
      * ``keyPool`` — the per-key rows derived from those redacted providers
        (:func:`key_pool.build_key_pool`); M4 enriches them with live usage.
      * ``routingPolicy`` — the persisted policy read FAIL-CLOSED to ``local``
        (:func:`routing_policy.read_routing_policy`; GATE-2 zero-egress).
      * ``eligibility`` — M2: when an Ollama runner is detected, its REAL
        ``/api/*`` metadata (quant + VRAM estimate + capability gate, deduped by
        digest) drives the device-fit LLM ranking; with no runner it degrades to
        the static-ladder ``fallback`` (:func:`ollama_meta.eligibility_for_runners`).
        Feeds the "using X because Y" reason strip's real-quant copy.

    Composes probes/reads ONLY: ZERO provider/LLM calls, NO pull, and NO settings
    mutation (a strictly read-only screen). No full key ever crosses RPC.
    """
    from ..models import key_pool as _key_pool  # local: import-light pure
    from ..models import model_recommend as _mr  # local: import-light pure
    from ..models import ollama_meta as _ollama_meta  # local: import-light pure
    from ..models import routing_policy as _routing_policy  # local: import-light pure

    settings = self.settings.get()  # REDACTED view (providers' keys already last-4)
    hardware = self.system_probe(params, ctx)
    advisor = self.system_advisor(params, ctx)
    detected_local = self._detect_local_servers(settings)
    local_plan = _mr.recommend_local_models(hardware, detected_local)
    providers = self.providers_list(params, ctx)["providers"]
    transport = self._ollama_meta_transport or self._default_ollama_meta_transport()
    eligibility = _ollama_meta.eligibility_for_runners(detected_local, hardware, transport)
    return {
        "hardware": hardware,
        "tiers": advisor["tiers"],
        "recommendedPreset": advisor["recommendedPreset"],
        "runners": detected_local,
        "localPlan": local_plan,
        "providers": providers,
        "keyPool": _key_pool.build_key_pool(providers),
        "routingPolicy": _routing_policy.read_routing_policy(settings),
        "eligibility": eligibility,
    }


def models_set_routing_policy(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``models.setRoutingPolicy({global?, overrides?})`` -> ``{routingPolicy}``. WRITE.

    M3 — the WRITE half of the single ``RoutingPolicy`` store the M1a read
    (:func:`routing_policy.read_routing_policy`) surfaces. The header toggle sends
    ``{global}``; the Advanced per-function table sends ``{overrides}``. The
    incoming candidate is run through :func:`routing_policy.sanitize_routing_policy`
    BEFORE persistence so the SAME fail-closed clamp protects the write as the
    read: an out-of-enum (or corrupt) ``global`` / override mode is forced to
    ``local`` (zero silent cloud egress, GATE-2) and a non-string override key is
    dropped — the handler NEVER raises on a malformed body, it clamps.

    Persistence is the existing :class:`settings_store.SettingsStore` ``set`` (a
    partial top-level merge whose ``_write`` is an atomic temp-file +
    ``os.replace`` — mirrors ``library._write_json``), so a half-written file can
    never be observed. The DECISION §4 default (``global:'local'``, no auto-
    promote) is unchanged: the toggle only ever moves on an explicit user write.
    Returns the persisted, sanitised policy so the UI reflects exactly what landed
    on disk (never the raw request).
    """
    from ..models import routing_policy as _routing_policy  # local: import-light pure

    policy = _routing_policy.sanitize_routing_policy(params)
    self.settings.set({"routingPolicy": policy})
    return {"routingPolicy": policy}


def models_resolve_route(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``models.resolveRoute({fn?})`` -> the CONCRETE per-function route(s). Direct.

    M5 (DESIGN §2.3 step 4) — the concrete second half of routing resolution. It
    composes the read-only :meth:`models_overview` (local plan + detected runners +
    redacted providers) ONCE, then runs the PURE
    :func:`routing_resolve.resolve_concrete_route` to answer, per AI function,
    ``{mode, model, runner|provider}``. A ``cloud`` / ``auto`` function with no key
    on disk degrades LOUDLY to local (``degraded=True`` +
    :data:`routing_resolve.ROUTE_DEGRADED_NOTICE`), never a silent cloud route.

    With a non-empty string ``fn`` it returns ``{route}`` for that one function
    (the per-job call); otherwise ``{routes}`` for every canonical
    :data:`routing_resolve.AI_FUNCTIONS` (the Advanced override-table preview).
    Composes reads ONLY: ZERO provider/LLM calls, NO mutation, no full key crosses
    RPC (the overview's providers are already redacted to last-4).
    """
    from ..models import routing_resolve as _routing_resolve  # local: import-light pure

    settings = self.settings.get()
    overview = self.models_overview(params, ctx)
    fn = params.get("fn")
    if isinstance(fn, str) and fn:
        return {"route": _routing_resolve.resolve_concrete_route(fn, settings, overview)}
    return {"routes": _routing_resolve.resolve_all_routes(settings, overview)}


def system_self_test(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``system.selfTest()`` -> the first-run diagnostic report. Direct-return.

    WU-2: validates a fresh install END-TO-END and reports LOUDLY so the app
    never proceeds into a broken render. Composes the PURE
    :func:`self_test.run` over the runtime services — the data-dir writability
    probe (write+read+delete under :attr:`data_dir`), the hardware probe seam
    (:class:`HardwareProbe`, the SAME one ``system.probe``/``advisor`` use), the
    native-dependency import map (cv2/mediapipe for reframe + the faster-whisper
    ASR backend, via ``importlib.find_spec`` — nothing heavy is imported), and
    the ffmpeg/ffprobe chain (:func:`tools_resolver.resolve_tool`). Every probe
    is fail-open: a failure becomes a reported problem + fix hint, never an
    exception. Returns the camelCase wire report the setup-status panel renders.
    """
    from .. import tools_resolver as _tools_resolver  # local: import-light (registers tool assets)
    from ..features import self_test as _self_test  # local: import-light pure

    settings = self.settings.get()
    probe = self._hardware_probe or self._default_hardware_probe()
    report = _self_test.run(
        data_dir=self.data_dir,
        hardware_probe=probe,
        resolve_tool=lambda name: _tools_resolver.resolve_tool(name, settings),
    )
    return _self_test_report_to_wire(report)


def phase8_signals(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``phase8.signals({videoId, tier?})`` -> ``{jobId}``. Job-based.

    Runs the enabled Wave-1 signal modules at the chosen tier over the video's
    media and returns a per-channel summary + a present map. Heavy (loads ML
    models), so it runs on ``ctx.jobs`` and the heavy compute lives behind the
    injectable :func:`phase8_runner` seam (tests inject a fake that returns
    canned tracks). ``job.done.result`` is ``{tracks, present}``.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    path = self._resolve_video_path(video_id)
    if not path:
        raise _invalid(f"unknown video: {video_id}")
    settings = self.settings.get()
    tier = _coerce_tier(params.get("tier"), settings)
    runner = self._phase8_runner or self._default_phase8_runner()
    probe = self._ffprobe_duration or _self_ffprobe()

    def job_body(job_ctx: Any) -> dict[str, Any]:
        tracks = runner(
            path,
            tier=tier,
            settings=settings,
            duration_probe=probe,
            on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
            should_cancel=lambda: job_ctx.cancelled,
        )
        return _signals_summary(tracks)

    job = ctx.jobs.start(job_body)
    return {"jobId": job.id}


def phase8_select(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``phase8.select({videoId, prompt?, controls?, tier?})`` -> ``{jobId}``. Job-based.

    The unified tri-modal selector: computes the Wave-1 signal tracks (via the
    phase8 runner seam), then calls :func:`select.select_unified` with those
    tracks + the persisted transcript + the chosen tier. Caches the resulting
    candidates server-side (the same "rank@sourceStart" cache shortmaker.export
    consults) and returns ``{candidates}`` on done. Coexists with the legacy
    transcript-only ``shortmaker.select``.
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    path = self._resolve_video_path(video_id)
    if not path:
        raise _invalid(f"unknown video: {video_id}")
    settings = self.settings.get()
    tier = _coerce_tier(params.get("tier"), settings)
    prompt = str(params.get("prompt") or "")
    controls = params.get("controls") or {}
    transcript = self._load_or_create_project(video_id).data.get("transcript")
    runner = self._phase8_runner or self._default_phase8_runner()
    probe = self._ffprobe_duration or _self_ffprobe()

    def work(job_ctx: Any, _envelope: Any, provider: Any) -> dict[str, Any]:
        from ..features import select as _select  # local: import-light

        # WU-vision: resolve the Tier-2 vlm_reranker FIRST — the frame-egress
        # consent gate runs BEFORE any frame is sampled/encoded (a no-consent
        # run never prepares a frame for egress). tier<2 skips the re-rank
        # entirely (so no vision pool is built / no consent read). Cloud-vision
        # + frame consent -> a CloudVlmBackend closure over the vision pool;
        # else local weights -> the local reranker; else None (transcript-only).
        vlm_reranker = self._resolve_vlm_reranker(settings, media_path=path) if tier >= 2 else None
        tracks = runner(
            path,
            tier=tier,
            settings=settings,
            duration_probe=probe,
            on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
            should_cancel=lambda: job_ctx.cancelled,
        )
        candidates = _select.select_unified(
            transcript,
            prompt,
            cast("Any", controls),
            provider,
            tracks=tracks,
            tier=tier,
            vlm_reranker=vlm_reranker,
        )
        resolved = cast("list[Candidate]", list(candidates))
        self._cache_candidates(video_id, resolved)
        return {"candidates": resolved}

    # WU-envelope: the AI re-rank/select rides the AiJob substrate so it gets
    # the shared cancel-check + degrade-aware provider + (later) cost/cache
    # while preserving the {jobId} shape and the {candidates} done payload.
    # WU-presets: the select seam honors routing.perFunction["select"] — its
    # rotation pool tries the routed provider first (local-only when routed to
    # LOCAL). A legacy injected provider (tests) still wins. OFFLINE GATE: when
    # offline, the provider is forced LOCAL-only so select_unified's chat egress
    # is refused (no cloud primary, no 429 cloud failover).
    select_provider = self._select_provider_or_local()
    job = self._run_ai_job(
        ctx,
        messages=[{"role": "user", "content": prompt}],
        model=str(settings.get("cloudModel") or ""),
        provider=select_provider,
        work=work,
        feature="phase8",
        label="phase8.select",
        videoId=video_id,
        ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
    )
    return {"jobId": job.id}


def _models_present_map(self: Services, settings: dict[str, Any]) -> dict[str, bool]:
    """Map each model-backed advisor component -> is its weight installed.

    Probes the asset manager for each Phase-8 component's pinned asset so the
    advisor (and the ASR picker) can report installed-state + degrade an
    offline-missing model. Components with no registered asset are omitted
    (the advisor then treats them as not-installed). Fail-open: a probe error
    for one component marks it absent, never crashes the report.
    """
    from ..assets import manifest as _manifest  # local: import-light
    from ..assets.manager import AssetManager  # local: import-light

    mgr = AssetManager(root=self.data_dir, settings_provider=lambda: settings)
    present: dict[str, bool] = {}
    for component, asset_name in _COMPONENT_ASSETS.items():
        entry = _manifest.get_asset(asset_name)
        if entry is None:
            continue
        try:
            present[component] = mgr.installed_path(entry) is not None
        except Exception:  # noqa: BLE001 - one bad probe must not sink the report
            present[component] = False
    return present


def _installed_asset_names(self: Services, settings: dict[str, Any]) -> set[str]:
    """The set of installed WU-C2 capability assets (read-only probe).

    Resolves installed-state for exactly the ``_capabilities.capability_asset_names``
    set (the reframe tracker + the on-demand saliency/scene weights) so
    ``readiness.summary`` can roll the feature-capability family up. A de-registered
    capability asset is skipped (never probed); fail-open per asset. Read-only: it
    only asks ``installed_path`` (an ``is_file`` check), so it NEVER creates the data
    dir — the read-only summary invariant holds.
    """
    from ..assets import manifest as _manifest  # local: import-light
    from ..assets.manager import AssetManager  # local: import-light
    from . import _capabilities  # local: import-light, data only

    mgr = AssetManager(root=self.data_dir, settings_provider=lambda: settings)
    installed: set[str] = set()
    for asset_name in _capabilities.capability_asset_names():
        entry = _manifest.get_asset(asset_name)
        if entry is None:
            continue
        try:
            if mgr.installed_path(entry) is not None:
                installed.add(asset_name)
        except Exception:  # noqa: BLE001 - one bad probe must not sink the report
            continue
    return installed


def _default_hardware_probe(
    self: Services,
) -> Any:  # pragma: no cover - lazy heavy seam (pynvml/torch); tests inject a fake
    """Build the real :class:`HardwareProbe` (lazy import; runtime only).

    The free-disk seam is bound to the DATA dir so the device strip reports the
    room left on the drive model downloads actually land on.
    """
    from ..features import system_advisor as _sa  # noqa: PLC0415 - lazy

    return _sa.HardwareProbe(disk_probe=lambda: _sa.default_disk_probe(str(self.data_dir)))


def _default_ollama_meta_transport(self: Services) -> Any:
    """Build the real method-aware Ollama ``/api/*`` transport (lazy; runtime only).

    Adapts the stdlib :mod:`provider` request core to the ``ollama_meta``
    ``(url, method, body, timeout)`` shape: GET for ``/api/tags`` (body ignored),
    POST for ``/api/show`` (body carries ``{model}``). Built only when no transport
    is injected; the actual socket I/O lives in the inner closure (host-only) so the
    overview compose stays pure under test (every test injects a fake transport).
    """
    from ..models import provider as _provider_mod  # noqa: PLC0415 - lazy heavy seam

    def _transport(
        url: str, method: str, body: dict[str, Any], timeout: float
    ) -> dict[str, Any]:  # pragma: no cover - host-only urllib I/O; tests inject a fake
        if method == "POST":
            return _provider_mod._urllib_post_json(url, body, {}, timeout)
        return _provider_mod.urllib_get_json(url, {}, {}, timeout)

    return _transport


def _default_phase8_runner(self: Services) -> Callable[..., dict[str, Any]]:
    """Resolve the real Wave-1 signal-compute runner (lazy; runtime only).

    Returns the module-level :func:`_run_phase8_signals` which loads + runs the
    heavy Wave-1 signal modules. Kept behind a method so tests can inject a fake
    ``phase8_runner`` instead and never touch torch / transformers / cv2.
    """
    return _run_phase8_signals
