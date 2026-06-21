"""Caption-accuracy polish (Phase-8 WU9 — punct/casing/segmentation/emphasis/profanity).

This module replaces the greedy char-packing caption build with a SOTA polish
pass that makes captions both *readable* (Netflix timing/segmentation rules) and
*accurate* (restored punctuation + casing, highlighted keywords, masked
profanity). It runs on the frozen Cue contract ``{index, start, end, text}`` and
returns brand-new cue dicts (the inputs are never mutated).

Design — the canonical Phase-8 seam pattern (see ``quality_gate`` /
``audio_saliency`` / ``diarize``):

  * **Pure half (fully covered, no heavy deps):** the Netflix CPS/CPL/min-gap
    constants, :func:`cps_of`, :func:`wrap_two_lines`, :func:`enforce_cps_cpl`
    (the timing + segmentation gate — pure stdlib string/number math), and
    :func:`polish_cues` (the orchestrator that threads the optional model seams
    through the pure gate). Every line here is unit-tested with hand-built cues.

  * **Heavy half (behind three Protocol seams, never imported at module load):**
    the real sherpa-onnx punctuation+casing restorer, the KeyBERT keyword
    extractor, and the alt-profanity-check masker each live in a sibling
    ``caption_polish_backend.py`` and are built LAZILY by the
    ``_default_*_factory`` helpers. Tests inject fakes implementing the three
    Protocols, so no sherpa-onnx / keybert / sklearn / torch is ever touched.

Degrade rule (the §3 missing-modality contract): when a backend seam is ``None``
its stage is simply skipped — punctuation/casing is left as-is, no emphasis is
marked, no profanity is masked. The CPS/CPL/min-gap gate needs no model and is
ALWAYS applied. A backend never fabricates output it could not compute, and no
stage ever raises on a missing model.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ..util import get_logger
from . import emphasis as _emphasis

log = get_logger("media_studio.features.caption_polish")

#: A Cue per the frozen contract ``{index:int, start:float, end:float, text:str}``
#: (rpc.ts / caption.CueLike). Plain dicts on the wire; output cues additionally
#: carry ``emphasis`` + ``emoji`` (mirrors ``emphasis.annotate_cue``).
Cue = dict[str, Any]

# --------------------------------------------------------------------------- #
# Netflix Timed Text Style Guide constants (RULES, no model — manifest #15)
#   https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977
# --------------------------------------------------------------------------- #
#: max reading speed, characters/second, adult content.
MAX_CPS = 17
#: max reading speed, characters/second, children's content.
MAX_CPS_CHILDREN = 13
#: max characters per line (Latin scripts).
MAX_CPL = 42
#: max lines per cue.
MAX_LINES = 2
#: minimum gap between consecutive cues, in frames.
MIN_GAP_FRAMES = 2

#: default frame rate used to convert :data:`MIN_GAP_FRAMES` into seconds.
DEFAULT_FPS = 30.0

#: the tiny EN-only sherpa-onnx punctuation+casing model (manifest #15).
PUNCT_ASSET_NAME = "sherpa-onnx-punct-en"

# --------------------------------------------------------------------------- #
# the three heavy backend seams — never imported at module load
# --------------------------------------------------------------------------- #


class PunctBackend(Protocol):
    """Restores punctuation + sentence casing on a raw (lower-cased) line.

    The real impl wraps sherpa-onnx's CT-Transformer punctuation model. Tests
    inject a fake that returns a hand-built capitalised/punctuated string.
    """

    def restore(self, text: str) -> str:
        """Return ``text`` with punctuation + casing restored."""
        ...  # pragma: no cover - Protocol stub (the body lives in the backend)


class KeywordBackend(Protocol):
    """Extracts the salient keywords of a line (for emphasis highlighting).

    The real impl wraps KeyBERT (all-MiniLM-L6-v2). Tests inject a fake that
    returns a hand-built keyword list. Returned keywords are matched
    case-insensitively as whole words against the cue text.
    """

    def keywords(self, text: str) -> list[str]:
        """Return the salient keywords of ``text`` (most-salient first)."""
        ...  # pragma: no cover - Protocol stub (the body lives in the backend)


class ProfanityBackend(Protocol):
    """Classifies whether a single word is profane (for masking).

    The real impl wraps alt-profanity-check's linear SVM. Tests inject a fake
    returning ``True`` for the words it should mask.
    """

    def is_profane(self, word: str) -> bool:
        """Return True when ``word`` should be masked."""
        ...  # pragma: no cover - Protocol stub (the body lives in the backend)


#: ``settings -> PunctBackend`` — default lazily builds the real sherpa-onnx impl.
PunctFactory = Callable[[dict[str, Any]], PunctBackend]
#: ``settings -> KeywordBackend`` — default lazily builds the real KeyBERT impl.
KeywordFactory = Callable[[dict[str, Any]], KeywordBackend]
#: ``settings -> ProfanityBackend`` — default lazily builds the real masker impl.
ProfanityFactory = Callable[[dict[str, Any]], ProfanityBackend]


# --------------------------------------------------------------------------- #
# pure: the Netflix CPS / CPL / min-gap timing + segmentation gate
# --------------------------------------------------------------------------- #
def cps_of(cue: Cue) -> float:
    """Characters-per-second reading speed of ``cue`` (newlines excluded).

    Pure. The visible character count (line breaks do not count as characters a
    viewer reads) divided by the cue's on-screen duration. A non-positive
    duration returns ``inf`` (it is unreadable at any speed, so the gate will
    always try to lengthen it).
    """
    text = str(cue.get("text", "") or "").replace("\n", "")
    duration = float(cue.get("end", 0.0)) - float(cue.get("start", 0.0))
    if duration <= 0.0:
        return float("inf")
    return len(text) / duration


def wrap_two_lines(text: str, max_cpl: int = MAX_CPL) -> str:
    """Greedily wrap ``text`` into at most :data:`MAX_LINES` lines <= ``max_cpl``.

    Pure + deterministic. Words are packed left-to-right; a new line opens when
    the next word would exceed ``max_cpl``. Only the FIRST :data:`MAX_LINES`
    lines are kept as separate lines — any overflow words are appended to the
    last line (the caller is expected to have split the cue first via
    :func:`enforce_cps_cpl`, so this just lays out a cue that already fits). A
    single word longer than ``max_cpl`` is kept whole on its own line (never
    hyphen-split — mid-word breaks read worse than an over-long line).
    """
    words = text.split()
    if not words:
        return ""
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_cpl and len(lines) < MAX_LINES - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    # ``words`` is non-empty here (guarded above) and ``str.split`` never yields
    # empty tokens, so ``current`` always holds the trailing line.
    lines.append(current)
    return "\n".join(lines)


def _split_text_by_chars(text: str, limit: int) -> list[str]:
    """Split ``text`` into word-aligned chunks each <= ``limit`` chars.

    Pure. Greedily packs words; a single word longer than ``limit`` becomes its
    own chunk (never mid-word split). Used by :func:`enforce_cps_cpl` to break a
    too-long / too-fast cue into multiple cues — that caller always passes
    non-empty text, so the result is never empty.
    """
    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = word
        else:
            current = candidate
    # Only ever called with non-empty text (``enforce_cps_cpl`` guards), so the
    # loop always runs and ``current`` holds the trailing chunk.
    chunks.append(current)
    return chunks


def enforce_cps_cpl(
    cue: Cue,
    max_cps: int = MAX_CPS,
    max_cpl: int = MAX_CPL,
) -> list[Cue]:
    """Split + retime ``cue`` so its text fits CPL<=``max_cpl`` over <=2 lines.

    Pure + deterministic. A cue whose text cannot fit two ``max_cpl`` lines is
    broken into several cues, each carrying a proportional slice of the original
    time span (so the words stay in sync). Each resulting cue's text is wrapped to
    <= :data:`MAX_LINES` lines via :func:`wrap_two_lines`. A cue that already fits
    is returned (wrapped) as a single-element list. Empty-text cues are dropped
    (they would never display).

    Note on CPS: splitting a cue into pieces that *proportionally share the same
    time span* is reading-speed invariant — each piece keeps ``chars/duration``,
    so it can never lower CPS below the source cue's rate. CPS is therefore the
    *capacity floor* that drives the piece count (so each piece's text is at least
    short enough to read inside its slice when the source already met CPS), not a
    guarantee this function can manufacture: a genuinely too-fast cue (more chars
    than ``max_cps * duration``) cannot be made readable by splitting alone — that
    needs more on-screen time, which only an upstream retime/merge stage can give.
    ``max_cps`` is honoured for any cue whose source rate already fits, and is
    used as the per-piece char budget otherwise; the gate never silently claims a
    too-fast cue is readable. CPL<=``max_cpl`` IS always enforced.

    The piece count is the larger of the CPS char-budget requirement
    (chars / per-slice capacity) and the CPL requirement (chars / two-line
    capacity), so one pass satisfies CPL and shrinks each piece toward the CPS
    budget. Times are renumbered ``index`` 1..N over the returned cues.
    """
    text = str(cue.get("text", "") or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return []

    start = float(cue.get("start", 0.0))
    end = float(cue.get("end", 0.0))
    duration = max(end - start, 0.0)

    two_line_capacity = max_cpl * MAX_LINES
    # Pieces needed to satisfy CPL (each piece <= two full lines).
    cpl_pieces = (len(text) + two_line_capacity - 1) // two_line_capacity
    # Pieces sized by the CPS char-budget: a piece that reads inside its slice
    # holds at most ``max_cps`` chars per second of slice. With ``pieces`` equal
    # slices the per-piece budget is ``max_cps * duration / pieces``; requiring
    # ``chars / pieces <= max_cps * duration / pieces`` cancels ``pieces`` (proof
    # that equal-proportional splitting is CPS-invariant — see the docstring), so
    # this does NOT lower the rate. We instead size each piece to the *whole-cue*
    # CPS budget ``max_cps * duration`` chars: a cue already inside the rate yields
    # one piece, while a piece count >1 only ever shortens text per cue (helping
    # CPL / per-piece density), never claiming to fix a genuinely too-fast cue. A
    # zero-duration cue cannot be made readable by splitting, so it stays 1 piece
    # (its CPS is inf; only an upstream retime can lengthen it).
    cps_capacity = max(max_cps, 1)
    cps_pieces = max(1, math.ceil(len(text) / (cps_capacity * duration))) if duration > 0.0 else 1
    pieces = max(1, cpl_pieces, cps_pieces)

    if pieces == 1:
        return [
            {
                **cue,
                "index": 1,
                "start": start,
                "end": end,
                "text": wrap_two_lines(text, max_cpl),
            }
        ]

    # Split the text into ``pieces`` word-aligned chunks of roughly equal length.
    per_chunk_chars = max(1, (len(text) + pieces - 1) // pieces)
    chunks = _split_text_by_chars(text, per_chunk_chars)
    if not chunks:  # pragma: no cover - text is non-empty, so chunks is non-empty
        return []

    out: list[Cue] = []
    slice_dur = duration / len(chunks) if chunks else 0.0
    for i, chunk in enumerate(chunks):
        piece_start = start + slice_dur * i
        piece_end = start + slice_dur * (i + 1) if i < len(chunks) - 1 else end
        out.append(
            {
                **cue,
                "index": i + 1,
                "start": piece_start,
                "end": piece_end,
                "text": wrap_two_lines(chunk, max_cpl),
            }
        )
    return out


def enforce_min_gap(cues: list[Cue], *, fps: float = DEFAULT_FPS) -> list[Cue]:
    """Pull back each cue's ``end`` so consecutive cues keep :data:`MIN_GAP_FRAMES`.

    Pure + deterministic. When ``cues[i].end`` is closer than the min gap (in
    seconds, derived from ``fps``) to ``cues[i+1].start``, the earlier cue's
    ``end`` is shortened so the gap holds. A cue is never shortened past its own
    ``start`` (a zero/negative-length cue is left at its start, the timing gate
    upstream is responsible for its length). Returns NEW cue dicts; never mutates.
    """
    if not cues:
        return []
    gap = MIN_GAP_FRAMES / fps if fps > 0 else 0.0
    out: list[Cue] = [dict(c) for c in cues]
    for i in range(len(out) - 1):
        cur_end = float(out[i].get("end", 0.0))
        cur_start = float(out[i].get("start", 0.0))
        next_start = float(out[i + 1].get("start", 0.0))
        if next_start - cur_end < gap:
            new_end = max(cur_start, next_start - gap)
            out[i] = {**out[i], "end": new_end}
    return out


# --------------------------------------------------------------------------- #
# pure: emphasis + profanity application (model-fed, but applied with pure code)
# --------------------------------------------------------------------------- #
def apply_emphasis_spans(
    cue: Cue,
    keywords: Sequence[str],
) -> dict[str, Any]:
    """Return a NEW cue with ``emphasis`` spans + ``emoji`` (immutable).

    Combines the deterministic emphasis spans (``emphasis.find_emphasis_spans``)
    with extra ``keyword``-kind spans for the model-extracted ``keywords`` (each
    matched as a whole word, case-insensitive, in the cue text). The merged spans
    are validated + de-overlapped via ``emphasis.normalize_spans`` so the
    renderer never sees nested codes. The trailing emoji reuses
    ``emphasis.pick_emoji``. Pure given the keyword list.
    """
    text = str(cue.get("text", "") or "")
    spans = list(_emphasis.find_emphasis_spans(text))
    lowered = text.lower()
    for kw in keywords:
        kw_norm = str(kw or "").strip().lower()
        if not kw_norm:
            continue
        for match in re.finditer(rf"\b{re.escape(kw_norm)}\b", lowered):
            spans.append({"start": match.start(), "end": match.end(), "kind": "keyword"})
    out = dict(cue)
    out["emphasis"] = _emphasis.normalize_spans(spans, len(text))
    out["emoji"] = _emphasis.pick_emoji(text)
    return out


def mask_profanity(text: str, predictor: ProfanityBackend) -> str:
    """Mask every profane WORD in ``text`` with asterisks (keeps length + case-feel).

    Pure given the predictor. Each whitespace-delimited token's letters/digits
    are passed to ``predictor.is_profane``; a profane token's word characters are
    replaced by ``*`` (surrounding punctuation is preserved). Non-word tokens and
    clean words pass through unchanged.
    """

    def _mask(match: re.Match[str]) -> str:
        word = match.group(0)
        return "*" * len(word) if predictor.is_profane(word) else word

    return re.sub(r"[^\W_]+(?:['’][^\W_]+)*", _mask, text)


# --------------------------------------------------------------------------- #
# the orchestrator
# --------------------------------------------------------------------------- #
def polish_cues(
    cues: list[Cue],
    *,
    settings: dict[str, Any] | None = None,
    punct_backend: PunctBackend | None = None,
    keyword_backend: KeywordBackend | None = None,
    profanity_backend: ProfanityBackend | None = None,
    fps: float = DEFAULT_FPS,
) -> list[Cue]:
    """Polish ``cues`` end-to-end: punct/casing -> profanity -> timing -> emphasis.

    Stages (each model stage is SKIPPED when its backend is ``None`` — the §3
    degrade rule):

      1. **Punctuation + casing** (``punct_backend``) — restore sentence casing
         and punctuation on each cue's text.
      2. **Profanity masking** (``profanity_backend``) — replace profane words
         with asterisks.
      3. **Timing + segmentation gate** (PURE, always) — split/retime each cue to
         fit CPL<=:data:`MAX_CPL` over <=2 lines, sizing pieces against the CPS
         char budget (``MAX_CPS_CHILDREN`` when ``settings['captionChildren']``,
         else :data:`MAX_CPS`); see :func:`enforce_cps_cpl` for why proportional
         splitting cannot lower a too-fast cue's reading rate. Then pull ends back
         to keep the :data:`MIN_GAP_FRAMES` min gap.
      4. **Emphasis keywords** (``keyword_backend`` for the salient words, plus
         the deterministic ``emphasis`` heuristics which always run) — stamp
         ``emphasis`` spans + a trailing ``emoji`` on each final cue.

    Returns brand-new cue dicts in time order, renumbered ``index`` 1..N. Inputs
    are never mutated. ``settings`` selects the adult/children CPS limit; ``fps``
    drives the min-gap conversion.
    """
    settings = settings or {}
    if not cues:
        return []

    max_cps = MAX_CPS_CHILDREN if settings.get("captionChildren") else MAX_CPS

    # Stage 1+2 operate per source cue, BEFORE the timing split (so casing +
    # masking see whole sentences). Then the timing gate splits into final cues.
    split_cues: list[Cue] = []
    for cue in cues:
        text = str(cue.get("text", "") or "")
        if punct_backend is not None:
            text = punct_backend.restore(text)
        if profanity_backend is not None:
            text = mask_profanity(text, profanity_backend)
        retimed = enforce_cps_cpl({**cue, "text": text}, max_cps=max_cps, max_cpl=MAX_CPL)
        split_cues.extend(retimed)

    if not split_cues:
        return []

    gapped = enforce_min_gap(split_cues, fps=fps)

    out: list[Cue] = []
    for i, cue in enumerate(gapped):
        keywords = keyword_backend.keywords(str(cue.get("text", "") or "")) if keyword_backend is not None else []
        annotated = apply_emphasis_spans(cue, keywords)
        annotated["index"] = i + 1
        out.append(annotated)
    return out


# --------------------------------------------------------------------------- #
# availability + default heavy seams (lazy real impls; tests inject fakes)
# --------------------------------------------------------------------------- #
def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the sherpa-onnx punctuation asset is installed (no heavy import).

    Looks the asset up via the asset manager so an already-cached snapshot
    counts. Any lookup failure (asset not yet registered in Wave-1) degrades to
    ``False`` (the punct stage is skipped), never raises.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(PUNCT_ASSET_NAME)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - missing asset machinery -> skip the stage
        return False


def _default_punct_factory(settings: dict[str, Any]) -> PunctBackend:
    """Build the real sherpa-onnx punct+casing backend (LAZY import; runtime only)."""
    from .caption_polish_backend import SherpaPunctBackend  # noqa: PLC0415 - heavy seam

    return SherpaPunctBackend(settings)


def _default_keyword_factory(settings: dict[str, Any]) -> KeywordBackend:
    """Build the real KeyBERT keyword backend (LAZY import; runtime only)."""
    from .caption_polish_backend import KeyBertBackend  # noqa: PLC0415 - heavy seam

    return KeyBertBackend(settings)


def _default_profanity_factory(settings: dict[str, Any]) -> ProfanityBackend:
    """Build the real alt-profanity-check masker (LAZY import; runtime only)."""
    from .caption_polish_backend import AltProfanityBackend  # noqa: PLC0415 - heavy seam

    return AltProfanityBackend(settings)


# --------------------------------------------------------------------------- #
# asset registration (mirrors diarize / ctc_align / parakeet_asr)
# --------------------------------------------------------------------------- #
#: the tiny EN-only sherpa-onnx punctuation+casing model repo (manifest #15).
PUNCT_HF_REPO = "csukuangfj/sherpa-onnx-online-punct-en-2024-08-06"
PUNCT_SIZE_MB = 30


def register_caption_polish_assets() -> None:
    """Register the sherpa-onnx punctuation+casing model as an on-demand asset.

    Apache-2.0 engine, tiny EN-only punct+casing model (~30 MB). The asset name
    matches :data:`PUNCT_ASSET_NAME` so :func:`default_models_present` detects an
    already-cached snapshot. KeyBERT (all-MiniLM) + alt-profanity-check are tiny
    pip deps with no separate model asset (they download their own backbone on
    first use), so only the sherpa-onnx model is registered. Idempotent.
    """
    from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle

    manifest.register_asset(
        manifest.AssetEntry(
            name=PUNCT_ASSET_NAME,
            kind="model",
            size_mb=PUNCT_SIZE_MB,
            label="sherpa-onnx punctuation + casing (EN, Apache-2.0)",
            installer="hf",
            hf_repo=PUNCT_HF_REPO,
        )
    )


# Register the asset at import (mirrors diarize.register_diarize_assets()).
register_caption_polish_assets()


__all__ = [
    "DEFAULT_FPS",
    "MAX_CPL",
    "MAX_CPS",
    "MAX_CPS_CHILDREN",
    "MAX_LINES",
    "MIN_GAP_FRAMES",
    "PUNCT_ASSET_NAME",
    "PUNCT_HF_REPO",
    "PUNCT_SIZE_MB",
    "Cue",
    "KeywordBackend",
    "KeywordFactory",
    "ProfanityBackend",
    "ProfanityFactory",
    "PunctBackend",
    "PunctFactory",
    "apply_emphasis_spans",
    "cps_of",
    "default_models_present",
    "enforce_cps_cpl",
    "enforce_min_gap",
    "mask_profanity",
    "polish_cues",
    "register_caption_polish_assets",
    "wrap_two_lines",
]
