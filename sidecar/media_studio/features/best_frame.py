"""PURE best-frame core — prompt build, forgiving reply parse, result shaping.

Capability C (AI best-frame thumbnail), WU-C1. This module is the *pure half* of
the best-frame picker: it builds the multimodal instruction, parses the model's
free-text reply into a single 0-based frame index (defensively — a malformed
reply degrades to index 0, never raises), and shapes a chosen index into the
``{frameTimeSec, score}`` result the handler returns.

It imports **no cv2 and no model** — frames and replies are injected by the
caller, so the whole module is unit-coverable.

WU-C2 adds the two job-time *seams* the picker needs without dragging native
code into the import path: a :class:`FrameScorer` (default
:class:`CloudFrameScorer`, which reuses
:class:`~media_studio.features.smolvlm2.CloudVlmBackend` by treating each frame
as a one-frame "clip") and a :data:`ThumbnailWriter` (default
:func:`_default_thumbnail_writer`, the single ``cv2.imwrite`` line that is the
lone ``# pragma: no cover`` here — mirroring
:func:`media_studio.features.smolvlm2._default_frame_encoder`).
:func:`pick_best_frame` wires the two together: score the frames, take the
argmax, write that frame, and shape the result. Tests inject fakes for both
seams, so apart from the one prod ``imwrite`` line the whole module stays 100%
line+branch covered with no cv2 and no model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

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


# --------------------------------------------------------------------------- #
# WU-C2 — job-time seams (scorer + writer) and the picker that wires them
# --------------------------------------------------------------------------- #
#: ``(frames, prompt) -> per-frame scores``. The default is :class:`CloudFrameScorer`
#: (cloud VLM via a 1-frame-per-clip reuse of the rerank backend); tests inject a
#: plain callable returning canned scores, so no model is touched under the gate.
FrameScorer = Callable[[Sequence[Any], str], "list[float]"]
#: ``(frame, path) -> None``. The default is :func:`_default_thumbnail_writer`
#: (cv2 ``imwrite``); tests inject a fake recording its ``(frame, path)`` call.
ThumbnailWriter = Callable[[Any, str], None]


class _RankClipsBackend(Protocol):
    """The slice of a VLM backend :class:`CloudFrameScorer` needs.

    Exactly :meth:`~media_studio.features.smolvlm2.CloudVlmBackend.rank_clips`,
    so the cloud (or local) rerank backend satisfies it unchanged. Declared as a
    Protocol so tests inject a trivial fake with no model/weights.
    """

    def rank_clips(self, frames_per_clip: Sequence[Any], prompt: str) -> list[float]:
        """Score each clip (a frame stack) for the prompt — higher = better."""
        ...  # pragma: no cover - Protocol stub


def argmax_index(scores: Sequence[float]) -> int:
    """Index of the highest score; ties keep the earliest frame; ``[]`` -> ``0``.

    Stable and total: an empty score list degrades to ``0`` (the deterministic
    first-frame fallback, never an exception), mirroring the defensive contract
    of :func:`parse_best_index`.
    """
    best_idx = 0
    best_val = float("-inf")
    for idx, raw in enumerate(scores):
        value = float(raw)
        if value > best_val:
            best_val = value
            best_idx = idx
    return best_idx


class CloudFrameScorer:
    """Score frames by reusing a clip-ranking VLM backend, one frame per "clip".

    The best-frame picker scores *frames*, but the established cloud seam
    (:class:`~media_studio.features.smolvlm2.CloudVlmBackend`) ranks *clips* (frame
    stacks). This adapter bridges them by wrapping each frame as its own
    single-frame stack, so the cloud VLM scores frames with the exact same
    multimodal path it uses for clips — no new network code. An empty frame list
    short-circuits to ``[]`` (the backend is never called, so a zero-frame job
    costs no egress).
    """

    def __init__(self, backend: _RankClipsBackend) -> None:
        self._backend = backend

    def score_frames(self, frames: Sequence[Any], prompt: str) -> list[float]:
        """Return one score per frame (each scored as a 1-frame clip stack)."""
        stacks = [[frame] for frame in frames]
        if not stacks:
            return []
        return list(self._backend.rank_clips(stacks, prompt))


def _default_thumbnail_writer(
    frame: Any, path: str
) -> None:  # pragma: no cover - prod seam (writes a JPEG/PNG with cv2)
    """Write one RGB frame array to ``path`` as a JPEG/PNG (LAZY native import).

    ``cv2`` is imported INSIDE the function so importing this module never drags
    in OpenCV; tests inject a fake writer, so this body is the single
    runtime-only, coverage-excluded line here (mirrors
    :func:`media_studio.features.smolvlm2._default_frame_encoder`).
    """
    import cv2  # noqa: PLC0415 - job-time native

    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(path, bgr):
        raise RuntimeError(f"thumbnail write failed: {path}")


def pick_best_frame(
    frames: Sequence[Any],
    prompt: str,
    *,
    frame_times: Sequence[float],
    thumbnail_path: str,
    scorer: FrameScorer,
    writer: ThumbnailWriter,
) -> dict[str, Any]:
    """Score ``frames``, pick the argmax, write it, and shape the result.

    The two side-effecting halves arrive as injected seams: ``scorer`` produces a
    per-frame score list (default :class:`CloudFrameScorer`) and ``writer`` persists
    the chosen frame to ``thumbnail_path`` (default :func:`_default_thumbnail_writer`).
    With at least one frame, the highest-scoring frame is written and the result is
    :func:`shape_result` plus ``thumbnailPath``. With no frames nothing is written
    and a zero-time/zero-score result (still carrying ``thumbnailPath``) is returned,
    so the caller never sees an ``IndexError``.
    """
    scores = scorer(frames, prompt)
    result: dict[str, Any] = {"frameTimeSec": 0.0, "score": 0.0, "thumbnailPath": thumbnail_path}
    if not frames:
        return result
    index = argmax_index(scores)
    writer(frames[index], thumbnail_path)
    result.update(shape_result(index, frame_times, scores))
    result["thumbnailPath"] = thumbnail_path
    return result
