# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Vision re-rank / best-frame thumbnail + semantic-index handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

import hashlib
import json as _json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..features import offline as _offline
from ..features import shorts as _shorts_meta
from ..protocol import ErrorCode, RpcContext, RpcError
from ._shared import (
    _invalid,
    _LocalOnlyPool,
    _require_number,
    _require_str,
)
from ._wire import (
    _evenly_spaced,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only import, never executed at runtime
    from ._services import Services


def _resolve_vlm_reranker(self: Services, settings: dict[str, Any], *, media_path: str) -> Any:
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
    from ..features import smolvlm2 as _sv  # local: import-light (no heavy import)
    from ..models import routing_policy as _routing_policy  # local: import-light pure

    # WU-D2b-2 THREAD-SAFETY: ``settings`` is the RAW settings the CALLER captured
    # SYNCHRONOUSLY while the per-request key overlay was still open (the
    # ``_key_overlay_wrapper`` overlay is closed by the time this reranker resolves
    # on the job WORKER thread). Re-reading ``get_raw()`` here would run off-thread
    # after the overlay closed and return only the redacted at-rest MARKERS, so the
    # cloud egress would carry a corrupt ``Bearer …-key``. Use the caller's snapshot.
    raw_settings = settings
    # OFFLINE / ROUTING-LOCAL GATE: offline forbids ALL cloud frame egress, even for
    # a fully frame-consented + routed provider (offline is authoritative over
    # consent). A RoutingPolicy Local mode (GATE-2, resolved fail-closed) is EQUALLY
    # authoritative — ``mode == 'local'`` skips the cloud branch so a user who flipped
    # the global/override toggle to Local can never egress frames despite a stale
    # ``routing.perFunction['vision']`` cloud entry (mirrors ``_provider_for_function``).
    # Either degrades the resolver to local weights / None — the same fall-through a
    # no-consent run takes (mirrors assets/diarize).
    vision_provider = (
        None
        if (_offline.is_offline(settings) or _routing_policy.resolve_route("vision", settings)["mode"] == "local")
        else self._vision_provider_for_consent(raw_settings)
    )
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


def _resolve_frame_scorer(self: Services, settings: dict[str, Any]) -> Any:
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

    from ..features import best_frame as _bf  # local: import-light (no cv2/model)
    from ..features import smolvlm2 as _sv  # local: import-light
    from ..models import routing_policy as _routing_policy  # local: import-light pure

    # WU-D2b-2 THREAD-SAFETY: ``settings`` is the RAW settings the CALLER captured
    # SYNCHRONOUSLY while the per-request key overlay was still open. This scorer
    # resolves on the job WORKER thread, AFTER ``_key_overlay_wrapper`` closed the
    # overlay — re-reading ``get_raw()`` here would return only the redacted at-rest
    # MARKERS, so the vision egress would carry a corrupt ``Bearer …-key`` (a
    # UnicodeEncodeError on the wire). Use the caller's synchronous snapshot.
    raw_settings = settings
    # OFFLINE / ROUTING-LOCAL GATE: offline forbids ALL cloud frame egress, even for
    # a fully frame-consented + routed provider — and a RoutingPolicy Local mode
    # (GATE-2, resolved fail-closed) is EQUALLY authoritative, so ``mode == 'local'``
    # also skips the cloud branch (a user who flipped the toggle to Local can never
    # egress frames despite a stale ``routing.perFunction['vision']`` cloud entry).
    # Either degrades to local weights / None (degrade-to-midpoint), exactly the
    # no-consent fall-through. Mirrors :meth:`_resolve_vlm_reranker`.
    vision_provider = (
        None
        if (_offline.is_offline(settings) or _routing_policy.resolve_route("vision", settings)["mode"] == "local")
        else self._vision_provider_for_consent(raw_settings)
    )
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


def _frame_clip_loader(self: Services) -> Any:
    """The clip-frame sampler for the thumbnail picker (injected fake or native).

    Tests inject ``vlm_clip_frame_loader`` (the SAME seam the re-ranker uses) so
    no cv2 is touched; the default is the heavy native loader (coverage-excluded
    prod seam), mirroring :meth:`_default_phase8_runner`.
    """
    if self._vlm_clip_frame_loader is not None:
        return self._vlm_clip_frame_loader
    from ..features import smolvlm2 as _sv  # pragma: no cover - native default seam

    return _sv._default_clip_frame_loader  # pragma: no cover - native default seam


def _frame_clip_time_loader(self: Services) -> Any:
    """The TIME-AWARE clip sampler for the thumbnail picker (injected fake or native).

    Bug-sweep (frame-time drift): the plain clip loader returns only frame stacks, so
    the handler had to RECONSTRUCT sample times from the surviving stack length. When
    the native cv2 loader silently drops a failed read the survivors keep their
    ORIGINAL grid times, but that reconstruction re-grids at a coarser step — shifting
    every reported ``frameTimeSec``. This seam instead returns aligned
    ``(frames, times)`` per span so a dropped read never moves a survivor's time.

    Tests inject ``vlm_clip_time_loader``; the default is the heavy native loader
    (:func:`smolvlm2._default_clip_frames_with_times`, coverage-excluded prod seam),
    mirroring :meth:`_frame_clip_loader`. Only consulted for the thumbnail path when
    NO legacy ``vlm_clip_frame_loader`` was injected (existing framed-loader tests keep
    the regrid path unchanged; a fake time-loader / the native default drives prod).
    """
    if self._vlm_clip_time_loader is not None:
        return self._vlm_clip_time_loader
    from ..features import smolvlm2 as _sv  # pragma: no cover - native default seam

    return _sv._default_clip_frames_with_times  # pragma: no cover - native default seam


def _frame_thumbnail_writer(self: Services) -> Any:
    """The thumbnail writer for the picker (injected fake or the cv2 imwrite seam).

    Tests inject ``thumbnail_writer`` to record the ``(frame, path)`` call; the
    default is :func:`best_frame._default_thumbnail_writer` (the lone cv2
    ``imwrite`` line, coverage-excluded in WU-C2).
    """
    if self._thumbnail_writer is not None:
        return self._thumbnail_writer
    from ..features import best_frame as _bf  # pragma: no cover - native default seam

    return _bf._default_thumbnail_writer  # pragma: no cover - native default seam


def _resolve_thumbnail_span(self: Services, params: dict[str, Any], video_id: str) -> tuple[str, float, float]:
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
        start = _require_number(params, "start", 0.0)
        end = _require_number(params, "end", 0.0)
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


def thumbnail_select(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``thumbnail.select({videoId, candidateId?|path?, start?, end?})`` -> ``{jobId}`` (WU-C3).

    Pick the single best thumbnail frame for one produced clip with the AI
    best-frame picker, riding the shared :meth:`_run_ai_job` envelope for the
    universal cancel / degrade / budget framing. The work body:

    * Resolves the clip span (explicit ``{path,start,end}`` or a cached
      ``candidateId``) and the conventional ``<clip>.thumb.jpg`` write target.
    * Consults the AI content cache keyed by clip span + frame params + the
      resolved route (degraded vs scored), so a second identical call is a cache
      hit that NEVER re-scores (AC d) — yet a run that DEGRADED (no consent / no
      weights) is not served forever once consent is granted or the weights are
      installed (the route tag flips, the key changes, and the picker runs).
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
    # FACTORY PATH (WU-D2b-2): the frame scorer needs the RAW apiKey on the wire,
    # and it resolves on the job WORKER thread — AFTER the per-request key overlay
    # closes. Capture the RAW settings NOW (synchronously, while the overlay is
    # still open) so the off-thread :meth:`_resolve_frame_scorer` sees live keys,
    # exactly as ``index.build`` captures ``get_raw()`` up front (handlers.py).
    settings = dict(self.settings.get_raw())
    prompt = str(params.get("prompt") or "")

    def work(job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
        from ..features import best_frame as _bf  # local: import-light (no cv2/model)

        thumb_path = str(_shorts_meta.thumbnail_path(media_path))
        cache = self._ai_cache()
        # Resolve the scorer BEFORE the cache key so the DEGRADE decision is part of
        # the cache identity (bug-sweep): a route-blind key let a degraded midpoint
        # result (no consent / no weights) be served FOREVER — the AiCache has no TTL
        # or invalidation — even after the user grants frame consent or installs the
        # VLM weights. Folding a "degraded"/"scored" route tag into the key means the
        # cache MISSES once the resolver flips to a real scorer, so the picker runs
        # (a repeat identical call within the SAME route still hits, AC d preserved).
        scorer = self._resolve_frame_scorer(settings)
        route = "degraded" if scorer is None else "scored"
        cache_key = cache.key(
            [{"role": "user", "content": prompt}],
            "thumbnail.select",
            {"path": media_path, "start": start, "end": end, "route": route},
        )
        cached = cache.get(cache_key)
        if cached is not None:
            job_ctx.progress(100.0, "cache hit")
            return dict(cached)

        if scorer is None:
            # Degrade-to-midpoint: deterministic, zero egress, scorer untouched. NO
            # thumbnailPath is advertised here — the writer never runs on this branch,
            # so a path would point at a file that was never written; ``degraded`` is
            # the signal consumers key on.
            midpoint = (start + end) / 2.0
            _shorts_meta.write_thumbnail_metadata(media_path, midpoint)
            result = {"frameTimeSec": midpoint, "score": 0.0, "degraded": True}
            cache.put(cache_key, result)
            return result

        # Sample the clip's frames WITH their aligned sample times so a dropped native
        # read never shifts the reported frameTimeSec (bug-sweep): the plain loader
        # returns only stacks, forcing a coarser regrid when a read fails. A legacy
        # framed loader injected by a test keeps the original regrid path (its fakes
        # never drop, so _evenly_spaced is exact); otherwise the time-aware seam
        # carries the true survivor times through (native prod default or a fake).
        if self._vlm_clip_frame_loader is not None:
            frames = list(self._frame_clip_loader()(media_path, [(start, end)]))
            stack = list(frames[0]) if frames else []
            frame_times = _evenly_spaced(start, end, len(stack))
        else:
            pairs = list(self._frame_clip_time_loader()(media_path, [(start, end)]))
            stack, frame_times = (list(pairs[0][0]), list(pairs[0][1])) if pairs else ([], [])
        # Cancel checkpoint AFTER sampling but BEFORE scoring/writing, so a job
        # cancelled mid-load scores nothing and writes no thumbnail (AC f).
        if job_ctx.cancelled:
            return {"cancelled": True}
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


def _index_path(self: Services, video_id: str) -> Path:
    """The per-video vector sidecar path (``projects/<videoId>.index.json``).

    PLAN §WU-A5 decision: vectors persist to a sidecar file NEXT TO the
    manifest, NOT the manifest body, so a large embedding matrix never bloats
    the project JSON. Deleting this file reverts the index (idempotent rebuild).
    """
    return self.projects_dir / f"{video_id}.index.json"


def _read_index(self: Services, video_id: str) -> dict[str, Any] | None:
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


def _write_index(self: Services, video_id: str, payload: dict[str, Any]) -> None:
    """Persist the index ``payload`` to the per-video sidecar (idempotent).

    ``projects_dir`` is ensured so a first build never fails on a missing dir;
    a rebuild overwrites the file wholesale (PLAN §WU-A5 (f)).
    """
    self.projects_dir.mkdir(parents=True, exist_ok=True)
    self._index_path(video_id).write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _resolve_index_embedder(self: Services, settings: dict[str, Any]) -> Any:
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

    from ..models import embedder as _embedder  # local: import-light

    # OFFLINE GATE: offline forbids ALL cloud text egress, even for a fully
    # TEXT-consented + routed provider — use the deterministic local backstop
    # (zero egress) instead of resolving a CloudEmbedder. Offline is
    # authoritative over consent/routing (mirrors assets/diarize).
    if _offline.is_offline(settings):
        return _embedder.LocalEmbedder()

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


def _ai_pool_for_index(self: Services, settings: dict[str, Any]) -> Any:
    """Build the routed ``index`` rotation pool from ``settings`` (or ``None``).

    Honors ``routing.perFunction["index"]`` so the routed embeddings provider
    is tried first. Detection of local servers is OFF (no socket): the pool is
    read only for its catalog-shaped cloud entries (base URL / model / key) the
    embedder bridge consumes. ``None`` when the provider module is a test stub
    without ``build_pool_provider``.
    """
    from ..models import provider as _provider_mod  # local: heavy seam

    builder = getattr(_provider_mod, "build_pool_provider", None)
    if builder is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
        return None
    return builder(settings, detect_local=False, prefer=self._function_prefer("index"))


def _transcript_fp(corpus: Any) -> str:
    """A stable fingerprint of the ordered transcript corpus an index was built
    from (bug-sweep fix). If the current transcript's fingerprint differs from the
    one stored at index.build, the persisted vectors no longer line up with the
    live segments — search would zip new segments onto old vectors and return
    silently-wrong text/timestamps. index.search uses this to refuse a stale index.
    """
    return hashlib.sha256(repr(corpus).encode("utf-8")).hexdigest()


def index_build(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``index.build({videoId, confirmBudget?})`` -> ``{jobId}`` (WU-A5).

    A long job (custom ``work`` body on a shared AiJob envelope): embed every
    transcript segment through the consent + budget-gated ``index`` route and
    persist the vectors to the per-video sidecar. The done payload is
    ``{segmentCount, model, builtAt, dim}``.

    The embedding egress rides the AiJob envelope so it inherits the cancel
    check, degrade tracking, and the SAME ``confirmCloudBudget`` ack the rest of
    the bundle enforces; the embedder is resolved through the per-entry
    TEXT-consent filter (:meth:`_resolve_index_embedder`) so a cloud route never
    reaches a non-consented provider. The budget envelope is planned over the
    TEXT-consented settings (:meth:`_plan_index_envelope`, the SAME path
    ``index.search`` uses) so ``willEgress`` reflects post-consent reality — a
    consent-denied build routes LOCAL and so is NEVER refused for a missing ack
    (DESIGN §1.5 "default privacy preset -> local -> zero egress regardless").
    A transcript with zero segments builds an empty index (``segmentCount=0``).
    """
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    video_id = _require_str(params, "videoId")
    project = self._load_or_create_project(video_id)
    transcript = project.data.get("transcript")
    if not transcript:
        raise _invalid(f"video {video_id} has no transcript yet (run transcribe.start first)")
    # FACTORY PATH: the embedder resolution below reaches CloudEmbedder, which
    # needs the RAW apiKey on the wire — mirror the vision/director factories
    # (get_raw() at _provider_for_function/_resolve_frame_scorer). get_raw()
    # only un-redacts apiKey; consent/routing/budget semantics are identical to
    # get() (settings_store.get just last-4-redacts providers[].apiKeys).
    settings = dict(self.settings.get_raw())

    def work(job_ctx: Any, _envelope: Any, _provider: Any) -> dict[str, Any]:
        from ..features import semantic_index as _si  # local: import-light (pure)

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
            # Bug-sweep: fingerprint the corpus so index.search can detect a
            # re-transcribe and refuse a stale index instead of mis-pairing.
            "transcriptFp": _transcript_fp(corpus),
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

    # Plan + gate the budget envelope over the TEXT-consented settings (so a
    # consent-denied local build is never refused), then run the custom work body
    # on the shared job bus. The envelope's egress is sized text-shaped (the
    # shared budget reads the messages only — every caller's contract).
    from ..models import ai_job as _ai_job  # local: import-light

    inputs = _ai_job.AiInputs(
        messages=({"role": "user", "content": "index.build"},),
        model=str(settings.get("cloudEmbedModel") or settings.get("cloudModel") or ""),
    )
    envelope = self._plan_index_envelope(inputs)
    # WU-spend-cap: the index embedding egress is gated (ack + monthly hard cap)
    # and metered exactly like _run_ai_job — it is a cloud egress path too.
    self._enforce_egress_gates(
        envelope,
        params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
    )

    # The work body drives the EMBEDDER (not this chat provider), so the
    # provider here only satisfies run_ai_job's degrade-aware factory contract;
    # it is the injected provider in tests and the lazily-built real one in prod.
    job = _ai_job.run_ai_job(
        envelope,
        jobs=ctx.jobs,
        provider_factory=self._index_provider_factory,
        cache=self._ai_cache(),
        work=work,
        feature="index",
        label="index.build",
        videoId=video_id,
        on_egress=self._record_egress_cost,
    )
    return {"jobId": job.id}


def _index_provider_factory(self: Services) -> Any:
    """The degrade-aware chat provider for the ``index.build`` job's envelope.

    The embedding work body uses the EMBEDDER seam, not this provider, so this
    only satisfies ``run_ai_job``'s factory contract — the injected provider in
    tests, else the lazily-built real one (FACTORY PATH: RAW keys).
    """
    if self._provider is not None:
        return self._provider
    from ..models import provider as _provider_mod  # pragma: no cover - real-provider factory (tests inject)

    return _provider_mod.get_provider(self.settings.get_raw())  # pragma: no cover - real-provider factory


def index_status(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
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


def index_search(self: Services, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """``index.search({videoId, query, topK?, confirmBudget?})`` -> ``{hits:[...]}``.

    Direct-return: ONE short query-embedding call then a pure cosine over the
    already-persisted segment vectors. The inline query embedding is itself a
    cloud egress when routed to cloud, so it is NOT a silent provider call — it
    passes the SAME text-consent + budget path as :meth:`index_build`:

    * the embedder is resolved through :meth:`_resolve_index_embedder` (the
      per-entry TEXT-consent filter), so the query text never reaches a
      non-consented provider (PLAN §WU-A5 (c2));
    * the query vector is cache-keyed via :meth:`_ai_cache` on the query + the
      RESOLVED embedder identity (model + base URL), so a repeated identical query
      never re-embeds (PLAN §WU-A5 (e)) AND a local-route vector can never be served
      for a cloud route (or vice-versa) — which would otherwise poison the cache and
      permanently defeat the dimension guard;
    * the cache is consulted BEFORE the budget gate, so a repeat identical query
      served from cache (zero egress) is NEVER charged a fresh ack / hard-cap check;
    * on a cache MISS the budget envelope is planned over the text-consented settings
      and gated by :meth:`_enforce_egress_gates` BEFORE any embedding, so an unacked
      cloud search egresses nothing (PLAN §WU-A5 (c3)); ``willEgress`` reflects
      post-consent reality (a consent-denied -> local search never demands an ack).

    Searching an unbuilt video raises a typed "build the index first"
    INVALID_PARAMS (mirrors :meth:`subtitles_generate`), never an empty list.
    """
    from ..features import semantic_index as _si  # local: import-light (pure)
    from ..models import ai_job as _ai_job  # local: import-light

    video_id = _require_str(params, "videoId")
    query = _require_str(params, "query")
    top_k = int(_require_number(params, "topK", 8))
    index = self._read_index(video_id)
    if index is None:
        raise _invalid(f"video {video_id} has no semantic index yet (run index.build first)")

    # FACTORY PATH: the query-embedder resolution below reaches CloudEmbedder,
    # which needs the RAW apiKey on the wire — get_raw() mirrors the vision/
    # director factories and only un-redacts apiKey (consent/routing identical).
    settings = dict(self.settings.get_raw())
    inputs = _ai_job.AiInputs(
        messages=({"role": "user", "content": query},),
        model=str(settings.get("cloudEmbedModel") or settings.get("cloudModel") or ""),
    )

    # Resolve the embedder FIRST (socket-free: _resolve_index_embedder /
    # _ai_pool_for_index use detect_local=False), then fold its RESOLVED identity
    # (model + base URL) into the query-vector cache key. ``inputs.model`` is only the
    # settings string cloudEmbedModel/cloudModel — it does NOT change when the route
    # flips to LocalEmbedder (offline / consent-revoked / no cloud key), so keying on
    # it alone let a local (384-dim) vector be served for a later cloud route and
    # PERMANENTLY defeat the dimension guard (rebuild could never fix the wedge). The
    # LocalEmbedder carries no model/base_url attrs, so it keys under "local"/"" —
    # cleanly separated from every cloud (model+base_url) slot.
    cache = self._ai_cache()
    embedder = self._resolve_index_embedder(settings)
    cache_key = cache.key(
        [{"role": "user", "content": query}],
        "index.search",
        {
            "model": inputs.model,
            "embedder": str(getattr(embedder, "model", "local")),
            "baseUrl": str(getattr(embedder, "base_url", "")),
        },
    )
    cached = cache.get(cache_key)
    if cached is not None:
        # A cache HIT egresses nothing (the query vector is already computed), so it
        # must NOT be gated: consulting the budget/monthly-cap BEFORE the cache lookup
        # wrongly demanded a fresh confirmBudget ack (and could be refused by the hard
        # cap) for a repeat identical query that never touches a provider.
        query_vec = list(cached)
    else:
        # Cache MISS -> a genuine (possibly cloud) egress. Plan the budget envelope
        # over the TEXT-consented settings so willEgress reflects post-consent reality,
        # enforce the ack + monthly cap BEFORE any embed (zero egress on an unacked
        # run), then embed, cache the vector, and record the cost iff it egressed.
        envelope = self._plan_index_envelope(inputs)
        self._enforce_egress_gates(
            envelope,
            params.get("confirmBudget") if isinstance(params.get("confirmBudget"), str) else None,
        )
        query_vec = embedder.embed([query])[0]
        cache.put(cache_key, query_vec)
        if envelope.route.willEgress:
            self._record_egress_cost(envelope)

    # Guard the cross-route mismatch (PLAN §WU-A5 (d) error contract; WU-A4's
    # search defers the dimension check to its caller — this is that caller). The
    # index was built on whatever route was active THEN; if the route has since
    # changed (e.g. privacy-default LocalEmbedder -> a cloud embedder of a
    # different dim), the query vector won't line up with the persisted vectors.
    # Surface a typed "rebuild" error rather than letting diarize.cosine_similarity
    # raise a raw ValueError out of the handler.
    built_dim = index.get("dim") or 0
    if isinstance(built_dim, int) and built_dim > 0 and len(query_vec) != built_dim:
        raise _invalid(
            f"semantic index for {video_id} was built with a different embedding "
            "model (dimension mismatch); run index.build to rebuild it first"
        )

    vectors = index.get("vectors") or []
    project_transcript = self._load_or_create_project(video_id).data.get("transcript")
    # Bug-sweep: refuse a STALE index. If the transcript was re-transcribed since
    # the index was built, the persisted vectors no longer line up with the live
    # segments (search would zip new segments onto old vectors -> silently-wrong
    # text/timestamps). An index built before this fix carries no fingerprint, so
    # it is skipped (backward-compat) rather than force-flagged.
    built_fp = index.get("transcriptFp")
    if built_fp is not None and built_fp != _transcript_fp(_si.build_corpus(project_transcript or {})):
        raise _invalid(
            f"semantic index for {video_id} is stale (the transcript changed since it was "
            "built); run index.build to rebuild it first"
        )
    segments = project_transcript.get("segments") or [] if isinstance(project_transcript, dict) else []
    hits = _si.search(query_vec, vectors, segments, top_k)
    return {"hits": hits}


def _plan_index_envelope(self: Services, inputs: Any) -> Any:
    """Plan the budget envelope for an ``index.search`` query over consented settings.

    Builds the planning pool from :meth:`_text_consented_settings` so the
    envelope's ``willEgress`` reflects what would leave the box AFTER the
    per-entry text-consent filter — a consent-denied search routes local and so
    never spuriously demands a budget ack (PLAN §WU-A5 (c3)).

    OFFLINE GATE (bug-sweep): offline forbids ALL cloud egress and is AUTHORITATIVE
    over consent/routing — the embedder resolver already swaps to LocalEmbedder when
    offline (:meth:`_resolve_index_embedder`), so the envelope must plan LOCAL too, or
    an offline run with a text-consented cloud provider configured would set
    ``willEgress=True`` and spuriously demand a budget ack, be refused by the monthly
    hard cap, and record PHANTOM egress cents for a run that actually embeds locally.
    Planning over a local-only pool mirrors how consent-denial STRIPS the pool.
    """
    from ..models import ai_job as _ai_job  # local: import-light

    settings = dict(self.settings.get())
    if _offline.is_offline(settings):
        pool: Any = _LocalOnlyPool()
    else:
        pool = self._ai_pool_for_index(self._text_consented_settings(settings))
        if pool is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
            pool = _LocalOnlyPool()
    return _ai_job.plan_ai_job(
        inputs,
        pool=pool,
        catalog=_ai_job.CatalogFreeCapAdapter(),
        cache=self._ai_cache(),
    )
