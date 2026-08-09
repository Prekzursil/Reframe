"""Pure gaze-correction geometry (C15) — the fully-verified half.

Everything here is real arithmetic over real arrays: no model weights, no video
decode, no network. The heavy half (YuNet instantiation, frame decode/encode,
ffmpeg mux) lives behind the ``GazeBackend`` Protocol in ``gaze_backend.py`` and
is ``# pragma: no cover``.

The tests that matter most are the LAST two groups: they build a synthetic eye
patch with a dark iris disc at a known offset, run the real locator and the real
warp map over it, and assert the iris actually MOVED by the intended amount.
That is an executable check on the geometry itself, not on plumbing.

HONEST SCOPE (see also the module docstring of ``features/gaze.py``): these
tests prove the geometry is self-consistent and that the warp displaces pixels as
specified. They do NOT and cannot establish that the result looks natural on real
human footage — that is a perceptual question this suite has no instrument for.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from media_studio.features.gaze import (
    DEFAULT_EYE_BOX_SCALE,
    IDX_LEFT_EYE,
    IDX_RIGHT_EYE,
    MAX_SHIFT_FRACTION,
    YUNET_ROW_WIDTH,
    EyeBox,
    EyePair,
    SkipReason,
    build_warp_maps,
    clamp_strength,
    eye_box,
    interocular_px,
    iris_shift,
    locate_iris,
    max_shift_px,
    skip_reason,
    yunet_eye_pairs,
)


def _row(
    *,
    box: tuple[float, float, float, float] = (10.0, 20.0, 60.0, 60.0),
    right_eye: tuple[float, float] = (25.0, 40.0),
    left_eye: tuple[float, float] = (55.0, 40.0),
    score: float = 0.9,
) -> list[float]:
    """One 15-column YuNet detection row (the shape ``detect()`` returns)."""
    x, y, w, h = box
    rex, rey = right_eye
    lex, ley = left_eye
    return [x, y, w, h, rex, rey, lex, ley, 40.0, 50.0, 30.0, 65.0, 50.0, 65.0, score]


def _eye_patch(
    size: int = 40,
    iris_center: tuple[float, float] = (20.0, 20.0),
    iris_radius: float = 7.0,
    *,
    sclera: int = 230,
    iris: int = 30,
) -> np.ndarray:
    """A synthetic grayscale eye: bright sclera with one dark iris disc."""
    yy, xx = np.mgrid[0:size, 0:size]
    dist = np.hypot(xx - iris_center[0], yy - iris_center[1])
    patch = np.full((size, size), sclera, dtype=np.uint8)
    patch[dist <= iris_radius] = iris
    return patch


# --------------------------------------------------------------------------- #
# yunet_eye_pairs — reuse the ALREADY-VENDORED detector's discarded columns
# --------------------------------------------------------------------------- #
def test_row_width_and_landmark_indices_match_the_yunet_contract() -> None:
    # The 15-col row is [x,y,w,h, 5 landmark xy pairs = 10 cols, score]; the eye
    # landmarks are the FIRST two pairs. _lightasd_infer._yunet_boxes reads only
    # cols 0-3 and -1, discarding exactly the columns this feature needs.
    assert YUNET_ROW_WIDTH == 15
    assert (IDX_RIGHT_EYE, IDX_LEFT_EYE) == (4, 6)


def test_yunet_eye_pairs_extracts_both_eye_centres_and_score() -> None:
    faces = np.array([_row(right_eye=(25.0, 40.0), left_eye=(55.0, 42.0), score=0.87)])
    pairs = yunet_eye_pairs(faces)
    assert pairs == [EyePair(right=(25.0, 40.0), left=(55.0, 42.0), score=0.87)]


def test_yunet_eye_pairs_handles_several_faces() -> None:
    faces = np.array([_row(score=0.9), _row(right_eye=(125.0, 40.0), left_eye=(155.0, 40.0), score=0.7)])
    assert [p.score for p in yunet_eye_pairs(faces)] == [0.9, 0.7]


def test_yunet_eye_pairs_of_none_is_empty() -> None:
    # detect() returns None when nothing clears the score threshold.
    assert yunet_eye_pairs(None) == []


def test_yunet_eye_pairs_of_empty_array_is_empty() -> None:
    assert yunet_eye_pairs(np.zeros((0, YUNET_ROW_WIDTH))) == []


def test_yunet_eye_pairs_skips_a_short_row() -> None:
    # A malformed/truncated row must be skipped, never indexed past its end.
    assert yunet_eye_pairs([[1.0, 2.0, 3.0]]) == []


def test_yunet_eye_pairs_accepts_a_plain_list_of_rows() -> None:
    assert yunet_eye_pairs([_row(score=0.5)])[0].score == 0.5


# --------------------------------------------------------------------------- #
# interocular_px — the scale reference every other length derives from
# --------------------------------------------------------------------------- #
def test_interocular_px_is_the_euclidean_eye_distance() -> None:
    pair = EyePair(right=(10.0, 10.0), left=(40.0, 50.0), score=0.9)
    assert interocular_px(pair) == pytest.approx(50.0)  # 30-40-50 triangle


def test_interocular_px_is_zero_for_coincident_eyes() -> None:
    pair = EyePair(right=(10.0, 10.0), left=(10.0, 10.0), score=0.9)
    assert interocular_px(pair) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# eye_box — scale-invariant, frame-clamped
# --------------------------------------------------------------------------- #
def test_eye_box_side_scales_with_interocular_distance() -> None:
    box = eye_box((100.0, 100.0), 100.0, frame_w=400, frame_h=400)
    assert box is not None
    assert box.w == box.h == int(round(100.0 * DEFAULT_EYE_BOX_SCALE))


def test_eye_box_is_centred_on_the_landmark_when_it_fits() -> None:
    box = eye_box((100.0, 100.0), 100.0, frame_w=400, frame_h=400)
    assert box is not None
    assert box.x + box.w / 2 == pytest.approx(100.0, abs=1.0)
    assert box.y + box.h / 2 == pytest.approx(100.0, abs=1.0)


def test_eye_box_clamps_to_the_frame_at_the_top_left() -> None:
    box = eye_box((2.0, 3.0), 100.0, frame_w=400, frame_h=400)
    assert box is not None
    assert box.x == 0
    assert box.y == 0


def test_eye_box_clamps_to_the_frame_at_the_bottom_right() -> None:
    box = eye_box((399.0, 399.0), 100.0, frame_w=400, frame_h=400)
    assert box is not None
    assert box.x + box.w <= 400
    assert box.y + box.h <= 400


def test_eye_box_is_none_when_it_would_be_degenerate() -> None:
    # A tiny interocular distance yields a sub-2px box: nothing to warp.
    assert eye_box((100.0, 100.0), 1.0, frame_w=400, frame_h=400) is None


def test_eye_box_is_none_when_wholly_outside_the_frame() -> None:
    assert eye_box((-500.0, -500.0), 100.0, frame_w=400, frame_h=400) is None


def test_eye_box_honours_an_explicit_scale() -> None:
    box = eye_box((100.0, 100.0), 100.0, frame_w=400, frame_h=400, scale=0.5)
    assert box is not None
    assert box.w == 50


# --------------------------------------------------------------------------- #
# clamp_strength / max_shift_px — the conservative caps
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("raw", "expected"), [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
def test_clamp_strength_passes_the_valid_range(raw: float, expected: float) -> None:
    assert clamp_strength(raw) == pytest.approx(expected)


@pytest.mark.parametrize(("raw", "expected"), [(-1.0, 0.0), (2.5, 1.0), (float("inf"), 1.0)])
def test_clamp_strength_clamps_out_of_range(raw: float, expected: float) -> None:
    assert clamp_strength(raw) == pytest.approx(expected)


def test_clamp_strength_of_nan_is_zero() -> None:
    # NaN must fail SAFE (no correction), never propagate into a warp map.
    assert clamp_strength(float("nan")) == 0.0


def test_clamp_strength_of_a_non_number_is_zero() -> None:
    assert clamp_strength("0.8") == 0.0  # type: ignore[arg-type]


def test_max_shift_px_is_a_fraction_of_interocular_distance() -> None:
    assert max_shift_px(100.0) == pytest.approx(100.0 * MAX_SHIFT_FRACTION)


def test_max_shift_fraction_is_conservative() -> None:
    # A cap above ~20% of interocular distance would slide the iris out of the
    # aperture and produce the classic uncanny result. Pin the intent.
    assert 0.0 < MAX_SHIFT_FRACTION <= 0.2


# --------------------------------------------------------------------------- #
# skip_reason — per-frame confidence gating (a skipped frame stays PRISTINE)
# --------------------------------------------------------------------------- #
def test_skip_reason_is_none_for_a_good_detection() -> None:
    assert skip_reason(EyePair(right=(0.0, 0.0), left=(60.0, 0.0), score=0.9)) is None


def test_skip_reason_flags_a_low_confidence_face() -> None:
    pair = EyePair(right=(0.0, 0.0), left=(60.0, 0.0), score=0.1)
    assert skip_reason(pair) == SkipReason.LOW_CONFIDENCE


def test_skip_reason_flags_eyes_too_small_to_warp() -> None:
    pair = EyePair(right=(0.0, 0.0), left=(6.0, 0.0), score=0.9)
    assert skip_reason(pair) == SkipReason.EYES_TOO_SMALL


def test_skip_reason_flags_an_implausible_head_roll() -> None:
    # Eyes near-vertical means the 5-point model is mis-fit or the head is
    # rotated far past what an aperture-centre target can represent.
    pair = EyePair(right=(0.0, 0.0), left=(5.0, 60.0), score=0.9)
    assert skip_reason(pair) == SkipReason.EXTREME_ROLL


def test_skip_reason_thresholds_are_overridable() -> None:
    pair = EyePair(right=(0.0, 0.0), left=(60.0, 0.0), score=0.5)
    assert skip_reason(pair, min_score=0.8) == SkipReason.LOW_CONFIDENCE
    assert skip_reason(pair, min_score=0.4) is None


# --------------------------------------------------------------------------- #
# locate_iris — REAL detection on a synthetic eye
# --------------------------------------------------------------------------- #
def test_locate_iris_finds_a_centred_disc() -> None:
    patch = _eye_patch(size=40, iris_center=(20.0, 20.0), iris_radius=7.0)
    cx, cy = locate_iris(patch)
    assert (cx, cy) == (pytest.approx(20.0, abs=1.0), pytest.approx(20.0, abs=1.0))


@pytest.mark.parametrize("center", [(12.0, 20.0), (28.0, 20.0), (20.0, 14.0), (20.0, 26.0)])
def test_locate_iris_follows_an_offset_disc(center: tuple[float, float]) -> None:
    # The whole feature depends on this: an off-camera gaze IS an offset iris.
    patch = _eye_patch(size=40, iris_center=center, iris_radius=6.0)
    cx, cy = locate_iris(patch)
    assert (cx, cy) == (pytest.approx(center[0], abs=1.5), pytest.approx(center[1], abs=1.5))


def test_locate_iris_of_a_uniform_patch_is_the_centre() -> None:
    # No dark region -> no evidence -> the neutral answer (no spurious shift).
    patch = np.full((30, 30), 200, dtype=np.uint8)
    cx, cy = locate_iris(patch)
    assert (cx, cy) == (pytest.approx(14.5, abs=0.6), pytest.approx(14.5, abs=0.6))


def test_locate_iris_accepts_a_colour_patch() -> None:
    gray = _eye_patch(size=40, iris_center=(15.0, 22.0), iris_radius=6.0)
    colour = np.repeat(gray[:, :, None], 3, axis=2)
    assert locate_iris(colour) == pytest.approx(locate_iris(gray), abs=0.75)


def test_locate_iris_rejects_an_empty_patch() -> None:
    with pytest.raises(ValueError, match="empty"):
        locate_iris(np.zeros((0, 0), dtype=np.uint8))


# --------------------------------------------------------------------------- #
# iris_shift — how far, and never further than the cap
# --------------------------------------------------------------------------- #
def test_iris_shift_points_from_the_iris_toward_the_target() -> None:
    box = EyeBox(x=0, y=0, w=40, h=40)
    # The aperture centre of a 40px box is (39/2, 39/2) = (19.5, 19.5) — the SAME
    # pixel-index convention locate_iris reports in (see the uniform-patch test).
    # Iris sits LEFT of that centre and level with it -> push RIGHT (+x), no y.
    dx, dy = iris_shift((14.0, 19.5), box, strength=1.0, max_shift=100.0)
    assert dx == pytest.approx(5.5)
    assert dy == pytest.approx(0.0, abs=1e-6)


def test_iris_shift_scales_linearly_with_strength() -> None:
    box = EyeBox(x=0, y=0, w=40, h=40)
    full = iris_shift((14.0, 19.5), box, strength=1.0, max_shift=100.0)
    half = iris_shift((14.0, 19.5), box, strength=0.5, max_shift=100.0)
    assert half[0] == pytest.approx(full[0] / 2)


def test_iris_shift_of_zero_strength_is_no_shift() -> None:
    box = EyeBox(x=0, y=0, w=40, h=40)
    assert iris_shift((5.0, 30.0), box, strength=0.0, max_shift=100.0) == (0.0, 0.0)


def test_iris_shift_is_clamped_to_max_shift() -> None:
    box = EyeBox(x=0, y=0, w=400, h=400)
    dx, dy = iris_shift((0.0, 0.0), box, strength=1.0, max_shift=5.0)
    assert math.hypot(dx, dy) == pytest.approx(5.0)


def test_iris_shift_is_zero_when_already_on_target() -> None:
    box = EyeBox(x=0, y=0, w=40, h=40)
    assert iris_shift((19.5, 19.5), box, strength=1.0, max_shift=10.0) == (0.0, 0.0)


def test_iris_shift_honours_an_explicit_target() -> None:
    # The aperture centre is only an APPROXIMATION of "looking at camera"; the
    # target is therefore injectable rather than hardcoded.
    box = EyeBox(x=0, y=0, w=40, h=40)
    dx, _dy = iris_shift((20.0, 20.0), box, strength=1.0, max_shift=10.0, target=(30.0, 20.0))
    assert dx == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# build_warp_maps — exact properties of the displacement field
# --------------------------------------------------------------------------- #
def test_warp_maps_have_the_right_shape_and_dtype() -> None:
    map_x, map_y = build_warp_maps(20, 16, iris=(10.0, 8.0), radius=6.0, shift=(2.0, 0.0))
    assert map_x.shape == map_y.shape == (16, 20)
    assert map_x.dtype == map_y.dtype == np.float32


def test_zero_shift_yields_the_identity_map() -> None:
    # The no-op case must be pixel-exact, so a skipped/zero-strength eye is
    # provably untouched rather than resampled.
    map_x, map_y = build_warp_maps(12, 10, iris=(6.0, 5.0), radius=4.0, shift=(0.0, 0.0))
    yy, xx = np.mgrid[0:10, 0:12]
    assert np.allclose(map_x, xx)
    assert np.allclose(map_y, yy)


def test_at_the_iris_centre_the_map_samples_the_full_shift_back() -> None:
    # remap semantics: destination reads from source = p - displacement.
    map_x, map_y = build_warp_maps(41, 41, iris=(20.0, 20.0), radius=8.0, shift=(3.0, -2.0))
    assert map_x[20, 20] == pytest.approx(20.0 - 3.0, abs=1e-4)
    assert map_y[20, 20] == pytest.approx(20.0 + 2.0, abs=1e-4)


def test_outside_the_radius_the_map_is_identity() -> None:
    # The eyelids and sclera edge must not move, or the eye tears visibly.
    map_x, map_y = build_warp_maps(41, 41, iris=(20.0, 20.0), radius=6.0, shift=(4.0, 0.0))
    assert map_x[0, 0] == pytest.approx(0.0, abs=1e-4)
    assert map_y[0, 0] == pytest.approx(0.0, abs=1e-4)
    assert map_x[20, 40] == pytest.approx(40.0, abs=1e-4)


def test_the_falloff_is_monotone_from_the_iris_outward() -> None:
    map_x, _map_y = build_warp_maps(81, 41, iris=(40.0, 20.0), radius=20.0, shift=(4.0, 0.0))
    # Displacement magnitude along the row through the iris, going outward.
    disp = [abs(map_x[20, x] - x) for x in range(40, 81)]
    assert disp[0] == pytest.approx(4.0, abs=1e-4)
    assert disp[-1] == pytest.approx(0.0, abs=1e-4)
    assert all(a >= b - 1e-6 for a, b in zip(disp, disp[1:], strict=False))


def test_build_warp_maps_rejects_a_non_positive_radius() -> None:
    with pytest.raises(ValueError, match="radius"):
        build_warp_maps(10, 10, iris=(5.0, 5.0), radius=0.0, shift=(1.0, 0.0))


def test_build_warp_maps_rejects_a_degenerate_size() -> None:
    with pytest.raises(ValueError, match="size"):
        build_warp_maps(0, 10, iris=(5.0, 5.0), radius=3.0, shift=(1.0, 0.0))


# --------------------------------------------------------------------------- #
# END-TO-END on synthetic pixels: does the iris ACTUALLY move as intended?
# --------------------------------------------------------------------------- #
def _remap_bilinear(patch: np.ndarray, map_x: np.ndarray, map_y: np.ndarray) -> np.ndarray:
    """Bilinear gather, mirroring cv2.remap semantics without importing cv2.

    Kept in the TEST (not the module) deliberately: the production path uses
    cv2.remap, and re-implementing it here means this assertion checks the MAP,
    which is the thing this module is responsible for.
    """
    h, w = patch.shape[:2]
    xs = np.clip(map_x, 0, w - 1)
    ys = np.clip(map_y, 0, h - 1)
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    fx = (xs - x0)[..., None] if patch.ndim == 3 else (xs - x0)
    fy = (ys - y0)[..., None] if patch.ndim == 3 else (ys - y0)
    src = patch.astype(np.float64)
    top = src[y0, x0] * (1 - fx) + src[y0, x1] * fx
    bottom = src[y1, x0] * (1 - fx) + src[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


def test_the_warp_moves_a_real_iris_disc_by_the_requested_shift() -> None:
    """The load-bearing executable check: locate -> shift -> warp -> re-locate."""
    patch = _eye_patch(size=61, iris_center=(24.0, 30.0), iris_radius=7.0)
    before = locate_iris(patch)
    assert before[0] == pytest.approx(24.0, abs=1.0)

    box = EyeBox(x=0, y=0, w=61, h=61)
    shift = iris_shift(before, box, strength=1.0, max_shift=8.0)
    map_x, map_y = build_warp_maps(61, 61, iris=before, radius=16.0, shift=shift)
    warped = _remap_bilinear(patch, map_x, map_y)

    after = locate_iris(warped)
    # The iris moved toward the aperture centre by (approximately) the shift.
    assert after[0] - before[0] == pytest.approx(shift[0], abs=1.5)
    assert after[0] > before[0]  # it moved RIGHT, toward centre


def test_the_warp_leaves_the_patch_border_untouched() -> None:
    """Eyelid/sclera preservation: outside the radius the pixels are identical."""
    patch = _eye_patch(size=61, iris_center=(24.0, 30.0), iris_radius=7.0)
    map_x, map_y = build_warp_maps(61, 61, iris=(24.0, 30.0), radius=14.0, shift=(6.0, 0.0))
    warped = _remap_bilinear(patch, map_x, map_y)
    assert warped[0, :] == pytest.approx(patch[0, :].astype(np.float64))
    assert warped[:, 0] == pytest.approx(patch[:, 0].astype(np.float64))


def test_a_zero_shift_warp_is_pixel_identical() -> None:
    """A skipped or zero-strength eye must come back bit-for-bit unchanged."""
    patch = _eye_patch(size=41, iris_center=(20.0, 20.0), iris_radius=6.0)
    map_x, map_y = build_warp_maps(41, 41, iris=(20.0, 20.0), radius=10.0, shift=(0.0, 0.0))
    warped = _remap_bilinear(patch, map_x, map_y)
    assert np.array_equal(warped, patch.astype(np.float64))
