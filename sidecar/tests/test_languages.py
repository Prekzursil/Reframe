"""Tests for the language-inventory SSOT (``media_studio.features.languages``).

The inventory is the sidecar half of the renderer<->sidecar mirror that
``app/renderer/src/lib/languages.conformance.test.ts`` pins. These tests assert
the SHAPE and the PREDICATES; the conformance test asserts the two copies agree.

Every count asserted here was MEASURED, not hand-counted:

* ``WHISPER_LANGS`` (100) — ``_LANGUAGE_CODES`` in ``faster_whisper/tokenizer.py``
  at tag ``v1.2.1`` (the pin in ``sidecar/requirements.lock.txt``), cross-checked
  against openai-whisper's ``LANGUAGES`` dict: both yielded the SAME 100 codes.
* ``PARAKEET_LANGS`` (25) — the ``language:`` YAML block of the
  ``nvidia/parakeet-tdt-0.6b-v3`` model card at the pinned revision
  ``575de92b31b2f60855bca9b70968bde5afb069ba``, cross-checked against that
  card's own prose count ("25").
* ``TIER1_LANGS`` (40) / ``TIER2_LANGS`` (12) — parsed out of
  ``media_studio/models/translation.py``.
"""

from __future__ import annotations

import pytest
from media_studio.features import languages as L
from media_studio.models import translation as T


# --------------------------------------------------------------------------- #
# Inventory shape
# --------------------------------------------------------------------------- #
def test_engine_sets_have_the_measured_sizes() -> None:
    assert len(L.WHISPER_LANGS) == 100
    assert len(L.PARAKEET_LANGS) == 25
    # Spot-checks from each measured source (not an exhaustive restatement).
    assert {"en", "ro", "yue", "haw", "nn"} <= L.WHISPER_LANGS
    assert {"ro", "mt", "et"} <= L.PARAKEET_LANGS
    # Parakeet advertises 25 EUROPEAN languages, so no CJK / Indic.
    assert not ({"ja", "ko", "zh", "hi"} & L.PARAKEET_LANGS)


def test_parakeet_is_a_subset_of_whisper_so_switching_engines_always_recovers() -> None:
    """MEASURED: ``PARAKEET_LANGS - WHISPER_LANGS`` is empty.

    This is what makes the UI advice "switch to Whisper" always correct. If a
    future engine bump adds a language whisper lacks, this test goes RED on
    purpose — the advice text has to be revisited, not the assertion.
    """
    assert L.PARAKEET_LANGS <= L.WHISPER_LANGS
    assert L.ASR_LANGS == L.WHISPER_LANGS


def test_mt_tiers_mirror_translation_py_exactly() -> None:
    assert L.TIER1_LANGS is T.TIER1_LANGS
    assert L.TIER2_LANGS is T.TIER2_LANGS
    assert len(L.TIER1_LANGS) == 40
    assert len(L.TIER2_LANGS) == 12
    assert not (L.TIER1_LANGS & L.TIER2_LANGS)
    assert L.MT_LOCAL_LANGS == L.TIER1_LANGS | L.TIER2_LANGS


def test_tier_names_match_translation_py() -> None:
    """The tier ids :func:`mt_tier` returns are translation.py's own constants."""
    assert L.TIER_LOCAL == T.TIER_LOCAL
    assert L.TIER_LOCAL_HEAVY == T.TIER_LOCAL_HEAVY
    assert L.TIER_HOSTED == T.TIER_HOSTED


def test_supported_is_the_union_of_asr_and_local_mt() -> None:
    assert L.SUPPORTED_LANGS == L.ASR_LANGS | L.MT_LOCAL_LANGS
    assert len(L.SUPPORTED_LANGS) == 102


def test_every_supported_code_has_an_ascii_label_and_vice_versa() -> None:
    assert set(L.LANGUAGE_LABELS) == set(L.SUPPORTED_LANGS)
    assert len(L.LANGUAGE_LABELS) == 102
    for code, label in L.LANGUAGE_LABELS.items():
        assert label.strip() == label and label, code
        # ASCII-only keeps the label safe for ASS/SRT and for a Windows console.
        assert label.isascii(), code
    # No two languages share a display label (an ambiguous dropdown is a defect).
    assert len(set(L.LANGUAGE_LABELS.values())) == 102


def test_the_auto_sentinel_is_not_a_language() -> None:
    assert L.AUTO_DETECT == "auto"
    assert L.AUTO_DETECT not in L.SUPPORTED_LANGS
    assert L.AUTO_DETECT not in L.LANGUAGE_LABELS


def test_common_codes_are_the_curated_creator_head_of_the_list() -> None:
    assert len(L.COMMON_CODES) == 19
    assert set(L.COMMON_CODES) <= L.SUPPORTED_LANGS
    assert L.COMMON_CODES[0] == "en"
    assert len(set(L.COMMON_CODES)) == len(L.COMMON_CODES)
    # ORDERED_CODES leads with the common head, then the rest, and covers all.
    assert L.ORDERED_CODES[: len(L.COMMON_CODES)] == L.COMMON_CODES
    assert set(L.ORDERED_CODES) == L.SUPPORTED_LANGS
    assert len(L.ORDERED_CODES) == 102
    # The tail is sorted by LABEL (what a user scans), not by code.
    tail = L.ORDERED_CODES[len(L.COMMON_CODES) :]
    assert [L.LANGUAGE_LABELS[c] for c in tail] == sorted(L.LANGUAGE_LABELS[c] for c in tail)


# --------------------------------------------------------------------------- #
# normalize_code
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("  EN  ", "en"),
        ("pt-BR", "pt"),
        ("pt_BR", "pt"),
        ("zh_Hant", "zh"),
        ("", ""),
        ("   ", ""),
        ("-", ""),
        (None, ""),
        (7, ""),
    ],
)
def test_normalize_code_is_lenient(raw: object, expected: str) -> None:
    assert L.normalize_code(raw) == expected


def test_normalize_code_agrees_with_translation_normalize_lang_on_every_code() -> None:
    """The lenient normalizer must not DIVERGE from the routing one.

    ``translation.normalize_lang`` raises on blank; ``normalize_code`` returns
    ``""``. On every non-blank input they must agree, or routing and the UI would
    disagree about what code a user picked.
    """
    for code in sorted(L.SUPPORTED_LANGS):
        assert L.normalize_code(code) == T.normalize_lang(code)
    for raw in ("pt-BR", "ZH_hant", "  ro  "):
        assert L.normalize_code(raw) == T.normalize_lang(raw)


# --------------------------------------------------------------------------- #
# resolve_source_language — the AUTO -> None wire translation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", [None, "", "   ", "auto", "AUTO", "  Auto ", "auto-detect"])
def test_resolve_source_language_maps_every_auto_spelling_to_none(raw: object) -> None:
    assert L.resolve_source_language(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [("en", "en"), ("PT-br", "pt"), ("  ro ", "ro")])
def test_resolve_source_language_normalizes_a_real_code(raw: str, expected: str) -> None:
    assert L.resolve_source_language(raw) == expected


def test_resolve_source_language_passes_an_unknown_code_through() -> None:
    """An unrecognized code is NOT silently rewritten to auto-detect.

    Rewriting it would hide a bad request; the engine's own error is the honest
    outcome. (Unknown-but-plausible codes also let a model bump add support
    before this table does.)
    """
    assert L.resolve_source_language("zz") == "zz"


# --------------------------------------------------------------------------- #
# Capability predicates
# --------------------------------------------------------------------------- #
def test_transcription_engines_for_a_code() -> None:
    assert L.transcription_engines("ro") == ("whisper", "parakeet")
    assert L.transcription_engines("ja") == ("whisper",)
    # nb / zu are LOCAL-MT-only: no ASR engine covers them.
    assert L.transcription_engines("nb") == ()
    assert L.transcription_engines("zu") == ()
    # A region subtag is stripped before the lookup (ja is whisper-only; note pt
    # WOULD be both, so it is the wrong probe for a whisper-only assertion).
    assert L.transcription_engines("JA-jp") == ("whisper",)
    assert L.transcription_engines("PT-br") == ("whisper", "parakeet")
    assert L.transcription_engines("zz") == ()


def test_supports_transcription_per_engine() -> None:
    assert L.supports_transcription("whisper", "ja") is True
    assert L.supports_transcription("parakeet", "ja") is False
    assert L.supports_transcription("parakeet", "ro") is True
    # An unknown engine name is not silently treated as whisper.
    assert L.supports_transcription("nope", "en") is False
    assert L.supports_transcription("WHISPER", "en") is True


def test_asr_only_languages_are_the_measured_two() -> None:
    assert sorted(L.MT_LOCAL_LANGS - L.ASR_LANGS) == ["nb", "zu"]


def test_mt_tier_routes_by_language() -> None:
    assert L.mt_tier("ro") == T.TIER_LOCAL
    assert L.mt_tier("ta") == T.TIER_LOCAL_HEAVY
    # Outside local coverage -> hosted (network + credentials required).
    assert L.mt_tier("yue") == T.TIER_HOSTED
    assert L.mt_tier("zz") == T.TIER_HOSTED
    assert L.mt_tier("PT_br") == T.TIER_LOCAL


def test_mt_tier_agrees_with_translation_route_on_every_supported_code() -> None:
    """Two implementations, one answer — else the UI promises the wrong tier."""
    for code in sorted(L.SUPPORTED_LANGS):
        assert L.mt_tier(code) == T.route(code)
