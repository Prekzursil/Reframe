"""Canonical aspect-ratio registry for the reframe engines (WU R3 multi-aspect).

A single, dependency-light source of truth for the supported social EXPORT
aspects and their canonical output dimensions, shared by BOTH reframe engines
(:mod:`.reframe` verthor adapter + :mod:`.reframe_claudeshorts`) and the export
catalog (:mod:`.export_presets`). Before R3 each engine duplicated this aspect
math "kept in sync with the contract"; this module removes that duplication so
the engines and the catalog can never drift on what 1:1 / 4:5 / 9:16 mean.

Four curated aspects (the OpusClip / Instagram / TikTok / YouTube standard):

  * **9:16** -> 1080x1920  — vertical (Reels / TikTok / Shorts / Stories),
  * **1:1**  -> 1080x1080  — square (Instagram feed),
  * **4:5**  -> 1080x1350  — portrait (Instagram / Facebook feed),
  * **16:9** -> 1920x1080  — widescreen (YouTube / LinkedIn / X, landscape).

:func:`output_dimensions` returns the curated dimensions for those four and a
generic "fit the long edge to 1920" fallback for any OTHER positive ratio (so a
programmatic 3:4 / 21:9 target still resolves to even h264 dimensions). This is a
PURE module — no subprocess, no ffmpeg, no native imports — so it stays trivially
unit-testable and importable by the cycle-sensitive claudeshorts engine.

**Multi-aspect fan-out (v1.5).** :func:`require_supported_aspects` and
:func:`fanout_plan` are the pure primitives for "one source, N aspects, one
action": they canonicalize a whole REQUEST, dedupe it so three vertical
destinations collapse to a single 9:16 render target, and pair each surviving
aspect with its canonical dimensions. Callers get a plan they can execute; the
registry stays the only place that knows what an aspect means.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

#: The default export aspect (vertical) — unchanged from V1.
DEFAULT_ASPECT = "9:16"

#: Curated social export aspects -> canonical (width, height), matching the
#: OpusClip / IG / TikTok / YouTube delivery sizes. 1:1 and 4:5 were the R3
#: net-new aspects alongside the original 9:16; **16:9 is the v1.5 addition**.
#:
#: The three social aspects are 1080-WIDE (portrait/square delivery). 16:9 is
#: landscape, so its canonical size is 1920x1080 — the standard widescreen
#: delivery, and byte-identical to what :func:`output_dimensions` already
#: returned for 16:9 through the generic fallback. Promoting it therefore widens
#: :data:`SUPPORTED_ASPECTS` (what a caller is ALLOWED to ask for) without moving
#: a single pixel of existing geometry.
ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "16:9": (1920, 1080),
}

#: The export-catalog's allowed aspect ids (exactly the curated preset keys).
SUPPORTED_ASPECTS: frozenset[str] = frozenset(ASPECT_PRESETS)

#: The long edge a NON-preset (generic) ratio is scaled to (h264-even). Matches
#: the engines' original fallback math so 3:4 / 21:9 dimensions are unchanged.
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
    parseable-but-uncurated ratio (e.g. ``21:9``) or for garbage — this is the
    boundary guard the export catalog uses so it can only ever persist a render
    target the pipeline actually offers. See :func:`require_supported_aspects` for
    the list form a multi-aspect fan-out crosses.
    """
    norm = normalize_aspect(aspect)
    if norm not in SUPPORTED_ASPECTS:
        raise ValueError(f"unsupported aspect {aspect!r}; supported: {sorted(SUPPORTED_ASPECTS)}")
    return norm


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """Return the ``(width, height)`` the reframe should produce for ``aspect``.

    The four curated social aspects resolve to their fixed dimensions
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


# --------------------------------------------------------------------------- #
# multi-aspect fan-out (v1.5): ONE source -> N aspect targets, in one action
# --------------------------------------------------------------------------- #
class AspectTarget(NamedTuple):
    """One rendered destination of a fan-out: a curated aspect + its canvas."""

    #: The canonical ``"W:H"`` aspect id (a :data:`SUPPORTED_ASPECTS` member).
    aspect: str
    #: Output width in pixels (even, h264-safe).
    width: int
    #: Output height in pixels (even, h264-safe).
    height: int


def require_supported_aspects(aspects: Iterable[str]) -> tuple[str, ...]:
    """Canonicalize + guard a MULTI-aspect request, order-preserving and deduped.

    The list form of :func:`require_supported_aspect`, and the boundary a caller
    crosses when one action targets several aspects at once. Every member is
    normalized and must be curated (an uncurated ratio raises, naming that
    member); duplicates that only differ in spelling — ``"9x16"`` vs ``"9:16"`` —
    collapse to their FIRST occurrence, so a fan-out can never queue the same
    render twice. An empty request raises rather than silently rendering nothing.

    A bare ``str`` is rejected explicitly: Python would iterate it CHARACTER by
    character, so ``"9:16"`` would fan out to ``"9"`` / ``":"`` / ``"1"`` / ``"6"``
    and fail somewhere downstream with a nonsense message. Fail loud, here.
    """
    if isinstance(aspects, str):
        raise ValueError(f"aspects must be an iterable of aspect strings, got the bare str {aspects!r}")
    out: list[str] = []
    seen: set[str] = set()
    for raw in aspects:
        norm = require_supported_aspect(raw)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    if not out:
        raise ValueError("at least one aspect is required")
    return tuple(out)


def fanout_plan(aspects: Iterable[str]) -> tuple[AspectTarget, ...]:
    """The render matrix for a multi-aspect fan-out of ONE source.

    Returns one :class:`AspectTarget` per DISTINCT requested aspect, in request
    order, each carrying the canonical canvas from :func:`output_dimensions`. The
    dedupe is what makes the plan meaningful at the destination level: picking
    TikTok + Reels + Shorts is three destinations but ONE 9:16 render, so the plan
    has a single entry and the caller produces a single file.

    Raises ``ValueError`` (via :func:`require_supported_aspects`) for an empty
    request or any uncurated member — a fan-out plan is only ever built from
    aspects the pipeline actually offers.
    """
    return tuple(AspectTarget(a, *output_dimensions(a)) for a in require_supported_aspects(aspects))


__all__ = [
    "ASPECT_PRESETS",
    "DEFAULT_ASPECT",
    "SUPPORTED_ASPECTS",
    "AspectTarget",
    "even",
    "fanout_plan",
    "normalize_aspect",
    "output_dimensions",
    "parse_aspect",
    "require_supported_aspect",
    "require_supported_aspects",
]
