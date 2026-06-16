"""Emphasis annotation — deterministic per-cue keyword highlight + emoji (P4 §8a).

OpusClip-style captions highlight the "punchy" words in a line (a colored or
boxed word) and sometimes punctuate the line with a single trailing emoji. This
module computes that annotation **deterministically** from the cue text alone:

  * a small, frozen keyword lexicon (marketing / hook words), plus
  * three text heuristics — ALL-CAPS tokens, tokens containing a digit, and
    long tokens (>= :data:`LONG_WORD_MIN_LEN` chars).

and a small keyword -> emoji map for an optional single trailing emoji.

NO LLM, NO network, NO randomness (PLAN-P4 §8a): the same cue text always yields
the same spans + emoji, so the libass burn, the Remotion render, and the live
HTML overlay all agree on what to highlight.

The annotation is ADDITIVE and IMMUTABLE: :func:`annotate` returns brand-new cue
dicts (the inputs are never mutated) carrying two extra contract fields:

    emphasis: list[{start:int, end:int, kind:str}]   # char offsets into ``text``
    emoji:    str                                     # "" when none applies

``start``/``end`` are half-open character offsets into the cue's ORIGINAL
``text`` (so a renderer can slice ``text[start:end]`` to find the highlighted
word). ``kind`` is one of :data:`KINDS` (the reason the word was emphasised),
ordered by precedence so a word matched by several rules reports the strongest.

When ``enable`` is falsey, :func:`annotate` returns copies with EMPTY emphasis +
no emoji (the clean/minimal templates), so callers can thread one flag through
the export pipeline without branching.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# A Cue is the contract's ``{index:int, start:float, end:float, text:str}``; we
# accept it duck-typed as a Mapping so this module stays import-light (mirrors
# caption.CueLike). Output cues add ``emphasis`` + ``emoji``.
CueLike = Mapping[str, Any]

# --------------------------------------------------------------------------- #
# the deterministic lexicons (FROZEN — keep the overlay/libass/remotion in sync)
# --------------------------------------------------------------------------- #
#: Hook / marketing words that read as "punchy" and get highlighted. Lower-case;
#: matching is case-insensitive on the token's letters-only form.
KEYWORDS: frozenset[str] = frozenset(
    {
        "free",
        "now",
        "new",
        "secret",
        "secrets",
        "best",
        "worst",
        "never",
        "always",
        "stop",
        "warning",
        "huge",
        "massive",
        "crazy",
        "insane",
        "amazing",
        "incredible",
        "shocking",
        "money",
        "rich",
        "million",
        "billion",
        "win",
        "winning",
        "instantly",
        "fast",
        "easy",
        "proven",
        "guaranteed",
        "first",
        "last",
        "only",
        "everyone",
        "nobody",
        "everything",
        "nothing",
        "love",
        "hate",
        "danger",
        "dangerous",
        "important",
        "must",
        "ultimate",
        "exclusive",
        "viral",
        "boom",
        "fire",
        "growth",
        "hack",
        "mistake",
        "mistakes",
        "truth",
        "real",
        "biggest",
        "powerful",
        "power",
    }
)

#: Single trailing emoji for a line whose text mentions one of these stems. The
#: FIRST matching stem (in iteration order over a stable list) wins, so the map
#: is deterministic. Stems match on a word boundary, case-insensitively.
EMOJI_MAP: tuple[tuple[str, str], ...] = (
    ("fire", "\U0001f525"),  # 🔥
    ("money", "\U0001f4b0"),  # 💰
    ("rich", "\U0001f4b0"),  # 💰
    ("million", "\U0001f4b0"),  # 💰
    ("billion", "\U0001f4b0"),  # 💰
    ("win", "\U0001f3c6"),  # 🏆
    ("winning", "\U0001f3c6"),  # 🏆
    ("love", "❤️"),  # ❤️
    ("warning", "⚠️"),  # ⚠️
    ("danger", "⚠️"),  # ⚠️
    ("crazy", "\U0001f92f"),  # 🤯
    ("insane", "\U0001f92f"),  # 🤯
    ("shocking", "\U0001f92f"),  # 🤯
    ("boom", "\U0001f4a5"),  # 💥
    ("growth", "\U0001f4c8"),  # 📈
    ("idea", "\U0001f4a1"),  # 💡
    ("secret", "\U0001f92b"),  # 🤫
    ("secrets", "\U0001f92b"),  # 🤫
    ("time", "⏰"),  # ⏰
    ("fast", "⚡"),  # ⚡
)

#: Minimum letters in a token for the "long word" heuristic to fire.
LONG_WORD_MIN_LEN = 8

#: Minimum letters in an ALL-CAPS token for the caps heuristic (avoids "A"/"I").
CAPS_MIN_LEN = 2

#: Emphasis kinds, STRONGEST first — when several rules match one token the
#: earliest in this tuple is reported (precedence is deterministic).
KINDS: tuple[str, ...] = ("keyword", "caps", "number", "long")

#: Caption styles for which emphasis defaults OFF — the clean / minimal looks
#: (and the no-caption passes). Every other (OpusClip-style) template defaults
#: emphasis ON (PLAN-P4 §8a). Lower-case ids; matched case-insensitively.
CLEAN_STYLES: frozenset[str] = frozenset({"clean", "subtitle", "none", "libass", ""})


def default_emphasis_for_style(style: str | None) -> bool:
    """Whether emphasis defaults ON for caption ``style`` (PLAN-P4 §8a).

    ON for the OpusClip-style templates (bold/hormozi/neon/...); OFF for the
    clean/minimal looks + the no-caption passes (:data:`CLEAN_STYLES`).
    """
    return str(style or "").strip().lower() not in CLEAN_STYLES


def resolve_emphasis(settings: Mapping[str, Any] | None) -> bool:
    """Resolve the effective ``emphasis`` flag from export settings.

    An explicit ``settings["emphasis"]`` wins (threaded through the export params
    like ``captionStyle``); when absent it falls back to the per-style default
    (:func:`default_emphasis_for_style` on ``settings["captionStyle"]``). Pure.
    """
    settings = settings or {}
    explicit = settings.get("emphasis")
    if explicit is not None:
        return bool(explicit)
    return default_emphasis_for_style(settings.get("captionStyle"))


# A token = a run of word characters (incl. apostrophes) optionally with a
# trailing/leading digit cluster. We keep the token's char offsets so spans
# point into the ORIGINAL text. ``\w`` here is unicode-aware by default.
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def _letters_only(token: str) -> str:
    """Lower-cased letters of ``token`` (drops digits/punctuation) for matching."""
    return "".join(_LETTER_RE.findall(token)).lower()


def classify_token(token: str) -> str | None:
    """Return the strongest emphasis :data:`KINDS` for ``token`` (or ``None``).

    Pure + deterministic. Precedence (strongest first):
      1. ``keyword`` — the letters-only form is in :data:`KEYWORDS`;
      2. ``caps``    — an ALL-CAPS token of >= :data:`CAPS_MIN_LEN` letters;
      3. ``number``  — the token contains a digit;
      4. ``long``    — a token of >= :data:`LONG_WORD_MIN_LEN` letters.
    """
    letters = _letters_only(token)
    if letters and letters in KEYWORDS:
        return "keyword"
    # ALL-CAPS: every cased letter is upper-case and there are enough of them.
    cased = [ch for ch in token if ch.isalpha()]
    if len(cased) >= CAPS_MIN_LEN and all(ch.isupper() for ch in cased):
        return "caps"
    if _DIGIT_RE.search(token):
        return "number"
    if len(letters) >= LONG_WORD_MIN_LEN:
        return "long"
    return None


def find_emphasis_spans(text: str) -> list[dict[str, Any]]:
    """Char-offset emphasis spans for ``text`` (sorted, non-overlapping).

    Each span is ``{start, end, kind}`` with half-open char offsets into ``text``
    (so ``text[start:end]`` is the highlighted token). Tokens are scanned
    left-to-right; the spans they yield are therefore already sorted and
    non-overlapping (one regex match per token).
    """
    spans: list[dict[str, Any]] = []
    if not text:
        return spans
    for match in _TOKEN_RE.finditer(text):
        kind = classify_token(match.group(0))
        if kind is None:
            continue
        spans.append({"start": match.start(), "end": match.end(), "kind": kind})
    return spans


def pick_emoji(text: str) -> str:
    """The single trailing emoji for ``text`` (``""`` when none applies).

    Scans :data:`EMOJI_MAP` in order and returns the emoji for the FIRST stem
    that appears as a whole word in ``text`` (case-insensitive). Deterministic:
    the map order is the tie-break, never the text order.
    """
    if not text:
        return ""
    lowered = text.lower()
    for stem, emoji in EMOJI_MAP:
        if re.search(rf"\b{re.escape(stem)}\b", lowered):
            return emoji
    return ""


def normalize_spans(raw: Any, text_len: int | None = None) -> list[dict[str, Any]]:
    """Validated, sorted, non-overlapping emphasis spans from arbitrary input.

    Shared by both caption engines (libass + remotion) so a malformed annotation
    can never reach a render. Each kept span is ``{start:int, end:int, kind:str}``
    with a half-open range (``end > start``); when ``text_len`` is given the
    offsets are clamped to ``[0, text_len]``. Non-mappings / non-numeric offsets
    are dropped; spans overlapping one already kept are skipped (so inline render
    codes never nest). Pure.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    candidates: list[tuple] = []
    for span in raw:
        if not isinstance(span, Mapping):
            continue
        try:
            # int(None) deliberately raises TypeError -> skip (same idiom as
            # fillers.py); the explicit arg-type ignore documents that intent.
            start = int(span.get("start"))  # type: ignore[arg-type]
            end = int(span.get("end"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if text_len is not None:
            start = max(0, min(start, text_len))
            end = max(0, min(end, text_len))
        if end > start:
            candidates.append((start, end, str(span.get("kind") or "")))
    candidates.sort()
    out: list[dict[str, Any]] = []
    last_end = 0
    for start, end, kind in candidates:
        if start < last_end:
            continue  # overlaps a kept span: skip
        out.append({"start": start, "end": end, "kind": kind})
        last_end = end
    return out


def annotate_cue(cue: CueLike, *, enable: bool = True) -> dict[str, Any]:
    """Return a NEW cue dict with ``emphasis`` + ``emoji`` added (immutable).

    The input cue is copied (never mutated). When ``enable`` is falsey the copy
    carries an empty ``emphasis`` list + ``""`` emoji, so the field shape is
    stable whether or not emphasis is on (clean/minimal templates pass it off).
    """
    out = dict(cue)
    text = str(cue.get("text", "") or "")
    if enable:
        out["emphasis"] = find_emphasis_spans(text)
        out["emoji"] = pick_emoji(text)
    else:
        out["emphasis"] = []
        out["emoji"] = ""
    return out


def annotate(cues: Sequence[CueLike], enable: bool = True) -> list[dict[str, Any]]:
    """Annotate every cue with deterministic emphasis spans + a trailing emoji.

    Returns a brand-new list of new cue dicts; the inputs are never mutated
    (PLAN-P4 §8a immutability). Pure + deterministic — same input, same output;
    NO LLM, NO network, NO randomness. Applied in BOTH caption paths (libass +
    remotion) and mirrored by the live HTML overlay.
    """
    return [annotate_cue(cue, enable=enable) for cue in (cues or [])]


__all__ = [
    "CAPS_MIN_LEN",
    "CLEAN_STYLES",
    "EMOJI_MAP",
    "KEYWORDS",
    "KINDS",
    "LONG_WORD_MIN_LEN",
    "annotate",
    "annotate_cue",
    "classify_token",
    "default_emphasis_for_style",
    "find_emphasis_spans",
    "pick_emoji",
    "resolve_emphasis",
]
