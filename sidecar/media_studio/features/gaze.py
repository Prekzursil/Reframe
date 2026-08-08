"""Eye-contact / gaze correction (C15) — the PURE, fully-covered half.

Redirects a speaker's apparent gaze toward the camera when they are reading from
an off-camera script, by locating each iris and warping it toward the eye
aperture's centre. Everything in this module is arithmetic over arrays: no model
weights, no video decode, no network, no GPU. The heavy half (YuNet
instantiation, frame decode/encode, ffmpeg mux) sits behind the
``GazeBackend`` Protocol in ``gaze_backend.py`` and is ``# pragma: no cover``.

WHY THIS IS GEOMETRIC AND NOT GENERATIVE — the licence constraint
----------------------------------------------------------------
A commercial build here ships only MIT / Apache-2.0 / BSD components. This
engine therefore uses:

  * **YuNet** (``opencv/face_detection_yunet``, MIT — (c) 2020 Shiqi Yu) for the
    eye landmarks — the SAME sha256-pinned ONNX the ASD path already vendors and
    resolves via ``reframe_claudeshorts.resolve_yunet_model_path``. NO second
    face detector is introduced, and no new weight is downloaded.
  * **numpy / OpenCV** (BSD / Apache-2.0) for the iris locator and the warp.

There are NO learned gaze-redirection weights in this path, so there is no
model licence to accept. The stronger generative alternatives were surveyed and
are NOT adopted here; see ``docs/wiring/WIRING-gaze.md`` for the option table
and the owner decision it is waiting on.

REUSING THE COLUMNS THE ASD PATH THROWS AWAY
--------------------------------------------
``cv2.FaceDetectorYN.detect`` returns 15-column rows:
``[x, y, w, h, <5 landmark xy pairs = 10 cols>, score]``. The ASD front-end's
``_lightasd_infer._yunet_boxes`` reads only columns 0-3 and -1 — it DISCARDS the
ten landmark columns. The first two landmark pairs are the right and left eye
centres, which is exactly what this feature needs, so
:func:`yunet_eye_pairs` recovers them from the same detection rows.
:func:`yunet_eye_pairs` is kept HERE rather than added to ``_lightasd_infer`` so
the ASD module is untouched, but the row contract is shared and the two helpers
must stay in step (:func:`test_row_width_and_landmark_indices_match_the_yunet_contract`
pins the indices).

WHAT THIS CAN AND CANNOT DO — read before trusting output
---------------------------------------------------------
Gaze correction fails VISIBLY when it fails ("uncanny eyes"), so the engine is
deliberately conservative and its limits are stated rather than hidden:

  * The correction target is the eye APERTURE CENTRE, which equals "looking at
    camera" only for a roughly frontal face. It is an approximation, which is
    why :func:`iris_shift` takes an injectable ``target``.
  * :data:`MAX_SHIFT_FRACTION` caps displacement at 12% of interocular
    distance. A larger shift slides the iris toward/past the eyelid and is the
    classic uncanny result.
  * :func:`skip_reason` gates every frame. A low-confidence detection, eyes too
    small to carry a warp, or an implausible head roll SKIPS that frame, leaving
    it PRISTINE (the same presence-gating discipline the watermark-removal path
    uses). Skipping is always preferred to a bad warp.
  * The warp has a flat core and a smooth falloff to zero at
    :data:`WARP_CORE_FRACTION` of the radius outward, so the eyelids and the
    sclera boundary do not move. A moving eyelid edge is what makes a warped eye
    read as broken.

NOT HANDLED, and no attempt is made to hide it: eyeglasses (specular highlights
and frame edges are warped like anything else), large head yaw, heavy eyelid
occlusion, motion blur, and very low-resolution faces. Those are the cases
:func:`skip_reason` is meant to drop rather than mangle, but its thresholds are
geometric proxies, not a yaw estimator.

THE ETHICS GATE IS NOT OPTIONAL
-------------------------------
This module alters a real person's face. ``media_studio.models.likeness`` is the
FAIL-CLOSED attestation gate every entry point must pass through first; see
:func:`media_studio.models.likeness.resolve_attestation`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from ..util import get_logger

log = get_logger("media_studio.features.gaze")

# --------------------------------------------------------------------------- #
# The YuNet detection-row contract (see the module docstring)
# --------------------------------------------------------------------------- #
#: Columns in one ``cv2.FaceDetectorYN.detect`` row.
YUNET_ROW_WIDTH: int = 15
#: Column of the right-eye landmark x (y is the next column).
IDX_RIGHT_EYE: int = 4
#: Column of the left-eye landmark x (y is the next column).
IDX_LEFT_EYE: int = 6

# --------------------------------------------------------------------------- #
# Conservative defaults (every one is a deliberate quality/safety trade-off)
# --------------------------------------------------------------------------- #
#: Eye-crop side length as a fraction of interocular distance. Scale-invariant,
#: so it holds for a close-up and for a wide shot alike.
DEFAULT_EYE_BOX_SCALE: float = 0.34
#: Hard cap on iris displacement, as a fraction of interocular distance. Above
#: roughly 20% the iris leaves the aperture and the result reads as uncanny.
MAX_SHIFT_FRACTION: float = 0.12
#: Default correction strength (0 = off, 1 = fully re-centre). Deliberately not
#: 1.0: a partial correction reads as natural where a full one often does not.
DEFAULT_STRENGTH: float = 0.7
#: Detection-confidence floor. Matches the ASD path's YuNet threshold.
MIN_FACE_SCORE: float = 0.6
#: Interocular distance below which an eye cannot carry a warp (too few pixels).
MIN_INTEROCULAR_PX: float = 24.0
#: Max |dy| / |dx| between the eye landmarks before the fit is judged implausible.
MAX_ROLL_RATIO: float = 0.5
#: Darkest quantile treated as iris/pupil evidence by :func:`locate_iris`.
IRIS_DARK_QUANTILE: float = 0.25
#: Fraction of the warp radius that moves RIGIDLY before the falloff starts, so
#: the iris translates as a disc instead of smearing.
WARP_CORE_FRACTION: float = 0.6


class GazeError(RuntimeError):
    """Base typed failure for the gaze-correction feature."""


class GazeUnavailableError(GazeError):
    """Raised when gaze correction was EXPLICITLY requested but cannot run.

    Mirrors ``reframe_multispeaker.MultiSpeakerUnavailableError``: an explicit
    request with the YuNet model absent NAMES the real cause rather than
    silently degrading to a pass-through.
    """


class SkipReason(StrEnum):
    """Why a frame/face was left PRISTINE instead of corrected.

    A :class:`enum.StrEnum` so it crosses the RPC boundary as a plain JSON
    string while still comparing as an enum member in-process.
    """

    LOW_CONFIDENCE = "low-confidence"
    EYES_TOO_SMALL = "eyes-too-small"
    EXTREME_ROLL = "extreme-roll"


@dataclass(frozen=True)
class EyePair:
    """The two eye-centre landmarks of one detected face, plus its score."""

    right: tuple[float, float]
    left: tuple[float, float]
    score: float


@dataclass(frozen=True)
class EyeBox:
    """An integer, frame-clamped crop rectangle around one eye."""

    x: int
    y: int
    w: int
    h: int


# --------------------------------------------------------------------------- #
# Landmark recovery
# --------------------------------------------------------------------------- #
def yunet_eye_pairs(faces: Any) -> list[EyePair]:
    """Extract the eye-centre landmarks from ``cv2.FaceDetectorYN.detect`` rows.

    ``faces`` is the detector's second return value: an ndarray of 15-column
    rows, or ``None`` when nothing cleared the score threshold. A row shorter
    than :data:`YUNET_ROW_WIDTH` is SKIPPED rather than indexed past its end, so
    a malformed detection degrades to "no face here" instead of raising.

    PURE (indexing + float conversion only), which is why it is unit-tested for
    real while the ``cv2`` call stays in the heavy seam.
    """
    if faces is None:
        return []
    pairs: list[EyePair] = []
    for row in faces:
        if len(row) < YUNET_ROW_WIDTH:
            continue
        pairs.append(
            EyePair(
                right=(float(row[IDX_RIGHT_EYE]), float(row[IDX_RIGHT_EYE + 1])),
                left=(float(row[IDX_LEFT_EYE]), float(row[IDX_LEFT_EYE + 1])),
                score=float(row[-1]),
            )
        )
    return pairs


def interocular_px(pair: EyePair) -> float:
    """Distance between the eye centres — the scale every length derives from."""
    return math.hypot(pair.left[0] - pair.right[0], pair.left[1] - pair.right[1])


def eye_box(
    center: tuple[float, float],
    interocular: float,
    *,
    frame_w: int,
    frame_h: int,
    scale: float = DEFAULT_EYE_BOX_SCALE,
) -> EyeBox | None:
    """A square crop around one eye, sized from ``interocular`` and frame-clamped.

    Returns ``None`` when there is nothing usable to warp: a box that would be
    smaller than 2px (face too small / degenerate landmarks), or one that lies
    wholly outside the frame. ``None`` means "skip this eye", never "warp
    something arbitrary".
    """
    side = min(int(round(interocular * scale)), frame_w, frame_h)
    if side < 2:
        return None
    left = center[0] - side / 2.0
    top = center[1] - side / 2.0
    if left + side <= 0 or top + side <= 0 or left >= frame_w or top >= frame_h:
        return None
    x = max(0, min(int(round(left)), frame_w - side))
    y = max(0, min(int(round(top)), frame_h - side))
    return EyeBox(x=x, y=y, w=side, h=side)


# --------------------------------------------------------------------------- #
# Caps and gating
# --------------------------------------------------------------------------- #
def clamp_strength(value: float) -> float:
    """Correction strength clamped into ``0.0..1.0``; anything invalid is 0.0.

    FAILS SAFE: a non-numeric or NaN strength becomes 0.0 (no correction) rather
    than propagating into a warp map, where NaN would poison every sampled pixel.
    """
    if not isinstance(value, (int, float)):
        return 0.0
    numeric = float(value)
    if math.isnan(numeric):
        return 0.0
    return max(0.0, min(1.0, numeric))


def max_shift_px(interocular: float) -> float:
    """The hard displacement cap in pixels for this face's scale."""
    return interocular * MAX_SHIFT_FRACTION


def skip_reason(
    pair: EyePair,
    *,
    min_score: float = MIN_FACE_SCORE,
    min_interocular: float = MIN_INTEROCULAR_PX,
    max_roll_ratio: float = MAX_ROLL_RATIO,
) -> SkipReason | None:
    """Why this face should be left alone, or ``None`` when it is safe to correct.

    Checked in increasing cost order: confidence, then size, then plausibility of
    the landmark fit. The roll test is written as ``dy > dx * ratio`` rather than
    a division so vertically-aligned landmarks (``dx == 0``) fall out as
    :attr:`SkipReason.EXTREME_ROLL` instead of dividing by zero.
    """
    if pair.score < min_score:
        return SkipReason.LOW_CONFIDENCE
    if interocular_px(pair) < min_interocular:
        return SkipReason.EYES_TOO_SMALL
    dx = abs(pair.left[0] - pair.right[0])
    dy = abs(pair.left[1] - pair.right[1])
    if dy > dx * max_roll_ratio:
        return SkipReason.EXTREME_ROLL
    return None


# --------------------------------------------------------------------------- #
# Iris location
# --------------------------------------------------------------------------- #
def locate_iris(patch: Any) -> tuple[float, float]:
    """Locate the iris/pupil inside an eye crop, in patch-local pixel indices.

    The iris is the dark region: pixels below the :data:`IRIS_DARK_QUANTILE`
    quantile are weighted by how far below it they sit, and the weighted centroid
    is returned. Classical and deterministic — no learned weights, so nothing
    here carries a model licence.

    When there is no dark evidence at all (a uniform patch — a closed eye, a
    blown-out highlight), the geometric centre is returned so the resulting shift
    is zero rather than an arbitrary jump. Accepts grayscale or colour.
    """
    arr = np.asarray(patch)
    if arr.size == 0:
        raise ValueError("locate_iris: empty patch")
    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    arr = arr.astype(np.float64)
    height, width = arr.shape
    threshold = float(np.quantile(arr, IRIS_DARK_QUANTILE))
    weights = np.clip(threshold - arr, 0.0, None)
    total = float(weights.sum())
    if total <= 0.0:
        return ((width - 1) / 2.0, (height - 1) / 2.0)
    yy, xx = np.mgrid[0:height, 0:width]
    return (float((weights * xx).sum() / total), float((weights * yy).sum() / total))


def iris_shift(
    iris: tuple[float, float],
    box: EyeBox,
    *,
    strength: float,
    max_shift: float,
    target: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """The displacement to apply to the iris, capped at ``max_shift`` pixels.

    ``target`` defaults to the box's aperture centre in the SAME pixel-index
    convention :func:`locate_iris` reports (``(w-1)/2``, ``(h-1)/2``). It is
    injectable because the aperture centre only approximates "looking at camera"
    for a frontal face — see the module docstring.

    Returns ``(0.0, 0.0)`` for zero strength or an already-centred iris, so the
    caller can cheaply detect a no-op and leave the frame untouched.
    """
    scaled = clamp_strength(strength)
    tx, ty = target if target is not None else ((box.w - 1) / 2.0, (box.h - 1) / 2.0)
    dx = (tx - iris[0]) * scaled
    dy = (ty - iris[1]) * scaled
    magnitude = math.hypot(dx, dy)
    if magnitude <= 0.0:
        return (0.0, 0.0)
    if magnitude > max_shift:
        ratio = max_shift / magnitude
        return (dx * ratio, dy * ratio)
    return (dx, dy)


# --------------------------------------------------------------------------- #
# The warp field
# --------------------------------------------------------------------------- #
def _falloff(radius_map: np.ndarray, radius: float) -> np.ndarray:
    """Weight 1.0 inside the rigid core, smoothly to 0.0 at ``radius``.

    A flat core (:data:`WARP_CORE_FRACTION`) makes the iris translate as a disc;
    the smoothstep tail brings the displacement to exactly zero at the boundary
    so the eyelids and sclera edge stay put.
    """
    core = radius * WARP_CORE_FRACTION
    span = max(radius - core, 1e-6)
    t = np.clip((radius_map - core) / span, 0.0, 1.0)
    return 1.0 - (t * t * (3.0 - 2.0 * t))


def build_warp_maps(
    width: int,
    height: int,
    *,
    iris: tuple[float, float],
    radius: float,
    shift: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Build ``(map_x, map_y)`` for ``cv2.remap`` over one eye crop.

    ``remap`` semantics are DESTINATION -> SOURCE, so to move content BY
    ``+shift`` each destination pixel must sample from ``p - shift``; the maps
    are therefore ``p - shift * falloff(|p - iris|)``.

    A zero ``shift`` yields the exact identity map, so a skipped or
    zero-strength eye is provably untouched rather than resampled (resampling
    alone would soften it).

    Returns ``float32`` arrays of shape ``(height, width)`` — the dtype
    ``cv2.remap`` wants for ``map1``/``map2``.
    """
    if width < 1 or height < 1:
        raise ValueError(f"build_warp_maps: size must be at least 1x1, got {width}x{height}")
    if radius <= 0:
        raise ValueError(f"build_warp_maps: radius must be > 0, got {radius}")
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    xx = grid_x.astype(np.float64)
    yy = grid_y.astype(np.float64)
    weight = _falloff(np.hypot(xx - iris[0], yy - iris[1]), radius)
    map_x = (xx - shift[0] * weight).astype(np.float32)
    map_y = (yy - shift[1] * weight).astype(np.float32)
    return map_x, map_y


__all__ = [
    "DEFAULT_EYE_BOX_SCALE",
    "DEFAULT_STRENGTH",
    "IDX_LEFT_EYE",
    "IDX_RIGHT_EYE",
    "IRIS_DARK_QUANTILE",
    "MAX_ROLL_RATIO",
    "MAX_SHIFT_FRACTION",
    "MIN_FACE_SCORE",
    "MIN_INTEROCULAR_PX",
    "WARP_CORE_FRACTION",
    "YUNET_ROW_WIDTH",
    "EyeBox",
    "EyePair",
    "GazeError",
    "GazeUnavailableError",
    "SkipReason",
    "build_warp_maps",
    "clamp_strength",
    "eye_box",
    "interocular_px",
    "iris_shift",
    "locate_iris",
    "max_shift_px",
    "skip_reason",
    "yunet_eye_pairs",
]
