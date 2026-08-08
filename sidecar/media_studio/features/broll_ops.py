"""The ``broll.*`` RPC surface: index -> status -> suggest -> apply.

Ties the three pure b-roll modules to the wire. It owns orchestration only —
sequencing, params, jobs, and error shape — while every heavy edge is an
injected seam:

===================== =====================================================
seam                  what it hides
===================== =====================================================
``embed_images``      the SigLIP-2 image tower (``BackboneBackend``)
``embed_texts``       the SigLIP-2 text tower (the SAME joint space)
``load_index`` /      the on-disk vector sidecar
``save_index``
``load_transcript``   the project's transcript
``resolver``          videoId -> media path
``duration``          ffprobe
``run``               the drained ``ffmpeg.run``
===================== =====================================================

so the whole surface is exercised with plain lists and no model, exactly as
``vlm_backbone``'s pure scorers are.

Wire surface (NET-NEW)::

    broll.status({})                              -> {indexed, assetCount, libraryCount,
                                                      model, dim, stale, staleCount, willEgress}
    broll.index({force?})                         -> {jobId} -> {assetCount, embedded, model, willEgress}
    broll.suggest({videoId, threshold?, ...})     -> {jobId} -> {insertions, reason, willEgress}
    broll.apply({videoId, insertions})            -> {jobId} -> {path, inserted}

**``willEgress`` is False by construction, and that is the point.** Auto-b-roll
is asset RETRIEVAL over the user's OWN library using LOCAL embeddings: no frame
and no transcript text ever leaves the machine, so ``consent.require_frame_consent``
/ ``require_text_consent`` are simply not reachable from here and no method may
join the key-injection allowlist (which is driven by the ``ai.`` / ``director.``
/ ``shortmaker.`` / ``index.`` prefixes — ``broll.`` is none of them). If a future
variant ever routes a frame or a segment to a CLOUD VLM, THAT path must re-trigger
the consent gates; keeping distillation local is what keeps this gate-free.

**``apply`` is review-first.** It composites exactly the insertion list handed to
it and never re-plans, so what the user accepted in the inspector is what gets
rendered.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .. import protocol
from ..jobs import JobContext
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import broll_compose, broll_index, broll_plan

log = get_logger("media_studio.broll")

#: The methods this module owns (asserted against the registration in tests).
METHODS = ("broll.status", "broll.index", "broll.suggest", "broll.apply")

#: The default matcher — already vendored and registered (Apache-2.0).
DEFAULT_MODEL_ID = "google/siglip2-so400m-patch16-384"

#: The honest empty state. "No confident match" is a RESULT, not an error, and
#: not an excuse to insert something anyway.
NO_CONFIDENT_MATCH = "no confident match"
MATCHED = "matched"

Resolver = Callable[[str], str | None]
AssetLister = Callable[[], Sequence[Mapping[str, Any]]]
IndexLoader = Callable[[], Any]
IndexSaver = Callable[[Any], None]
TranscriptLoader = Callable[[str], Mapping[str, Any]]
Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]
ProbeFn = Callable[..., float]
RunFn = Callable[..., int]
Clock = Callable[[], str]


#: Settings key naming the folder the user keeps their b-roll in.
BROLL_DIR_KEY = "brollDir"
#: The index sidecar's filename under the data dir.
INDEX_FILENAME = "broll.index.json"

#: What counts as b-roll. Matched case-INSENSITIVELY: cameras write ``.MP4``
#: and ``.JPG``, and a library that silently skipped those would report an
#: empty folder the user can see files in.
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"})
VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"})


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def scan_assets(root: str | os.PathLike) -> list[dict[str, Any]]:
    """Every b-roll file under ``root``, as planner/index-shaped asset dicts.

    Walks recursively in sorted order so the index — and therefore every plan
    built from it — is reproducible run to run. Each row carries the ``path``,
    ``sizeBytes`` and ``mtime`` that :func:`broll_index.fingerprint` hashes, plus
    a stable ``assetId`` derived from the path (so re-scanning the same folder
    keeps the same ids and an accepted suggestion still resolves).

    A missing or unconfigured folder yields ``[]``: that is the normal first-run
    state, not an error.
    """
    if not root:
        return []
    base = Path(root)
    if not base.is_dir():
        return []
    assets: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        suffix = path.suffix.lower()
        kind = "image" if suffix in IMAGE_EXTS else "video" if suffix in VIDEO_EXTS else None
        if kind is None or not path.is_file():
            continue
        stat = path.stat()
        assets.append(
            {
                "assetId": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16],
                "path": str(path),
                "kind": kind,
                "sizeBytes": stat.st_size,
                "mtime": stat.st_mtime,
                "durationSec": None,
            }
        )
    return assets


def load_index_file(path: str | os.PathLike) -> Any:
    """Read the index sidecar, or ``None`` when it is absent or unreadable.

    A half-written or hand-edited sidecar degrades to "not indexed" — a state
    the UI can act on with a re-index button — rather than taking the sidecar
    process down at startup.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def save_index_file(path: str | os.PathLike, index: Any) -> None:
    """Write the index sidecar, creating its parent directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index), encoding="utf-8")


def _require_str(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise _invalid(f"{key} (str) is required")
    return value


def _opt_float(params: Mapping[str, Any], key: str, default: float) -> float:
    value = params.get(key, default)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415 - keep module import-light

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _no_backbone(_paths: Sequence[str]) -> Sequence[Sequence[float]]:  # pragma: no cover - unwired-default guard
    """Default embedder: the real SigLIP-2 tower is wired by the composition root."""
    raise RpcError(
        "no local image/text backbone is wired; install the SigLIP-2 assets first",
        ErrorCode.INTERNAL_ERROR,
    )


# --------------------------------------------------------------------------- #
# the backbone adapters — the ONE heavy edge, split so the logic is testable
# --------------------------------------------------------------------------- #
def _default_backbone_factory(settings: dict[str, Any]) -> Any:  # pragma: no cover - heavy seam
    """The real SigLIP-2 backbone (reuses the shipped ``vlm_backbone`` factory)."""
    from . import vlm_backbone as _vlm  # noqa: PLC0415 - heavy seam

    return _vlm._default_backbone_factory(settings)


def _default_asset_frame(path: str, kind: str) -> Any:  # pragma: no cover - runtime native (cv2)
    """One representative BGR frame for ``path`` (mid-frame for a video).

    Mirrors ``vlm_backbone._default_frame_loader``'s cv2 usage; excluded from
    coverage for the same reason (cv2 is a GPU-host dependency, not a gate one),
    with the logic that CONSUMES it covered via an injected loader.
    """
    import cv2  # noqa: PLC0415 - job-time native

    if kind != "video":
        return cv2.imread(path)
    cap = cv2.VideoCapture(path)
    try:
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if frames > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frames // 2))
        _ok, frame = cap.read()
        return frame
    finally:
        cap.release()


def _rows(matrix: Any) -> list[list[float]]:
    """A backbone's ``(N, D)`` output as plain JSON-safe float lists."""
    return [[float(v) for v in row] for row in matrix]


def make_image_embedder(
    *,
    backend_factory: Callable[[dict[str, Any]], Any] | None = None,
    frame_loader: Callable[[str, str], Any] | None = None,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
) -> Embedder:
    """An ``embed_images`` seam over the SigLIP-2 image tower.

    Loads ONE representative frame per asset (a still is itself; a video is its
    mid-frame — see ``flagship-auto-broll.md`` §11.3, which flags mean-pooling
    several frames as the more robust but unmeasured alternative), stacks them
    into a single batch so the tower is entered once, and returns plain float
    lists the index can persist as JSON.

    Both heavy defaults are injectable, which is what lets this batching and
    conversion logic be covered with a fake tower instead of a real checkpoint.
    UNVERIFIED: no test on this branch runs the REAL SigLIP-2 tower or cv2 —
    the settling experiment is design WU BR8's real-model tier (embed a dog
    frame and a cityscape decoy, assert the dog out-scores the decoy).
    """
    factory = backend_factory or _default_backbone_factory
    loader = frame_loader or _default_asset_frame
    provider = settings_provider or dict

    def embed(paths: Sequence[str]) -> Sequence[Sequence[float]]:
        if not paths:
            return []
        import numpy as np  # noqa: PLC0415 - keep module import-light

        backend = factory(provider())
        frames = [loader(str(path), "video" if Path(path).suffix.lower() in VIDEO_EXTS else "image") for path in paths]
        return _rows(backend.embed_images(np.stack(frames)))

    return embed


def make_text_embedder(
    *,
    backend_factory: Callable[[dict[str, Any]], Any] | None = None,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
) -> Embedder:
    """An ``embed_texts`` seam over the SigLIP-2 TEXT tower.

    Must be the same family as :func:`make_image_embedder`'s tower — a
    cross-modal cosine is only meaningful inside one joint space, which is the
    invariant ``broll_index.require_model`` enforces at query time.
    """
    factory = backend_factory or _default_backbone_factory
    provider = settings_provider or dict

    def embed(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        return _rows(factory(provider()).embed_texts(list(texts)))

    return embed


class BrollComposeError(RuntimeError):
    """The composite ffmpeg pass failed (non-zero exit)."""


class BrollOps:
    """Owns the four ``broll.*`` methods over injected seams."""

    def __init__(
        self,
        *,
        resolver: Resolver,
        list_assets: AssetLister,
        load_index: IndexLoader,
        save_index: IndexSaver,
        load_transcript: TranscriptLoader,
        out_dir: str | os.PathLike,
        embed_images: Embedder | None = None,
        embed_texts: Embedder | None = None,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        duration: ProbeFn | None = None,
        run: RunFn | None = None,
        model_id: str = DEFAULT_MODEL_ID,
        clock: Clock | None = None,
    ) -> None:
        self._resolver = resolver
        self._list_assets = list_assets
        self._load_index = load_index
        self._save_index = save_index
        self._load_transcript = load_transcript
        self._out_dir = Path(out_dir)
        self._embed_images = embed_images or _no_backbone
        self._embed_texts = embed_texts or _no_backbone
        self._settings_provider = settings_provider or dict
        self._duration = duration
        self._run = run
        self._model_id = model_id
        self._clock = clock or _utc_now

    # -- helpers ------------------------------------------------------------ #
    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - settings must never break an op
            return {}

    def _resolve(self, params: Mapping[str, Any]) -> str:
        video_id = _require_str(params, "videoId")
        resolved = self._resolver(video_id)
        if not resolved:
            raise _invalid(f"unknown video: {video_id}")
        return str(resolved)

    @staticmethod
    def _jobs(ctx: RpcContext):
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        return ctx.jobs

    # -- broll.status ------------------------------------------------------- #
    def status(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``broll.status({})`` -> the index freshness snapshot. Direct, pure read.

        No provider call and no model load, exactly like ``index.status``.
        """
        snapshot = broll_index.status(self._load_index(), list(self._list_assets()), model=self._model_id)
        return {**snapshot, "willEgress": False}

    # -- broll.index -------------------------------------------------------- #
    def index(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``broll.index({force?})`` -> ``{jobId}`` -> ``{assetCount, embedded, model}``.

        Embeds ONLY the assets whose fingerprint moved (or everything on
        ``force``/a backbone change), then persists the merged index.
        """
        jobs = self._jobs(ctx)
        force = bool(params.get("force", False))

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            assets = list(self._list_assets())
            plan = broll_index.refresh_plan(self._load_index(), assets, model=self._model_id, force=force)
            job_ctx.progress(10, f"embedding {len(plan['embed'])} of {len(assets)} assets")
            vectors = list(self._embed_images([str(a.get("path", "")) for _i, a in plan["embed"]]))
            if len(vectors) != len(plan["embed"]):
                raise RpcError(
                    f"the image backbone returned {len(vectors)} vectors for {len(plan['embed'])} assets",
                    ErrorCode.INTERNAL_ERROR,
                )
            embedded = {position: vectors[n] for n, (position, _a) in enumerate(plan["embed"])}
            merged = broll_index.merge(plan, assets, embedded, model=self._model_id, built_at=self._clock())
            self._save_index(merged)
            job_ctx.progress(100, f"indexed {len(assets)} b-roll assets")
            return {
                "assetCount": len(assets),
                "embedded": len(embedded),
                "model": self._model_id,
                "willEgress": False,
            }

        return {"jobId": jobs.start(job_body).id}

    # -- broll.suggest ------------------------------------------------------ #
    def suggest(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``broll.suggest({videoId, threshold?, maxCoveragePct?, layout?})``.

        -> ``{jobId}`` -> ``{insertions, reason, willEgress}``. One text-embed
        pass over the transcript, then the PURE planner. Refuses a library that
        is unindexed or indexed by a different backbone, rather than scoring
        across joint spaces.
        """
        jobs = self._jobs(ctx)
        media_path = self._resolve(params)
        video_id = _require_str(params, "videoId")
        threshold = _opt_float(params, "threshold", broll_plan.DEFAULT_MIN_SIMILARITY)
        coverage = _opt_float(params, "maxCoveragePct", broll_plan.DEFAULT_MAX_COVERAGE_PCT)
        layout = str(params.get("layout") or broll_plan.DEFAULT_LAYOUT)
        settings = self._settings()

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            index = self._load_index()
            broll_index.require_model(index, self._model_id)
            assets, asset_vecs = broll_index.rows(index)
            transcript = dict(self._load_transcript(video_id) or {})
            segments = list(transcript.get("segments") or [])
            if not segments:
                raise _invalid(f"{video_id} has no transcript yet; run transcribe.start first")
            job_ctx.progress(20, f"matching {len(segments)} segments against {len(assets)} assets")
            segment_vecs = list(self._embed_texts([str(s.get("text", "")) for s in segments]))
            total = self._duration(media_path, settings) if self._duration else float(segments[-1].get("end", 0.0))
            insertions = broll_plan.plan(
                segments,
                segment_vecs,
                assets,
                asset_vecs,
                total_sec=float(total),
                threshold=threshold,
                layout=layout,
                max_coverage_pct=coverage,
            )
            job_ctx.progress(100, f"{len(insertions)} b-roll insertion(s)")
            return {
                "insertions": insertions,
                "reason": MATCHED if insertions else NO_CONFIDENT_MATCH,
                "willEgress": False,
            }

        return {"jobId": jobs.start(job_body).id}

    # -- broll.apply -------------------------------------------------------- #
    def apply(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``broll.apply({videoId, insertions})`` -> ``{jobId}`` -> ``{path, inserted}``.

        Composites the REVIEWED plan verbatim — no re-ranking, no second model
        pass — into a NEW file, leaving the source untouched.
        """
        jobs = self._jobs(ctx)
        media_path = self._resolve(params)
        insertions = params.get("insertions") or []
        if not isinstance(insertions, list) or not insertions:
            raise _invalid("insertions (a non-empty list) is required")
        settings = self._settings()
        run = self._run
        out_dir = self._out_dir

        def job_body(job_ctx: JobContext) -> dict[str, Any]:
            job_ctx.raise_if_cancelled()
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(out_dir / f"{Path(media_path).stem or 'clip'}.broll.mp4")
            argv = broll_compose.build_broll_argv(media_path, insertions, out_path, settings=settings)
            job_ctx.progress(10, f"compositing {len(insertions)} b-roll window(s)")
            code = (run or _default_run)(argv)
            if code != 0:
                raise BrollComposeError(f"b-roll composite failed (ffmpeg exit {code}) for {media_path}")
            job_ctx.progress(100, f"composited {len(insertions)} b-roll window(s)")
            return {"path": out_path, "inserted": len(insertions)}

        return {"jobId": jobs.start(job_body).id}


def _default_run(argv: list[str]) -> int:  # pragma: no cover - the real drained seam
    from .. import ffmpeg as _ffmpeg  # noqa: PLC0415 - keep module import-light

    return _ffmpeg.run(argv)


def register(
    *,
    resolver: Resolver,
    list_assets: AssetLister,
    load_index: IndexLoader,
    save_index: IndexSaver,
    load_transcript: TranscriptLoader,
    out_dir: str | os.PathLike,
    embed_images: Embedder | None = None,
    embed_texts: Embedder | None = None,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    duration: ProbeFn | None = None,
    run: RunFn | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    clock: Clock | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> BrollOps:
    """Create the service and register every ``broll.*`` method.

    Mirrors ``silencetrim.register`` / ``tracks_audio.register``: ``register_fn``
    defaults to :func:`protocol.register` (a duplicate name fails loudly at
    startup) and tests inject a collecting registrar.
    """
    service = BrollOps(
        resolver=resolver,
        list_assets=list_assets,
        load_index=load_index,
        save_index=save_index,
        load_transcript=load_transcript,
        out_dir=out_dir,
        embed_images=embed_images,
        embed_texts=embed_texts,
        settings_provider=settings_provider,
        duration=duration,
        run=run,
        model_id=model_id,
        clock=clock,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("broll.status", service.status)
    reg("broll.index", service.index)
    reg("broll.suggest", service.suggest)
    reg("broll.apply", service.apply)
    log.info("registered %s", ", ".join(METHODS))
    return service


__all__ = [
    "BROLL_DIR_KEY",
    "DEFAULT_MODEL_ID",
    "IMAGE_EXTS",
    "INDEX_FILENAME",
    "MATCHED",
    "METHODS",
    "NO_CONFIDENT_MATCH",
    "VIDEO_EXTS",
    "BrollComposeError",
    "BrollOps",
    "load_index_file",
    "make_image_embedder",
    "make_text_embedder",
    "register",
    "save_index_file",
    "scan_assets",
]
