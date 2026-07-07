"""The Services composition root (F4b split): owns the runtime services +
__init__, and binds every feature handler (handlers/*_ops) as a method. The
class is @final + the handlers carry `self: Services`, so the type checker sees
one whole class; behaviour + the RPC surface are byte-identical to pre-split."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, final

from .. import library as _library
from ..settings_store import SettingsStore, default_config_dir
from . import (
    ai_ops,
    director_ops,
    library_ops,
    media_ops,
    providers_ops,
    shortmaker_ops,
    system_ops,
    vision_ops,
)
from ._shared import Candidate, _DirectorPlanEntry


@final
class Services:
    """The runtime services + per-method handlers (the composition root).

    Owns the on-disk locations (all under a single per-user **data dir**, never a
    project folder): the library index, the per-video project manifests, the
    short-maker export output, and the settings file. Tests construct it with an
    injected ``data_dir`` (a tmp path) and injected seams (whisper loader, scene
    detector, ffmpeg ``run``) so no heavy dep / real subprocess is touched.
    """

    def __init__(
        self,
        *,
        data_dir: str | os.PathLike | None = None,
        settings_store: SettingsStore | None = None,
        library: _library.Library | None = None,
        whisper_loader: Any | None = None,
        ffmpeg_run: Callable[..., int] | None = None,
        ffprobe_duration: Callable[..., float] | None = None,
        reframe_runner: Callable[..., Any] | None = None,
        silence_run: Callable[..., Any] | None = None,
        scene_detector: Callable[[str], Any] | None = None,
        provider: Any | None = None,
        hardware_probe: Any | None = None,
        phase8_runner: Callable[..., dict[str, Any]] | None = None,
        test_key_transport: Any | None = None,
        openrouter_usage_transport: Any | None = None,
        now: Callable[[], float] | None = None,
        vlm_clip_frame_loader: Any | None = None,
        vlm_frame_encoder: Any | None = None,
        vlm_models_present: Callable[[dict[str, Any]], bool] | None = None,
        vlm_chat_transport: Any | None = None,
        local_detector: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
        ollama_meta_transport: Any | None = None,
        frame_scorer: Any | None = None,
        frame_backend_factory: Callable[[dict[str, Any]], Any] | None = None,
        thumbnail_writer: Any | None = None,
        embedder: Any | None = None,
        embed_transport: Any | None = None,
    ) -> None:
        base = Path(data_dir) if data_dir is not None else default_config_dir()
        self.data_dir = base
        self.projects_dir = base / "projects"
        self.exports_dir = base / "exports"
        self.settings = settings_store or SettingsStore(base / "settings.json")
        self.library = library or _library.Library(base / "library.json")

        # Injectable seams (default to the real, lazily-resolved impls).
        self._whisper_loader = whisper_loader
        self._ffmpeg_run = ffmpeg_run
        self._ffprobe_duration = ffprobe_duration
        self._reframe_runner = reframe_runner
        self._silence_run = silence_run
        self._scene_detector = scene_detector
        self._provider = provider
        # Phase-8 seams: a HardwareProbe (VRAM/RAM/CPU) for system.probe/advisor and
        # a signal-compute runner for phase8.signals/select. Defaults are the real
        # (heavy) impls, resolved lazily; tests inject fakes so no GPU / no torch.
        self._hardware_probe = hardware_probe
        self._phase8_runner = phase8_runner
        # WU-keys: the transport providers.testKey uses for its validation ping.
        # None -> the real stdlib urllib transport; tests inject a fake.
        self._test_key_transport = test_key_transport
        # WU-models/device: the GET transport providers.openrouterUsage uses to read
        # each OpenRouter key's cumulative credit usage. None -> the real stdlib
        # urllib GET transport; tests inject a fake so no socket is opened.
        self._openrouter_usage_transport = openrouter_usage_transport
        # WU-usage-ui: the wall-clock seam used to stamp + stale-flag the cached
        # providers.usage rows. None -> real ``time.time``; tests inject a fake
        # clock so the >10-min stale threshold is deterministic.
        self._now: Callable[[], float] = now or time.time
        # WU-vision: the Tier-2 re-rank seams. Defaults are the real (heavy) impls
        # resolved lazily inside smolvlm2; tests inject fakes so no cv2 / no torch /
        # no weights / no network is ever touched. ``vlm_models_present`` overrides
        # the local-weight probe so the cloud-vs-local-vs-off decision is testable.
        self._vlm_clip_frame_loader = vlm_clip_frame_loader
        self._vlm_frame_encoder = vlm_frame_encoder
        self._vlm_models_present = vlm_models_present
        # WU-vision: the chat transport the vision rotation pool uses (the
        # provider.py HTTP seam). None -> the real stdlib urllib transport; tests
        # inject a fake so frame egress is observable without a socket.
        self._vlm_chat_transport = vlm_chat_transport
        # WU-B2: the local-server detector seam (system.recommend folds detected
        # Ollama / LM Studio servers over the recommended routing). None -> the
        # real detector over the stdlib urllib GET transport; tests inject a fake
        # that returns canned PoolEntry dicts so no socket is opened.
        self._local_detector = local_detector
        # M2 (models.overview eligibility): the method-aware Ollama /api/* transport
        # used to read REAL model metadata (quant + VRAM estimate) for the reason
        # strip. None -> the real lazy stdlib urllib adapter; tests inject a fake so
        # the overview compose opens no socket.
        self._ollama_meta_transport = ollama_meta_transport

        # WU-C3 (thumbnail.select): the best-frame scorer + writer seams. Defaults
        # resolve a CloudFrameScorer over the SAME frame-consented vision pool the
        # re-ranker uses (cloud) or the local SmolVLM2 backend (weights present),
        # else None (degrade-to-midpoint). ``frame_scorer`` short-circuits the
        # resolution (tests / a future override); ``frame_backend_factory`` is the
        # backend the local CloudFrameScorer wraps (default the heavy native seam);
        # ``thumbnail_writer`` is the cv2 imwrite seam (tests record its call).
        self._frame_scorer = frame_scorer
        self._frame_backend_factory = frame_backend_factory
        self._thumbnail_writer = thumbnail_writer

        # WU-A5 (index.*): the embedding seam for the semantic index. ``embedder``
        # short-circuits resolution outright (tests / a wholesale override). When
        # absent, :meth:`_resolve_index_embedder` builds a CloudEmbedder over ONLY
        # the TEXT-consented + routed cloud entries (so transcript text can never
        # rotate onto a non-consented provider) or falls back to the deterministic
        # LocalEmbedder. ``embed_transport`` is the OpenAI ``/v1/embeddings`` HTTP
        # seam the real CloudEmbedder uses; tests inject a fake so the consent
        # gate is proven without a socket (the egress is observable, not mocked away).
        self._embedder = embedder
        self._embed_transport = embed_transport

        # T3: the shared llama.cpp ModelRunner (built lazily; model-identity-aware,
        # so the tiered translator can swap MT GGUFs on the one server lane).
        self._model_runner: Any | None = None

        # short-maker selection cache: selectionId -> {candidateId -> Candidate}.
        # CONTRACT-NOTE (INTEGRATION-REPORT HIGH-3): the UI builds candidate ids as
        # "rank@sourceStart" and sends only candidateIds to shortmaker.export. We
        # cache the select result server-side under those same ids so export can
        # resolve real clips; the loader exposes the cache as the context's
        # "candidates" map that _resolve_candidates already consults.
        self._selection_cache: dict[str, dict[str, Candidate]] = {}

        # WU-plan-rpc: the Director plan store. ``director.plan`` stashes each
        # validated EditPlan (+ the planner messages + the videoId it was planned
        # against) under its ``planId`` so the follow-up ``director.previewCost`` /
        # ``director.apply`` calls resolve the SAME plan without re-running the LLM.
        # In-memory (per-session), mirroring the selection cache above.
        self._director_plans: dict[str, _DirectorPlanEntry] = {}

        # WU-undo: the recorded-inverse store. ``director.apply`` stashes the
        # ``inverse_plan`` it recorded (newest-first ops) under the SAME ``planId``
        # so ``director.undo`` can re-run those inverse ops over a fresh COPY for a
        # one-shot reversal (DESIGN §5/§7.1). A plan that was never applied has no
        # entry here, so ``director.undo`` rejects it (nothing to undo).
        self._director_inverses: dict[str, Any] = {}  # planId -> edit_plan.EditPlan
        self._director_engines_logged = False  # one-shot deferred-kinds log (FIX #7)

    # Class-level seam (qualitative Director-eval judge; overridable in tests).
    _director_eval_judge: Any = None

    # ---- feature handlers (bound from handlers/*_ops; see F4b split) --------
    _resolve_video_path = library_ops._resolve_video_path
    _video_title = library_ops._video_title
    _project_path = library_ops._project_path
    _load_or_create_project = library_ops._load_or_create_project
    _find_project_for_track = library_ops._find_project_for_track
    library_list = library_ops.library_list
    library_add = library_ops.library_add
    library_remove = library_ops.library_remove
    library_thumbnail = library_ops.library_thumbnail
    library_lineage = library_ops.library_lineage
    library_reveal = library_ops.library_reveal
    library_regenerate = library_ops.library_regenerate
    library_pin_hash = library_ops.library_pin_hash
    library_relink = library_ops.library_relink
    library_keep_copy = library_ops.library_keep_copy
    library_managed_status = library_ops.library_managed_status
    library_managed_evict = library_ops.library_managed_evict
    library_managed_clear = library_ops.library_managed_clear
    project_open = library_ops.project_open
    project_save = library_ops.project_save
    project_consolidate = library_ops.project_consolidate
    settings_get = library_ops.settings_get
    settings_set = library_ops.settings_set
    paths_describe = library_ops.paths_describe
    readiness_summary = library_ops.readiness_summary
    providers_catalog = providers_ops.providers_catalog
    providers_list = providers_ops.providers_list
    providers_upsert = providers_ops.providers_upsert
    providers_remove = providers_ops.providers_remove
    providers_test_key = providers_ops.providers_test_key
    providers_reveal_key = providers_ops.providers_reveal_key
    providers_set_consent = providers_ops.providers_set_consent
    providers_usage = providers_ops.providers_usage
    providers_openrouter_usage = providers_ops.providers_openrouter_usage
    providers_usage_availability = providers_ops.providers_usage_availability
    providers_spend = providers_ops.providers_spend
    providers_apply_preset = providers_ops.providers_apply_preset
    providers_set_function_model = providers_ops.providers_set_function_model
    providers_first_run = providers_ops.providers_first_run
    _save_presets_block = providers_ops._save_presets_block
    save_presets_list = providers_ops.save_presets_list
    save_presets_upsert = providers_ops.save_presets_upsert
    save_presets_apply = providers_ops.save_presets_apply
    save_presets_remove = providers_ops.save_presets_remove
    _function_prefer = providers_ops._function_prefer
    _provider_for_function = providers_ops._provider_for_function
    _select_provider_or_local = providers_ops._select_provider_or_local
    _translator_for_function = providers_ops._translator_for_function
    _frame_consented_vision_settings = providers_ops._frame_consented_vision_settings
    _text_consented_settings = providers_ops._text_consented_settings
    _vision_pool = providers_ops._vision_pool
    _vision_provider_for_consent = providers_ops._vision_provider_for_consent
    _resolve_vlm_reranker = vision_ops._resolve_vlm_reranker
    _resolve_frame_scorer = vision_ops._resolve_frame_scorer
    _frame_clip_loader = vision_ops._frame_clip_loader
    _frame_thumbnail_writer = vision_ops._frame_thumbnail_writer
    _resolve_thumbnail_span = vision_ops._resolve_thumbnail_span
    thumbnail_select = vision_ops.thumbnail_select
    _index_path = vision_ops._index_path
    _read_index = vision_ops._read_index
    _write_index = vision_ops._write_index
    _resolve_index_embedder = vision_ops._resolve_index_embedder
    _ai_pool_for_index = vision_ops._ai_pool_for_index
    index_build = vision_ops.index_build
    _index_provider_factory = vision_ops._index_provider_factory
    index_status = vision_ops.index_status
    index_search = vision_ops.index_search
    _plan_index_envelope = vision_ops._plan_index_envelope
    subtitles_generate = media_ops.subtitles_generate
    subtitles_edit = media_ops.subtitles_edit
    subtitles_export = media_ops.subtitles_export
    subtitles_translate = media_ops.subtitles_translate
    tracks_list = media_ops.tracks_list
    tracks_rename = media_ops.tracks_rename
    tracks_relabel = media_ops.tracks_relabel
    tracks_add = media_ops.tracks_add
    tracks_remove = media_ops.tracks_remove
    tracks_strip = media_ops.tracks_strip
    tracks_burn = media_ops.tracks_burn
    convert_start = media_ops.convert_start
    convert_batch = media_ops.convert_batch
    transcribe_start = media_ops.transcribe_start
    _diarize_backend_factory = media_ops._diarize_backend_factory
    _diarize_models_present = media_ops._diarize_models_present
    _maybe_align_words = media_ops._maybe_align_words
    system_probe = system_ops.system_probe
    system_advisor = system_ops.system_advisor
    asr_engines = system_ops.asr_engines
    _detect_local_servers = system_ops._detect_local_servers
    system_recommend = system_ops.system_recommend
    models_runners = system_ops.models_runners
    models_overview = system_ops.models_overview
    models_set_routing_policy = system_ops.models_set_routing_policy
    models_resolve_route = system_ops.models_resolve_route
    system_self_test = system_ops.system_self_test
    phase8_signals = system_ops.phase8_signals
    phase8_select = system_ops.phase8_select
    _models_present_map = system_ops._models_present_map
    _installed_asset_names = system_ops._installed_asset_names
    _default_hardware_probe = system_ops._default_hardware_probe
    _default_ollama_meta_transport = system_ops._default_ollama_meta_transport
    _default_phase8_runner = system_ops._default_phase8_runner
    _shortmaker = shortmaker_ops._build_shortmaker
    _detect_boundaries = shortmaker_ops._detect_boundaries
    _shortmaker_context = shortmaker_ops._shortmaker_context
    shortmaker_select = shortmaker_ops.shortmaker_select
    shortmaker_export = shortmaker_ops.shortmaker_export
    _approved_clips = shortmaker_ops._approved_clips
    nle_export = shortmaker_ops.nle_export
    package_export = shortmaker_ops.package_export
    _cache_candidates = shortmaker_ops._cache_candidates
    candidate_id = staticmethod(shortmaker_ops.candidate_id)
    _get_provider = ai_ops._get_provider
    _ai_cache = ai_ops._ai_cache
    _ai_pool = ai_ops._ai_pool
    _spend_ledger = ai_ops._spend_ledger
    _estimate_job_cents = ai_ops._estimate_job_cents
    _enforce_monthly_hard_cap = ai_ops._enforce_monthly_hard_cap
    _enforce_egress_gates = ai_ops._enforce_egress_gates
    _record_egress_cost = ai_ops._record_egress_cost
    plan_ai_job_envelope = ai_ops.plan_ai_job_envelope
    _run_ai_job = ai_ops._run_ai_job
    _enforce_cloud_budget_ack = ai_ops._enforce_cloud_budget_ack
    ai_plan_job = ai_ops.ai_plan_job
    _soft_spend_warning = ai_ops._soft_spend_warning
    _director_video_duration_ms = director_ops._director_video_duration_ms
    _director_get_plan = director_ops._director_get_plan
    _editplan_provider_or_refuse = director_ops._editplan_provider_or_refuse
    director_plan = director_ops.director_plan
    director_preview_cost = director_ops.director_preview_cost
    _director_engines = director_ops._director_engines
    _director_inverse_engines = director_ops._director_inverse_engines
    _director_apply_ack = director_ops._director_apply_ack
    director_apply = director_ops.director_apply
    director_undo = director_ops.director_undo
    _director_eval_signals = director_ops._director_eval_signals
    director_evaluate = director_ops.director_evaluate
    _budget_request = ai_ops._budget_request
    _default_target_job_size = ai_ops._default_target_job_size
    _get_model_runner = ai_ops._get_model_runner
    _llama_ensure = ai_ops._llama_ensure
    _get_translator = ai_ops._get_translator
    _dub_translator = ai_ops._dub_translator
