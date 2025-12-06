from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SegmentCandidate:
    start: float
    end: float
    score: float = 0.0
    reason: Optional[str] = None
    snippet: Optional[str] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def equal_splits(duration: float, clip_length: float) -> List[SegmentCandidate]:
    """Produce naive equal splits across the duration."""
    if duration <= 0 or clip_length <= 0:
        return []
    segments: List[SegmentCandidate] = []
    t = 0.0
    while t < duration:
        end = min(duration, t + clip_length)
        segments.append(SegmentCandidate(start=t, end=end, score=0.0, reason="equal_split"))
        t += clip_length
    return segments


def sliding_window(duration: float, window: float, stride: float) -> List[SegmentCandidate]:
    if duration <= 0 or window <= 0 or stride <= 0:
        return []
    segments: List[SegmentCandidate] = []
    t = 0.0
    while t < duration:
        end = min(duration, t + window)
        segments.append(SegmentCandidate(start=t, end=end, score=0.0, reason="sliding_window"))
        t += stride
    return segments


def select_top(
    candidates: List[SegmentCandidate],
    max_segments: int,
    min_duration: float,
    max_duration: float,
) -> List[SegmentCandidate]:
    """Select top non-overlapping segments by score within duration bounds."""
    filtered = [
        c
        for c in candidates
        if c.duration >= min_duration and c.duration <= max_duration and c.start < c.end
    ]
    filtered.sort(key=lambda c: c.score, reverse=True)
    selected: List[SegmentCandidate] = []
    for cand in filtered:
        if len(selected) >= max_segments:
            break
        if any(not (cand.end <= s.start or cand.start >= s.end) for s in selected):
            continue
        selected.append(cand)
    selected.sort(key=lambda c: c.start)
    return selected
