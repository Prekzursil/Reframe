"""PURE auto-b-roll planner tests (v1.5 flagship #3, WU BR3+BR4).

Every cosine here is HAND-BUILT: asset vectors are the 2-D basis (``[1,0]`` /
``[0,1]``) and each segment's query vector is aimed at one of them, so the
retrieval score of every (segment, asset) pair is arithmetic the test states
outright. No model, no torch, no network — the planner never sees one (it takes
already-embedded vectors through an injected seam), which is what makes 100%
branch coverage of the gate/timing/dedupe logic honest rather than mocked.
"""

from __future__ import annotations

import math

import pytest
from media_studio.features import broll_plan as bp

# --------------------------------------------------------------------------- #
# fixtures: two orthogonal assets and segments aimed at one or the other
# --------------------------------------------------------------------------- #
ASSETS = [
    {"assetId": "a-dog", "path": "/lib/dog.mp4", "kind": "video", "durationSec": 12.0},
    {"assetId": "a-city", "path": "/lib/city.png", "kind": "image", "durationSec": None},
]
ASSET_VECS = [[1.0, 0.0], [0.0, 1.0]]

#: cos ~= 0.99 vs a-dog, ~= 0.14 vs a-city.
Q_DOG = [0.99, 0.14]
#: cos ~= 0.14 vs a-dog, ~= 0.99 vs a-city.
Q_CITY = [0.14, 0.99]
#: 45 degrees from both -> cos ~= 0.707 each (an exact tie).
Q_TIE = [1.0, 1.0]


def _seg(start: float, end: float, text: str = "") -> dict[str, object]:
    return {"start": start, "end": end, "text": text}


# --------------------------------------------------------------------------- #
# rank_assets — the INVERTED semantic_index.search (query=text, corpus=images)
# --------------------------------------------------------------------------- #
def test_rank_assets_orders_by_cosine_and_carries_asset_identity():
    hits = bp.rank_assets(Q_DOG, ASSET_VECS, ASSETS, top_k=2)
    assert [h["assetId"] for h in hits] == ["a-dog", "a-city"]
    assert hits[0]["path"] == "/lib/dog.mp4"
    assert hits[0]["kind"] == "video"
    assert hits[0]["score"] == pytest.approx(0.99, abs=1e-3)
    assert hits[1]["score"] == pytest.approx(0.14, abs=1e-3)


def test_rank_assets_truncates_to_top_k():
    assert len(bp.rank_assets(Q_CITY, ASSET_VECS, ASSETS, top_k=1)) == 1


def test_rank_assets_non_positive_top_k_is_empty():
    assert bp.rank_assets(Q_DOG, ASSET_VECS, ASSETS, top_k=0) == []


def test_rank_assets_ties_keep_source_order():
    # An exact tie must resolve to the LOWEST asset index (stable sort), so the
    # planner is reproducible run-to-run.
    hits = bp.rank_assets(Q_TIE, ASSET_VECS, ASSETS, top_k=2)
    assert [h["assetId"] for h in hits] == ["a-dog", "a-city"]
    assert hits[0]["score"] == pytest.approx(hits[1]["score"])


def test_rank_assets_dimension_mismatch_propagates():
    with pytest.raises(ValueError):
        bp.rank_assets([1.0, 0.0, 0.0], ASSET_VECS, ASSETS, top_k=1)


# --------------------------------------------------------------------------- #
# suggest — the per-segment threshold gate (the "no random static images" wall)
# --------------------------------------------------------------------------- #
def test_suggest_matches_each_segment_to_its_own_asset():
    segments = [_seg(0.0, 4.0, "a dog running"), _seg(10.0, 14.0, "the city skyline")]
    out = bp.suggest(segments, [Q_DOG, Q_CITY], ASSETS, ASSET_VECS, threshold=0.5)
    assert [s["assetId"] for s in out] == ["a-dog", "a-city"]
    assert [s["segmentIndex"] for s in out] == [0, 1]
    assert out[0]["start"] == 0.0 and out[0]["end"] == 4.0
    assert out[0]["layout"] == bp.DEFAULT_LAYOUT


def test_suggest_below_threshold_yields_NO_candidate():
    # The single most important behaviour: a semantically unrelated segment must
    # produce NOTHING, never a low-confidence filler insert.
    segments = [_seg(0.0, 4.0, "unrelated chatter")]
    out = bp.suggest(segments, [Q_DOG], ASSETS, ASSET_VECS, threshold=0.995)
    assert out == []


def test_suggest_threshold_is_inclusive_at_the_boundary():
    segments = [_seg(0.0, 4.0)]
    exact = bp.rank_assets(Q_DOG, ASSET_VECS, ASSETS, top_k=1)[0]["score"]
    assert bp.suggest(segments, [Q_DOG], ASSETS, ASSET_VECS, threshold=exact) != []
    assert bp.suggest(segments, [Q_DOG], ASSETS, ASSET_VECS, threshold=math.nextafter(exact, 2.0)) == []


def test_suggest_reason_names_the_matched_text_and_score():
    segments = [_seg(0.0, 4.0, "a dog running through a field of very tall grass")]
    out = bp.suggest(segments, [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)
    assert "0.99" in out[0]["reason"]
    assert "a dog running" in out[0]["reason"]
    assert len(out[0]["reason"]) <= bp.MAX_REASON_CHARS


def test_suggest_reason_on_an_empty_segment_text():
    out = bp.suggest([_seg(0.0, 4.0, "")], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)
    assert out[0]["reason"].startswith(bp.REASON_NO_TEXT)


def test_suggest_reason_truncates_a_long_segment_and_still_fits_the_cap():
    long_text = "a dog running " * 20
    out = bp.suggest([_seg(0.0, 4.0, long_text)], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)
    reason = out[0]["reason"]
    assert len(reason) <= bp.MAX_REASON_CHARS
    assert "…" in reason
    assert reason.endswith("(0.99)")


def test_suggest_reason_collapses_runaway_whitespace():
    out = bp.suggest([_seg(0.0, 4.0, "  a\n\tdog   running  ")], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)
    assert out[0]["reason"].startswith('"a dog running"')


def test_suggest_with_no_assets_is_empty():
    assert bp.suggest([_seg(0.0, 4.0)], [Q_DOG], [], [], threshold=0.0) == []


def test_suggest_honours_an_explicit_layout():
    out = bp.suggest([_seg(0.0, 4.0)], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5, layout="pip")
    assert out[0]["layout"] == "pip"


def test_suggest_rejects_an_unknown_layout():
    with pytest.raises(ValueError, match="layout"):
        bp.suggest([_seg(0.0, 4.0)], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5, layout="picture-in-picture")


def test_suggest_requires_one_vector_per_segment():
    with pytest.raises(ValueError, match="one vector per segment"):
        bp.suggest([_seg(0.0, 4.0), _seg(5.0, 9.0)], [Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)


def test_suggest_requires_one_vector_per_asset():
    with pytest.raises(ValueError, match="one vector per asset"):
        bp.suggest([_seg(0.0, 4.0)], [Q_DOG], ASSETS, ASSET_VECS[:1], threshold=0.5)


# --------------------------------------------------------------------------- #
# diversify — MMR across the accepted suggestions (reuses features/diversity)
# --------------------------------------------------------------------------- #
def test_diversify_drops_a_near_duplicate_asset():
    # Three segments all match a-dog; MMR with k=2 must not return a-dog twice
    # when a genuinely different asset is available.
    segments = [_seg(0.0, 4.0), _seg(10.0, 14.0), _seg(20.0, 24.0)]
    out = bp.suggest(segments, [Q_DOG, Q_DOG, Q_CITY], ASSETS, ASSET_VECS, threshold=0.5)
    kept = bp.diversify(out, ASSETS, ASSET_VECS, k=2)
    assert len(kept) == 2
    assert {s["assetId"] for s in kept} == {"a-dog", "a-city"}


def test_diversify_returns_chronological_order():
    segments = [_seg(20.0, 24.0), _seg(0.0, 4.0)]
    out = bp.suggest(segments, [Q_CITY, Q_DOG], ASSETS, ASSET_VECS, threshold=0.5)
    kept = bp.diversify(out, ASSETS, ASSET_VECS)
    assert [s["start"] for s in kept] == [0.0, 20.0]


def test_diversify_of_nothing_is_nothing():
    assert bp.diversify([], ASSETS, ASSET_VECS) == []


def test_diversify_supports_dpp():
    segments = [_seg(0.0, 4.0), _seg(10.0, 14.0)]
    out = bp.suggest(segments, [Q_DOG, Q_CITY], ASSETS, ASSET_VECS, threshold=0.5)
    assert len(bp.diversify(out, ASSETS, ASSET_VECS, method="dpp")) == 2


def test_diversify_on_an_unknown_asset_id_raises():
    orphan = [
        {
            "segmentIndex": 0,
            "start": 0.0,
            "end": 4.0,
            "assetId": "ghost",
            "path": "",
            "kind": "image",
            "score": 1.0,
            "reason": "",
            "layout": "cutaway",
        }
    ]
    with pytest.raises(KeyError, match="ghost"):
        bp.diversify(orphan, ASSETS, ASSET_VECS)


# --------------------------------------------------------------------------- #
# place — timing, coverage cap, min-gap, per-asset cooldown
# --------------------------------------------------------------------------- #
def _sugg(seg_index: int, start: float, end: float, asset_id: str = "a-dog", score: float = 0.9):
    return {
        "segmentIndex": seg_index,
        "start": start,
        "end": end,
        "assetId": asset_id,
        "path": "/lib/dog.mp4",
        "kind": "video",
        "score": score,
        "reason": "r",
        "layout": "cutaway",
    }


def test_place_clamps_duration_to_the_max():
    out = bp.place([_sugg(0, 0.0, 30.0)], total_sec=600.0, max_duration_sec=5.0)
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 5.0


def test_place_never_runs_past_the_segment_end():
    out = bp.place([_sugg(0, 10.0, 13.0)], total_sec=600.0, max_duration_sec=5.0)
    assert out[0]["end"] == 13.0


def test_place_drops_a_segment_shorter_than_the_minimum():
    assert bp.place([_sugg(0, 0.0, 0.9)], total_sec=600.0, min_duration_sec=1.5) == []


def test_place_enforces_the_coverage_cap():
    # Three 5 s inserts = 15 s; a 10% cap on a 100 s video allows only 10 s = two.
    sugg = [_sugg(0, 0.0, 5.0, score=0.9), _sugg(1, 20.0, 25.0, score=0.8), _sugg(2, 40.0, 45.0, score=0.7)]
    out = bp.place(sugg, total_sec=100.0, max_coverage_pct=10.0, min_gap_sec=0.0, cooldown_sec=0.0)
    assert len(out) == 2
    # The cap keeps the HIGHEST-scoring pair, not simply the first two by time.
    assert [s["score"] for s in out] == [0.9, 0.8]


def test_place_keeps_the_higher_score_when_the_cap_bites():
    sugg = [_sugg(0, 0.0, 5.0, score=0.5), _sugg(1, 20.0, 25.0, score=0.95)]
    out = bp.place(sugg, total_sec=100.0, max_coverage_pct=5.0, min_gap_sec=0.0, cooldown_sec=0.0)
    assert [s["score"] for s in out] == [0.95]


def test_place_enforces_the_minimum_gap():
    sugg = [_sugg(0, 0.0, 3.0, score=0.9), _sugg(1, 3.5, 6.5, score=0.8)]
    out = bp.place(sugg, total_sec=600.0, min_gap_sec=2.0, cooldown_sec=0.0)
    assert [s["start"] for s in out] == [0.0]


def test_place_allows_an_insert_exactly_one_gap_later():
    sugg = [_sugg(0, 0.0, 3.0, score=0.9), _sugg(1, 5.0, 8.0, score=0.8)]
    out = bp.place(sugg, total_sec=600.0, min_gap_sec=2.0, cooldown_sec=0.0)
    assert [s["start"] for s in out] == [0.0, 5.0]


def test_place_enforces_the_per_asset_cooldown():
    sugg = [_sugg(0, 0.0, 3.0, "a-dog", 0.9), _sugg(1, 20.0, 23.0, "a-dog", 0.8)]
    out = bp.place(sugg, total_sec=600.0, cooldown_sec=30.0, min_gap_sec=0.0)
    assert [s["start"] for s in out] == [0.0]


def test_cooldown_is_per_asset_not_global():
    sugg = [_sugg(0, 0.0, 3.0, "a-dog", 0.9), _sugg(1, 20.0, 23.0, "a-city", 0.8)]
    out = bp.place(sugg, total_sec=600.0, cooldown_sec=30.0, min_gap_sec=0.0)
    assert [s["assetId"] for s in out] == ["a-dog", "a-city"]


def test_place_snaps_the_start_to_a_nearby_shot_boundary():
    out = bp.place([_sugg(0, 10.2, 15.0)], total_sec=600.0, boundaries=[10.0, 300.0], snap_window_sec=0.5)
    assert out[0]["start"] == 10.0


def test_place_does_not_snap_to_a_far_boundary():
    out = bp.place([_sugg(0, 10.2, 15.0)], total_sec=600.0, boundaries=[3.0], snap_window_sec=0.5)
    assert out[0]["start"] == 10.2


def test_place_ignores_boundaries_when_none_are_supplied():
    out = bp.place([_sugg(0, 10.2, 15.0)], total_sec=600.0)
    assert out[0]["start"] == 10.2


def test_place_returns_chronological_order_even_when_scores_invert_it():
    sugg = [_sugg(0, 50.0, 54.0, "a-dog", 0.99), _sugg(1, 10.0, 14.0, "a-city", 0.60)]
    out = bp.place(sugg, total_sec=600.0, min_gap_sec=0.0, cooldown_sec=0.0)
    assert [s["start"] for s in out] == [10.0, 50.0]


def test_place_carries_a_source_offset_for_a_video_asset():
    out = bp.place([_sugg(0, 10.0, 14.0)], total_sec=600.0)
    assert out[0]["sourceStart"] == 0.0
    assert out[0]["duration"] == pytest.approx(4.0)


def test_place_of_nothing_is_nothing():
    assert bp.place([], total_sec=600.0) == []


def test_place_rejects_a_non_positive_total():
    with pytest.raises(ValueError, match="totalSec"):
        bp.place([_sugg(0, 0.0, 4.0)], total_sec=0.0)


# --------------------------------------------------------------------------- #
# plan — the composed pipeline (suggest -> diversify -> place)
# --------------------------------------------------------------------------- #
def test_plan_end_to_end_matches_dedupes_and_times():
    segments = [_seg(0.0, 6.0, "a dog running"), _seg(30.0, 36.0, "the city skyline")]
    out = bp.plan(
        segments,
        [Q_DOG, Q_CITY],
        ASSETS,
        ASSET_VECS,
        total_sec=120.0,
        threshold=0.5,
    )
    assert [i["assetId"] for i in out] == ["a-dog", "a-city"]
    assert all(i["end"] - i["start"] <= bp.DEFAULT_MAX_DURATION_SEC + 1e-9 for i in out)


def test_plan_returns_nothing_when_everything_is_below_threshold():
    segments = [_seg(0.0, 6.0, "unrelated")]
    assert bp.plan(segments, [Q_DOG], ASSETS, ASSET_VECS, total_sec=120.0, threshold=0.999) == []


def test_plan_coverage_of_an_empty_library():
    assert bp.plan([_seg(0.0, 6.0)], [Q_DOG], [], [], total_sec=120.0) == []
