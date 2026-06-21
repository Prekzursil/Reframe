"""Tier-0 motion-energy signal (WU0 — the OpenCV floor, zero downloads).

The cheapest Phase-8 signal: a per-window *motion-energy* curve over the clip.
Two pure-numpy/OpenCV motion measures are offered (the WU0 acceptance: a silent
clip still yields a non-empty, scored signal with **zero** model downloads):

* ``absdiff`` — mean absolute frame-to-frame difference (the default floor).
* ``flow`` — mean Farneback dense-optical-flow magnitude (denser, more robust to
  illumination flicker; still pure OpenCV).

An OPTIONAL :class:`MotionBackend` seam lets a higher-accuracy flow model
(NeuFlow_v2, Apache-2.0, ONNX/PyTorch — manifest component #7) be injected later
without touching this module; the default stays the OpenCV floor (``backend`` is
``None`` -> the built-in absdiff/flow path runs).

Architecture (the canonical Wave-1 seam pattern):

* **Pure half** (top of file): :func:`frame_diff_energy`,
  :func:`farneback_flow_magnitude`, :func:`sample_windows`,
  :func:`normalize_curve`, track assembly — plain numpy/OpenCV, 100% covered with
  hand-built arrays, no I/O.
* **Frame-loading half** behind an injectable :data:`FrameLoader` callable
  (``cv2.VideoCapture`` is imported INSIDE the default loader only — exactly like
  :func:`reframe_claudeshorts.detect_subject_centers`). Tests inject a fake
  loader returning synthetic numpy frames, so cv2's *decode* path is never
  exercised and no real video is required.

There is **no heavy model** on the floor path — OpenCV *is* the dependency and it
is in the venv — so unlike the model-backed Wave-1 modules this one has no
offline gate: motion always runs (``present=True``), even on a 1-frame or empty
clip (a single ``0.0`` sample). The module is transport-agnostic pure logic; the
JSON-RPC handler + asset wiring are Wave-2's job.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from ..util import clamp, get_logger

if TYPE_CHECKING:  # numpy is in the venv, but keep the public surface import-light
    import numpy as np

_log = get_logger("media_studio.features.motion")

# Default windowing grid (shared with every Wave-1 module via ``sample_windows``).
DEFAULT_WIN_SEC = 1.0
DEFAULT_HOP_SEC = 1.0

#: The primary channel name this module emits (frozen vocabulary — Wave-2 keys
#: scorer weights off it).
CHANNEL = "motion"

#: Which motion measure to compute.
MotionMode = Literal["absdiff", "flow"]

# Injectable seams.
#: ``(path, timestamps) -> sampled BGR frames`` (one ndarray per timestamp). The
#: default lazily uses ``cv2.VideoCapture`` (import INSIDE the loader only).
FrameLoader = Callable[[str, "Sequence[float]"], "list[np.ndarray]"]
#: cooperative cancel probe + progress sink (match the rest of the codebase).
CancelProbe = Callable[[], bool]
ProgressCb = Callable[[float, str], None]


# --------------------------------------------------------------------------- #
# the shared Signal contract (frozen — Wave-2's unified scorer consumes this)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Signal:
    """One scored observation on the shared timeline (seconds, ORIGINAL video).

    ``value`` is ALWAYS normalized to ``0.0..1.0`` (1.0 = maximally interesting on
    this channel) and clamped at the boundary, so the scorer never sees an
    un-normalized number.
    """

    channel: str
    start: float
    end: float
    value: float
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalTrack:
    """All :class:`Signal`\\ s from this module + a modality-presence flag.

    ``present=False`` is the degrade signal (Wave-2 drops the channel's weight and
    re-normalizes the survivors). Motion is the CPU floor, so it is effectively
    always ``present=True`` — even an empty clip yields a single ``0.0`` sample.
    """

    channel: str
    signals: tuple[Signal, ...]
    present: bool
    fps_hint: float | None = None


# --------------------------------------------------------------------------- #
# pure motion measures (numpy / OpenCV — no I/O, fully covered)
# --------------------------------------------------------------------------- #
def frame_diff_energy(prev: np.ndarray, cur: np.ndarray) -> float:
    """Mean absolute frame-to-frame difference, normalized to ``0.0..1.0``.

    ``cv2.absdiff`` of the two frames (any dtype/shape, as long as they match),
    meaned over all elements and divided by 255 (the 8-bit range) so the result
    is a per-frame motion magnitude in ``[0, 1]``. Reused as the ``absdiff``
    measure's per-pair score. Raises ``ValueError`` on a shape mismatch (the
    loader guarantees uniform frames, but be explicit at the boundary).
    """
    import cv2  # noqa: PLC0415 - OpenCV is the dep; kept out of import time
    import numpy as np  # noqa: PLC0415 - paired with the cv2 lazy import

    if prev.shape != cur.shape:
        raise ValueError(f"frame shape mismatch: {prev.shape} vs {cur.shape}")
    diff = cv2.absdiff(prev, cur)
    return float(np.mean(diff)) / 255.0


def farneback_flow_magnitude(prev_gray: np.ndarray, cur_gray: np.ndarray) -> float:
    """Mean Farneback dense-optical-flow magnitude, normalized to ``0.0..1.0``.

    Computes dense flow between two **single-channel** (grayscale) frames with
    ``cv2.calcOpticalFlowFarneback`` (the standard parameter set), then means the
    per-pixel flow vector magnitude. The mean magnitude (pixels/frame) is squashed
    with ``m / (m + 1)`` into ``[0, 1)`` — a parameter-free monotone map that
    keeps small motions distinguishable while bounding large ones (no scene-wide
    max needed, so it is per-pair pure). Raises ``ValueError`` on a shape
    mismatch.
    """
    import cv2  # noqa: PLC0415 - OpenCV is the dep
    import numpy as np  # noqa: PLC0415

    if prev_gray.shape != cur_gray.shape:
        raise ValueError(f"frame shape mismatch: {prev_gray.shape} vs {cur_gray.shape}")
    # cv2 accepts None for the output ``flow`` arg (it allocates one); the opencv
    # type stubs type it as a required ndarray, so the overload-match is ignored.
    flow = cv2.calcOpticalFlowFarneback(  # pyright: ignore[reportCallIssue]
        prev_gray,
        cur_gray,
        None,  # type: ignore[arg-type]
        0.5,
        3,
        15,
        3,
        5,
        1.2,
        0,
    )
    mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    mean_mag = float(np.mean(mag))
    return mean_mag / (mean_mag + 1.0)


def _to_gray(frame: np.ndarray) -> np.ndarray:
    """Grayscale a frame for flow: BGR via OpenCV, else pass an already-2D frame.

    Farneback needs single-channel input. A 3-channel BGR frame is converted with
    ``cv2.cvtColor``; a frame that is already 2-D (synthetic grayscale) is used
    as-is so the flow path is testable without a colour frame.
    """
    import cv2  # noqa: PLC0415 - OpenCV is the dep

    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


# --------------------------------------------------------------------------- #
# windowing + normalization (pure stdlib/numpy)
# --------------------------------------------------------------------------- #
def sample_windows(
    duration: float,
    win_sec: float = DEFAULT_WIN_SEC,
    hop_sec: float = DEFAULT_HOP_SEC,
) -> tuple[tuple[float, float], ...]:
    """The shared windowing grid: ``((start, end), ...)`` over ``[0, duration]``.

    Mirrors ``reframe_claudeshorts.window_timestamps`` so every Wave-1 module
    shares ONE grid (the scorer aligns tracks by window index). Windows start at
    ``0, hop, 2*hop, ...`` and are ``win_sec`` long, clamped so the last window's
    end never exceeds ``duration``. A non-positive ``duration`` yields a single
    ``(0.0, 0.0)`` window (the empty-clip floor). ``win_sec``/``hop_sec`` must be
    positive.
    """
    d = max(0.0, float(duration))
    if win_sec <= 0.0 or hop_sec <= 0.0:
        raise ValueError(f"win_sec and hop_sec must be positive, got {win_sec}, {hop_sec}")
    if d <= 0.0:
        return ((0.0, 0.0),)
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < d:
        end = min(start + win_sec, d)
        windows.append((round(start, 3), round(end, 3)))
        start += hop_sec
    return tuple(windows)


def normalize_curve(values: Sequence[float]) -> list[float]:
    """Min-max normalize a curve to ``0.0..1.0`` (clamped, NaN-safe enough).

    ``(v - min) / (max - min)`` per element, clamped to ``[0, 1]``. A flat curve
    (``max == min``) maps to all ``0.0`` (no relative motion to highlight). An
    empty input returns ``[]``. Negative inputs are clamped at the boundary, so
    the result is always a valid normalized curve.
    """
    vals = [float(v) for v in values]
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    span = hi - lo
    if span <= 0.0:
        return [0.0 for _ in vals]
    return [clamp((v - lo) / span, 0.0, 1.0) for v in vals]


# --------------------------------------------------------------------------- #
# the optional higher-accuracy backend seam (NeuFlow_v2 — never imported here)
# --------------------------------------------------------------------------- #
class MotionBackend(Protocol):
    """Optional higher-accuracy flow model (e.g. NeuFlow_v2, manifest #7).

    A real implementation (built lazily, never at import time) returns a
    per-adjacent-pair motion magnitude for a stack of frames. The OpenCV floor is
    the default (``backend=None``); injecting a backend swaps in the model without
    changing this module. Tests inject a FAKE returning a canned list — no weights.
    """

    def pair_magnitudes(self, frames: list[np.ndarray]) -> list[float]:
        """Per-adjacent-pair motion magnitude (len = ``max(0, len(frames) - 1)``)."""
        ...  # pragma: no cover - Protocol method body is never executed


# --------------------------------------------------------------------------- #
# the default cv2 frame loader (cv2 imported INSIDE the function only)
# --------------------------------------------------------------------------- #
def _default_frame_loader(
    path: str, timestamps: Sequence[float]
) -> list[
    np.ndarray
]:  # pragma: no cover - real cv2.VideoCapture decode; needs a real video file (tests inject a fake loader)
    """Load one BGR frame per timestamp via ``cv2.VideoCapture`` (lazy import).

    cv2 is imported INSIDE this function (the proven A6 pattern — natives are
    job-time only). For each timestamp we seek by milliseconds and read one
    frame; unreadable seeks are skipped. Tests inject a fake loader, so this real
    decode path is excluded from coverage (it needs a real video file + the cv2
    capture stack).
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    cap = cv2.VideoCapture(path)
    frames: list[np.ndarray] = []
    try:
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(ts) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        cap.release()
    return frames


# --------------------------------------------------------------------------- #
# the public runner (pure orchestration over the seams)
# --------------------------------------------------------------------------- #
def _pair_scores(
    frames: list[np.ndarray],
    mode: MotionMode,
    backend: MotionBackend | None,
) -> list[float]:
    """Per-adjacent-pair raw motion magnitudes for ``frames``.

    Uses the injected ``backend`` when present (its magnitudes are clamped into
    ``[0, 1]`` defensively); otherwise the OpenCV floor — ``absdiff`` or
    Farneback ``flow`` per ``mode``. With <2 frames there are no pairs -> ``[]``.
    """
    if backend is not None:
        return [clamp(float(m), 0.0, 1.0) for m in backend.pair_magnitudes(frames)]
    scores: list[float] = []
    for prev, cur in zip(frames[:-1], frames[1:], strict=False):
        if mode == "flow":
            scores.append(farneback_flow_magnitude(_to_gray(prev), _to_gray(cur)))
        else:
            scores.append(frame_diff_energy(prev, cur))
    return scores


def _window_value(pair_scores: list[float], n_windows: int, index: int) -> float:
    """The pair-score for window ``index`` (each window = the pair entering it).

    Window 0 has no preceding frame, so it inherits window 1's pair score (or
    ``0.0`` when there is only one window / no motion). Subsequent windows map to
    ``pair_scores[index - 1]`` when available, else ``0.0``.
    """
    if not pair_scores:
        return 0.0
    if index == 0:
        # the first window has no incoming pair; mirror the next window's motion
        return pair_scores[0] if n_windows > 1 else 0.0
    pair_idx = index - 1
    return pair_scores[pair_idx] if pair_idx < len(pair_scores) else 0.0


def compute_motion_signals(
    media_path: str,
    duration: float,
    *,
    settings: dict[str, Any] | None = None,
    frame_loader: FrameLoader | None = None,
    backend: MotionBackend | None = None,
    mode: MotionMode = "absdiff",
    on_progress: ProgressCb | None = None,
    should_cancel: CancelProbe | None = None,
) -> SignalTrack:
    """Compute the per-window motion-energy :class:`SignalTrack` for a clip.

    Samples one frame at each window midpoint (via ``frame_loader``, default lazy
    cv2), computes adjacent-pair motion (``absdiff`` floor, ``flow`` Farneback, or
    an injected ``backend``), maps pair scores onto the window grid, min-max
    normalizes the curve, and emits one :class:`Signal` per window. Motion is the
    CPU floor: it ALWAYS returns ``present=True`` — an empty / 1-frame clip yields
    a single ``0.0`` sample rather than ``present=False`` (there is no model to be
    missing). ``settings`` is accepted for interface symmetry with the
    model-backed Wave-1 modules (motion needs none). Cooperative cancel via
    ``should_cancel`` returns the partial track gathered so far.
    """
    _ = settings  # symmetry with model-backed modules; motion needs no settings
    loader: FrameLoader = frame_loader if frame_loader is not None else _default_frame_loader
    windows = sample_windows(duration)
    n = len(windows)
    midpoints = [round((s + e) / 2.0, 3) for s, e in windows]

    if should_cancel is not None and should_cancel():
        _log.info("motion: cancelled before frame load")
        return SignalTrack(channel=CHANNEL, signals=(), present=True)

    frames = list(loader(media_path, midpoints) or [])
    if on_progress is not None:
        on_progress(50.0, "loaded frames")

    pair_scores = _pair_scores(frames, mode, backend)
    raw = [_window_value(pair_scores, n, i) for i in range(n)]
    curve = normalize_curve(raw)

    signals: list[Signal] = []
    for i, (start, end) in enumerate(windows):
        if should_cancel is not None and should_cancel():
            _log.info("motion: cancelled mid-emit at window %d/%d", i, n)
            break
        signals.append(
            Signal(
                channel=CHANNEL,
                start=start,
                end=end,
                value=clamp(curve[i], 0.0, 1.0),
                confidence=1.0,
                meta={
                    "mode": "flow" if backend is None and mode == "flow" else ("backend" if backend else "absdiff"),
                    "raw": raw[i],
                },
            )
        )
    if on_progress is not None:
        on_progress(100.0, "done")
    return SignalTrack(channel=CHANNEL, signals=tuple(signals), present=True)


__all__ = [
    "CHANNEL",
    "DEFAULT_HOP_SEC",
    "DEFAULT_WIN_SEC",
    "FrameLoader",
    "MotionBackend",
    "MotionMode",
    "Signal",
    "SignalTrack",
    "compute_motion_signals",
    "farneback_flow_magnitude",
    "frame_diff_energy",
    "normalize_curve",
    "sample_windows",
]
