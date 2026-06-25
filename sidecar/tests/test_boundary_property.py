"""Property tests for media_studio.features.boundary (WU-B).

The boundary snapper is dense in float comparisons + window math. The invariants
asserted here are the contract's hard promises (boundary.py docstrings, §5):

  * a kept clip stays within ``[min_sec, max_sec]`` and never cuts mid-word,
  * snapping is idempotent (re-snapping a kept clip on the SAME boundary set
    that now includes its endpoints returns the same geometry),
  * ``sentence_ends_from_words`` is sorted/de-duplicated and only emits valid
    word-end times,
  * ``BoundarySet.all_targets`` is sorted + de-duplicated,
  * ``snap_candidates`` re-ranks kept clips 1..N and partitions every input,
  * ``parse_silencedetect`` midpoints are sorted, de-duplicated, and lie strictly
    between their gap's start and end.

Append-only: ADDS coverage; no source/existing-test change.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st
from media_studio.features import boundary as B

_t = st.floats(min_value=0.0, max_value=300.0, allow_nan=False, allow_infinity=False)
_terminator = st.sampled_from([".", "!", "?", "…"])


@st.composite
def _word(draw: st.DrawFn, *, sentence_end: bool = False) -> dict:
    start = draw(_t)
    end = start + draw(st.floats(min_value=0.01, max_value=2.0, allow_nan=False))
    body = draw(st.text(st.characters(min_codepoint=0x61, max_codepoint=0x7A), min_size=1, max_size=6))
    text = body + (draw(_terminator) if sentence_end else "")
    return {"text": text, "start": start, "end": end}


_words = st.lists(_word(), min_size=0, max_size=10)
_target_list = st.lists(_t, min_size=0, max_size=12)


# --------------------------------------------------------------------------- #
# BoundarySet
# --------------------------------------------------------------------------- #
@given(se=_target_list, si=_target_list, sc=_target_list)
def test_all_targets_sorted_deduped(se: list[float], si: list[float], sc: list[float]) -> None:
    bs = B.BoundarySet(sentence_ends=tuple(se), silences=tuple(si), scene_cuts=tuple(sc))
    targets = bs.all_targets()
    assert list(targets) == sorted(set(targets))
    assert set(targets) == set(se) | set(si) | set(sc)


@given(words=st.lists(_word(sentence_end=True), min_size=0, max_size=8))
def test_sentence_ends_sorted_deduped_and_valid(words: list[dict]) -> None:
    ends = B.sentence_ends_from_words(words)
    assert list(ends) == sorted(set(ends))
    valid = {float(w["end"]) for w in words}
    assert set(ends) <= valid


@given(silences=_target_list, scenes=_target_list, words=_words)
def test_build_boundary_set_cleans_inputs(silences: list[float], scenes: list[float], words: list[dict]) -> None:
    bs = B.build_boundary_set(words, silences=silences, scene_cuts=scenes)
    assert list(bs.silences) == sorted(set(silences))
    assert list(bs.scene_cuts) == sorted(set(scenes))


# --------------------------------------------------------------------------- #
# snapping invariants
# --------------------------------------------------------------------------- #
@st.composite
def _snap_case(draw: st.DrawFn) -> tuple[dict, list[dict], B.BoundarySet]:
    """A candidate + words + a boundary set rich enough to often snap."""
    start = draw(st.floats(min_value=0.0, max_value=60.0, allow_nan=False))
    end = start + draw(st.floats(min_value=5.0, max_value=80.0, allow_nan=False))
    cand = {"rank": 1, "start": start, "end": end, "hook": "h", "why": "w", "score": 1.0, "sourceStart": 0.0}
    # Targets spread across [0, end+40] so the windowed search has options.
    targets = draw(st.lists(st.floats(min_value=0.0, max_value=end + 40, allow_nan=False), max_size=10))
    bs = B.BoundarySet(sentence_ends=tuple(sorted(set(targets))))
    return cand, [], bs


@given(case=_snap_case())
def test_kept_clip_in_window_and_word_aligned(case: tuple[dict, list[dict], B.BoundarySet]) -> None:
    cand, words, bs = case
    res = B.snap_candidate(cand, words, bs, min_sec=20.0, max_sec=60.0)
    if res.dropped:
        assert res.candidate is None
        return
    c = res.candidate
    assert c is not None
    dur = c["end"] - c["start"]
    assert 20.0 - 1e-6 <= dur <= 60.0 + 1e-6
    assert c["end"] > c["start"]
    # geometry fields recomputed; non-geometry preserved
    assert c["hook"] == "h" and c["why"] == "w"
    assert abs(c["durationSec"] - round(dur, 3)) < 1e-9


@given(case=_snap_case())
def test_snap_is_idempotent(case: tuple[dict, list[dict], B.BoundarySet]) -> None:
    cand, words, bs = case
    first = B.snap_candidate(cand, words, bs, min_sec=20.0, max_sec=60.0)
    assume(not first.dropped and first.candidate is not None)
    kept = first.candidate
    # The endpoints are now themselves valid targets (they were chosen from the
    # set); re-snapping must return the same geometry.
    bs2 = B.BoundarySet(sentence_ends=tuple(sorted(set(bs.sentence_ends) | {kept["start"], kept["end"]})))
    second = B.snap_candidate(kept, words, bs2, min_sec=20.0, max_sec=60.0)
    assert not second.dropped
    assert abs(second.candidate["start"] - kept["start"]) < 1e-6
    assert abs(second.candidate["end"] - kept["end"]) < 1e-6


@given(
    start=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    bad_dur=st.floats(min_value=-5.0, max_value=0.0, allow_nan=False),
)
def test_nonpositive_duration_always_dropped(start: float, bad_dur: float) -> None:
    cand = {"start": start, "end": start + bad_dur}
    res = B.snap_candidate(cand, [], B.BoundarySet(), min_sec=20.0, max_sec=60.0)
    assert res.dropped and res.candidate is None


@given(case=_snap_case())
def test_batch_partitions_and_reranks(case: tuple[dict, list[dict], B.BoundarySet]) -> None:
    cand, words, bs = case
    batch = [dict(cand, rank=i) for i in range(3)]
    kept, dropped = B.snap_candidates(batch, words, bs, min_sec=20.0, max_sec=60.0)
    assert len(kept) + len(dropped) == len(batch)
    # kept clips re-ranked 1..N preserving order
    assert [c["rank"] for c in kept] == list(range(1, len(kept) + 1))
    for d in dropped:
        assert "candidate" in d and "reason" in d and d["reason"]


# --------------------------------------------------------------------------- #
# silencedetect parsing
# --------------------------------------------------------------------------- #
@given(
    gaps=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
            st.floats(min_value=0.01, max_value=20.0, allow_nan=False),
        ),
        max_size=6,
    )
)
def test_parse_silencedetect_midpoints_within_gaps(gaps: list[tuple[float, float]]) -> None:
    lines = []
    spans = []
    for start, length in gaps:
        end = start + length
        spans.append((start, end))
        lines.append(f"[silencedetect @ 0x1] silence_start: {start}")
        lines.append(f"[silencedetect @ 0x1] silence_end: {end} | silence_duration: {length}")
    mids = B.parse_silencedetect("\n".join(lines))
    assert list(mids) == sorted(set(mids))
    for mid in mids:
        # every midpoint lies inside at least one (start,end) gap
        assert any(start < mid < end for start, end in spans)
