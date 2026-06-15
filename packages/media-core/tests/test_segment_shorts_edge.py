"""Edge-case coverage for segment scoring/selection helpers."""

from __future__ import annotations

import pytest

from media_core.segment import shorts
from media_core.segment.shorts import (
    HeuristicWeights,
    SegmentCandidate,
    _duration_bonus,
    _jaccard,
    _to_weights,
    equal_splits,
    score_segments_heuristic,
    score_segments_llm,
    select_top,
    sliding_window,
)


def test_to_weights_passthrough_instance():
    weights = HeuristicWeights(base_score=0.9)
    assert _to_weights(weights) is weights


def test_to_weights_from_dict_applies_known_keys_and_skips_bad():
    raw = {
        "base_score": "0.5",  # coerced to float
        "keyword_density": "not-a-number",  # invalid -> skipped, keeps default
        "unknown_key": 99,  # ignored
    }
    cfg = _to_weights(raw)
    assert cfg.base_score == pytest.approx(0.5)
    assert cfg.keyword_density == HeuristicWeights().keyword_density


def test_to_weights_non_dict_non_instance_returns_default():
    assert _to_weights(None) == HeuristicWeights()
    assert _to_weights("nope") == HeuristicWeights()


def test_jaccard_empty_inputs_zero():
    assert _jaccard(set(), {"a"}) == 0.0
    assert _jaccard({"a"}, set()) == 0.0


def test_jaccard_overlap_ratio():
    assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_equal_splits_invalid_inputs_empty():
    assert equal_splits(0.0, 4.0) == []
    assert equal_splits(10.0, 0.0) == []


def test_sliding_window_invalid_inputs_empty():
    assert sliding_window(0.0, 2.0, 1.0) == []
    assert sliding_window(5.0, 0.0, 1.0) == []
    assert sliding_window(5.0, 2.0, 0.0) == []


def test_select_top_zero_max_segments_returns_empty():
    cands = [SegmentCandidate(start=0.0, end=5.0, score=1.0)]
    assert select_top(cands, max_segments=0, min_duration=1.0, max_duration=10.0) == []


def test_select_top_no_candidates_in_bounds_returns_empty():
    # All candidates too short -> filtered out -> empty.
    cands = [SegmentCandidate(start=0.0, end=0.1, score=1.0)]
    assert select_top(cands, max_segments=2, min_duration=1.0, max_duration=10.0) == []


def test_duration_bonus_inside_and_outside_sweet_spot():
    # Inside 15-60s window -> full bonus.
    assert _duration_bonus(30.0) == 1.0
    # Outside the window -> decays below 1.0 (the `return _clamp(...)` branch).
    assert _duration_bonus(120.0) < 1.0
    assert _duration_bonus(5.0) < 1.0


def test_score_segments_heuristic_handles_short_clip_outside_window():
    cands = [SegmentCandidate(start=0.0, end=3.0, snippet="quick clip without keywords")]
    out = score_segments_heuristic(cands)
    assert isinstance(out[0].score, float)


def test_score_segments_llm_requires_client():
    with pytest.raises(RuntimeError, match="LLM client not provided"):
        score_segments_llm("transcript", [], prompt="p", model="m", client=None)


def test_parse_llm_score_map_invalid_json_returns_empty():
    assert shorts._parse_llm_score_map("{not json") == {}


def test_parse_llm_score_map_non_list_returns_empty():
    # Valid JSON but not a list -> empty map (the `isinstance(scores, list)` is False).
    assert shorts._parse_llm_score_map('{"start": 0}') == {}


def test_parse_llm_score_map_skips_malformed_entries():
    content = '[{"start": 0.0, "end": 1.0, "score": 0.5}, {"missing": "fields"}]'
    score_map = shorts._parse_llm_score_map(content)
    assert score_map == {(0.0, 1.0): 0.5}


def test_score_segments_llm_leaves_unmatched_candidate_untouched():
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages):  # noqa: ARG004
                    # Score only the first candidate; the second has no match.
                    content = '[{"start": 0.0, "end": 5.0, "score": 0.9}]'

                    class Choice:
                        message = type("m", (), {"content": content})

                    return type("Resp", (), {"choices": [Choice()]})

    cands = [
        SegmentCandidate(start=0.0, end=5.0, score=0.0),
        SegmentCandidate(start=6.0, end=9.0, score=0.0),
    ]
    out = score_segments_llm(
        transcript="", candidates=cands, prompt="p", model="m", client=FakeClient()
    )
    assert out[0].score == pytest.approx(0.9)
    # Second candidate's key was not in the score map -> stays at its original score.
    assert out[1].score == 0.0
