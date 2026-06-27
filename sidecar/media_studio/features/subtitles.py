"""Subtitles: build / edit / translate a SubtitleTrack and read+write SRT/ASS/VTT.

Pure logic — no heavy-ML imports. The translation seam takes an injected
*Provider* (the ``models.provider.Provider`` interface; only its ``chat`` method
is used here), so tests mock a fake provider instead of loading a real LLM.

Schemas are frozen by CONTRACTS.md §3 (field names identical on both sides):
  Word        = {text, start, end}
  Segment     = {start, end, text, words}
  Transcript  = {language, segments, durationSec}
  Cue         = {index, start, end, text}
  SubtitleTrack = {id, lang, name, format, kind:"soft"|"hard", cues}

Public surface (CONTRACTS.md §2 ``subtitles.*``):
  generate(transcript|videoId)  -> track
  edit(track, cues)             -> track
  translate(track, targetLang, provider) -> track   (the job body)
  export(track, format)         -> path             (format: srt|ass|vtt)
  read_srt / read_ass / read_vtt                    (round-trip parsing)

This module owns only ``features/subtitles.py`` (+ its test). It does not import
the (separately-owned) provider module: the provider is duck-typed via the
:class:`Provider` Protocol and injected by the caller / RPC handler.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

# --------------------------------------------------------------------------- #
# Types (dicts keyed exactly as CONTRACTS.md §3 — TypedDict-style aliases).
# --------------------------------------------------------------------------- #
Cue = dict[str, Any]
SubtitleTrack = dict[str, Any]
Transcript = dict[str, Any]
Segment = dict[str, Any]

#: The subtitle file formats this unit can read and write (CONTRACTS.md §2).
FORMATS: tuple[str, ...] = ("srt", "ass", "vtt")


class Provider(Protocol):
    """Minimal slice of ``models.provider.Provider`` used for translation.

    The real provider exposes ``complete``/``chat`` (CONTRACTS.md §1). Only
    ``chat`` is needed here. Declared as a Protocol so the seam is duck-typed:
    tests pass a fake object with a matching ``chat`` and never import the LLM.
    """

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:  # pragma: no cover - interface
        ...


# A line-translator seam: maps one source line -> its translation. Used by
# translate(); the default implementation drives a Provider, but tests can also
# inject a plain function to exercise the cue-mapping logic in isolation.
LineTranslator = Callable[[str], str]


# --------------------------------------------------------------------------- #
# id / helpers
# --------------------------------------------------------------------------- #
def _new_id() -> str:
    """A short, collision-free track id."""
    return uuid.uuid4().hex[:12]


def _is_blank(text: str) -> bool:
    return not text or not text.strip()


def new_track(
    cues: Sequence[Cue] | None = None,
    *,
    lang: str = "und",
    name: str = "Subtitles",
    fmt: str = "srt",
    kind: str = "soft",
    track_id: str | None = None,
) -> SubtitleTrack:
    """Build a SubtitleTrack dict with all §3 fields present.

    ``kind`` is constrained to ``"soft"`` | ``"hard"`` (anything else is coerced
    to ``"soft"``). Cues are reindexed 1..N so the track is always well-formed.
    """
    norm_kind = kind if kind in ("soft", "hard") else "soft"
    return {
        "id": track_id or _new_id(),
        "lang": lang,
        "name": name,
        "format": fmt,
        "kind": norm_kind,
        "cues": reindex(list(cues or [])),
    }


def make_cue(index: int, start: float, end: float, text: str, *, speaker: str | None = None) -> Cue:
    """Construct a single Cue dict (CONTRACTS.md §3 field order/names).

    The frozen §3 fields ``index/start/end/text`` keep their order/names. The
    optional diarized ``speaker`` is ADDITIVE: the key is only set when a non-empty
    ``speaker`` is supplied, so a non-diarized cue stays byte-identical to today
    (no ``speaker: None`` leakage into the §3 shape).
    """
    cue: Cue = {"index": int(index), "start": float(start), "end": float(end), "text": text}
    if speaker:
        cue["speaker"] = str(speaker)
    return cue


def reindex(cues: Sequence[Cue]) -> list[Cue]:
    """Return cues renumbered 1..N (1-based), as fresh dicts (no mutation).

    An optional diarized ``speaker`` on the input cue is preserved (additive);
    absent ⇒ no ``speaker`` key on the output (no ``speaker: None`` leakage).
    """
    out: list[Cue] = []
    for i, cue in enumerate(cues, start=1):
        out.append(
            make_cue(
                i,
                float(cue.get("start", 0.0)),
                float(cue.get("end", 0.0)),
                str(cue.get("text", "")),
                speaker=cue.get("speaker"),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# generate: Transcript -> SubtitleTrack
# --------------------------------------------------------------------------- #
def cues_from_transcript(
    transcript: Transcript,
    *,
    max_chars: int = 84,
    max_duration: float = 7.0,
) -> list[Cue]:
    """Derive a list of Cues from a Transcript's segments.

    One cue per segment by default. Segments longer than ``max_chars`` *or*
    ``max_duration`` and carrying per-word timing are split on word boundaries
    so no caption is an unreadable wall of text. Blank segments are dropped.
    """
    cues: list[Cue] = []
    for seg in transcript.get("segments", []) or []:
        text = str(seg.get("text", "")).strip()
        if _is_blank(text):
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        speaker = seg.get("speaker")
        words = seg.get("words") or []
        if (len(text) > max_chars or (end - start) > max_duration) and words:
            cues.extend(_split_segment(words, max_chars, max_duration, speaker=speaker))
        else:
            cues.append(make_cue(0, start, end, text, speaker=speaker))
    return reindex(cues)


def _split_segment(
    words: Sequence[dict[str, Any]],
    max_chars: int,
    max_duration: float,
    *,
    speaker: str | None = None,
) -> list[Cue]:
    """Greedily pack word-timed tokens into cues bounded by chars + duration.

    Each emitted split-cue inherits the parent segment's ``speaker`` (additive;
    omitted when the segment has none).
    """
    cues: list[Cue] = []
    cur: list[dict[str, Any]] = []

    def flush() -> None:
        if not cur:
            return
        text = " ".join(str(w.get("text", "")).strip() for w in cur).strip()
        if text:
            cues.append(
                make_cue(
                    0,
                    float(cur[0].get("start", 0.0)),
                    float(cur[-1].get("end", 0.0)),
                    text,
                    speaker=speaker,
                )
            )

    for w in words:
        tentative = cur + [w]
        text = " ".join(str(x.get("text", "")).strip() for x in tentative).strip()
        span = float(tentative[-1].get("end", 0.0)) - float(tentative[0].get("start", 0.0))
        if cur and (len(text) > max_chars or span > max_duration):
            flush()
            cur = [w]
        else:
            cur = tentative
    flush()
    return cues


def format_speaker_prefix(cues: Sequence[Cue], *, on: bool) -> list[Cue]:
    """Return cues with each speaker-bearing cue's text prefixed ``"<speaker>: "``.

    Pure + immutable: returns fresh cue dicts (the inputs are never mutated). When
    ``on`` is falsy this is the identity on text (cues are still copied so callers
    get a consistent fresh-list contract). A cue with no ``speaker`` is left
    untouched even when ``on`` is true. The ``captionSpeakerLabels`` setting (read
    in WU-5) drives ``on``.
    """
    out: list[Cue] = []
    for cue in cues:
        new_cue = dict(cue)
        speaker = new_cue.get("speaker")
        if on and speaker:
            new_cue["text"] = f"{speaker}: {new_cue.get('text', '')}"
        out.append(new_cue)
    return out


def generate(
    transcript: Transcript,
    *,
    name: str = "Subtitles",
    fmt: str = "srt",
    track_id: str | None = None,
) -> SubtitleTrack:
    """Generate a soft SubtitleTrack from a Transcript (CONTRACTS.md §2).

    ``lang`` is taken from the transcript's ``language``. The track is ``soft``
    (cues, not burned-in); burning is the ``tracks``/``caption`` unit's job.
    """
    cues = cues_from_transcript(transcript)
    lang = str(transcript.get("language") or "und")
    return new_track(cues, lang=lang, name=name, fmt=fmt, kind="soft", track_id=track_id)


# A caption-polish seam matching ``caption_polish.polish_cues``'s shape:
# ``(cues, *, settings) -> cues``. Injected in tests; the default lazily delegates
# to the real (degrade-safe) module so this stays import-light + heavy-dep-free.
CaptionPolisher = Callable[..., list["Cue"]]


def _default_caption_polisher(cues: list[Cue], **kwargs: Any) -> list[Cue]:
    """Delegate to the real caption-polish pass (LAZY import; runtime only).

    ``caption_polish`` is import-light (its heavy backends are behind seams that
    default to ``None`` -> skipped), so the timing/segmentation gate always runs
    and the model stages degrade gracefully when their backends are absent.
    """
    from .caption_polish import polish_cues as _polish  # noqa: PLC0415

    return _polish(cues, **kwargs)


def generate_polished(
    transcript: Transcript,
    *,
    name: str = "Subtitles",
    fmt: str = "srt",
    track_id: str | None = None,
    settings: dict[str, Any] | None = None,
    polisher: CaptionPolisher | None = None,
) -> SubtitleTrack:
    """Generate a soft SubtitleTrack, then run the WU9 caption-polish pass on its cues.

    Additive sibling of :func:`generate` (which is left byte-unchanged). After the
    standard cue derivation it threads the cues through ``caption_polish.polish_cues``
    (the Netflix CPS/CPL/min-gap timing+segmentation gate, plus optional punct/casing,
    emphasis-keyword, and profanity-masking model stages — each skipped when its
    backend is absent). The polished cues are reindexed onto the track via
    :func:`new_track`. ``polisher`` is the injectable seam (default lazily delegates
    to the real, degrade-safe module). ``settings`` selects the adult/children CPS
    limit + the model backends.
    """
    polish = polisher if polisher is not None else _default_caption_polisher
    base = generate(transcript, name=name, fmt=fmt, track_id=track_id)
    polished = polish(list(base.get("cues") or []), settings=settings or {})
    return new_track(
        polished,
        lang=str(base.get("lang") or "und"),
        name=name,
        fmt=fmt,
        kind="soft",
        track_id=base.get("id"),
    )


# --------------------------------------------------------------------------- #
# edit: replace cues on a track (immutable — returns a new track)
# --------------------------------------------------------------------------- #
def edit(track: SubtitleTrack, cues: Sequence[Cue]) -> SubtitleTrack:
    """Return a copy of ``track`` with its cues replaced by ``cues`` (reindexed).

    Immutable: the input track dict is not mutated (CONTRACTS.md coding-style).
    """
    updated = dict(track)
    updated["cues"] = reindex(list(cues))
    return updated


# --------------------------------------------------------------------------- #
# translate: per-cue text translation via an injected Provider
# --------------------------------------------------------------------------- #
_TRANSLATE_SYS = (
    "You are a professional subtitle translator. Translate the user's text into "
    "{lang}. Reply with ONLY the translation — no quotes, no notes, no "
    "explanation. Preserve meaning and keep it concise enough to read as a "
    "subtitle."
)


def make_provider_translator(provider: Provider, target_lang: str) -> LineTranslator:
    """Build a one-line translator backed by ``provider.chat`` for ``target_lang``.

    Each call sends a 2-message chat (system + the source line) and returns the
    provider's stripped reply. Blank input short-circuits to blank output (no
    provider call), so empty cues stay empty.
    """
    system = _TRANSLATE_SYS.format(lang=target_lang)

    def _translate(text: str) -> str:
        if _is_blank(text):
            return text
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        reply = provider.chat(messages)
        return str(reply).strip()

    return _translate


def translate(
    track: SubtitleTrack,
    target_lang: str,
    *,
    provider: Provider | None = None,
    translator: LineTranslator | None = None,
    progress: Callable[[int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SubtitleTrack:
    """Translate every cue's text into ``target_lang``, returning a NEW track.

    Exactly one translation seam must be supplied: an injected ``translator``
    (a ``str -> str`` callable, used directly) OR a ``provider`` (wrapped via
    :func:`make_provider_translator`). The new track keeps the same cue
    timings/indices and updates ``lang`` to ``target_lang``. Cues are translated
    one-by-one so a cooperative ``cancelled()`` check + ``progress(pct, msg)``
    callback (the job seam, CONTRACTS.md §2) can be threaded through.
    """
    if translator is None:
        if provider is None:
            raise ValueError("translate() requires either a provider or a translator")
        translator = make_provider_translator(provider, target_lang)

    cues = track.get("cues") or []
    total = len(cues)
    out_cues: list[Cue] = []
    for i, cue in enumerate(cues):
        if cancelled is not None and cancelled():
            break
        new_text = translator(str(cue.get("text", "")))
        out_cues.append(
            make_cue(int(cue.get("index", i + 1)), float(cue.get("start", 0.0)), float(cue.get("end", 0.0)), new_text)
        )
        if progress is not None and total:
            progress(int(round((i + 1) / total * 100)), f"translated {i + 1}/{total}")

    updated = dict(track)
    updated["lang"] = target_lang
    updated["cues"] = out_cues
    return updated


# --------------------------------------------------------------------------- #
# bilingual stacked subtitles (original + translation in one cue)
# --------------------------------------------------------------------------- #
#: Default order of the two languages within a stacked bilingual cue.
BILINGUAL_ORDERS: tuple[str, ...] = ("original-first", "translation-first")


def stack_cue_text(original: str, translation: str, *, order: str = "original-first") -> str:
    """Join two language lines into one stacked cue body (newline-separated).

    The original and the translation share one cue (same timing); they are
    stacked on two lines so a player renders both at once. ``order`` controls
    which language is on top. A blank line is dropped so a missing translation
    never leaves a dangling empty row.
    """
    top, bottom = (original, translation) if order != "translation-first" else (translation, original)
    parts = [str(p).strip() for p in (top, bottom) if str(p).strip()]
    return "\n".join(parts)


def stack_bilingual(
    original: SubtitleTrack,
    translation: SubtitleTrack,
    *,
    order: str = "original-first",
    name: str | None = None,
    track_id: str | None = None,
) -> SubtitleTrack:
    """Combine an ``original`` track and its ``translation`` into ONE stacked track.

    The two tracks are expected to share cue timings (the translation is produced
    by :func:`translate`, which preserves timing/indices). Each output cue keeps
    the original's timing and carries both lines stacked via :func:`stack_cue_text`.
    Translation cues are matched by ``index`` first, falling back to positional
    order, so a slight count mismatch degrades gracefully instead of raising.

    The result ``lang`` is ``"<orig>+<trans>"`` to mark it bilingual, and its
    ``name`` defaults to ``"Bilingual (<orig>/<trans>)"``. Immutable: neither
    input track is mutated.
    """
    orig_cues = list(original.get("cues") or [])
    trans_cues = list(translation.get("cues") or [])
    by_index: dict[int, Cue] = {}
    for c in trans_cues:
        try:
            by_index[int(c.get("index"))] = c
        except (TypeError, ValueError):
            continue

    out_cues: list[Cue] = []
    for pos, cue in enumerate(orig_cues):
        idx = int(cue.get("index", pos + 1))
        match = by_index.get(idx)
        if match is None and pos < len(trans_cues):
            match = trans_cues[pos]
        translated_text = str(match.get("text", "")) if match else ""
        out_cues.append(
            make_cue(
                idx,
                float(cue.get("start", 0.0)),
                float(cue.get("end", 0.0)),
                stack_cue_text(str(cue.get("text", "")), translated_text, order=order),
            )
        )

    orig_lang = str(original.get("lang") or "und")
    trans_lang = str(translation.get("lang") or "und")
    return new_track(
        out_cues,
        lang=f"{orig_lang}+{trans_lang}",
        name=name or f"Bilingual ({orig_lang}/{trans_lang})",
        fmt=str(original.get("format") or "srt"),
        kind="soft",
        track_id=track_id,
    )


# --------------------------------------------------------------------------- #
# timestamp helpers
# --------------------------------------------------------------------------- #
def _split_seconds(seconds: float) -> tuple[int, int, int, int]:
    """Decompose seconds into (h, m, s, ms), clamping negatives to zero."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return h, m, s, ms


def format_timestamp_srt(seconds: float) -> str:
    """``HH:MM:SS,mmm`` — the SRT timestamp form (comma decimal separator)."""
    h, m, s, ms = _split_seconds(seconds)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """``HH:MM:SS.mmm`` — the WebVTT timestamp form (dot decimal separator)."""
    h, m, s, ms = _split_seconds(seconds)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_timestamp_ass(seconds: float) -> str:
    """``H:MM:SS.cc`` — the ASS timestamp form (centiseconds, 1-digit hours)."""
    h, m, s, ms = _split_seconds(seconds)
    cs = ms // 10
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


_TS_RE = re.compile(r"(?P<h>\d+):(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:[.,](?P<frac>\d{1,3}))?")


def parse_timestamp(text: str) -> float:
    """Parse an SRT/VTT/ASS timestamp into float seconds.

    Accepts comma or dot fractional separators and 2- or 3-digit fractions
    (ASS centiseconds vs SRT/VTT milliseconds). Raises ``ValueError`` on garbage.
    """
    m = _TS_RE.search(text.strip())
    if not m:
        raise ValueError(f"unparseable timestamp: {text!r}")
    h = int(m.group("h"))
    mn = int(m.group("m"))
    s = int(m.group("s"))
    frac_raw = m.group("frac") or ""
    if not frac_raw:
        frac = 0.0
    elif len(frac_raw) == 2:  # centiseconds (ASS)
        frac = int(frac_raw) / 100.0
    else:  # milliseconds (pad to 3 digits)
        frac = int(frac_raw.ljust(3, "0")) / 1000.0
    return h * 3600 + mn * 60 + s + frac


# --------------------------------------------------------------------------- #
# SRT
# --------------------------------------------------------------------------- #
def to_srt(cues: Sequence[Cue]) -> str:
    """Serialize cues to SRT text (blank line between blocks, trailing newline)."""
    blocks: list[str] = []
    for i, cue in enumerate(reindex(cues), start=1):
        start = format_timestamp_srt(cue["start"])
        end = format_timestamp_srt(cue["end"])
        text = str(cue["text"]).strip("\n")
        blocks.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def read_srt(text: str) -> list[Cue]:
    """Parse SRT text into cues (tolerant of CRLF, BOM, and missing indices)."""
    body = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        # Optional numeric index line.
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, _, end_raw = lines[0].partition("-->")
        start = parse_timestamp(start_raw)
        end = parse_timestamp(end_raw)
        body_text = "\n".join(lines[1:]).strip("\n")
        cues.append(make_cue(0, start, end, body_text))
    return reindex(cues)


# --------------------------------------------------------------------------- #
# WebVTT
# --------------------------------------------------------------------------- #
def to_vtt(cues: Sequence[Cue]) -> str:
    """Serialize cues to WebVTT text (``WEBVTT`` header + dot-separator times).

    A blank line always separates the ``WEBVTT`` header from the cue body, as the
    WebVTT spec requires (browsers / ffmpeg reject a header with no trailing
    blank line).
    """
    parts: list[str] = []
    for cue in reindex(cues):
        start = format_timestamp_vtt(cue["start"])
        end = format_timestamp_vtt(cue["end"])
        text = str(cue["text"]).strip("\n")
        parts.append(f"{start} --> {end}\n{text}")
    return "WEBVTT\n\n" + "\n\n".join(parts) + ("\n" if parts else "")


def read_vtt(text: str) -> list[Cue]:
    """Parse WebVTT text into cues (skips ``WEBVTT`` header, NOTE, and cue ids)."""
    body = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    body = re.sub(r"^WEBVTT[^\n]*\n?", "", body, count=1)
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip("\n")
        if not block.strip() or block.startswith("NOTE"):
            continue
        lines = block.split("\n")
        # A cue may carry an id line before the timing line.
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        timing = lines[0].split("-->")
        start = parse_timestamp(timing[0])
        # Strip any cue settings (e.g. "align:start") after the end timestamp.
        end = parse_timestamp(timing[1].strip().split(" ")[0])
        body_text = "\n".join(lines[1:]).strip("\n")
        cues.append(make_cue(0, start, end, body_text))
    return reindex(cues)


# --------------------------------------------------------------------------- #
# ASS / SSA
# --------------------------------------------------------------------------- #
_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,20,20,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def escape_ass_text(text: str) -> str:
    r"""Escape cue text for an ASS ``Dialogue`` field.

    Per CONTRACTS.md §4: NO raw ``{`` / ``}`` override-block injection. Braces
    are neutralized, newlines become the ASS ``\N`` line break, and commas are
    preserved (the Text field is the last field, so embedded commas are safe).
    """
    out = str(text)
    out = out.replace("\\", "\\\\")  # literal backslash first
    # Neutralize braces to a brace-FREE, reversible escape: '{' -> '\(' and
    # '}' -> '\)'. The output contains NO raw '{'/'}' so no ASS override block can
    # be injected (CONTRACTS.md §4), and _unescape_ass_text reverses it losslessly.
    # ('\' is escaped first, so a literal '(' / ')' is never confused with an
    # escaped brace, and a literal '\(' encodes as '\\(' — collision-free.)
    out = out.replace("{", "\\(").replace("}", "\\)")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\N")
    return out


#: Reverse map for :func:`_unescape_ass_text` — each ``\<key>`` decodes to its
#: value (inverse of :func:`escape_ass_text`): ``\N``/``\n`` -> newline,
#: ``\(`` -> ``{``, ``\)`` -> ``}``, ``\\`` -> ``\``.
_ASS_UNESCAPE: dict[str, str] = {"N": "\n", "n": "\n", "(": "{", ")": "}", "\\": "\\"}


def _unescape_ass_text(text: str) -> str:
    r"""Inverse of :func:`escape_ass_text`, round-tripping ``\N``/``\{``/``\}``/``\\``.

    A single left-to-right pass consuming each ``\<x>`` escape as a unit, so a
    literal backslash (escaped as ``\\``) can never collide with a following
    ``{``/``}``/``N`` (e.g. ``\\{`` decodes to a literal backslash + ``{``).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            decoded = _ASS_UNESCAPE.get(text[i + 1])
            if decoded is not None:
                out.append(decoded)
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def to_ass(cues: Sequence[Cue], *, width: int = 1080, height: int = 1920, fontsize: int = 54) -> str:
    """Serialize cues to a complete ASS document sized ``width`` x ``height``.

    Cue text is escaped (:func:`escape_ass_text`) so no override block can be
    injected (CONTRACTS.md §4). Default canvas is the 9:16 short format.
    """
    lines = [_ASS_HEADER.format(width=width, height=height, fontsize=fontsize)]
    for cue in reindex(cues):
        start = format_timestamp_ass(cue["start"])
        end = format_timestamp_ass(cue["end"])
        text = escape_ass_text(cue["text"])
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def read_ass(text: str) -> list[Cue]:
    """Parse the ``[Events]`` ``Dialogue:`` lines of an ASS document into cues.

    Honors the ``Format:`` declaration to locate Start/End/Text columns; the
    Text column is the remainder of the line (it may contain commas).
    """
    body = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    fmt_cols: list[str] = []
    in_events = False
    for raw in body.split("\n"):
        line = raw.strip()
        if line.startswith("["):
            in_events = line.lower().startswith("[events]")
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fmt_cols = [c.strip().lower() for c in line.split(":", 1)[1].split(",")]
            continue
        if line.lower().startswith("dialogue:"):
            cue = _parse_dialogue(line, fmt_cols)
            if cue is not None:
                cues.append(cue)
    return reindex(cues)


def _parse_dialogue(line: str, fmt_cols: list[str]) -> Cue | None:
    """Parse a single ``Dialogue:`` line using the ``Format:`` column order."""
    cols = fmt_cols or [
        "layer",
        "start",
        "end",
        "style",
        "name",
        "marginl",
        "marginr",
        "marginv",
        "effect",
        "text",
    ]
    payload = line.split(":", 1)[1]
    text_idx = cols.index("text") if "text" in cols else len(cols) - 1
    # Split into (text_idx) fields; the final field (Text) keeps its commas.
    fields = payload.split(",", text_idx)
    if len(fields) <= max(cols.index("start"), cols.index("end")):
        return None
    try:
        start = parse_timestamp(fields[cols.index("start")])
        end = parse_timestamp(fields[cols.index("end")])
    except ValueError:
        return None
    text = _unescape_ass_text(fields[text_idx].strip()) if text_idx < len(fields) else ""
    return make_cue(0, start, end, text)


# --------------------------------------------------------------------------- #
# format dispatch + file I/O
# --------------------------------------------------------------------------- #
_SERIALIZERS: dict[str, Callable[[Sequence[Cue]], str]] = {
    "srt": to_srt,
    "vtt": to_vtt,
    "ass": to_ass,
}
_PARSERS: dict[str, Callable[[str], list[Cue]]] = {
    "srt": read_srt,
    "vtt": read_vtt,
    "ass": read_ass,
}


def _normalize_format(fmt: str) -> str:
    f = str(fmt).strip().lower().lstrip(".")
    if f == "ssa":
        f = "ass"
    if f not in FORMATS:
        raise ValueError(f"unsupported subtitle format: {fmt!r} (want one of {FORMATS})")
    return f


def serialize(track: SubtitleTrack, fmt: str) -> str:
    """Serialize a track's cues to subtitle text in ``fmt`` (srt|ass|vtt)."""
    f = _normalize_format(fmt)
    return _SERIALIZERS[f](track.get("cues") or [])


def parse(text: str, fmt: str) -> list[Cue]:
    """Parse subtitle ``text`` of format ``fmt`` (srt|ass|vtt) into cues."""
    f = _normalize_format(fmt)
    return _PARSERS[f](text)


def export(track: SubtitleTrack, fmt: str, out_path: str | Path) -> str:
    """Write ``track`` to ``out_path`` as ``fmt`` and return the path (§2).

    The handler maps ``subtitles.export({trackId, format}) -> {path}`` onto this.
    """
    f = _normalize_format(fmt)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(track, f), encoding="utf-8")
    return str(path)


def load(in_path: str | Path, fmt: str | None = None) -> list[Cue]:
    """Read a subtitle file into cues; ``fmt`` defaults to the file extension."""
    path = Path(in_path)
    effective = fmt if fmt is not None else path.suffix.lstrip(".")
    return parse(path.read_text(encoding="utf-8"), effective)


def track_from_file(
    in_path: str | Path,
    *,
    lang: str = "und",
    name: str | None = None,
    kind: str = "soft",
    track_id: str | None = None,
) -> SubtitleTrack:
    """Read a subtitle file and wrap its cues in a full SubtitleTrack dict."""
    path = Path(in_path)
    fmt = _normalize_format(path.suffix.lstrip("."))
    cues = load(path, fmt)
    return new_track(
        cues,
        lang=lang,
        name=name or path.stem,
        fmt=fmt,
        kind=kind,
        track_id=track_id,
    )


def track_to_json(track: SubtitleTrack) -> str:
    """JSON-encode a track (stable key order) — convenience for persistence."""
    return json.dumps(track, ensure_ascii=False, indent=2)
