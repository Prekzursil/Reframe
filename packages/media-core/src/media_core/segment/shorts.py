from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Dict, List, Optional

import json
import re


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


@dataclass(frozen=True)
class HeuristicWeights:
    base_score: float = 0.2
    keyword_density: float = 1.0
    sentence_boundary_bonus: float = 0.35
    speech_density_norm: float = 0.6
    duration_bonus: float = 0.3
    novelty_penalty: float = 0.35


_TOKEN_RE = re.compile(r"[a-z0-9']+")
_SENTENCE_RE = re.compile(r"[.!?](?:\s|$)")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _to_weights(raw: Optional[HeuristicWeights | dict]) -> HeuristicWeights:
    if isinstance(raw, HeuristicWeights):
        return raw
    if not isinstance(raw, dict):
        return HeuristicWeights()
    defaults = HeuristicWeights()
    values = defaults.__dict__.copy()
    for key, value in raw.items():
        if key in values:
            try:
                values[key] = float(value)
            except (TypeError, ValueError):
                continue
    return HeuristicWeights(**values)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


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


def _filter_by_bounds(
    candidates: List[SegmentCandidate],
    min_duration: float,
    max_duration: float,
) -> List[SegmentCandidate]:
    """Keep candidates whose duration is within bounds and which are non-empty."""
    return [
        c
        for c in candidates
        if c.duration >= min_duration and c.duration <= max_duration and c.start < c.end
    ]


def _stable_scores(intervals: List[SegmentCandidate]) -> list[float]:
    """Compute tie-broken scores so selection is deterministic for equal scores."""
    return [
        float(item.score) - (float(item.start) * 1e-6) - (idx * 1e-9)
        for idx, item in enumerate(intervals)
    ]


def _predecessors(intervals: List[SegmentCandidate], min_gap: float) -> list[int]:
    """For each interval return the 1-based predecessor index (0 means none)."""
    ends = [c.end for c in intervals]
    preds: list[int] = []
    for i, cand in enumerate(intervals):
        cutoff = cand.start - min_gap
        j = bisect_right(ends, cutoff, 0, i) - 1
        preds.append(j + 1)
    return preds


def _interval_dp(
    stable_scores: list[float], preds: list[int], k_max: int
) -> list[list[float]]:
    """Weighted interval scheduling DP table with a max-segment (k) constraint."""
    n = len(stable_scores)
    dp: list[list[float]] = [[0.0] * (k_max + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score_i = stable_scores[i - 1]
        pred = preds[i - 1]
        for k in range(1, k_max + 1):
            skip = dp[i - 1][k]
            take = score_i + dp[pred][k - 1]
            dp[i][k] = take if take > skip else skip
    return dp


def _backtrack_selection(
    intervals: List[SegmentCandidate],
    stable_scores: list[float],
    preds: list[int],
    dp: list[list[float]],
    k_max: int,
) -> list[SegmentCandidate]:
    """Reconstruct the chosen intervals from the DP table."""
    selected: list[SegmentCandidate] = []
    i = len(intervals)
    k = k_max
    while i > 0 and k > 0:
        score_i = stable_scores[i - 1]
        pred = preds[i - 1]
        if score_i + dp[pred][k - 1] > dp[i - 1][k]:
            selected.append(intervals[i - 1])
            i = pred
            k -= 1
        else:
            i -= 1
    selected.sort(key=lambda c: c.start)
    return selected


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
    filtered = _filter_by_bounds(candidates, min_duration, max_duration)
    if max_segments <= 0 or not filtered:
        return []

    # Weighted interval scheduling with a max_segments constraint:
    # maximize total score under non-overlap (+ optional min_gap).
    intervals = sorted(filtered, key=lambda c: (c.end, c.start))
    stable_scores = _stable_scores(intervals)
    preds = _predecessors(intervals, min_gap)

    k_max = min(max_segments, len(intervals))
    dp = _interval_dp(stable_scores, preds, k_max)
    return _backtrack_selection(intervals, stable_scores, preds, dp, k_max)


def _keyword_density(text: str, keywords: List[str], token_count: int) -> float:
    keyword_hits = sum(text.count(k) for k in keywords) if (text and keywords) else 0
    return keyword_hits / max(1, token_count)


def _speech_density(token_count: int, duration: float) -> float:
    wps = token_count / max(duration, 0.5)
    target_wps = 2.4
    return _clamp(1.0 - abs(wps - target_wps) / target_wps, 0.0, 1.0)


def _duration_bonus(duration: float) -> float:
    if 15.0 <= duration <= 60.0:
        return 1.0
    return _clamp(1.0 - abs(duration - 30.0) / 30.0, 0.0, 1.0)


def _apply_heuristic_score(
    cand: SegmentCandidate,
    cfg: HeuristicWeights,
    keywords: List[str],
    seen_tokens: list[set[str]],
) -> set[str]:
    """Score a single candidate in place; return its token set for novelty tracking."""
    text = (cand.snippet or "").strip().lower()
    tokens = _tokenize(text)
    token_set = set(tokens)

    keyword_density = _keyword_density(text, keywords, len(tokens))
    sentence_bonus = 1.0 if _SENTENCE_RE.search(text) else 0.0
    speech_density = _speech_density(len(tokens), cand.duration)
    duration_bonus = _duration_bonus(cand.duration)
    novelty_overlap = max((_jaccard(token_set, prev) for prev in seen_tokens), default=0.0)

    total = (
        (cfg.base_score * float(cand.score))
        + (cfg.keyword_density * keyword_density)
        + (cfg.sentence_boundary_bonus * sentence_bonus)
        + (cfg.speech_density_norm * speech_density)
        + (cfg.duration_bonus * duration_bonus)
        - (cfg.novelty_penalty * novelty_overlap)
    )
    cand.score = float(total)
    cand.reason = (
        f"kw={keyword_density:.3f},sentence={sentence_bonus:.1f},speech={speech_density:.3f},"
        f"duration={duration_bonus:.3f},novelty={novelty_overlap:.3f}"
    )
    return token_set


def score_segments_heuristic(
    candidates: List[SegmentCandidate],
    keywords: Optional[List[str]] = None,
    weights: Optional[HeuristicWeights | dict] = None,
) -> List[SegmentCandidate]:
    cfg = _to_weights(weights)
    keywords = [k.lower() for k in (keywords or []) if k]
    seen_tokens: list[set[str]] = []
    for cand in candidates:
        token_set = _apply_heuristic_score(cand, cfg, keywords, seen_tokens)
        seen_tokens.append(token_set)
    return candidates


def _build_llm_messages(
    transcript: str, prompt: str, candidates: List[SegmentCandidate]
) -> list[dict]:
    payload = [
        {"start": c.start, "end": c.end, "snippet": c.snippet or ""}
        for c in candidates
    ]
    return [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": json.dumps({"transcript": transcript, "candidates": payload}),
        },
    ]


def _parse_llm_score_map(content: str) -> Dict[tuple, float]:
    """Parse the LLM JSON response into a {(start, end): score} map.

    Malformed top-level JSON or individual entries are ignored, mirroring the
    lenient behavior expected by callers (best-effort scoring).
    """
    try:
        scores = json.loads(content)
    except json.JSONDecodeError:
        return {}

    score_map: Dict[tuple, float] = {}
    if isinstance(scores, list):
        for entry in scores:
            try:
                key = (float(entry["start"]), float(entry["end"]))
                score_map[key] = float(entry.get("score", 0.0))
            except (KeyError, TypeError, ValueError):
                continue
    return score_map


def score_segments_llm(
    transcript: str,
    candidates: List[SegmentCandidate],
    prompt: str,
    model: str,
    client: Optional[object] = None,
) -> List[SegmentCandidate]:
    """Score segments using an LLM client.

    client must expose chat.completions.create(model=..., messages=[...]) similar to OpenAI.
    This function is testable by passing a fake client that returns JSON content.
    """

    if client is None:
        raise RuntimeError("LLM client not provided; supply a compatible client")

    messages = _build_llm_messages(transcript, prompt, candidates)
    resp = client.chat.completions.create(model=model, messages=messages)
    content = resp.choices[0].message.content  # type: ignore[attr-defined]
    score_map = _parse_llm_score_map(content)

    for cand in candidates:
        key = (cand.start, cand.end)
        if key in score_map:
            cand.score = score_map[key]
    return candidates
