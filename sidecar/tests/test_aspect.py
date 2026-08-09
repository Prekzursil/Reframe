"""Tests for the canonical aspect registry (WU R3 multi-aspect export).

The registry is the SINGLE source of truth shared by both reframe engines
(``reframe`` / ``reframe_claudeshorts``) so the supported social export aspects —
9:16 (vertical), 1:1 (square), 4:5 (portrait), 16:9 (widescreen) — and their
canonical output dimensions can never drift between the two engines or the
export catalog.

v1.5 aspect-matrix lane: 16:9 is now a FIRST-CLASS curated preset (it used to be
rejected by :func:`require_supported_aspect`), and the registry grows the pure
MULTI-aspect primitives (:func:`require_supported_aspects` /
:func:`fanout_plan`) that let ONE source target N aspects in a single action.
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
@pytest.mark.parametrize(
    ("raw", "norm"),
    [("9x16", "9:16"), ("1:1", "1:1"), ("4:5", "4:5"), ("16x9", "16:9")],
)
def test_require_supported_aspect_accepts_the_four(raw, norm):
    assert aspect.require_supported_aspect(raw) == norm


# SCOPE FIX (v1.5 aspect-matrix lane): "16:9" used to sit in this rejection list.
# It is now a FIRST-CLASS curated preset by design, so it moved UP into
# ``test_require_supported_aspect_accepts_the_four``. No assertion was weakened —
# the remaining uncurated ratios still fail loud, and the accept-list grew.
@pytest.mark.parametrize("unsupported", ["3:4", "2:3", "21:9"])
def test_require_supported_aspect_rejects_unsupported_ratio(unsupported):
    # Parses fine, but is not one of the curated social export aspects -> fail loud.
    with pytest.raises(ValueError, match="unsupported aspect"):
        aspect.require_supported_aspect(unsupported)


def test_require_supported_aspect_rejects_garbage():
    with pytest.raises(ValueError):
        aspect.require_supported_aspect("nope")


def test_supported_aspects_set_is_the_preset_keys():
    assert frozenset({"9:16", "1:1", "4:5", "16:9"}) == aspect.SUPPORTED_ASPECTS
    assert frozenset(aspect.ASPECT_PRESETS) == aspect.SUPPORTED_ASPECTS


# --------------------------------------------------------------------------- #
# require_supported_aspects — the MULTI-aspect (fan-out) request guard
# --------------------------------------------------------------------------- #
def test_require_supported_aspects_canonicalizes_and_preserves_order():
    assert aspect.require_supported_aspects(["16x9", " 4:5 ", "9:16"]) == ("16:9", "4:5", "9:16")


def test_require_supported_aspects_dedupes_keeping_first_occurrence():
    # "9x16" and "9:16" are the SAME target — a fan-out must not render it twice.
    assert aspect.require_supported_aspects(["9x16", "1:1", "9:16", "1:1"]) == ("9:16", "1:1")


def test_require_supported_aspects_rejects_empty():
    with pytest.raises(ValueError, match="at least one aspect"):
        aspect.require_supported_aspects([])


def test_require_supported_aspects_rejects_a_bare_string():
    # A bare str is iterable CHAR-BY-CHAR; silently fanning out to "1"/":"/"1"
    # would be a confusing downstream failure, so reject it at the boundary.
    with pytest.raises(ValueError, match="iterable of aspect strings"):
        aspect.require_supported_aspects("9:16")  # type: ignore[arg-type]


def test_require_supported_aspects_propagates_the_unsupported_member():
    with pytest.raises(ValueError, match="unsupported aspect"):
        aspect.require_supported_aspects(["9:16", "3:4"])


# --------------------------------------------------------------------------- #
# fanout_plan — ONE source -> N aspect targets, in one action
# --------------------------------------------------------------------------- #
def test_fanout_plan_pairs_every_aspect_with_its_canonical_dimensions():
    plan = aspect.fanout_plan(["9:16", "1:1", "4:5", "16:9"])
    assert plan == (
        aspect.AspectTarget("9:16", 1080, 1920),
        aspect.AspectTarget("1:1", 1080, 1080),
        aspect.AspectTarget("4:5", 1080, 1350),
        aspect.AspectTarget("16:9", 1920, 1080),
    )


def test_fanout_plan_targets_are_named_tuples():
    (target,) = aspect.fanout_plan(["16:9"])
    assert (target.aspect, target.width, target.height) == ("16:9", 1920, 1080)


def test_fanout_plan_dedupes_so_one_file_per_distinct_aspect():
    # Three vertical destinations (TikTok/Reels/Shorts) are ONE render target.
    assert aspect.fanout_plan(["9:16", "9x16", "9:16"]) == (aspect.AspectTarget("9:16", 1080, 1920),)


def test_fanout_plan_rejects_an_uncurated_member():
    with pytest.raises(ValueError, match="unsupported aspect"):
        aspect.fanout_plan(["9:16", "2:3"])


# --------------------------------------------------------------------------- #
# consumer proof: the export-preset catalog now ACCEPTS a 16:9 preset
# --------------------------------------------------------------------------- #
def test_export_preset_catalog_accepts_a_widescreen_preset():
    """BOTH-STATES anchor for the widening: this raised ``RpcError`` before 16:9
    became a curated preset (``export_presets._require_supported_aspect`` →
    ``aspect.require_supported_aspect``), and must now persist cleanly."""
    from media_studio.features import export_presets

    saved = export_presets.normalize_preset(
        {
            "id": "widescreen",
            "label": "Widescreen",
            "aspect": "16x9",
            "minSec": 20,
            "maxSec": 60,
            "count": 1,
            "captionStyle": "libass",
        }
    )
    assert saved["aspect"] == "16:9"


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


def test_output_dimensions_widescreen_16_9_is_1920x1080():
    # 16:9 is now a CURATED preset. Its dimensions are byte-identical to what the
    # generic landscape fallback produced before the widening (1920x1080), so the
    # promotion changes MEMBERSHIP (require_supported_aspect) — never geometry.
    assert aspect.output_dimensions("16:9") == (1920, 1080)


def test_output_dimensions_accepts_x_form_for_presets():
    assert aspect.output_dimensions("9x16") == (1080, 1920)


def test_output_dimensions_generic_portrait_fixes_height():
    # 3:4 is NOT a curated preset -> generic fallback (long edge 1920), both even.
    w, h = aspect.output_dimensions("3:4")
    assert (w, h) == (1440, 1920)
    assert w % 2 == 0 and h % 2 == 0


def test_output_dimensions_generic_landscape_fixes_width_even():
    # 21:9 (ultrawide) is NOT curated, so it still exercises the generic LANDSCAPE
    # branch that 16:9 used to cover before it was promoted to a preset:
    # round(1920*9/21) = 823 -> even() -> 824.
    w, h = aspect.output_dimensions("21:9")
    assert w == 1920
    assert h == 824
    assert h % 2 == 0


def test_output_dimensions_generic_odd_derived_edge_is_rounded_even():
    # 7:15 portrait -> width round(1920*7/15)=896 (even already); use a ratio that
    # yields an odd derived edge to exercise the even() rounding branch: 1920*5/9
    # = 1066.67 -> round 1067 -> even 1068.
    w, h = aspect.output_dimensions("5:9")
    assert h == 1920
    assert w == 1068
    assert w % 2 == 0
