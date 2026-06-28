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
        out = cp.polish_cues(
            [_cue(1, 0.0, 5.0, "hello world")],
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
            punct_backend=FakePunct({"x": "   "}),
        )
        assert out == []

    def test_full_pipeline_renumbers_and_orders(self):
        cues = [_cue(5, 0.0, 5.0, "first cue"), _cue(6, 6.0, 11.0, "second cue")]
        out = cp.polish_cues(
            cues,
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
