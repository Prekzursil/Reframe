"""Custom ASR dictionary — proper-noun / jargon biasing + rule post-correction.

Proper nouns, brand names and jargon ("Reframe", "ctranslate2", "C++") are the
words an ASR model has the least evidence for, and until now this sidecar had
**no** way to tell either engine about them: a repo-wide search for
``initial_prompt|hotwords|custom_dict|glossary|word_list|customVocab`` over
``sidecar/media_studio`` returned zero hits, and neither
:func:`media_studio.features.transcribe.transcribe_file` nor
:func:`media_studio.features.parakeet_asr.transcribe_file` exposed a
vocabulary parameter.

**What each backend actually supports** — this drove the design, and the two
halves are deliberately different:

* **faster-whisper (pinned 1.2.1, `sidecar/requirements.lock.txt`).**
  ``WhisperModel.transcribe`` accepts ``initial_prompt: str | Iterable[int] |
  None`` ("text … to provide as a prompt for the first window") **and**
  ``hotwords: str | None`` ("Hotwords/hint phrases to provide the model with.
  Has no effect if prefix is not None"). Both are verified against the upstream
  ``v1.2.1`` tag, not from memory. So whisper gets REAL decode-time biasing —
  :func:`build_initial_prompt` and :func:`build_hotwords`. This wrapper never
  passes ``prefix``, so the ``hotwords`` caveat cannot bite.
* **Parakeet (NeMo).** This repo's adapter — ``parakeet_asr_backend.
  _RealParakeetModel.transcribe`` — calls ``self._model.transcribe([audio],
  timestamps=True)`` and forwards **nothing else**; there is no prompt/hotword
  argument on that path at all. So for Parakeet the only available lever is the
  post-hoc rule pass.

:func:`apply_corrections` is therefore the ENGINE-AGNOSTIC half: a deterministic,
whole-word, longest-match-first rewrite over a §3 ``Transcript`` that fixes both
the segment text **and** the word list (timings preserved, multi-word aliases
merged into one word) so karaoke/CTC consumers never see a segment and its words
disagree.

Pure stdlib; no heavy-ML import, no I/O. The settings value is UNTRUSTED (it
crosses the renderer RPC boundary), so every pattern is :func:`re.escape`-d — no
user string is ever compiled as regex syntax — and term/alias counts and lengths
are capped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.features.asr_vocabulary")

#: the settings key holding the user's term list (see ``settings_store``).
VOCAB_SETTINGS_KEY = "asrVocabulary"

#: at most this many distinct terms are honoured (the tail is dropped).
MAX_TERMS = 256
#: a term / alias longer than this is not a term — it is skipped.
MAX_TERM_CHARS = 80
#: at most this many ``soundsLike`` aliases per term.
MAX_ALIASES_PER_TERM = 16
#: an alias may span at most this many whitespace-separated words; this is what
#: bounds the word-merge scan window in :func:`apply_corrections`.
MAX_ALIAS_WORDS = 8
#: hard character budget for either biasing string. Whisper's prompt window is
#: ~224 tokens; this keeps the string well inside it and bounds the settings
#: value's influence on the decode.
MAX_PROMPT_CHARS = 700
#: the sentence frame the glossary terms are listed in for ``initial_prompt``.
PROMPT_PREFIX = "Glossary: "
PROMPT_SUFFIX = "."

# Type aliases matching CONTRACTS.md §3 (plain JSON-able dicts both sides).
Word = dict[str, Any]
Segment = dict[str, Any]
Transcript = dict[str, Any]

#: a run of characters that are NOT word characters (punctuation/space).
_NON_WORD = r"\W*"


@dataclass(frozen=True)
class VocabTerm:
    """One canonical term plus the mis-transcriptions that should map onto it.

    ``term`` is the spelling that ends up in the transcript; ``sounds_like`` are
    additional (already normalized, casefold-deduped) phrases that the ASR is
    known to emit instead. The canonical term is ALWAYS matched too — that is
    what fixes a mere casing miss (``reframe`` -> ``Reframe``).
    """

    term: str
    sounds_like: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class _CompiledRules:
    """The compiled form of a term list (built once per correction pass)."""

    #: alternation used for the per-word / per-segment substitution.
    word_re: re.Pattern[str]
    #: ``\\W* (alternation) \\W*`` used to test "this whole span IS the phrase".
    span_re: re.Pattern[str]
    #: casefolded token tuple -> canonical replacement.
    by_key: dict[tuple[str, ...], str]
    #: the longest alias, in words — the word-merge scan window.
    max_span: int


# --------------------------------------------------------------------------- #
# parsing the untrusted settings value
# --------------------------------------------------------------------------- #
def _has_word_char(value: str) -> bool:
    """True when ``value`` contains at least one word character.

    A phrase made only of punctuation can never satisfy the ``(?<!\\w)`` /
    ``(?!\\w)`` boundaries a rule is built with, so it would compile into a rule
    that can never fire — it is dropped at parse time instead.
    """
    return re.search(r"\w", value) is not None


def _clean_phrase(value: Any) -> str:
    """Normalize one term/alias: trim, collapse inner whitespace, validate.

    Returns ``""`` for anything that is not a usable phrase — a non-string, an
    empty/whitespace-only value, a value longer than :data:`MAX_TERM_CHARS`, or
    one with no word character at all.
    """
    if not isinstance(value, str):
        return ""
    trimmed = " ".join(value.split())
    if not trimmed or len(trimmed) > MAX_TERM_CHARS or not _has_word_char(trimmed):
        return ""
    return trimmed


def _parse_aliases(value: Any, term: str) -> tuple[str, ...]:
    """Normalize a ``soundsLike`` list into deduped, capped alias phrases.

    An alias equal (casefold) to the term is dropped — the canonical term is
    already a pattern, so it would be a duplicate rule. An alias spanning more
    than :data:`MAX_ALIAS_WORDS` words is dropped so the word-merge scan window
    stays bounded.
    """
    if not isinstance(value, list | tuple):
        return ()
    out: list[str] = []
    seen: set[str] = {term.casefold()}
    for raw in value:
        alias = _clean_phrase(raw)
        key = alias.casefold()
        if not alias or key in seen or len(alias.split()) > MAX_ALIAS_WORDS:
            continue
        seen.add(key)
        out.append(alias)
        if len(out) >= MAX_ALIASES_PER_TERM:
            break
    return tuple(out)


def _parse_entry(entry: Any) -> VocabTerm | None:
    """Parse ONE settings entry — a bare string OR ``{term, soundsLike}``."""
    if isinstance(entry, str):
        term = _clean_phrase(entry)
        return VocabTerm(term) if term else None
    if not isinstance(entry, dict):
        return None
    term = _clean_phrase(entry.get("term"))
    if not term:
        return None
    return VocabTerm(term, _parse_aliases(entry.get("soundsLike"), term))


def parse_terms(settings: dict[str, Any] | None) -> tuple[VocabTerm, ...]:
    """Read ``settings[VOCAB_SETTINGS_KEY]`` into normalized :class:`VocabTerm`s.

    TOLERANT by design (mirrors ``transcribe.selected_asr_engine``): a missing
    key, a non-list value, and every unusable entry inside the list degrade to
    "no vocabulary" rather than raising — a typo'd setting must never break
    transcription. Terms are deduped case-insensitively (first wins) and capped
    at :data:`MAX_TERMS`.
    """
    if not isinstance(settings, dict):
        return ()
    raw = settings.get(VOCAB_SETTINGS_KEY)
    if not isinstance(raw, list | tuple):
        return ()
    out: list[VocabTerm] = []
    seen: set[str] = set()
    for entry in raw:
        parsed = _parse_entry(entry)
        if parsed is None or parsed.term.casefold() in seen:
            continue
        seen.add(parsed.term.casefold())
        out.append(parsed)
        if len(out) >= MAX_TERMS:
            break
    return tuple(out)


# --------------------------------------------------------------------------- #
# the faster-whisper biasing strings
# --------------------------------------------------------------------------- #
def _fit(parts: Sequence[str], separator: str, prefix: str, suffix: str) -> str | None:
    """Join as many leading ``parts`` as fit :data:`MAX_PROMPT_CHARS`, else None.

    Truncation drops the TAIL — a term is either fully present or absent, never
    cut mid-word (a half word would bias the decode toward a non-word). When not
    even the first part fits, there is no honest string to send: ``None``.
    """
    chosen: list[str] = []
    for part in parts:
        candidate = prefix + separator.join([*chosen, part]) + suffix
        if len(candidate) > MAX_PROMPT_CHARS:
            break
        chosen.append(part)
    if not chosen:
        return None
    return prefix + separator.join(chosen) + suffix


def build_initial_prompt(terms: Sequence[VocabTerm]) -> str | None:
    """The faster-whisper ``initial_prompt`` for ``terms`` (None when empty).

    ``initial_prompt`` is prepended as *previous context* for the first window,
    so it must read like natural text — a bare comma list biases the decoder
    toward emitting a list. ``"Glossary: A, B."`` keeps it a sentence.
    """
    return _fit([t.term for t in terms], ", ", PROMPT_PREFIX, PROMPT_SUFFIX)


def build_hotwords(terms: Sequence[VocabTerm]) -> str | None:
    """The faster-whisper ``hotwords`` string for ``terms`` (None when empty).

    Unlike ``initial_prompt`` this is a bare space-separated hint phrase list —
    that is the shape faster-whisper documents for the parameter.
    """
    return _fit([t.term for t in terms], " ", "", "")


# --------------------------------------------------------------------------- #
# the engine-agnostic rule pass
# --------------------------------------------------------------------------- #
def _phrase_pattern(tokens: Sequence[str]) -> str:
    """A whole-word regex for ``tokens`` — every token is :func:`re.escape`-d.

    ``(?<!\\w) … (?!\\w)`` (not ``\\b``) so a term ending in punctuation such as
    ``C++`` still anchors correctly, and inner whitespace is ``\\s+`` so the
    phrase matches across any run of spaces/newlines.
    """
    return r"(?<!\w)" + r"\s+".join(re.escape(t) for t in tokens) + r"(?!\w)"


def _compile_rules(terms: Sequence[VocabTerm]) -> _CompiledRules | None:
    """Compile ``terms`` into the two regexes + the key->replacement table.

    Every phrase (each term plus each of its aliases) becomes one alternative,
    ordered LONGEST FIRST so Python's leftmost-first alternation yields
    longest-match semantics (``open ai codex`` wins over ``open ai``). Duplicate
    phrases across terms are dropped, first term wins. ``None`` when no phrase
    survives — the caller then leaves the transcript untouched.
    """
    ordered: list[tuple[str, ...]] = []
    by_key: dict[tuple[str, ...], str] = {}
    for term in terms:
        for phrase in (term.term, *term.sounds_like):
            tokens = tuple(phrase.split())
            key = tuple(t.casefold() for t in tokens)
            if not tokens or key in by_key:
                continue
            by_key[key] = term.term
            ordered.append(tokens)
    if not ordered:
        return None
    ordered.sort(key=lambda toks: (len(toks), sum(len(t) for t in toks)), reverse=True)
    alternation = "|".join(f"(?:{_phrase_pattern(toks)})" for toks in ordered)
    return _CompiledRules(
        word_re=re.compile(alternation, re.IGNORECASE),
        span_re=re.compile(f"{_NON_WORD}(?P<phrase>{alternation}){_NON_WORD}", re.IGNORECASE),
        by_key=by_key,
        max_span=max(len(toks) for toks in ordered),
    )


def _replacement_for(rules: _CompiledRules, matched: str) -> str:
    """Canonical spelling for a matched phrase (identity if somehow unknown).

    The match came from an alternation of the SAME escaped tokens the table is
    keyed on, so the casefolded token tuple is guaranteed to be present; the
    ``get`` default exists so an exotic Unicode case-fold asymmetry degrades to
    "leave the text alone" instead of raising mid-transcription.
    """
    return rules.by_key.get(tuple(t.casefold() for t in matched.split()), matched)


def _rewrite_text(rules: _CompiledRules, text: str) -> str:
    """Apply every rule to ``text`` in ONE pass (no cascade re-matching)."""
    return rules.word_re.sub(lambda m: _replacement_for(rules, m.group(0)), text)


def _num(value: Any) -> float:
    """Coerce a JSON time value to float; anything non-numeric becomes 0.0."""
    return float(value) if isinstance(value, int | float) else 0.0


def _field(item: Any, key: str) -> Any:
    """``item[key]`` when ``item`` is a dict, else ``None`` (untrusted input)."""
    return item.get(key) if isinstance(item, dict) else None


def _leading_ws(text: str) -> str:
    """The leading whitespace of ``text`` (faster-whisper words carry one)."""
    return text[: len(text) - len(text.lstrip())]


def _merge_span(rules: _CompiledRules, words: Sequence[Any], index: int) -> tuple[int, Word] | None:
    """Try to collapse ``words[index:index+n]`` (n>=2) into one corrected word.

    Longest span first. The WHOLE span must be the phrase (modulo surrounding
    punctuation) — ``span_re`` is a ``fullmatch``, so ``re frame-shift`` is left
    alone rather than half-rewritten. On success the merged word keeps the first
    word's start and the last word's end, so no timing is invented or lost.
    """
    limit = min(rules.max_span, len(words) - index)
    for span in range(limit, 1, -1):
        bodies = [str(_field(words[k], "text") or "").strip() for k in range(index, index + span)]
        if not all(bodies):
            continue
        joined = " ".join(bodies)
        matched = rules.span_re.fullmatch(joined)
        if matched is None:
            continue
        head, tail = joined[: matched.start("phrase")], joined[matched.end("phrase") :]
        first = words[index]
        text = _leading_ws(str(_field(first, "text") or "")) + head
        return span, {
            "text": text + _replacement_for(rules, matched.group("phrase")) + tail,
            "start": _num(_field(first, "start")),
            "end": _num(_field(words[index + span - 1], "end")),
        }
    return None


def _correct_words(rules: _CompiledRules, words: Sequence[Any]) -> list[Word]:
    """Rewrite a word list: merge multi-word aliases, then fix single words."""
    out: list[Word] = []
    index = 0
    while index < len(words):
        merged = _merge_span(rules, words, index)
        if merged is not None:
            span, word = merged
            out.append(word)
            index += span
            continue
        raw = words[index]
        out.append(
            {
                "text": _rewrite_text(rules, str(_field(raw, "text") or "")),
                "start": _num(_field(raw, "start")),
                "end": _num(_field(raw, "end")),
            }
        )
        index += 1
    return out


def _correct_segment(rules: _CompiledRules, seg: Any) -> Segment:
    """Rewrite one §3 ``Segment``; start/end pass through untouched."""
    raw_words = _field(seg, "words")
    words = raw_words if isinstance(raw_words, list) else []
    return {
        "start": _num(_field(seg, "start")),
        "end": _num(_field(seg, "end")),
        "text": _rewrite_text(rules, str(_field(seg, "text") or "")),
        "words": _correct_words(rules, words),
    }


def apply_corrections(transcript: Transcript, terms: Sequence[VocabTerm]) -> Transcript:
    """Return ``transcript`` with every vocabulary rule applied (PURE).

    The input is never mutated; with no usable terms the SAME object is returned
    so the zero-vocabulary path costs nothing. Both the segment text and the word
    list are rewritten by the same compiled rules, so a karaoke/CTC consumer can
    never see a segment whose text and words disagree.
    """
    rules = _compile_rules(terms)
    if rules is None:
        return transcript
    raw_segments = transcript.get("segments")
    segments = raw_segments if isinstance(raw_segments, list) else []
    return {**transcript, "segments": [_correct_segment(rules, seg) for seg in segments]}


__all__ = [
    "MAX_ALIASES_PER_TERM",
    "MAX_ALIAS_WORDS",
    "MAX_PROMPT_CHARS",
    "MAX_TERMS",
    "MAX_TERM_CHARS",
    "VOCAB_SETTINGS_KEY",
    "VocabTerm",
    "apply_corrections",
    "build_hotwords",
    "build_initial_prompt",
    "parse_terms",
]
