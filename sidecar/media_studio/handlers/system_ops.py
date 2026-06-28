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


def _default_hardware_probe(
    self: Services,
) -> Any:  # pragma: no cover - lazy heavy seam (pynvml/torch); tests inject a fake
    """Build the real :class:`HardwareProbe` (lazy import; runtime only).

    The free-disk seam is bound to the DATA dir so the device strip reports the
    room left on the drive model downloads actually land on.
    """
    from ..features import system_advisor as _sa  # noqa: PLC0415 - lazy

    return _sa.HardwareProbe(disk_probe=lambda: _sa.default_disk_probe(str(self.data_dir)))


def _default_phase8_runner(self: Services) -> Callable[..., dict[str, Any]]:
    """Resolve the real Wave-1 signal-compute runner (lazy; runtime only).

    Returns the module-level :func:`_run_phase8_signals` which loads + runs the
    heavy Wave-1 signal modules. Kept behind a method so tests can inject a fake
    ``phase8_runner`` instead and never touch torch / transformers / cv2.
    """
    return _run_phase8_signals
