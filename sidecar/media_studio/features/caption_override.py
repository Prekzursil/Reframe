"""Caption *override* resolution — the sidecar half of the V1.1 Lane-1 tuning patch.

V1 treats a caption style as a whole-template atomic pick. V1.1 (WU S1 renderer /
WU S2 sidecar) adds a SEPARATE, additive :class:`CaptionOverride` patch that tweaks
~8 primitive controls (font / size / colours / outline / card / casing /
position-band / line-count / reading-speed) ON TOP of the resolved template visual,
*without* touching the frozen three-way caption mirror.

This module is the concrete render contract for that patch: it merges a validated
override onto the base libass caption visual and resolves it to a
:class:`ResolvedCaptionStyle` whose fields :func:`media_studio.features.caption.build_ass`
emits as the ``Style: Default`` line (and which is echoed back to the UI so the live
preview shows exactly what will burn).

Everything here is PURE (no ffmpeg, no I/O) and fully unit-tested.

Load-bearing format detail (the silent-wrong-colour trap, §1.2 of V1.1-FEATURES):
ASS colours are ``&HAABBGGRR`` — **alpha + blue-green-red, the reverse of CSS
``#RRGGBB``** — and the alpha byte is *inverted* (``00`` = opaque, ``FF`` =
transparent). :func:`hex_to_ass_color` performs that byte-swap (defaulting alpha to
``00`` = fully opaque), so ``#FF0000`` becomes ``&H000000FF&``. Getting this wrong
renders the wrong colour with no crash, so the unit tests assert the EXACT ``&H…``
string per input hex.

Validation mirrors the renderer's ``sanitizeCaptionOverride`` (defence in depth — the
sidecar never trusts the wire): unknown font => drop (keep the template font), bad
hex => drop (keep the template colour), out-of-range number => clamp. A malformed
override degrades field-by-field to the template default; it never raises.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# the bundled, curated caption-font allowlist (DECISIONS §3: a fixed list, no
# system-font detection). MUST mirror the renderer's CURATED_CAPTION_FONTS
# (lib/captionOverride.ts) — a font outside this set is dropped so a burn never
# silently falls back to an unexpected face. ``DejaVu Sans`` is libass's
# always-present fallback and the base/default body font is ``Arial``.
# --------------------------------------------------------------------------- #
CURATED_CAPTION_FONTS: tuple[str, ...] = (
    "Inter",
    "Roboto",
    "Open Sans",
    "Noto Sans",
    "Lato",
    "Nunito",
    "Montserrat",
    "Poppins",
    "Oswald",
    "Anton",
    "Bebas Neue",
    "Archivo Black",
    "DejaVu Sans",
)

# --------------------------------------------------------------------------- #
# base libass caption visual — these are EXACTLY the values the historical
# ``build_ass`` ``Style: Default`` line hard-codes, so resolving an empty/None
# override reproduces the V1 style byte-for-byte (back-compat keystone).
# --------------------------------------------------------------------------- #
BASE_FONT = "Arial"
BASE_PRIMARY = "&H00FFFFFF"  # white text fill
BASE_SECONDARY = "&H000000FF"  # karaoke secondary (red, libass default-ish)
BASE_OUTLINE = "&H00000000"  # black outline
BASE_BACK = "&H64000000"  # semi-opaque shadow/box backdrop
BASE_BORDER_STYLE = 1  # 1 = outline+shadow, 3 = opaque box
BASE_OUTLINE_WIDTH = 3
BASE_SHADOW = 1

#: font-size multiplier clamp window (§1.2). Mirrors the renderer.
SIZE_SCALE_MIN = 0.6
SIZE_SCALE_MAX = 1.8

#: coarse vertical bands -> ASS numpad ``Alignment`` (all horizontally centred).
POSITION_BAND_ALIGNMENT = {"top": 8, "center": 5, "bottom": 2}

#: ``#RRGGBB`` only — 3-digit shorthand / alpha forms are deliberately rejected
#: (mirrors the renderer's HEX_COLOR), so a malformed colour drops to the template.
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def hex_to_ass_color(value: Any, alpha: str = "00") -> str | None:
    r"""Convert a CSS ``#RRGGBB`` hex colour to an ASS ``&HAABBGGRR&`` colour.

    The byte order is **reversed** (CSS is RGB, ASS is BGR) and an ``alpha`` byte
    is prepended (default ``"00"`` = fully opaque under ASS's *inverted* alpha
    convention). Returns the uppercase ``&H…&`` token, or ``None`` for anything
    that is not a strict ``#RRGGBB`` string (the caller then keeps the template
    colour — never a silent crash).

    >>> hex_to_ass_color("#FF0000")
    '&H000000FF&'
    >>> hex_to_ass_color("#123456")
    '&H00563412&'
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not _HEX_COLOR.match(s):
        return None
    rr, gg, bb = s[1:3], s[3:5], s[5:7]
    return f"&H{alpha}{bb}{gg}{rr}&".upper()


def _as_bool(value: Any) -> bool | None:
    """Return ``value`` when it is a genuine ``bool``, else ``None`` (absent)."""
    return value if isinstance(value, bool) else None


def _clamp_size_scale(value: Any) -> float:
    """Clamp ``value`` into ``[SIZE_SCALE_MIN, SIZE_SCALE_MAX]`` or default to ``1.0``.

    A non-number / non-finite / boolean ``value`` (booleans are *not* sizes) drops
    to the neutral ``1.0`` multiplier.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 1.0
    if value < SIZE_SCALE_MIN:
        return SIZE_SCALE_MIN
    if value > SIZE_SCALE_MAX:
        return SIZE_SCALE_MAX
    return float(value)


@dataclass(frozen=True)
class ResolvedCaptionStyle:
    """The fully-resolved libass body-caption visual after override merge.

    ``build_ass`` reads these fields to emit the ``Style: Default`` line; the same
    object (via :meth:`to_dict`) is echoed to the UI so the live preview matches
    the burn exactly. ``size_scale`` is a multiplier on the canvas-derived base
    font size (applied at emit time, not a fixed px). The ``*_color`` role fields
    keep the per-role resolved values for preview parity even though several map to
    the same ASS Style colour slot.
    """

    font_name: str = BASE_FONT
    size_scale: float = 1.0
    primary_color: str = BASE_PRIMARY
    secondary_color: str = BASE_SECONDARY
    outline_color: str = BASE_OUTLINE
    back_color: str = BASE_BACK
    border_style: int = BASE_BORDER_STYLE
    outline_width: int = BASE_OUTLINE_WIDTH
    shadow: int = BASE_SHADOW
    uppercase: bool = False
    position_band: str | None = None
    # per-role colours kept for the UI echo / preview parity (None => template).
    text_color: str | None = None
    active_color: str | None = None
    spoken_color: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable echo of the resolved style (post-conversion)."""
        return asdict(self)


def _resolve_border(box: bool | None, outline: bool | None) -> tuple[int, int]:
    """Resolve ``(BorderStyle, Outline-width)`` from the ``box`` / ``outline`` toggles.

    Precedence (a solid card and a pure outline are mutually exclusive — the card
    wins): a ``box`` card => ``BorderStyle=3`` (opaque box, uses ``BackColour``);
    otherwise an explicit ``outline`` toggle picks stroke on (width 3) / off
    (width 0); an untouched pair keeps the base outline+shadow style.
    """
    if box is True:
        return 3, BASE_OUTLINE_WIDTH
    if outline is True:
        return 1, BASE_OUTLINE_WIDTH
    if outline is False:
        return 1, 0
    return BASE_BORDER_STYLE, BASE_OUTLINE_WIDTH


def apply_override(override: Mapping[str, Any] | None) -> ResolvedCaptionStyle:
    """Merge a validated :class:`CaptionOverride` patch onto the base libass visual.

    Each field is resolved independently and degrades to the template default when
    absent or malformed (unknown font dropped, bad hex dropped, out-of-range size
    clamped) — never raising. ``None`` / ``{}`` yields the base style unchanged
    (byte-identical to V1). Colour roles map to ASS Style slots as: ``textColor``
    (or, failing that, the karaoke ``spokenColor``) -> ``PrimaryColour``;
    ``activeColor`` -> ``SecondaryColour``.
    """
    o = override or {}

    raw_font = o.get("fontFamily")
    font_name = raw_font.strip() if isinstance(raw_font, str) else ""
    font_name = font_name if font_name in CURATED_CAPTION_FONTS else BASE_FONT

    text_color = hex_to_ass_color(o.get("textColor"))
    active_color = hex_to_ass_color(o.get("activeColor"))
    spoken_color = hex_to_ass_color(o.get("spokenColor"))
    primary = text_color or spoken_color or BASE_PRIMARY
    secondary = active_color or BASE_SECONDARY

    border_style, outline_width = _resolve_border(_as_bool(o.get("box")), _as_bool(o.get("outline")))

    band = o.get("positionBand")
    position_band = band if band in POSITION_BAND_ALIGNMENT else None

    return ResolvedCaptionStyle(
        font_name=font_name,
        size_scale=_clamp_size_scale(o.get("sizeScale")),
        primary_color=primary,
        secondary_color=secondary,
        outline_color=BASE_OUTLINE,
        back_color=BASE_BACK,
        border_style=border_style,
        outline_width=outline_width,
        shadow=BASE_SHADOW,
        uppercase=_as_bool(o.get("uppercase")) or False,
        position_band=position_band,
        text_color=text_color,
        active_color=active_color,
        spoken_color=spoken_color,
    )


def resolve_caption_style(override: Mapping[str, Any] | None) -> dict[str, Any]:
    """Echo helper: the resolved style as a plain dict (post-conversion &H colours).

    Thin wrapper over :func:`apply_override` for the UI preview/echo path so the
    renderer shows exactly what will burn (the resolved colours are already in the
    ASS ``&H…&`` form used by the Style line).
    """
    return apply_override(override).to_dict()


__all__ = [
    "BASE_BACK",
    "BASE_BORDER_STYLE",
    "BASE_FONT",
    "BASE_OUTLINE",
    "BASE_OUTLINE_WIDTH",
    "BASE_PRIMARY",
    "BASE_SECONDARY",
    "BASE_SHADOW",
    "CURATED_CAPTION_FONTS",
    "POSITION_BAND_ALIGNMENT",
    "SIZE_SCALE_MAX",
    "SIZE_SCALE_MIN",
    "ResolvedCaptionStyle",
    "apply_override",
    "hex_to_ass_color",
    "resolve_caption_style",
]
