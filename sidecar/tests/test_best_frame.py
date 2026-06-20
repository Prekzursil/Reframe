"""Unit tests for the PURE best-frame core (WU-C1).

Mirrors the ``smolvlm2`` re-rank test idiom: prompt-build + forgiving reply
parse + index/score shaping, fully covered with NO heavy import (no cv2, no
model — frames + replies are injected). The vision/scorer seam lands in WU-C2.
"""

from __future__ import annotations

import pytest
from media_studio.features import best_frame


# --------------------------------------------------------------------------- #
# build_select_prompt
# --------------------------------------------------------------------------- #
def test_build_select_prompt_mentions_count_and_is_a_question() -> None:
    """The prompt names the frame count and asks for the best thumbnail index."""
    prompt = best_frame.build_select_prompt(8)
    assert isinstance(prompt, str)
    assert "8" in prompt
    # One multimodal instruction: which numbered frame is the best thumbnail + why.
    lowered = prompt.lower()
    assert "thumbnail" in lowered
    assert "best" in lowered
    assert "why" in lowered


def test_build_select_prompt_uses_one_based_numbering_hint() -> None:
    """The instruction refers to numbered frames so replies are 1-based."""
    prompt = best_frame.build_select_prompt(3)
    assert "3" in prompt
    assert "frame" in prompt.lower()


def test_build_select_prompt_single_frame() -> None:
    """``n == 1`` still yields a valid, count-bearing instruction."""
    prompt = best_frame.build_select_prompt(1)
    assert "1" in prompt
    assert "thumbnail" in prompt.lower()


# --------------------------------------------------------------------------- #
# parse_best_index — forgiving, always in range(n)
# --------------------------------------------------------------------------- #
def test_parse_best_index_one_based_reply_maps_to_zero_based() -> None:
    """AC(a): "the best is frame 4" with n=8 -> 0-based index 3."""
    assert best_frame.parse_best_index("the best is frame 4", 8) == 3


def test_parse_best_index_simple_frame_three() -> None:
    """ "frame 3" -> 2 (1-based reply, 0-based result)."""
    assert best_frame.parse_best_index("frame 3", 8) == 2


def test_parse_best_index_garbage_falls_back_to_zero() -> None:
    """AC(a): no number found -> deterministic fallback index 0."""
    assert best_frame.parse_best_index("garbage", 8) == 0


def test_parse_best_index_empty_reply_falls_back_to_zero() -> None:
    """An empty reply is the no-number case -> 0."""
    assert best_frame.parse_best_index("", 8) == 0


def test_parse_best_index_takes_first_number_when_multiple() -> None:
    """Multiple numbers: the first declared index wins."""
    # 1-based "2" then "5" -> first is 2 -> 0-based 1.
    assert best_frame.parse_best_index("I think 2, maybe 5", 8) == 1


def test_parse_best_index_clamps_out_of_range_high() -> None:
    """A 1-based number above ``n`` clamps into ``range(n)`` (last index)."""
    # "frame 99" with n=8 -> clamp 0-based 98 to 7.
    assert best_frame.parse_best_index("frame 99", 8) == 7


def test_parse_best_index_clamps_zero_reply() -> None:
    """A 1-based "0" (-> -1) clamps up to 0."""
    assert best_frame.parse_best_index("frame 0", 8) == 0


def test_parse_best_index_single_frame_always_zero() -> None:
    """With ``n == 1`` every reply resolves to the only index, 0."""
    assert best_frame.parse_best_index("frame 1", 1) == 0
    assert best_frame.parse_best_index("frame 7", 1) == 0
    assert best_frame.parse_best_index("nope", 1) == 0


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "garbage",
        "frame 0",
        "frame 1",
        "frame 4",
        "frame 99",
        "-3 then 100",
        "the 2nd one (index 2) looks great because 1",
        "00007",
    ],
)
@pytest.mark.parametrize("n", [1, 2, 5, 8])
def test_parse_best_index_property_always_in_range(reply: str, n: int) -> None:
    """AC(b): the result is ALWAYS a valid index into ``range(n)``."""
    idx = best_frame.parse_best_index(reply, n)
    assert 0 <= idx < n


# --------------------------------------------------------------------------- #
# shape_result — index -> {frameTimeSec, score}
# --------------------------------------------------------------------------- #
def test_shape_result_maps_index_to_time_and_score() -> None:
    """AC(c): the chosen index selects the matching ``frameTimeSec``."""
    out = best_frame.shape_result(1, frame_times=[0.0, 1.5, 3.0], scores=[0.1, 0.9, 0.3])
    assert out == {"frameTimeSec": 1.5, "score": 0.9}


def test_shape_result_first_index() -> None:
    """Index 0 maps to the first time/score."""
    out = best_frame.shape_result(0, frame_times=[2.25, 9.0], scores=[0.8, 0.2])
    assert out["frameTimeSec"] == 2.25
    assert out["score"] == 0.8


def test_shape_result_clamps_score_into_unit_range() -> None:
    """Scores are clamped to [0, 1] so the UI never sees an out-of-range value."""
    out = best_frame.shape_result(0, frame_times=[0.0], scores=[1.7])
    assert out["score"] == 1.0
    out_low = best_frame.shape_result(0, frame_times=[0.0], scores=[-0.4])
    assert out_low["score"] == 0.0


def test_shape_result_missing_score_defaults_to_zero() -> None:
    """When no score aligns to the index the shaped score is 0.0 (not a raise)."""
    out = best_frame.shape_result(2, frame_times=[0.0, 1.0, 2.0], scores=[0.5])
    assert out == {"frameTimeSec": 2.0, "score": 0.0}


def test_shape_result_out_of_range_index_clamps_time() -> None:
    """A defensively out-of-range index clamps to the last available time."""
    out = best_frame.shape_result(9, frame_times=[0.0, 1.0], scores=[0.2, 0.4])
    assert out["frameTimeSec"] == 1.0
    assert out["score"] == 0.0


def test_shape_result_empty_times_yields_zero_time() -> None:
    """No frames -> a zero time, zero score result rather than an IndexError."""
    out = best_frame.shape_result(0, frame_times=[], scores=[])
    assert out == {"frameTimeSec": 0.0, "score": 0.0}
