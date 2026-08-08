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

STYLING CONTRACT (v1.5 lane-karaoke). The preset used to be style-LOCKED: its
``build_karaoke_ass`` took only cues + canvas + ``source_start``, so a
:class:`caption_override.CaptionOverride` tuned in the gallery was silently
discarded while the renderer's live preview
(``captionOverridePreview.previewVisual`` folded onto
``captionTemplates.KARAOKE_PRESET_VISUAL``) painted the tuned look — the preview
and the burn disagreed. Every user-settable control now reaches the burn:

===================== =========================================================
control               how the karaoke preset honours it
===================== =========================================================
``fontFamily``        Style ``Fontname`` (curated allowlist; else ``Anton``)
``sizeScale``         multiplies the canvas-derived base size (>= 12 floor)
``textColor``         Style ``PrimaryColour`` (the white fill words reset to)
``spokenColor``       fill FALLBACK when ``textColor`` is absent
``activeColor``       the inline ``\1c`` accent — COLLAPSES the alternation
``box`` / ``outline`` Style ``BorderStyle`` / ``Outline`` width
``uppercase``         per-word casing (tri-state; preset default all-caps)
``positionBand``      safe-area band -> ``Alignment`` + ``MarginV``
``captionPosition``   the normalised ``{x,y,w,h}`` box (shared helpers)
``hook_title``        the P3-A headline / WU-SP2 card overlay (shared emitter)
===================== =========================================================

EXPLICITLY DECLINED, with the mechanical reason (NOT a silent drop):

* **``emphasis`` spans -> bold.** The karaoke Style sets ``Bold=-1``
  (:data:`KARAOKE_BOLD`) — the whole line is already bold — so the ``{\b1}``
  wrap :func:`caption.render_cue_text` uses cannot render any contrast here. It
  would emit tags with zero visual effect. Not applied; see
  :func:`build_line_text`.
* **``maxLines`` / ``maxCps``.** Consumed at cue GENERATION by
  :func:`caption_polish.resolve_caption_limits`, i.e. UPSTREAM of all three
  engines, so they are not karaoke drops. This preset then re-groups the words it
  is given into its own 1-4-words-per-line look (the teardown model).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import caption_override as _override
from .caption import (
    CueLike,
    caption_position_fields,
    escape_ass_text,
    format_ass_timestamp,
    hook_overlay_parts,
    normalize_caption_box,
    rebase_cue_time,
)

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


def active_color_for_index(index: int, palette: tuple[str, str] = KARAOKE_ACTIVE_INLINE) -> str:
    """Inline ``\\1c`` colour for the word at absolute ``index`` (yellow/green alt).

    ``palette`` defaults to the teardown-verified yellow/green pair; a resolved
    :class:`ResolvedKaraokeStyle` passes its own (see
    :func:`resolve_karaoke_style`, where an explicit ``activeColor`` collapses both
    slots to one colour).
    """
    return palette[index % 2]


# --------------------------------------------------------------------------- #
# override resolution — the CaptionOverride merged onto the KARAOKE base
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResolvedKaraokeStyle:
    """The karaoke visual after merging a validated ``CaptionOverride`` patch.

    Deliberately NOT :class:`caption_override.ResolvedCaptionStyle`: that dataclass
    resolves against the libass-NORMAL base (Arial, outline width 3), so reusing it
    would silently thin the preset's signature thick outline (4 -> 3) on any render
    that merely *has* an override. These defaults are the karaoke preset's own, so
    an absent/empty override reproduces the teardown look byte-for-byte.

    ``uppercase`` / ``position_band`` are TRI-STATE (``None`` = the field was absent
    or malformed, so :func:`build_karaoke_ass` keeps its own argument's value).
    """

    font_name: str = KARAOKE_FONT
    size_scale: float = 1.0
    primary_color: str = KARAOKE_FILL
    secondary_color: str = KARAOKE_FILL
    outline_color: str = KARAOKE_OUTLINE
    back_color: str = KARAOKE_BACK
    border_style: int = KARAOKE_BORDER_STYLE
    outline_width: int = KARAOKE_OUTLINE_WIDTH
    shadow: int = KARAOKE_SHADOW
    active_colors: tuple[str, str] = KARAOKE_ACTIVE_INLINE
    uppercase: bool | None = None
    position_band: str | None = None


def _style_colour(inline: str | None) -> str | None:
    """A ``&HAABBGGRR&`` inline colour as the Style-line form (no trailing ``&``).

    :func:`caption_override.hex_to_ass_color` emits the inline form; Style lines in
    this module are written without the trailing ``&`` (matching
    :data:`KARAOKE_FILL`). ``None`` in -> ``None`` out, so the caller keeps the
    preset colour.
    """
    return inline.rstrip("&") if inline else None


def _resolve_karaoke_border(box: bool | None, outline: bool | None) -> tuple[int, int]:
    """``(BorderStyle, Outline width)`` from the ``box`` / ``outline`` toggles.

    Same precedence as :func:`caption_override._resolve_border` (a solid card and a
    pure outline are mutually exclusive — the card wins) but resolved against the
    KARAOKE defaults, so an untouched pair keeps the preset's THICK outline
    (:data:`KARAOKE_OUTLINE_WIDTH`) instead of the normal path's thinner one.
    """
    if box is True:
        return 3, KARAOKE_OUTLINE_WIDTH  # opaque box card
    if outline is False:
        return KARAOKE_BORDER_STYLE, 0  # stroke explicitly off
    return KARAOKE_BORDER_STYLE, KARAOKE_OUTLINE_WIDTH


def resolve_karaoke_style(override: Mapping[str, Any] | None) -> ResolvedKaraokeStyle:
    """Merge a ``CaptionOverride`` patch onto the OpusClip karaoke base visual.

    Validation is DELEGATED to :func:`caption_override.apply_override` (curated
    font allowlist, strict ``#RRGGBB`` hex, clamped ``sizeScale``, known position
    band) so the two libass paths can never drift on what counts as a valid patch;
    only the DEFAULTS a dropped field falls back to are karaoke's own. A malformed
    field degrades to the preset value field-by-field and never raises.

    Two karaoke-specific semantics:

    * ``fontFamily`` falls back to :data:`KARAOKE_FONT`. An absent/off-allowlist
      font resolves to :data:`caption_override.BASE_FONT` (``Arial``), which is NOT
      a member of ``CURATED_CAPTION_FONTS`` — so that sentinel unambiguously means
      "untouched" and can never be a real user pick.
    * an explicit ``activeColor`` COLLAPSES the yellow/green alternation to that one
      colour. The alternation is the preset's default flourish; a user who names an
      active colour asked for the lit word to be that colour, and alternating it
      against a leftover green would defeat the setting.
    """
    o = override or {}
    base = _override.apply_override(o)
    fill = _style_colour(base.text_color or base.spoken_color) or KARAOKE_FILL
    active = base.active_color
    border_style, outline_width = _resolve_karaoke_border(
        _override.as_bool(o.get("box")), _override.as_bool(o.get("outline"))
    )
    return ResolvedKaraokeStyle(
        font_name=KARAOKE_FONT if base.font_name == _override.BASE_FONT else base.font_name,
        size_scale=base.size_scale,
        primary_color=fill,
        secondary_color=fill,
        border_style=border_style,
        outline_width=outline_width,
        active_colors=(active, active) if active else KARAOKE_ACTIVE_INLINE,
        uppercase=_override.as_bool(o.get("uppercase")),
        position_band=base.position_band,
    )


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

    A cue's ``emphasis`` spans are deliberately NOT bolded here (unlike
    :func:`caption.render_cue_text`): the karaoke Style is ``Bold=-1``
    (:data:`KARAOKE_BOLD`), so the whole line already renders bold and a ``{\\b1}``
    wrap could not produce any visible contrast. This is an explicit decline with a
    mechanical reason, not a dropped feature — see the module docstring.
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
    resolved: ResolvedKaraokeStyle | None = None,
) -> str:
    """The OpusClip karaoke ``Style: Default`` line (all-caps condensed base look).

    White fill, a thick dark outline + shadow (``BorderStyle=1``), bold condensed
    font. The active-word colour + scale-pop are applied inline per word; this
    Style is the white-fill/outline base every word resets (``\\r``) back to.

    ``resolved`` supplies the font / colours / border after a ``CaptionOverride``
    merge; ``None`` means the un-tuned preset, so the emitted line is
    byte-identical to the pre-override V1.1 output. ``Bold`` is deliberately NOT
    overridable — the karaoke look is always bold (which is also why per-word
    ``emphasis`` bolding is declined; see the module docstring).
    """
    style = resolved or resolve_karaoke_style(None)
    return (
        f"Style: Default,{style.font_name},{font_size},"
        f"{style.primary_color},{style.secondary_color},{style.outline_color},{style.back_color},"
        f"{KARAOKE_BOLD},0,0,0,"
        f"100,100,0,0,{style.border_style},{style.outline_width},{style.shadow},"
        f"{alignment},{margin_l},{margin_r},{margin_v},1"
    )


def build_karaoke_ass(
    cues: Sequence[CueLike],
    width: int = 1080,
    height: int = 1920,
    source_start: float = 0.0,
    position_band: str = "bottom",
    uppercase: bool = True,
    override: Mapping[str, Any] | None = None,
    position: Any = None,
    hook_title: str | None = None,
    total_sec: float = 0.0,
    hook_card: bool = False,
    hook_card_sec: float = 0.0,
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

    Styling (v1.5 lane-karaoke — see the module docstring for the full table):

    - ``override`` is a validated ``CaptionOverride`` merged onto the preset by
      :func:`resolve_karaoke_style`; ``None``/``{}`` reproduces the teardown look
      byte-for-byte. Its ``positionBand`` / ``uppercase`` fields, when present, WIN
      over the ``position_band`` / ``uppercase`` arguments (which stay the defaults
      for direct callers).
    - ``position`` is the renderer's normalised ``{x,y,w,h}`` caption box, resolved
      with the SAME :func:`caption.normalize_caption_box` /
      :func:`caption.caption_position_fields` helpers the normal path uses. A
      present ``positionBand`` then re-anchors ``Alignment``/``MarginV`` while the
      box keeps the fine L/R offset — the ordering
      :func:`caption.build_ass` uses.
    - ``hook_title`` / ``total_sec`` / ``hook_card`` / ``hook_card_sec`` emit the
      headline-or-card overlay via the shared :func:`caption.hook_overlay_parts`,
      so the overlay is byte-identical across both libass paths.
    """
    play_x = int(width)
    play_y = int(height)
    resolved = resolve_karaoke_style(override)

    # The override's coarse band wins over the caller's argument when present.
    band = _resolve_band(position_band if resolved.position_band is None else resolved.position_band)
    band_alignment = KARAOKE_BAND_ALIGNMENT[band]
    band_margin_v = safe_area_margin_v(play_y, band)
    margin_h = max(0, int(round(play_x * SIDE_MARGIN_FRACTION)))

    # P4 §4: honour the renderer's normalised caption POSITION box when present;
    # otherwise keep the safe-area band placement. Malformed boxes fall back to the
    # band (no silent crash).
    box = normalize_caption_box(position)
    if box is None:
        alignment, margin_l, margin_r, margin_v = band_alignment, margin_h, margin_h, band_margin_v
    else:
        alignment, margin_l, margin_r, margin_v = caption_position_fields(box, play_x, play_y)
    if resolved.position_band is not None:
        # An explicit band re-anchors; the box still supplies the fine L/R offset.
        alignment, margin_v = band_alignment, band_margin_v

    upper = uppercase if resolved.uppercase is None else resolved.uppercase
    hook_styles, hook_events = hook_overlay_parts(
        hook_title,
        cues,
        play_x,
        play_y,
        source_start=source_start,
        total_sec=total_sec,
        hook_card=hook_card,
        hook_card_sec=hook_card_sec,
    )

    font_size = max(12, int(round(play_y * 0.05)))
    font_size = max(12, int(round(font_size * resolved.size_scale)))

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
        build_karaoke_style_line(font_size, alignment, margin_l, margin_r, margin_v, resolved),
        *hook_styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # The hook overlay is emitted FIRST so it draws above the karaoke line.
    events: list[str] = [*hook_events]
    global_index = 0
    # Bug-sweep: the shortmaker pipeline feeds ONE-WORD cues (features._cues_for_clip
    # emits a cue per transcript word), so grouping per-cue collapsed every karaoke
    # line to a single word. Flatten words across ALL cues first, then group globally
    # so the 1-4-words-per-line look renders from per-word cues. A cue that carries an
    # aligned ``words`` array still contributes its words in order.
    all_words = [word for cue in cues for word in words_from_cue(cue)]
    for line in group_into_lines(all_words):
        for active_index, word in enumerate(line):
            color = active_color_for_index(global_index, resolved.active_colors)
            global_index += 1
            start = rebase_cue_time(word.get("start", 0.0), source_start)
            end = rebase_cue_time(word.get("end", 0.0), source_start)
            if end <= start:
                continue  # entirely before the clip (or zero-length after re-base)
            text = build_line_text(line, active_index, color, uppercase=upper)
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
    "ResolvedKaraokeStyle",
    "active_color_for_index",
    "build_karaoke_ass",
    "build_karaoke_style_line",
    "build_line_text",
    "group_into_lines",
    "is_karaoke_style",
    "resolve_karaoke_style",
    "safe_area_margin_v",
    "words_from_cue",
]
