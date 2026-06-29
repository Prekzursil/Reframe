"""Tests for the canonical aspect registry (WU R3 multi-aspect export).

The registry is the SINGLE source of truth shared by both reframe engines
(``reframe`` / ``reframe_claudeshorts``) so the supported social export aspects —
9:16 (vertical), 1:1 (square), 4:5 (portrait) — and their canonical 1080-wide
output dimensions can never drift between the two engines or the export catalog.
"""

from __future__ import annotations

import pytest
from media_studio.features import aspect


# --------------------------------------------------------------------------- #
# parse_aspect
# --------------------------------------------------------------------------- #
def test_parse_aspect_colon_and_x_and_whitespace():
    assert aspect.parse_aspect("9:16") == (9, 16)
    assert aspect.parse_aspect("9x16") == (9, 16)
    assert aspect.parse_aspect("  16:9 ") == (16, 9)


@pytest.mark.parametrize("bad", ["9", "9:16:1", "a:b", "0:16", "9:0", "-9:16", "", "1:-1"])
def test_parse_aspect_rejects_garbage(bad):
    with pytest.raises(ValueError):
        aspect.parse_aspect(bad)


def test_parse_aspect_rejects_non_string_components():
    # A list as one component goes through int() and raises TypeError -> ValueError.
    with pytest.raises(ValueError):
        aspect.parse_aspect(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# even
# --------------------------------------------------------------------------- #
def test_even_rounds_up_odd_keeps_even():
    assert aspect.even(1080) == 1080
    assert aspect.even(1081) == 1082
    assert aspect.even(0) == 0


# --------------------------------------------------------------------------- #
# normalize_aspect
# --------------------------------------------------------------------------- #
def test_normalize_aspect_canonicalizes():
    assert aspect.normalize_aspect("9x16") == "9:16"
    assert aspect.normalize_aspect("  4 : 5 ".replace(" ", "")) == "4:5"
    assert aspect.normalize_aspect("1:1") == "1:1"


def test_normalize_aspect_rejects_garbage():
    with pytest.raises(ValueError):
        aspect.normalize_aspect("potato")


# --------------------------------------------------------------------------- #
# require_supported_aspect
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("raw", "norm"), [("9x16", "9:16"), ("1:1", "1:1"), ("4:5", "4:5")])
def test_require_supported_aspect_accepts_the_three(raw, norm):
    assert aspect.require_supported_aspect(raw) == norm


@pytest.mark.parametrize("unsupported", ["16:9", "3:4", "2:3"])
def test_require_supported_aspect_rejects_unsupported_ratio(unsupported):
    # Parses fine, but is not one of the curated social export aspects -> fail loud.
    with pytest.raises(ValueError, match="unsupported aspect"):
        aspect.require_supported_aspect(unsupported)


def test_require_supported_aspect_rejects_garbage():
    with pytest.raises(ValueError):
        aspect.require_supported_aspect("nope")


def test_supported_aspects_set_is_the_preset_keys():
    assert frozenset({"9:16", "1:1", "4:5"}) == aspect.SUPPORTED_ASPECTS
    assert frozenset(aspect.ASPECT_PRESETS) == aspect.SUPPORTED_ASPECTS


# --------------------------------------------------------------------------- #
# output_dimensions — the three social presets + the generic fallback
# --------------------------------------------------------------------------- #
def test_output_dimensions_default_is_vertical_1080x1920():
    assert aspect.output_dimensions() == (1080, 1920)
    assert aspect.output_dimensions("9:16") == (1080, 1920)
    assert aspect.DEFAULT_ASPECT == "9:16"


def test_output_dimensions_square_is_1080x1080():
    assert aspect.output_dimensions("1:1") == (1080, 1080)


def test_output_dimensions_portrait_4_5_is_1080x1350():
    assert aspect.output_dimensions("4:5") == (1080, 1350)


def test_output_dimensions_accepts_x_form_for_presets():
    assert aspect.output_dimensions("9x16") == (1080, 1920)


def test_output_dimensions_generic_portrait_fixes_height():
    # 3:4 is NOT a curated preset -> generic fallback (long edge 1920), both even.
    w, h = aspect.output_dimensions("3:4")
    assert (w, h) == (1440, 1920)
    assert w % 2 == 0 and h % 2 == 0


def test_output_dimensions_generic_landscape_fixes_width_even():
    w, h = aspect.output_dimensions("16:9")
    assert w == 1920
    assert h % 2 == 0


def test_output_dimensions_generic_odd_derived_edge_is_rounded_even():
    # 7:15 portrait -> width round(1920*7/15)=896 (even already); use a ratio that
    # yields an odd derived edge to exercise the even() rounding branch: 1920*5/9
    # = 1066.67 -> round 1067 -> even 1068.
    w, h = aspect.output_dimensions("5:9")
    assert h == 1920
    assert w == 1068
    assert w % 2 == 0
