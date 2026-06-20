"""Composition root — wire every §2 method's handler onto ``protocol.METHODS``.

The feature modules ship correct pure functions but register NOTHING. This module
is the assembly seam the build was missing (INTEGRATION-REPORT §CRITICAL-1):

  * it owns the runtime services — a :class:`~media_studio.library.Library`, a
    :class:`~media_studio.settings_store.SettingsStore`, a per-video Project
    manifest store, and a short-maker selection cache;
  * it authors thin ``(params, ctx) -> result`` handlers that ADAPT the wire
    params (``videoId``/``trackId``/``id``/``path``) onto each pure function and
    return the EXACT §3 result dict; long-running ones run on ``ctx.jobs`` and
    return ``{jobId}``;
  * :func:`register_all` calls ``protocol.register`` (and the feature modules'
    own ``register`` helpers) for all ~30 methods.

``media_studio/__main__.py`` imports this, calls :func:`register_all`, then runs
``rpc.main`` — so the registrations land in ``METHODS`` before the loop serves.

Heavy deps stay behind the same seams the features already use: this module does
NOT import faster-whisper / scenedetect / verthor / a provider at module load.
The transcribe/select/translate handlers reach those only inside a job body.
"""

from __future__ import annotations

import json as _json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from . import library as _library
from . import protocol
from .features import boundary as _boundary
from .features import convert as _convert
from .features import media_compat as _media_compat
from .features import nle_export as _nle_export
from .features import offline as _offline
from .features import package_export as _package_export
from .features import shortmaker as _shortmaker
from .features import shorts as _shorts_meta
from .features import subtitles as _subtitles
from .features import timeline as _timeline
from .features import tracks as _tracks
from .features import transcribe as _transcribe
from .protocol import ErrorCode, RpcContext, RpcError
from .settings_store import SettingsStore, default_config_dir
from .util import get_logger

log = get_logger("media_studio.handlers")

Video = dict[str, Any]
SubtitleTrack = dict[str, Any]
Candidate = dict[str, Any]


@dataclass(frozen=True)
class _BudgetRequest:
    """A wire-coerced budget request (satisfies ``budget.BudgetRequest`` duck-type).

    ``target_size`` is the discrete output count (``None`` -> the budget default);
    the two byte fields are the per-request egress split by data kind.
    """

    target_size: int | None
    text_bytes: int
    frame_bytes: int


@dataclass(frozen=True)
class _LocalPoolEntry:
    """A single local backstop pool entry (satisfies ``budget.PoolEntry``)."""

    provider: str = "local"
    local: bool = True


@dataclass(frozen=True)
class _LocalOnlyPool:
    """A local-only fallback pool used when the provider module is a test stub.

    Satisfies :func:`budget.estimate`'s pool shape (``.entries`` of provider/local
    items); the budget then reports local-only with zero cloud egress.
    """

    entries: tuple[_LocalPoolEntry, ...] = (_LocalPoolEntry(),)


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _routing_block(routing: dict[str, Any]) -> dict[str, Any]:
    """Extract the persistable ``{perFunction}`` block from a preset routing.

    ``presets.apply_preset`` returns ``{activePreset, perFunction}``; the settings
    ``routing`` key stores only the ``{perFunction}`` map (``activePreset`` is its
    own settings key), so this drops the redundant ``activePreset`` field.
    """
    return {"perFunction": routing["perFunction"]}


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
        now: Callable[[], float] | None = None,
        vlm_clip_frame_loader: Any | None = None,
        vlm_frame_encoder: Any | None = None,
        vlm_models_present: Callable[[dict[str, Any]], bool] | None = None,
        vlm_chat_transport: Any | None = None,
        local_detector: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
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

    # ===================================================================== #
    # resolvers
    # ===================================================================== #
    def _resolve_video_path(self, video_id: str) -> str | None:
        """videoId -> absolute media path (or None if unknown)."""
        video = self.library.get(video_id)
        if video is None:
            return None
        return video.get("path") or None

    def _project_path(self, video_id: str) -> Path:
        """The manifest path for a video's project (one project per video)."""
        return self.projects_dir / f"{video_id}.json"

    def _load_or_create_project(self, video_id: str) -> _library.Project:
        """Open the video's project manifest, creating a fresh one if absent."""
        path = self._project_path(video_id)
        if path.exists():
            return _library.Project.open(path)
        video = self.library.get(video_id)
        if video is None:
            raise _invalid(f"unknown video: {video_id}")
        project = _library.Project.new(video, settings=self.settings.get())
        project.save(path)
        return project

    def _find_project_for_track(self, track_id: str) -> _library.Project:
        """Find the project whose tracks contain ``track_id`` (scan manifests).

        CONTRACT-NOTE: tracks.rename / tracks.relabel send only a ``trackId`` (no
        ``videoId``), so we locate the owning project by scanning the per-video
        manifests. Other tracks.* methods carry ``videoId`` and use the direct
        path. Raises INVALID_PARAMS when no project owns the id.
        """
        if self.projects_dir.exists():
            for manifest in sorted(self.projects_dir.glob("*.json")):
                try:
                    project = _library.Project.open(manifest)
                except Exception:  # noqa: BLE001 - skip an unreadable manifest
                    continue
                for track in project.data.get("tracks") or []:
                    if isinstance(track, dict) and track.get("id") == track_id:
                        return project
        raise _invalid(f"unknown track: {track_id}")

    # ===================================================================== #
    # library.*
    # ===================================================================== #
    def library_list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.list`` -> ``{videos:[Video]}`` (§2). Direct-return."""
        return {"videos": self.library.list()}

    def library_add(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.add({path})`` -> ``{video}`` (§2). Direct-return."""
        path = _require_str(params, "path")
        title = params.get("title")
        try:
            video = self.library.add(path, title if isinstance(title, str) else None)
        except FileNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        return {"video": video}

    def library_remove(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``library.remove({id})`` -> ``{ok:true}`` (§2). Direct-return."""
        video_id = _require_str(params, "id")
        ok = self.library.remove(video_id)
        return {"ok": bool(ok)}

    # ===================================================================== #
    # project.*
    # ===================================================================== #
    def project_open(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.open({id})`` -> ``{project}`` (§2). Direct-return.

        CONTRACT-NOTE: the UI sends a video ``id``; ``library.Project.open`` takes
        a *manifest path*. We resolve id -> the per-video manifest, creating a
        fresh project on first open so the Workspace always has a project.
        """
        video_id = _require_str(params, "id")
        project = self._load_or_create_project(video_id)
        return {"project": project.data}

    def project_save(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.save({project})`` -> ``{ok}`` (§2). Direct-return."""
        project_data = params.get("project")
        if not isinstance(project_data, dict):
            raise _invalid("project (object) is required")
        video = project_data.get("video") or {}
        video_id = video.get("id") if isinstance(video, dict) else None
        if not isinstance(video_id, str) or not video_id:
            raise _invalid("project.video.id is required to save")
        proj = _library.Project(dict(project_data), manifest_path=self._project_path(video_id))
        proj.save()
        return {"ok": True}

    def project_consolidate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``project.consolidate({id})`` -> ``{ok, folder}`` (§2). Direct-return."""
        video_id = _require_str(params, "id")
        project = self._load_or_create_project(video_id)
        folder = self.projects_dir / f"{video_id}-consolidated"
        out = project.consolidate(folder)
        return {"ok": True, "folder": out}

    # ===================================================================== #
    # settings.*
    # ===================================================================== #
    def settings_get(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``settings.get()`` -> §2 settings object. Direct-return."""
        return self.settings.get()

    def settings_set(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``settings.set({...})`` -> merged §2 settings object. Direct-return.

        CONTRACT-NOTE (WU-keys): ``settings.set`` returns ``self.settings.set``'s
        REDACTED merged view (``SettingsStore.set`` backfills + redacts the same
        way ``get`` does), so the round-tripped response never echoes a full key.
        """
        return self.settings.set(dict(params))

    # ===================================================================== #
    # providers.* (WU-keys: user-brings keys; RPC is key-free / redacted)
    # ===================================================================== #
    def providers_catalog(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.catalog()`` -> the static curated model catalog (WU-catalog).

        Returns :data:`catalog.CATALOG` as JSON: every provider/model with its
        per-task tiers, privacy / train-on-input flags, unit, free limits, the
        editorial top-pick per task, and the dated ``asOfDate`` stamp. PURE data —
        NO API keys, URLs, or secrets ever appear in this payload (the catalog is
        curated metadata; the user's keys live only in the redacted providers.list
        view). The renderer reads the camelCase wire shape verbatim.
        """
        from .models import catalog as _catalog  # local: import-light pure data

        return _catalog.catalog_to_json()

    def providers_list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.list()`` -> ``{providers:[...redacted...]}`` (WU-keys).

        Returns the configured pool with every ``apiKeys`` entry REDACTED to
        last-4 — the RPC layer NEVER returns a full key. Sourced from the
        already-redacting :meth:`SettingsStore.get`.
        """
        providers = self.settings.get().get("providers")
        return {"providers": providers if isinstance(providers, list) else []}

    def providers_upsert(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.upsert({id, provider?, kind?, baseUrl?, model?, apiKeys?, enabled?,
        capabilities?, unit?})`` -> ``{providers:[...redacted...]}`` (WU-keys).

        Inserts a new provider entry or merges into the existing one with the same
        ``id`` (RAW keys are stored). The returned providers list is REDACTED.
        Adding more keys to the SAME provider is failover-only (never N x quota,
        SE2) — that semantics lives in the rotation pool; here we just store them.
        """
        nested = params.get("provider")
        entry: dict[str, Any] = nested if isinstance(nested, dict) else params
        provider_id = entry.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise _invalid("providers.upsert requires a provider id")
        existing = list(self.settings.get_raw().get("providers") or [])
        merged: list[dict[str, Any]] = []
        found = False
        for raw in existing:
            if isinstance(raw, dict) and raw.get("id") == provider_id:
                patch = {k: v for k, v in entry.items() if k != "id"}
                merged.append({**raw, **patch, "id": provider_id})
                found = True
            elif isinstance(raw, dict):
                merged.append(raw)
        if not found:
            merged.append(dict(entry))
        self.settings.set({"providers": merged})
        return self.providers_list(params, ctx)

    def providers_remove(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.remove({id})`` -> ``{providers:[...redacted...]}`` (WU-keys).

        Drops the provider entry with the given ``id``; returns the REDACTED
        remaining list. Removing an absent id is a no-op (idempotent).
        """
        provider_id = _require_str(params, "id")
        existing = list(self.settings.get_raw().get("providers") or [])
        remaining = [raw for raw in existing if not (isinstance(raw, dict) and raw.get("id") == provider_id)]
        self.settings.set({"providers": remaining})
        return self.providers_list(params, ctx)

    def providers_test_key(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.testKey({baseUrl, model?, apiKey})`` -> ``{ok, capabilities?, error?}``.

        Validates a key by issuing ONE minimal completion through the provider
        seam (a fake transport in tests). NEVER echoes the key back: the response
        carries only ``ok`` + the declared ``capabilities`` + a SCRUBBED ``error``
        string on failure (the live key is stripped at the provider construction
        site, so a 4xx error body never leaks the key over RPC).
        """
        base_url = _require_str(params, "baseUrl")
        api_key = params.get("apiKey")
        if not isinstance(api_key, str) or not api_key:
            raise _invalid("providers.testKey requires an apiKey")
        capabilities = [str(c) for c in (params.get("capabilities") or ["text"])]
        from .models import provider as _provider_mod  # local: heavy seam

        prov = _provider_mod.CloudProvider(
            api_key=api_key,
            base_url=base_url,
            model=str(params.get("model") or _provider_mod.DEFAULT_CLOUD_MODEL),
            transport=self._test_key_transport,
        )
        try:
            prov.chat([{"role": "user", "content": "ping"}], max_tokens=1)
        except _provider_mod.ProviderError as exc:
            # The message is already scrubbed at the construction site; do NOT add
            # the key back. Defensively scrub again in case a caller-side detail
            # carried it.
            from .models.secrets import scrub_error_body

            return {"ok": False, "error": scrub_error_body(str(exc), [api_key])}
        return {"ok": True, "capabilities": capabilities}

    def providers_set_consent(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.setConsent({provider, text?, frames?})`` -> ``{consent}`` (WU-keys / SE1).

        TEXT (transcripts) and FRAMES (vision) consent are SEPARATE and
        independently revocable: only the keys present in the request are changed,
        so revoking ``frames`` leaves ``text`` intact and vice-versa. Returns the
        full consent block (no secrets — consent carries booleans only).
        """
        provider_name = _require_str(params, "provider")
        raw = self.settings.get_raw()
        consent = dict(raw.get("consent") or {})
        per_provider = dict(consent.get("perProvider") or {})
        current = dict(per_provider.get(provider_name) or {})
        if "text" in params:
            current["text"] = bool(params.get("text"))
        if "frames" in params:
            current["frames"] = bool(params.get("frames"))
        per_provider[provider_name] = current
        consent["perProvider"] = per_provider
        self.settings.set({"consent": consent})
        return {"consent": consent}

    def providers_usage(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.usage()`` -> ``{usage:[...]}`` per-key live usage (WU-usage-ui).

        Surfaces the rotation pool's per-key accounting
        ``{provider, key(redacted), used, max, unit, resetAt}`` — already produced
        from optimistic decrement + parsed 429/``X-RateLimit-*`` headers, so this
        is NOT a poller (no background loop, no per-call burst: the pool is built
        with ``detect_local=False`` so no ``GET /models`` socket is opened).

        The pool's in-memory counters reset each process, so the last-known numbers
        are PERSISTED (timestamped) in ``settings.usageCache`` and folded back in
        on read (DESIGN §15-Q1): the UI shows immediately on launch without
        re-polling, and rows older than the >10-min threshold are flagged ``stale``
        (the renderer desaturates them + shows "last checked Xm ago"). The ``key``
        field is ALWAYS the redacted last-4 (the pool never carries a live key into
        this row), so no full key crosses RPC.
        """
        from .models.usage import flag_stale, merge_usage_cache

        live_rows: list[dict[str, Any]] = list(self._ai_pool().usage())
        raw_cache = self.settings.get_raw().get("usageCache")
        cache: dict[str, Any] = raw_cache if isinstance(raw_cache, dict) else {}
        raw_rows = cache.get("rows")
        cached_rows: list[dict[str, Any]] = raw_rows if isinstance(raw_rows, list) else []
        raw_checked = cache.get("checkedAt")
        checked_at: dict[str, Any] = raw_checked if isinstance(raw_checked, dict) else {}

        merged = merge_usage_cache(live_rows, cached_rows)
        now = self._now()
        # A row that carries real data this call is freshly checked NOW; one that
        # only survived from the persisted cache keeps its previous timestamp so
        # its age (and stale flag) keep counting up across reads.
        next_checked: dict[str, float] = {}
        for live in live_rows:
            ident = "\x00".join((str(live.get("provider", "")), str(live.get("key", ""))))
            used = live.get("used")
            fresh = (isinstance(used, (int, float)) and used > 0) or live.get("max") is not None
            next_checked[ident] = now if fresh else float(checked_at.get(ident, now))

        stamped = flag_stale(merged, now=now, checked_at=next_checked)
        # Persist the merged snapshot so the next launch shows it without polling.
        self.settings.set({"usageCache": {"rows": merged, "checkedAt": next_checked, "savedAt": now}})
        return {"usage": stamped}

    # ===================================================================== #
    # providers.* presets + per-function routing (WU-presets / PH3)
    # ===================================================================== #
    def providers_apply_preset(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.applyPreset({name})`` -> ``{activePreset, routing}`` (WU-presets).

        Resolves one of the smart presets (``privacy`` / ``bestFreeCloud`` /
        ``balanced``) into a concrete ``routing.perFunction`` map over the REAL
        curated catalog (via :class:`presets.CatalogAdapter`) and PERSISTS it. The
        ``privacy`` preset routes every function to local (zero cloud egress);
        ``bestFreeCloud`` picks the catalog's per-task top model with a local
        backstop; ``balanced`` mixes cloud text with local vision.
        """
        name = _require_str(params, "name")
        from .models import presets as _presets  # local: import-light pure seam

        try:
            routing = _presets.apply_preset(name, self.settings.get(), _presets.CatalogAdapter())
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        self.settings.set({"activePreset": routing["activePreset"], "routing": _routing_block(routing)})
        return {"activePreset": routing["activePreset"], "routing": _routing_block(routing)}

    def providers_set_function_model(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.setFunctionModel({function, provider})`` -> ``{activePreset, routing}``.

        Overrides ONE function's routed provider (a catalog model-id or the
        :data:`presets.LOCAL` sentinel), leaving the other slots untouched, and
        flips ``activePreset`` to ``"custom"`` so the UI reflects the hand-edit.
        An unknown function or a missing provider is a typed invalid-params error.
        """
        from .models import presets as _presets  # local: import-light pure seam

        function = _require_str(params, "function")
        if function not in _presets.FUNCTIONS:
            raise _invalid(f"unknown function: {function!r}")
        provider_id = _require_str(params, "provider")
        routing = dict(self.settings.get().get("routing") or {})
        per_function = dict(routing.get("perFunction") or {})
        per_function[function] = {"provider": provider_id, "fallback": []}
        new_routing = {"perFunction": per_function}
        self.settings.set({"activePreset": "custom", "routing": new_routing})
        return {"activePreset": "custom", "routing": new_routing}

    def providers_first_run(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``providers.firstRun({choice?})`` -> the first-run local-vs-cloud chooser (P1 #6).

        With NO ``choice`` it is a READ: returns ``{firstRunChoiceMade, default}``
        where ``default`` is the local-safe :func:`presets.first_run_default`
        (``"privacy"`` until the user picks). With a ``choice`` (``"privacy"`` or
        any preset name) it APPLIES that preset, sets ``firstRunChoiceMade=True``,
        and returns ``{firstRunChoiceMade, activePreset, routing}`` — so a cloud
        choice flips the routing while a local choice keeps the all-local default.
        """
        from .models import presets as _presets  # local: import-light pure seam

        choice = params.get("choice")
        if choice is None:
            return {
                "firstRunChoiceMade": bool(self.settings.get().get("firstRunChoiceMade")),
                "default": _presets.first_run_default(self.settings.get()),
            }
        if not isinstance(choice, str) or choice not in _presets.PRESETS:
            raise _invalid(f"unknown first-run choice: {choice!r}")
        try:
            routing = _presets.apply_preset(choice, self.settings.get(), _presets.CatalogAdapter())
        except ValueError as exc:  # pragma: no cover -- choice is guarded against PRESETS above
            raise _invalid(str(exc)) from exc
        block = _routing_block(routing)
        self.settings.set({"firstRunChoiceMade": True, "activePreset": routing["activePreset"], "routing": block})
        return {"firstRunChoiceMade": True, "activePreset": routing["activePreset"], "routing": block}

    # -- per-function routing resolution (the seam wiring) ------------------ #
    def _function_prefer(self, function: str) -> str | None:
        """Return the configured provider id the ``function`` seam should prefer.

        Reads ``routing.perFunction[function].provider`` (a catalog model-id, the
        :data:`presets.LOCAL` sentinel, or unset). The sentinel maps to
        :data:`provider.LOCAL_PROVIDER_ID` (a local-only route); an unset slot
        returns ``None`` (the pool keeps its configured order). The provider id is
        threaded into ``get_provider``/``get_translator`` as ``prefer=`` so the
        seam tries that provider first (PLAN §WU-presets acceptance (b)).
        """
        routing = self.settings.get().get("routing")
        if not isinstance(routing, dict):
            return None
        per_function = routing.get("perFunction")
        if not isinstance(per_function, dict):
            return None
        slot = per_function.get(function)
        if not isinstance(slot, dict):
            return None
        provider_id = slot.get("provider")
        return provider_id if isinstance(provider_id, str) and provider_id else None

    def _provider_for_function(self, function: str) -> Any:
        """Build the LLM provider the ``function`` seam uses, honoring routing.

        FACTORY PATH (PLAN §WU-keys): RAW keys via ``get_raw()``. The routed
        provider (``_function_prefer``) is tried first; the rest of the pool is
        failover with the local backstop last (or local-only when routed to LOCAL).
        """
        from .models import provider as _provider_mod  # local: heavy seam

        return _provider_mod.get_provider(self.settings.get_raw(), prefer=self._function_prefer(function))

    def _translator_for_function(self, function: str) -> Any:
        """Build the TieredTranslator whose tier3 hosted pool honors routing."""
        from .models import translation as _translation_mod  # local: heavy seam

        return _translation_mod.get_translator(
            self.settings.get_raw(), runner=self._get_model_runner(), prefer=self._function_prefer(function)
        )

    # ===================================================================== #
    # WU-vision: Tier-2 vision re-rank resolution (cloud pool / local / off)
    # ===================================================================== #
    def _frame_consented_vision_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Return ``settings`` with ``providers`` filtered to FRAME-consented entries.

        CRITICAL PRIVACY INVARIANT (PLAN §WU-vision acceptance (a): "NO frame
        egressed without that provider's frame consent"): the rotation pool that
        backs :class:`CloudVlmBackend` rotates across EVERY vision-capable cloud
        entry on a 429, so consent must be enforced PER-ENTRY at pool-construction
        time — not once against the first provider. Any cloud provider whose FRAME
        consent (``consent.perProvider[<provider>].frames``) is not explicitly
        granted is DROPPED from ``providers`` before the pool is built, so a 429
        failover can NEVER reach a non-consented target. Local-backstop entries
        (added inside ``build_pool_provider``, no key) are unaffected — they never
        egress. PURE: returns a new settings dict; the original is never mutated.
        """
        from .models import consent as _consent  # local: import-light pure gate

        providers = settings.get("providers")
        if not isinstance(providers, list):
            return settings
        kept = [
            p
            for p in providers
            if isinstance(p, dict)
            and _consent.frame_consent_granted(settings, str(p.get("provider") or p.get("id") or "cloud"))
        ]
        return {**settings, "providers": kept}

    def _text_consented_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Return ``settings`` with ``providers`` filtered to TEXT-consented entries.

        CRITICAL PRIVACY INVARIANT (PLAN §WU-A1, G-A5 — the text analog of
        :meth:`_frame_consented_vision_settings`): the embedder rotation pool any
        cloud ``index`` route builds rotates across EVERY cloud entry on a 429, so
        TEXT consent must be enforced PER-ENTRY at pool-construction time — not once
        against the first provider — or a failover could rotate transcript text onto
        a non-consented target. Any provider whose TEXT consent
        (``consent.perProvider[<provider>].text``) is not explicitly granted is
        DROPPED from ``providers`` before the pool is built. Local-backstop entries
        (no key) are unaffected — they never egress. PURE: returns a new settings
        dict; the original is never mutated.

        Scope (PLAN §WU-A1): this seam is introduced HERE and consumed ONLY by the
        ``index`` routes; wiring it into the existing text functions
        (translation/select/subtitles) is an explicit follow-up (DESIGN §4 G-A5).
        """
        from .models import consent as _consent  # local: import-light pure gate

        providers = settings.get("providers")
        if not isinstance(providers, list):
            return settings
        kept = [
            p
            for p in providers
            if isinstance(p, dict)
            and _consent.text_consent_granted(settings, str(p.get("provider") or p.get("id") or "cloud"))
        ]
        return {**settings, "providers": kept}

    def _vision_pool(self, settings: dict[str, Any]) -> Any:
        """Build the vision rotation pool honoring routing.perFunction["vision"].

        FACTORY PATH (PLAN §WU-keys): RAW keys via the caller's ``get_raw()``
        ``settings``. The routed vision provider is tried first; detection of local
        Ollama/LM-Studio is OFF here (no socket — only the configured cloud vision
        entries + the local backstop are needed). ``None`` when the provider module
        is a test stub without ``build_pool_provider``.

        SECURITY: callers building the cloud egress pool MUST pass settings already
        filtered through :meth:`_frame_consented_vision_settings`, so every
        cloud slot the pool may rotate to is frame-consented (no rotation bypass).
        """
        from .models import provider as _provider_mod  # local: heavy seam

        builder = getattr(_provider_mod, "build_pool_provider", None)
        if builder is None:  # pragma: no cover -- only when provider is a stub w/o the pool builder
            return None
        return builder(
            settings,
            transport=self._vlm_chat_transport,
            detect_local=False,
            prefer=self._function_prefer("vision"),
        )

    def _vision_provider_for_consent(self, settings: dict[str, Any]) -> str | None:
        """The provider NAME a frame-consented vision pool would egress frames to.

        Builds the routed vision pool over the FRAME-CONSENT-FILTERED providers and
        returns the first vision-capable CLOUD entry's provider name — exactly the
        egress target. Because the input is already consent-filtered, ANY cloud
        entry it returns is one whose FRAME consent is granted; ``None`` when no
        consented cloud entry can serve vision (then the cloud path is never taken,
        so no frame is ever prepared for egress).
        """
        pool = self._vision_pool(self._frame_consented_vision_settings(settings))
        if pool is None:  # pragma: no cover -- stub-provider guard (see _vision_pool)
            return None
        from .models.provider import DEFAULT_CAPABILITY  # local: import-light

        _vision = "vision"
        for entry in pool.entries:
            if not entry.local and _vision in entry.capabilities and _vision != DEFAULT_CAPABILITY:
                return entry.provider
        return None

    def _resolve_vlm_reranker(self, settings: dict[str, Any], *, media_path: str) -> Any:
        """Resolve the Tier-2 ``vlm_reranker`` BEFORE any frame is sampled (WU-vision).

        The frame-egress consent gate is the FIRST decision, so a no-consent run
        never prepares a frame for egress. Decision tree (PLAN §WU-vision):

        1. At least one cloud vision provider is routed AND frame-consented ->
           a :class:`SmolVlmReranker` whose backend factory is a CLOSURE building a
           :class:`smolvlm2.CloudVlmBackend` over a pool filtered to ONLY
           frame-consented cloud entries (the ``BackendFactory`` signature stays
           ``settings -> SmolVlmBackend``). The pool can therefore only ever rotate
           to a consented provider on a 429 — no rotation bypass.
        2. Else if the local SmolVLM2 weights are present -> the local reranker.
        3. Else -> ``None`` (the existing transcript-only no-rerank path).
        """
        from .features import smolvlm2 as _sv  # local: import-light (no heavy import)

        raw_settings = self.settings.get_raw()
        vision_provider = self._vision_provider_for_consent(raw_settings)
        if vision_provider is not None:
            # SECURITY: the pool is built over ONLY frame-consented cloud entries,
            # so RotatingProvider.chat(capability="vision") can never fail over to a
            # provider whose frame consent was not granted (PLAN §WU-vision (a)).
            pool = self._vision_pool(self._frame_consented_vision_settings(raw_settings))

            def cloud_factory(backend_settings: Any) -> Any:
                return _sv.CloudVlmBackend(
                    pool=pool,
                    settings=backend_settings,
                    frame_encoder=self._vlm_frame_encoder,
                )

            return _sv.SmolVlmReranker(
                settings=settings,
                backend_factory=cloud_factory,
                clip_frame_loader=self._vlm_clip_frame_loader,
                media_path=media_path,
            )

        present = self._vlm_models_present or _sv.default_models_present
        if present(settings):
            return _sv.build_reranker(
                settings=settings,
                media_path=media_path,
                clip_frame_loader=self._vlm_clip_frame_loader,
                models_present=lambda _s: True,
            )
        return None

    # ===================================================================== #
    # WU-C3 — thumbnail.select (AI best-frame picker, frame-egress consented)
    # ===================================================================== #
    def _resolve_frame_scorer(self, settings: dict[str, Any]) -> Any:
        """Resolve the best-frame :data:`best_frame.FrameScorer`, or ``None`` (degrade).

        The EXACT decision tree of :meth:`_resolve_vlm_reranker` (DESIGN §3.2), so
        the frame-egress consent gate is the FIRST decision and a no-consent run
        never prepares a frame for egress:

        1. A cloud vision provider is routed AND frame-consented -> a
           :class:`best_frame.CloudFrameScorer` over a :class:`smolvlm2.CloudVlmBackend`
           bound to a pool filtered to ONLY frame-consented cloud entries (so a 429
           failover can never rotate frames onto a non-consented provider).
        2. Else if the local SmolVLM2 weights are present -> a CloudFrameScorer over
           the local backend (the same one-frame-per-clip reuse).
        3. Else -> ``None`` (the degrade-to-midpoint path; zero egress, no scoring).

        An injected ``frame_scorer`` seam wins outright (tests / overrides).
        """
        if self._frame_scorer is not None:
            return self._frame_scorer

        from .features import best_frame as _bf  # local: import-light (no cv2/model)
        from .features import smolvlm2 as _sv  # local: import-light

        raw_settings = self.settings.get_raw()
        vision_provider = self._vision_provider_for_consent(raw_settings)
        if vision_provider is not None:
            pool = self._vision_pool(self._frame_consented_vision_settings(raw_settings))
            backend = _sv.CloudVlmBackend(
                pool=pool,
                settings=settings,
                frame_encoder=self._vlm_frame_encoder,
            )
            return _bf.CloudFrameScorer(backend).score_frames

        present = self._vlm_models_present or _sv.default_models_present
        if present(settings):
            factory = self._frame_backend_factory or _sv._default_backend_factory
            return _bf.CloudFrameScorer(factory(settings)).score_frames
        return None

    def _frame_clip_loader(self) -> Any:
        """The clip-frame sampler for the thumbnail picker (injected fake or native).

        Tests inject ``vlm_clip_frame_loader`` (the SAME seam the re-ranker uses) so
        no cv2 is touched; the default is the heavy native loader (coverage-excluded
        prod seam), mirroring :meth:`_default_phase8_runner`.
        """
        if self._vlm_clip_frame_loader is not None:
            return self._vlm_clip_frame_loader
        from .features import smolvlm2 as _sv  # pragma: no cover - native default seam

        return _sv._default_clip_frame_loader  # pragma: no cover - native default seam

    def _frame_thumbnail_writer(self) -> Any:
        """The thumbnail writer for the picker (injected fake or the cv2 imwrite seam).

        Tests inject ``thumbnail_writer`` to record the ``(frame, path)`` call; the
        default is :func:`best_frame._default_thumbnail_writer` (the lone cv2
        ``imwrite`` line, coverage-excluded in WU-C2).
        """
        if self._thumbnail_writer is not None:
            return self._thumbnail_writer
        from .features import best_frame as _bf  # pragma: no cover - native default seam

        return _bf._default_thumbnail_writer  # pragma: no cover - native default seam

    def _resolve_thumbnail_span(self, params: dict[str, Any], video_id: str) -> tuple[str, float, float]:
        """Resolve ``(media_path, start, end)`` for the clip to thumbnail (DESIGN §3.2).

        An explicit ``{path, start, end}`` wins (the renderer's per-clip action
        forwards the produced clip). Otherwise a ``candidateId`` indexes the
        server-side selection cache (the SAME "rank@sourceStart" cache the
        short-maker export consults), whose candidate carries the source span
        (``sourceStart`` .. ``end``). The path then resolves from the video id.
        Raises INVALID_PARAMS when neither yields a usable span.
        """
        explicit_path = params.get("path")
        if isinstance(explicit_path, str) and explicit_path:
            start = float(params.get("start") or 0.0)
            end = float(params.get("end") or 0.0)
            return explicit_path, start, end

        candidate_id = params.get("candidateId")
        if isinstance(candidate_id, str) and candidate_id:
            cand = self._selection_cache.get(video_id, {}).get(candidate_id)
            if cand is None:
                raise _invalid(f"unknown candidateId for {video_id}: {candidate_id}")
            path = self._resolve_video_path(video_id)
            if not path:
                raise _invalid(f"unknown video: {video_id}")
            start = float(cand.get("sourceStart", cand.get("start", 0.0)) or 0.0)
            end = float(cand.get("end", 0.0) or 0.0)
            return path, start, end

        raise _invalid("thumbnail.select requires either {path} or {candidateId}")

    def thumbnail_select(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``thumbnail.select({videoId, candidateId?|path?, start?, end?})`` -> ``{jobId}`` (WU-C3).

        Pick the single best thumbnail frame for one produced clip with the AI
        best-frame picker, riding the shared :meth:`_run_ai_job` envelope for the
        universal cancel / degrade / budget framing. The work body:

        * Resolves the clip span (explicit ``{path,start,end}`` or a cached
          ``candidateId``) and the conventional ``<clip>.thumb.jpg`` write target.
        * Consults the AI content cache keyed by clip span + frame params, so a
          second identical call is a cache hit that NEVER re-scores (AC d).
        * Resolves the frame scorer through the frame-egress consent gate. With NO
          consent AND NO local weights it DEGRADES to the deterministic clip
          midpoint — zero egress, the scorer is never called, no thumbnail is
          written, and the job still succeeds (AC b/c/f).
        * Otherwise samples the clip's frames, scores them, writes the argmax frame
          via the cv2 writer seam, and records ``thumbnailFrameSec`` on the clip's
          metadata. Done payload: ``{frameTimeSec, thumbnailPath, score}`` (AC e).
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        media_path, start, end = self._resolve_thumbnail_span(params, video_id)
        settings = dict(self.settings.get())
        prompt = str(params.get("prompt") or "")

        def work(job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
            from .features import best_frame as _bf  # local: import-light (no cv2/model)

            thumb_path = str(_shorts_meta.thumbnail_path(media_path))
            cache = self._ai_cache()
            cache_key = cache.key(
                [{"role": "user", "content": prompt}],
                "thumbnail.select",
                {"path": media_path, "start": start, "end": end},
            )
            cached = cache.get(cache_key)
            if cached is not None:
                job_ctx.progress(100.0, "cache hit")
                return dict(cached)

            scorer = self._resolve_frame_scorer(settings)
            if scorer is None:
                # Degrade-to-midpoint: deterministic, zero egress, scorer untouched.
                midpoint = (start + end) / 2.0
                _shorts_meta.write_thumbnail_metadata(media_path, midpoint)
                result = {"frameTimeSec": midpoint, "thumbnailPath": thumb_path, "score": 0.0, "degraded": True}
                cache.put(cache_key, result)
                return result

            loader = self._frame_clip_loader()
            frames = list(loader(media_path, [(start, end)]))
            # Cancel checkpoint AFTER sampling but BEFORE scoring/writing, so a job
            # cancelled mid-load scores nothing and writes no thumbnail (AC f).
            if job_ctx.cancelled:
                return {"cancelled": True}
            stack = list(frames[0]) if frames else []
            frame_times = _evenly_spaced(start, end, len(stack))
            writer = self._frame_thumbnail_writer()
            picked = _bf.pick_best_frame(
                stack,
                prompt,
                frame_times=frame_times,
                thumbnail_path=thumb_path,
                scorer=scorer,
                writer=writer,
            )
            frame_sec = float(picked["frameTimeSec"])
            _shorts_meta.write_thumbnail_metadata(media_path, frame_sec)
            result = {
                "frameTimeSec": frame_sec,
                "thumbnailPath": str(picked["thumbnailPath"]),
                "score": float(picked["score"]),
                "degraded": False,
            }
            cache.put(cache_key, result)
            return result

        # The frame egress rides the shared AiJob substrate (cancel/degrade/budget)
        # exactly as phase8.select does. _run_ai_job sizes the pre-flight budget from
        # the messages only (a text-shaped estimate, frame_bytes=0) — the same
        # contract every _run_ai_job caller shares; threading a frame-shaped
        # BudgetRequest would mean widening that shared substrate, which is out of
        # this WU's scope. The confirmCloudBudget ack gate still fires for the cloud
        # path (willEgress stays True). The run provider is the routed vision provider.
        scorer_provider = self._provider if self._provider is not None else self._provider_for_function("vision")
        job = self._run_ai_job(
            ctx,
            messages=[{"role": "user", "content": prompt}],
            model=str(settings.get("cloudModel") or ""),
            provider=scorer_provider,
            work=work,
            feature="thumbnail",
            label="thumbnail.select",
            videoId=video_id,
            ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
        )
        return {"jobId": job.id}

    # ===================================================================== #
    # WU-A5 — index.* (semantic index: build [job] / search [direct] / status)
    # ===================================================================== #
    def _index_path(self, video_id: str) -> Path:
        """The per-video vector sidecar path (``projects/<videoId>.index.json``).

        PLAN §WU-A5 decision: vectors persist to a sidecar file NEXT TO the
        manifest, NOT the manifest body, so a large embedding matrix never bloats
        the project JSON. Deleting this file reverts the index (idempotent rebuild).
        """
        return self.projects_dir / f"{video_id}.index.json"

    def _read_index(self, video_id: str) -> dict[str, Any] | None:
        """Load the persisted index sidecar for ``video_id`` (``None`` if unbuilt).

        A missing, unreadable, or malformed sidecar is treated as "not built yet"
        (``None``) rather than an error — a corrupt index must not wedge search;
        the caller surfaces the typed "build the index first" guidance.
        """
        path = self._index_path(video_id)
        if not path.exists():
            return None
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - corrupt-sidecar guard (defensive)
            return None
        return data if isinstance(data, dict) else None  # pragma: no cover - shape guard (defensive)

    def _write_index(self, video_id: str, payload: dict[str, Any]) -> None:
        """Persist the index ``payload`` to the per-video sidecar (idempotent).

        ``projects_dir`` is ensured so a first build never fails on a missing dir;
        a rebuild overwrites the file wholesale (PLAN §WU-A5 (f)).
        """
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._index_path(video_id).write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _resolve_index_embedder(self, settings: dict[str, Any]) -> Any:
        """Resolve the embedder for the ``index`` route (cloud-consented or local).

        Mirrors :meth:`_resolve_frame_scorer`: the consent gate is the FIRST
        decision so transcript text is never prepared for a non-consented egress.

        1. An injected ``embedder`` seam wins outright (tests / a wholesale override).
        2. Else, over the TEXT-consent-filtered + routed providers, the first cloud
           (``not local``) entry yields a :class:`embedder.CloudEmbedder` bound to
           that entry's base URL / model / first key and the injectable
           ``embed_transport``. Because the pool is built from
           :meth:`_text_consented_settings`, ANY cloud entry it can reach is
           text-consented — a 429 failover can never rotate transcript text onto a
           provider the user did not consent to (PLAN §WU-A5 (c)/(c2)).
        3. Else -> the deterministic :class:`embedder.LocalEmbedder` backstop
           (offline / unconsented / no-cloud-key still produces vectors, zero egress).
        """
        if self._embedder is not None:
            return self._embedder

        from .models import embedder as _embedder  # local: import-light

        pool = self._ai_pool_for_index(self._text_consented_settings(settings))
        if pool is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
            return _embedder.LocalEmbedder()
        for entry in pool.entries:
            # ``build_pool_provider`` only materializes cloud specs that carry at
            # least one key (keyless cloud providers are dropped), so a non-local
            # entry is guaranteed to have ``entry.keys[0]`` — the egress target.
            if not entry.local:
                return _embedder.CloudEmbedder(
                    api_key=str(entry.keys[0]),
                    base_url=str(entry.base_url),
                    model=str(entry.model),
                    transport=self._embed_transport,
                )
        return _embedder.LocalEmbedder()

    def _ai_pool_for_index(self, settings: dict[str, Any]) -> Any:
        """Build the routed ``index`` rotation pool from ``settings`` (or ``None``).

        Honors ``routing.perFunction["index"]`` so the routed embeddings provider
        is tried first. Detection of local servers is OFF (no socket): the pool is
        read only for its catalog-shaped cloud entries (base URL / model / key) the
        embedder bridge consumes. ``None`` when the provider module is a test stub
        without ``build_pool_provider``.
        """
        from .models import provider as _provider_mod  # local: heavy seam

        builder = getattr(_provider_mod, "build_pool_provider", None)
        if builder is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
            return None
        return builder(settings, detect_local=False, prefer=self._function_prefer("index"))

    def index_build(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``index.build({videoId, confirmBudget?})`` -> ``{jobId}`` (WU-A5).

        A long job (custom ``work`` body via :meth:`_run_ai_job`): embed every
        transcript segment through the consent + budget-gated ``index`` route and
        persist the vectors to the per-video sidecar. The done payload is
        ``{segmentCount, model, builtAt, dim}``.

        The embedding egress rides the shared AiJob envelope so it inherits the
        cancel check, degrade tracking, and the SAME ``confirmCloudBudget`` ack the
        rest of the bundle enforces; the embedder itself is resolved through the
        per-entry TEXT-consent filter (:meth:`_resolve_index_embedder`) so a cloud
        route never reaches a non-consented provider. A transcript with zero
        segments builds an empty index (``segmentCount=0``) rather than erroring.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        project = self._load_or_create_project(video_id)
        transcript = project.data.get("transcript")
        if not transcript:
            raise _invalid(f"video {video_id} has no transcript yet (run transcribe.start first)")
        settings = dict(self.settings.get())

        def work(job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
            from .features import semantic_index as _si  # local: import-light (pure)

            corpus = _si.build_corpus(transcript)
            job_ctx.progress(10.0, "embedding transcript")
            embedder = self._resolve_index_embedder(settings)
            vectors = embedder.embed(corpus)
            dim = len(vectors[0]) if vectors else 0
            built_at = self._now()
            payload = {
                "model": str(getattr(embedder, "model", "local")),
                "dim": dim,
                "builtAt": built_at,
                "vectors": vectors,
            }
            self._write_index(video_id, payload)
            job_ctx.progress(100.0, "index built")
            return {
                "segmentCount": len(corpus),
                "model": payload["model"],
                "builtAt": built_at,
                "dim": dim,
            }

        # The query embedding's egress is sized text-shaped (the corpus is the
        # privacy-sensitive payload, but _run_ai_job's shared budget reads the
        # messages only — the same contract every caller shares). The cloud ack
        # gate still fires (willEgress stays True when a cloud index entry exists).
        job = self._run_ai_job(
            ctx,
            messages=[{"role": "user", "content": "index.build"}],
            model=str(settings.get("cloudEmbedModel") or settings.get("cloudModel") or ""),
            provider=self._provider,
            work=work,
            feature="index",
            label="index.build",
            videoId=video_id,
            ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
        )
        return {"jobId": job.id}

    def index_status(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``index.status({videoId})`` -> ``{built, segmentCount, model, builtAt, dim}``.

        Direct-return, pure file read (no provider call). An unbuilt video reports
        ``{built:false, segmentCount:0, model:None, builtAt:None, dim:0}``.
        """
        video_id = _require_str(params, "videoId")
        index = self._read_index(video_id)
        if index is None:
            return {"built": False, "segmentCount": 0, "model": None, "builtAt": None, "dim": 0}
        vectors = index.get("vectors")
        return {
            "built": True,
            "segmentCount": len(vectors) if isinstance(vectors, list) else 0,
            "model": index.get("model"),
            "builtAt": index.get("builtAt"),
            "dim": index.get("dim", 0),
        }

    def index_search(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``index.search({videoId, query, topK?, confirmBudget?})`` -> ``{hits:[...]}``.

        Direct-return: ONE short query-embedding call then a pure cosine over the
        already-persisted segment vectors. The inline query embedding is itself a
        cloud egress when routed to cloud, so it is NOT a silent provider call — it
        passes the SAME text-consent + budget path as :meth:`index_build`:

        * the embedder is resolved through :meth:`_resolve_index_embedder` (the
          per-entry TEXT-consent filter), so the query text never reaches a
          non-consented provider (PLAN §WU-A5 (c2));
        * the budget envelope is planned BEFORE any embedding and gated by
          :meth:`_enforce_cloud_budget_ack`, so an unacked cloud search egresses
          nothing (PLAN §WU-A5 (c3)). The envelope is planned over the
          text-consented settings so ``willEgress`` reflects post-consent reality
          (a consent-denied -> local search never spuriously demands an ack).
        * the query vector is cache-keyed via :meth:`_ai_cache`, so a repeated
          identical query never re-embeds (PLAN §WU-A5 (e)).

        Searching an unbuilt video raises a typed "build the index first"
        INVALID_PARAMS (mirrors :meth:`subtitles_generate`), never an empty list.
        """
        from .features import semantic_index as _si  # local: import-light (pure)
        from .models import ai_job as _ai_job  # local: import-light

        video_id = _require_str(params, "videoId")
        query = _require_str(params, "query")
        top_k = int(params.get("topK") or 8)
        index = self._read_index(video_id)
        if index is None:
            raise _invalid(f"video {video_id} has no semantic index yet (run index.build first)")

        settings = dict(self.settings.get())
        # Plan the budget envelope over the TEXT-consented settings so willEgress
        # reflects what would actually leave the box after the consent filter, then
        # enforce the ack BEFORE any embedding call (zero egress on an unacked run).
        inputs = _ai_job.AiInputs(
            messages=({"role": "user", "content": query},),
            model=str(settings.get("cloudEmbedModel") or settings.get("cloudModel") or ""),
        )
        envelope = self._plan_index_envelope(inputs)
        self._enforce_cloud_budget_ack(
            envelope,
            params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
        )

        cache = self._ai_cache()
        cache_key = cache.key(
            [{"role": "user", "content": query}],
            "index.search",
            {"model": inputs.model},
        )
        cached = cache.get(cache_key)
        if cached is not None:
            query_vec = list(cached)
        else:
            embedder = self._resolve_index_embedder(settings)
            query_vec = embedder.embed([query])[0]
            cache.put(cache_key, query_vec)

        vectors = index.get("vectors") or []
        project_transcript = self._load_or_create_project(video_id).data.get("transcript")
        segments = project_transcript.get("segments") or [] if isinstance(project_transcript, dict) else []
        hits = _si.search(query_vec, vectors, segments, top_k)
        return {"hits": hits}

    def _plan_index_envelope(self, inputs: Any) -> Any:
        """Plan the budget envelope for an ``index.search`` query over consented settings.

        Builds the planning pool from :meth:`_text_consented_settings` so the
        envelope's ``willEgress`` reflects what would leave the box AFTER the
        per-entry text-consent filter — a consent-denied search routes local and so
        never spuriously demands a budget ack (PLAN §WU-A5 (c3)).
        """
        from .models import ai_job as _ai_job  # local: import-light

        pool: Any = self._ai_pool_for_index(self._text_consented_settings(dict(self.settings.get())))
        if pool is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
            pool = _LocalOnlyPool()
        return _ai_job.plan_ai_job(
            inputs,
            pool=pool,
            catalog=_ai_job.CatalogFreeCapAdapter(),
            cache=self._ai_cache(),
        )

    # ===================================================================== #
    # subtitles.* (generate/edit/export direct; translate = job)
    # ===================================================================== #
    def subtitles_generate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.generate({videoId})`` -> ``{track}`` (§2). Direct-return.

        CONTRACT-NOTE: the pure ``subtitles.generate`` takes a *transcript*; the
        wire sends ``{videoId}``. We load the video's project transcript, generate
        the track, persist it onto the project, and return ``{track}``.
        """
        video_id = _require_str(params, "videoId")
        project = self._load_or_create_project(video_id)
        transcript = project.data.get("transcript")
        if not transcript:
            raise _invalid(f"video {video_id} has no transcript yet (run transcribe.start first)")
        # WU9 wiring: settings['captionPolish'] runs the Netflix CPS/CPL + punct/
        # casing/emphasis/profanity polish over the cues (degrade-safe — model
        # stages skip when their backends are absent). Off -> the plain generate.
        settings = self.settings.get()
        if settings.get("captionPolish"):
            track = _subtitles.generate_polished(transcript, settings=settings)
        else:
            track = _subtitles.generate(transcript)
        _tracks.add_track(project.data, track)
        project.save()
        return {"track": track}

    def subtitles_edit(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.edit({trackId, cues})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        cues = params.get("cues")
        if not isinstance(cues, list):
            raise _invalid("cues (array) is required")
        project = self._find_project_for_track(track_id)
        existing = _tracks.find_track(project.data, track_id)
        updated = _subtitles.edit(existing, cues)
        # Persist the edit back onto the project's track list (immutable replace).
        project.data["tracks"] = [
            updated if (isinstance(t, dict) and t.get("id") == track_id) else t
            for t in project.data.get("tracks") or []
        ]
        project.save()
        return {"track": updated}

    def subtitles_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.export({trackId, format})`` -> ``{path}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        fmt = _require_str(params, "format")
        project = self._find_project_for_track(track_id)
        track = _tracks.find_track(project.data, track_id)
        out_path = self.exports_dir / f"{track_id}.{fmt.lower().lstrip('.')}"
        try:
            path = _subtitles.export(track, fmt, out_path)
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        return {"path": path}

    def subtitles_translate(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``subtitles.translate({trackId, targetLang, bilingual?, order?})`` -> ``{jobId}`` (§2).

        Long job: returns ``{jobId}``, streams ``job.progress``, and its
        ``job.done.result`` is ``{track}``. The pure ``translate`` is synchronous;
        we run it in a job so the contract's ``{jobId}`` + progress shape holds.

        BILINGUAL (captions-export): when ``bilingual`` is truthy the translated
        cues are STACKED with the originals into one track (original + translation
        on two lines per cue, via :func:`subtitles.stack_bilingual`). ``order``
        ("original-first" | "translation-first") picks which line sits on top. The
        stacked track is added as a NEW track on the project (the source track is
        left intact); a monolingual translate still replaces in place as before.
        """
        track_id = _require_str(params, "trackId")
        target_lang = _require_str(params, "targetLang")
        bilingual = bool(params.get("bilingual"))
        order = params.get("order")
        order = order if order in _subtitles.BILINGUAL_ORDERS else "original-first"
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        # Offline gate: the cloud translation path goes to a remote API; refuse
        # it (typed) when offline. Local (llama) translation stays offline-safe.
        settings_now = self.settings.get()
        if settings_now.get("useCloud"):
            _offline.guard_network(settings_now, "cloud translation")
        project = self._find_project_for_track(track_id)
        track = _tracks.find_track(project.data, track_id)
        # WU-presets: the translation seam honors routing.perFunction["translation"]
        # (its tier3 hosted pool tries the routed provider first); falls back to the
        # legacy injected provider when one is set (existing tests).
        translator = None if self._provider is not None else self._translator_for_function("translation")
        legacy_provider = self._provider if translator is None else None
        save_path = project.manifest_path

        def work(job_ctx: Any, _envelope: Any, provider: Any) -> dict[str, Any]:
            if translator is not None:
                # T3 tiered path: language-aware tier routing + fallback chain;
                # tier failures surface via job.done error payload (A6.3).
                translated = translator.translate_track(
                    track,
                    target_lang,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
            else:
                translated = _subtitles.translate(
                    track,
                    target_lang,
                    provider=provider,
                    progress=lambda pct, msg: job_ctx.progress(pct, msg),
                    cancelled=lambda: job_ctx.cancelled,
                )
            if bilingual:
                # Stack original + translation into a NEW track; keep the source.
                stacked = _subtitles.stack_bilingual(track, translated, order=order)
                _tracks.add_track(project.data, stacked)
                if save_path is not None:
                    project.save(save_path)
                return {"track": stacked}
            # Monolingual: replace the source track in place (legacy behaviour).
            project.data["tracks"] = [
                translated if (isinstance(t, dict) and t.get("id") == track_id) else t
                for t in project.data.get("tracks") or []
            ]
            if save_path is not None:
                project.save(save_path)
            return {"track": translated}

        # WU-envelope: subtitle translation rides the AiJob substrate (shared
        # cancel-check + degrade-aware provider) while keeping the {jobId} shape
        # and the {track} done payload. The legacy injected provider (tests) is
        # passed through; the T3 tiered path ignores the work's provider arg.
        job = self._run_ai_job(
            ctx,
            messages=[{"role": "user", "content": target_lang}],
            model=str(settings_now.get("cloudModel") or ""),
            provider=legacy_provider,
            work=work,
            feature="subtitles",
            label="subtitles.translate",
            videoId=None,
            ack=params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
        )
        return {"jobId": job.id}

    # ===================================================================== #
    # tracks.* (list/rename/relabel/add/remove/strip direct; burn = job)
    # ===================================================================== #
    def tracks_list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.list({videoId})`` -> ``{tracks}`` (§2). Direct-return."""
        video_id = _require_str(params, "videoId")
        project = self._load_or_create_project(video_id)
        return {"tracks": _tracks.list_tracks(project.data)}

    def tracks_rename(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.rename({trackId, name})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        name = _require_str(params, "name")
        project = self._find_project_for_track(track_id)
        try:
            track = _tracks.rename_track(project.data, track_id, name)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"track": track}

    def tracks_relabel(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.relabel({trackId, lang})`` -> ``{track}`` (§2). Direct-return."""
        track_id = _require_str(params, "trackId")
        lang = _require_str(params, "lang")
        project = self._find_project_for_track(track_id)
        try:
            track = _tracks.relabel_track(project.data, track_id, lang)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"track": track}

    def tracks_add(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.add({videoId, trackId})`` -> ``{ok}`` (§2). Direct-return.

        CONTRACT-NOTE: the wire sends ``{videoId, trackId}`` but the pure
        ``add_track`` needs a *track object*. We locate the track in whatever
        project currently owns it (the available-tracks source) and copy it onto
        the target video's project.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        track = params.get("track")
        if not isinstance(track, dict):
            # Resolve the full track object from the project that owns the id.
            track = _tracks.find_track(self._find_project_for_track(track_id).data, track_id)
        project = self._load_or_create_project(video_id)
        try:
            _tracks.add_track(project.data, track)
        except _tracks.TrackError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"ok": True}

    def tracks_remove(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.remove({videoId, trackId})`` -> ``{ok}`` (§2). Direct-return."""
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        project = self._load_or_create_project(video_id)
        try:
            _tracks.remove_track(project.data, track_id)
        except _tracks.HardSubtitleError as exc:
            raise _invalid(str(exc)) from exc
        except _tracks.TrackNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        project.save()
        return {"ok": True}

    def tracks_strip(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.strip({videoId, trackId})`` -> ``{path}`` (§2). Direct-return.

        CONTRACT-NOTE: §2 types strip as a plain ``{path}`` (not a job). We re-mux
        the source omitting the track's subtitle stream via ``strip_track`` (its
        ffmpeg ``run`` seam is injectable for tests).
        """
        video_id = _require_str(params, "videoId")
        _require_str(params, "trackId")
        in_path = self._resolve_video_path(video_id)
        if not in_path:
            raise _invalid(f"unknown video: {video_id}")
        settings = self.settings.get()
        run = self._ffmpeg_run or _self_ffmpeg_run()
        probe = self._ffprobe_duration or _self_ffprobe()
        try:
            path = _tracks.strip_track(in_path, settings=settings, run=run, duration=probe)
        except _tracks.TrackError as exc:
            raise RpcError(str(exc), ErrorCode.INTERNAL_ERROR) from exc
        return {"path": path}

    def tracks_burn(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``tracks.burn({videoId, trackId})`` -> ``{jobId}`` (§2). Job-based.

        Long job: returns ``{jobId}``, streams progress, ``job.done.result`` is
        ``{path}``. Burning re-encodes the video, so it must run as a job.
        """
        video_id = _require_str(params, "videoId")
        track_id = _require_str(params, "trackId")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        in_path = self._resolve_video_path(video_id)
        if not in_path:
            raise _invalid(f"unknown video: {video_id}")
        project = self._load_or_create_project(video_id)
        track = _tracks.find_track(project.data, track_id)
        settings = self.settings.get()
        run = self._ffmpeg_run or _self_ffmpeg_run()
        probe = self._ffprobe_duration or _self_ffprobe()

        def job_body(job_ctx: Any) -> dict[str, Any]:
            path = _tracks.burn_track(
                in_path,
                track,
                settings=settings,
                ctx=job_ctx,
                run=run,
                duration=probe,
            )
            return {"path": path}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    # ===================================================================== #
    # convert.* (both jobs — adapt the factory handlers)
    # ===================================================================== #
    def convert_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``convert.start({videoId|path, options})`` -> ``{jobId}`` (§2). Job-based.

        CONTRACT-NOTE (INTEGRATION-REPORT HIGH-1): ``convert.start_handler`` is a
        FACTORY returning a ``(JobContext)->{path}`` body, not a ``(params,ctx)``
        handler. We build the body, start it on ``ctx.jobs``, and return ``{jobId}``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        body = _convert.start_handler(
            params,
            settings=self.settings.get(),
            resolver=self._resolve_video_path,
            run=self._ffmpeg_run or _self_ffmpeg_run(),
            probe=self._ffprobe_duration or _self_ffprobe(),
        )
        job = ctx.jobs.start(body)
        return {"jobId": job.id}

    def convert_batch(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``convert.batch({items})`` -> ``{jobId}`` (§2). Job-based.

        ``job.done.result`` is ``{paths}``. Same factory-adaptation as start.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        body = _convert.batch_handler(
            params,
            settings=self.settings.get(),
            resolver=self._resolve_video_path,
            run=self._ffmpeg_run or _self_ffmpeg_run(),
            probe=self._ffprobe_duration or _self_ffprobe(),
        )
        job = ctx.jobs.start(body)
        return {"jobId": job.id}

    # ===================================================================== #
    # transcribe.start (job — handled via transcribe.make_transcribe_handler)
    # ===================================================================== #
    def transcribe_start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``transcribe.start({videoId, language?})`` -> ``{jobId}`` (§2). Job-based.

        Long job: returns ``{jobId}``, streams progress, ``job.done.result`` is
        ``{transcript}``. On completion the transcript is PERSISTED onto the
        video's project manifest (so subtitles.generate / shortmaker can read it)
        and the library's ``hasTranscript`` flag is flipped.

        CONTRACT-NOTE: we don't call ``_transcribe.make_transcribe_handler``
        directly because its job body only returns ``{transcript}`` — it can't
        persist onto our project store. We reuse ``transcribe.transcribe_file``
        (the pure transcription seam) inside our own job body instead.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        language = params.get("language")
        if language is not None and not isinstance(language, str):
            raise _invalid("language must be a string when given")
        audio_path = self._resolve_video_path(video_id)
        if not audio_path:
            raise _invalid(f"unknown video: {video_id}")
        loader = self._whisper_loader or _transcribe.FasterWhisperLoader()
        # WU7 wiring: settings['asrEngine'] picks whisper (default) or parakeet;
        # the duration probe lets parakeet chunk the audio (the hard 6 GB rule).
        settings = self.settings.get()
        probe = self._ffprobe_duration or _self_ffprobe()

        def job_body(job_ctx: Any) -> dict[str, Any]:
            transcript = _transcribe.transcribe_with_engine(
                audio_path,
                loader=loader,
                settings=settings,
                language=language,
                duration_probe=probe,
                on_progress=lambda pct, msg: job_ctx.progress(pct, msg),
                should_cancel=lambda: job_ctx.cancelled,
            )
            transcript = self._maybe_align_words(transcript, audio_path, settings)
            if not job_ctx.cancelled:
                # Persist the transcript onto the project + flip the library flag.
                project = self._load_or_create_project(video_id)
                project.data["transcript"] = transcript
                project.save()
                try:
                    self.library.set_has_transcript(video_id, True)
                except Exception:  # noqa: BLE001 - flag bookkeeping is non-fatal
                    log.warning("set_has_transcript failed for %s", video_id)
            return {"transcript": transcript}

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    def _diarize_backend_factory(self, settings: dict[str, Any]) -> Any:
        """Phase-8: build the diarizer backend selected by settings['diarizeBackend'].

        Delegates to ``pyannote_backend.select_backend_factory`` closed over the
        SpeechBrain default factory: an unknown value keeps the safe speechbrain
        default; ``"pyannote"`` validates the env HF token eagerly (typed refusal,
        no deep 401) before any heavy import.
        """
        from .features import diarize as _diarize  # local: import-light
        from .features import pyannote_backend as _pyannote  # local: import-light

        return _pyannote.select_backend_factory(
            settings,
            speechbrain_factory=_diarize._default_backend_factory,
        )

    def _diarize_models_present(self, settings: dict[str, Any]) -> bool:
        """Phase-8: probe the installed-state of whichever diarize backend is selected.

        Pyannote checks its two gated repos; speechbrain checks the VAD + ECAPA
        assets. Drives the offline gate so a missing-model download is refused for
        the right backend.
        """
        from .features import diarize as _diarize  # local: import-light
        from .features import pyannote_backend as _pyannote  # local: import-light

        if _pyannote.selected_backend_name(settings) == _pyannote.PYANNOTE_BACKEND:
            return _pyannote.default_models_present(settings)
        return _diarize.default_models_present(settings)

    def _maybe_align_words(
        self,
        transcript: dict[str, Any],
        audio_path: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """WU6 wiring: refine word timings via ctc-forced-aligner when karaoke is on.

        Runs the ctc-forced-aligner 2nd pass on the freshly produced transcript
        when ``settings['karaoke']`` is truthy, giving karaoke-grade per-word
        boundaries the caption builder consumes. ``ctc_align.align_words`` is
        degrade-safe (returns the input unchanged when the model is unavailable
        offline or any backend step fails), so this never crashes the transcribe
        job. No-op (input returned unchanged) when karaoke is off.
        """
        if not settings.get("karaoke"):
            return transcript
        from .features import ctc_align as _ctc_align  # local: import-light seam

        return _ctc_align.align_words(transcript, audio_path, settings=settings)

    # ===================================================================== #
    # system.* + phase8.* (Phase-8 moment-finding tier controls)
    # ===================================================================== #
    def system_probe(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
        }

    def system_advisor(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``system.advisor({commercial?})`` -> AdvisorReport JSON. Direct-return.

        The "Models & System" panel brain: probes hardware + dependency
        availability, checks which model weights are already installed (the asset
        manager), and returns each component's quality-vs-cost verdict + the rolled
        -up runnable tiers + the recommended preset. Honors Offline mode (a missing
        weight that would need a download counts as unavailable). Pure decision
        logic; nothing heavy is imported.
        """
        from .features import system_advisor as _sa  # local: import-light

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

    def asr_engines(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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

    def _detect_local_servers(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        """Detect locally-running Ollama / LM Studio servers (fail-open).

        Uses the injected ``local_detector`` seam when present (tests inject a fake
        returning canned PoolEntry dicts); otherwise runs the real
        :func:`local_detect.detect_local_servers` over the stdlib urllib GET
        transport. Detection is best-effort: it returns ``[]`` (never raises) when
        no local server answers.
        """
        if self._local_detector is not None:
            return list(self._local_detector(settings))
        from .models import local_detect as _local_detect  # local: import-light
        from .models import provider as _provider_mod  # local: heavy seam

        return cast(
            "list[dict[str, Any]]",
            list(_local_detect.detect_local_servers(settings, transport=_provider_mod.urllib_get_json)),
        )

    def system_recommend(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
        from .features import recommender as _recommender  # local: import-light pure
        from .features import system_advisor as _sa  # local: import-light

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

    def phase8_signals(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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

    def phase8_select(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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
            from .features import select as _select  # local: import-light

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
        # LOCAL). A legacy injected provider (tests) still wins.
        select_provider = self._provider if self._provider is not None else self._provider_for_function("select")
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

    def _models_present_map(self, settings: dict[str, Any]) -> dict[str, bool]:
        """Map each model-backed advisor component -> is its weight installed.

        Probes the asset manager for each Phase-8 component's pinned asset so the
        advisor (and the ASR picker) can report installed-state + degrade an
        offline-missing model. Components with no registered asset are omitted
        (the advisor then treats them as not-installed). Fail-open: a probe error
        for one component marks it absent, never crashes the report.
        """
        from .assets import manifest as _manifest  # local: import-light
        from .assets.manager import AssetManager  # local: import-light

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

    def _default_hardware_probe(self) -> Any:  # pragma: no cover - lazy heavy seam (pynvml/torch); tests inject a fake
        """Build the real :class:`HardwareProbe` (lazy import; runtime only)."""
        from .features import system_advisor as _sa  # noqa: PLC0415 - lazy

        return _sa.HardwareProbe()

    def _default_phase8_runner(self) -> Callable[..., dict[str, Any]]:
        """Resolve the real Wave-1 signal-compute runner (lazy; runtime only).

        Returns the module-level :func:`_run_phase8_signals` which loads + runs the
        heavy Wave-1 signal modules. Kept behind a method so tests can inject a fake
        ``phase8_runner`` instead and never touch torch / transformers / cv2.
        """
        return _run_phase8_signals

    # ===================================================================== #
    # shortmaker.* (both jobs — via ShortMaker with selection caching)
    # ===================================================================== #
    def _shortmaker(self) -> _shortmaker.ShortMaker:
        """Build a ShortMaker bound to our context loader + selection cache."""
        return _shortmaker.ShortMaker(
            load_context=self._shortmaker_context,
            out_dir_for=lambda vid: str(self.exports_dir / f"shorts-{vid}"),
            stages=_shortmaker.Stages(),
            settings_provider=self.settings.get,
        )

    def _detect_boundaries(self, video_id: str) -> dict[str, Any]:
        """Run the silence + scene-cut detectors for a video's path.

        CONTRACT-NOTE: ``_lazy_snap`` reads ``settings["silences"]`` /
        ``settings["sceneCuts"]`` which nothing fills. We detect them here (ffmpeg
        silencedetect + PySceneDetect, both behind the boundary seams) and inject
        them into the settings dict the select job uses, so boundary-snap has real
        silence + scene targets — not just sentence ends. Detection failures fall
        back to empty lists (snap then uses sentence ends only).
        """
        path = self._resolve_video_path(video_id)
        if not path:
            return {"silences": [], "sceneCuts": []}
        silences = _boundary.detect_silences(path, settings=self.settings.get(), run=self._silence_run)
        scene_cuts = _boundary.detect_scene_cuts(path, detector=self._scene_detector)
        return {"silences": list(silences), "sceneCuts": list(scene_cuts)}

    def _shortmaker_context(self, video_id: str) -> dict[str, Any]:
        """Load a video's path + transcript + the cached candidate map.

        CONTRACT-NOTE (HIGH-3): exposes the cached select result under
        ``"candidates"`` (id -> Candidate), which ``ShortMaker._resolve_candidates``
        consults when the UI sends only ``candidateIds``.

        CONTRACT-NOTE (A2 audioTrackId): also exposes the manifest's A3
        ``Project.audioTracks`` under ``"audioTracks"`` so the export pipeline
        can resolve ``shortmaker.export``'s optional ``audioTrackId`` and mux
        the chosen track onto each exported clip.
        """
        path = self._resolve_video_path(video_id) or ""
        transcript = None
        audio_tracks: list[dict[str, Any]] = []
        manifest = self._project_path(video_id)
        if manifest.exists():
            try:
                data = _library.Project.open(manifest).data
                transcript = data.get("transcript")
                audio_tracks = list(data.get("audioTracks") or [])
            except Exception:  # noqa: BLE001 - a bad manifest just means no transcript
                transcript = None
                audio_tracks = []
        # P4 §3: the source video title for the persisted ShortInfo metadata.
        video = self.library.get(video_id)
        source_title = str((video or {}).get("title") or "")
        return {
            "path": path,
            "transcript": transcript,
            "sourceTitle": source_title,
            "candidates": self._selection_cache.get(video_id, {}),
            "audioTracks": audio_tracks,
        }

    def shortmaker_select(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shortmaker.select({videoId, prompt, controls})`` -> ``{jobId}`` (§2).

        Wraps the feature pipeline so (a) boundary detectors feed the snap stage
        and (b) the produced candidates are cached server-side (keyed by
        "rank@sourceStart") for a later ``shortmaker.export``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        video_id = _require_str(params, "videoId")
        sm = self._shortmaker()

        def handler(job_ctx: Any) -> dict[str, Any]:
            settings = dict(self.settings.get())
            # Feed the real silence + scene-cut detectors into the snap settings.
            settings.update(self._detect_boundaries(video_id))
            result = _shortmaker.run_select(
                job_ctx,
                video_id=video_id,
                prompt=str(params.get("prompt") or ""),
                controls=params.get("controls") or {},
                load_context=self._shortmaker_context,
                stages=sm.stages,
                settings=settings,
            )
            self._cache_candidates(video_id, result.get("candidates") or [])
            return result

        job = ctx.jobs.start(handler)
        return {"jobId": job.id}

    def shortmaker_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``shortmaker.export({videoId, candidateIds})`` -> ``{jobId}`` (§2).

        Resolution uses the cached select result (HIGH-3): the UI's
        ``candidateIds`` ("rank@sourceStart") index into the per-video cache, so
        export carves the real clips. The UI may also forward full ``candidates``.
        A2's optional ``audioTrackId`` (plus T4b's ``captionStyle`` /
        ``reframeEngine``) flows through ``params`` into ``ShortMaker.export``;
        the AudioTrack itself is resolved against ``_shortmaker_context``'s
        ``audioTracks``.
        """
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        sm = self._shortmaker()
        return sm.export(params, ctx)

    # ===================================================================== #
    # nle.* — EDL / CSV timeline export (captions-export)
    # ===================================================================== #
    def _approved_clips(self, video_id: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve the approved clips to export for ``video_id``.

        Prefers an explicit ``clips`` array on ``params`` (so the UI can export the
        just-produced batch before manifest persistence); otherwise reads the
        project manifest's persisted ``clips`` (the ``{candidate, path}`` records
        the short-maker export carved). Returns ``[]`` when neither has clips.
        """
        explicit = params.get("clips")
        if isinstance(explicit, list) and explicit:
            return [c for c in explicit if isinstance(c, dict)]
        project = self._load_or_create_project(video_id)
        return [c for c in (project.data.get("clips") or []) if isinstance(c, dict)]

    def nle_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``nle.export({videoId, format?, fps?, title?, clips?})`` -> ``{path}`` (captions-export).

        Export the approved clips of a video as an editable NLE timeline: a
        CMX3600 ``.edl`` (default) or a ``.csv`` for Premiere / DaVinci Resolve.
        ``fps`` is one of 24/25/30/60 (default 30); ``title`` names the sequence.
        Per-clip reel names come from each candidate's optional ``reel``. Direct-
        return ``{path}`` (the build is fast, pure-Python — no job needed).
        """
        video_id = _require_str(params, "videoId")
        fmt = str(params.get("format") or "edl")
        fps = params.get("fps", 30)
        title = params.get("title")
        if not isinstance(title, str) or not title:
            video = self.library.get(video_id)
            title = str((video or {}).get("title") or "Media Studio Timeline")
        clips = self._approved_clips(video_id, params)
        try:
            out_path = self.exports_dir / f"{video_id}-timeline.{_nle_export.normalize_format(fmt)}"
            path = _nle_export.export(clips, out_path, fmt=fmt, fps=fps, title=title)
        except ValueError as exc:
            raise _invalid(str(exc)) from exc
        return {"path": path, "clipCount": len(clips)}

    # ===================================================================== #
    # package.* — ZIP "package for upload" (captions-export)
    # ===================================================================== #
    def package_export(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``package.export({path, suggestion?})`` -> ``{path, manifest}`` (captions-export).

        Bundle ONE produced short (its rendered ``<clip>.mp4`` + thumbnail + a
        suggested title/description/tags ``upload.json``) into a ``.zip`` for
        manual posting. ``path`` is the exported clip; the clip's sidecar
        ``<clip>.json`` metadata drives the suggested copy (an optional
        ``suggestion`` override wins per-field). The clip MUST live inside the
        exports root (path-traversal guard). Direct-return.
        """
        clip_path = _require_str(params, "path")
        resolved = Path(clip_path).resolve()
        root = self.exports_dir.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise _invalid(f"path is outside the exports root: {clip_path}") from None
        if not resolved.exists():
            raise _invalid(f"short not found: {clip_path}")
        meta = _shorts_meta.read_metadata(resolved) or {}
        thumb = _shorts_meta.thumbnail_path(resolved)
        suggestion = params.get("suggestion")
        suggestion = suggestion if isinstance(suggestion, dict) else None
        out_zip = resolved.with_name(resolved.stem + ".package.zip")
        try:
            result = _package_export.package(
                resolved,
                out_zip,
                meta=meta,
                thumbnail_path=thumb if thumb.exists() else None,
                suggestion=suggestion,
            )
        except FileNotFoundError as exc:
            raise _invalid(str(exc)) from exc
        return result

    def _cache_candidates(self, video_id: str, candidates: list[Candidate]) -> None:
        """Cache select candidates keyed by "rank@sourceStart" (the UI's id form)."""
        by_id: dict[str, Candidate] = {}
        for cand in candidates:
            cid = self.candidate_id(cand)
            by_id[cid] = cand
        self._selection_cache[video_id] = by_id

    @staticmethod
    def candidate_id(candidate: Candidate) -> str:
        """Stable candidate id matching ShortMaker.tsx's ``candidateId`` ("rank@sourceStart").

        CONTRACT-NOTE: the renderer builds ``${rank}@${sourceStart}``; we mirror it
        exactly. ``sourceStart`` is rendered the way JS ``String(number)`` would
        (an integer-valued float prints without a trailing ".0").
        """
        rank = candidate.get("rank")
        src = candidate.get("sourceStart", candidate.get("start", 0.0))
        return f"{rank}@{_js_number(src)}"

    # ===================================================================== #
    # provider seam
    # ===================================================================== #
    def _get_provider(self) -> Any:
        """Return the LLM provider for translation (cached test seam or real).

        FACTORY PATH (PLAN §WU-keys): builds from RAW keys via ``get_raw()`` — the
        provider must carry the live key; only RPC reads return redacted.
        """
        if self._provider is not None:
            return self._provider
        from .models import provider as _provider_mod  # local import: heavy seam

        return _provider_mod.get_provider(self.settings.get_raw())

    def _ai_cache(self) -> Any:
        """The shared AI-call content cache (WU-cache), under the data dir.

        Honors ``settings.aiCacheDir`` (absolute path) when set, else
        ``data_dir/ai-cache``. The cache is local-only; nothing leaves the box.
        """
        from .models.ai_cache import DEFAULT_CACHE_DIRNAME, AiCache  # local: import-light

        configured = self.settings.get().get("aiCacheDir")
        store_dir = Path(configured) if configured else self.data_dir / DEFAULT_CACHE_DIRNAME
        return AiCache(store_dir=store_dir)

    def _ai_pool(self) -> Any:
        """Build the rotation pool (WU-pool) from settings for budget/route reads.

        Returns an object whose ``.entries`` (each carrying ``.provider`` /
        ``.local``) satisfy :func:`budget.estimate`'s pool shape. The real path
        builds a :class:`RotatingProvider` with detection OFF (planning only reads
        the catalog-shaped entries; skipping the live ``GET /models`` probe keeps
        ai.planJob / the plan step socket-free — PLAN: ZERO provider calls). When
        the provider module is a test stub WITHOUT ``build_pool_provider`` we fall
        back to a local-only pool (the budget then reports local-only, no egress).
        """
        from .models import provider as _provider_mod  # local: heavy seam

        builder = getattr(_provider_mod, "build_pool_provider", None)
        if builder is None:
            return _LocalOnlyPool()
        # FACTORY PATH (PLAN §WU-keys): the pool is built from RAW keys.
        return builder(self.settings.get_raw(), detect_local=False)

    def plan_ai_job_envelope(self, inputs: Any) -> Any:
        """Assemble an :class:`ai_job.AiJob` envelope for ``inputs`` (PURE, no calls).

        Shared by ``ai.planJob`` (pre-flight) and the AI-bearing job handlers so
        cost/route/cacheKey are derived from ONE place. Performs ZERO provider
        calls — the pool is built only to read its catalog-shaped ``.entries``.
        """
        from .models import ai_job as _ai_job  # local: import-light

        return _ai_job.plan_ai_job(
            inputs,
            pool=self._ai_pool(),
            catalog=_ai_job.CatalogFreeCapAdapter(),
            cache=self._ai_cache(),
        )

    def _run_ai_job(
        self,
        ctx: RpcContext,
        *,
        messages: list[dict[str, str]],
        model: str,
        provider: Any,
        work: Any,
        feature: str,
        label: str,
        videoId: str | None = None,  # noqa: N803 - wire-name kwarg (matches JobRegistry)
        ack: str | None = None,
    ) -> Any:
        """Plan + run an :class:`ai_job.AiJob` on ``ctx.jobs`` with a custom ``work``.

        ``provider`` is the resolved provider the work consumes; when ``None`` the
        pool-aware ``get_provider`` is built lazily (so rotation + degrade tracking
        apply). The envelope's cost/route/cacheKey come from
        :meth:`plan_ai_job_envelope`. Returns the created job (the ``{jobId}``
        source). The work's own result dict is the ``job.done`` payload.

        WU-budget pre-flight gate: when ``settings['confirmCloudBudget']`` is on
        AND the planned run WOULD egress, ``ack`` MUST equal the envelope's
        ``cacheKey`` (the token ``ai.planJob`` returns), else the run is refused
        with a typed error telling the client to pre-flight + acknowledge first.
        A local-only / cache-hit run never egresses, so it is never gated.
        """
        from .models import ai_job as _ai_job  # local: import-light

        inputs = _ai_job.AiInputs(
            messages=tuple({str(k): str(v) for k, v in m.items()} for m in messages),
            model=model,
        )
        envelope = self.plan_ai_job_envelope(inputs)
        self._enforce_cloud_budget_ack(envelope, ack)

        def _factory() -> Any:
            if provider is not None:
                return provider
            from .models import provider as _provider_mod  # local: heavy seam

            # FACTORY PATH (PLAN §WU-keys): the run provider carries RAW keys.
            return _provider_mod.get_provider(self.settings.get_raw())

        return _ai_job.run_ai_job(
            envelope,
            jobs=ctx.jobs,
            provider_factory=_factory,
            cache=self._ai_cache(),
            work=work,
            feature=feature,
            label=label,
            videoId=videoId,
        )

    def _enforce_cloud_budget_ack(self, envelope: Any, ack: str | None) -> None:
        """Refuse a non-acknowledged cloud run when ``confirmCloudBudget`` is on.

        The gate fires ONLY when both hold: the setting ``confirmCloudBudget`` is
        truthy AND the planned envelope ``route.willEgress`` is True (a run that
        sends bytes off the machine). In that case ``ack`` must equal the
        envelope's ``cacheKey`` — the token ``ai.planJob`` returns — proving the
        client previewed THIS exact request's cost/egress budget. A local-only or
        cache-hit run never egresses, so it bypasses the gate entirely.
        """
        if not envelope.route.willEgress:
            return
        if not self.settings.get().get("confirmCloudBudget"):
            return
        if ack == envelope.cacheKey:
            return
        raise _invalid(
            "cloud run requires budget acknowledgement: call ai.planJob and pass "
            "its cacheKey as confirmBudget (or disable confirmCloudBudget)"
        )

    def ai_plan_job(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``ai.planJob({messages?, model?, params?, request?, capability?})`` -> pre-flight.

        Returns ``{route, costEst, cacheHit, willEgress, budget, preview, cacheKey}``
        WITHOUT executing any AI call (PLAN acceptance: ZERO provider calls). The
        request shape is the budget request (``target_size`` / ``text_bytes`` /
        ``frame_bytes``); ``messages`` feed the cache key so the pre-flight knows
        whether a real run would be a cache hit.
        """
        from .models import ai_job as _ai_job  # local: import-light

        raw_messages = params.get("messages")
        messages = (
            tuple({str(k): str(v) for k, v in m.items()} for m in raw_messages if isinstance(m, dict))
            if isinstance(raw_messages, list)
            else ()
        )
        request = self._budget_request(params.get("request"))
        inputs = _ai_job.AiInputs(
            messages=messages,
            model=str(params.get("model") or ""),
            params=dict(params.get("params") or {}),
            request=request,
            capability=str(params.get("capability") or "text"),
        )
        return self.plan_ai_job_envelope(inputs).planned()

    def _budget_request(self, raw: Any) -> Any:
        """Coerce a wire ``request`` dict into a budget request (or ``None``).

        The returned :class:`_BudgetRequest` satisfies the duck-typed
        ``budget.BudgetRequest`` protocol (``target_size`` / ``text_bytes`` /
        ``frame_bytes``). A non-dict ``raw`` yields ``None`` (an unsized request).

        WU-budget (P1 #6): when the wire request pins NO ``targetSize`` we resolve
        the size to the user's ``defaultTargetJobSize`` setting, so the pre-flight
        budget reflects the configured default job size (one source -> N shorts)
        rather than only the module constant. A request that DOES pin a size keeps
        it verbatim. A non-positive / non-int setting falls back to the budget
        module's ``DEFAULT_TARGET_JOB_SIZE`` (the same fallback ``estimate`` uses).
        """
        if not isinstance(raw, dict):
            return None
        size = raw.get("targetSize")
        return _BudgetRequest(
            target_size=int(size) if isinstance(size, int) else self._default_target_job_size(),
            text_bytes=int(raw.get("textBytes") or 0),
            frame_bytes=int(raw.get("frameBytes") or 0),
        )

    def _default_target_job_size(self) -> int:
        """The configured default job size, or the budget module's constant.

        Reads ``settings['defaultTargetJobSize']`` (PLAN P1 #6); a missing /
        non-int / non-positive value falls back to
        :data:`budget.DEFAULT_TARGET_JOB_SIZE` so the estimate stays falsifiable.
        """
        from .models import budget as _budget_mod  # local: import-light pure

        configured = self.settings.get().get("defaultTargetJobSize")
        if isinstance(configured, int) and configured > 0:
            return configured
        return _budget_mod.DEFAULT_TARGET_JOB_SIZE

    def _get_model_runner(self) -> Any:
        """The shared ModelRunner (lazily built from settings; T3)."""
        if self._model_runner is None:
            from .models import runner as _runner_mod  # local import: heavy seam

            self._model_runner = _runner_mod.ModelRunner(self.settings.get())
        return self._model_runner

    def _get_translator(self) -> Any | None:
        """TieredTranslator for subtitles.translate (T3).

        Returns ``None`` when a legacy ``provider`` seam was injected (tests):
        the caller then keeps the original single-provider path, so every
        existing handler test stays green.
        """
        if self._provider is not None:
            return None
        from .models import translation as _translation_mod  # local import

        # FACTORY PATH (PLAN §WU-keys): the tier3 hosted provider is built from RAW keys.
        return _translation_mod.get_translator(self.settings.get_raw(), runner=self._get_model_runner())

    def _dub_translator(self) -> Any:
        """Adapt T3's TieredTranslator to dub's text-based Translator seam.

        CONTRACT-NOTE (WIRING-T2 §2): ``tts.dub.Translator`` is
        ``translate(texts, target_lang, source_lang) -> texts`` + ``free()``;
        T3's TieredTranslator is cue-based and exposes no ``free``. This
        adapter wraps texts into cue dicts (timings unused by MT) and frees the
        MT model by stopping the shared llama server — the batched 'free MT'
        stage between translate-ALL and synth-ALL (A4).
        """
        from .models import translation as _translation_mod  # local: heavy seam

        runner = self._get_model_runner()
        # FACTORY PATH (PLAN §WU-keys): the dub translator's tier3 carries RAW keys.
        tiered = _translation_mod.get_translator(self.settings.get_raw(), runner=runner)

        class _DubTranslator:
            def translate(
                self,
                texts: list[str],
                target_lang: str,
                source_lang: str | None = None,
            ) -> list[str]:
                cues = [{"index": i + 1, "start": 0.0, "end": 0.0, "text": str(t)} for i, t in enumerate(texts)]
                out = tiered.translate(cues, target_lang, source_lang=source_lang)
                return [str(c.get("text", "")) for c in out]

            def free(self) -> None:
                try:
                    runner.stop_server()
                except Exception:  # noqa: BLE001 - freeing is best-effort
                    log.warning("MT free: stop_server failed")

        return _DubTranslator()


# --------------------------------------------------------------------------- #
# small helpers (kept module-level so the seams stay import-light)
# --------------------------------------------------------------------------- #
def _self_ffmpeg_run() -> Callable[..., int]:
    """The default ffmpeg ``run`` (imported lazily to keep this module light)."""
    from . import ffmpeg as _ffmpeg

    return _ffmpeg.run


def _self_ffprobe() -> Callable[..., float]:
    """The default ffprobe duration probe (lazy import)."""
    from . import ffmpeg as _ffmpeg

    return _ffmpeg.ffprobe_duration


def _evenly_spaced(start: float, end: float, n: int) -> list[float]:
    """The ``n`` evenly-spaced sample times across ``[start, end)`` (WU-C3).

    Mirrors the frame-loader's even sampling so the picked frame's index maps back
    to its source-relative time. ``n <= 0`` yields ``[]``; a single frame samples
    the span start (the loader's first sample). A zero-length span collapses all
    samples onto ``start`` (a still clip), never raising.
    """
    if n <= 0:
        return []
    span = float(end) - float(start)
    step = span / float(n)
    return [float(start) + step * k for k in range(n)]


def _js_number(value: Any) -> str:
    """Render a number the way JavaScript ``String(n)`` would (for candidate ids).

    JS prints ``5`` for ``5.0`` and ``5.5`` for ``5.5``. Python's ``str(5.0)`` is
    ``"5.0"``, so an integer-valued float must drop the ``.0`` to match the UI's
    ``${c.sourceStart}`` template, otherwise the cached id never matches.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return str(int(num))
    return repr(num)


# --------------------------------------------------------------------------- #
# Phase-8 wiring helpers (pure; the heavy runner stays pragma-excluded)
# --------------------------------------------------------------------------- #
#: advisor component name -> its registered manifest asset name (the installed
#: -state probe key). Components with no own asset (motion/diversity/ranker are
#: zero-download floors) are absent; ``aesthetic`` shares the SigLIP-2 backbone.
_COMPONENT_ASSETS: dict[str, str] = {
    "saliency": "vinet-s-saliency",
    "audio_saliency": "panns-cnn14",
    "scene_transnet": "transnetv2-pytorch",
    "vlm_backbone": "siglip2-so400m",
    "aesthetic": "siglip2-so400m",
    "quality_gate": "dover-mobile-quality",
    "emotion": "hsemotion-onnx",
    "ocr": "rapidocr-onnx",
    "parakeet": "parakeet-tdt-0.6b-v3",
    "ctc_aligner": "ctc-forced-aligner-mms",
    "pyannote": "pyannote-speaker-diarization-31",
    "smolvlm2": "smolvlm2-2.2b",
}

#: settings key picking the Phase-8 moment-finding tier (0/1/2).
PHASE8_TIER_KEY = "phase8Tier"


def _coerce_tier(value: Any, settings: dict[str, Any]) -> int:
    """Resolve the Phase-8 tier: explicit ``value`` wins, else settings, else 1.

    Clamped to 0..2 (the three runnable presets). Any non-integer / out-of-range
    input falls back to the Tier-1 default so a typo never breaks a select.
    """
    raw = value if value is not None else settings.get(PHASE8_TIER_KEY, 1)
    try:
        tier = int(raw)
    except (TypeError, ValueError):
        return 1
    return min(2, max(0, tier))


def _signals_summary(tracks: dict[str, Any]) -> dict[str, Any]:
    """Summarize computed signal tracks -> ``{tracks:{ch:count}, present:{ch:bool}}``.

    A JSON-safe digest of the per-channel :class:`SignalTrack` map (the heavy
    runner's output): per-channel signal count + present flag. Keeps the wire
    payload small (the raw signals stay server-side for the select path).
    """
    counts: dict[str, int] = {}
    present: dict[str, bool] = {}
    for channel, track in tracks.items():
        counts[channel] = len(getattr(track, "signals", ()) or ())
        present[channel] = bool(getattr(track, "present", False))
    return {"tracks": counts, "present": present}


def _advisor_report_to_wire(report: Any) -> dict[str, Any]:
    """Convert an :class:`AdvisorReport` frozen tree to the camelCase wire dict.

    Mirrors the renderer's ``AdvisorReport`` TS type (components/tiers/
    recommendedPreset/vramBudgetMb/notes), so the panel maps it 1:1 without a
    snake_case shim.
    """
    return {
        "components": [
            {
                "name": c.name,
                "present": c.present,
                "verdict": c.verdict,
                "vramMb": c.vram_mb,
                "licenseCommercialOk": c.license_commercial_ok,
                "reason": c.reason,
            }
            for c in report.components
        ],
        "tiers": [
            {"tier": t.tier, "label": t.label, "verdict": t.verdict, "components": list(t.components)}
            for t in report.tiers
        ],
        "recommendedPreset": report.recommended_preset,
        "vramBudgetMb": report.vram_budget_mb,
        "notes": list(report.notes),
    }


def _run_phase8_signals(  # pragma: no cover - heavy Wave-1 signal compute (torch/cv2/transformers); tests inject a fake runner
    media_path: str,
    *,
    tier: int,
    settings: dict[str, Any],
    duration_probe: Callable[[str], float],
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run the enabled Wave-1 signal modules for ``media_path`` at ``tier``.

    The real (heavy) signal-compute path: motion always (Tier-0 floor), plus the
    Tier-1 visual/audio model tracks. Each module degrades to ``present=False``
    when its weights are missing offline (the §-signal rule), so this returns a
    partial map on any machine. Excluded from coverage — it imports the heavy ML
    backends; the pure shaping (:func:`_signals_summary`) and the select wiring are
    covered with an injected fake runner.
    """
    from .features import (  # noqa: PLC0415 - lazy heavy seam
        audio_saliency as _audio_saliency,
    )
    from .features import (
        motion as _motion,
    )

    duration = duration_probe(media_path)
    tracks: dict[str, Any] = {}
    # motion / saliency / scene_transnet each return a SINGLE SignalTrack (keyed by
    # its ``.channel``); audio_saliency / vlm_backbone return a dict[channel,track].
    motion_track = _motion.compute_motion_signals(media_path, duration, settings=settings)
    tracks[motion_track.channel] = motion_track
    if tier >= 1:
        from .features import saliency as _saliency  # noqa: PLC0415
        from .features import scene_transnet as _scene_transnet  # noqa: PLC0415
        from .features import vlm_backbone as _vlm_backbone  # noqa: PLC0415

        tracks.update(_audio_saliency.compute_audio_signals(media_path, duration, settings=settings))
        sal = _saliency.compute_saliency_signals(media_path, duration, settings=settings)
        tracks[sal.channel] = sal
        scene = _scene_transnet.compute_scene_signals(media_path, duration, settings=settings)
        tracks[scene.channel] = scene
        tracks.update(_vlm_backbone.compute_backbone_signals(media_path, duration, settings=settings))
    if on_progress is not None:
        on_progress(100.0, "signals done")
    _ = should_cancel
    return tracks


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def register_all(
    services: Services | None = None,
    *,
    register: Callable[[str, Any], None] | None = None,
) -> Services:
    """Register every §2 method handler on ``protocol.METHODS``; return the Services.

    Idempotent only across a fresh registry: ``protocol.register`` raises on a
    duplicate name (a typo/double-wire fails loudly at startup). ``services`` and
    ``register`` are injectable for tests (a tmp-dir Services + a fake registrar).
    """
    svc = services or Services()
    reg = register if register is not None else protocol.register

    reg("library.list", svc.library_list)
    reg("library.add", svc.library_add)
    reg("library.remove", svc.library_remove)

    reg("project.open", svc.project_open)
    reg("project.save", svc.project_save)
    reg("project.consolidate", svc.project_consolidate)

    reg("settings.get", svc.settings_get)
    reg("settings.set", svc.settings_set)

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

    # WU-envelope: AI-Job pre-flight. ai.planJob returns the route + cost/egress
    # budget + cacheHit/willEgress with ZERO provider calls (the pure planner).
    reg("ai.planJob", svc.ai_plan_job)

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
    reg("providers.setConsent", svc.providers_set_consent)
    # WU-usage-ui: per-key live usage (cached, persisted, stale-flagged; no poll
    # burst). The rotation pool already accounts usage from optimistic decrement +
    # parsed 429/X-RateLimit-* headers — this RPC just surfaces it, redacted.
    reg("providers.usage", svc.providers_usage)
    # WU-presets (PH3): smart presets + per-function override + first-run chooser.
    # applyPreset resolves a preset over the curated catalog into routing.perFunction;
    # setFunctionModel overrides one slot; firstRun is the local-vs-cloud chooser
    # (local-safe default pre-choice, flips routing + firstRunChoiceMade on choice).
    reg("providers.applyPreset", svc.providers_apply_preset)
    reg("providers.setFunctionModel", svc.providers_set_function_model)
    reg("providers.firstRun", svc.providers_first_run)

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
    from .features import tracks_audio as _tracks_audio  # local: import-light
    from .features import tts as _tts

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
    from .features import feedback as _feedback  # local: import-light

    _feedback.register(register_fn=reg)

    # shorts.* (P4 §2/C6): the shorts library registers its own four methods,
    # bound to the same exports root + per-video out-dir layout the short-maker
    # export uses (Services.exports_dir / "shorts-<videoId>").
    from .features import shorts as _shorts  # local: import-light

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
    from .features import cues as _cues  # local: import-light

    _cues.register(load_context=svc._shortmaker_context, register_fn=reg)

    # audio-stabilize group (NET-NEW): the three transport-agnostic engine
    # features each own their own register() (mirrors shorts/tracks_audio):
    #   stabilize.run        camera-shake stabilization (ffmpeg vidstab 2-pass)
    #   audiomix.merge       A/V merge + sidechain DUCK + EBU R128 loudnorm
    #   audiomix.normalize   EBU R128 loudnorm only (no bed)
    #   silence.trim         dead-air removal (ffmpeg silencedetect -> re-cut)
    # All resolve media via the library + write derivatives under the exports
    # root, reusing the same injectable ffmpeg seams the sibling features use.
    from .features import audiomix as _audiomix  # local: import-light
    from .features import silencetrim as _silencetrim  # local: import-light
    from .features import stabilize as _stabilize  # local: import-light

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
    from .features import diarize as _diarize  # local: import-light
    from .features import health as _health  # local: import-light
    from .features import recipes as _recipes  # local: import-light

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

    # assets.* (A2): registered via the assets package's own register() so the
    # manager binds to the services' data dir + settings (U4).
    from .assets import rpc as _assets_rpc  # local import keeps handlers import-light

    _assets_rpc.register(
        root=svc.data_dir,
        settings_provider=svc.settings.get,
        register_fn=reg,
    )

    # Imports for side effect — U4 manifest entries only, NO new RPC methods:
    # T3 (TranslateGemma GGUF tiers), T4a (Chrome Headless Shell + exposes
    # RemotionCaptionEngine/STYLES), T5 (llama-server tool builds + the
    # resolve_tool() chains).
    from . import tools_resolver  # noqa: F401

    # Phase-8 model modules — imported for their asset-registration side effects
    # (each registers its on-demand AssetEntry at import, mirroring diarize /
    # tools_resolver). No new RPC methods: parakeet plugs into transcribe via the
    # ASR-engine seam, ctc_align into the transcribe karaoke tail, caption_polish
    # into subtitles.generate, pyannote into diarize's backend selector (above).
    from .features import (
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
    from .models import translation as _translation_assets  # noqa: F401

    # job.list / job.retry (U5) are protocol.py built-ins — no wiring needed.

    log.info("registered %d feature methods", len(protocol.METHODS))
    return svc
