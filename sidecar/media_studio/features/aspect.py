"""Canonical aspect-ratio registry for the reframe engines (WU R3 multi-aspect).

A single, dependency-light source of truth for the supported social EXPORT
aspects and their canonical output dimensions, shared by BOTH reframe engines
(:mod:`.reframe` verthor adapter + :mod:`.reframe_claudeshorts`) and the export
catalog (:mod:`.export_presets`). Before R3 each engine duplicated this aspect
math "kept in sync with the contract"; this module removes that duplication so
the engines and the catalog can never drift on what 1:1 / 4:5 / 9:16 mean.

Three curated aspects (the OpusClip / Instagram / TikTok standard, all 1080-wide):

  * **9:16** -> 1080x1920  — vertical (Reels / TikTok / Shorts / Stories),
  * **1:1**  -> 1080x1080  — square (Instagram feed),
  * **4:5**  -> 1080x1350  — portrait (Instagram / Facebook feed).

:func:`output_dimensions` returns the curated dimensions for those three and a
generic "fit the long edge to 1920" fallback for any OTHER positive ratio (so a
programmatic 16:9 / 3:4 target still resolves to even h264 dimensions). This is a
PURE module — no subprocess, no ffmpeg, no native imports — so it stays trivially
unit-testable and importable by the cycle-sensitive claudeshorts engine.
"""

from __future__ import annotations

#: The default export aspect (vertical) — unchanged from V1.
DEFAULT_ASPECT = "9:16"

#: Curated social export aspects -> canonical (width, height). All 1080-wide,
#: matching the OpusClip / IG / TikTok delivery sizes. 1:1 and 4:5 are the R3
#: net-new aspects alongside the original 9:16.
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}

#: The export-catalog's allowed aspect ids (exactly the curated preset keys).
SUPPORTED_ASPECTS: frozenset[str] = frozenset(ASPECT_PRESETS)

#: The long edge a NON-preset (generic) ratio is scaled to (h264-even). Matches
#: the engines' original fallback math so 3:4 / 16:9 dimensions are unchanged.
_FALLBACK_LONG_EDGE = 1920


def parse_aspect(aspect: str) -> tuple[int, int]:
    """Parse a ``"W:H"`` (or ``"WxH"``) aspect string into a positive ``(w, h)``.

    Accepts a colon or an ``x`` separator and surrounding whitespace. Raises
    ``ValueError`` for anything that is not exactly two POSITIVE integers — the
    same fail-loud contract both engines enforced individually.
    """
    raw = str(aspect).strip().replace("x", ":")
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"aspect must be 'W:H', got {aspect!r}")
    try:
        w, h = int(parts[0]), int(parts[1])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"aspect must be two integers, got {aspect!r}") from exc
    if w <= 0 or h <= 0:
        raise ValueError(f"aspect components must be positive, got {aspect!r}")
    return w, h


def even(n: int) -> int:
    """Round a dimension up to the nearest even value (h264 requires even sizes)."""
    return n if n % 2 == 0 else n + 1


def normalize_aspect(aspect: str) -> str:
    """Canonicalize an aspect string to ``"W:H"`` (validating it parses).

    ``"9x16"`` / ``"  9:16 "`` -> ``"9:16"``. Raises ``ValueError`` on garbage.
    The canonical form is what :data:`ASPECT_PRESETS` is keyed on.
    """
    w, h = parse_aspect(aspect)
    return f"{w}:{h}"


def require_supported_aspect(aspect: str) -> str:
    """Normalize ``aspect`` and assert it is one of the curated :data:`SUPPORTED_ASPECTS`.

    Returns the canonical ``"W:H"`` form. Raises ``ValueError`` (fail loud) for a
    parseable-but-uncurated ratio (e.g. ``16:9``) or for garbage — this is the
    boundary guard the export catalog uses so it can only ever persist a render
    target the pipeline actually offers.
    """
    norm = normalize_aspect(aspect)
    if norm not in SUPPORTED_ASPECTS:
        raise ValueError(f"unsupported aspect {aspect!r}; supported: {sorted(SUPPORTED_ASPECTS)}")
    return norm


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """Return the ``(width, height)`` the reframe should produce for ``aspect``.

    The three curated social aspects resolve to their fixed 1080-wide dimensions
    (:data:`ASPECT_PRESETS`). Any other positive ratio falls back to the engines'
    original generic math: portrait/square fix the HEIGHT to 1920, landscape fix
    the WIDTH to 1920, deriving the other edge from the ratio rounded to even.
    """
    norm = normalize_aspect(aspect)
    preset = ASPECT_PRESETS.get(norm)
    if preset is not None:
        return preset
    w, h = parse_aspect(norm)
    if h >= w:
        return even(int(round(_FALLBACK_LONG_EDGE * (w / h)))), _FALLBACK_LONG_EDGE
    return _FALLBACK_LONG_EDGE, even(int(round(_FALLBACK_LONG_EDGE * (h / w))))


__all__ = [
    "ASPECT_PRESETS",
    "DEFAULT_ASPECT",
    "SUPPORTED_ASPECTS",
    "even",
    "normalize_aspect",
    "output_dimensions",
    "parse_aspect",
    "require_supported_aspect",
]
