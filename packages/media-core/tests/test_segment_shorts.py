from media_core.segment.shorts import SegmentCandidate, equal_splits, select_top, sliding_window


def test_equal_splits_produces_segments():
    segs = equal_splits(duration=10.0, clip_length=4.0)
    assert len(segs) == 3
    assert segs[0].start == 0.0 and segs[1].start == 4.0
    assert segs[-1].end == 10.0


def test_sliding_window_stride():
    segs = sliding_window(duration=5.0, window=2.0, stride=1.0)
    assert len(segs) == 5
    assert segs[0].start == 0.0 and segs[1].start == 1.0


def test_select_top_filters_and_sorts():
    cands = [
        SegmentCandidate(start=0, end=2, score=0.5),
        SegmentCandidate(start=2.1, end=4, score=0.8),
        SegmentCandidate(start=1, end=3, score=0.9),  # overlaps
    ]
    selected = select_top(cands, max_segments=2, min_duration=1.0, max_duration=5.0)
    assert len(selected) == 2
    assert selected[0].start == 0 and selected[1].start == 2.1
