from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import json


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
    min_gap: float = 0.0,
) -> List[SegmentCandidate]:
    """Select top non-overlapping segments by score within duration bounds.

    If min_gap > 0, enforces a gap between selected segments.
    """
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
        overlaps = any(
            not (cand.end + min_gap <= s.start or cand.start >= s.end + min_gap) for s in selected
        )
        if overlaps:
            continue
        selected.append(cand)
    selected.sort(key=lambda c: c.start)
    return selected


def score_segments_heuristic(
    candidates: List[SegmentCandidate],
    keywords: Optional[List[str]] = None,
) -> List[SegmentCandidate]:
    keywords = [k.lower() for k in (keywords or []) if k]
    for cand in candidates:
        base = 0.0
        if cand.snippet and keywords:
            text = cand.snippet.lower()
            base += sum(text.count(k) for k in keywords)
        # Favor 15-60s durations lightly.
        if 15 <= cand.duration <= 60:
            base += 1.0
        cand.score = base
    return candidates


def score_segments_llm(
    transcript: str,
    candidates: List[SegmentCandidate],
    prompt: str,
    model: str,
    client: Optional[object] = None,
    provider: str = "openai",
) -> List[SegmentCandidate]:
    """Score segments using an LLM client.

    client must expose chat.completions.create(model=..., messages=[...]) similar to OpenAI.
    This function is testable by passing a fake client that returns JSON content.
    """

    if client is None:
        raise RuntimeError("LLM client not provided; supply a compatible client")

    payload = [
        {"start": c.start, "end": c.end, "snippet": c.snippet or ""}
        for c in candidates
    ]
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": json.dumps({"transcript": transcript, "candidates": payload}),
        },
    ]

    resp = client.chat.completions.create(model=model, messages=messages)
    content = resp.choices[0].message.content  # type: ignore[attr-defined]
    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        return candidates

    score_map: Dict[tuple, float] = {}
    if isinstance(scores, list):
        for entry in scores:
            try:
                key = (float(entry["start"]), float(entry["end"]))
                score_map[key] = float(entry.get("score", 0.0))
            except Exception:
                continue

    for cand in candidates:
        key = (cand.start, cand.end)
        if key in score_map:
            cand.score = score_map[key]
    return candidates
