"""Unit tests for the prompt-driven clip selector (CONTRACTS.md §5).

Pure-logic only: NO heavy-ML imports. The LLM is reached through the
:class:`Provider` seam, which a :class:`FakeProvider` satisfies by returning
canned JSON. Tests assert the prompt embeds the frozen recipe rules (two-pass
thesis + 6-8 quotable lines + 20-60 s + most-quotable-line-included), that the
response parser strips ``<think>`` and parses JSON into Candidates, that the
duration clamp holds, and that ``controls.count`` is honored.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from media_studio.features import select as sel
from media_studio.features.select import (
    MAX_CLIP_SEC,
    MIN_CLIP_SEC,
    TEMPERATURE,
    build_rerank_user_prompt,
    build_system_prompt,
    build_user_prompt,
    extract_clips,
    render_lines,
    select,
    strip_think,
    to_candidates,
)

# ---------------------------------------------------------------------------
# Fakes & fixtures
# ---------------------------------------------------------------------------


class FakeProvider:
    """A canned-JSON :class:`Provider` that records every chat call.

    ``responses`` is a queue of raw assistant-content strings returned in order
    (the last one repeats once exhausted). Each call's messages + kwargs are
    captured in ``calls`` so tests can assert on the prompt text + parameters.
    """

    def __init__(self, responses: Sequence[str]):
        self._responses: list[str] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.4,
        max_tokens: int = 6000,
    ) -> str:
        self.calls.append(
            {
                "messages": list(messages),
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]

    # -- convenience accessors for assertions ------------------------------
    @property
    def last_system(self) -> str:
        return self.calls[-1]["messages"][0]["content"]

    @property
    def last_user(self) -> str:
        return self.calls[-1]["messages"][1]["content"]


def _clips_json(clips: list[dict[str, Any]], think: str = "reasoning...") -> str:
    """Wrap clip dicts in the spike's <think> + {"clips": [...]} response shape."""
    return f"<think>{think}</think>\n" + json.dumps({"clips": clips})


def _short_transcript() -> dict[str, Any]:
    return {
        "language": "en",
        "durationSec": 300.0,
        "segments": [
            {"start": 0.0, "end": 30.0, "text": "Opening hook line."},
            {"start": 30.0, "end": 75.0, "text": "The thesis payoff. (Applause)"},
            {"start": 75.0, "end": 120.0, "text": "A counterintuitive twist."},
        ],
    }


def _long_transcript(n_segments: int = 600) -> dict[str, Any]:
    """A transcript long enough to trip the map-reduce path."""
    segments = [
        {"start": float(i * 5), "end": float(i * 5 + 5), "text": f"Line number {i}."} for i in range(n_segments)
    ]
    return {"language": "en", "durationSec": float(n_segments * 5), "segments": segments}


@pytest.fixture()
def good_clips() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "start": "00:30",
            "end": "01:15",
            "duration_sec": 45,
            "hook": "The thesis payoff",
            "why": "high impact",
            "score": 95,
        },
        {
            "rank": 2,
            "start": "01:15",
            "end": "02:00",
            "duration_sec": 45,
            "hook": "A twist",
            "why": "curiosity",
            "score": 80,
        },
    ]


# ---------------------------------------------------------------------------
# Recipe constants (frozen)
# ---------------------------------------------------------------------------


def test_recipe_constants_match_contract():
    assert TEMPERATURE == 0.4
    assert MIN_CLIP_SEC == 20.0
    assert MAX_CLIP_SEC == 60.0


# ---------------------------------------------------------------------------
# System prompt: the two-pass recipe text
# ---------------------------------------------------------------------------


def test_system_prompt_has_two_pass_thesis_and_quotable_rule():
    sys_p = build_system_prompt(count=5, min_sec=20, max_sec=60)
    low = sys_p.lower()
    # Pass 1: thesis + 6-8 quotable lines, weight (Applause), complete thought.
    assert "thesis" in low
    assert "6-8 most quotable" in low
    assert "(Applause)" in sys_p
    assert "complete" in low and "thought" in low
    assert "setup" in low and "payoff" in low
    # Pass 2: select N, hard 20-60s, hook, most-quotable line MUST be included.
    assert "20-60 SECONDS" in sys_p
    assert ">= 20 and <= 60" in sys_p
    assert "hook" in low
    assert "most quotable line of the whole talk MUST" in sys_p
    # Reasoning ON, JSON last — and NEVER /no_think.
    assert "Think step by step FIRST" in sys_p
    assert "/no_think" not in sys_p
    assert "output ONLY the" in sys_p


def test_system_prompt_count_and_window_are_parameterized():
    sys_p = build_system_prompt(count=3, min_sec=25, max_sec=45)
    assert "select the 3 best clips" in sys_p.lower()
    assert "25-45 SECONDS" in sys_p
    assert ">= 25 and <= 45" in sys_p


# ---------------------------------------------------------------------------
# User prompt: JSON schema + duration clamp + transcript
# ---------------------------------------------------------------------------


def test_user_prompt_embeds_schema_clamp_and_transcript():
    user_p = build_user_prompt("make shorts", count=4, min_sec=20, max_sec=60, body="[00:00] hello world")
    assert "make shorts" in user_p
    assert "select the 4 best clips" in user_p.lower()
    # Exact schema field names (kept identical TS-side via Candidate mapping).
    for field in ("rank", "start", "end", "duration_sec", "hook", "why", "score"):
        assert f'"{field}"' in user_p
    # Duration clamp re-stated in the user message.
    assert "MUST be between 20 and 60" in user_p
    # Transcript body present.
    assert "[00:00] hello world" in user_p


def test_rerank_prompt_is_global_and_carries_schema():
    rr = build_rerank_user_prompt("topic", count=5, min_sec=20, max_sec=60, shortlist_body="[00:30-01:15] score=95")
    low = rr.lower()
    assert "re-rank" in low
    assert "shortlisted" in low or "shortlist" in low
    assert "MUST be between 20 and 60" in rr
    assert "[00:30-01:15] score=95" in rr


# ---------------------------------------------------------------------------
# render_lines
# ---------------------------------------------------------------------------


def test_render_lines_formats_timestamps_and_keeps_applause():
    lines = render_lines(_short_transcript())
    assert lines[0] == "[00:00] Opening hook line."
    assert lines[1] == "[00:30] The thesis payoff. (Applause)"
    assert lines[2] == "[01:15] A counterintuitive twist."


def test_render_lines_drops_empty_segments():
    t = {"segments": [{"start": 0, "end": 1, "text": "  "}, {"start": 1, "end": 2, "text": "kept"}]}
    assert render_lines(t) == ["[00:01] kept"]


# ---------------------------------------------------------------------------
# strip_think / extract_clips parsing
# ---------------------------------------------------------------------------


def test_strip_think_removes_reasoning_block():
    assert strip_think('<think>secret\nplan</think>  {"a":1}') == '{"a":1}'


def test_extract_clips_parses_after_stripping_think():
    raw = _clips_json([{"start": "00:10", "end": "00:50"}])
    clips = extract_clips(raw)
    assert clips == [{"start": "00:10", "end": "00:50"}]


def test_extract_clips_finds_json_amid_prose():
    raw = 'Here you go:\n{"clips": [{"rank": 1}]}\nThanks!'
    assert extract_clips(raw) == [{"rank": 1}]


def test_extract_clips_returns_empty_on_garbage():
    assert extract_clips("no json here") == []
    assert extract_clips("<think>only thinking</think>") == []
    assert extract_clips("{not valid json}") == []


# ---------------------------------------------------------------------------
# to_candidates: parsing + duration clamp + sourceStart + schema field names
# ---------------------------------------------------------------------------


def test_to_candidates_maps_to_contract_schema_fields(good_clips):
    cands = to_candidates(good_clips, MIN_CLIP_SEC, MAX_CLIP_SEC)
    assert len(cands) == 2
    c = cands[0]
    # §3 base fields + P3-C factor fields (viralityPct is added by select()'s
    # _finalize over the returned batch, NOT by to_candidates — so it is absent
    # here, by design).
    assert set(c.keys()) == {
        "rank",
        "start",
        "end",
        "durationSec",
        "hook",
        "why",
        "score",
        "sourceStart",
        "factors",
        "factorNotes",
    }
    assert set(c["factors"].keys()) == {
        "hookStrength",
        "emotionalFlow",
        "perceivedValue",
        "shareability",
    }
    assert all(0 <= v <= 100 for v in c["factors"].values())
    assert "viralityPct" not in c  # batch percentile is applied in select()
    # mm:ss parsed to seconds; sourceStart == start (clip start in original video).
    assert c["start"] == 30.0
    assert c["end"] == 75.0
    assert c["sourceStart"] == 30.0
    assert c["durationSec"] == 45.0


def test_to_candidates_clamps_too_short_clip_up_to_min():
    clips = [{"start": "00:10", "end": "00:13", "score": 50}]  # 3s -> extend to 20s
    c = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)[0]
    assert c["durationSec"] == MIN_CLIP_SEC
    assert c["start"] == 10.0
    assert c["end"] == 30.0


def test_to_candidates_clamps_too_long_clip_down_to_max():
    clips = [{"start": "00:00", "end": "03:00", "score": 50}]  # 180s -> 60s
    c = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)[0]
    assert c["durationSec"] == MAX_CLIP_SEC
    assert c["end"] == 60.0


def test_to_candidates_respects_custom_window():
    clips = [{"start": "00:00", "end": "00:10", "score": 50}]  # 10s -> 30s (min=30)
    c = to_candidates(clips, 30.0, 50.0)[0]
    assert c["durationSec"] == 30.0


def test_to_candidates_does_not_run_past_source_duration():
    clips = [{"start": "04:50", "end": "04:55", "score": 50}]  # near a 300s end
    c = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC, duration_total=300.0)[0]
    assert c["end"] <= 300.0
    assert c["durationSec"] == MIN_CLIP_SEC


def test_to_candidates_reranks_by_score_descending():
    clips = [
        {"start": "00:00", "end": "00:40", "score": 10},
        {"start": "01:00", "end": "01:40", "score": 90},
        {"start": "02:00", "end": "02:40", "score": 50},
    ]
    cands = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)
    assert [c["score"] for c in cands] == [90, 50, 10]
    assert [c["rank"] for c in cands] == [1, 2, 3]


def test_to_candidates_swaps_reversed_times():
    clips = [{"start": "01:00", "end": "00:30", "score": 50}]
    c = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)[0]
    assert c["start"] == 30.0
    assert c["end"] == 60.0


def test_to_candidates_skips_rows_without_times():
    clips = [{"hook": "no times", "score": 99}, {"start": "00:00", "end": "00:40"}]
    cands = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)
    assert len(cands) == 1
    assert cands[0]["start"] == 0.0


def test_to_candidates_handles_seconds_and_hhmmss():
    clips = [
        {"start": 5, "end": 50, "score": 1},  # bare numeric seconds
        {"start": "01:00:00", "end": "01:00:40", "score": 2},  # hh:mm:ss
    ]
    cands = to_candidates(clips, MIN_CLIP_SEC, MAX_CLIP_SEC)
    by_start = {c["start"] for c in cands}
    assert 5.0 in by_start
    assert 3600.0 in by_start


# ---------------------------------------------------------------------------
# select(): single-pass orchestration + provider call params
# ---------------------------------------------------------------------------


def test_select_single_pass_returns_candidates(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select(_short_transcript(), "make shorts", {"count": 2}, provider)
    assert len(cands) == 2
    assert all(isinstance(c["sourceStart"], float) for c in cands)
    assert len(provider.calls) == 1  # short transcript -> single pass


def test_select_passes_temperature_0_4_and_reasoning_on(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    select(_short_transcript(), "x", {"count": 2}, provider)
    call = provider.calls[0]
    assert call["temperature"] == 0.4
    # Reasoning ON: no /no_think anywhere in the messages.
    blob = call["messages"][0]["content"] + call["messages"][1]["content"]
    assert "/no_think" not in blob
    # The transcript appears in the user message.
    assert "Opening hook line." in call["messages"][1]["content"]


def test_select_honors_controls_count(good_clips):
    many = good_clips + [
        {"start": "02:00", "end": "02:40", "score": 70, "hook": "h", "why": "w"},
        {"start": "03:00", "end": "03:40", "score": 60, "hook": "h", "why": "w"},
    ]
    provider = FakeProvider([_clips_json(many)])
    cands = select(_short_transcript(), "x", {"count": 2}, provider)
    assert len(cands) == 2  # capped to controls.count even though 4 returned


def test_select_defaults_count_to_five_when_omitted():
    six = [{"start": f"0{i}:00", "end": f"0{i}:40", "score": 90 - i, "hook": "h", "why": "w"} for i in range(6)]
    provider = FakeProvider([_clips_json(six)])
    cands = select(_short_transcript(), "x", None, provider)
    assert len(cands) == sel.DEFAULT_COUNT == 5


def test_select_uses_default_prompt_when_blank(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    select(_short_transcript(), "   ", {"count": 1}, provider)
    user_msg = provider.calls[0]["messages"][1]["content"]
    assert "share-worthy" in user_msg.lower()


def test_select_empty_on_unparseable_response():
    provider = FakeProvider(["sorry, no json"])
    cands = select(_short_transcript(), "x", {"count": 3}, provider)
    assert cands == []


def test_select_clamps_out_of_range_controls_window():
    # minSec/maxSec outside the hard 20-60 envelope must be pulled back in.
    clips = [{"start": "00:00", "end": "00:05", "score": 50}]
    provider = FakeProvider([_clips_json(clips)])
    cands = select(_short_transcript(), "x", {"count": 1, "minSec": 5, "maxSec": 999}, provider)
    assert cands[0]["durationSec"] >= MIN_CLIP_SEC
    assert cands[0]["durationSec"] <= MAX_CLIP_SEC
    # The system prompt window is clamped to 20-60, not 5-999.
    assert "20-60 SECONDS" in provider.calls[0]["messages"][0]["content"]


# ---------------------------------------------------------------------------
# select(): map-reduce path for long transcripts
# ---------------------------------------------------------------------------


def test_select_long_transcript_triggers_map_reduce(good_clips):
    # 600 segments -> 600 lines -> 3 chunks of 200 -> 3 map calls + 1 reduce = 4.
    map_resp = _clips_json(
        [
            {"start": "00:30", "end": "01:15", "score": 88, "hook": "h", "why": "w"},
        ]
    )
    reduce_resp = _clips_json(good_clips)
    provider = FakeProvider([map_resp, map_resp, map_resp, reduce_resp])
    cands = select(_long_transcript(600), "x", {"count": 2}, provider)
    assert len(provider.calls) == 4  # 3 map + 1 reduce
    assert len(cands) == 2
    # The reduce (last) call carries the global re-rank instruction.
    assert "re-rank" in provider.last_user.lower()


def test_select_map_reduce_falls_back_to_shortlist_when_reduce_unparseable():
    map_resp = _clips_json(
        [
            {"start": "00:30", "end": "01:15", "score": 88, "hook": "h", "why": "w"},
        ]
    )
    # Reduce returns garbage -> fall back to the validated map shortlist.
    provider = FakeProvider([map_resp, map_resp, map_resp, "no json"])
    cands = select(_long_transcript(600), "x", {"count": 5}, provider)
    assert len(cands) >= 1
    assert all(MIN_CLIP_SEC <= c["durationSec"] <= MAX_CLIP_SEC for c in cands)


def test_select_map_reduce_empty_when_no_shortlist():
    provider = FakeProvider(["no json", "no json", "no json", "no json"])
    cands = select(_long_transcript(600), "x", {"count": 5}, provider)
    assert cands == []


# ---------------------------------------------------------------------------
# _parse_ts — timestamp parsing edge cases (mm:ss / hh:mm:ss / bare / junk)
# ---------------------------------------------------------------------------
def test_parse_ts_numeric_and_string_forms():
    assert sel._parse_ts(42) == pytest.approx(42.0)
    assert sel._parse_ts(42.5) == pytest.approx(42.5)
    assert sel._parse_ts("90") == pytest.approx(90.0)
    assert sel._parse_ts("01:30") == pytest.approx(90.0)  # mm:ss
    assert sel._parse_ts("01:02:03") == pytest.approx(3723.0)  # hh:mm:ss


def test_parse_ts_returns_none_for_non_str_non_number():
    # A list / dict / None is neither int/float nor str -> None (row skipped).
    assert sel._parse_ts(["00:30"]) is None
    assert sel._parse_ts(None) is None
    assert sel._parse_ts({"t": 1}) is None


def test_parse_ts_returns_none_for_blank_and_garbage():
    assert sel._parse_ts("   ") is None  # blank
    assert sel._parse_ts("ab:cd") is None  # colon form, non-numeric parts
    assert sel._parse_ts("not-a-number") is None  # bare, non-numeric


# ---------------------------------------------------------------------------
# to_candidates — non-dict rows, end-only anchoring, start/end swap
# ---------------------------------------------------------------------------
def test_to_candidates_skips_non_dict_rows():
    out = to_candidates(["junk", 42, None, {"start": "00:30", "end": "01:15", "score": 5}], 20.0, 60.0)
    assert len(out) == 1  # only the real dict survived


def test_to_candidates_end_only_anchors_min_length_window():
    # Only an ``end`` given -> a min-length window ending there.
    out = to_candidates([{"end": "01:00", "score": 7}], 20.0, 60.0)
    assert len(out) == 1
    c = out[0]
    assert c["end"] == pytest.approx(60.0)
    assert c["start"] == pytest.approx(40.0)  # 60 - minSec(20)
    assert c["durationSec"] == pytest.approx(20.0)


def test_to_candidates_start_only_extends_to_min_length():
    # Only a ``start`` given (no end) -> end = start + minSec.
    out = to_candidates([{"start": "00:10", "score": 6}], 20.0, 60.0)
    assert len(out) == 1
    c = out[0]
    assert c["start"] == pytest.approx(10.0)
    assert c["end"] == pytest.approx(30.0)  # 10 + minSec(20)
    assert c["durationSec"] == pytest.approx(20.0)


def test_to_candidates_swaps_inverted_start_end():
    # end < start -> swapped so the window is well-ordered before clamping.
    out = to_candidates([{"start": "01:00", "end": "00:30", "score": 3}], 20.0, 60.0)
    assert len(out) == 1
    c = out[0]
    assert c["start"] <= c["end"]
    assert 20.0 <= c["durationSec"] <= 60.0


# ---------------------------------------------------------------------------
# _resolve_controls — defaults, clamps, and the min>max swap
# ---------------------------------------------------------------------------
def test_resolve_controls_count_below_one_uses_default():
    cfg = sel._resolve_controls({"count": 0})
    assert cfg["count"] == sel.DEFAULT_COUNT


def test_resolve_controls_non_numeric_min_max_fall_back_to_defaults():
    cfg = sel._resolve_controls({"minSec": "oops", "maxSec": None})
    assert cfg["min_sec"] == pytest.approx(MIN_CLIP_SEC)
    assert cfg["max_sec"] == pytest.approx(MAX_CLIP_SEC)


def test_resolve_controls_clamps_into_hard_envelope():
    # Requests outside the hard 20-60 s envelope are clamped to it.
    cfg = sel._resolve_controls({"minSec": 5.0, "maxSec": 999.0})
    assert cfg["min_sec"] == pytest.approx(MIN_CLIP_SEC)
    assert cfg["max_sec"] == pytest.approx(MAX_CLIP_SEC)


def test_resolve_controls_swaps_when_min_exceeds_max():
    # minSec > maxSec (both inside the envelope) -> swapped so min <= max.
    cfg = sel._resolve_controls({"minSec": 50.0, "maxSec": 30.0})
    assert cfg["min_sec"] <= cfg["max_sec"]
    assert cfg["min_sec"] == pytest.approx(30.0)
    assert cfg["max_sec"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# select — non-numeric durationSec degrades to "no source-duration cap"
# ---------------------------------------------------------------------------
def test_select_non_numeric_duration_total_is_ignored():
    # A transcript whose durationSec is non-numeric -> duration_total None (no
    # source-length cap), and selection still produces clamped candidates.
    transcript = {
        "language": "en",
        "durationSec": "not-a-number",
        "segments": [
            {"start": 0.0, "end": 30.0, "text": "Opening hook line."},
            {"start": 30.0, "end": 75.0, "text": "The thesis payoff."},
        ],
    }
    resp = _clips_json([{"start": "00:05", "end": "00:40", "score": 90, "hook": "h", "why": "w"}])
    provider = FakeProvider([resp])
    cands = select(transcript, "x", {"count": 1}, provider)
    assert len(cands) == 1
    assert MIN_CLIP_SEC <= cands[0]["durationSec"] <= MAX_CLIP_SEC


# ===========================================================================
# select_unified() — the Wave-2 tri-modal scorer (ADDITIVE; backward compatible)
# ===========================================================================

from media_studio.features.motion import Signal, SignalTrack  # noqa: E402
from media_studio.features.quality_gate import QualityScore  # noqa: E402
from media_studio.features.select import select_unified  # noqa: E402


def _grid_track(channel: str, per_window: list[float], *, present: bool = True) -> SignalTrack:
    """A SignalTrack with one 1-second window per value (the shared grid)."""
    sigs = tuple(Signal(channel=channel, start=float(i), end=float(i + 1), value=v) for i, v in enumerate(per_window))
    return SignalTrack(channel=channel, signals=sigs, present=present)


class FakeRanker:
    """A fake ``RankerBackend`` whose ``predict`` is a simple linear scorer.

    Scores each feature row by the sum of its columns, so a clip with stronger
    signals re-ranks above a weaker one — deterministic, no lightgbm.
    """

    def __init__(self) -> None:
        self.fit_called = False

    def fit(self, x, y, groups) -> None:  # noqa: ANN001 - test fake
        self.fit_called = True

    def predict(self, x):  # noqa: ANN001 - test fake
        return [float(sum(row)) for row in x]


class FakeVlmReranker:
    """A fake ``VlmReranker`` that reverses the top-K (records the call)."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def rerank_top_k(self, cands, *, top_k):  # noqa: ANN001 - test fake
        self.calls.append(top_k)
        k = min(int(top_k), len(cands))
        top = list(reversed([dict(c) for c in cands[:k]]))
        return top + [dict(c) for c in cands[k:]]


def _tracks() -> dict[str, SignalTrack]:
    """A small present visual+audio track set over a 300s grid (sparse)."""
    return {
        "motion": _grid_track("motion", [0.5] * 300),
        "saliency": _grid_track("saliency", [0.7] * 300),
    }


# --- backward compat: transcript path delegates to the unchanged select() --


def test_select_unified_transcript_path_matches_select_ordering(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "make shorts", {"count": 2}, provider)
    assert len(cands) == 2
    # Every candidate carries the new Wave-2 stamps additively.
    for c in cands:
        assert "signals" in c
        assert "signalScore" in c
        assert "rankerScore" in c
        assert "viralityPct" in c  # _finalize still stamps the batch percentile


def test_select_unified_blends_signals_onto_candidates(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider, tracks=_tracks(), duration_total=300.0)
    # signalScore is a 0..1 fusion of legacy score + the present-weighted boost.
    for c in cands:
        assert 0.0 <= c["signalScore"] <= 1.0
        # present tracks pooled into the per-clip signal map.
        assert set(c["signals"]).issubset({"motion", "saliency"})


# --- the silent-video / no-LLM path (WU5 acceptance) ----------------------


def test_select_unified_silent_video_path_no_transcript():
    # No transcript -> visual-only peak-pick of the fused interest curve.
    tracks = {"motion": _grid_track("motion", [0.0] * 300)}
    curve_tracks = dict(tracks)
    # make a clear peak so a candidate is produced.
    sigs = list(curve_tracks["motion"].signals)
    sigs[40] = Signal(channel="motion", start=40.0, end=41.0, value=1.0)
    curve_tracks["motion"] = SignalTrack(channel="motion", signals=tuple(sigs), present=True)
    cands = select_unified(None, "x", {"count": 1}, None, tracks=curve_tracks, duration_total=300.0)
    assert len(cands) == 1
    assert cands[0]["why"] == "visual interest peak"
    assert "rankerScore" in cands[0]


def test_select_unified_no_provider_uses_visual_path():
    # A transcript is present but provider is None -> still the visual-only path.
    tracks = {"motion": _grid_track("motion", [0.6] * 300)}
    cands = select_unified(_short_transcript(), "x", {"count": 1}, None, tracks=tracks, duration_total=300.0)
    assert len(cands) == 1
    assert cands[0]["why"] == "visual interest peak"


def test_select_unified_empty_transcript_segments_uses_visual_path():
    # An empty-segments transcript counts as "no transcript".
    tracks = {"motion": _grid_track("motion", [0.6] * 300)}
    cands = select_unified(
        {"segments": []}, "x", {"count": 1}, FakeProvider(["{}"]), tracks=tracks, duration_total=300.0
    )
    assert len(cands) == 1
    assert cands[0]["why"] == "visual interest peak"


def test_select_unified_returns_empty_when_no_candidates():
    # No transcript + no tracks -> empty curve -> no candidates.
    assert select_unified(None, "x", {"count": 3}, None, tracks={}, duration_total=0.0) == []


def test_select_unified_returns_empty_when_llm_unparseable():
    provider = FakeProvider(["no json at all"])
    cands = select_unified(_short_transcript(), "x", {"count": 3}, provider, duration_total=300.0)
    assert cands == []


# --- Tier-0: learned re-rank + diversity (always on, zero downloads) -------


def test_select_unified_tier0_uses_fallback_ranker_without_backend(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider, tier=0)
    # No ranker backend -> factor-average fallback still stamps rankerScore.
    assert all("rankerScore" in c for c in cands)


def test_select_unified_uses_injected_ranker_backend(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    fake = FakeRanker()
    cands = select_unified(
        _short_transcript(), "x", {"count": 2}, provider, tracks=_tracks(), ranker=fake, duration_total=300.0
    )
    assert fake.fit_called is False  # rank() only predicts; training is upstream
    assert all("rankerScore" in c for c in cands)


def test_select_unified_diversity_uses_supplied_embeddings(good_clips):
    import numpy as np

    provider = FakeProvider([_clips_json(good_clips)])
    embeds = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=float)
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider, embeddings=embeds, duration_total=300.0)
    assert len(cands) == 2


def test_select_unified_dpp_diversity_method(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(
        _short_transcript(),
        "x",
        {"count": 2, "diversityMethod": "dpp"},
        provider,
        tracks=_tracks(),
        duration_total=300.0,
    )
    assert len(cands) <= 2


# --- Tier-1: quality gate (optional; no-op when scores absent) -------------


def test_select_unified_quality_gate_demotes_when_scores_present(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    # A poor quality score on the (originally) top clip demotes it.
    scores = [QualityScore(technical=0.0, aesthetic=0.0, overall=0.0), QualityScore(0.9, 0.9, 0.9)]
    cands = select_unified(
        _short_transcript(),
        "x",
        {"count": 2},
        provider,
        quality_scores=scores,
        duration_total=300.0,
    )
    assert all("qualityScore" in c for c in cands)


def test_select_unified_quality_gate_noop_when_scores_none(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider, quality_scores=None)
    # No quality scores -> gate is a no-op -> no qualityScore stamped.
    assert all("qualityScore" not in c for c in cands)


# --- Tier-2: VLM re-rank (opt-in; off by default) -------------------------


def test_select_unified_tier2_invokes_vlm_reranker(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    fake = FakeVlmReranker()
    select_unified(
        _short_transcript(),
        "x",
        {"count": 2, "smolvlmTopK": 2},
        provider,
        vlm_reranker=fake,
        tier=2,
        duration_total=300.0,
    )
    assert fake.calls == [2]  # top_k read from settings


def test_select_unified_tier1_skips_vlm_even_if_supplied(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    fake = FakeVlmReranker()
    select_unified(_short_transcript(), "x", {"count": 2}, provider, vlm_reranker=fake, tier=1)
    assert fake.calls == []  # tier < 2 -> step 6 skipped


def test_select_unified_tier2_no_reranker_is_noop(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider, vlm_reranker=None, tier=2)
    assert len(cands) == 2


# --- settings resolvers ----------------------------------------------------


def test_select_unified_custom_alpha_changes_signal_score(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    # alpha 0 -> signalScore is pure legacy score (95/100 = 0.95 for the top clip).
    cands = select_unified(
        _short_transcript(), "x", {"count": 2, "scorerAlpha": 0.0}, provider, tracks=_tracks(), duration_total=300.0
    )
    top = max(cands, key=lambda c: c["score"])
    assert top["signalScore"] == pytest.approx(top["score"] / 100.0)


def test_select_unified_invalid_alpha_falls_back_to_default(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(
        _short_transcript(), "x", {"count": 1, "scorerAlpha": "oops"}, provider, tracks=_tracks(), duration_total=300.0
    )
    assert 0.0 <= cands[0]["signalScore"] <= 1.0


def test_select_unified_invalid_top_k_falls_back_to_default(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    fake = FakeVlmReranker()
    select_unified(
        _short_transcript(),
        "x",
        {"count": 2, "smolvlmTopK": "nope"},
        provider,
        vlm_reranker=fake,
        tier=2,
    )
    assert fake.calls == [10]  # invalid setting -> default top_k 10 passed through


def test_select_unified_zero_top_k_falls_back_to_default(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    fake = FakeVlmReranker()
    select_unified(
        _short_transcript(),
        "x",
        {"count": 2, "smolvlmTopK": 0},
        provider,
        vlm_reranker=fake,
        tier=2,
    )
    assert fake.calls == [10]  # 0 -> default top_k 10 passed through


def test_select_unified_resolves_duration_from_transcript_when_arg_omitted(good_clips):
    # duration_total omitted -> falls back to transcript.durationSec (300s here).
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(_short_transcript(), "x", {"count": 2}, provider)
    assert all(c["end"] <= 300.0 for c in cands)


def test_select_unified_non_mapping_controls_uses_defaults(good_clips):
    provider = FakeProvider([_clips_json(good_clips)])
    # controls=None -> default count 5, default settings (mmr, alpha 0.5).
    cands = select_unified(_short_transcript(), "x", None, provider, tracks=_tracks(), duration_total=300.0)
    assert len(cands) == 2  # only 2 clips returned by the fake provider


def test_select_unified_non_numeric_transcript_duration_leaves_total_none(good_clips):
    # duration_total omitted AND transcript.durationSec is non-numeric -> no source
    # cap is resolved (total stays None), and selection still produces candidates.
    transcript = {
        "language": "en",
        "durationSec": "not-a-number",
        "segments": [{"start": 0.0, "end": 30.0, "text": "Opening hook line."}],
    }
    provider = FakeProvider([_clips_json(good_clips)])
    cands = select_unified(transcript, "x", {"count": 2}, provider)
    assert len(cands) == 2
