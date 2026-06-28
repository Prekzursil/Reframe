"""Tests for the OpusClip-style HOOK-CARD overlay + virality-rank gating (WU SP2).

Pure-logic assertions for:
  - the hook-card config resolver (enabled / top-N / first-~5 s duration) with
    clamp + bad-input fallbacks (NO silent crash, sane defaults at the boundary);
  - the TOP-N virality-rank GATE (only the N best-ranked clips get a card);
  - the rank-ordered filename/order prefix (the "title export" 01-N prefix);
  - the libass HOOK-CARD ASS Style line (white box / bold black / upper-third)
    whose resolved &H colours are DRIFT-GUARDED against caption_override.

Everything here is PURE (no ffmpeg, no I/O).
"""

from __future__ import annotations

import pytest
from media_studio.features import hook_card as hc
from media_studio.features.caption_override import hex_to_ass_color


# --------------------------------------------------------------------------- #
# palette drift guard (the silent-wrong-colour trap)
# --------------------------------------------------------------------------- #
def test_resolved_colours_match_hex_to_ass_color():
    # Style-line form is &HAABBGGRR WITHOUT the trailing & (== hex_to_ass[:-1]).
    assert hex_to_ass_color(hc.HOOK_CARD_TEXT_HEX)[:-1] == hc.HOOK_CARD_TEXT
    assert hex_to_ass_color(hc.HOOK_CARD_FILL_HEX)[:-1] == hc.HOOK_CARD_BOX
    # white box, black text — the OpusClip hook card (inverse of the caption box).
    assert hc.HOOK_CARD_TEXT == "&H00000000"
    assert hc.HOOK_CARD_BOX == "&H00FFFFFF"


# --------------------------------------------------------------------------- #
# resolve_hook_card_config
# --------------------------------------------------------------------------- #
def test_config_defaults_when_settings_absent():
    cfg = hc.resolve_hook_card_config(None)
    assert cfg.enabled is True
    assert cfg.top_n == hc.HOOK_CARD_DEFAULT_TOP_N == 10
    assert cfg.duration_sec == hc.HOOK_CARD_DEFAULT_SEC == 5.0


def test_config_reads_explicit_values():
    cfg = hc.resolve_hook_card_config({"hookCard": True, "hookCardTopN": 3, "hookCardSec": 4.5})
    assert cfg.enabled is True
    assert cfg.top_n == 3
    assert cfg.duration_sec == 4.5


def test_config_disabled_flag_is_honoured():
    cfg = hc.resolve_hook_card_config({"hookCard": False})
    assert cfg.enabled is False


def test_config_non_bool_enabled_defaults_on():
    # A non-bool truthy/falsey value is NOT a real toggle -> default ON (G-4).
    assert hc.resolve_hook_card_config({"hookCard": 1}).enabled is True
    assert hc.resolve_hook_card_config({"hookCard": "yes"}).enabled is True


def test_config_top_n_clamps_to_min_one():
    assert hc.resolve_hook_card_config({"hookCardTopN": 0}).top_n == 1
    assert hc.resolve_hook_card_config({"hookCardTopN": -5}).top_n == 1


@pytest.mark.parametrize("bad", [None, "ten", True, 2.5])
def test_config_top_n_bad_type_defaults(bad):
    # bool is NOT an int count; floats/strings/None fall back to the default.
    assert hc.resolve_hook_card_config({"hookCardTopN": bad}).top_n == hc.HOOK_CARD_DEFAULT_TOP_N


def test_config_duration_clamps_window():
    assert hc.resolve_hook_card_config({"hookCardSec": 0.0}).duration_sec == hc.HOOK_CARD_DEFAULT_SEC
    assert hc.resolve_hook_card_config({"hookCardSec": -2}).duration_sec == hc.HOOK_CARD_DEFAULT_SEC
    assert hc.resolve_hook_card_config({"hookCardSec": 999}).duration_sec == hc.HOOK_CARD_MAX_SEC
    assert hc.resolve_hook_card_config({"hookCardSec": 0.5}).duration_sec == hc.HOOK_CARD_MIN_SEC


@pytest.mark.parametrize("bad", [None, "5", True, float("nan"), float("inf")])
def test_config_duration_bad_type_defaults(bad):
    assert hc.resolve_hook_card_config({"hookCardSec": bad}).duration_sec == hc.HOOK_CARD_DEFAULT_SEC


# --------------------------------------------------------------------------- #
# resolve_rank + top-N virality gate
# --------------------------------------------------------------------------- #
def test_resolve_rank_prefers_field_else_fallback():
    assert hc.resolve_rank({"rank": 4}, 99) == 4
    assert hc.resolve_rank({}, 7) == 7  # missing -> 1-based position
    assert hc.resolve_rank({"rank": True}, 7) == 7  # bool is not a rank
    assert hc.resolve_rank({"rank": "x"}, 7) == 7  # non-int -> fallback


def _cands(*ranks):
    return [{"rank": r, "start": 0.0, "end": 10.0} for r in ranks]


def test_gate_selects_top_n_smallest_ranks():
    # ranks 1..5, top_n=2 -> the two best-virality clips (rank 1 and 2) only.
    cfg = hc.resolve_hook_card_config({"hookCardTopN": 2})
    gated = hc.select_hook_card_ranks(_cands(3, 1, 5, 2, 4), cfg)
    assert gated == frozenset({1, 2})


def test_gate_top_n_larger_than_batch_returns_all():
    cfg = hc.resolve_hook_card_config({"hookCardTopN": 10})
    gated = hc.select_hook_card_ranks(_cands(2, 1), cfg)
    assert gated == frozenset({1, 2})


def test_gate_empty_when_disabled():
    cfg = hc.resolve_hook_card_config({"hookCard": False})
    assert hc.select_hook_card_ranks(_cands(1, 2, 3), cfg) == frozenset()


def test_gate_empty_for_no_candidates():
    cfg = hc.resolve_hook_card_config(None)
    assert hc.select_hook_card_ranks([], cfg) == frozenset()


def test_gate_uses_position_fallback_when_rank_missing():
    cfg = hc.resolve_hook_card_config({"hookCardTopN": 1})
    # no rank -> positions 1, 2; top-1 keeps position 1.
    gated = hc.select_hook_card_ranks([{"start": 0.0}, {"start": 1.0}], cfg)
    assert gated == frozenset({1})


# --------------------------------------------------------------------------- #
# rank-ordered filename / order prefix (the "title export" 01-N prefix)
# --------------------------------------------------------------------------- #
def test_order_prefix_zero_pads_to_max_rank_width():
    assert hc.order_prefix(1, 9) == "01"  # min width 2 even for single digit
    assert hc.order_prefix(2, 41) == "02"
    assert hc.order_prefix(41, 41) == "41"
    assert hc.order_prefix(7, 100) == "007"


def test_order_prefix_coerces_and_floors():
    assert hc.order_prefix(3, 0) == "03"  # max_rank<1 -> width floor (2)
    assert hc.order_prefix("5", "9") == "05"  # str inputs coerced


def test_max_export_rank():
    assert hc.max_export_rank(_cands(2, 5, 1)) == 5
    assert hc.max_export_rank([]) == 1  # empty -> safe floor
    assert hc.max_export_rank([{"start": 0.0}, {"start": 1.0}]) == 2  # fallbacks


def test_rank_ordered_stem():
    assert hc.rank_ordered_stem("talk", 1, 41) == "01-talk"
    assert hc.rank_ordered_stem("talk", 12, 41) == "12-talk"


# --------------------------------------------------------------------------- #
# hook-card ASS style line + time-box
# --------------------------------------------------------------------------- #
def test_style_line_is_white_box_bold_black_upper_third():
    line = hc.hook_card_style_line(1080, 1920)
    assert line.startswith(f"Style: {hc.HOOK_CARD_STYLE_NAME},Arial,")
    # PrimaryColour (text) = black; OutlineColour (the BorderStyle-3 box) = white.
    assert hc.HOOK_CARD_TEXT in line
    assert hc.HOOK_CARD_BOX in line
    # bold ON, BorderStyle 3 (opaque box = the card), top-centre alignment (8).
    fields = line.split(",")
    assert fields[7] == str(hc.HOOK_CARD_BOLD)  # Bold
    assert fields[15] == str(hc.HOOK_CARD_BORDER_STYLE)  # BorderStyle == 3
    assert fields[18] == str(hc.HOOK_CARD_ALIGNMENT)  # Alignment == 8 (top)
    # upper-third vertical margin (from the top edge under alignment 8).
    assert fields[21] == str(max(12, round(1920 * hc.HOOK_CARD_TOP_FRACTION)))


def test_hook_card_end_sec_time_boxes_to_first_seconds():
    # known clip length: capped to the clip; otherwise the configured window.
    assert hc.hook_card_end_sec(5.0, 30.0) == 5.0
    assert hc.hook_card_end_sec(5.0, 3.0) == 3.0  # clip shorter than the card window
    assert hc.hook_card_end_sec(5.0, 0.0) == 5.0  # unknown length -> the window
    assert hc.hook_card_end_sec(0.0, 0.0) == hc.HOOK_CARD_DEFAULT_SEC  # non-positive -> default
