"""Unit tests for the pure refine planner (features/refine.py, WU-1).

``plan_refine`` is PURE timeline math: it composes the already-shipped filler
cut-list (:func:`fillers.build_cutlist_with_stats`) and silence keep-spans
(:func:`silencetrim.keep_spans`) into ONE union keep-list plus mirrored stats.
No subprocess, no model, no I/O — so every branch is exercised with hand-built
``words``/``silences`` and the bundled default filler sets.
"""

from __future__ import annotations

from typing import Any

from media_studio.features import fillers as fl
from media_studio.features import refine as rf


def w(text: str, start: float, end: float) -> dict[str, Any]:
    return {"text": text, "start": start, "end": end}


def _kept_seconds(keeps: list[list[float]]) -> float:
    return round(sum(b - a for a, b in keeps), 3)


# ---------------------------------------------------------------------------
# both-off pass-through (acceptance #1)
# ---------------------------------------------------------------------------
def test_both_off_keeps_whole_clip_and_zero_stats():
    words = [w("um", 2.0, 2.4), w("hello", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=False,
        remove_silence=False,
    )
    assert plan["keeps"] == [[0.0, 10.0]]
    stats = plan["stats"]
    assert stats["fillersRemoved"] == 0
    assert stats["fillerSeconds"] == 0.0
    assert stats["silenceRemovedSec"] == 0.0
    assert stats["keptSec"] == 10.0


# ---------------------------------------------------------------------------
# disjoint filler + silence (acceptance #2 — no double-count)
# ---------------------------------------------------------------------------
def test_disjoint_filler_and_silence_excluded_no_double_count():
    words = [
        w("people", 0.0, 0.5),
        w("um", 2.0, 2.4),
        w("buy", 3.0, 3.5),
    ]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=True,
        pad_sec=0.0,
    )
    keeps = plan["keeps"]
    # The filler [2.0,2.4] and the silence [5.0,7.0] are both removed.
    for start, end in keeps:
        assert not (start <= 2.0 < end), keeps
        assert not (start < 7.0 and end > 5.0 and start >= 5.0), keeps
    stats = plan["stats"]
    assert abs(stats["fillerSeconds"] - 0.4) < 1e-6
    assert abs(stats["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(stats["keptSec"] - 7.6) < 1e-6
    assert stats["fillersRemoved"] == 1


# ---------------------------------------------------------------------------
# overlapping filler-inside-silence collapses (acceptance #3)
# ---------------------------------------------------------------------------
def test_overlapping_filler_inside_silence_single_removed_region():
    # The filler word sits INSIDE the silent span: the removed region is ONE,
    # not the sum of both, so kept == total - removed (no double subtraction).
    words = [
        w("people", 0.0, 0.5),
        w("um", 5.5, 5.9),
        w("buy", 8.0, 8.5),
    ]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=True,
        pad_sec=0.0,
    )
    keeps = plan["keeps"]
    removed = round(10.0 - _kept_seconds(keeps), 3)
    assert removed <= 10.0
    assert abs(plan["stats"]["keptSec"] - _kept_seconds(keeps)) < 1e-6
    # The combined removed region equals the single 2.0s silence (filler subset).
    assert abs(removed - 2.0) < 1e-6


# ---------------------------------------------------------------------------
# edge silences (head at 0.0 / tail at total) — full-window inversion
# ---------------------------------------------------------------------------
def test_leading_silence_removed_from_clip_start():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [(0.0, 2.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["keeps"] == [[2.0, 10.0]]
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(plan["stats"]["keptSec"] - 8.0) < 1e-6


def test_trailing_silence_removed_to_clip_end():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [(8.0, 10.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["keeps"] == [[0.0, 8.0]]
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    assert abs(plan["stats"]["keptSec"] - 8.0) < 1e-6


# ---------------------------------------------------------------------------
# fillers-only / silence-only branch matrix
# ---------------------------------------------------------------------------
def test_fillers_only_ignores_silence():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=True,
        remove_silence=False,
    )
    assert plan["stats"]["silenceRemovedSec"] == 0.0
    assert plan["stats"]["fillerSeconds"] > 0.0
    # The silence span is NOT removed when remove_silence is off.
    assert any(start <= 6.0 < end for start, end in plan["keeps"])


def test_silence_only_ignores_fillers():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        "en",
        10.0,
        [(5.0, 7.0)],
        remove_fillers=False,
        remove_silence=True,
        pad_sec=0.0,
    )
    assert plan["stats"]["fillerSeconds"] == 0.0
    assert plan["stats"]["fillersRemoved"] == 0
    assert abs(plan["stats"]["silenceRemovedSec"] - 2.0) < 1e-6
    # The filler is NOT removed when remove_fillers is off.
    assert any(start <= 2.2 < end for start, end in plan["keeps"])


# ---------------------------------------------------------------------------
# empty inputs + degenerate edges
# ---------------------------------------------------------------------------
def test_empty_words_and_empty_silences():
    plan = rf.plan_refine(
        [],
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=True,
    )
    assert plan["keeps"] == [[0.0, 10.0]]
    assert plan["stats"]["fillersRemoved"] == 0
    assert plan["stats"]["silenceRemovedSec"] == 0.0
    assert plan["stats"]["keptSec"] == 10.0


def test_zero_length_total_sec_yields_empty_keeps():
    plan = rf.plan_refine(
        [],
        "en",
        0.0,
        [],
        remove_fillers=True,
        remove_silence=True,
    )
    assert plan["keeps"] == []
    assert plan["stats"]["keptSec"] == 0.0


def test_lang_none_falls_back_to_en():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    plan = rf.plan_refine(
        words,
        None,
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
    )
    # 'en' "um" is an always-filler, so it is removed under the en fallback.
    assert plan["stats"]["fillersRemoved"] == 1


# ---------------------------------------------------------------------------
# filler-set override threading (acceptance #4)
# ---------------------------------------------------------------------------
def test_filler_sets_override_changes_cut_math_for_ro():
    # A word that is NOT a default 'ro' filler; standing alone (pause-bounded).
    words = [
        w("bună", 0.0, 0.5),
        w("totuși", 2.0, 2.5),  # custom-only filler; pause-bounded both sides
        w("lume", 4.0, 4.5),
    ]
    base = rf.plan_refine(
        words,
        "ro",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
    )
    assert base["stats"]["fillersRemoved"] == 0  # default 'ro' keeps it
    assert any(start <= 2.2 < end for start, end in base["keeps"])

    custom = {
        "ro": {
            "always": frozenset({"totuși"}),
            "standalone": frozenset(),
        }
    }
    over = rf.plan_refine(
        words,
        "ro",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=custom,
    )
    assert over["stats"]["fillersRemoved"] == base["stats"]["fillersRemoved"] + 1
    assert not any(start <= 2.2 < end for start, end in over["keeps"])


def test_filler_sets_none_uses_default_sets():
    words = [w("people", 0.0, 0.5), w("um", 2.0, 2.4), w("buy", 3.0, 3.5)]
    explicit = rf.plan_refine(
        words,
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=None,
    )
    default = rf.plan_refine(
        words,
        "en",
        10.0,
        [],
        remove_fillers=True,
        remove_silence=False,
        filler_sets=fl.DEFAULT_SETS,
    )
    assert explicit == default


# ---------------------------------------------------------------------------
# RefinePlan typing surface
# ---------------------------------------------------------------------------
def test_refineplan_keys_and_all():
    plan = rf.plan_refine([], "en", 1.0, [], remove_fillers=False, remove_silence=False)
    assert set(plan) == {"keeps", "stats"}
    assert set(plan["stats"]) == {
        "fillersRemoved",
        "fillerSeconds",
        "silenceRemovedSec",
        "keptSec",
    }
    assert "plan_refine" in rf.__all__
    assert "RefinePlan" in rf.__all__
