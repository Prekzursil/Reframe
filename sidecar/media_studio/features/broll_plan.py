"""PURE auto-b-roll planner (v1.5 flagship #3, WU BR3+BR4).

Turns *already-embedded* transcript segments and *already-embedded* library
assets into a list of timed B-roll insertions. It is the decision half of the
feature and it is deliberately model-free: no torch, no ffmpeg, no network, no
disk. The heavy cross-modal embedding lives behind the existing
:class:`~media_studio.features.vlm_backbone.BackboneBackend` seam
(``embed_images`` / ``embed_texts``); this module only consumes the vectors that
seam produced, which is what lets every branch below be covered deterministically
with hand-built arrays instead of a mocked model.

Four stages, each its own function so each is separately testable:

``rank_assets``
    The cross-modal INVERSION of the existing text index. The shipped
    :func:`semantic_index.search` ranks *segments* against a query; here the
    corpus rows are **assets** and the query is a **segment's text vector**, so
    the same function — with its length-guarded
    :func:`diarize.cosine_similarity`, its stable tie ordering, and its
    non-positive-``top_k`` guard — is reused verbatim and its ``segmentIndex``
    is read as the asset row index.

``suggest``
    The per-segment min-similarity gate. A segment whose best asset scores below
    ``threshold`` yields **nothing**. That wall is the whole feature: the #1
    complaint about hosted auto-b-roll is confidently-wrong filler, and the only
    honest answer to "no confident match" is no insert.

``diversify``
    Diversity RE-RANKING across the accepted suggestions, delegated to the
    shipped :func:`diversity.dedupe_candidates` (MMR or DPP) over the matched
    assets' own embeddings. Read that verb literally: with no ``k`` it re-ranks
    and drops NOTHING (``dedupe_candidates`` at ``budget == n`` returns all ``n``
    rows), so on the default path the thing that actually stops one asset
    repeating is ``place``'s per-asset COOLDOWN, not MMR. An earlier draft of
    this docstring said "near-duplicate suppression" flatly; measured, that was
    wider than the code — ``diversify(3 suggestions, k=None)`` returns 3.
    Suppression here requires an explicit ``k`` (``plan(max_inserts=…)``).

``place``
    The editorial constraints: clamp each insert's duration, keep it inside its
    segment, snap its start to a nearby shot boundary, enforce a minimum gap
    between inserts, enforce a per-asset cooldown, and cap total coverage as a
    percentage of the video. Selection is greedy in score order so the cap keeps
    the *best* inserts; the result is returned chronologically.

Thresholds are per-model: SigLIP-2's sigmoid-loss cosine scale does not transfer
to a softmax-CLIP tier, so :data:`DEFAULT_MIN_SIMILARITY` is the so400m default
only and a caller on another tier must pass its own calibrated value.
UNVERIFIED: that default is a placeholder carried from the design doc, NOT a
calibrated number — no labelled probe set has been measured on this branch. The
experiment that would settle it is docs/plans/v1.5/flagship-auto-broll.md §11.2
(20-30 (segment, relevant-asset, decoy) triples per tier, pick the
precision/recall knee). Until then treat the default as "requires a threshold
slider", not as a tuned constant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypedDict

from . import diversity, semantic_index

#: A dense vector (one per asset, or the per-segment text query).
Vector = Sequence[float]

#: How an insert is composited. ``cutaway`` replaces the frame for its window;
#: ``pip`` insets it in a face-safe corner. Consumed by ``broll_compose``.
Layout = Literal["cutaway", "pip"]
LAYOUTS: tuple[str, ...] = ("cutaway", "pip")
DEFAULT_LAYOUT = "cutaway"

#: Minimum cosine for a match to be offered at all. See the module docstring:
#: this is the SigLIP-2 so400m placeholder and is UNVERIFIED as a calibrated
#: value; pass an explicit ``threshold`` for any other backbone tier.
DEFAULT_MIN_SIMILARITY = 0.22

#: Timing envelope. An insert shorter than the minimum is dropped rather than
#: stretched (a 0.4 s flash reads as a glitch, not an edit).
DEFAULT_MIN_DURATION_SEC = 1.5
DEFAULT_MAX_DURATION_SEC = 5.0
#: Quiet time required between two inserts (measured edge to edge).
DEFAULT_MIN_GAP_SEC = 2.0
#: The same asset may not reappear within this many seconds.
DEFAULT_COOLDOWN_SEC = 30.0
#: Ceiling on how much of the video B-roll may cover, as a percentage.
DEFAULT_MAX_COVERAGE_PCT = 40.0
#: A start within this many seconds of a shot boundary is snapped onto it.
DEFAULT_SNAP_WINDOW_SEC = 0.5
#: How many assets each segment ranks before the gate is applied.
DEFAULT_TOP_K = 5

#: The reason string is shown verbatim in the review UI, so it is capped.
MAX_REASON_CHARS = 96
#: Prefix used when the segment carried no text to quote back.
REASON_NO_TEXT = "no segment text"


class AssetHit(TypedDict):
    """One asset ranked against a segment's text vector."""

    assetIndex: int
    assetId: str
    path: str
    kind: str
    score: float


class BrollSuggestion(TypedDict):
    """A gated, reviewable match: this asset, under this segment, this well."""

    segmentIndex: int
    start: float
    end: float
    assetId: str
    path: str
    kind: str
    score: float
    reason: str
    layout: str


class BrollInsertion(TypedDict):
    """A suggestion with its final, constraint-satisfying timing."""

    segmentIndex: int
    start: float
    end: float
    duration: float
    sourceStart: float
    assetId: str
    path: str
    kind: str
    score: float
    reason: str
    layout: str


def _asset_id(asset: Mapping[str, Any], index: int) -> str:
    """The asset's id, falling back to a positional one so a row is never anonymous."""
    return str(asset.get("assetId") or f"asset-{index}")


def rank_assets(
    query_vec: Vector,
    asset_vecs: Sequence[Vector],
    assets: Sequence[Mapping[str, Any]],
    top_k: int,
) -> list[AssetHit]:
    """Rank ``assets`` by cosine of their image vector against ``query_vec``.

    This is :func:`semantic_index.search` used cross-modally: its "corpus" rows
    are assets rather than transcript segments, so its ``segmentIndex`` is the
    asset row index. Reusing it (instead of re-deriving the loop) inherits three
    behaviours the planner depends on — a stable sort, so equal scores resolve to
    the lowest asset index and the plan is reproducible; a ``top_k <= 0`` guard;
    and the length-guarded cosine, so a query embedded by a *different* model
    surfaces as a :class:`ValueError` instead of a silently wrong ranking.
    """
    hits = semantic_index.search(query_vec, asset_vecs, assets, top_k)
    return [
        AssetHit(
            assetIndex=hit["segmentIndex"],
            assetId=_asset_id(assets[hit["segmentIndex"]], hit["segmentIndex"]),
            path=str(assets[hit["segmentIndex"]].get("path", "")),
            kind=str(assets[hit["segmentIndex"]].get("kind", "image")),
            score=hit["score"],
        )
        for hit in hits
    ]


def _reason(text: str, score: float) -> str:
    """A short, honest "why this matched" line: the quoted text plus the cosine."""
    suffix = f" ({score:.2f})"
    stripped = " ".join(text.split())
    if not stripped:
        return REASON_NO_TEXT + suffix
    budget = MAX_REASON_CHARS - len(suffix) - 2  # the two quote characters
    if len(stripped) > budget:
        stripped = stripped[: budget - 1].rstrip() + "…"
    return f'"{stripped}"{suffix}'


def suggest(
    segments: Sequence[Mapping[str, Any]],
    segment_vecs: Sequence[Vector],
    assets: Sequence[Mapping[str, Any]],
    asset_vecs: Sequence[Vector],
    *,
    threshold: float = DEFAULT_MIN_SIMILARITY,
    top_k: int = DEFAULT_TOP_K,
    layout: str = DEFAULT_LAYOUT,
) -> list[BrollSuggestion]:
    """Best above-``threshold`` asset per segment, in segment order.

    ``segment_vecs[i]`` is the text embedding of ``segments[i]`` and
    ``asset_vecs[j]`` the image embedding of ``assets[j]``; both must come from
    the SAME backbone family, because a cross-modal cosine is only meaningful
    inside one joint space.

    A segment whose best asset scores **below** ``threshold`` contributes no
    suggestion at all (the comparison is inclusive: exactly ``threshold``
    passes). An empty library yields ``[]``.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")
    if len(segment_vecs) != len(segments):
        raise ValueError(f"need one vector per segment: {len(segment_vecs)} vectors vs {len(segments)} segments")
    if len(asset_vecs) != len(assets):
        raise ValueError(f"need one vector per asset: {len(asset_vecs)} vectors vs {len(assets)} assets")

    out: list[BrollSuggestion] = []
    for index, (segment, query_vec) in enumerate(zip(segments, segment_vecs, strict=True)):
        hits = rank_assets(query_vec, asset_vecs, assets, top_k)
        if not hits or hits[0]["score"] < threshold:
            continue
        best = hits[0]
        out.append(
            BrollSuggestion(
                segmentIndex=index,
                start=float(segment.get("start", 0.0)),
                end=float(segment.get("end", 0.0)),
                assetId=best["assetId"],
                path=best["path"],
                kind=best["kind"],
                score=best["score"],
                reason=_reason(str(segment.get("text", "")), best["score"]),
                layout=layout,
            )
        )
    return out


def diversify(
    suggestions: Sequence[BrollSuggestion],
    assets: Sequence[Mapping[str, Any]],
    asset_vecs: Sequence[Vector],
    *,
    method: diversity.Method = "mmr",
    k: int | None = None,
) -> list[BrollSuggestion]:
    """Diversity-rank ``suggestions`` by their matched assets (MMR or DPP).

    Each suggestion is represented by its MATCHED ASSET's embedding, so two
    segments that landed on visually-identical assets compete. Delegates to the
    shipped :func:`diversity.dedupe_candidates` (which reads each candidate's
    ``score`` as relevance) and then restores chronological order, because the
    diversity ranking is a *selection*, not the edit order.

    ``k`` IS THE SUPPRESSION KNOB, and without it nothing is dropped. At the
    default ``k=None`` the underlying budget is ``n``, so MMR returns every row
    — re-ordered, then re-sorted chronologically here, i.e. a no-op on the
    OUTPUT SET. Measured: three suggestions all matching one asset come back as
    three at ``k=None`` and as one at ``k=1``. Pass ``k`` (or
    ``plan(max_inserts=…)``) when you want a cap; otherwise repetition is held
    down by ``place``'s per-asset cooldown instead.

    A suggestion naming an asset absent from ``assets`` is a caller bug and
    raises :class:`KeyError` rather than being silently dropped.
    """
    if not suggestions:
        return []
    by_id = {_asset_id(asset, index): index for index, asset in enumerate(assets)}
    rows = []
    for suggestion in suggestions:
        asset_id = suggestion["assetId"]
        if asset_id not in by_id:
            raise KeyError(f"suggestion names an unknown asset: {asset_id!r}")
        rows.append(list(asset_vecs[by_id[asset_id]]))
    kept = diversity.dedupe_candidates([dict(s) for s in suggestions], rows, method=method, k=k)
    kept.sort(key=lambda s: (float(s["start"]), int(s["segmentIndex"])))
    return [BrollSuggestion(**s) for s in kept]  # type: ignore[typeddict-item]


def _snap(start: float, boundaries: Sequence[float], window: float) -> float:
    """Snap ``start`` onto the nearest boundary within ``window`` seconds."""
    if not boundaries:
        return start
    nearest = min(boundaries, key=lambda b: abs(float(b) - start))
    if abs(float(nearest) - start) <= window:
        return float(nearest)
    return start


def _conflicts(
    candidate: BrollInsertion,
    accepted: Sequence[BrollInsertion],
    *,
    min_gap_sec: float,
    cooldown_sec: float,
) -> bool:
    """Whether ``candidate`` violates the spacing or the per-asset cooldown."""
    for other in accepted:
        overlaps = candidate["start"] < other["end"] + min_gap_sec and other["start"] < candidate["end"] + min_gap_sec
        if overlaps:
            return True
        if other["assetId"] == candidate["assetId"] and abs(candidate["start"] - other["start"]) < cooldown_sec:
            return True
    return False


def place(
    suggestions: Sequence[BrollSuggestion],
    *,
    total_sec: float,
    min_duration_sec: float = DEFAULT_MIN_DURATION_SEC,
    max_duration_sec: float = DEFAULT_MAX_DURATION_SEC,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    max_coverage_pct: float = DEFAULT_MAX_COVERAGE_PCT,
    boundaries: Sequence[float] = (),
    snap_window_sec: float = DEFAULT_SNAP_WINDOW_SEC,
) -> list[BrollInsertion]:
    """Turn ``suggestions`` into timed, constraint-satisfying insertions.

    Each insert is anchored to its segment's start (snapped onto a nearby shot
    boundary when one is given), runs for at most ``max_duration_sec``, never
    past its segment's end, and is dropped outright when the room left is under
    ``min_duration_sec``.

    Selection is greedy in DESCENDING score — so when the coverage cap or the
    spacing rules force a choice, the higher-confidence insert wins rather than
    the merely earlier one — and the survivors are returned in chronological
    order, which is the order an editor reads them.
    """
    if total_sec <= 0:
        raise ValueError(f"totalSec must be > 0, got {total_sec}")
    if not suggestions:
        return []

    budget_sec = total_sec * max_coverage_pct / 100.0
    candidates: list[BrollInsertion] = []
    for suggestion in suggestions:
        start = _snap(float(suggestion["start"]), boundaries, snap_window_sec)
        end = min(float(suggestion["end"]), start + max_duration_sec)
        duration = end - start
        if duration < min_duration_sec:
            continue
        candidates.append(
            BrollInsertion(
                segmentIndex=suggestion["segmentIndex"],
                start=start,
                end=end,
                duration=duration,
                # Video assets play from their own head; a still has no timeline.
                sourceStart=0.0,
                assetId=suggestion["assetId"],
                path=suggestion["path"],
                kind=suggestion["kind"],
                score=suggestion["score"],
                reason=suggestion["reason"],
                layout=suggestion["layout"],
            )
        )

    candidates.sort(key=lambda c: -c["score"])
    accepted: list[BrollInsertion] = []
    used_sec = 0.0
    for candidate in candidates:
        if used_sec + candidate["duration"] > budget_sec:
            continue
        if _conflicts(candidate, accepted, min_gap_sec=min_gap_sec, cooldown_sec=cooldown_sec):
            continue
        accepted.append(candidate)
        used_sec += candidate["duration"]
    accepted.sort(key=lambda c: (c["start"], c["segmentIndex"]))
    return accepted


def plan(
    segments: Sequence[Mapping[str, Any]],
    segment_vecs: Sequence[Vector],
    assets: Sequence[Mapping[str, Any]],
    asset_vecs: Sequence[Vector],
    *,
    total_sec: float,
    threshold: float = DEFAULT_MIN_SIMILARITY,
    top_k: int = DEFAULT_TOP_K,
    layout: str = DEFAULT_LAYOUT,
    method: diversity.Method = "mmr",
    max_inserts: int | None = None,
    min_duration_sec: float = DEFAULT_MIN_DURATION_SEC,
    max_duration_sec: float = DEFAULT_MAX_DURATION_SEC,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
    max_coverage_pct: float = DEFAULT_MAX_COVERAGE_PCT,
    boundaries: Sequence[float] = (),
    snap_window_sec: float = DEFAULT_SNAP_WINDOW_SEC,
) -> list[BrollInsertion]:
    """The composed pipeline: gate, then diversity-rank, then time.

    Returns ``[]`` — never a low-confidence filler insert — when nothing clears
    the threshold or the library is empty.

    ``max_inserts`` is :func:`diversify`'s ``k``. Leave it ``None`` and the
    diversity stage drops nothing; what keeps one asset from repeating is then
    ``cooldown_sec``, and what bounds the total is ``max_coverage_pct``. Set it
    when you want a hard cap on how many suggestions survive ranking.
    """
    gated = suggest(
        segments,
        segment_vecs,
        assets,
        asset_vecs,
        threshold=threshold,
        top_k=top_k,
        layout=layout,
    )
    diverse = diversify(gated, assets, asset_vecs, method=method, k=max_inserts)
    return place(
        diverse,
        total_sec=total_sec,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
        min_gap_sec=min_gap_sec,
        cooldown_sec=cooldown_sec,
        max_coverage_pct=max_coverage_pct,
        boundaries=boundaries,
        snap_window_sec=snap_window_sec,
    )


__all__ = [
    "DEFAULT_COOLDOWN_SEC",
    "DEFAULT_LAYOUT",
    "DEFAULT_MAX_COVERAGE_PCT",
    "DEFAULT_MAX_DURATION_SEC",
    "DEFAULT_MIN_DURATION_SEC",
    "DEFAULT_MIN_GAP_SEC",
    "DEFAULT_MIN_SIMILARITY",
    "DEFAULT_SNAP_WINDOW_SEC",
    "DEFAULT_TOP_K",
    "LAYOUTS",
    "MAX_REASON_CHARS",
    "REASON_NO_TEXT",
    "AssetHit",
    "BrollInsertion",
    "BrollSuggestion",
    "diversify",
    "place",
    "plan",
    "rank_assets",
    "suggest",
]
