"""Tests for the WU R4 source-chyron safe-zone detection (N6).

These exercise the PURE detection + safe-zone logic exhaustively (100% line +
branch) with synthetic, path-injected text boxes. The heavy OCR half lives behind
the :class:`~media_studio.features.chyron_safezone.OcrBackend` seam and is faked
here; its real implementation's import surface is covered separately.
"""

from __future__ import annotations

import math

import pytest
from media_studio.features import chyron_safezone as cz

# --------------------------------------------------------------------------- #
# TextBox
# --------------------------------------------------------------------------- #


def test_textbox_properties() -> None:
    box = cz.TextBox(x=0.1, y=0.2, w=0.4, h=0.1, text="Sursa", confidence=0.9)
    assert box.right == pytest.approx(0.5)
    assert box.bottom == pytest.approx(0.3)
    assert box.center_y == pytest.approx(0.25)
    assert box.center_x == pytest.approx(0.3)


@pytest.mark.parametrize("w,h", [(0.0, 0.1), (0.1, 0.0), (-0.1, 0.1)])
def test_textbox_rejects_non_positive_size(w: float, h: float) -> None:
    with pytest.raises(cz.ChyronError, match="positive"):
        cz.TextBox(x=0.1, y=0.1, w=w, h=h)


@pytest.mark.parametrize("x,y", [(-0.01, 0.1), (1.01, 0.1), (0.1, -0.01), (0.1, 1.01)])
def test_textbox_rejects_out_of_unit_origin(x: float, y: float) -> None:
    with pytest.raises(cz.ChyronError, match=r"\[0, 1\]"):
        cz.TextBox(x=x, y=y, w=0.05, h=0.05)


def test_textbox_rejects_overflow_right() -> None:
    with pytest.raises(cz.ChyronError, match="fit within"):
        cz.TextBox(x=0.9, y=0.1, w=0.5, h=0.05)


def test_textbox_rejects_overflow_bottom() -> None:
    with pytest.raises(cz.ChyronError, match="fit within"):
        cz.TextBox(x=0.1, y=0.9, w=0.05, h=0.5)


@pytest.mark.parametrize("conf", [-0.01, 1.01])
def test_textbox_rejects_bad_confidence(conf: float) -> None:
    with pytest.raises(cz.ChyronError, match="confidence"):
        cz.TextBox(x=0.1, y=0.1, w=0.05, h=0.05, confidence=conf)


def test_textbox_from_pixels() -> None:
    box = cz.TextBox.from_pixels(192, 972, 768, 54, frame_width=1920, frame_height=1080, text="bar", confidence=0.8)
    assert box.x == pytest.approx(0.1)
    assert box.y == pytest.approx(0.9)
    assert box.w == pytest.approx(0.4)
    assert box.h == pytest.approx(0.05)
    assert box.text == "bar"
    assert box.confidence == pytest.approx(0.8)


@pytest.mark.parametrize("fw,fh", [(0, 1080), (1920, 0)])
def test_textbox_from_pixels_rejects_bad_frame(fw: int, fh: int) -> None:
    with pytest.raises(cz.ChyronError, match="frame dimensions"):
        cz.TextBox.from_pixels(1, 1, 1, 1, frame_width=fw, frame_height=fh)


# --------------------------------------------------------------------------- #
# Band clustering
# --------------------------------------------------------------------------- #


def _box(x: float, y: float, w: float, h: float, **kw: object) -> cz.TextBox:
    return cz.TextBox(x=x, y=y, w=w, h=h, **kw)  # type: ignore[arg-type]


def test_cluster_empty_returns_empty() -> None:
    assert cz.cluster_boxes_into_bands(()) == ()


def test_cluster_negative_gap_raises() -> None:
    with pytest.raises(cz.ChyronError, match="vertical_gap"):
        cz.cluster_boxes_into_bands((_box(0.1, 0.1, 0.1, 0.05),), vertical_gap=-0.1)


def test_cluster_single_box() -> None:
    bands = cz.cluster_boxes_into_bands((_box(0.2, 0.9, 0.3, 0.05),))
    assert len(bands) == 1
    band = bands[0]
    assert band.top == pytest.approx(0.9)
    assert band.bottom == pytest.approx(0.95)
    assert band.left == pytest.approx(0.2)
    assert band.right == pytest.approx(0.5)
    assert band.height == pytest.approx(0.05)
    assert band.width == pytest.approx(0.3)
    assert band.center_y == pytest.approx(0.925)
    assert band.center_x == pytest.approx(0.35)


def test_cluster_merges_words_on_same_line() -> None:
    bands = cz.cluster_boxes_into_bands((_box(0.1, 0.9, 0.2, 0.05), _box(0.35, 0.9, 0.2, 0.05)), vertical_gap=0.02)
    assert len(bands) == 1
    assert bands[0].left == pytest.approx(0.1)
    assert bands[0].right == pytest.approx(0.55)


def test_cluster_separates_distant_lines() -> None:
    bands = cz.cluster_boxes_into_bands((_box(0.1, 0.05, 0.5, 0.05), _box(0.1, 0.9, 0.5, 0.05)), vertical_gap=0.02)
    assert len(bands) == 2
    assert bands[0].center_y < bands[1].center_y


def test_cluster_keeps_outer_bottom_when_nested_box_merges() -> None:
    # Second box is vertically inside the first -> max() must keep the tall bottom.
    bands = cz.cluster_boxes_into_bands((_box(0.1, 0.8, 0.5, 0.15), _box(0.2, 0.82, 0.1, 0.02)), vertical_gap=0.0)
    assert len(bands) == 1
    assert bands[0].bottom == pytest.approx(0.95)


# --------------------------------------------------------------------------- #
# Band classification
# --------------------------------------------------------------------------- #


def test_classify_narrow_band_is_not_chyron() -> None:
    band = cz.Band(top=0.9, bottom=0.95, left=0.4, right=0.6)
    assert cz.classify_band(band, min_width=0.35) is None


def test_classify_top_edge() -> None:
    band = cz.Band(top=0.02, bottom=0.08, left=0.0, right=0.9)
    assert cz.classify_band(band, edge_margin=0.18) == cz.EDGE_TOP


def test_classify_bottom_edge() -> None:
    band = cz.Band(top=0.9, bottom=0.97, left=0.0, right=0.9)
    assert cz.classify_band(band, edge_margin=0.18) == cz.EDGE_BOTTOM


def test_classify_middle_band_is_none() -> None:
    band = cz.Band(top=0.45, bottom=0.55, left=0.0, right=0.9)
    assert cz.classify_band(band, edge_margin=0.18) is None


# --------------------------------------------------------------------------- #
# detect_chyrons (full pure pipeline)
# --------------------------------------------------------------------------- #


def _bottom_bar_frame() -> tuple[cz.TextBox, ...]:
    return (_box(0.05, 0.9, 0.9, 0.06, text="Sursa: Facebook"),)


def test_detect_requires_at_least_one_frame() -> None:
    with pytest.raises(cz.ChyronError, match="at least one"):
        cz.detect_chyrons(())


@pytest.mark.parametrize("persistence", [0.0, -0.1, 1.5])
def test_detect_rejects_bad_persistence(persistence: float) -> None:
    with pytest.raises(cz.ChyronError, match="persistence"):
        cz.detect_chyrons((_bottom_bar_frame(),), persistence=persistence)


def test_detect_rejects_negative_y_tol() -> None:
    with pytest.raises(cz.ChyronError, match="y_tol"):
        cz.detect_chyrons((_bottom_bar_frame(),), y_tol=-0.01)


@pytest.mark.parametrize("mc", [-0.1, 1.1])
def test_detect_rejects_bad_min_confidence(mc: float) -> None:
    with pytest.raises(cz.ChyronError, match="min_confidence"):
        cz.detect_chyrons((_bottom_bar_frame(),), min_confidence=mc)


def test_detect_finds_persistent_bottom_bar() -> None:
    frames = tuple(_bottom_bar_frame() for _ in range(4))
    sz = cz.detect_chyrons(frames, persistence=0.5)
    assert len(sz.bands) == 1
    band = sz.bands[0]
    assert band.edge == cz.EDGE_BOTTOM
    assert band.coverage == pytest.approx(1.0)
    assert sz.has_bottom
    assert not sz.has_top
    assert sz.bottom_bands == (band,)
    assert sz.top_bands == ()


def test_detect_finds_both_top_and_bottom_sorted() -> None:
    top = _box(0.05, 0.02, 0.9, 0.05, text="LIVE")
    bottom = _box(0.05, 0.9, 0.9, 0.06, text="Sursa")
    frames = tuple((top, bottom) for _ in range(3))
    sz = cz.detect_chyrons(frames)
    assert [b.edge for b in sz.bands] == [cz.EDGE_TOP, cz.EDGE_BOTTOM]
    assert sz.has_top and sz.has_bottom


def test_detect_ignores_transient_caption() -> None:
    # A bottom bar in only 1 of 4 frames is below the persistence floor.
    frames = (
        _bottom_bar_frame(),
        (),
        (),
        (),
    )
    sz = cz.detect_chyrons(frames, persistence=0.5)
    assert sz.bands == ()


def test_detect_filters_low_confidence_boxes() -> None:
    frames = tuple((_box(0.05, 0.9, 0.9, 0.06, confidence=0.2),) for _ in range(4))
    sz = cz.detect_chyrons(frames, min_confidence=0.5)
    assert sz.bands == ()


def test_detect_ignores_narrow_middle_text() -> None:
    frames = tuple((_box(0.4, 0.5, 0.2, 0.05),) for _ in range(4))
    sz = cz.detect_chyrons(frames)
    assert sz.bands == ()


# --------------------------------------------------------------------------- #
# _group_candidates (direct, to pin every branch arc)
# --------------------------------------------------------------------------- #


def test_group_candidates_branches() -> None:
    b_bottom_a = cz.Band(top=0.90, bottom=0.96, left=0.0, right=0.9)
    b_bottom_close = cz.Band(top=0.905, bottom=0.965, left=0.1, right=0.95)
    b_bottom_far = cz.Band(top=0.70, bottom=0.76, left=0.0, right=0.9)
    b_top = cz.Band(top=0.02, bottom=0.08, left=0.0, right=0.9)
    candidates = [
        (cz.EDGE_BOTTOM, b_bottom_a),
        (cz.EDGE_TOP, b_top),  # different edge -> A False path
        (cz.EDGE_BOTTOM, b_bottom_close),  # same edge, within tol -> merge
        (cz.EDGE_BOTTOM, b_bottom_far),  # same edge, beyond tol -> new group
    ]
    groups = cz._group_candidates(candidates, y_tol=0.05)
    sizes = sorted(len(members) for _edge, members in groups)
    assert sizes == [1, 1, 2]


# --------------------------------------------------------------------------- #
# caption_safe_y_range
# --------------------------------------------------------------------------- #


def test_caption_safe_range_no_chyrons() -> None:
    sz = cz.SafeZone(bands=())
    assert cz.caption_safe_y_range(sz) == (0.0, 1.0)


def test_caption_safe_range_pushes_below_top_and_above_bottom() -> None:
    sz = cz.SafeZone(
        bands=(
            cz.ChyronBand(top=0.0, bottom=0.1, left=0.0, right=0.9, edge=cz.EDGE_TOP, coverage=1.0),
            cz.ChyronBand(top=0.88, bottom=0.97, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),
        )
    )
    top, bottom = cz.caption_safe_y_range(sz, padding=0.02)
    assert top == pytest.approx(0.12)
    assert bottom == pytest.approx(0.86)


def test_caption_safe_range_keeps_default_when_band_outside_default() -> None:
    # Band is below the requested default_bottom -> limit (band.top) not lower -> default kept.
    sz = cz.SafeZone(
        bands=(cz.ChyronBand(top=0.9, bottom=0.97, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),)
    )
    assert cz.caption_safe_y_range(sz, default_bottom=0.5, padding=0.0) == (0.0, 0.5)


def test_caption_safe_range_keeps_default_when_top_band_above_default_top() -> None:
    sz = cz.SafeZone(bands=(cz.ChyronBand(top=0.0, bottom=0.05, left=0.0, right=0.9, edge=cz.EDGE_TOP, coverage=1.0),))
    assert cz.caption_safe_y_range(sz, default_top=0.2, padding=0.0) == (0.2, 1.0)


def test_caption_safe_range_negative_padding_raises() -> None:
    with pytest.raises(cz.ChyronError, match="padding"):
        cz.caption_safe_y_range(cz.SafeZone(bands=()), padding=-0.1)


def test_caption_safe_range_bad_defaults_raise() -> None:
    with pytest.raises(cz.ChyronError, match="default_top"):
        cz.caption_safe_y_range(cz.SafeZone(bands=()), default_top=0.8, default_bottom=0.2)


def test_caption_safe_range_no_room_raises() -> None:
    sz = cz.SafeZone(
        bands=(
            cz.ChyronBand(top=0.0, bottom=0.6, left=0.0, right=0.9, edge=cz.EDGE_TOP, coverage=1.0),
            cz.ChyronBand(top=0.4, bottom=1.0, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),
        )
    )
    with pytest.raises(cz.ChyronError, match="no safe caption band"):
        cz.caption_safe_y_range(sz, padding=0.0)


# --------------------------------------------------------------------------- #
# overlap / avoidance
# --------------------------------------------------------------------------- #


def _bottom_safezone() -> cz.SafeZone:
    return cz.SafeZone(
        bands=(cz.ChyronBand(top=0.9, bottom=0.97, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),)
    )


def test_overlap_fraction_full_inside() -> None:
    frac = cz.chyron_overlap_fraction((0.1, 0.91, 0.2, 0.04), _bottom_safezone())
    assert frac == pytest.approx(1.0)


def test_overlap_fraction_partial() -> None:
    # Box straddles the band top edge (0.9): half its height overlaps.
    frac = cz.chyron_overlap_fraction((0.1, 0.88, 0.2, 0.04), _bottom_safezone())
    assert frac == pytest.approx(0.5)


def test_overlap_fraction_no_overlap() -> None:
    frac = cz.chyron_overlap_fraction((0.1, 0.1, 0.2, 0.04), _bottom_safezone())
    assert frac == pytest.approx(0.0)


def test_overlap_fraction_clamped_to_one_with_overlapping_bands() -> None:
    sz = cz.SafeZone(
        bands=(
            cz.ChyronBand(top=0.9, bottom=0.97, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),
            cz.ChyronBand(top=0.9, bottom=0.97, left=0.0, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),
        )
    )
    assert cz.chyron_overlap_fraction((0.1, 0.91, 0.2, 0.04), sz) == pytest.approx(1.0)


@pytest.mark.parametrize("bw,bh", [(0.0, 0.1), (0.1, 0.0)])
def test_overlap_fraction_rejects_zero_area(bw: float, bh: float) -> None:
    with pytest.raises(cz.ChyronError, match="positive area"):
        cz.chyron_overlap_fraction((0.1, 0.1, bw, bh), _bottom_safezone())


def test_box_avoids_chyrons_true_and_false() -> None:
    sz = _bottom_safezone()
    assert cz.box_avoids_chyrons((0.1, 0.1, 0.2, 0.04), sz)
    assert not cz.box_avoids_chyrons((0.1, 0.91, 0.2, 0.04), sz)


def test_box_avoids_chyrons_with_tolerance() -> None:
    sz = _bottom_safezone()
    # ~50% overlap is allowed once max_overlap is loosened past it.
    assert cz.box_avoids_chyrons((0.1, 0.88, 0.2, 0.04), sz, max_overlap=0.6)


@pytest.mark.parametrize("mo", [-0.1, 1.1])
def test_box_avoids_chyrons_bad_tolerance(mo: float) -> None:
    with pytest.raises(cz.ChyronError, match="max_overlap"):
        cz.box_avoids_chyrons((0.1, 0.1, 0.2, 0.04), _bottom_safezone(), max_overlap=mo)


# --------------------------------------------------------------------------- #
# crop slicing (horizontal pan vs a localised bar)
# --------------------------------------------------------------------------- #


def _corner_bar_safezone() -> cz.SafeZone:
    # A localised lower-left source bug spanning x in [0.0, 0.45].
    return cz.SafeZone(
        bands=(cz.ChyronBand(top=0.9, bottom=0.97, left=0.0, right=0.45, edge=cz.EDGE_BOTTOM, coverage=1.0),)
    )


def test_crop_slices_when_left_edge_inside_band() -> None:
    assert cz.crop_slices_chyrons(0.3, 0.7, _corner_bar_safezone())


def test_crop_slices_when_right_edge_inside_band() -> None:
    # Crop fully left of the bar's right edge but its right edge cuts the bar.
    sz = cz.SafeZone(
        bands=(cz.ChyronBand(top=0.9, bottom=0.97, left=0.3, right=0.9, edge=cz.EDGE_BOTTOM, coverage=1.0),)
    )
    assert cz.crop_slices_chyrons(0.0, 0.5, sz)


def test_crop_does_not_slice_when_band_fully_inside() -> None:
    assert not cz.crop_slices_chyrons(0.0, 0.6, _corner_bar_safezone())


def test_crop_does_not_slice_when_band_fully_outside() -> None:
    assert not cz.crop_slices_chyrons(0.5, 0.9, _corner_bar_safezone())


def test_crop_slices_empty_safezone_is_false() -> None:
    assert not cz.crop_slices_chyrons(0.2, 0.8, cz.SafeZone(bands=()))


def test_crop_invalid_window_raises() -> None:
    with pytest.raises(cz.ChyronError, match="crop_left"):
        cz.crop_slices_chyrons(0.7, 0.3, _corner_bar_safezone())


def test_strictly_inside_branches() -> None:
    assert cz._strictly_inside(0.5, 0.4, 0.6)
    assert not cz._strictly_inside(0.3, 0.4, 0.6)
    assert not cz._strictly_inside(0.7, 0.4, 0.6)


# --------------------------------------------------------------------------- #
# default_sample_times
# --------------------------------------------------------------------------- #


def test_sample_times_single() -> None:
    assert cz.default_sample_times(10.0, count=1) == (5.0,)


def test_sample_times_multiple_even_spacing() -> None:
    assert cz.default_sample_times(10.0, count=4) == pytest.approx((2.0, 4.0, 6.0, 8.0))


def test_sample_times_rejects_bad_duration() -> None:
    with pytest.raises(cz.ChyronError, match="duration"):
        cz.default_sample_times(0.0)


def test_sample_times_rejects_bad_count() -> None:
    with pytest.raises(cz.ChyronError, match="count"):
        cz.default_sample_times(10.0, count=0)


# --------------------------------------------------------------------------- #
# analyze_chyrons (seam orchestration with a fake OCR backend)
# --------------------------------------------------------------------------- #


class _FakeOcr:
    def __init__(self, frames: tuple[tuple[cz.TextBox, ...], ...]) -> None:
        self._frames = frames
        self.calls: list[tuple[str, tuple[float, ...]]] = []

    def detect(self, media_path: str, *, sample_times: tuple[float, ...]) -> tuple[tuple[cz.TextBox, ...], ...]:
        self.calls.append((media_path, sample_times))
        return self._frames


def test_analyze_chyrons_happy_path() -> None:
    frames = tuple(_bottom_bar_frame() for _ in range(3))
    backend = _FakeOcr(frames)
    sz = cz.analyze_chyrons("/clip.mp4", backend, sample_times=(1.0, 2.0, 3.0))
    assert sz.has_bottom
    assert backend.calls == [("/clip.mp4", (1.0, 2.0, 3.0))]


def test_analyze_chyrons_empty_sample_times_raises() -> None:
    with pytest.raises(cz.ChyronError, match="sample_times"):
        cz.analyze_chyrons("/clip.mp4", _FakeOcr(()), sample_times=())


def test_analyze_chyrons_length_mismatch_raises() -> None:
    backend = _FakeOcr((_bottom_bar_frame(),))  # 1 frame for 2 requested times
    with pytest.raises(cz.ChyronError, match="frame count"):
        cz.analyze_chyrons("/clip.mp4", backend, sample_times=(1.0, 2.0))


def test_module_exports_stable_surface() -> None:
    for name in (
        "TextBox",
        "Band",
        "ChyronBand",
        "SafeZone",
        "OcrBackend",
        "detect_chyrons",
        "analyze_chyrons",
        "ChyronError",
    ):
        assert name in cz.__all__


# --------------------------------------------------------------------------- #
# Heavy OCR backend — import surface only (the body is # pragma: no cover)
# --------------------------------------------------------------------------- #


def test_real_ocr_backend_surface_imports_light() -> None:
    import media_studio.features.chyron_safezone_backend as be

    assert be.RealChyronOcrBackend.__name__ == "RealChyronOcrBackend"
    assert "RealChyronOcrBackend" in be.__all__
    assert math.isfinite(be.DEFAULT_SAMPLE_COUNT)
