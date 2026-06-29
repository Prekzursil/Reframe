r"""OpusClip-style HOOK-CARD overlay + virality-rank gating (V1.1 WU SP2).

The P3-A ``hook_title`` overlay (:func:`caption.build_ass`) renders the
candidate's hook as a plain white top headline for the whole clip. OpusClip's
teardown (``razvan_gandu``) shows a stronger device on its BEST clips only: a
**hook card** — a white rounded box with bold BLACK text in the upper third,
shown for the **first ~5 s only**, and applied to the **top-N clips by virality
rank only** (the rest keep the plain title). It also exports clips with a
rank-ordered **01-N filename prefix** so the set sorts by virality in a file
browser.

This module owns the PURE half of that feature:

  * :func:`resolve_hook_card_config` — parse the (clamped) config off the export
    settings (enabled / top-N / first-~5 s window). Bad/missing inputs fall back
    to sane defaults at the boundary (input sanitisation, not a silent error).
  * :func:`select_hook_card_ranks` — the TOP-N **virality-rank** GATE: the N
    smallest ``rank`` values (rank 1 == best virality) get a card.
  * :func:`order_prefix` / :func:`rank_ordered_stem` — the rank-ordered,
    zero-padded ``01-N`` output filename prefix (the "title export").
  * :func:`hook_card_style_line` / :func:`hook_card_end_sec` — the libass ASS
    Style line (white opaque box / bold black / upper-third) + the first-seconds
    time-box. :func:`caption.build_ass` emits these when ``hook_card=True``.

Load-bearing colour detail (the silent-wrong-colour trap, mirrored from
:mod:`.caption_override`): ASS colours are ``&HAABBGGRR`` (BGR + *inverted*
alpha). With ``BorderStyle=3`` (opaque box) libass fills the box with the
**OutlineColour** — so the WHITE card is the OutlineColour and the BLACK text is
the PrimaryColour. The resolved ``&H`` forms are pinned as constants whose drift
from :func:`caption_override.hex_to_ass_color` is asserted by the unit tests.

Everything here is PURE (no ffmpeg, no I/O).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# palette (#RRGGBB declared; &H resolved forms pinned + drift-tested)
# --------------------------------------------------------------------------- #
HOOK_CARD_FILL_HEX = "#FFFFFF"  # the white card box
HOOK_CARD_TEXT_HEX = "#000000"  # bold black headline text

#: Style-line colour form (``&HAABBGGRR`` WITHOUT the trailing ``&``, matching
#: :data:`caption_override.BASE_PRIMARY`). == ``hex_to_ass_color(...)[:-1]``.
HOOK_CARD_TEXT = "&H00000000"  # PrimaryColour = black text
HOOK_CARD_BOX = "&H00FFFFFF"  # OutlineColour = white box (BorderStyle 3)
HOOK_CARD_SECONDARY = "&H000000FF"  # unused karaoke slot (mirrors BASE_SECONDARY)
HOOK_CARD_BACK = "&H64000000"  # semi-opaque drop shadow (mirrors BASE_BACK)

# --------------------------------------------------------------------------- #
# typography / geometry
# --------------------------------------------------------------------------- #
HOOK_CARD_STYLE_NAME = "HookCard"
HOOK_CARD_FONT = "Arial"
HOOK_CARD_BOLD = -1  # ASS true (bold)
HOOK_CARD_BORDER_STYLE = 3  # 3 = opaque box (the card); 1 = outline+shadow
HOOK_CARD_OUTLINE_WIDTH = 6  # box padding around the text
HOOK_CARD_SHADOW = 1
HOOK_CARD_ALIGNMENT = 8  # numpad top-centre -> upper area
#: font size + margins as fractions of the canvas.
HOOK_CARD_FONT_FRACTION = 0.05
HOOK_CARD_TOP_FRACTION = 0.12  # MarginV from the top edge -> upper third
HOOK_CARD_SIDE_FRACTION = 0.08  # L/R margin so the card clears the edges

# --------------------------------------------------------------------------- #
# config defaults / clamps
# --------------------------------------------------------------------------- #
HOOK_CARD_DEFAULT_TOP_N = 10  # OpusClip cards the top-10 ranked clips only
HOOK_CARD_DEFAULT_SEC = 5.0  # cards show for the first ~5 s only
HOOK_CARD_MIN_SEC = 0.5
HOOK_CARD_MAX_SEC = 30.0
HOOK_CARD_MIN_ORDER_WIDTH = 2  # zero-pad the order prefix to at least 01-NN


@dataclass(frozen=True)
class HookCardConfig:
    """Resolved hook-card export config (all already validated/clamped)."""

    enabled: bool = True
    top_n: int = HOOK_CARD_DEFAULT_TOP_N
    duration_sec: float = HOOK_CARD_DEFAULT_SEC


def _as_int_count(value: Any) -> int | None:
    """Return ``value`` as a positive int count, or ``None`` when it is not one.

    ``bool`` is rejected (a toggle is not a count) and so is any non-``int`` /
    non-positive value, so the caller falls back to the default rather than
    silently using a nonsense count.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else 1


def _as_seconds(value: Any) -> float | None:
    """Return ``value`` clamped into the [MIN, MAX] window, or ``None`` when it is
    not a usable number (``bool`` / non-number / non-finite / non-positive)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0.0:
        return None
    return float(min(max(value, HOOK_CARD_MIN_SEC), HOOK_CARD_MAX_SEC))


def resolve_hook_card_config(settings: Mapping[str, Any] | None) -> HookCardConfig:
    """Parse the hook-card config off the export ``settings`` (clamped).

    ``hookCard`` (bool, default ON) toggles the feature; ``hookCardTopN`` (int
    >= 1, default 10) gates how many top clips get a card; ``hookCardSec`` (float
    in [0.5, 30], default 5) is the first-seconds time-box. A missing / wrong-typed
    value falls back to its default (input sanitisation at the boundary — never a
    silent crash).
    """
    s = settings or {}
    raw_enabled = s.get("hookCard")
    enabled = raw_enabled if isinstance(raw_enabled, bool) else True
    top_n = _as_int_count(s.get("hookCardTopN"))
    duration = _as_seconds(s.get("hookCardSec"))
    return HookCardConfig(
        enabled=enabled,
        top_n=HOOK_CARD_DEFAULT_TOP_N if top_n is None else top_n,
        duration_sec=HOOK_CARD_DEFAULT_SEC if duration is None else duration,
    )


def resolve_rank(candidate: Mapping[str, Any], fallback: int) -> int:
    """The candidate's virality ``rank`` (int), or ``fallback`` when absent/bad.

    ``bool`` is rejected (it is not a rank); anything not coercible to ``int``
    falls back to the caller's 1-based position so gating/ordering still works.
    """
    raw = candidate.get("rank")
    if isinstance(raw, bool):
        return fallback
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def select_hook_card_ranks(candidates: Sequence[Mapping[str, Any]], config: HookCardConfig) -> frozenset[int]:
    """The set of ``rank`` values that get a hook card — the TOP-N by virality.

    Gating is by **virality rank only**: rank 1 is the best clip, so the N
    smallest ranks qualify. Returns an empty set when the feature is disabled or
    there are no candidates. A candidate missing a rank uses its 1-based position.
    """
    if not config.enabled:
        return frozenset()
    ranks = sorted(resolve_rank(c, i + 1) for i, c in enumerate(candidates))
    return frozenset(ranks[: config.top_n])


def max_export_rank(candidates: Sequence[Mapping[str, Any]]) -> int:
    """The largest ``rank`` across ``candidates`` (>= 1) — the order-prefix width."""
    return max((resolve_rank(c, i + 1) for i, c in enumerate(candidates)), default=1)


def order_prefix(rank: Any, max_rank: Any) -> str:
    """Zero-padded rank-ordered filename prefix (``01``, ``02`` … ``NN``).

    Padded to the width of ``max_rank`` (so 41 clips -> ``01``..``41``), with a
    minimum width of 2 so a single-digit set still sorts (``01`` not ``1``).
    """
    width = max(HOOK_CARD_MIN_ORDER_WIDTH, len(str(max(1, int(max_rank)))))
    return f"{int(rank):0{width}d}"


def rank_ordered_stem(base: str, rank: Any, max_rank: Any) -> str:
    """The rank-ordered output stem: ``<NN>-<base>`` (sorts by virality rank)."""
    return f"{order_prefix(rank, max_rank)}-{base}"


def hook_card_style_line(width: int, height: int) -> str:
    """The libass ``Style: HookCard`` line — white opaque box, bold black text,
    upper-third (top-centre). Sized + margined to the ``width`` x ``height``
    canvas (default the 1080x1920 vertical short)."""
    size = max(14, int(round(int(height) * HOOK_CARD_FONT_FRACTION)))
    margin_v = max(12, int(round(int(height) * HOOK_CARD_TOP_FRACTION)))
    margin_lr = max(20, int(round(int(width) * HOOK_CARD_SIDE_FRACTION)))
    return (
        f"Style: {HOOK_CARD_STYLE_NAME},{HOOK_CARD_FONT},"
        f"{size},"
        f"{HOOK_CARD_TEXT},{HOOK_CARD_SECONDARY},{HOOK_CARD_BOX},{HOOK_CARD_BACK},"
        f"{HOOK_CARD_BOLD},0,0,0,"
        f"100,100,0,0,{HOOK_CARD_BORDER_STYLE},{HOOK_CARD_OUTLINE_WIDTH},{HOOK_CARD_SHADOW},"
        f"{HOOK_CARD_ALIGNMENT},{margin_lr},{margin_lr},{margin_v},1"
    )


def hook_card_end_sec(duration_sec: float, total_sec: float) -> float:
    """The card's end time: the first ``duration_sec`` seconds, capped to the clip
    length (``total_sec``) when it is known (> 0). A non-positive ``duration_sec``
    falls back to the default window."""
    sec = float(duration_sec)
    if sec <= 0.0:
        sec = HOOK_CARD_DEFAULT_SEC
    if total_sec and float(total_sec) > 0.0:
        return min(sec, float(total_sec))
    return sec
