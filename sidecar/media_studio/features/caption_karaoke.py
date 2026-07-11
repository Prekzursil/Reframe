r"""OpusClip-style KARAOKE caption preset — the libass/ASS half (V1.1 WU SP1).

The V1 caption styles are whole-template picks rendered either by libass
(:mod:`.caption`) or Remotion (:mod:`.caption_remotion`). This module adds the
teardown-verified **OpusClip karaoke** look as a first-class *libass preset*:
word-by-word reveal with an ALTERNATING yellow/green active word + a scale-pop,
all-caps condensed, white fill + a thick dark outline, 1-4 words per line, and a
safe-area-aware lower-mid position for 9:16. (Verified against OpusClip's 41
``razvan_gandu`` shorts — see the basic-memory teardown note.)

Why a dedicated ASS builder rather than a :class:`caption_override.CaptionOverride`
patch: the alternating per-word colour and the ``\t`` ``\fscx`` scale-pop are
karaoke effects the flat override fields cannot express. The standard
:func:`caption.build_ass` stays byte-identical to V1; this preset is a SEPARATE,
additive ASS document the libass :class:`caption.CaptionEngine` emits when the
``opusclip-karaoke`` style is selected.

Render model (word-by-word, libass-native + deterministic so the burn is
testable): each spoken word becomes ONE ``Dialogue`` event over that word's
[start, end]. The event shows its whole 1-4 word line with the active word wrapped
in an inline ``{\1c<colour>\t(0,<ms>,\fscx<pop>\fscy<pop>)}WORD{\r}`` block (the
alternating accent + the scale-pop, reset back to the white-fill Style default for
the rest of the line). The active colour alternates yellow -> green by absolute
word order.

Everything here is PURE (no ffmpeg, no I/O) and fully unit-tested. Caption text is
escaped against ASS override injection (it is user/transcript-derived) exactly
like :func:`caption.build_ass`.

Load-bearing colour detail (the silent-wrong-colour trap, mirrored from
:mod:`.caption_override`): ASS colours are ``&HAABBGGRR`` (BGR + *inverted*
alpha). The palette below is declared as ``#RRGGBB`` and the resolved ``&H`` forms
are pinned as constants whose drift from :func:`caption_override.hex_to_ass_color`
is asserted by the unit tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .caption import CueLike, escape_ass_text, format_ass_timestamp, rebase_cue_time

# --------------------------------------------------------------------------- #
# preset identity
# --------------------------------------------------------------------------- #
#: The caption-style id that selects this preset (libass engine, karaoke ASS).
#: NOT a member of ``caption_remotion.STYLES`` — it routes to libass, so it never
#: widens the frozen three-way Remotion-template mirror.
OPUSCLIP_KARAOKE_STYLE = "opusclip-karaoke"

# --------------------------------------------------------------------------- #
# palette (#RRGGBB declared; &H resolved forms pinned + drift-tested)
# --------------------------------------------------------------------------- #
KARAOKE_FILL_HEX = "#FFFFFF"  # white text fill
KARAOKE_OUTLINE_HEX = "#000000"  # thick dark outline
#: alternating active-word accent: yellow, then green (teardown-verified order).
KARAOKE_ACTIVE_HEX: tuple[str, str] = ("#FFFF00", "#00FF00")

#: Style-line colour form (``&HAABBGGRR`` WITHOUT the trailing ``&``, matching
#: :data:`caption_override.BASE_PRIMARY`). == ``hex_to_ass_color(...)[:-1]``.
KARAOKE_FILL = "&H00FFFFFF"
KARAOKE_OUTLINE = "&H00000000"
#: semi-opaque shadow/box backdrop (mirrors ``caption_override.BASE_BACK``).
KARAOKE_BACK = "&H64000000"
#: inline ``\1c`` active-word colours WITH the trailing ``&`` (yellow, green).
#: == ``tuple(hex_to_ass_color(h) for h in KARAOKE_ACTIVE_HEX)`` (drift-tested).
KARAOKE_ACTIVE_INLINE: tuple[str, str] = ("&H0000FFFF&", "&H0000FF00&")

# --------------------------------------------------------------------------- #
# typography / animation
# --------------------------------------------------------------------------- #
#: condensed all-caps display font (in ``caption_override.CURATED_CAPTION_FONTS``,
#: i.e. the burn-in fontconfig allowlist) so a karaoke burn never falls back.
KARAOKE_FONT = "Anton"
KARAOKE_BOLD = -1  # ASS true
KARAOKE_BORDER_STYLE = 1  # outline + shadow (NOT an opaque box)
KARAOKE_OUTLINE_WIDTH = 4  # thick dark outline
KARAOKE_SHADOW = 2
#: active-word scale-pop: ``\t(0,KARAOKE_POP_MS,\fscxKARAOKE_POP_SCALE\fscy...)``.
KARAOKE_POP_SCALE = 115
KARAOKE_POP_MS = 120
#: 1-4 words per caption line (teardown).
MAX_WORDS_PER_LINE = 4

# --------------------------------------------------------------------------- #
# safe area (9:16) — keep the line clear of the platform UI
# --------------------------------------------------------------------------- #
#: ASS numpad ``Alignment`` per safe-area band (all horizontally centred).
KARAOKE_BAND_ALIGNMENT = {"top": 8, "center": 5, "bottom": 2}
#: vertical clearances as fractions of the canvas height.
SAFE_AREA_TOP_FRACTION = 0.10  # clear the top ~10% (status bar / source chyron)
SAFE_AREA_BOTTOM_FRACTION = 0.18  # clear the bottom ~18% (caption/UI band) -> lower-mid
#: horizontal L/R margin as a fraction of canvas width.
SIDE_MARGIN_FRACTION = 0.06


def is_karaoke_style(style: Any) -> bool:
    """True iff ``style`` selects the OpusClip karaoke preset (case/space-insensitive)."""
    return isinstance(style, str) and style.strip().lower() == OPUSCLIP_KARAOKE_STYLE


def active_color_for_index(index: int) -> str:
    """Inline ``\\1c`` colour for the word at absolute ``index`` (yellow/green alt)."""
    return KARAOKE_ACTIVE_INLINE[index % 2]


def safe_area_margin_v(height: int, band: str) -> int:
    """Vertical margin (px) that keeps the line inside the 9:16 safe area.

    ``top`` -> clear the top ~10%; ``center`` -> libass-centred so the margin is
    ignored (0); anything else (``bottom``, the default) -> clear the bottom ~18%
    so the karaoke line sits in the lower-mid, off the platform UI band.
    """
    if band == "top":
        return int(round(height * SAFE_AREA_TOP_FRACTION))
    if band == "center":
        return 0
    return int(round(height * SAFE_AREA_BOTTOM_FRACTION))


def _resolve_band(band: str | None) -> str:
    """Coerce a requested position band to a known one (default ``bottom``)."""
    candidate = (band or "").strip().lower()
    return candidate if candidate in KARAOKE_BAND_ALIGNMENT else "bottom"


def words_from_cue(cue: CueLike) -> list[dict[str, Any]]:
    """Per-word timed tokens ``[{text,start,end}]`` for a caption cue.

    Prefers the cue's aligned ``words`` (karaoke-grade timing from
    :mod:`.ctc_align`); blank word tokens are dropped. When a cue carries NO word
    timing, its ``text`` is whitespace-split and the cue window ``[start, end]`` is
    distributed EVENLY across the tokens — a documented degrade (the preset still
    reveals word-by-word without forced alignment), not a silent failure. A
    blank/empty cue yields ``[]``.
    """
    words = cue.get("words")
    if words:
        out: list[dict[str, Any]] = []
        for word in words:
            text = str(word.get("text") or "").strip()
            if not text:
                continue
            out.append(
                {
                    "text": text,
                    "start": float(word.get("start", 0.0)),
                    "end": float(word.get("end", 0.0)),
                }
            )
        return out

    tokens = str(cue.get("text") or "").split()
    if not tokens:
        return []
    start = float(cue.get("start", 0.0))
    end = float(cue.get("end", 0.0))
    step = max(0.0, end - start) / len(tokens)
    return [
        {"text": token, "start": start + index * step, "end": start + (index + 1) * step}
        for index, token in enumerate(tokens)
    ]


def group_into_lines(
    words: Sequence[dict[str, Any]],
    max_per_line: int = MAX_WORDS_PER_LINE,
) -> list[list[dict[str, Any]]]:
    """Chunk ``words`` into consecutive lines of 1..``max_per_line`` words (1-4)."""
    return [list(words[i : i + max_per_line]) for i in range(0, len(words), max_per_line)]


def _active_word_block(word_text: str, color: str) -> str:
    r"""Inline ASS for the active word: alternating colour + scale-pop, then ``\r``.

    Emits ``{\1c<color>\t(0,<ms>,\fscx<pop>\fscy<pop>)}WORD{\r}`` — the active
    accent and a grow-pop animated over the first ``KARAOKE_POP_MS`` of the word's
    own event, reset (``\r``) so the rest of the line keeps the white-fill Style
    default.
    """
    return (
        f"{{\\1c{color}\\t(0,{KARAOKE_POP_MS},\\fscx{KARAOKE_POP_SCALE}\\fscy{KARAOKE_POP_SCALE})}}{word_text}{{\\r}}"
    )


def build_line_text(
    line_words: Sequence[dict[str, Any]],
    active_index: int,
    active_color: str,
    uppercase: bool = True,
) -> str:
    """ASS ``Dialogue`` text for a line with word ``active_index`` highlighted.

    The active word gets :func:`_active_word_block` (alternating colour + pop); the
    others render as the plain white Style default. Every word is escaped (and
    upper-cased when requested, the OpusClip all-caps look) BEFORE assembly so the
    inserted override tags can never be corrupted and caption text can never inject
    ASS.
    """
    parts: list[str] = []
    for index, word in enumerate(line_words):
        raw = str(word.get("text") or "")
        text = escape_ass_text(raw.upper() if uppercase else raw)
        parts.append(_active_word_block(text, active_color) if index == active_index else text)
    return " ".join(parts)


def build_karaoke_style_line(
    font_size: int,
    alignment: int,
    margin_l: int,
    margin_r: int,
    margin_v: int,
) -> str:
    """The OpusClip karaoke ``Style: Default`` line (all-caps condensed base look).

    White fill, a thick dark outline + shadow (``BorderStyle=1``), bold condensed
    font. The active-word colour + scale-pop are applied inline per word; this
    Style is the white-fill/outline base every word resets (``\\r``) back to.
    """
    return (
        f"Style: Default,{KARAOKE_FONT},{font_size},"
        f"{KARAOKE_FILL},{KARAOKE_FILL},{KARAOKE_OUTLINE},{KARAOKE_BACK},"
        f"{KARAOKE_BOLD},0,0,0,"
        f"100,100,0,0,{KARAOKE_BORDER_STYLE},{KARAOKE_OUTLINE_WIDTH},{KARAOKE_SHADOW},"
        f"{alignment},{margin_l},{margin_r},{margin_v},1"
    )


def build_karaoke_ass(
    cues: Sequence[CueLike],
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    position_band: str = "bottom",
    uppercase: bool = True,
) -> str:
    r"""Build a complete OpusClip-style karaoke ASS document for ``cues``.

    - ``[Script Info]`` carries ``PlayResX``/``PlayResY`` = ``width``/``height`` so
      libass lays out for the exact export canvas (default the 1080x1920 short).
    - One ``Style: Default`` line fixes the all-caps condensed / white-fill /
      thick-dark-outline base, anchored to the safe-area band (default lower-mid).
    - Each cue is split into per-word timed tokens (:func:`words_from_cue`),
      chunked into 1-4 word lines, and each word emits ONE ``Dialogue`` event over
      its [start, end] (re-based by ``source_start``) showing the line with that
      word highlighted (alternating yellow/green + scale-pop). Words whose window
      lies entirely before the clip (end <= start after re-base) are skipped, but
      still advance the alternation so the accent order is stable.
    """
    play_x = int(width)
    play_y = int(height)
    band = _resolve_band(position_band)
    alignment = KARAOKE_BAND_ALIGNMENT[band]
    margin_v = safe_area_margin_v(play_y, band)
    margin_h = max(0, int(round(play_x * SIDE_MARGIN_FRACTION)))
    font_size = max(12, int(round(play_y * 0.05)))

    header = [
        "[Script Info]",
        "; Generated by media-studio CaptionEngine (libass/ffmpeg) — OpusClip karaoke preset.",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {play_x}",
        f"PlayResY: {play_y}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        build_karaoke_style_line(font_size, alignment, margin_h, margin_h, margin_v),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    global_index = 0
    # Bug-sweep: the shortmaker pipeline feeds ONE-WORD cues (features._cues_for_clip
    # emits a cue per transcript word), so grouping per-cue collapsed every karaoke
    # line to a single word. Flatten words across ALL cues first, then group globally
    # so the 1-4-words-per-line look renders from per-word cues. A cue that carries an
    # aligned ``words`` array still contributes its words in order.
    all_words = [word for cue in cues for word in words_from_cue(cue)]
    for line in group_into_lines(all_words):
        for active_index, word in enumerate(line):
            color = active_color_for_index(global_index)
            global_index += 1
            start = rebase_cue_time(word.get("start", 0.0), source_start)
            end = rebase_cue_time(word.get("end", 0.0), source_start)
            if end <= start:
                continue  # entirely before the clip (or zero-length after re-base)
            text = build_line_text(line, active_index, color, uppercase=uppercase)
            events.append(
                f"Dialogue: 0,{format_ass_timestamp(start)},{format_ass_timestamp(end)},Default,,0,0,0,,{text}"
            )

    # LF line endings for cross-platform determinism (tests assert exact content).
    return "\n".join(header + events) + "\n"


__all__ = [
    "KARAOKE_ACTIVE_HEX",
    "KARAOKE_ACTIVE_INLINE",
    "KARAOKE_BACK",
    "KARAOKE_BAND_ALIGNMENT",
    "KARAOKE_BOLD",
    "KARAOKE_BORDER_STYLE",
    "KARAOKE_FILL",
    "KARAOKE_FILL_HEX",
    "KARAOKE_FONT",
    "KARAOKE_OUTLINE",
    "KARAOKE_OUTLINE_HEX",
    "KARAOKE_OUTLINE_WIDTH",
    "KARAOKE_POP_MS",
    "KARAOKE_POP_SCALE",
    "KARAOKE_SHADOW",
    "MAX_WORDS_PER_LINE",
    "OPUSCLIP_KARAOKE_STYLE",
    "SAFE_AREA_BOTTOM_FRACTION",
    "SAFE_AREA_TOP_FRACTION",
    "SIDE_MARGIN_FRACTION",
    "active_color_for_index",
    "build_karaoke_ass",
    "build_karaoke_style_line",
    "build_line_text",
    "group_into_lines",
    "is_karaoke_style",
    "safe_area_margin_v",
    "words_from_cue",
]
