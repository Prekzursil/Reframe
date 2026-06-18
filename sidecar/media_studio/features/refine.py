"""REFINE — pure span/stat unifier for filler + silence removal (WU-1).

``plan_refine`` composes the ALREADY-SHIPPED, already-tested timeline math —
filler cut-lists (:func:`features.fillers.build_cutlist_with_stats`) and silence
keep-spans (:func:`features.silencetrim.keep_spans`) — into ONE union keep-list
plus mirrored stats. It is a Descript-style "see before you cut" planner:

    plan_refine(words, lang, total_sec, silences, *,
                remove_fillers, remove_silence,
                merge_gap_ms=..., pad_sec=..., filler_sets=None) -> RefinePlan

with ``RefinePlan = {"keeps": [[s, e], ...], "stats": {...}}``.

NO subprocess, NO model, NO I/O. The two engines each emit KEEP spans; the
removed regions are the gaps inside their respective windows. Combining a
filler-removal AND a silence-removal means the FINAL removed region is the
*union* of the two removed sets (so a filler that sits inside a silence is one
removed region, not two — no double-count). The final keep-list is therefore
``[0, total_sec]`` minus that union. Per-category stats stay independent
(``fillersRemoved``/``fillerSeconds`` mirror the shipped per-clip stats and
``silenceRemovedSec`` mirrors :func:`silencetrim.removed_seconds`), while
``keptSec`` reflects the de-duplicated union so it always equals
``total_sec - |union of removed|``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

from . import fillers as _fillers
from . import silencetrim as _silencetrim

# A keep span as emitted in the plan: [start, end] in original-video seconds.
Span = tuple[float, float]


class RefineStats(TypedDict):
    """Per-category refine stats (mirrors the shipped per-clip stat fields)."""

    fillersRemoved: int
    fillerSeconds: float
    silenceRemovedSec: float
    keptSec: float


class RefinePlan(TypedDict):
    """The pure refine plan: a union keep-list plus de-duplicated stats."""

    keeps: list[list[float]]
    stats: RefineStats


def _removed_from_keeps(keeps: Sequence[Span], lo: float, hi: float) -> list[Span]:
    """Invert ``keeps`` into the removed regions across ``[lo, hi]``.

    Every part of ``[lo, hi]`` not covered by a keep is a removed region (head,
    interior gaps, and tail all count). An empty keep-list means the engine
    declined to cut anything (it leaves the span whole), so nothing is removed.
    Callers pass ``[lo, hi]`` = the engine's removal window: ``[0, total]`` for
    silence (edge silences count) and the words' own span for fillers (nothing
    outside the transcript is ever a filler cut).
    """
    if hi <= lo or not keeps:
        return []
    spans = sorted((max(lo, float(a)), min(hi, float(b))) for a, b in keeps if float(b) > float(a))
    removed: list[Span] = []
    cursor = lo
    for start, end in spans:
        if start > cursor:
            removed.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < hi:
        removed.append((cursor, hi))
    return removed


def _union_spans(spans: Sequence[Span]) -> list[Span]:
    """Merge overlapping/adjacent spans into a minimal sorted union."""
    ordered = sorted((float(a), float(b)) for a, b in spans if float(b) > float(a))
    merged: list[Span] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end))
        else:
            merged.append((start, end))
    return merged


def _keeps_from_removed(removed: Sequence[Span], total: float) -> list[list[float]]:
    """Invert the (already-unioned) removed regions over ``[0, total]``."""
    keeps: list[list[float]] = []
    cursor = 0.0
    for start, end in removed:
        if start > cursor:
            keeps.append([round(cursor, 3), round(start, 3)])
        cursor = max(cursor, end)
    if cursor < total:
        keeps.append([round(cursor, 3), round(total, 3)])
    return keeps


def plan_refine(
    words: Sequence[Mapping[str, Any]],
    lang: str | None,
    total_sec: float,
    silences: Sequence[Span],
    *,
    remove_fillers: bool,
    remove_silence: bool,
    merge_gap_ms: int = _fillers.DEFAULT_MERGE_GAP_MS,
    pad_sec: float = _silencetrim.DEFAULT_PAD_SEC,
    filler_sets: Mapping[str, Mapping[str, frozenset]] | None = None,
) -> RefinePlan:
    """Compose filler + silence removal into ONE union keep-list and stats.

    ``words`` are §3 Words (original-video seconds), ``silences`` are detected
    silent spans, ``total_sec`` the clip duration. ``filler_sets`` (default
    ``None`` ⇒ :data:`fillers.DEFAULT_SETS`) is threaded straight into the
    filler engine's ``fillers=`` kwarg, so a caller-supplied per-language
    override genuinely changes which words are cut.
    """
    total = max(0.0, float(total_sec))

    filler_seconds = 0.0
    fillers_removed = 0
    filler_removed: list[Span] = []
    if remove_fillers:
        sets = filler_sets if filler_sets is not None else _fillers.DEFAULT_SETS
        keeps, stats = _fillers.build_cutlist_with_stats(
            words,
            lang,
            fillers=sets,
            merge_gap_ms=merge_gap_ms,
        )
        filler_seconds = float(stats["fillerSeconds"])
        fillers_removed = int(stats["fillersRemoved"])
        win_lo = keeps[0][0] if keeps else 0.0
        win_hi = keeps[-1][1] if keeps else 0.0
        filler_removed = _removed_from_keeps(keeps, win_lo, win_hi)

    silence_removed_sec = 0.0
    silence_removed: list[Span] = []
    if remove_silence:
        keeps = _silencetrim.keep_spans(silences, total, pad_sec=pad_sec)
        silence_removed_sec = _silencetrim.removed_seconds(keeps, total)
        silence_removed = _removed_from_keeps(keeps, 0.0, total)

    removed = _union_spans([*filler_removed, *silence_removed])
    if total <= 0.0:
        keeps_out: list[list[float]] = []
    else:
        keeps_out = _keeps_from_removed(removed, total) or [[0.0, round(total, 3)]]

    kept_sec = round(sum(b - a for a, b in keeps_out), 3)

    return RefinePlan(
        keeps=keeps_out,
        stats=RefineStats(
            fillersRemoved=fillers_removed,
            fillerSeconds=round(filler_seconds, 3),
            silenceRemovedSec=round(silence_removed_sec, 3),
            keptSec=kept_sec,
        ),
    )


__all__ = ["RefinePlan", "RefineStats", "plan_refine"]
