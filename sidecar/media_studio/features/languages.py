"""The ONE language inventory — the sidecar half of the renderer<->sidecar mirror.

Before this module the app carried **four** disagreeing language vocabularies
(``docs/plans/v1.5/captions-translation-audit-2026-08.md`` §1.1): a 19-entry UI
list, a *second* 9-entry list hardcoded in the Transcribe panel, the 52-code local
MT routing table, and the two ASR engines' real sets — which existed only as
prose in a docstring, so nothing in the app could reason about them. This module
is the single definition; ``app/renderer/src/lib/languages.ts`` is its mirror and
``app/renderer/src/lib/languages.conformance.test.ts`` fails the build if the two
drift (the same pattern ``captionTemplates.conformance.test.ts`` uses).

**Every set below was MEASURED from a pinned source, not hand-written:**

* :data:`WHISPER_LANGS` (100) — the ``_LANGUAGE_CODES`` tuple of
  ``faster_whisper/tokenizer.py`` at tag ``v1.2.1``, which is the pin in
  ``sidecar/requirements.lock.txt``. Cross-checked against a mechanically
  different artifact — openai-whisper's ``LANGUAGES`` dict, a different file in a
  different repo — which yielded the SAME 100 codes with zero difference either
  way. (This settles the audit's §1.2 ``NOT-CHECKED``, which could not assert a
  count because ``faster_whisper`` is not importable in the ambient Python.)
* :data:`PARAKEET_LANGS` (25) — the ``language:`` YAML block of the
  ``nvidia/parakeet-tdt-0.6b-v3`` model card at the revision this repo pins,
  ``575de92b31b2f60855bca9b70968bde5afb069ba`` (``parakeet_asr.py``). Cross-checked
  against that card's own prose count ("25"). Measured relation:
  ``PARAKEET_LANGS`` is a strict SUBSET of ``WHISPER_LANGS`` — which is what makes
  the "switch to Whisper" advice in :func:`capability_note`'s renderer twin always
  correct.
* :data:`TIER1_LANGS` (40) / :data:`TIER2_LANGS` (12) — the local TranslateGemma
  coverage. **Defined here and imported by** ``models.translation``, so there is
  one definition rather than a copy. (The dependency runs THIS way because this
  module is pure stdlib: ``translation`` registers HF assets at import time, so a
  vocabulary module must not import it.)

Labels are English display names taken from openai-whisper's ``LANGUAGES`` map,
title-cased, with a short reasoned override list for endonyms/ambiguities. They
are ASCII-only so they are safe in an ASS/SRT document and on a Windows console.

Pure stdlib, no side effects at import time.
"""

from __future__ import annotations

#: The sentinel "let the engine detect the language" choice. NOT a language code —
#: it must be translated to ``None`` before it reaches an engine (see
#: :func:`resolve_source_language`); faster-whisper would read the literal string
#: ``"auto"`` as a language id (``transcribe.transcribe_file`` forwards it straight
#: through to ``whisper_model.transcribe(language=...)``).
AUTO_DETECT: str = "auto"

#: Every spelling of "auto-detect" a persisted setting or an older build may carry.
_AUTO_ALIASES: frozenset[str] = frozenset({"auto", "auto-detect", "autodetect", "detect"})

# --------------------------------------------------------------------------- #
# ASR engines
# --------------------------------------------------------------------------- #
WHISPER_ENGINE: str = "whisper"
PARAKEET_ENGINE: str = "parakeet"

#: faster-whisper v1.2.1 ``tokenizer._LANGUAGE_CODES`` (measured; see the header).
WHISPER_LANGS: frozenset[str] = frozenset(
    {
        "af",
        "am",
        "ar",
        "as",
        "az",
        "ba",
        "be",
        "bg",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "cs",
        "cy",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "eu",
        "fa",
        "fi",
        "fo",
        "fr",
        "gl",
        "gu",
        "ha",
        "haw",
        "he",
        "hi",
        "hr",
        "ht",
        "hu",
        "hy",
        "id",
        "is",
        "it",
        "ja",
        "jw",
        "ka",
        "kk",
        "km",
        "kn",
        "ko",
        "la",
        "lb",
        "ln",
        "lo",
        "lt",
        "lv",
        "mg",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "ne",
        "nl",
        "nn",
        "no",
        "oc",
        "pa",
        "pl",
        "ps",
        "pt",
        "ro",
        "ru",
        "sa",
        "sd",
        "si",
        "sk",
        "sl",
        "sn",
        "so",
        "sq",
        "sr",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "tk",
        "tl",
        "tr",
        "tt",
        "uk",
        "ur",
        "uz",
        "vi",
        "yi",
        "yo",
        "yue",
        "zh",
    }
)

#: ``nvidia/parakeet-tdt-0.6b-v3`` @ 575de92 — 25 European languages (measured).
PARAKEET_LANGS: frozenset[str] = frozenset(
    {
        "bg",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fi",
        "fr",
        "hr",
        "hu",
        "it",
        "lt",
        "lv",
        "mt",
        "nl",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sv",
        "uk",
    }
)

#: engine id -> the languages that engine can transcribe.
ASR_ENGINE_LANGS: dict[str, frozenset[str]] = {
    WHISPER_ENGINE: WHISPER_LANGS,
    PARAKEET_ENGINE: PARAKEET_LANGS,
}

#: Every language SOME wired ASR engine can transcribe.
ASR_LANGS: frozenset[str] = WHISPER_LANGS | PARAKEET_LANGS

# --------------------------------------------------------------------------- #
# Local MT coverage (imported by models.translation — defined here, once)
# --------------------------------------------------------------------------- #
#: Tier ids, mirroring ``models.translation``'s constants (pinned by a test rather
#: than imported, because ``translation`` must not be imported from here).
TIER_LOCAL: str = "tier1"
TIER_LOCAL_HEAVY: str = "tier2"
TIER_HOSTED: str = "tier3"

#: TranslateGemma-4B (fast, fully GPU-resident) coverage.
TIER1_LANGS: frozenset[str] = frozenset(
    {
        "ar",
        "bg",
        "ca",
        "cs",
        "da",
        "de",
        "el",
        "en",
        "es",
        "et",
        "fa",
        "fi",
        "fr",
        "he",
        "hi",
        "hr",
        "hu",
        "id",
        "it",
        "ja",
        "ko",
        "lt",
        "lv",
        "ms",
        "nb",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "ru",
        "sk",
        "sl",
        "sr",
        "sv",
        "th",
        "tr",
        "uk",
        "vi",
        "zh",
    }
)

#: TranslateGemma-12B (partial offload, labelled SLOW) coverage.
TIER2_LANGS: frozenset[str] = frozenset(
    {
        "bn",
        "gu",
        "is",
        "kn",
        "ml",
        "mr",
        "pa",
        "sw",
        "ta",
        "te",
        "ur",
        "zu",
    }
)

#: Everything the LOCAL translator covers (no network, no credentials).
MT_LOCAL_LANGS: frozenset[str] = TIER1_LANGS | TIER2_LANGS

# --------------------------------------------------------------------------- #
# The offered inventory
# --------------------------------------------------------------------------- #
#: The curated creator head of the picker (the pre-v1.5 list), in its own order.
#: These are NOT a capability claim — every one is also in the sets above; the
#: ordering exists so the common choices stay one glance away in a 102-item list
#: (V1-GRILL §h intent).
COMMON_CODES: tuple[str, ...] = (
    "en",
    "es",
    "pt",
    "fr",
    "de",
    "it",
    "nl",
    "pl",
    "ru",
    "uk",
    "tr",
    "ar",
    "hi",
    "id",
    "vi",
    "th",
    "ja",
    "ko",
    "zh",
)

#: code -> English display label, in PICKER ORDER: the common head first, then the
#: rest sorted by label. The renderer mirror must match this order exactly.
LANGUAGE_LABELS: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "tr": "Turkish",
    "ar": "Arabic",
    "hi": "Hindi",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "af": "Afrikaans",
    "sq": "Albanian",
    "am": "Amharic",
    "hy": "Armenian",
    "as": "Assamese",
    "az": "Azerbaijani",
    "ba": "Bashkir",
    "eu": "Basque",
    "be": "Belarusian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "br": "Breton",
    "bg": "Bulgarian",
    "my": "Burmese",
    "yue": "Cantonese",
    "ca": "Catalan",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "et": "Estonian",
    "fo": "Faroese",
    "fi": "Finnish",
    "gl": "Galician",
    "ka": "Georgian",
    "el": "Greek",
    "gu": "Gujarati",
    "ht": "Haitian Creole",
    "ha": "Hausa",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "hu": "Hungarian",
    "is": "Icelandic",
    "jw": "Javanese",
    "kn": "Kannada",
    "kk": "Kazakh",
    "km": "Khmer",
    "lo": "Lao",
    "la": "Latin",
    "lv": "Latvian",
    "ln": "Lingala",
    "lt": "Lithuanian",
    "lb": "Luxembourgish",
    "mk": "Macedonian",
    "mg": "Malagasy",
    "ms": "Malay",
    "ml": "Malayalam",
    "mt": "Maltese",
    "mi": "Maori",
    "mr": "Marathi",
    "mn": "Mongolian",
    "ne": "Nepali",
    "no": "Norwegian",
    "nb": "Norwegian Bokmal",
    "nn": "Norwegian Nynorsk",
    "oc": "Occitan",
    "ps": "Pashto",
    "fa": "Persian",
    "pa": "Punjabi",
    "ro": "Romanian",
    "sa": "Sanskrit",
    "sr": "Serbian",
    "sn": "Shona",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "su": "Sundanese",
    "sw": "Swahili",
    "sv": "Swedish",
    "tl": "Tagalog",
    "tg": "Tajik",
    "ta": "Tamil",
    "tt": "Tatar",
    "te": "Telugu",
    "bo": "Tibetan",
    "tk": "Turkmen",
    "ur": "Urdu",
    "uz": "Uzbek",
    "cy": "Welsh",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zu": "Zulu",
}

#: The offered inventory in picker order (the keys of :data:`LANGUAGE_LABELS`).
ORDERED_CODES: tuple[str, ...] = tuple(LANGUAGE_LABELS)

#: Every language the app offers: transcribable by SOME engine, or translatable
#: locally. Derived from the engines, never curated by hand.
SUPPORTED_LANGS: frozenset[str] = ASR_LANGS | MT_LOCAL_LANGS


# --------------------------------------------------------------------------- #
# Predicates
# --------------------------------------------------------------------------- #
def normalize_code(raw: object) -> str:
    """Normalize a language tag to a bare lowercase primary subtag, leniently.

    ``pt-BR`` / ``pt_BR`` -> ``pt``; ``zh_Hant`` -> ``zh``; ``EN`` -> ``en``.

    Unlike ``models.translation.normalize_lang`` (which RAISES on a blank tag so a
    missing ``targetLang`` fails loudly at the routing boundary) this returns
    ``""``, because the UI legitimately holds "nothing chosen yet". The two agree
    on every non-blank input — ``test_languages.py`` asserts that across the whole
    inventory so the lenient copy cannot drift from the routing one.

    A NON-STRING input is ``""``, not its ``str()``: this sits at a system boundary
    (a persisted setting, an RPC param) where ``7`` must not become the language
    ``"7"`` and get forwarded to an engine.
    """
    if not isinstance(raw, str):
        return ""
    code = raw.strip().lower().replace("_", "-")
    return code.split("-", 1)[0].strip()


def resolve_source_language(raw: object) -> str | None:
    """The SOURCE-language value to hand an ASR engine: a code, or ``None``.

    ``None`` means "auto-detect", which is what every wired engine already does
    when given no language (``transcribe.transcribe_file``'s docstring; Parakeet
    reads the detected code off ``info.language``). Auto-detect therefore needed
    EXPOSING, not implementing.

    Every auto spelling collapses to ``None``. An unrecognized-but-non-blank code
    passes through unchanged: rewriting it would hide a bad request behind a
    silent auto-detect, and it also lets a model bump support a code before this
    table lists it.
    """
    code = normalize_code(raw)
    if not code or code in _AUTO_ALIASES:
        return None
    return code


def transcription_engines(code: object) -> tuple[str, ...]:
    """The wired ASR engines that can transcribe ``code`` (whisper first)."""
    norm = normalize_code(code)
    return tuple(engine for engine in (WHISPER_ENGINE, PARAKEET_ENGINE) if norm in ASR_ENGINE_LANGS[engine])


def supports_transcription(engine: object, code: object) -> bool:
    """Whether ``engine`` can transcribe ``code``. An unknown engine is ``False``.

    An unknown engine name is deliberately NOT treated as the whisper default:
    this answers "is this combination safe to offer", and guessing would turn a
    typo into a false promise. (``transcribe.selected_asr_engine`` separately
    resolves an unknown *setting* to whisper — that is engine RESOLUTION, a
    different question.)
    """
    langs = ASR_ENGINE_LANGS.get(str(engine or "").strip().lower())
    if langs is None:
        return False
    return normalize_code(code) in langs


def mt_tier(code: object) -> str:
    """The translation tier ``code`` routes to (mirrors ``translation.route``)."""
    norm = normalize_code(code)
    if norm in TIER1_LANGS:
        return TIER_LOCAL
    if norm in TIER2_LANGS:
        return TIER_LOCAL_HEAVY
    return TIER_HOSTED
