"""PURE best-frame core — prompt build, forgiving reply parse, result shaping.

Capability C (AI best-frame thumbnail), WU-C1. This module is the *pure half* of
the best-frame picker: it builds the multimodal instruction, parses the model's
free-text reply into a single 0-based frame index (defensively — a malformed
reply degrades to index 0, never raises), and shapes a chosen index into the
``{frameTimeSec, score}`` result the handler returns.

It imports **no cv2 and no model** — frames and replies are injected by the
caller, so the whole module is unit-coverable. The frame-scoring seam
(``score_frames``) and the cv2 ``imwrite`` writer land in WU-C2; this file holds
only the deterministic, dependency-free shaping that mirrors
:func:`media_studio.features.smolvlm2.parse_rerank_order`.
"""

from __future__ import annotations

from collections.abc import Sequence

from media_studio.util import clamp


def build_select_prompt(n: int) -> str:
    """Render the one multimodal instruction asking for the best thumbnail frame.

    The model is shown ``n`` numbered frames (1-based, as humans count) and asked
    which single one is the best thumbnail and *why*. The wording is a constant
    so tests can assert it; the count is interpolated so the reply numbering is
    unambiguous. The parsing side (:func:`parse_best_index`) converts the 1-based
    reply back to a 0-based index.
    """
    return (
        f"You are choosing the single best thumbnail frame for a short video. "
        f"You are shown {n} numbered frames (1 to {n}). Reply with the number of "
        f"the BEST thumbnail frame and a brief reason why it is the most "
        f"eye-catching, in-focus, and representative of the clip."
    )


def parse_best_index(reply: str, n: int) -> int:
    """Parse the model's reply into a single 0-based frame index in ``range(n)``.

    Forgiving and total (mirrors :func:`smolvlm2.parse_rerank_order`): the FIRST
    integer token in the reply is taken as the model's 1-based choice and
    converted to 0-based, then clamped into ``range(n)`` so the result is ALWAYS
    a valid index. A reply with no parseable number degrades to ``0`` (a
    deterministic fallback — the first frame) rather than raising. ``n <= 0`` is
    treated as a single-frame degenerate case and also yields ``0``.
    """
    last = max(0, n - 1)
    token = ""
    for ch in f"{reply} ":  # trailing space flushes a final digit run
        if ch.isdigit():
            token += ch
            continue
        if token:
            one_based = int(token)
            zero_based = one_based - 1
            return int(clamp(float(zero_based), 0.0, float(last)))
    return 0


def shape_result(
    index: int,
    frame_times: Sequence[float],
    scores: Sequence[float],
) -> dict[str, float]:
    """Shape a chosen frame ``index`` into the ``{frameTimeSec, score}`` result.

    ``frame_times`` and ``scores`` are aligned to the sampled frames. The chosen
    ``index`` maps to its frame time (clamped into the available range so a
    defensively out-of-range index never raises) and its score (clamped to the
    unit interval; a missing/out-of-range score defaults to ``0.0``). With no
    frames at all the result is a zero time / zero score rather than an
    ``IndexError``.
    """
    if frame_times:
        time_idx = int(clamp(float(index), 0.0, float(len(frame_times) - 1)))
        frame_time = float(frame_times[time_idx])
    else:
        frame_time = 0.0
    score = clamp(float(scores[index]), 0.0, 1.0) if 0 <= index < len(scores) else 0.0
    return {"frameTimeSec": frame_time, "score": score}
