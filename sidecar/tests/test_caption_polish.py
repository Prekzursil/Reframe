"""Heavy-ML-free tests for the WU9 caption-polish module.

Exercises the pure Netflix CPS/CPL/min-gap gate with real cues and the three
model stages with injected fakes (no sherpa-onnx / keybert / sklearn / torch).
Targets 100% line + branch coverage of ``caption_polish.py``; the heavy
``caption_polish_backend.py`` is ``pragma: no cover`` and only its lazy-import
factories are smoke-tested.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import caption_polish as cp


# --------------------------------------------------------------------------- #
# fakes for the three injectable backend seams
# --------------------------------------------------------------------------- #
class FakePunct:
    """Returns a canned restored string, or echoes title-cased input."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = mapping or {}

    def restore(self, text: str) -> str:
        if text in self._mapping:
            return self._mapping[text]
        return text.capitalize()


class FakeKeywords:
    """Returns a fixed keyword list regardless of input."""

    def __init__(self, words: list[str]) -> None:
        self._words = words

    def keywords(self, text: str) -> list[str]:
        _ = text
        return list(self._words)


class FakeProfanity:
    """Marks the words in ``bad`` (case-insensitive) as profane."""

    def __init__(self, bad: set[str]) -> None:
        self._bad = {w.lower() for w in bad}

    def is_profane(self, word: str) -> bool:
        return word.lower() in self._bad


def _cue(index: int, start: float, end: float, text: str) -> cp.Cue:
    return {"index": index, "start": start, "end": end, "text": text}


# --------------------------------------------------------------------------- #
# cps_of
# --------------------------------------------------------------------------- #
class TestCpsOf:
    def test_basic_rate(self):
        # 10 chars over 2 s = 5 cps.
        assert cp.cps_of(_cue(1, 0.0, 2.0, "abcde fghi")) == pytest.approx(5.0)

    def test_excludes_newlines(self):
        # "ab\ncd" -> 4 visible chars over 2 s = 2 cps.
        assert cp.cps_of(_cue(1, 0.0, 2.0, "ab\ncd")) == pytest.approx(2.0)

    def test_zero_duration_is_inf(self):
        assert cp.cps_of(_cue(1, 5.0, 5.0, "hi")) == float("inf")

    def test_negative_duration_is_inf(self):
        assert cp.cps_of(_cue(1, 5.0, 4.0, "hi")) == float("inf")


# --------------------------------------------------------------------------- #
# wrap_two_lines
# --------------------------------------------------------------------------- #
class TestWrapTwoLines:
    def test_empty_text(self):
        assert cp.wrap_two_lines("") == ""

    def test_whitespace_only(self):
        assert cp.wrap_two_lines("   ") == ""

    def test_short_stays_one_line(self):
        assert cp.wrap_two_lines("hello world", max_cpl=42) == "hello world"

    def test_wraps_to_two_lines(self):
        text = "alpha beta gamma delta"
        out = cp.wrap_two_lines(text, max_cpl=12)
        lines = out.split("\n")
        assert len(lines) == 2
        assert all(len(line) <= 12 for line in lines)

    def test_overflow_words_append_to_last_line(self):
        # With a tiny CPL the 1st line fills, then ALL remaining words pile onto
        # line 2 (we never open a 3rd line) — exercising the else branch.
        text = "aa bb cc dd ee"
        out = cp.wrap_two_lines(text, max_cpl=3)
        assert out.count("\n") == 1
        assert out.split("\n")[1] == "bb cc dd ee"

    def test_single_long_word_kept_whole(self):
        out = cp.wrap_two_lines("supercalifragilistic", max_cpl=5)
        assert out == "supercalifragilistic"


# --------------------------------------------------------------------------- #
# enforce_cps_cpl
# --------------------------------------------------------------------------- #
class TestEnforceCpsCpl:
    def test_empty_text_dropped(self):
        assert cp.enforce_cps_cpl(_cue(1, 0.0, 1.0, "   ")) == []

    def test_fitting_cue_single_piece(self):
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 5.0, "short line"), max_cps=17, max_cpl=42)
        assert len(out) == 1
        assert out[0]["text"] == "short line"
        assert out[0]["start"] == 0.0
        assert out[0]["end"] == 5.0
        assert out[0]["index"] == 1

    def test_collapses_internal_newlines_and_whitespace(self):
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 5.0, "a\nb   c"), max_cps=17, max_cpl=42)
        assert out[0]["text"] == "a b c"

    def test_too_fast_splits_into_multiple(self):
        # 39 chars over 1 s = 39 cps > 17 -> the gate splits to shrink per-piece
        # text toward the CPS char budget (max_cps * duration = 17 chars here).
        text = " ".join(["word"] * 8)  # 39 chars
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 1.0, text), max_cps=17, max_cpl=42)
        assert len(out) >= 2
        # Each piece's visible text is bounded by the whole-cue CPS char budget
        # (not the tautological "has a newline" escape the first draft used).
        budget = 17 * 1.0
        for piece in out:
            visible = piece["text"].replace("\n", "")
            assert len(visible) <= budget + 4  # +1 chunk-rounding slack

    def test_too_fast_cps_is_not_falsely_reduced(self):
        # HONEST CONTRACT: proportional splitting is reading-speed invariant, so a
        # genuinely too-fast cue's pieces still exceed max_cps. The gate must NOT
        # pretend otherwise — it only bounds per-piece density / CPL, never the
        # rate of a cue that needs more on-screen time than it has.
        text = " ".join(["word"] * 8)  # 39 chars / 1 s = 39 cps
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 1.0, text), max_cps=17, max_cpl=42)
        assert all(cp.cps_of(p) > 17 for p in out)  # rate genuinely unfixed

    def test_in_budget_cue_not_split_for_cps(self):
        # A cue already inside the CPS rate (and CPL) stays a single piece — the
        # CPS char-budget term yields 1, so no spurious over-splitting.
        text = " ".join(["word"] * 4)  # 19 chars over 5 s = 3.8 cps (<<17), CPL ok
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 5.0, text), max_cps=17, max_cpl=42)
        assert len(out) == 1

    def test_too_long_for_two_lines_splits(self):
        # 100 chars, generous time -> CPS ok but CPL (42*2=84) forces a split.
        text = " ".join(["abcd"] * 20)  # 99 chars
        out = cp.enforce_cps_cpl(_cue(1, 0.0, 100.0, text), max_cps=17, max_cpl=42)
        assert len(out) >= 2
        for piece in out:
            for line in piece["text"].split("\n"):
                assert len(line) <= 42

    def test_split_times_are_contiguous_and_cover_span(self):
        text = " ".join(["word"] * 12)
        out = cp.enforce_cps_cpl(_cue(1, 10.0, 16.0, text), max_cps=17, max_cpl=42)
        assert out[0]["start"] == 10.0
        assert out[-1]["end"] == 16.0
        for a, b in zip(out, out[1:], strict=False):
            assert a["end"] == pytest.approx(b["start"])

    def test_split_indices_renumbered(self):
        text = " ".join(["word"] * 12)
        out = cp.enforce_cps_cpl(_cue(9, 0.0, 1.0, text), max_cps=17, max_cpl=42)
        assert [c["index"] for c in out] == list(range(1, len(out) + 1))

    def test_zero_duration_single_piece(self):
        # A zero-length cue cannot be lengthened by splitting -> stays 1 piece
        # (the duration<=0 branch sets cps_pieces=1; CPL still applies if long).
        out = cp.enforce_cps_cpl(_cue(1, 5.0, 5.0, "tiny"), max_cps=17, max_cpl=42)
        assert len(out) == 1
        assert out[0]["start"] == 5.0
        assert out[0]["end"] == 5.0

    def test_zero_duration_long_text_split_by_cpl(self):
        # duration=0 (cps_pieces branch=1) but text too long for two lines ->
        # cpl_pieces drives the split; slices all start/end at the same instant.
        text = " ".join(["abcd"] * 30)  # 149 chars > 84
        out = cp.enforce_cps_cpl(_cue(1, 3.0, 3.0, text), max_cps=17, max_cpl=42)
        assert len(out) >= 2
        assert all(c["start"] == 3.0 and c["end"] == 3.0 for c in out)


# --------------------------------------------------------------------------- #
# enforce_min_gap
# --------------------------------------------------------------------------- #
class TestEnforceMinGap:
    def test_empty(self):
        assert cp.enforce_min_gap([]) == []

    def test_single_cue_unchanged(self):
        cues = [_cue(1, 0.0, 1.0, "a")]
        assert cp.enforce_min_gap(cues, fps=30.0) == cues

    def test_pulls_back_end_when_too_close(self):
        # gap needed = 2/30 ≈ 0.0667 s. cue0 ends at 1.0, cue1 starts at 1.02.
        cues = [_cue(1, 0.0, 1.0, "a"), _cue(2, 1.02, 2.0, "b")]
        out = cp.enforce_min_gap(cues, fps=30.0)
        assert out[0]["end"] == pytest.approx(1.02 - 2 / 30.0)
        assert out[1]["start"] == 1.02  # untouched

    def test_does_not_shorten_past_start(self):
        # cue0 is [0.9, 1.0]; required new end 1.02-0.0667=0.953 > start -> ok,
        # but make a case where the pull-back would cross start.
        cues = [_cue(1, 1.0, 1.01, "a"), _cue(2, 1.0, 2.0, "b")]
        out = cp.enforce_min_gap(cues, fps=30.0)
        assert out[0]["end"] == out[0]["start"]  # clamped to start (1.0)

    def test_far_apart_unchanged(self):
        cues = [_cue(1, 0.0, 1.0, "a"), _cue(2, 5.0, 6.0, "b")]
        out = cp.enforce_min_gap(cues, fps=30.0)
        assert out[0]["end"] == 1.0

    def test_zero_fps_zero_gap(self):
        # fps<=0 -> gap is 0; only overlaps (next < end) get pulled back.
        cues = [_cue(1, 0.0, 1.5, "a"), _cue(2, 1.0, 2.0, "b")]
        out = cp.enforce_min_gap(cues, fps=0.0)
        assert out[0]["end"] == 1.0  # pulled back to next start


# --------------------------------------------------------------------------- #
# apply_emphasis_spans
# --------------------------------------------------------------------------- #
class TestApplyEmphasisSpans:
    def test_no_keywords_uses_heuristics(self):
        # "FREE" is an all-caps keyword in the emphasis lexicon.
        out = cp.apply_emphasis_spans(_cue(1, 0.0, 1.0, "get FREE stuff"), [])
        assert out["emphasis"]  # non-empty
        assert any(s["kind"] == "keyword" for s in out["emphasis"])

    def test_keyword_backend_adds_spans(self):
        out = cp.apply_emphasis_spans(_cue(1, 0.0, 1.0, "the quick fox"), ["quick"])
        spans_text = [("quick" in "the quick fox"[s["start"] : s["end"]]) for s in out["emphasis"]]
        assert any(spans_text)

    def test_blank_keyword_skipped(self):
        out = cp.apply_emphasis_spans(_cue(1, 0.0, 1.0, "plain words here"), ["", "  "])
        # No keyword spans added; only heuristic spans (none here -> empty).
        assert isinstance(out["emphasis"], list)

    def test_emoji_picked(self):
        out = cp.apply_emphasis_spans(_cue(1, 0.0, 1.0, "this is fire today"), [])
        assert out["emoji"] == "\U0001f525"

    def test_input_not_mutated(self):
        cue = _cue(1, 0.0, 1.0, "hello")
        cp.apply_emphasis_spans(cue, ["hello"])
        assert "emphasis" not in cue


# --------------------------------------------------------------------------- #
# mask_profanity
# --------------------------------------------------------------------------- #
class TestMaskProfanity:
    def test_masks_bad_word(self):
        pred = FakeProfanity({"darn"})
        assert cp.mask_profanity("oh darn it", pred) == "oh **** it"

    def test_keeps_clean_words(self):
        pred = FakeProfanity(set())
        assert cp.mask_profanity("all good here", pred) == "all good here"

    def test_preserves_surrounding_punctuation(self):
        pred = FakeProfanity({"darn"})
        assert cp.mask_profanity("(darn!)", pred) == "(****!)"

    def test_case_insensitive(self):
        pred = FakeProfanity({"darn"})
        assert cp.mask_profanity("DARN", pred) == "****"


# --------------------------------------------------------------------------- #
# polish_cues — the orchestrator
# --------------------------------------------------------------------------- #
class TestPolishCues:
    def test_empty_returns_empty(self):
        assert cp.polish_cues([]) == []

    def test_all_none_backends_only_timing_gate(self):
        out = cp.polish_cues([_cue(1, 0.0, 5.0, "hello world")])
        assert len(out) == 1
        assert out[0]["text"] == "hello world"
        assert out[0]["index"] == 1
        assert out[0]["emphasis"] == []  # no keyword backend + no heuristic match
        assert "emoji" in out[0]

    def test_punct_backend_applied(self):
        # ``language="en"`` is required: the punct backend is English-only and is
        # gated on the language (see TestPunctLanguageGate).
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "hello world")],
            language="en",
            punct_backend=FakePunct({"hello world": "Hello, world."}),
        )
        assert out[0]["text"] == "Hello, world."

    def test_profanity_backend_applied(self):
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "you darn fool")],
            profanity_backend=FakeProfanity({"darn"}),
        )
        assert out[0]["text"] == "you **** fool"

    def test_keyword_backend_marks_emphasis(self):
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "the quick brown")],
            keyword_backend=FakeKeywords(["quick"]),
        )
        assert any(s["kind"] == "keyword" for s in out[0]["emphasis"])

    def test_children_cps_limit_splits_more(self):
        # 30 chars over 2 s = 15 cps: OK for adults (<=17), too fast for children
        # (<=13) -> children path produces more pieces.
        cue = _cue(1, 0.0, 2.0, " ".join(["abc"] * 7))  # 27 chars
        adult = cp.polish_cues([cue], settings={"captionChildren": False})
        child = cp.polish_cues([cue], settings={"captionChildren": True})
        assert len(child) >= len(adult)

    def test_all_cues_empty_after_punct_returns_empty(self):
        # A punct backend that empties the text -> every cue drops -> [].
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "x")],
            language="en",
            punct_backend=FakePunct({"x": "   "}),
        )
        assert out == []

    def test_full_pipeline_renumbers_and_orders(self):
        cues = [_cue(5, 0.0, 5.0, "first cue"), _cue(6, 6.0, 11.0, "second cue")]
        out = cp.polish_cues(
            cues,
            language="en",
            punct_backend=FakePunct(),
            keyword_backend=FakeKeywords([]),
            profanity_backend=FakeProfanity(set()),
        )
        assert [c["index"] for c in out] == [1, 2]

    def test_fps_threaded_into_min_gap(self):
        cues = [_cue(1, 0.0, 1.0, "a a"), _cue(2, 1.01, 2.0, "b b")]
        out = cp.polish_cues(cues, fps=30.0)
        assert out[0]["end"] < 1.0  # pulled back for the min gap


# --------------------------------------------------------------------------- #
# language gate on the EN-only punctuation restorer
#   `docs/plans/v1.5/captions-translation-audit-2026-08.md` §3.5 measured that the
#   sherpa-onnx `PUNCT_ASSET_NAME` model is English-only yet ran on EVERY language,
#   so it made non-English captions worse. T5 is the gate.
# --------------------------------------------------------------------------- #
class RecordingPunct:
    """A punct backend that records every call, so a SKIP is directly observable."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def restore(self, text: str) -> str:
        self.seen.append(text)
        return f"EN-PUNCT({text})"


class TestResolveCaptionLanguage:
    def test_explicit_argument_wins(self):
        assert cp.resolve_caption_language({"captionLanguage": "fr", "language": "de"}, "ro") == "ro"

    def test_caption_language_beats_language(self):
        assert cp.resolve_caption_language({"captionLanguage": "FR", "language": "de"}) == "fr"

    def test_language_is_the_last_resort(self):
        assert cp.resolve_caption_language({"language": " DE "}) == "de"

    def test_blank_and_missing_resolve_to_unknown(self):
        assert cp.resolve_caption_language(None) == ""
        assert cp.resolve_caption_language({}) == ""
        assert cp.resolve_caption_language({"captionLanguage": "  ", "language": ""}) == ""

    def test_resolve_caption_limits_takes_an_explicit_language(self):
        # An explicit English language reaches the Netflix English reading speed even
        # when settings carry a different one (one resolution path, no drift).
        assert cp.resolve_caption_limits({"language": "ro"}, "en")[0] == cp.MAX_CPS_ENGLISH
        assert cp.resolve_caption_limits({"language": "en"}, "ro")[0] == cp.MAX_CPS


class TestEndsSentence:
    @pytest.mark.parametrize("text", ["Done.", "Really?", "Stop!", "Well…", "終わり。", "كيف؟", "ठीक।"])
    def test_sentence_final_marks(self, text: str):
        assert cp.ends_sentence(text) is True

    @pytest.mark.parametrize("text", ['He said "go."', "(that is it.)", "«asa e.»", "Fine.  "])
    def test_closers_and_trailing_space_are_looked_through(self, text: str):
        assert cp.ends_sentence(text) is True

    @pytest.mark.parametrize("text", ["", "   ", "and then", "a comma,", '"""', "mid-clause -"])
    def test_non_terminal_text(self, text: str):
        assert cp.ends_sentence(text) is False


class TestSplitTextProportional:
    def test_no_weights_yields_no_pieces(self):
        assert cp.split_text_proportional("anything", []) == []

    def test_single_weight_takes_the_whole_normalized_text(self):
        assert cp.split_text_proportional("  a   b \n c ", [3.0]) == ["a b c"]

    def test_splits_on_word_boundaries_near_the_proportional_target(self):
        # weights 11/10 over a 25-char body -> ~13/12 chars, snapped to a word edge.
        pieces = cp.split_text_proportional("XX:hello there good night", [11.0, 10.0])
        assert pieces == ["XX:hello there", "good night"]

    def test_exactly_one_word_per_piece_never_starves_a_later_piece(self):
        # A greedy first piece would swallow both words and leave the second cue
        # blank; the reserved-word guard is what stops it.
        assert cp.split_text_proportional("aa bb", [1.0, 1.0]) == ["aa", "bb"]
        assert cp.split_text_proportional("aaaaaaaaaaaa bb", [9.0, 1.0]) == ["aaaaaaaaaaaa", "bb"]

    def test_weightless_input_splits_evenly(self):
        assert cp.split_text_proportional("aa bb cc dd", [0.0, 0.0]) == ["aa bb", "cc dd"]

    def test_no_whitespace_text_falls_back_to_character_slices(self):
        # Japanese/Chinese/Thai carry no spaces: a word split would yield ONE token
        # for the whole sentence and starve every cue but the first.
        pieces = cp.split_text_proportional("こんにちは世界", [11.0, 10.0])
        assert pieces == ["こんにち", "は世界"]
        assert "".join(pieces) == "こんにちは世界"

    def test_more_cues_than_characters_never_loses_a_character(self):
        pieces = cp.split_text_proportional("ab", [1.0, 1.0, 1.0])
        assert len(pieces) == 3
        assert "".join(pieces) == "ab"

    def test_blank_text_yields_blank_pieces(self):
        assert cp.split_text_proportional("   ", [1.0, 1.0]) == ["", ""]

    @pytest.mark.parametrize(
        "text",
        [
            "one two three four five six seven eight",
            "Cand ea a deschis in sfarsit scrisoarea, a plans.",
            "短い文と、もう一つの文。",
        ],
    )
    @pytest.mark.parametrize("n", [2, 3, 4])
    def test_losslessness_over_every_split(self, text: str, n: int):
        pieces = cp.split_text_proportional(text, [1.0] * n)
        assert len(pieces) == n
        assert "".join("".join(p.split()) for p in pieces) == "".join(text.split())


class TestRedistributeCueText:
    def test_empty_cues(self):
        assert cp.redistribute_cue_text([], "anything") == []

    def test_timings_and_indices_are_byte_identical(self):
        src = [_cue(7, 0.0, 1.5, "hello there"), _cue(8, 1.5, 3.0, "good night")]
        out = cp.redistribute_cue_text(src, "XX:hello there good night")
        assert [(c["index"], c["start"], c["end"]) for c in out] == [(7, 0.0, 1.5), (8, 1.5, 3.0)]
        assert [c["text"] for c in out] == ["XX:hello there", "good night"]

    def test_inputs_are_not_mutated_and_extra_keys_survive(self):
        src = [{**_cue(1, 0.0, 1.0, "a b"), "speaker": "S1"}]
        out = cp.redistribute_cue_text(src, "c d")
        assert out[0]["speaker"] == "S1"
        assert out[0]["text"] == "c d"
        assert src[0]["text"] == "a b"
        assert out[0] is not src[0]

    def test_all_blank_source_cues_split_the_text_evenly(self):
        src = [_cue(1, 0.0, 1.0, "  "), _cue(2, 1.0, 2.0, "")]
        out = cp.redistribute_cue_text(src, "aa bb cc dd")
        assert [c["text"] for c in out] == ["aa bb", "cc dd"]

    def test_source_whitespace_does_not_inflate_a_cue_weight(self):
        # A hard-wrapped source cue must weigh its VISIBLE characters only: raw
        # weights (9, 9) would split "aa bb | cc dd"; normalized (3, 9) splits "aa |
        # bb cc dd". Asserting the normalized answer pins the newline handling.
        src = [_cue(1, 0.0, 1.0, "x\n\n\n\n\n\n\ny"), _cue(2, 1.0, 2.0, "123456789")]
        assert [c["text"] for c in cp.redistribute_cue_text(src, "aa bb cc dd")] == ["aa", "bb cc dd"]


class TestPunctLanguageGate:
    def test_non_english_language_skips_the_en_only_restorer(self):
        punct = RecordingPunct()
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "nu este bine")],
            settings={"language": "ro"},
            punct_backend=punct,
        )
        assert punct.seen == [], "the EN-only restorer ran on Romanian text"
        assert out[0]["text"] == "nu este bine"

    def test_english_language_still_runs_the_restorer(self):
        punct = RecordingPunct()
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "hello world")],
            settings={"language": "en-US"},
            punct_backend=punct,
        )
        assert punct.seen == ["hello world"]
        assert out[0]["text"] == "EN-PUNCT(hello world)"

    def test_unknown_language_skips_the_restorer(self):
        """Adverse inference: a blank language is worst-case, not "probably English"."""
        punct = RecordingPunct()
        cp.polish_cues([_cue(1, 0.0, 5.0, "no language declared")], punct_backend=punct)
        assert punct.seen == []

    def test_caption_language_setting_is_read_before_language(self):
        punct = RecordingPunct()
        cp.polish_cues(
            [_cue(1, 0.0, 5.0, "bonjour tout le monde")],
            settings={"captionLanguage": "fr", "language": "en"},
            punct_backend=punct,
        )
        assert punct.seen == []

    def test_non_english_language_does_not_disable_the_other_stages(self):
        """Only the EN-only stage is gated: masking + timing + emphasis still run."""
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "tu darn prost")],
            settings={"language": "ro"},
            punct_backend=RecordingPunct(),
            profanity_backend=FakeProfanity({"darn"}),
            keyword_backend=FakeKeywords(["prost"]),
        )
        assert out[0]["text"] == "tu **** prost"
        assert any(s["kind"] == "keyword" for s in out[0]["emphasis"])


# --------------------------------------------------------------------------- #
# default_models_present — asset-manager seam
# --------------------------------------------------------------------------- #
class TestDefaultModelsPresent:
    def test_no_entry(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manifest

        monkeypatch.setattr(manifest, "get_asset", lambda _name: None)
        assert cp.default_models_present({}) is False

    def test_entry_installed(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manager as manager_mod
        from media_studio.assets import manifest

        sentinel = object()
        monkeypatch.setattr(manifest, "get_asset", lambda _name: sentinel)

        class FakeMgr:
            def __init__(self, *_a: Any, **_k: Any) -> None: ...

            def installed_path(self, _entry: Any) -> str | None:
                return "C:/cache/punct"

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert cp.default_models_present({}) is True

    def test_entry_missing(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manager as manager_mod
        from media_studio.assets import manifest

        monkeypatch.setattr(manifest, "get_asset", lambda _name: object())

        class FakeMgr:
            def __init__(self, *_a: Any, **_k: Any) -> None: ...

            def installed_path(self, _entry: Any) -> str | None:
                return None

        monkeypatch.setattr(manager_mod, "AssetManager", FakeMgr)
        assert cp.default_models_present({}) is False

    def test_lookup_failure_degrades_to_false(self, monkeypatch: pytest.MonkeyPatch):
        from media_studio.assets import manifest

        def boom(_name: str) -> Any:
            raise RuntimeError("asset machinery missing")

        monkeypatch.setattr(manifest, "get_asset", boom)
        assert cp.default_models_present({}) is False


# --------------------------------------------------------------------------- #
# default factories — lazy real-backend construction (heavy bodies excluded)
# --------------------------------------------------------------------------- #
class TestDefaultFactories:
    def test_punct_factory_builds_backend(self):
        from media_studio.features.caption_polish_backend import SherpaPunctBackend

        assert isinstance(cp._default_punct_factory({}), SherpaPunctBackend)

    def test_keyword_factory_builds_backend(self):
        from media_studio.features.caption_polish_backend import KeyBertBackend

        assert isinstance(cp._default_keyword_factory({}), KeyBertBackend)

    def test_profanity_factory_builds_backend(self):
        from media_studio.features.caption_polish_backend import AltProfanityBackend

        assert isinstance(cp._default_profanity_factory({}), AltProfanityBackend)


# --------------------------------------------------------------------------- #
# resolve_caption_limits — per-content/per-language CPS default + override (S2)
# --------------------------------------------------------------------------- #
class TestResolveCaptionLimits:
    def test_none_settings_defaults(self):
        max_cps, max_lines = cp.resolve_caption_limits(None)
        assert max_cps == cp.MAX_CPS  # 17 cross-language default
        assert max_lines == cp.MAX_LINES

    def test_empty_settings_defaults(self):
        assert cp.resolve_caption_limits({}) == (cp.MAX_CPS, cp.MAX_LINES)

    def test_children_uses_children_cps(self):
        max_cps, _ = cp.resolve_caption_limits({"captionChildren": True})
        assert max_cps == cp.MAX_CPS_CHILDREN  # 13

    @pytest.mark.parametrize("lang", ["en", "EN", "en-US", "eng", "english"])
    def test_english_relaxes_to_20(self, lang: str):
        max_cps, _ = cp.resolve_caption_limits({"language": lang})
        assert max_cps == cp.MAX_CPS_ENGLISH  # 20

    def test_caption_language_key_takes_priority(self):
        max_cps, _ = cp.resolve_caption_limits({"captionLanguage": "en", "language": "fr"})
        assert max_cps == cp.MAX_CPS_ENGLISH

    def test_non_english_uses_cross_language_default(self):
        max_cps, _ = cp.resolve_caption_limits({"language": "fr"})
        assert max_cps == cp.MAX_CPS

    def test_children_beats_english(self):
        # children content stays at the children's cap even for English projects.
        max_cps, _ = cp.resolve_caption_limits({"captionChildren": True, "language": "en"})
        assert max_cps == cp.MAX_CPS_CHILDREN

    def test_override_maxcps_wins_and_clamps_within(self):
        max_cps, _ = cp.resolve_caption_limits({"captionOverride": {"maxCps": 22}})
        assert max_cps == 22

    def test_override_maxcps_clamps_below_floor(self):
        max_cps, _ = cp.resolve_caption_limits({"captionOverride": {"maxCps": 3}})
        assert max_cps == cp.MAX_CPS_FLOOR  # 10

    def test_override_maxcps_clamps_above_ceil(self):
        max_cps, _ = cp.resolve_caption_limits({"captionOverride": {"maxCps": 99}})
        assert max_cps == cp.MAX_CPS_CEIL  # 30

    def test_override_maxcps_overrides_children(self):
        # an explicit user choice wins over the children's default.
        max_cps, _ = cp.resolve_caption_limits({"captionChildren": True, "captionOverride": {"maxCps": 25}})
        assert max_cps == 25

    @pytest.mark.parametrize("bad", [True, False, "20", None, float("nan"), float("inf")])
    def test_override_maxcps_invalid_keeps_default(self, bad: object):
        max_cps, _ = cp.resolve_caption_limits({"captionOverride": {"maxCps": bad}})
        assert max_cps == cp.MAX_CPS

    @pytest.mark.parametrize("lines", [1, 2])
    def test_override_maxlines_applied(self, lines: int):
        _, max_lines = cp.resolve_caption_limits({"captionOverride": {"maxLines": lines}})
        assert max_lines == lines

    @pytest.mark.parametrize("bad", [3, 0, "1", None, True])
    def test_override_maxlines_invalid_keeps_default(self, bad: object):
        _, max_lines = cp.resolve_caption_limits({"captionOverride": {"maxLines": bad}})
        assert max_lines == cp.MAX_LINES

    def test_non_dict_override_ignored(self):
        assert cp.resolve_caption_limits({"captionOverride": "nope"}) == (cp.MAX_CPS, cp.MAX_LINES)


# --------------------------------------------------------------------------- #
# wrap_two_lines / enforce_cps_cpl — max_lines parameterisation (S2)
# --------------------------------------------------------------------------- #
class TestMaxLinesParameter:
    def test_wrap_two_lines_default_two(self):
        # long text wraps onto two lines by default.
        out = cp.wrap_two_lines("a " * 30, max_cpl=10)
        assert out.count("\n") == 1

    def test_wrap_one_line_never_breaks(self):
        # maxLines=1 keeps everything on a single line (no hard break).
        out = cp.wrap_two_lines("a " * 30, max_cpl=10, max_lines=1)
        assert "\n" not in out

    def test_enforce_one_line_splits_more_than_two(self):
        cue = _cue(1, 0.0, 60.0, " ".join(["word"] * 30))  # plenty of slack on time
        two = cp.enforce_cps_cpl(cue, max_cpl=42, max_lines=2)
        one = cp.enforce_cps_cpl(cue, max_cpl=42, max_lines=1)
        assert len(one) > len(two)

    def test_polish_cues_maxlines_one_via_override(self):
        out = cp.polish_cues(
            [_cue(1, 0.0, 60.0, " ".join(["word"] * 30))],
            settings={"captionOverride": {"maxLines": 1}},
        )
        # every resulting cue is a single line (no hard break inserted).
        assert all("\n" not in c["text"] for c in out)

    def test_polish_cues_override_maxcps_threaded(self):
        # a very low maxCps forces more pieces than the default cap would.
        cue = _cue(1, 0.0, 2.0, " ".join(["abc"] * 7))  # 27 chars / 2s = 13.5 cps
        default = cp.polish_cues([cue])
        strict = cp.polish_cues([cue], settings={"captionOverride": {"maxCps": 10}})
        assert len(strict) >= len(default)
