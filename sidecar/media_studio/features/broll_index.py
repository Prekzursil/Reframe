"""Visual B-ROLL INDEX — a FLAT float32 embedding store (NOT a vector-DB).

Closes the VISUAL half of the text-only :mod:`semantic_index`: index a clip's
frames/shots by their vision embedding, then retrieve matching b-roll by a TEXT
query ("a drone shot of a city at night") or by an image. The store is a plain
contiguous ``float32`` matrix scanned by brute-force cosine — deliberately NOT an
approximate-nearest-neighbour vector database (a local desktop b-roll library is
thousands of shots, not billions; a flat scan is exact, dependency-free, and
trivially portable). Persistence is raw little-endian ``float32`` bytes + a JSON
metadata sidecar, so an index round-trips with no DB engine.

Encoder seam (rides the EXISTING backbone — no new model on the default path):
the embeddings come from the shared :class:`vlm_backbone.BackboneBackend`
(SigLIP-2 SoViT-400M, Apache-2.0), the SAME single-load backbone the scorers use.
**PE-Core** (Meta Perception Encoder, ``facebook/PE-Core-B16-224``, Apache-2.0 —
verified) is registered as an OPT-IN higher-quality visual encoder (mirrors the
``ctc_align`` model-alias pattern); the wired default stays SigLIP-2 so the b-roll
index adds ZERO new required weights. (The Qwen3-VL backbone swap is a separate
STAGE — out of scope here.)

Design (the canonical Phase-8 seam pattern):
  * **Pure half (fully covered, no heavy deps):** the float32 store, cosine
    search, and (de)serialization — plain numpy, unit-tested with hand-built
    vectors; NO model, NO cv2, NO network.
  * **Heavy half (behind the shared backbone seam, lazy):** :func:`index_video`
    samples frames + embeds them ONCE; :func:`search_text` embeds a text query.
    Both degrade to an empty result (offline + model missing, or no frames) —
    never a raise, never fabricated vectors.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from ..util import get_logger
from . import offline as _offline
from . import vlm_backbone as _vlm

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.broll_index")

#: on-disk format version (bumped if the sidecar schema changes).
INDEX_VERSION = 1
#: file suffixes for the two-part persistence (raw float32 + JSON metadata).
VECTORS_SUFFIX = ".vectors.f32"
META_SUFFIX = ".meta.json"

#: the default (wired) visual encoder — the shared SigLIP-2 backbone (Apache-2.0).
DEFAULT_ENCODER_MODEL_ID = _vlm.SIGLIP2_MODEL_ID

#: OPT-IN higher-quality visual encoder — Meta Perception Encoder Core (Apache-2.0).
#: Real HF snapshot pin (git ls-remote, 2026-07-12). Registered as an asset so it
#: is discoverable; wiring a PE-Core backbone backend is a follow-up (the default
#: index rides SigLIP-2 and needs no new weights).
PE_CORE_MODEL_ID = "facebook/PE-Core-B16-224"
PE_CORE_REVISION = "a16450b46fef32363459920c2685a1b4ef13dcd9"
PE_CORE_ASSET_NAME = "pe-core-b16"
PE_CORE_SIZE_MB = 420

#: short alias -> full model id (the opt-in encoder switch, mirrors ctc_align).
_ENCODER_ALIASES: dict[str, str] = {
    "pe-core": PE_CORE_MODEL_ID,
    "pe-core-b16": PE_CORE_MODEL_ID,
    "siglip2": _vlm.SIGLIP2_MODEL_ID,
}

CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]
BackboneFactory = Callable[[dict[str, Any]], _vlm.BackboneBackend]
FrameLoader = Callable[[str, Sequence[float]], "list[np.ndarray]"]
ModelsPresent = Callable[[dict[str, Any]], bool]


class BrollEntry(TypedDict, total=False):
    """Metadata for ONE indexed shot/frame (parallel to its embedding row)."""

    videoId: str
    path: str
    start: float
    end: float
    frameTime: float
    label: str


class Hit(TypedDict):
    """One ranked b-roll search result, shaped for the renderer."""

    entryIndex: int
    videoId: str
    path: str
    start: float
    end: float
    frameTime: float
    score: float


# --------------------------------------------------------------------------- #
# pure numpy: normalization + cosine search over the flat matrix
# --------------------------------------------------------------------------- #
def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2-normalize a 2-D array (zero rows stay zero)."""
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    arr = np.asarray(matrix, dtype=np.float64)
    if arr.ndim != 2:
        arr = arr.reshape(1, -1) if arr.size else arr.reshape(0, 0)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    safe = np.where(norms == 0.0, 1.0, norms)
    return arr / safe


def cosine_rank(query_vec: Sequence[float], matrix: np.ndarray, top_k: int) -> list[tuple[int, float]]:
    """Rank rows of ``matrix`` by cosine against ``query_vec`` -> ``[(row, score)]``.

    Returns the top ``top_k`` ``(row_index, cosine)`` pairs, descending; ties keep
    the lower row index (stable). A non-positive ``top_k`` or an empty matrix
    yields ``[]``. A query whose dimension differs from the matrix raises
    ``ValueError`` (a real mismatch must fail loud, not silently mis-rank).
    """
    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    mat = np.asarray(matrix, dtype=np.float64)
    if top_k <= 0 or mat.ndim != 2 or mat.shape[0] == 0:
        return []
    q = np.asarray(query_vec, dtype=np.float64).reshape(-1)
    if q.shape[0] != mat.shape[1]:
        raise ValueError(f"query dim {q.shape[0]} != index dim {mat.shape[1]}")
    normed = _l2_normalize(mat)
    qn = q / (np.linalg.norm(q) or 1.0)
    sims = normed @ qn
    order = np.argsort(-sims, kind="stable")[: int(top_k)]
    return [(int(i), float(sims[i])) for i in order]


# --------------------------------------------------------------------------- #
# the flat float32 store
# --------------------------------------------------------------------------- #
class BrollIndex:
    """A flat ``(N, D)`` float32 embedding matrix + parallel entry metadata.

    Brute-force cosine search — exact, no ANN engine. Rows and ``entries`` stay
    1:1 and in insertion order. ``dim`` is fixed by the first added vector (or an
    explicit ``dim`` at construction); a mismatched vector raises ``ValueError``.
    """

    def __init__(self, dim: int | None = None, *, encoder_model_id: str = DEFAULT_ENCODER_MODEL_ID) -> None:
        import numpy as np  # noqa: PLC0415 - numpy is in the venv

        self._dim = int(dim) if dim else 0
        self._vectors: np.ndarray = np.zeros((0, self._dim), dtype=np.float32)
        self.entries: list[BrollEntry] = []
        self.encoder_model_id = encoder_model_id

    @property
    def dim(self) -> int:
        """The embedding dimension (0 until the first vector is added)."""
        return self._dim

    @property
    def vectors(self) -> np.ndarray:
        """The underlying ``(N, D)`` float32 matrix (a view — do not mutate)."""
        return self._vectors

    def __len__(self) -> int:
        return len(self.entries)

    def add(self, vector: Sequence[float], entry: BrollEntry) -> None:
        """Append ONE embedding + its entry (fixes ``dim`` on the first add)."""
        self.add_batch([vector], [entry])

    def add_batch(self, vectors: Sequence[Sequence[float]] | np.ndarray, entries: Sequence[BrollEntry]) -> None:
        """Append a batch of embeddings + entries (rows and entries stay 1:1)."""
        import numpy as np  # noqa: PLC0415 - numpy is in the venv

        if len(vectors) != len(entries):
            raise ValueError(f"vectors ({len(vectors)}) and entries ({len(entries)}) length mismatch")
        if len(vectors) == 0:  # NOTE: `not vectors` is ambiguous for a numpy array — use len()
            return
        block = np.asarray(vectors, dtype=np.float32)
        if block.ndim != 2:
            block = block.reshape(len(vectors), -1)
        if self._dim == 0:
            self._dim = int(block.shape[1])
            self._vectors = np.zeros((0, self._dim), dtype=np.float32)
        if block.shape[1] != self._dim:
            raise ValueError(f"vector dim {block.shape[1]} != index dim {self._dim}")
        self._vectors = np.vstack([self._vectors, block]) if len(self.entries) else block
        self.entries.extend(dict(e) for e in entries)  # type: ignore[misc]

    def search(self, query_vec: Sequence[float], top_k: int = 5) -> list[Hit]:
        """Cosine-rank the index against ``query_vec`` -> the top-K :class:`Hit`\\ s."""
        hits: list[Hit] = []
        for row, score in cosine_rank(query_vec, self._vectors, top_k):
            entry = self.entries[row]
            hits.append(
                {
                    "entryIndex": row,
                    "videoId": str(entry.get("videoId", "")),
                    "path": str(entry.get("path", "")),
                    "start": float(entry.get("start", 0.0)),
                    "end": float(entry.get("end", 0.0)),
                    "frameTime": float(entry.get("frameTime", entry.get("start", 0.0))),
                    "score": round(score, 6),
                }
            )
        return hits

    # ---- persistence: raw float32 bytes + a JSON sidecar (no DB engine) ---- #
    def save(self, base_path: str) -> tuple[str, str]:
        """Write ``<base>.vectors.f32`` (raw float32) + ``<base>.meta.json``.

        Returns ``(vectors_path, meta_path)``. The vectors file is the contiguous
        little-endian float32 matrix (C-order); the sidecar carries the shape,
        encoder id, version, and the parallel entry list so the pair round-trips.
        """
        import numpy as np  # noqa: PLC0415 - numpy is in the venv

        base = Path(base_path)
        base.parent.mkdir(parents=True, exist_ok=True)
        vectors_path = str(base) + VECTORS_SUFFIX
        meta_path = str(base) + META_SUFFIX
        np.ascontiguousarray(self._vectors, dtype="<f4").tofile(vectors_path)
        meta = {
            "version": INDEX_VERSION,
            "dim": self._dim,
            "count": len(self.entries),
            "encoderModelId": self.encoder_model_id,
            "entries": self.entries,
        }
        Path(meta_path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return vectors_path, meta_path

    @classmethod
    def load(cls, base_path: str) -> BrollIndex:
        """Load an index previously written by :meth:`save`.

        Raises ``ValueError`` when the raw float32 byte count does not match the
        sidecar's ``count * dim`` (a truncated / mismatched file must fail loud,
        never silently reshape into garbage).
        """
        import numpy as np  # noqa: PLC0415 - numpy is in the venv

        base = Path(base_path)
        meta = json.loads((Path(str(base) + META_SUFFIX)).read_text(encoding="utf-8"))
        dim = int(meta.get("dim", 0))
        count = int(meta.get("count", 0))
        raw = np.fromfile(str(base) + VECTORS_SUFFIX, dtype="<f4")
        if raw.size != count * dim:
            raise ValueError(f"broll index corrupt: {raw.size} float32 != count*dim ({count}*{dim})")
        index = cls(dim=dim, encoder_model_id=str(meta.get("encoderModelId", DEFAULT_ENCODER_MODEL_ID)))
        entries = [dict(e) for e in meta.get("entries", [])]
        if count:
            index.add_batch(raw.reshape(count, dim), entries)  # type: ignore[arg-type]
        return index


# --------------------------------------------------------------------------- #
# encoder-model resolution (default SigLIP-2 / opt-in PE-Core)
# --------------------------------------------------------------------------- #
def resolve_encoder_model_id(settings: dict[str, Any], model_id: str | None = None) -> str:
    """Pick the visual encoder: explicit arg > ``settings['brollEncoderId']`` > default.

    A short alias (``pe-core`` / ``siglip2``) resolves to its full HF id. Absent
    both, the wired SigLIP-2 default is used (no new weights).
    """
    if model_id:
        return _ENCODER_ALIASES.get(model_id, model_id)
    configured = settings.get("brollEncoderId")
    if isinstance(configured, str) and configured:
        return _ENCODER_ALIASES.get(configured, configured)
    return DEFAULT_ENCODER_MODEL_ID


# --------------------------------------------------------------------------- #
# default heavy seams (lazy; rides the SHARED SigLIP-2 backbone) — no coverage
# --------------------------------------------------------------------------- #
def _default_backend_factory(settings: dict[str, Any]) -> _vlm.BackboneBackend:  # pragma: no cover - heavy seam
    """Build the shared SigLIP-2 backbone (LAZY import; the SAME model the scorers load)."""
    from .vlm_backbone_backend import RealBackboneBackend  # noqa: PLC0415 - heavy seam

    return RealBackboneBackend(settings)


def _default_frame_loader(media_path: str, timestamps: Sequence[float]) -> list[np.ndarray]:  # pragma: no cover - needs cv2 + a real file
    """Grab one BGR frame per timestamp via cv2 (mirrors vlm_backbone's loader)."""
    import cv2  # noqa: PLC0415 - job-time native

    cap = cv2.VideoCapture(media_path)
    frames: list[np.ndarray] = []
    try:
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(ts) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        cap.release()
    return frames


def _default_models_present(settings: dict[str, Any]) -> bool:  # pragma: no cover - probes the asset store
    """True when the SigLIP-2 backbone asset is installed (reuses vlm_backbone's probe)."""
    return _vlm._default_models_present(settings)


# --------------------------------------------------------------------------- #
# the public runners (index a clip / search by text) — ride the backbone seam
# --------------------------------------------------------------------------- #
def index_video(
    media_path: str,
    *,
    video_id: str,
    duration: float,
    settings: dict[str, Any] | None = None,
    backend_factory: BackboneFactory | None = None,
    frame_loader: FrameLoader | None = None,
    models_present: ModelsPresent | None = None,
    win_sec: float = _vlm.DEFAULT_WIN_SEC,
    hop_sec: float = _vlm.DEFAULT_HOP_SEC,
    encoder_model_id: str | None = None,
    into: BrollIndex | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> BrollIndex:
    """Sample frames of ``media_path``, embed them ONCE, add them to a b-roll index.

    Returns a :class:`BrollIndex` (a new one, or ``into`` extended). Each frame
    becomes one entry ``{videoId, path, start, end, frameTime}`` on the window
    grid (:func:`vlm_backbone.sample_windows`). Degrade paths (never raise):
      * offline AND the backbone asset missing -> the (unchanged) index is
        returned empty;
      * the frame loader yields no frames -> unchanged;
      * a cooperative cancel before embedding -> unchanged.
    """
    settings = dict(settings or {})
    factory = backend_factory or _default_backend_factory
    loader = frame_loader or _default_frame_loader
    present = models_present or _default_models_present
    resolved = resolve_encoder_model_id(settings, encoder_model_id)
    index = into if into is not None else BrollIndex(encoder_model_id=resolved)

    if not present(settings) and _offline.is_offline(settings):
        log.info("broll_index: backbone unavailable offline — empty index")
        return index

    windows = _vlm.sample_windows(duration, win_sec, hop_sec)
    timestamps = [round((w0 + w1) / 2.0, 3) for w0, w1 in windows]
    if on_progress is not None:
        on_progress(5.0, "extracting frames")
    if should_cancel is not None and should_cancel():
        return index

    frames = list(loader(media_path, timestamps) or [])
    if not frames:
        log.info("broll_index: no frames extracted from %s", media_path)
        return index

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    backend = factory(settings)
    if on_progress is not None:
        on_progress(50.0, "embedding frames")
    embeds = np.asarray(backend.embed_images(np.asarray(frames)), dtype=np.float32)
    if embeds.ndim != 2 or embeds.shape[0] == 0:
        return index

    used = min(embeds.shape[0], len(windows))
    entries: list[BrollEntry] = [
        {
            "videoId": video_id,
            "path": media_path,
            "start": float(windows[i][0]),
            "end": float(windows[i][1]),
            "frameTime": float(timestamps[i]),
        }
        for i in range(used)
    ]
    index.add_batch(embeds[:used], entries)
    if on_progress is not None:
        on_progress(100.0, "done")
    return index


def search_text(
    index: BrollIndex,
    query: str,
    *,
    top_k: int = 5,
    settings: dict[str, Any] | None = None,
    backend_factory: BackboneFactory | None = None,
    models_present: ModelsPresent | None = None,
) -> list[Hit]:
    """Find b-roll matching a TEXT ``query`` by embedding it and cosine-ranking.

    Rides the SAME backbone's ``embed_texts``. Degrades to ``[]`` when the index
    is empty, the query is blank, or (offline AND the backbone asset missing) — a
    text query never fabricates a vector, never raises.
    """
    settings = dict(settings or {})
    if len(index) == 0 or not str(query).strip():
        return []
    factory = backend_factory or _default_backend_factory
    present = models_present or _default_models_present
    if not present(settings) and _offline.is_offline(settings):
        log.info("broll_index: backbone unavailable offline — no text search")
        return []

    import numpy as np  # noqa: PLC0415 - numpy is in the venv

    backend = factory(settings)
    text_embeds = np.asarray(backend.embed_texts([query]), dtype=np.float64)
    if text_embeds.ndim != 2 or text_embeds.shape[0] == 0:
        return []
    return index.search(text_embeds[0], top_k=top_k)


def search_image_embed(index: BrollIndex, image_embed: Sequence[float], *, top_k: int = 5) -> list[Hit]:
    """Find b-roll matching an already-embedded IMAGE vector (pure cosine search).

    For query-by-example when the caller already holds a frame embedding (e.g.
    from :func:`vlm_backbone.compute_backbone_signals`'s embed pass). No model,
    no network — a direct flat-matrix scan.
    """
    return index.search(image_embed, top_k=top_k)


# --------------------------------------------------------------------------- #
# asset registration (PE-Core opt-in encoder; mirrors vlm_backbone)
# --------------------------------------------------------------------------- #
def register_broll_assets() -> None:
    """Register the OPT-IN PE-Core visual encoder as an on-demand asset (idempotent).

    Meta Perception Encoder Core B16 (Apache-2.0). The wired default encoder is
    the already-registered SigLIP-2 backbone, so this asset is a pure upgrade a
    user opts into via ``settings['brollEncoderId'] = 'pe-core'``. Real pinned HF
    revision (F3c). Identical re-registration is a no-op.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=PE_CORE_ASSET_NAME,
            kind="model",
            size_mb=PE_CORE_SIZE_MB,
            label="PE-Core B16 (opt-in b-roll visual encoder, Apache-2.0)",
            tier="optional",
            why="Higher-quality visual embeddings for the b-roll index (default rides SigLIP-2, no new weights).",
            installer="hf",
            hf_repo=PE_CORE_MODEL_ID,
            hf_revision=PE_CORE_REVISION,
        )
    )


# Register the opt-in asset at import (mirrors vlm_backbone.register_backbone_assets()).
register_broll_assets()


__all__ = [
    "DEFAULT_ENCODER_MODEL_ID",
    "INDEX_VERSION",
    "META_SUFFIX",
    "PE_CORE_ASSET_NAME",
    "PE_CORE_MODEL_ID",
    "PE_CORE_SIZE_MB",
    "VECTORS_SUFFIX",
    "BackboneFactory",
    "BrollEntry",
    "BrollIndex",
    "FrameLoader",
    "Hit",
    "ModelsPresent",
    "cosine_rank",
    "index_video",
    "register_broll_assets",
    "resolve_encoder_model_id",
    "search_image_embed",
    "search_text",
]
