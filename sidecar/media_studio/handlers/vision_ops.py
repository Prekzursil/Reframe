# The only inter-module cycle is the TYPE_CHECKING-only Services ref below
# (no runtime cycle); silence the type-only back-edge warning.
# pyright: reportImportCycles=false
"""Composition-root handlers (F4b split): Vision re-rank / best-frame thumbnail + semantic-index handlers.

Each function is a Services method body extracted verbatim from the former
monolithic handlers.py; `self` is typed against the composed `Services` (bound
in services.py). Behaviour + the RPC surface are byte-identical to pre-split.
"""

from __future__ import annotations

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

    raw_settings = self.settings.get_raw()
    # OFFLINE GATE: offline forbids ALL cloud frame egress, even for a fully
    # frame-consented + routed provider (offline is authoritative over consent).
    # Skip the cloud branch so the resolver degrades to local weights / None —
    # the same fall-through a no-consent run takes (mirrors assets/diarize).
    vision_provider = None if _offline.is_offline(settings) else self._vision_provider_for_consent(raw_settings)
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

    raw_settings = self.settings.get_raw()
    # OFFLINE GATE: offline forbids ALL cloud frame egress, even for a fully
    # frame-consented + routed provider — skip the cloud branch so the resolver
    # degrades to local weights / None (degrade-to-midpoint), exactly the
    # no-consent fall-through. Mirrors :meth:`_resolve_vlm_reranker`.
    vision_provider = None if _offline.is_offline(settings) else self._vision_provider_for_consent(raw_settings)
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
        from ..features import best_frame as _bf  # local: import-light (no cv2/model)

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
    # Plan the budget envelope over the TEXT-consented settings so willEgress
    # reflects what would actually leave the box after the consent filter, then
    # enforce the ack BEFORE any embedding call (zero egress on an unacked run).
    inputs = _ai_job.AiInputs(
        messages=({"role": "user", "content": query},),
        model=str(settings.get("cloudEmbedModel") or settings.get("cloudModel") or ""),
    )
    envelope = self._plan_index_envelope(inputs)
    # WU-spend-cap: gate the query-embedding egress (ack + monthly hard cap).
    self._enforce_egress_gates(
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
        # WU-spend-cap record-at-completion: the synchronous query embed just
        # ran; record its cost iff it egressed (a cloud route). A cache hit
        # (above) re-embeds nothing and so is never recorded. _record_egress_cost
        # is a zero-record for a local-only envelope, but gating here keeps the
        # local-route path from touching the ledger at all.
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
    segments = project_transcript.get("segments") or [] if isinstance(project_transcript, dict) else []
    hits = _si.search(query_vec, vectors, segments, top_k)
    return {"hits": hits}


def _plan_index_envelope(self: Services, inputs: Any) -> Any:
    """Plan the budget envelope for an ``index.search`` query over consented settings.

    Builds the planning pool from :meth:`_text_consented_settings` so the
    envelope's ``willEgress`` reflects what would leave the box AFTER the
    per-entry text-consent filter — a consent-denied search routes local and so
    never spuriously demands a budget ack (PLAN §WU-A5 (c3)).
    """
    from ..models import ai_job as _ai_job  # local: import-light

    pool: Any = self._ai_pool_for_index(self._text_consented_settings(dict(self.settings.get())))
    if pool is None:  # pragma: no cover - only when provider is a stub w/o the pool builder
        pool = _LocalOnlyPool()
    return _ai_job.plan_ai_job(
        inputs,
        pool=pool,
        catalog=_ai_job.CatalogFreeCapAdapter(),
        cache=self._ai_cache(),
    )
