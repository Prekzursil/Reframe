"""Unit tests for the OpusClip-style karaoke caption preset (V1.1 WU SP1).

The teardown-verified OpusClip look: all-caps condensed, white fill + thick dark
outline, word-by-word karaoke with the active word ALTERNATING yellow/green and a
scale-pop (``\\t`` ``\\fscx``), 1-4 words per line, safe-area-aware lower-mid
position for 9:16. These tests pin the EXACT ASS tags + safe-area margins so the
burn output can never silently drift. Pure — no ffmpeg / I/O. Targets 100%
line + branch coverage of ``caption_karaoke.py``.
"""

from __future__ import annotations

import pytest
from media_studio.features import caption_karaoke as ck
from media_studio.features import caption_override as co


# --------------------------------------------------------------------------- #
# palette / constants — the silent-wrong-look traps, asserted as exact values
# --------------------------------------------------------------------------- #
class TestPalette:
    def test_style_id_is_opusclip_karaoke(self) -> None:
        assert ck.OPUSCLIP_KARAOKE_STYLE == "opusclip-karaoke"

    def test_fill_is_white_outline_is_black(self) -> None:
        # Style-line form (no trailing &), matching caption_override conventions.
        assert ck.KARAOKE_FILL == "&H00FFFFFF"
        assert ck.KARAOKE_OUTLINE == "&H00000000"

    def test_active_hex_is_yellow_then_green(self) -> None:
        assert ck.KARAOKE_ACTIVE_HEX == ("#FFFF00", "#00FF00")

    def test_active_inline_colours_match_hex_to_ass(self) -> None:
        # Drift guard: the inline \1c colours MUST equal the canonical converter
        # (BGR + inverted alpha), with the trailing & inline tags use.
        assert tuple(co.hex_to_ass_color(h) for h in ck.KARAOKE_ACTIVE_HEX) == ck.KARAOKE_ACTIVE_INLINE
        assert ck.KARAOKE_ACTIVE_INLINE == ("&H0000FFFF&", "&H0000FF00&")

    def test_fill_and_outline_match_hex_to_ass(self) -> None:
        # Style colours are the inline form minus the trailing &.
        assert co.hex_to_ass_color(ck.KARAOKE_FILL_HEX) == ck.KARAOKE_FILL + "&"
        assert co.hex_to_ass_color(ck.KARAOKE_OUTLINE_HEX) == ck.KARAOKE_OUTLINE + "&"

    def test_thick_outline_and_pop_and_max_words(self) -> None:
        assert ck.KARAOKE_OUTLINE_WIDTH == 4  # thick dark outline
        assert ck.KARAOKE_SHADOW == 2
        assert ck.KARAOKE_POP_SCALE == 115  # scale-pop %
        assert ck.KARAOKE_POP_MS == 120
        assert ck.MAX_WORDS_PER_LINE == 4
        assert ck.KARAOKE_FONT in co.CURATED_CAPTION_FONTS  # burn-in fontconfig set


# --------------------------------------------------------------------------- #
# active_color_for_index — alternation
# --------------------------------------------------------------------------- #
class TestActiveColor:
    @pytest.mark.parametrize(
        ("index", "expected"),
        [
            (0, "&H0000FFFF&"),  # yellow
            (1, "&H0000FF00&"),  # green
            (2, "&H0000FFFF&"),  # yellow
            (3, "&H0000FF00&"),  # green
            (10, "&H0000FFFF&"),
            (11, "&H0000FF00&"),
        ],
    )
    def test_alternates_yellow_green(self, index: int, expected: str) -> None:
        assert ck.active_color_for_index(index) == expected


# --------------------------------------------------------------------------- #
# is_karaoke_style — the router predicate
# --------------------------------------------------------------------------- #
class TestIsKaraokeStyle:
    @pytest.mark.parametrize("style", ["opusclip-karaoke", " OpusClip-Karaoke ", "OPUSCLIP-KARAOKE"])
    def test_true_for_the_preset(self, style: str) -> None:
        assert ck.is_karaoke_style(style) is True

    @pytest.mark.parametrize("style", ["karaoke", "bold", "", "libass", None, 123, []])
    def test_false_otherwise(self, style: object) -> None:
        assert ck.is_karaoke_style(style) is False


# --------------------------------------------------------------------------- #
# safe_area_margin_v — 9:16 safe area
# --------------------------------------------------------------------------- #
class TestSafeAreaMarginV:
    def test_bottom_clears_lower_band(self) -> None:
        # 1920 * 0.18 = 345.6 -> 346 px up from the bottom edge (lower-mid).
        assert ck.safe_area_margin_v(1920, "bottom") == 346

    def test_top_clears_status_bar(self) -> None:
        # 1920 * 0.10 = 192 px down from the top edge.
        assert ck.safe_area_margin_v(1920, "top") == 192

    def test_center_ignores_margin(self) -> None:
        assert ck.safe_area_margin_v(1920, "center") == 0

    def test_unknown_band_defaults_to_bottom(self) -> None:
        assert ck.safe_area_margin_v(1920, "sideways") == 346


# --------------------------------------------------------------------------- #
# words_from_cue — aligned words preferred; even-split fallback
# --------------------------------------------------------------------------- #
class TestWordsFromCue:
    def test_uses_aligned_words_when_present(self) -> None:
        cue = {
            "start": 0.0,
            "end": 2.0,
            "text": "in societate",
            "words": [
                {"text": "in", "start": 0.0, "end": 0.4},
                {"text": " ", "start": 0.4, "end": 0.5},  # blank -> dropped
                {"text": "societate", "start": 0.5, "end": 1.2},
            ],
        }
        out = ck.words_from_cue(cue)
        assert [w["text"] for w in out] == ["in", "societate"]
        assert out[0] == {"text": "in", "start": 0.0, "end": 0.4}

    def test_even_split_fallback_when_no_word_timing(self) -> None:
        cue = {"start": 1.0, "end": 4.0, "text": "one two three"}
        out = ck.words_from_cue(cue)
        assert [w["text"] for w in out] == ["one", "two", "three"]
        # 3s window split evenly across 3 tokens -> 1s each.
        assert out[0]["start"] == pytest.approx(1.0)
        assert out[0]["end"] == pytest.approx(2.0)
        assert out[2]["start"] == pytest.approx(3.0)
        assert out[2]["end"] == pytest.approx(4.0)

    def test_empty_text_yields_no_words(self) -> None:
        assert ck.words_from_cue({"start": 0.0, "end": 1.0, "text": "   "}) == []
        assert ck.words_from_cue({}) == []


# --------------------------------------------------------------------------- #
# group_into_lines — 1..4 words per line
# --------------------------------------------------------------------------- #
class TestGroupIntoLines:
    def test_chunks_into_max_four(self) -> None:
        words = [{"text": f"w{i}"} for i in range(9)]
        lines = ck.group_into_lines(words)
        assert [len(line) for line in lines] == [4, 4, 1]

    def test_empty(self) -> None:
        assert ck.group_into_lines([]) == []


# --------------------------------------------------------------------------- #
# build_line_text — exact inline tags for the active word
# --------------------------------------------------------------------------- #
class TestBuildLineText:
    def test_active_word_gets_colour_pop_and_reset(self) -> None:
        line = [{"text": "in"}, {"text": "societatea"}, {"text": "romaneasca"}]
        text = ck.build_line_text(line, active_index=1, active_color="&H0000FF00&")
        # all-caps; active word wrapped in alternating colour + scale-pop + reset.
        assert text == ("IN {\\1c&H0000FF00&\\t(0,120,\\fscx115\\fscy115)}SOCIETATEA{\\r} ROMANEASCA")

    def test_uppercase_can_be_disabled(self) -> None:
        line = [{"text": "abc"}]
        text = ck.build_line_text(line, active_index=0, active_color="&H0000FFFF&", uppercase=False)
        assert "abc" in text and "ABC" not in text

    def test_escapes_injection_in_active_and_plain_words(self) -> None:
        line = [{"text": "a{b}"}, {"text": "c\\d"}]
        text = ck.build_line_text(line, active_index=0, active_color="&H0000FFFF&")
        # braces/backslash neutralised in BOTH the active block and the plain word.
        assert "A\\{B\\}" in text
        assert "C\\\\D" in text


# --------------------------------------------------------------------------- #
# build_karaoke_ass — the full document
# --------------------------------------------------------------------------- #
class TestBuildKaraokeAss:
    def _two_word_cue(self) -> dict:
        return {
            "start": 0.0,
            "end": 1.0,
            "text": "hello world",
            "words": [
                {"text": "hello", "start": 0.0, "end": 0.5},
                {"text": "world", "start": 0.5, "end": 1.0},
            ],
        }

    def test_header_has_canvas_and_style(self) -> None:
        doc = ck.build_karaoke_ass([self._two_word_cue()], width=1080, height=1920)
        assert "PlayResX: 1080" in doc
        assert "PlayResY: 1920" in doc
        # all-caps condensed font + white fill + thick dark outline (BorderStyle 1).
        assert (
            "Style: Default,Anton,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
            "-1,0,0,0,100,100,0,0,1,4,2,2,65,65,346,1" in doc
        )

    def test_one_event_per_word_with_alternating_active_colour(self) -> None:
        doc = ck.build_karaoke_ass([self._two_word_cue()], width=1080, height=1920)
        lines = [ln for ln in doc.splitlines() if ln.startswith("Dialogue:")]
        assert len(lines) == 2
        # word 0 active -> yellow + pop; word 1 plain.
        assert lines[0] == (
            "Dialogue: 0,0:00:00.00,0:00:00.50,Default,,0,0,0,,"
            "{\\1c&H0000FFFF&\\t(0,120,\\fscx115\\fscy115)}HELLO{\\r} WORLD"
        )
        # word 1 active -> green + pop; word 0 plain.
        assert lines[1] == (
            "Dialogue: 0,0:00:00.50,0:00:01.00,Default,,0,0,0,,"
            "HELLO {\\1c&H0000FF00&\\t(0,120,\\fscx115\\fscy115)}WORLD{\\r}"
        )

    def test_document_ends_with_newline(self) -> None:
        doc = ck.build_karaoke_ass([self._two_word_cue()])
        assert doc.endswith("\n")

    def test_empty_cues_emit_header_only(self) -> None:
        doc = ck.build_karaoke_ass([])
        assert "[Events]" in doc
        assert not any(ln.startswith("Dialogue:") for ln in doc.splitlines())

    def test_source_start_rebases_and_drops_pre_clip_words(self) -> None:
        cue = {
            "start": 10.0,
            "end": 12.0,
            "text": "a b",
            "words": [
                {"text": "a", "start": 10.0, "end": 10.4},  # before clip in-point -> dropped
                {"text": "b", "start": 11.0, "end": 12.0},
            ],
        }
        doc = ck.build_karaoke_ass([cue], source_start=11.0)
        lines = [ln for ln in doc.splitlines() if ln.startswith("Dialogue:")]
        # 'a' [10.0,10.4) rebases to [0,0) -> dropped; 'b' [11,12) -> [0,1).
        assert len(lines) == 1
        assert "0:00:00.00,0:00:01.00" in lines[0]
        # alternation index still advanced for the dropped word: 'b' is index 1 (green).
        assert "&H0000FF00&" in lines[0]

    def test_top_band_uses_top_safe_area_and_alignment(self) -> None:
        doc = ck.build_karaoke_ass([self._two_word_cue()], position_band="top")
        # alignment 8 (top-centre), MarginV 192 (10% of 1920).
        assert ",8,65,65,192,1" in doc

    def test_more_than_four_words_wrap_into_lines(self) -> None:
        words = [{"text": f"w{i}", "start": float(i), "end": float(i) + 1.0} for i in range(5)]
        cue = {"start": 0.0, "end": 5.0, "text": " ".join(f"w{i}" for i in range(5)), "words": words}
        doc = ck.build_karaoke_ass([cue])
        dialogue = [ln for ln in doc.splitlines() if ln.startswith("Dialogue:")]
        assert len(dialogue) == 5  # one event per word
        # the 5th word is alone on its own line (group of 1): no sibling context.
        # absolute word index 4 -> 4 % 2 == 0 -> yellow.
        assert dialogue[4].endswith("{\\1c&H0000FFFF&\\t(0,120,\\fscx115\\fscy115)}W4{\\r}")
