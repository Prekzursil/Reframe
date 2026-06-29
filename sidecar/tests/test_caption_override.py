"""Unit tests for the V1.1 Lane-1 caption-override resolution (WU S2).

Covers the load-bearing ``#RRGGBB`` -> ``&H00BBGGRR&`` BGR + inverted-alpha
conversion (EXACT-string table), the additive field-by-field override merge onto
the base libass visual, and the echo helper. Pure — no ffmpeg / I/O. Targets 100%
line + branch coverage of ``caption_override.py``.
"""

from __future__ import annotations

import pytest
from media_studio.features import caption_override as co


# --------------------------------------------------------------------------- #
# hex_to_ass_color — the silent-wrong-colour trap: assert EXACT &H strings
# --------------------------------------------------------------------------- #
class TestHexToAssColor:
    @pytest.mark.parametrize(
        ("hex_in", "expected"),
        [
            ("#FF0000", "&H000000FF&"),  # pure red  -> BGR swap
            ("#00FF00", "&H0000FF00&"),  # pure green
            ("#0000FF", "&H00FF0000&"),  # pure blue
            ("#FFFFFF", "&H00FFFFFF&"),  # white
            ("#000000", "&H00000000&"),  # black
            ("#123456", "&H00563412&"),  # arbitrary RR=12 GG=34 BB=56 -> 56 34 12
            ("#abcdef", "&H00EFCDAB&"),  # lowercase input normalised to uppercase
        ],
    )
    def test_exact_conversion(self, hex_in: str, expected: str) -> None:
        assert co.hex_to_ass_color(hex_in) == expected

    def test_default_alpha_is_opaque_zero(self) -> None:
        # inverted alpha: 00 == fully opaque (the default).
        assert co.hex_to_ass_color("#FF0000").startswith("&H00")

    def test_custom_alpha_byte(self) -> None:
        assert co.hex_to_ass_color("#FF0000", alpha="80") == "&H800000FF&"

    def test_whitespace_trimmed(self) -> None:
        assert co.hex_to_ass_color("  #FF0000  ") == "&H000000FF&"

    @pytest.mark.parametrize(
        "bad",
        ["", "FF0000", "#FFF", "#GGGGGG", "#FF00", "#FF0000FF", "red", "#ff00"],
    )
    def test_invalid_hex_returns_none(self, bad: str) -> None:
        assert co.hex_to_ass_color(bad) is None

    @pytest.mark.parametrize("bad", [None, 123, 0xFF0000, [], {"x": 1}, True])
    def test_non_string_returns_none(self, bad: object) -> None:
        assert co.hex_to_ass_color(bad) is None


# --------------------------------------------------------------------------- #
# apply_override — base (empty/None) reproduces the V1 style exactly
# --------------------------------------------------------------------------- #
class TestApplyOverrideBase:
    @pytest.mark.parametrize("empty", [None, {}])
    def test_empty_is_base_style(self, empty: object) -> None:
        r = co.apply_override(empty)
        assert r.font_name == co.BASE_FONT
        assert r.size_scale == 1.0
        assert r.primary_color == co.BASE_PRIMARY
        assert r.secondary_color == co.BASE_SECONDARY
        assert r.outline_color == co.BASE_OUTLINE
        assert r.back_color == co.BASE_BACK
        assert r.border_style == co.BASE_BORDER_STYLE
        assert r.outline_width == co.BASE_OUTLINE_WIDTH
        assert r.shadow == co.BASE_SHADOW
        assert r.uppercase is False
        assert r.position_band is None
        assert r.text_color is None
        assert r.active_color is None
        assert r.spoken_color is None


# --------------------------------------------------------------------------- #
# apply_override — fontFamily allowlist
# --------------------------------------------------------------------------- #
class TestApplyOverrideFont:
    def test_curated_font_applied(self) -> None:
        assert co.apply_override({"fontFamily": "Montserrat"}).font_name == "Montserrat"

    def test_font_trimmed_before_lookup(self) -> None:
        assert co.apply_override({"fontFamily": "  Anton  "}).font_name == "Anton"

    def test_unknown_font_drops_to_base(self) -> None:
        assert co.apply_override({"fontFamily": "Comic Sans MS"}).font_name == co.BASE_FONT

    def test_non_string_font_drops_to_base(self) -> None:
        assert co.apply_override({"fontFamily": 42}).font_name == co.BASE_FONT


# --------------------------------------------------------------------------- #
# apply_override — sizeScale clamp
# --------------------------------------------------------------------------- #
class TestApplyOverrideSizeScale:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1.0, 1.0),
            (1.25, 1.25),
            (co.SIZE_SCALE_MIN, co.SIZE_SCALE_MIN),
            (co.SIZE_SCALE_MAX, co.SIZE_SCALE_MAX),
            (0.1, co.SIZE_SCALE_MIN),  # below clamp
            (5.0, co.SIZE_SCALE_MAX),  # above clamp
        ],
    )
    def test_clamp(self, value: float, expected: float) -> None:
        assert co.apply_override({"sizeScale": value}).size_scale == expected

    @pytest.mark.parametrize("bad", [None, "1.2", True, float("nan"), float("inf")])
    def test_invalid_defaults_to_one(self, bad: object) -> None:
        assert co.apply_override({"sizeScale": bad}).size_scale == 1.0

    def test_int_value_accepted(self) -> None:
        assert co.apply_override({"sizeScale": 1}).size_scale == 1.0


# --------------------------------------------------------------------------- #
# apply_override — colour roles -> ASS Style slots
# --------------------------------------------------------------------------- #
class TestApplyOverrideColors:
    def test_text_color_to_primary(self) -> None:
        r = co.apply_override({"textColor": "#FF0000"})
        assert r.primary_color == "&H000000FF&"
        assert r.text_color == "&H000000FF&"

    def test_active_color_to_secondary(self) -> None:
        r = co.apply_override({"activeColor": "#00FF00"})
        assert r.secondary_color == "&H0000FF00&"
        assert r.active_color == "&H0000FF00&"

    def test_spoken_color_fills_primary_when_no_text_color(self) -> None:
        r = co.apply_override({"spokenColor": "#0000FF"})
        assert r.primary_color == "&H00FF0000&"
        assert r.spoken_color == "&H00FF0000&"
        assert r.text_color is None

    def test_text_color_wins_over_spoken_for_primary(self) -> None:
        r = co.apply_override({"textColor": "#FF0000", "spokenColor": "#0000FF"})
        assert r.primary_color == "&H000000FF&"  # text wins
        assert r.spoken_color == "&H00FF0000&"  # still echoed

    def test_bad_hex_drops_to_base_colors(self) -> None:
        r = co.apply_override({"textColor": "nope", "activeColor": "#12", "spokenColor": "#ZZZZZZ"})
        assert r.primary_color == co.BASE_PRIMARY
        assert r.secondary_color == co.BASE_SECONDARY
        assert r.text_color is None
        assert r.active_color is None
        assert r.spoken_color is None


# --------------------------------------------------------------------------- #
# apply_override — outline / box border resolution
# --------------------------------------------------------------------------- #
class TestApplyOverrideBorder:
    def test_box_card_sets_border_style_3(self) -> None:
        r = co.apply_override({"box": True})
        assert r.border_style == 3
        assert r.outline_width == co.BASE_OUTLINE_WIDTH

    def test_box_wins_over_outline_off(self) -> None:
        # mutually exclusive: a solid card wins even if outline=False.
        r = co.apply_override({"box": True, "outline": False})
        assert r.border_style == 3
        assert r.outline_width == co.BASE_OUTLINE_WIDTH

    def test_outline_true_keeps_stroke(self) -> None:
        r = co.apply_override({"outline": True})
        assert r.border_style == 1
        assert r.outline_width == co.BASE_OUTLINE_WIDTH

    def test_outline_false_removes_stroke(self) -> None:
        r = co.apply_override({"outline": False})
        assert r.border_style == 1
        assert r.outline_width == 0

    def test_box_false_keeps_base(self) -> None:
        r = co.apply_override({"box": False})
        assert r.border_style == co.BASE_BORDER_STYLE
        assert r.outline_width == co.BASE_OUTLINE_WIDTH

    def test_non_bool_box_and_outline_ignored(self) -> None:
        r = co.apply_override({"box": "yes", "outline": 1})
        assert r.border_style == co.BASE_BORDER_STYLE
        assert r.outline_width == co.BASE_OUTLINE_WIDTH


# --------------------------------------------------------------------------- #
# apply_override — uppercase + positionBand
# --------------------------------------------------------------------------- #
class TestApplyOverrideMisc:
    def test_uppercase_true(self) -> None:
        assert co.apply_override({"uppercase": True}).uppercase is True

    def test_uppercase_false(self) -> None:
        assert co.apply_override({"uppercase": False}).uppercase is False

    def test_uppercase_non_bool_defaults_false(self) -> None:
        assert co.apply_override({"uppercase": "TRUE"}).uppercase is False

    @pytest.mark.parametrize("band", ["top", "center", "bottom"])
    def test_position_band_accepted(self, band: str) -> None:
        assert co.apply_override({"positionBand": band}).position_band == band

    @pytest.mark.parametrize("bad", ["middle", "", None, 8])
    def test_position_band_invalid_drops_to_none(self, bad: object) -> None:
        assert co.apply_override({"positionBand": bad}).position_band is None


# --------------------------------------------------------------------------- #
# resolve_caption_style — echo dict
# --------------------------------------------------------------------------- #
class TestResolveCaptionStyleEcho:
    def test_echo_is_plain_dict(self) -> None:
        d = co.resolve_caption_style({"textColor": "#FF0000", "uppercase": True})
        assert isinstance(d, dict)
        assert d["primary_color"] == "&H000000FF&"
        assert d["uppercase"] is True
        assert d["text_color"] == "&H000000FF&"

    def test_echo_none_is_base(self) -> None:
        d = co.resolve_caption_style(None)
        assert d["font_name"] == co.BASE_FONT
        assert d["primary_color"] == co.BASE_PRIMARY

    def test_to_dict_round_trips_dataclass(self) -> None:
        r = co.apply_override({"fontFamily": "Inter"})
        assert r.to_dict()["font_name"] == "Inter"
