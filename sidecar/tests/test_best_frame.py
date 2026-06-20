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


# --------------------------------------------------------------------------- #
# WU-C2: argmax_index — best-frame selection from per-frame scores
# --------------------------------------------------------------------------- #
def test_argmax_index_picks_highest_score() -> None:
    """AC(a): scores [0.1, 0.9, 0.3] select index 1."""
    assert best_frame.argmax_index([0.1, 0.9, 0.3]) == 1


def test_argmax_index_ties_keep_first() -> None:
    """A tie keeps the earliest frame (stable, deterministic)."""
    assert best_frame.argmax_index([0.5, 0.5, 0.2]) == 0


def test_argmax_index_empty_is_zero() -> None:
    """No scores -> 0 (the deterministic single-frame fallback, never raises)."""
    assert best_frame.argmax_index([]) == 0


def test_argmax_index_single() -> None:
    """One score -> its only index."""
    assert best_frame.argmax_index([0.42]) == 0


# --------------------------------------------------------------------------- #
# WU-C2: CloudFrameScorer — 1-frame-per-clip reuse of CloudVlmBackend
# --------------------------------------------------------------------------- #
def test_cloud_frame_scorer_treats_each_frame_as_a_one_frame_clip() -> None:
    """``score_frames`` ranks frames by wrapping each as a 1-frame clip stack.

    The injected backend records the ``frames_per_clip`` it received: each frame
    must arrive as its own single-frame stack so the cloud VLM scores frames the
    same way it scores clips.
    """
    seen: dict[str, object] = {}

    class FakeBackend:
        def rank_clips(self, frames_per_clip: object, prompt: str) -> list[float]:
            seen["frames_per_clip"] = frames_per_clip
            seen["prompt"] = prompt
            return [0.2, 0.8, 0.5]

    scorer = best_frame.CloudFrameScorer(FakeBackend())
    scores = scorer.score_frames(["fa", "fb", "fc"], "pick best")

    assert scores == [0.2, 0.8, 0.5]
    assert seen["prompt"] == "pick best"
    # each frame wrapped as its own 1-frame "clip" stack.
    assert list(seen["frames_per_clip"]) == [["fa"], ["fb"], ["fc"]]


def test_cloud_frame_scorer_no_frames_returns_empty() -> None:
    """No frames -> empty scores and the backend is never asked to rank."""

    class ExplodingBackend:
        def rank_clips(self, frames_per_clip: object, prompt: str) -> list[float]:
            raise AssertionError("backend must not be called for zero frames")

    scorer = best_frame.CloudFrameScorer(ExplodingBackend())
    assert scorer.score_frames([], "prompt") == []


# --------------------------------------------------------------------------- #
# WU-C2: pick_best_frame — score -> argmax -> write -> shape (fakes injected)
# --------------------------------------------------------------------------- #
def test_pick_best_frame_selects_argmax_and_writes_that_frame() -> None:
    """AC(a): scores [0.1,0.9,0.3] -> index 1; writer gets that frame + path."""
    writes: list[tuple[object, str]] = []

    def fake_scorer(frames: object, prompt: str) -> list[float]:
        return [0.1, 0.9, 0.3]

    def fake_writer(frame: object, path: str) -> None:
        writes.append((frame, path))

    result = best_frame.pick_best_frame(
        ["f0", "f1", "f2"],
        "which is best",
        frame_times=[0.0, 1.5, 3.0],
        thumbnail_path="/out/clip.jpg",
        scorer=fake_scorer,
        writer=fake_writer,
    )

    assert writes == [("f1", "/out/clip.jpg")]
    assert result == {"frameTimeSec": 1.5, "score": 0.9, "thumbnailPath": "/out/clip.jpg"}


def test_pick_best_frame_passes_prompt_to_scorer() -> None:
    """The built prompt is what the scorer receives (so the model gets the ask)."""
    seen: dict[str, object] = {}

    def fake_scorer(frames: object, prompt: str) -> list[float]:
        seen["frames"] = list(frames)
        seen["prompt"] = prompt
        return [0.7, 0.1]

    best_frame.pick_best_frame(
        ["a", "b"],
        best_frame.build_select_prompt(2),
        frame_times=[0.0, 2.0],
        thumbnail_path="/out/x.jpg",
        scorer=fake_scorer,
        writer=lambda _f, _p: None,
    )

    assert seen["frames"] == ["a", "b"]
    assert "thumbnail" in str(seen["prompt"]).lower()


def test_pick_best_frame_no_frames_writes_nothing_and_shapes_zero() -> None:
    """No frames -> no write, a zero-time/zero-score result with the path echoed."""
    writes: list[tuple[object, str]] = []

    def fake_scorer(frames: object, prompt: str) -> list[float]:
        return []

    result = best_frame.pick_best_frame(
        [],
        "prompt",
        frame_times=[],
        thumbnail_path="/out/empty.jpg",
        scorer=fake_scorer,
        writer=lambda f, p: writes.append((f, p)),
    )

    assert writes == []
    assert result == {"frameTimeSec": 0.0, "score": 0.0, "thumbnailPath": "/out/empty.jpg"}
