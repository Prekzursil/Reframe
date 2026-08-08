"""PURE b-roll asset index: persisted shape, staleness, incremental refresh.

The only state auto-b-roll owns is a vector per library asset. This module is
the shape of that state and the arithmetic around it — no model, no disk, no
network. The caller reads/writes the JSON and supplies the embeddings; the two
concerns kept here are the two that can be quietly, confidently wrong:

**A stale row.** A file was re-exported but its vector was not recomputed, so
the planner ranks the OLD picture and cheerfully reports a high cosine.
:func:`fingerprint` is the staleness key — ``sha256`` over ``(path, size,
mtime)``, the same style as ``vision_ops._transcript_fp``'s corpus fingerprint —
and :func:`refresh_plan` re-embeds ONLY the rows whose fingerprint moved. Note
what that key is and is not (this is a real limit, not a nit): it is a
cheap-stat fingerprint, not a content hash, so an edit that preserves both size
and mtime is invisible to it. The library's own ``content_hash`` is the stronger
key and is the upgrade path; ``force=True`` is the escape hatch today. UNVERIFIED
whether a size+mtime collision occurs in practice for this workload — the
experiment is to fingerprint a real asset folder both ways and diff the sets.

**A model mismatch.** A cross-modal cosine is only meaningful inside ONE joint
space, so scoring a SigLIP-2 *text* vector against a Nomic *image* vector yields
a number that is confident and meaningless. The index therefore records the
``model`` it was built with and :func:`require_model` raises
:class:`StaleIndexError` rather than letting a query cross spaces.

Persisted shape (a sidecar JSON, mirroring the ``<videoId>.index.json``
convention — vectors never live in a manifest body)::

    {"version": 1, "model": "<hf id>", "dim": 768, "builtAt": "<iso>",
     "assets": [{"assetId", "path", "kind", "durationSec", "fingerprint",
                 "vector": [...]}, ...]}
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

#: Bump when the persisted shape changes incompatibly.
INDEX_VERSION = 1

Vector = Sequence[float]


class IndexedAsset(TypedDict):
    """One library asset and the image embedding that stands for it."""

    assetId: str
    path: str
    kind: str
    durationSec: float | None
    fingerprint: str
    vector: list[float]


class BrollIndex(TypedDict):
    """The whole persisted index."""

    version: int
    model: str
    dim: int
    builtAt: str
    assets: list[IndexedAsset]


class RefreshPlan(TypedDict):
    """What :func:`merge` needs: which rows to embed, which vectors to reuse."""

    rebuildAll: bool
    model: str
    embed: list[tuple[int, dict[str, Any]]]
    reuse: dict[str, list[float]]


class BrollIndexError(RuntimeError):
    """A b-roll index problem the caller must surface, never swallow."""


class StaleIndexError(BrollIndexError):
    """The index cannot answer this query (absent, or a different joint space)."""


def fingerprint(asset: Mapping[str, Any]) -> str:
    """A stable staleness key for ``asset``: ``sha256(path|size|mtime)``.

    See the module docstring for the honest limit — this is cheap stat metadata,
    not a content hash, so a same-size same-mtime rewrite is invisible to it.
    """
    payload = "|".join(
        (
            str(asset.get("path", "")),
            str(asset.get("sizeBytes", "")),
            str(asset.get("mtime", "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row(asset: Mapping[str, Any], vector: Vector) -> IndexedAsset:
    duration = asset.get("durationSec")
    return IndexedAsset(
        assetId=str(asset.get("assetId", "")),
        path=str(asset.get("path", "")),
        kind=str(asset.get("kind", "image")),
        durationSec=None if duration is None else float(duration),
        fingerprint=fingerprint(asset),
        vector=[float(v) for v in vector],
    )


def build(
    assets: Sequence[Mapping[str, Any]],
    vectors: Sequence[Vector],
    *,
    model: str,
    built_at: str,
) -> BrollIndex:
    """A complete index over ``assets`` and their image embeddings.

    Every vector must share one dimension — a ragged matrix means two different
    towers produced them, which is the model-mismatch failure one step earlier.
    """
    if not model:
        raise ValueError("an index must record the model that built it")
    if len(vectors) != len(assets):
        raise ValueError(f"need one vector per asset: {len(vectors)} vectors vs {len(assets)} assets")
    dims = {len(v) for v in vectors}
    if len(dims) > 1:
        raise ValueError(f"every vector must have the same dimension, got {sorted(dims)}")
    return BrollIndex(
        version=INDEX_VERSION,
        model=model,
        dim=dims.pop() if dims else 0,
        builtAt=built_at,
        assets=[_row(asset, vector) for asset, vector in zip(assets, vectors, strict=True)],
    )


def rows(index: BrollIndex) -> tuple[list[dict[str, Any]], list[list[float]]]:
    """Split ``index`` into the ``(assets, vectors)`` pair the planner takes.

    The asset dicts deliberately drop ``vector``: ``broll_plan`` receives the
    matrix as its own argument, so carrying it twice invites the two copies to
    disagree.
    """
    assets = [{k: v for k, v in row.items() if k != "vector"} for row in index["assets"]]
    return assets, [list(row["vector"]) for row in index["assets"]]


def require_model(index: BrollIndex | None, model: str) -> None:
    """Refuse LOUDLY unless ``index`` lives in ``model``'s joint space."""
    if index is None:
        raise StaleIndexError("the b-roll library has not been indexed yet; run broll.index first")
    if index["model"] != model:
        raise StaleIndexError(
            f"the b-roll index was built with {index['model']!r} but the query uses {model!r}; "
            "a cross-modal cosine is only valid inside one joint space — re-index to switch backbone"
        )


def refresh_plan(
    index: BrollIndex | None,
    assets: Sequence[Mapping[str, Any]],
    *,
    model: str,
    force: bool = False,
) -> RefreshPlan:
    """Decide which of ``assets`` actually need embedding.

    Everything is re-embedded when there is no index, when ``force`` is set, or
    when ``model`` differs from the index's — the last because vectors from a
    different tower cannot be mixed into one space. Otherwise only the rows
    whose :func:`fingerprint` moved (or that are new) are listed in ``embed``;
    the rest are reused verbatim. Assets no longer in the library simply do not
    appear, which is how a removal prunes the index without a rebuild.
    """
    rebuild_all = force or index is None or index["model"] != model
    reuse: dict[str, list[float]] = {}
    if not rebuild_all and index is not None:
        reuse = {row["fingerprint"]: list(row["vector"]) for row in index["assets"]}
    embed = [(i, dict(asset)) for i, asset in enumerate(assets) if fingerprint(asset) not in reuse]
    return RefreshPlan(rebuildAll=rebuild_all, model=model, embed=embed, reuse=reuse)


def merge(
    plan: RefreshPlan,
    assets: Sequence[Mapping[str, Any]],
    embedded: Mapping[int, Vector],
    *,
    model: str,
    built_at: str,
) -> BrollIndex:
    """Fold freshly-computed vectors back onto ``plan``'s reused ones.

    ``embedded`` maps an index into ``assets`` to the vector just computed for
    it — exactly the positions ``plan['embed']`` asked for. A position the plan
    asked for and the caller did not supply is a bug and raises, rather than
    silently persisting a row with no vector.
    """
    vectors: list[Vector] = []
    for position, asset in enumerate(assets):
        if position in embedded:
            vectors.append(embedded[position])
            continue
        cached = plan["reuse"].get(fingerprint(asset))
        if cached is None:
            raise ValueError(f"no embedding supplied for asset {position} ({asset.get('path', '')!r})")
        vectors.append(cached)
    return build(assets, vectors, model=model, built_at=built_at)


def status(
    index: BrollIndex | None,
    assets: Sequence[Mapping[str, Any]],
    *,
    model: str,
) -> dict[str, Any]:
    """The freshness snapshot the UI renders (a pure read; no provider call).

    ``staleCount`` is how many library assets would have to be embedded to make
    the index current — the whole library on a model change, which is why the
    UI can honestly say "switching backbone means a full re-index".
    """
    plan = refresh_plan(index, assets, model=model)
    stale_count = len(plan["embed"])
    return {
        "indexed": index is not None,
        "assetCount": 0 if index is None else len(index["assets"]),
        "libraryCount": len(assets),
        "model": "" if index is None else index["model"],
        "dim": 0 if index is None else index["dim"],
        "stale": stale_count > 0 or plan["rebuildAll"],
        "staleCount": stale_count,
    }


__all__ = [
    "INDEX_VERSION",
    "BrollIndex",
    "BrollIndexError",
    "IndexedAsset",
    "RefreshPlan",
    "StaleIndexError",
    "build",
    "fingerprint",
    "merge",
    "refresh_plan",
    "require_model",
    "rows",
    "status",
]
