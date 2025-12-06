from media_core.segment.shorts import SegmentCandidate, select_top


def test_select_top_enforces_non_overlap_and_limits():
    cands = [
        SegmentCandidate(start=0, end=5, score=0.9),
        SegmentCandidate(start=4, end=8, score=0.8),  # overlaps
        SegmentCandidate(start=9, end=12, score=0.7),
    ]
    out = select_top(cands, max_segments=2, min_duration=1.0, max_duration=10.0)
    assert len(out) == 2
    assert out[0].start == 0 and out[1].start == 9


def test_select_top_respects_min_duration_and_gap():
    cands = [
        SegmentCandidate(start=0, end=0.4, score=1.0),  # too short
        SegmentCandidate(start=1.0, end=2.0, score=0.9),
        SegmentCandidate(start=2.4, end=3.3, score=0.8),
    ]
    out = select_top(cands, max_segments=3, min_duration=0.5, max_duration=10.0, min_gap=0.3)
    # first candidate filtered out; gap prevents the third from colliding if close
    assert len(out) == 2
    assert out[0].start == 1.0 and out[1].start == 2.4
