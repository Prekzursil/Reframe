"""Unit tests for the unified tri-modal fusion engine (``features.scorer``).

Pure-logic only: NO heavy-ML imports. Every :class:`SignalTrack` is hand-built
(present/absent mixes), the ranker/diversity/quality seams are the real pure
functions, and the VLM seam is a fake. Asserts the degrade-by-re-normalization
rule, the silent-video curve + peak-pick, the weighted-mean math, the duration
clamp inherited from ``to_candidates``, and the score-fusion blend.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from media_studio.features import scorer
from media_studio.features.motion import Signal, SignalTrack
from media_studio.features.ranker import SIGNAL_FEATURES

# ---------------------------------------------------------------------------
# Track builders (hand-built — the canonical Wave-1 fake-injection pattern)
# ---------------------------------------------------------------------------


def _track(channel: str, values: list[tuple[float, float, float]], *, present: bool = True) -> SignalTrack:
    """Build a SignalTrack from ``[(start, end, value), ...]`` tuples."""
    sigs = tuple(Signal(channel=channel, start=s, end=e, value=v) for s, e, v in values)
    return SignalTrack(channel=channel, signals=sigs, present=present)


def _grid_track(channel: str, per_window: list[float], *, present: bool = True) -> SignalTrack:
    """A track with one 1-second window per value (the shared grid)."""
    return _track(channel, [(float(i), float(i + 1), v) for i, v in enumerate(per_window)], present=present)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_window_sec_and_weights_cover_the_frozen_vocabulary():
    assert scorer.WINDOW_SEC == 1.0
    # Every ranker signal feature has a blend weight (the frozen vocabulary).
    for channel in SIGNAL_FEATURES:
        assert channel in scorer.DEFAULT_WEIGHTS
    # sceneCut is a boundary signal, NOT a blend channel.
    assert "sceneCut" not in scorer.DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# present_channels — the degrade gate
# ---------------------------------------------------------------------------


def test_present_channels_orders_by_vocabulary_and_drops_absent():
    tracks = {
        "saliency": _grid_track("saliency", [0.5], present=True),
        "motion": _grid_track("motion", [0.5], present=True),
        "music": _grid_track("music", [0.5], present=False),  # present=False -> dropped
    }
    # Returned in DEFAULT_WEIGHTS order (motion before saliency), music dropped.
    assert scorer.present_channels(tracks) == ("motion", "saliency")


def test_present_channels_empty_when_no_tracks():
    assert scorer.present_channels({}) == ()


# ---------------------------------------------------------------------------
# pool_signals_for_window — per-channel mean + overlap + omission
# ---------------------------------------------------------------------------


def test_pool_takes_mean_of_overlapping_signals():
    tracks = {"motion": _track("motion", [(0.0, 1.0, 0.4), (1.0, 2.0, 0.8)])}
    # Window [0,2) overlaps both -> mean 0.6.
    assert scorer.pool_signals_for_window(tracks, 0.0, 2.0) == {"motion": pytest.approx(0.6)}


def test_pool_omits_channel_with_no_overlapping_signal():
    tracks = {"motion": _track("motion", [(10.0, 11.0, 0.9)])}
    # Window [0,2) overlaps nothing -> channel omitted (NOT zeroed).
    assert scorer.pool_signals_for_window(tracks, 0.0, 2.0) == {}


def test_pool_omits_absent_track():
    tracks = {"music": _grid_track("music", [0.9], present=False)}
    assert scorer.pool_signals_for_window(tracks, 0.0, 1.0) == {}


def test_pool_clamps_out_of_range_signal_values():
    tracks = {"motion": _track("motion", [(0.0, 1.0, 2.0)])}  # >1 -> clamped to 1.0
    assert scorer.pool_signals_for_window(tracks, 0.0, 1.0) == {"motion": pytest.approx(1.0)}


def test_pool_instantaneous_signal_overlaps_when_inside_window():
    # An instantaneous signal (start == end) overlaps when it sits inside [start,end).
    tracks = {"loudness": _track("loudness", [(0.5, 0.5, 0.7)])}
    assert scorer.pool_signals_for_window(tracks, 0.0, 1.0) == {"loudness": pytest.approx(0.7)}
    # ...and is omitted when it falls outside the window.
    assert scorer.pool_signals_for_window(tracks, 2.0, 3.0) == {}


# ---------------------------------------------------------------------------
# clip_signal_map — restricted to ranker feature columns (no sceneCut)
# ---------------------------------------------------------------------------


def test_clip_signal_map_keeps_only_ranker_feature_channels():
    tracks = {
        "motion": _track("motion", [(0.0, 1.0, 0.5)]),
        "sceneCut": _track("sceneCut", [(0.0, 1.0, 1.0)]),  # boundary signal -> excluded
    }
    sig = scorer.clip_signal_map(tracks, 0.0, 1.0)
    assert sig == {"motion": pytest.approx(0.5)}
    assert "sceneCut" not in sig


# ---------------------------------------------------------------------------
# window_interest_curve — degrade re-normalization (the headline rule)
# ---------------------------------------------------------------------------


def test_curve_weighted_mean_over_present_channels():
    tracks = {
        "motion": _grid_track("motion", [1.0, 0.0]),  # weight 0.8
        "saliency": _grid_track("saliency", [0.0, 1.0]),  # weight 1.2
    }
    curve = scorer.window_interest_curve(tracks, 2.0)
    # window0: (0.8*1 + 1.2*0)/(0.8+1.2) = 0.4 ; window1: (0.8*0 + 1.2*1)/2.0 = 0.6
    assert curve == [pytest.approx(0.4), pytest.approx(0.6)]


def test_curve_renormalizes_when_a_channel_is_absent():
    # Only motion present: a silent clip is judged on the visual weight alone, so
    # the denominator drops the missing channels' weights -> the motion value IS
    # the curve (re-normalized to its own weight), never diluted by zeros.
    tracks = {"motion": _grid_track("motion", [0.5, 0.9])}
    assert scorer.window_interest_curve(tracks, 2.0) == [pytest.approx(0.5), pytest.approx(0.9)]


def test_curve_zero_when_no_present_channel_in_window():
    tracks = {"motion": _track("motion", [(10.0, 11.0, 1.0)])}  # nothing in [0,2)
    assert scorer.window_interest_curve(tracks, 2.0) == [0.0, 0.0]


def test_curve_empty_for_nonpositive_duration():
    assert scorer.window_interest_curve({}, 0.0) == []


def test_curve_empty_for_nonpositive_window_sec():
    tracks = {"motion": _grid_track("motion", [0.5])}
    assert scorer.window_interest_curve(tracks, 5.0, window_sec=0.0) == []


def test_curve_custom_weights_override_default():
    tracks = {
        "motion": _grid_track("motion", [1.0]),
        "saliency": _grid_track("saliency", [0.0]),
    }
    # Equal weights -> simple mean 0.5.
    curve = scorer.window_interest_curve(tracks, 1.0, weights={"motion": 1.0, "saliency": 1.0})
    assert curve == [pytest.approx(0.5)]


# ---------------------------------------------------------------------------
# candidates_from_curve — the silent-video peak-pick path
# ---------------------------------------------------------------------------


def test_candidates_from_curve_peak_picks_highest_window():
    # A 200s source so the min-duration clamp (>=20s) actually applies; peaks at
    # window index 30.
    tracks = {"motion": _grid_track("motion", [0.0] * 200)}
    curve = list(scorer.window_interest_curve(tracks, 200.0))
    curve[30] = 0.9
    cands = scorer.candidates_from_curve(curve, 200.0, {"count": 1}, tracks)
    assert len(cands) == 1
    c = cands[0]
    assert c["why"] == "visual interest peak"
    assert c["hook"] == ""
    # Duration clamp inherited from to_candidates (min 20s) on a long-enough source.
    assert c["durationSec"] >= 20.0
    assert c["start"] == pytest.approx(30.0)
    # signals re-pooled over the final span.
    assert "motion" in c["signals"]


def test_candidates_from_curve_clamps_to_min_max_window():
    tracks = {"motion": _grid_track("motion", [0.9] * 200)}
    curve = scorer.window_interest_curve(tracks, 200.0)
    cands = scorer.candidates_from_curve(curve, 200.0, {"count": 1, "minSec": 30, "maxSec": 50}, tracks)
    assert 30.0 <= cands[0]["durationSec"] <= 50.0


def test_candidates_from_curve_clamps_clip_to_short_source_duration():
    # On a SHORT source the clip cannot reach min-duration; to_candidates pulls it
    # back to the source length (an honest cap, not a fabricated 20s clip).
    tracks = {"motion": _grid_track("motion", [0.1, 0.9, 0.2])}
    curve = scorer.window_interest_curve(tracks, 3.0)
    cands = scorer.candidates_from_curve(curve, 3.0, {"count": 1}, tracks)
    assert cands[0]["end"] <= 3.0


def test_candidates_from_curve_respects_count_and_non_overlap():
    # A long curve with several peaks: count=2 picks the two best, greedily
    # skipping any whose min-duration span overlaps an already-chosen clip.
    tracks = {"motion": _grid_track("motion", [0.0] * 200)}
    curve = list(scorer.window_interest_curve(tracks, 200.0))
    curve[10] = 0.9  # best
    curve[100] = 0.8  # third
    curve[101] = 0.85  # second-best, but overlaps the eventual 100/101 window
    cands = scorer.candidates_from_curve(curve, 200.0, {"count": 2}, tracks)
    assert len(cands) == 2
    starts = sorted(c["start"] for c in cands)
    # idx10 (0.9) then idx101 (0.85); idx100 overlaps idx101's 20s span -> dropped.
    assert starts == [pytest.approx(10.0), pytest.approx(101.0)]


def test_candidates_from_curve_empty_curve_returns_empty():
    assert scorer.candidates_from_curve([], 0.0, {"count": 5}, {}) == []


def test_candidates_from_curve_accepts_none_controls():
    tracks = {"motion": _grid_track("motion", [0.5] * 60)}
    curve = scorer.window_interest_curve(tracks, 60.0)
    cands = scorer.candidates_from_curve(curve, 60.0, None, tracks)
    assert len(cands) >= 1


def test_candidates_from_curve_zero_duration_uses_window_index_span():
    # duration 0 but a non-empty curve (degenerate): the per-window span still
    # advances by window index. Adjacent windows overlap each other's 20s spans,
    # so only the first non-overlapping peak survives.
    tracks: dict[str, Any] = {}
    cands = scorer.candidates_from_curve([0.5, 0.4], 0.0, {"count": 2}, tracks)
    assert len(cands) == 1
    assert cands[0]["signals"] == {}


# ---------------------------------------------------------------------------
# fuse_score — the LLM/signal blend
# ---------------------------------------------------------------------------


def test_fuse_score_blends_legacy_and_boost():
    # alpha 0.5: half legacy(80/100=0.8) + half boost(0.4) = 0.6.
    assert scorer.fuse_score(80, 0.4, 0.5) == pytest.approx(0.6)


def test_fuse_score_alpha_zero_is_pure_legacy():
    assert scorer.fuse_score(90, 0.0, 0.0) == pytest.approx(0.9)


def test_fuse_score_alpha_one_is_pure_signal():
    assert scorer.fuse_score(10, 0.7, 1.0) == pytest.approx(0.7)


def test_fuse_score_clamps_alpha_and_inputs():
    # alpha > 1 clamps to 1 (pure signal); boost > 1 clamps to 1.
    assert scorer.fuse_score(0, 2.0, 5.0) == pytest.approx(1.0)
    # legacy > 100 clamps to 1.0 unit at alpha 0.
    assert scorer.fuse_score(150, 0.0, 0.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# signal_boost_for_clip
# ---------------------------------------------------------------------------


def test_signal_boost_for_clip_matches_present_weighted_mean():
    tracks = {"motion": _track("motion", [(0.0, 2.0, 0.5)])}
    assert scorer.signal_boost_for_clip(tracks, 0.0, 2.0) == pytest.approx(0.5)


def test_signal_boost_zero_when_no_signal():
    assert scorer.signal_boost_for_clip({}, 0.0, 2.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# fallback_embeddings — the zero-model diversity matrix
# ---------------------------------------------------------------------------


def test_fallback_embeddings_builds_signal_vector_rows():
    tracks = {"motion": _track("motion", [(0.0, 5.0, 0.5)])}
    cands = [{"start": 0.0, "end": 5.0}, {"start": 0.0, "end": 5.0}]
    embeds = scorer.fallback_embeddings(cands, tracks)
    assert embeds.shape == (2, len(SIGNAL_FEATURES))
    # The motion column carries 0.5; the others are zeroed (absent channels).
    motion_col = SIGNAL_FEATURES.index("motion")
    assert embeds[0, motion_col] == pytest.approx(0.5)


def test_fallback_embeddings_empty_candidates_returns_empty_matrix():
    embeds = scorer.fallback_embeddings([], {})
    assert embeds.shape == (0, len(SIGNAL_FEATURES))
    assert isinstance(embeds, np.ndarray)
