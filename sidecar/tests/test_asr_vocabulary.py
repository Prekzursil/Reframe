"""Unit tests for media_studio.features.asr_vocabulary (custom ASR dictionary).

Pure stdlib: no ASR backend, no model, no network. The module under test turns a
user-supplied term list (``settings['asrVocabulary']``) into (a) the two
faster-whisper biasing strings and (b) a deterministic rule-based post-correction
over a §3 ``Transcript`` — the half that works for EVERY engine, including the
NeMo Parakeet adapter which exposes no biasing parameter at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import asr_vocabulary as V


# --------------------------------------------------------------------------- #
# parse_terms — tolerant normalization of an untrusted settings value
# --------------------------------------------------------------------------- #
def test_parse_terms_absent_settings_yields_no_terms():
    assert V.parse_terms(None) == ()
    assert V.parse_terms({}) == ()


@pytest.mark.parametrize("bad", ["Reframe", 7, {"term": "Reframe"}, None])
def test_parse_terms_non_list_value_yields_no_terms(bad: Any):
    assert V.parse_terms({V.VOCAB_SETTINGS_KEY: bad}) == ()


def test_parse_terms_accepts_plain_strings():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe", "  ctranslate2  "]})
    assert [t.term for t in terms] == ["Reframe", "ctranslate2"]
    assert all(t.sounds_like == () for t in terms)


def test_parse_terms_accepts_dicts_with_sounds_like():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame", " reframed ", ""]}]})
    assert len(terms) == 1
    assert terms[0].term == "Reframe"
    assert terms[0].sounds_like == ("re frame", "reframed")


def test_parse_terms_drops_alias_equal_to_the_term_case_insensitively():
    # The canonical term is ALWAYS a pattern, so an alias that only differs in
    # case would be a duplicate rule — dropped at parse time.
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["REFRAME", "re frame"]}]})
    assert terms[0].sounds_like == ("re frame",)


def test_parse_terms_dedupes_aliases_case_insensitively():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame", "Re Frame"]}]})
    assert terms[0].sounds_like == ("re frame",)


@pytest.mark.parametrize("junk", [None, 7, [], {}, {"term": ""}, {"term": "   "}, {"term": 5}, ""])
def test_parse_terms_skips_junk_entries(junk: Any):
    assert V.parse_terms({V.VOCAB_SETTINGS_KEY: [junk, "Reframe"]}) == (V.VocabTerm("Reframe", ()),)


def test_parse_terms_ignores_non_string_and_non_list_sounds_like():
    terms = V.parse_terms(
        {V.VOCAB_SETTINGS_KEY: [{"term": "A", "soundsLike": "nope"}, {"term": "B", "soundsLike": [1]}]}
    )
    assert terms == (V.VocabTerm("A", ()), V.VocabTerm("B", ()))


def test_parse_terms_skips_over_long_terms_and_aliases():
    long_term = "x" * (V.MAX_TERM_CHARS + 1)
    terms = V.parse_terms(
        {V.VOCAB_SETTINGS_KEY: [long_term, {"term": "Reframe", "soundsLike": [long_term, "re frame"]}]}
    )
    assert [t.term for t in terms] == ["Reframe"]
    assert terms[0].sounds_like == ("re frame",)


def test_parse_terms_caps_alias_count_per_term():
    aliases = [f"alias{i}" for i in range(V.MAX_ALIASES_PER_TERM + 5)]
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": aliases}]})
    assert len(terms[0].sounds_like) == V.MAX_ALIASES_PER_TERM


def test_parse_terms_caps_total_term_count():
    many = [f"term{i}" for i in range(V.MAX_TERMS + 10)]
    assert len(V.parse_terms({V.VOCAB_SETTINGS_KEY: many})) == V.MAX_TERMS


def test_parse_terms_dedupes_terms_case_insensitively_first_wins():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe", {"term": "reframe", "soundsLike": ["re frame"]}]})
    assert terms == (V.VocabTerm("Reframe", ()),)


def test_parse_terms_skips_alias_that_is_only_punctuation():
    # An alias with no word characters can never match a word boundary; it is
    # dropped rather than compiled into a rule that can never fire.
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["...", "re frame"]}]})
    assert terms[0].sounds_like == ("re frame",)


def test_parse_terms_accepts_a_tuple_value():
    assert V.parse_terms({V.VOCAB_SETTINGS_KEY: ("Reframe",)}) == (V.VocabTerm("Reframe", ()),)


def test_parse_terms_skips_a_term_with_no_word_characters():
    # A punctuation-only phrase can never satisfy the (?<!\w)/(?!\w) boundaries
    # a rule is built with, so it is refused rather than compiled into a rule
    # that can never fire.
    assert V.parse_terms({V.VOCAB_SETTINGS_KEY: ["...", "Reframe"]}) == (V.VocabTerm("Reframe", ()),)


# --------------------------------------------------------------------------- #
# build_initial_prompt / build_hotwords — the faster-whisper biasing strings
# --------------------------------------------------------------------------- #
def test_build_initial_prompt_none_without_terms():
    assert V.build_initial_prompt(()) is None


def test_build_initial_prompt_lists_the_terms():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe", "ctranslate2"]})
    assert V.build_initial_prompt(terms) == "Glossary: Reframe, ctranslate2."


def test_build_initial_prompt_truncates_to_the_char_budget():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [f"term{i:04d}" for i in range(V.MAX_TERMS)]})
    prompt = V.build_initial_prompt(terms)
    assert prompt is not None
    assert len(prompt) <= V.MAX_PROMPT_CHARS
    # Truncation drops the TAIL, never mangles a term.
    assert prompt.startswith("Glossary: term0000, term0001")
    assert prompt.endswith(".")


def test_build_initial_prompt_returns_none_when_even_one_term_overflows():
    # A single term longer than the whole budget cannot be represented; the
    # biasing string is omitted rather than emitted truncated mid-word.
    term = V.VocabTerm("y" * (V.MAX_PROMPT_CHARS + 10), ())
    assert V.build_initial_prompt((term,)) is None


def test_build_hotwords_none_without_terms():
    assert V.build_hotwords(()) is None


def test_build_hotwords_space_joins_the_terms():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe", "ctranslate2"]})
    assert V.build_hotwords(terms) == "Reframe ctranslate2"


def test_build_hotwords_truncates_to_the_char_budget():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [f"term{i:04d}" for i in range(V.MAX_TERMS)]})
    hot = V.build_hotwords(terms)
    assert hot is not None
    assert len(hot) <= V.MAX_PROMPT_CHARS


def test_build_hotwords_returns_none_when_the_single_term_overflows():
    term = V.VocabTerm("y" * (V.MAX_PROMPT_CHARS + 10), ())
    assert V.build_hotwords((term,)) is None


# --------------------------------------------------------------------------- #
# apply_corrections — the engine-agnostic rule pass
# --------------------------------------------------------------------------- #
def _transcript(*segments: dict[str, Any]) -> dict[str, Any]:
    return {"language": "en", "segments": list(segments), "durationSec": 9.0}


def _seg(text: str, words: list[tuple[str, float, float]]) -> dict[str, Any]:
    return {
        "start": words[0][1] if words else 0.0,
        "end": words[-1][2] if words else 0.0,
        "text": text,
        "words": [{"text": t, "start": s, "end": e} for t, s, e in words],
    }


def test_apply_corrections_without_terms_is_identity():
    t = _transcript(
        _seg(" re frame is good", [(" re", 0.0, 0.5), (" frame", 0.5, 1.0), (" is", 1.0, 1.2), (" good", 1.2, 2.0)])
    )
    assert V.apply_corrections(t, ()) is t


def test_apply_corrections_fixes_a_multi_word_alias_in_segment_text():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(
        _seg(" re frame is good", [(" re", 0.0, 0.5), (" frame", 0.5, 1.0), (" is", 1.0, 1.2), (" good", 1.2, 2.0)])
    )
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " Reframe is good"


def test_apply_corrections_merges_the_word_span_and_keeps_the_outer_timings():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(
        _seg(" re frame is good", [(" re", 0.0, 0.5), (" frame", 0.5, 1.0), (" is", 1.0, 1.2), (" good", 1.2, 2.0)])
    )
    words = V.apply_corrections(t, terms)["segments"][0]["words"]
    assert [w["text"] for w in words] == [" Reframe", " is", " good"]
    assert words[0]["start"] == pytest.approx(0.0)
    assert words[0]["end"] == pytest.approx(1.0)


def test_apply_corrections_fixes_the_canonical_terms_own_casing():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" reframe rocks", [(" reframe", 0.0, 1.0), (" rocks", 1.0, 2.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " Reframe rocks"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" Reframe", " rocks"]


def test_apply_corrections_preserves_trailing_punctuation_on_a_word():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" reframe.", [(" reframe.", 0.0, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " Reframe."
    assert out["segments"][0]["words"][0]["text"] == " Reframe."


def test_apply_corrections_preserves_leading_punctuation_on_a_word():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(' "reframe"', [(' "reframe"', 0.0, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["words"][0]["text"] == ' "Reframe"'


def test_apply_corrections_does_not_match_inside_a_longer_word():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" reframes reframed", [(" reframes", 0.0, 1.0), (" reframed", 1.0, 2.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " reframes reframed"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" reframes", " reframed"]


def test_apply_corrections_prefers_the_longest_alias():
    terms = V.parse_terms(
        {
            V.VOCAB_SETTINGS_KEY: [
                {"term": "OpenAI Codex", "soundsLike": ["open ai codex"]},
                {"term": "OpenAI", "soundsLike": ["open ai"]},
            ]
        }
    )
    t = _transcript(
        _seg(
            " open ai codex ships",
            [(" open", 0.0, 0.4), (" ai", 0.4, 0.8), (" codex", 0.8, 1.2), (" ships", 1.2, 2.0)],
        )
    )
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " OpenAI Codex ships"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" OpenAI Codex", " ships"]


def test_apply_corrections_handles_a_term_with_non_word_characters():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "C++", "soundsLike": ["see plus plus"]}]})
    t = _transcript(
        _seg(" see plus plus code", [(" see", 0.0, 0.4), (" plus", 0.4, 0.8), (" plus", 0.8, 1.2), (" code", 1.2, 2.0)])
    )
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " C++ code"
    assert [w["text"] for w in out["segments"][0]["words"]] == [" C++", " code"]


def test_apply_corrections_leaves_unrelated_text_untouched():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" nothing to see", [(" nothing", 0.0, 1.0), (" to", 1.0, 1.5), (" see", 1.5, 2.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " nothing to see"


def test_apply_corrections_preserves_the_transcript_envelope():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" reframe", [(" reframe", 0.0, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert set(out.keys()) == {"language", "segments", "durationSec"}
    assert out["language"] == "en"
    assert out["durationSec"] == pytest.approx(9.0)
    assert set(out["segments"][0].keys()) == {"start", "end", "text", "words"}


def test_apply_corrections_does_not_mutate_the_input():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg(" reframe", [(" reframe", 0.0, 1.0)]))
    V.apply_corrections(t, terms)
    assert t["segments"][0]["text"] == " reframe"
    assert t["segments"][0]["words"][0]["text"] == " reframe"


def test_apply_corrections_tolerates_a_segment_without_words():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": " reframe"}], "durationSec": 1.0}
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["text"] == " Reframe"
    assert out["segments"][0]["words"] == []


def test_apply_corrections_tolerates_a_transcript_without_segments():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    assert V.apply_corrections({"language": "en", "durationSec": 0.0}, terms)["segments"] == []


def test_apply_corrections_tolerates_non_list_segments():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    assert V.apply_corrections({"segments": "nope"}, terms)["segments"] == []


def test_apply_corrections_tolerates_a_non_dict_segment():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    out = V.apply_corrections({"segments": ["nope"]}, terms)
    assert out["segments"] == [{"start": 0.0, "end": 0.0, "text": "", "words": []}]


def test_apply_corrections_tolerates_a_non_dict_word():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = {"segments": [{"start": 0.0, "end": 1.0, "text": " reframe", "words": ["nope"]}]}
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["words"] == [{"text": "", "start": 0.0, "end": 0.0}]


def test_apply_corrections_tolerates_a_span_running_past_the_last_word():
    # "re" is the last word: the two-word alias cannot fit, so the single-word
    # scan must still run instead of indexing out of range.
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(_seg(" hello re", [(" hello", 0.0, 1.0), (" re", 1.0, 2.0)]))
    out = V.apply_corrections(t, terms)
    assert [w["text"] for w in out["segments"][0]["words"]] == [" hello", " re"]


def test_apply_corrections_skips_a_word_whose_body_is_empty():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: ["Reframe"]})
    t = _transcript(_seg("  reframe", [("   ", 0.0, 0.1), (" reframe", 0.1, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert [w["text"] for w in out["segments"][0]["words"]] == ["   ", " Reframe"]


def test_apply_corrections_caps_the_alias_word_span():
    # An alias longer than MAX_ALIAS_WORDS tokens is refused at parse time so the
    # word scan window stays bounded.
    alias = " ".join(f"w{i}" for i in range(V.MAX_ALIAS_WORDS + 1))
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": [alias, "re frame"]}]})
    assert terms[0].sounds_like == ("re frame",)


def test_apply_corrections_matches_across_a_word_carrying_inner_punctuation():
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(_seg(' "re frame."', [(' "re', 0.0, 0.5), (' frame."', 0.5, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert out["segments"][0]["words"][0]["text"] == ' "Reframe."'


def test_apply_corrections_with_only_blank_hand_built_terms_is_identity():
    # apply_corrections is public: a caller can hand it a VocabTerm that never
    # went through parse_terms. No compilable phrase => the transcript is
    # returned untouched (an empty alternation would match everywhere).
    t = _transcript(_seg(" reframe", [(" reframe", 0.0, 1.0)]))
    assert V.apply_corrections(t, (V.VocabTerm("   ", ()),)) is t


def test_apply_corrections_skips_a_span_whose_words_are_blank():
    # A blank word inside a candidate span makes the joined phrase ambiguous, so
    # the merge is refused and the single-word pass runs instead.
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(_seg(" re  frame", [(" re", 0.0, 0.5), ("   ", 0.5, 0.6), (" frame", 0.6, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert [w["text"] for w in out["segments"][0]["words"]] == [" re", "   ", " frame"]


# --------------------------------------------------------------------------- #
# the settings surface — the key is discoverable and round-trips through the store
# --------------------------------------------------------------------------- #
def test_default_settings_declares_the_vocabulary_key_as_an_empty_list():
    from media_studio.settings_store import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS[V.VOCAB_SETTINGS_KEY] == []


def test_the_term_list_round_trips_through_the_settings_store(tmp_path: Any):
    from media_studio.settings_store import SettingsStore

    path = tmp_path / "settings.json"
    store = SettingsStore(config_path=path)
    # A fresh install is backfilled with the empty list -> no vocabulary.
    assert V.parse_terms(store.get()) == ()

    merged = store.set({V.VOCAB_SETTINGS_KEY: ["Reframe", {"term": "C++", "soundsLike": ["see plus plus"]}]})
    assert V.parse_terms(merged) == (V.VocabTerm("Reframe", ()), V.VocabTerm("C++", ("see plus plus",)))

    # ...and survives a reload from disk (a NEW store over the same file).
    reloaded = V.parse_terms(SettingsStore(config_path=path).get())
    assert [t.term for t in reloaded] == ["Reframe", "C++"]


def test_the_settings_surface_never_writes_an_executable_path():
    # Guard against the vocabulary key drifting into the refused set: it is pure
    # data, so settings.set must accept it (EXECUTABLE_SETTING_KEYS is the list
    # of keys that reach a subprocess argv, and this must never join it).
    from media_studio.settings_store import EXECUTABLE_SETTING_KEYS

    assert V.VOCAB_SETTINGS_KEY not in EXECUTABLE_SETTING_KEYS


def test_apply_corrections_does_not_merge_a_span_that_runs_into_a_longer_word():
    # "re frame-shift" is NOT the phrase "re frame": the span match is a
    # fullmatch, so a half-rewrite ("Reframe-shift" losing "-shift") is refused.
    terms = V.parse_terms({V.VOCAB_SETTINGS_KEY: [{"term": "Reframe", "soundsLike": ["re frame"]}]})
    t = _transcript(_seg(" re frame-shift", [(" re", 0.0, 0.5), (" frame-shift", 0.5, 1.0)]))
    out = V.apply_corrections(t, terms)
    assert [w["text"] for w in out["segments"][0]["words"]] == [" re", " frame-shift"]
