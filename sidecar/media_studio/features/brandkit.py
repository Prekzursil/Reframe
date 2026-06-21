"""Brand kit export side — pure logo-overlay builder + brand defaults (P4 §8d / C12).

The brand kit lets a user stamp every exported short with a corner logo and
default the caption look (template + font) when they haven't picked one. This
module owns the **export side** of that, kept PURE + unit-testable:

  * :func:`build_logo_overlay_argv` — an ffmpeg argv that composites a logo image
    over a clip in a padded corner. It follows the proven SECOND-INPUT pattern of
    ``shortmaker.build_audio_mux_argv`` (input 0 = the clip, input 1 = the logo)
    and routes through the drained :func:`ffmpeg.run` seam (no re-implemented
    drain). argv LIST only (never ``shell=True``).
  * :func:`resolve_brand_defaults` — applies ``settings.brandCaptionTemplate`` /
    ``settings.brandFontFamily`` as DEFAULTS only when the user did NOT override
    them on the export (immutable: returns a new settings dict).

Brand settings keys (free-form; persisted via ``settings.set`` — PLAN-P4 C12):
``brandLogoPath`` (str|""), ``brandCaptionTemplate`` (template id|""),
``brandFontFamily`` (str|""). Added to ``DEFAULT_SETTINGS`` for discoverability;
there is NO ``outputDir`` (C12 — exports stay in ``Services.exports_dir``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Corner positions for the overlay, mapped to an ffmpeg ``overlay`` x:y pair. The
# logo is inset by :data:`DEFAULT_PADDING` px from the chosen edges; ``main_w`` /
# ``main_h`` / ``overlay_w`` / ``overlay_h`` are ffmpeg overlay-filter variables.
CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")

#: Default corner when settings don't specify one (top-right reads as a watermark
#: without colliding with bottom captions).
DEFAULT_CORNER = "top-right"

#: Default inset from the frame edges, in pixels.
DEFAULT_PADDING = 48

# Brand settings keys (FROZEN — mirror DEFAULT_SETTINGS / the §8d settings UI).
LOGO_PATH_KEY = "brandLogoPath"
CAPTION_TEMPLATE_KEY = "brandCaptionTemplate"
FONT_FAMILY_KEY = "brandFontFamily"


def _corner_xy(corner: str, padding: int) -> str:
    """The ffmpeg ``overlay`` ``x:y`` expression for ``corner`` (padded).

    Uses overlay-filter variables so the inset is correct at any clip/logo size:
      top-left      -> ``P:P``
      top-right     -> ``main_w-overlay_w-P:P``
      bottom-left   -> ``P:main_h-overlay_h-P``
      bottom-right  -> ``main_w-overlay_w-P:main_h-overlay_h-P``
    """
    p = int(padding)
    left = str(p)
    top = str(p)
    right = f"main_w-overlay_w-{p}"
    bottom = f"main_h-overlay_h-{p}"
    table = {
        "top-left": f"{left}:{top}",
        "top-right": f"{right}:{top}",
        "bottom-left": f"{left}:{bottom}",
        "bottom-right": f"{right}:{bottom}",
    }
    return table[corner]


def build_logo_overlay_filter(
    *,
    corner: str = DEFAULT_CORNER,
    padding: int = DEFAULT_PADDING,
    logo_scale_pct: float | None = None,
) -> str:
    """The ffmpeg ``filter_complex`` string compositing input 1 onto input 0.

    When ``logo_scale_pct`` is given the logo is first scaled to that percentage
    of the MAIN video width (keeping its aspect via ``-1``), then overlaid in the
    padded ``corner``. Pure: returns a string only.
    """
    if corner not in CORNERS:
        raise ValueError(f"corner must be one of {CORNERS}, got {corner!r}")
    if padding < 0:
        raise ValueError("padding must be >= 0")
    xy = _corner_xy(corner, padding)
    if logo_scale_pct is not None:
        if logo_scale_pct <= 0:
            raise ValueError("logo_scale_pct must be > 0 when given")
        # Scale input 1 (the logo) to a fraction of the MAIN width; -1 keeps AR.
        frac = float(logo_scale_pct) / 100.0
        return f"[1:v]scale=iw*{frac:.4f}:-1[logo];[0:v][logo]overlay={xy}"
    return f"[0:v][1:v]overlay={xy}"


def build_logo_overlay_argv(
    clip_path: str,
    logo_path: str,
    out_path: str,
    *,
    corner: str = DEFAULT_CORNER,
    padding: int = DEFAULT_PADDING,
    logo_scale_pct: float | None = None,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv compositing ``logo_path`` over ``clip_path`` in a padded corner.

    Mirrors :func:`shortmaker.build_audio_mux_argv`'s second-input shape: input 0
    is the finished clip (its audio copied through), input 1 is the logo image
    (``-loop 1`` so a still PNG covers the whole clip; ``-shortest`` ends with the
    video). The video is re-encoded with the overlay ``-filter_complex``; the
    audio is stream-copied. ``-progress pipe:1 -nostats`` so :func:`ffmpeg.run`
    drains stdout (C16 — reuse the proven drained seam). argv LIST only.
    """
    if not clip_path:
        raise ValueError("logo overlay requires a clip path")
    if not logo_path:
        raise ValueError("logo overlay requires a logo path")
    from .. import ffmpeg as _ffmpeg  # lazy: keep module import-light

    filter_complex = build_logo_overlay_filter(corner=corner, padding=padding, logo_scale_pct=logo_scale_pct)
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        clip_path,
        # -loop 1 so a still image spans the clip; -shortest ends with the video.
        "-loop",
        "1",
        "-i",
        logo_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-shortest",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


def brand_logo_path(settings: Mapping[str, Any] | None) -> str:
    """The configured brand logo path (``""`` when unset). Pure."""
    return str((settings or {}).get(LOGO_PATH_KEY) or "").strip()


def has_brand_logo(settings: Mapping[str, Any] | None) -> bool:
    """Whether a brand logo is configured (a non-empty ``brandLogoPath``)."""
    return bool(brand_logo_path(settings))


def resolve_brand_defaults(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Apply brand caption template / font as DEFAULTS (immutable; PLAN-P4 §8d).

    Returns a NEW settings dict. The brand template/font fill in ONLY when the
    user did not override them on the export:

      * ``captionStyle`` falls back to ``brandCaptionTemplate`` when absent/blank;
      * ``captionFontFamily`` falls back to ``brandFontFamily`` when absent/blank.

    The user's explicit choice always wins (the brand kit is a default, never an
    override). The input is never mutated.
    """
    merged: dict[str, Any] = dict(settings or {})
    brand_template = str(merged.get(CAPTION_TEMPLATE_KEY) or "").strip()
    if brand_template and not str(merged.get("captionStyle") or "").strip():
        merged["captionStyle"] = brand_template
    brand_font = str(merged.get(FONT_FAMILY_KEY) or "").strip()
    if brand_font and not str(merged.get("captionFontFamily") or "").strip():
        merged["captionFontFamily"] = brand_font
    return merged


__all__ = [
    "CAPTION_TEMPLATE_KEY",
    "CORNERS",
    "DEFAULT_CORNER",
    "DEFAULT_PADDING",
    "FONT_FAMILY_KEY",
    "LOGO_PATH_KEY",
    "brand_logo_path",
    "build_logo_overlay_argv",
    "build_logo_overlay_filter",
    "has_brand_logo",
    "resolve_brand_defaults",
]
