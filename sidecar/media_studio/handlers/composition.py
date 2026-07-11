"""The register_all composition root (F4b split): wires every Services method
and each feature module's own register() onto protocol.METHODS. Extracted
verbatim from the former handlers.py; the registration order is unchanged."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import library as _library
from .. import protocol
from ..features import media_compat as _media_compat
from ..features import timeline as _timeline
from ..features import tracks as _tracks
from ..protocol import Handler, RpcContext
from ..settings_store import INJECTED_KEYS_FIELD
from ._services import Services
from ._shared import _invalid, log
from ._wire import _self_ffprobe


def _key_overlay_wrapper(svc: Services, handler: Handler) -> Handler:
    """Wrap ``handler`` so the per-request injected DPAPI keys reach ``get_raw``.

    WU-D2b-2 CONSUME (orchestrator ruling B): main injects the decrypted keys
    under :data:`INJECTED_KEYS_FIELD` on the params of every provider-calling
    method. This wrapper POPS that field off the params IN PLACE (the SAME dict
    ``dispatch`` will hand to ``job.retry``'s ``record_request`` and ``rpc.py``'s
    error logger), so a live key can never land in a job-store record or a log
    line, then runs the handler inside :meth:`SettingsStore.key_overlay` so the
    FACTORY seams' ``get_raw()`` see the raw keys for THAT request only — every
    real key-consuming seam captures its provider/settings synchronously while
    this overlay is active. A request without the field is an ordinary call (the
    overlay is never opened).

    IDX 60 Part 2 (job-runner overlay propagation): for the long job-runner
    methods (``recipes.run`` / ``templates.apply`` / ``batch.start`` /
    ``batch.resume``) the outer handler only ENQUEUES the job and returns
    ``{jobId}`` — the nested steps run later on a worker thread AFTER this overlay
    context has closed, so without help they would see only the redacted at-rest
    markers. So the popped ``injected`` snapshot is stashed on the per-request
    :class:`RpcContext` (``ctx.injected_keys``) — the SAME ``ctx`` object the job
    body closes over — instead of being discarded when ``wrapped`` returns. The
    step runner (``RecipeRunner``) re-attaches it under :data:`INJECTED_KEYS_FIELD`
    onto each nested step's params, which are then dispatched through THIS wrapper
    again, so the overlay is re-opened (and the marker re-popped) per step. The
    snapshot lives ONLY on the ephemeral ``ctx`` (never serialized: ``RpcContext``
    is a dataclass whose ``repr``/equality see only its declared fields, and the
    job store records the already-popped request params), so the pop-in-place
    no-leak invariant holds."""

    def wrapped(params: dict[str, Any], ctx: RpcContext) -> Any:
        injected = params.pop(INJECTED_KEYS_FIELD, None) if isinstance(params, dict) else None
        if injected is None:
            return handler(params, ctx)
        # Stash for the deferred job-worker step runner (IDX 60 Part 2). Harmless for
        # synchronous handlers (they finish under the overlay and never read it back).
        ctx.injected_keys = injected
        with svc.settings.key_overlay(injected):
            return handler(params, ctx)

    return wrapped


def register_all(
    services: Services | None = None,
    *,
    register: Callable[[str, Any], None] | None = None,
) -> Services:
    """Register every §2 method handler on ``protocol.METHODS``; return the Services.

    Idempotent only across a fresh registry: ``protocol.register`` raises on a
    duplicate name (a typo/double-wire fails loudly at startup). ``services`` and
    ``register`` are injectable for tests (a tmp-dir Services + a fake registrar).

    WU-D2b-2: every handler is registered through :func:`_key_overlay_wrapper`
    (including the feature modules that take ``register_fn=reg``), so the
    per-request DPAPI key injection is consumed uniformly and stripped before it
    can reach a log line or the persisted job store.
    """
    svc = services or Services()
    base_reg = register if register is not None else protocol.register

    def reg(name: str, handler: Handler) -> None:
        base_reg(name, _key_overlay_wrapper(svc, handler))

    reg("library.list", svc.library_list)
    reg("library.add", svc.library_add)
    reg("library.remove", svc.library_remove)
    reg("library.thumbnail", svc.library_thumbnail)
    # L3 (V1.1 Lane 3): read-only provenance query — ancestors (made from) +
    # descendants (used to make) via a recursive derived_from edge walk. Direct.
    reg("library.lineage", svc.library_lineage)
    # L5 (V1.1 Lane 3): reveal source / regenerate-from-source / hash-verified
    # relink. Reveal+regenerate are read-only; relink/pinHash mutate the entity
    # row (path / content_hash) only after a whole-file BLAKE3 verify. Direct.
    reg("library.reveal", svc.library_reveal)
    reg("library.regenerate", svc.library_regenerate)
    reg("library.pinHash", svc.library_pin_hash)
    reg("library.relink", svc.library_relink)
    # WU-3b1: OPT-IN keep-a-copy managed store. keepCopy copies the source bytes into
    # the app-managed store (atomic, preflight, cap+LRU, dedup) and re-points lineage to
    # the copy; managedStatus is read-only; managedEvict/managedClear free the bytes and
    # re-point each entity back to its original source. Direct.
    reg("library.keepCopy", svc.library_keep_copy)
    reg("library.managedStatus", svc.library_managed_status)
    reg("library.managedEvict", svc.library_managed_evict)
    reg("library.managedClear", svc.library_managed_clear)

    reg("project.open", svc.project_open)
    reg("project.save", svc.project_save)
    reg("project.consolidate", svc.project_consolidate)

    reg("settings.get", svc.settings_get)
    reg("settings.set", svc.settings_set)

    # WU-1: read-only data-layout describe (no I/O, no secrets, idempotent).
    reg("paths.describe", svc.paths_describe)

    reg("transcribe.start", svc.transcribe_start)

    reg("subtitles.generate", svc.subtitles_generate)
    reg("subtitles.edit", svc.subtitles_edit)
    reg("subtitles.translate", svc.subtitles_translate)
    reg("subtitles.export", svc.subtitles_export)

    reg("tracks.list", svc.tracks_list)
    reg("tracks.rename", svc.tracks_rename)
    reg("tracks.relabel", svc.tracks_relabel)
    reg("tracks.add", svc.tracks_add)
    reg("tracks.remove", svc.tracks_remove)
    reg("tracks.burn", svc.tracks_burn)
    reg("tracks.strip", svc.tracks_strip)

    reg("convert.start", svc.convert_start)
    reg("convert.batch", svc.convert_batch)

    reg("shortmaker.select", svc.shortmaker_select)
    reg("shortmaker.export", svc.shortmaker_export)

    # Phase-8 moment-finding: system probe/advisor + ASR-engine list + the unified
    # tri-modal signals/select. system.* + asr.engines are direct (cheap probes);
    # phase8.* are long jobs (load heavy models behind the phase8 runner seam).
    reg("system.probe", svc.system_probe)
    reg("system.advisor", svc.system_advisor)
    # WU-B2: device-aware auto-recommender. Direct-return; composes the cheap
    # probes (advisor + present-map + local-server detect + asr engines) through
    # the PURE recommender. Makes ZERO provider/LLM calls.
    reg("system.recommend", svc.system_recommend)
    # WU-models/device: the local-model brain — device-ranked whisper + LLM
    # recommendation + Ollama/LM Studio detect/pull/install advice. Direct-return;
    # composes the cheap hardware probe + local-server detect through the PURE
    # model_recommend module. NO LLM/provider call, NO pull is triggered here.
    reg("models.runners", svc.models_runners)
    # M1a (V1.1 Lane 2): the THIN Models&System compose. Direct-return; stitches
    # the cheap probes (probe + advisor + local detect + recommend) with the
    # redacted providers + per-key pool + fail-closed routing policy into ONE
    # screen. ZERO provider/LLM calls, NO pull, NO settings mutation, no full key.
    reg("models.overview", svc.models_overview)
    # M3 (V1.1 Lane 2): the WRITE half of the single RoutingPolicy store. Persists
    # the sanitised (fail-closed clamped) {global, overrides} via the atomic
    # settings store; the header toggle + Advanced per-function table call it.
    reg("models.setRoutingPolicy", svc.models_set_routing_policy)
    # M5 (V1.1 Lane 2): the CONCRETE per-function route resolver (DESIGN §2.3 step
    # 4). Direct-return; composes the read-only overview then resolves {mode, model,
    # runner|provider} per AI function, degrading cloud/auto -> local LOUDLY when no
    # key is on disk. No provider/LLM call, no mutation, no full key over RPC.
    reg("models.resolveRoute", svc.models_resolve_route)
    # WU-2: the first-run self-diagnostic. Direct (no job): pure data-dir/device/
    # native-dep/ffmpeg probes behind seams — reports LOUDLY, never proceeds broken.
    reg("system.selfTest", svc.system_self_test)
    # WU-8: the unified read-only readiness roll-up (model tiers + per-function
    # provider key/consent state). Direct (no job): pure installed-state + redacted
    # settings reads — no provider call, no assets.ensure (the read-only invariant).
    reg("readiness.summary", svc.readiness_summary)
    reg("asr.engines", svc.asr_engines)
    reg("phase8.signals", svc.phase8_signals)
    reg("phase8.select", svc.phase8_select)
    # WU-C3: AI best-frame thumbnail picker. A custom-work AiJob (cancel/degrade/
    # budget); frame egress is frame-consent-gated, degrades to the clip midpoint
    # with zero egress when no vision model is available.
    reg("thumbnail.select", svc.thumbnail_select)

    # WU-A5: semantic index. index.build is a long job (embed + persist vectors);
    # index.search / index.status are direct-return (query embed + cosine / file read).
    reg("index.build", svc.index_build)
    reg("index.search", svc.index_search)
    reg("index.status", svc.index_status)
    # index.plan: the PURE pre-flight consent surface for a build/search (mirrors
    # ai.planJob) — cacheKey + willEgress computed with ZERO provider calls, so the
    # renderer can render the §9.1 egress card before deciding to build/search.
    reg("index.plan", svc.index_plan)

    # WU-envelope: AI-Job pre-flight. ai.planJob returns the route + cost/egress
    # budget + cacheHit/willEgress with ZERO provider calls (the pure planner).
    reg("ai.planJob", svc.ai_plan_job)

    # WU-plan-rpc (Director): the RPC spine onto the shipped AI substrate.
    # director.plan understands -> editPlan LLM (via _run_ai_job) -> validate ->
    # stored plan; director.previewCost is a PURE per-data-type pass-through to
    # ai.planJob (ZERO calls); director.apply walks the plan over a project COPY
    # (apply_plan, WU-apply) recording an inverse. All three register HERE ONLY
    # (the one composition root — no parallel AI path).
    reg("director.plan", svc.director_plan)
    reg("director.previewCost", svc.director_preview_cost)
    reg("director.apply", svc.director_apply)
    # WU-undo: one-shot reversal. director.undo re-applies the inverse plan that
    # director.apply recorded (over a fresh COPY) — registered AFTER the plan-rpc
    # methods (SEQUENCED on the single composition root, no parallel AI path).
    reg("director.undo", svc.director_undo)
    # WU-evaluate: objective goal-vs-result metrics. director.evaluate computes the
    # before/after deltas (jerk/cutRhythm/silenceRatio/ocrCoverage) via the PURE
    # director_eval.evaluate over the shipped phase8 signals; an optional LLM judge
    # note never overrides the objective score (DESIGN §4, AGENTS.md §7). Registered
    # HERE ONLY (the one composition root — no parallel AI path).
    reg("director.evaluate", svc.director_evaluate)

    # WU-keys: provider key management. Every read is REDACTED (last-4) — no RPC
    # method ever returns a full key; the FACTORY path reads RAW via get_raw().
    # Per-data-type (text vs frames) consent is SEPARATE + independently revocable.
    # WU-catalog: the static curated model catalog (per-task tiers + privacy /
    # train-on-input flags + asOfDate + unit) the UI renders. PURE data, no keys.
    reg("providers.catalog", svc.providers_catalog)
    reg("providers.list", svc.providers_list)
    reg("providers.upsert", svc.providers_upsert)
    reg("providers.remove", svc.providers_remove)
    reg("providers.testKey", svc.providers_test_key)
    # WU-D3: the ONE sanctioned plaintext exception — an explicit-click reveal that
    # returns exactly one RAW key for a transient, masked-by-default UI display. The
    # renderer holds it in a ref only (never state/store/logs/telemetry/crash) and
    # re-masks on blur/timeout. Every other providers.* read stays last-4 redacted.
    reg("providers.revealKey", svc.providers_reveal_key)
    reg("providers.setConsent", svc.providers_set_consent)
    # WU-usage-ui: per-key live usage (cached, persisted, stale-flagged; no poll
    # burst). The rotation pool already accounts usage from optimistic decrement +
    # parsed 429/X-RateLimit-* headers — this RPC just surfaces it, redacted.
    reg("providers.usage", svc.providers_usage)
    # WU-models/device: per-key OpenRouter COST rows (cumulative credit usage USD)
    # — the cost axis alongside providers.usage's calls/tokens. Best-effort GET per
    # RAW key through the GET-transport seam; no full key ever crosses RPC.
    reg("providers.openrouterUsage", svc.providers_openrouter_usage)
    # WU-D4: honest per-provider usage-API availability. OpenRouter has a per-key
    # usage API; OpenAI/Anthropic gate usage behind an org admin key and others
    # publish nothing per-key — this states that truthfully instead of a fake 0.
    reg("providers.usageAvailability", svc.providers_usage_availability)
    # WU-spend-cap: month-to-date cumulative spend + the configured monthly caps
    # (read-only). The persisted ledger is written at job completion; this RPC just
    # surfaces it (+ the soft/hard cap settings) for the renderer's spend view.
    reg("providers.spend", svc.providers_spend)
    # WU-presets (PH3): smart presets + per-function override + first-run chooser.
    # applyPreset resolves a preset over the curated catalog into routing.perFunction;
    # setFunctionModel overrides one slot; firstRun is the local-vs-cloud chooser
    # (local-safe default pre-choice, flips routing + firstRunChoiceMade on choice).
    reg("providers.applyPreset", svc.providers_apply_preset)
    reg("providers.setFunctionModel", svc.providers_set_function_model)
    reg("providers.firstRun", svc.providers_first_run)

    # WU-10 (UX/QoL): named {autosave, exportDefaults} save-presets, persisted under
    # the ``savePresets`` settings block (read-modify-write the whole block — the
    # settings merge is a SHALLOW top-level replace). Mirrors providers.applyPreset
    # (resolve -> persist) but stores user-named bundles, not routing presets.
    reg("savePresets.list", svc.save_presets_list)
    reg("savePresets.apply", svc.save_presets_apply)
    reg("savePresets.upsert", svc.save_presets_upsert)
    reg("savePresets.remove", svc.save_presets_remove)

    # captions-export: EDL/CSV NLE timeline export + ZIP package-for-upload.
    reg("nle.export", svc.nle_export)
    reg("package.export", svc.package_export)

    # ---------------------------------------------------------------------- #
    # P2 addendum methods (A2) — feature modules ship their own register()
    # ---------------------------------------------------------------------- #
    # media.* (U1): playable verdict + playback proxy.
    _media_compat.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # timeline.peaks (T1): direct-return waveform peaks (cached on disk).
    _timeline.register(
        resolver=svc._resolve_video_path,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # tracks.audio.* + tts.* (A2): registered via the modules' own register()
    # so they bind to the services' library/projects/settings (T2).
    from ..features import tracks_audio as _tracks_audio  # local: import-light
    from ..features import tts as _tts

    def _load_project_data(video_id: str) -> dict[str, Any]:
        return svc._load_or_create_project(video_id).data

    def _save_project_data(video_id: str, data: dict[str, Any]) -> None:
        _library.Project(dict(data), manifest_path=svc._project_path(video_id)).save()

    def _load_subtitle_track(video_id: str, track_id: str) -> dict[str, Any]:
        project = svc._load_or_create_project(video_id)
        try:
            return _tracks.find_track(project.data, track_id)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc

    audio_tracks_svc = _tracks_audio.register(
        resolver=svc._resolve_video_path,
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _tts.register(
        resolver=svc._resolve_video_path,
        load_track=_load_subtitle_track,
        audio_tracks=audio_tracks_svc,
        settings_provider=svc.settings.get,
        translator_factory=svc._dub_translator,  # T3 seam adapter (WIRING-T2 §2)
        media_duration=(svc._ffprobe_duration or _self_ffprobe()),
        out_dir=str(svc.data_dir / "dubs"),
        register_fn=reg,
    )

    # feedback.* (P3-D): the flywheel store registers its own two methods.
    from ..features import feedback as _feedback  # local: import-light

    _feedback.register(register_fn=reg)

    # reframe.eval (R0): the PURE ML eval harness — the regression gate R1 must
    # clear. Scores a predicted-vs-reference trace over the wire (the heavy
    # real-frame engine run stays out-of-band; the GPU/e2e tier wires it in R1).
    from ..features import reframe_eval as _reframe_eval  # local: import-light

    _reframe_eval.register(register_fn=reg)

    # reframe.shotPlan / reframe.applyOverrides (R2): the PURE manual per-shot
    # speaker/layout/crop override layer — derives an editable plan from a trace
    # and resolves a user's edits into the affected-shot set R1 re-renders (the
    # heavy per-shot compositor stays out-of-band).
    from ..features import reframe_override as _reframe_override  # local: import-light

    _reframe_override.register(register_fn=reg)

    # shorts.* (P4 §2/C6): the shorts library registers its own four methods,
    # bound to the same exports root + per-video out-dir layout the short-maker
    # export uses (Services.exports_dir / "shorts-<videoId>").
    from ..features import shorts as _shorts  # local: import-light

    _shorts.register(
        exports_dir=svc.exports_dir,
        out_dir_for=lambda vid: str(svc.exports_dir / f"shorts-{vid}"),
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        register_fn=reg,
    )

    # captions.cues (P4 §2/C6/C7): NET-NEW WORD-level cues for the live preview
    # overlay, built from the persisted transcript via the SAME context loader
    # the short-maker uses. The module owns its own register() (mirrors shorts).
    from ..features import cues as _cues  # local: import-light

    _cues.register(load_context=svc._shortmaker_context, register_fn=reg)

    # audio-stabilize group (NET-NEW): the three transport-agnostic engine
    # features each own their own register() (mirrors shorts/tracks_audio):
    #   stabilize.run        camera-shake stabilization (ffmpeg vidstab 2-pass)
    #   audiomix.merge       A/V merge + sidechain DUCK + EBU R128 loudnorm
    #   audiomix.normalize   EBU R128 loudnorm only (no bed)
    #   silence.trim         dead-air removal (ffmpeg silencedetect -> re-cut)
    # All resolve media via the library + write derivatives under the exports
    # root, reusing the same injectable ffmpeg seams the sibling features use.
    from ..features import audiomix as _audiomix  # local: import-light
    from ..features import silencetrim as _silencetrim  # local: import-light
    from ..features import stabilize as _stabilize  # local: import-light

    _stabilize.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "stabilized",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _audiomix.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "audiomix",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )
    _silencetrim.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "trimmed",
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )

    # ---------------------------------------------------------------------- #
    # system-advanced group (this build) — health / recipes / diarize.
    # Each module owns its own register() (mirrors shorts / cues / assets).
    # ---------------------------------------------------------------------- #
    from ..features import diarize as _diarize  # local: import-light
    from ..features import health as _health  # local: import-light
    from ..features import recipes as _recipes  # local: import-light

    # system.health (feature 1): the single "is my setup OK?" diagnostic. Reads
    # the same settings + tools_resolver chains the rest of the sidecar uses.
    _health.register(
        settings_provider=svc.settings.get,
        root=svc.data_dir,
        register_fn=reg,
    )

    # recipes.* (feature 3): saved multi-step pipelines run in one shot. The
    # runner invokes the live METHODS registry, so it must register AFTER the
    # methods its steps reference (transcribe/subtitles/shortmaker/etc.) — i.e.
    # here, near the end of register_all.
    _recipes.register(
        path=svc.data_dir / "recipes.json",
        register_fn=reg,
    )

    # exportPresets.* (repurpose WU2): server-persisted platform targets the
    # templates/batch groups reference by id. Direct-return CRUD over a JSON
    # catalog at data_dir/export-presets.json (atomic temp+rename, self-seeding).
    # Storage-only — no provider/ML imports; the module owns its own register().
    from ..features import export_presets as _export_presets  # local: import-light

    _export_presets_svc = _export_presets.register(
        path=svc.data_dir / "export-presets.json",
        register_fn=reg,
    )

    # templates.* (repurpose WU5): saved multi-source pipelines (a recipe PLUS
    # defaultControls + exportTargets). list/save/delete are direct CRUD; apply
    # runs ONE source through the EXISTING recipe runner after binding steps to
    # the videoId and fanning out the export step over the live preset catalog.
    # Registers AFTER the methods its steps reference AND after exportPresets (the
    # fan-out resolves preset ids from that catalog) — no new RPC site, no provider.
    from ..features import templates as _templates  # local: import-light

    _templates.register(
        path=svc.data_dir / "templates.json",
        presets_provider=lambda: {p["id"]: p for p in _export_presets_svc.store.list()},
        register_fn=reg,
    )

    # batch.* (repurpose WU10): point ONE template at MANY sources and run them as
    # one aggregate, resumable, per-source-isolated job (DESIGN §6). The seven
    # methods own no orchestration of their own — each source rides the live
    # ``templates.apply`` handler (registered just above), so the batch reaches the
    # AI envelope only by method name; consent uses ``ai.planJob`` by name (ZERO
    # provider calls). Registered AFTER templates (its default per-source runner +
    # consent planner resolve those handlers from the live registry). No new RPC
    # site, no provider/key wiring. The title seam reuses the library's display name.
    from ..features import batch as _batch  # local: import-light

    _batch.register(
        path=svc.data_dir / "batches",
        title_resolver=svc._video_title,
        register_fn=reg,
    )

    # diarize.start (feature 4): token-free speaker labelling. Reuses the same
    # project load/save helpers tracks_audio uses, plus the offline-gated assets.
    #
    # Phase-8 wiring: settings['diarizeBackend'] selects the SpeechBrain default
    # OR the opt-in pyannote 3.1 backend (gated HF weights + env HF token). The
    # selector validates the token eagerly (typed refusal, no deep 401) BEFORE any
    # heavy import; an unknown value keeps the safe speechbrain default. The
    # offline-gate models_present likewise checks whichever backend is selected.
    # Both seams are bound Services methods (testable in isolation).
    _diarize.register(
        resolver=svc._resolve_video_path,
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        backend_factory=svc._diarize_backend_factory,
        models_present=svc._diarize_models_present,
        register_fn=reg,
    )

    # refine.* (editing-refine WU-5): the standalone "tighten the edit" feature —
    # previewable filler/silence cut-list (no encode) + apply (job). It composes
    # the SHIPPED filler/silence math (no new cut logic) and reuses the exact
    # project-store + ffmpeg seams the sibling features use. refine.preview is a
    # DIRECT handler; refine.apply is a job (the module owns its register()).
    # settings['refine.fillerSets'] reaches plan_refine's cut math via the service
    # (params['fillerSets']); absent -> DEFAULT_SETS (no behaviour change).
    from ..features import refine as _refine  # local: import-light

    _refine.register(
        resolver=svc._resolve_video_path,
        out_dir=svc.exports_dir / "refined",
        load_project=_load_project_data,
        save_project=_save_project_data,
        settings_provider=svc.settings.get,
        run=svc._ffmpeg_run,  # None -> the real drained ffmpeg.run
        duration=svc._ffprobe_duration,
        register_fn=reg,
    )

    # assets.* (A2): registered via the assets package's own register() so the
    # manager binds to the services' data dir + settings (U4).
    from ..assets import rpc as _assets_rpc  # local import keeps handlers import-light

    _assets_rpc.register(
        root=svc.data_dir,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # Imports for side effect — U4 manifest entries only, NO new RPC methods:
    # T3 (TranslateGemma GGUF tiers), T4a (Chrome Headless Shell + exposes
    # RemotionCaptionEngine/STYLES), T5 (llama-server tool builds + the
    # resolve_tool() chains).
    from .. import tools_resolver  # noqa: F401

    # Phase-8 model modules — imported for their asset-registration side effects
    # (each registers its on-demand AssetEntry at import, mirroring diarize /
    # tools_resolver). No new RPC methods: parakeet plugs into transcribe via the
    # ASR-engine seam, ctc_align into the transcribe karaoke tail, caption_polish
    # into subtitles.generate, pyannote into diarize's backend selector (above).
    from ..features import (
        audio_saliency,  # noqa: F401
        caption_polish,  # noqa: F401
        caption_remotion,  # noqa: F401
        ctc_align,  # noqa: F401
        parakeet_asr,  # noqa: F401
        quality_gate,  # noqa: F401
        saliency,  # noqa: F401
        scene_transnet,  # noqa: F401
        smolvlm2,  # noqa: F401
        vlm_backbone,  # noqa: F401
    )
    from ..models import translation as _translation_assets  # noqa: F401

    # job.list / job.retry (U5) are protocol.py built-ins — no wiring needed.

    log.info("registered %d feature methods", len(protocol.METHODS))
    return svc
