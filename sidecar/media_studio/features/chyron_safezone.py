"""Source-chyron safe-zone detection (WU R4 / N6).

TV / talk-show sources frequently burn a *chyron* (lower-third banner) or a
*source bar* ("Sursa: Facebook/…") directly into the picture. When we reframe a
16:9 source to a narrow 9:16 vertical, that burned-in strip "rides along": the
pan keeps full height, so a full-width bottom bar surfaces as a sliced fragment,
and OUR burned captions / the chosen face can collide with it.

This module is the **PURE, dependency-free** detection + safe-zone layer (see the
OpusClip teardown ``opus-clip-teardown-razvan-gandu`` and the parity note
``docs/research/OPUSCLIP-PARITY-IMPROVEMENT-NOTE-2026-06-28.md`` §N6). It:

  * turns per-frame OCR text boxes into horizontal **bands** (one frame at a time),
  * classifies a band as a **top/bottom chyron candidate** by width + edge,
  * keeps only bands that **persist** across enough sampled frames (a transient
    on-screen caption is NOT a chyron), and
  * exposes a :class:`SafeZone` the reframe engines consume to (a) keep OUR
    captions / the tracked face OUT of a chyron band, and (b) detect when a
    horizontal pan would SLICE a localised source bug.

The heavy OCR half lives behind the :class:`OcrBackend` Protocol seam (real impl:
``chyron_safezone_backend.RealChyronOcrBackend``, ``# pragma: no cover``). Every input
is validated at the boundary and every failure is LOUD (:class:`ChyronError`) —
never a silent neutral result. All coordinates are normalised to ``[0, 1]`` of
the source frame (``x``/``left`` = horizontal, ``y``/``top`` = vertical).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

#: Float slack for unit-range fit checks (guards float division round-off).
_EPS = 1e-9

#: Edge labels a chyron band may carry.
EDGE_TOP = "top"
EDGE_BOTTOM = "bottom"
EDGES: tuple[str, ...] = (EDGE_TOP, EDGE_BOTTOM)

#: Tuning defaults (normalised). A chyron spans a wide horizontal strip pinned
#: near the top or bottom edge and is present in most sampled frames.
DEFAULT_VERTICAL_GAP = 0.04
DEFAULT_MIN_WIDTH = 0.35
DEFAULT_EDGE_MARGIN = 0.18
DEFAULT_PERSISTENCE = 0.5
DEFAULT_Y_TOL = 0.05
DEFAULT_CAPTION_PADDING = 0.02
DEFAULT_SAMPLE_COUNT = 12

#: A face / caption rectangle under test: ``(x, y, w, h)`` normalised.
Rect = tuple[float, float, float, float]


class ChyronError(ValueError):
    """Raised on any malformed input or impossible safe-zone (never silent)."""


def _require_unit(value: float, label: str) -> None:
    """Reject a value outside the closed unit interval ``[0, 1]``."""
    if value < 0.0 or value > 1.0:
        raise ChyronError(f"{label} must be within [0, 1]")


@dataclass(frozen=True)
class TextBox:
    """One OCR text region in normalised frame coords (top-left origin)."""

    x: float
    y: float
    w: float
    h: float
    text: str = ""
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.w <= 0.0 or self.h <= 0.0:
            raise ChyronError("TextBox width/height must be positive")
        _require_unit(self.x, "TextBox x")
        _require_unit(self.y, "TextBox y")
        if self.right > 1.0 + _EPS:
            raise ChyronError("TextBox must fit within the frame")
        if self.bottom > 1.0 + _EPS:
            raise ChyronError("TextBox must fit within the frame")
        _require_unit(self.confidence, "TextBox confidence")

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2.0

    @classmethod
    def from_pixels(
        cls,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        frame_width: float,
        frame_height: float,
        text: str = "",
        confidence: float = 1.0,
    ) -> TextBox:
        """Build a normalised box from pixel coords + the frame dimensions."""
        if frame_width <= 0.0 or frame_height <= 0.0:
            raise ChyronError("frame dimensions must be positive")
        return cls(
            x=x / frame_width,
            y=y / frame_height,
            w=w / frame_width,
            h=h / frame_height,
            text=text,
            confidence=confidence,
        )


@dataclass(frozen=True)
class Band:
    """A horizontal text strip (merged words on roughly the same line)."""

    top: float
    bottom: float
    left: float
    right: float

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0


@dataclass(frozen=True)
class ChyronBand:
    """A persistent chyron: a :class:`Band` plus its ``edge`` + ``coverage``."""

    top: float
    bottom: float
    left: float
    right: float
    edge: str
    coverage: float


@dataclass(frozen=True)
class SafeZone:
    """The detected chyrons + helpers the reframe engines key off."""

    bands: tuple[ChyronBand, ...] = field(default_factory=tuple)

    @property
    def top_bands(self) -> tuple[ChyronBand, ...]:
        return tuple(b for b in self.bands if b.edge == EDGE_TOP)

    @property
    def bottom_bands(self) -> tuple[ChyronBand, ...]:
        return tuple(b for b in self.bands if b.edge == EDGE_BOTTOM)

    @property
    def has_top(self) -> bool:
        return any(b.edge == EDGE_TOP for b in self.bands)

    @property
    def has_bottom(self) -> bool:
        return any(b.edge == EDGE_BOTTOM for b in self.bands)


class OcrBackend(Protocol):
    """Heavy seam: detect text boxes at the given sample times (one per frame)."""

    def detect(
        self, media_path: str, *, sample_times: tuple[float, ...]
    ) -> tuple[tuple[TextBox, ...], ...]: ...  # pragma: no cover - Protocol stub


# --------------------------------------------------------------------------- #
# Pure detection pipeline
# --------------------------------------------------------------------------- #


def cluster_boxes_into_bands(
    boxes: Sequence[TextBox], *, vertical_gap: float = DEFAULT_VERTICAL_GAP
) -> tuple[Band, ...]:
    """Merge boxes whose vertical spans are within ``vertical_gap`` into bands."""
    if vertical_gap < 0.0:
        raise ChyronError("vertical_gap must be >= 0")
    if not boxes:
        return ()
    ordered = sorted(boxes, key=lambda b: b.y)
    first = ordered[0]
    top, bottom, left, right = first.y, first.bottom, first.x, first.right
    bands: list[Band] = []
    for box in ordered[1:]:
        if box.y <= bottom + vertical_gap:
            bottom = max(bottom, box.bottom)
            left = min(left, box.x)
            right = max(right, box.right)
        else:
            bands.append(Band(top=top, bottom=bottom, left=left, right=right))
            top, bottom, left, right = box.y, box.bottom, box.x, box.right
    bands.append(Band(top=top, bottom=bottom, left=left, right=right))
    return tuple(bands)


def classify_band(
    band: Band,
    *,
    min_width: float = DEFAULT_MIN_WIDTH,
    edge_margin: float = DEFAULT_EDGE_MARGIN,
) -> str | None:
    """Return ``EDGE_TOP``/``EDGE_BOTTOM`` for a chyron-shaped band, else ``None``."""
    if band.width < min_width:
        return None
    if band.top <= edge_margin:
        return EDGE_TOP
    if band.bottom >= 1.0 - edge_margin:
        return EDGE_BOTTOM
    return None


def _group_candidates(candidates: Sequence[tuple[str, Band]], *, y_tol: float) -> list[tuple[str, list[Band]]]:
    """Group same-edge candidate bands whose centres fall within ``y_tol``."""
    groups: list[tuple[str, list[Band]]] = []
    for edge, band in candidates:
        placed = False
        for g_edge, members in groups:
            if g_edge == edge and abs(members[0].center_y - band.center_y) <= y_tol:
                members.append(band)
                placed = True
                break
        if not placed:
            groups.append((edge, [band]))
    return groups


def _aggregate(edge: str, members: Sequence[Band], num_frames: int) -> ChyronBand:
    """Average a group's extents into one :class:`ChyronBand` with coverage."""
    n = len(members)
    return ChyronBand(
        top=sum(m.top for m in members) / n,
        bottom=sum(m.bottom for m in members) / n,
        left=min(m.left for m in members),
        right=max(m.right for m in members),
        edge=edge,
        coverage=n / num_frames,
    )


def detect_chyrons(
    per_frame_boxes: Sequence[Sequence[TextBox]],
    *,
    vertical_gap: float = DEFAULT_VERTICAL_GAP,
    min_width: float = DEFAULT_MIN_WIDTH,
    edge_margin: float = DEFAULT_EDGE_MARGIN,
    persistence: float = DEFAULT_PERSISTENCE,
    y_tol: float = DEFAULT_Y_TOL,
    min_confidence: float = 0.0,
) -> SafeZone:
    """Detect persistent top/bottom chyrons across sampled frames (pure)."""
    frames = list(per_frame_boxes)
    if not frames:
        raise ChyronError("detect_chyrons needs at least one sampled frame")
    if persistence <= 0.0 or persistence > 1.0:
        raise ChyronError("persistence must be within (0, 1]")
    if y_tol < 0.0:
        raise ChyronError("y_tol must be >= 0")
    if min_confidence < 0.0 or min_confidence > 1.0:
        raise ChyronError("min_confidence must be within [0, 1]")

    num_frames = len(frames)
    candidates: list[tuple[str, Band]] = []
    for boxes in frames:
        kept = [b for b in boxes if b.confidence >= min_confidence]
        for band in cluster_boxes_into_bands(kept, vertical_gap=vertical_gap):
            edge = classify_band(band, min_width=min_width, edge_margin=edge_margin)
            if edge is not None:
                candidates.append((edge, band))

    required = math.ceil(persistence * num_frames)
    bands = [
        _aggregate(edge, members, num_frames)
        for edge, members in _group_candidates(candidates, y_tol=y_tol)
        if len(members) >= required
    ]
    bands.sort(key=lambda c: c.top)
    return SafeZone(bands=tuple(bands))


# --------------------------------------------------------------------------- #
# Safe-zone consumption helpers (pure)
# --------------------------------------------------------------------------- #


def caption_safe_y_range(
    safezone: SafeZone,
    *,
    default_top: float = 0.0,
    default_bottom: float = 1.0,
    padding: float = DEFAULT_CAPTION_PADDING,
) -> tuple[float, float]:
    """The ``[top, bottom)`` band OUR captions may use, clear of every chyron."""
    if padding < 0.0:
        raise ChyronError("padding must be >= 0")
    if default_top >= default_bottom:
        raise ChyronError("default_top must be < default_bottom")
    top, bottom = default_top, default_bottom
    for band in safezone.bands:
        if band.edge == EDGE_TOP:
            limit = band.bottom + padding
            if limit > top:
                top = limit
        else:
            limit = band.top - padding
            if limit < bottom:
                bottom = limit
    if top >= bottom:
        raise ChyronError("chyrons leave no safe caption band")
    return (top, bottom)


def _interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Length of the overlap of ``[a0, a1)`` and ``[b0, b1)`` (0 if disjoint)."""
    span = min(a1, b1) - max(a0, b0)
    if span > 0.0:
        return span
    return 0.0


def chyron_overlap_fraction(box: Rect, safezone: SafeZone) -> float:
    """Fraction of ``box``'s area covered by any chyron band (clamped to 1.0)."""
    bx, by, bw, bh = box
    if bw <= 0.0 or bh <= 0.0:
        raise ChyronError("box must have positive area")
    area = bw * bh
    covered = 0.0
    for band in safezone.bands:
        ix = _interval_overlap(bx, bx + bw, band.left, band.right)
        iy = _interval_overlap(by, by + bh, band.top, band.bottom)
        covered += ix * iy
    return min(covered / area, 1.0)


def box_avoids_chyrons(box: Rect, safezone: SafeZone, *, max_overlap: float = 0.0) -> bool:
    """``True`` when ``box`` overlaps every chyron by at most ``max_overlap``."""
    if max_overlap < 0.0 or max_overlap > 1.0:
        raise ChyronError("max_overlap must be within [0, 1]")
    return chyron_overlap_fraction(box, safezone) <= max_overlap


def _strictly_inside(value: float, lo: float, hi: float) -> bool:
    """``True`` when ``lo < value < hi`` (an edge falling INSIDE a band)."""
    return lo < value < hi


def _band_is_sliced(crop_left: float, crop_right: float, band: ChyronBand) -> bool:
    return _strictly_inside(crop_left, band.left, band.right) or _strictly_inside(crop_right, band.left, band.right)


def crop_slices_chyrons(crop_left: float, crop_right: float, safezone: SafeZone) -> bool:
    """``True`` when the ``[crop_left, crop_right]`` pan window cuts through a bar.

    A vertical reframe keeps full height, so this only matters horizontally: a
    localised source bug is "sliced" when exactly one crop edge falls inside its
    horizontal extent (fully-inside or fully-outside is fine).
    """
    if crop_left >= crop_right:
        raise ChyronError("crop_left must be < crop_right")
    return any(_band_is_sliced(crop_left, crop_right, band) for band in safezone.bands)


# --------------------------------------------------------------------------- #
# Sampling + seam orchestration
# --------------------------------------------------------------------------- #


def default_sample_times(duration: float, *, count: int = DEFAULT_SAMPLE_COUNT) -> tuple[float, ...]:
    """Evenly spaced interior sample timestamps across ``[0, duration]``."""
    if duration <= 0.0:
        raise ChyronError("duration must be > 0")
    if count <= 0:
        raise ChyronError("count must be > 0")
    if count == 1:
        return (duration / 2.0,)
    step = duration / (count + 1)
    return tuple(step * (i + 1) for i in range(count))


def analyze_chyrons(
    media_path: str,
    backend: OcrBackend,
    *,
    sample_times: Sequence[float],
    vertical_gap: float = DEFAULT_VERTICAL_GAP,
    min_width: float = DEFAULT_MIN_WIDTH,
    edge_margin: float = DEFAULT_EDGE_MARGIN,
    persistence: float = DEFAULT_PERSISTENCE,
    y_tol: float = DEFAULT_Y_TOL,
    min_confidence: float = 0.0,
) -> SafeZone:
    """Run the OCR seam at ``sample_times`` then detect chyrons (loud on shape)."""
    times = tuple(sample_times)
    if not times:
        raise ChyronError("sample_times must be non-empty")
    frames = tuple(backend.detect(media_path, sample_times=times))
    if len(frames) != len(times):
        raise ChyronError("backend returned a frame count != sample count")
    return detect_chyrons(
        frames,
        vertical_gap=vertical_gap,
        min_width=min_width,
        edge_margin=edge_margin,
        persistence=persistence,
        y_tol=y_tol,
        min_confidence=min_confidence,
    )


__all__ = [
    "Band",
    "ChyronBand",
    "ChyronError",
    "DEFAULT_CAPTION_PADDING",
    "DEFAULT_EDGE_MARGIN",
    "DEFAULT_MIN_WIDTH",
    "DEFAULT_PERSISTENCE",
    "DEFAULT_SAMPLE_COUNT",
    "DEFAULT_VERTICAL_GAP",
    "DEFAULT_Y_TOL",
    "EDGE_BOTTOM",
    "EDGE_TOP",
    "OcrBackend",
    "Rect",
    "SafeZone",
    "TextBox",
    "analyze_chyrons",
    "box_avoids_chyrons",
    "caption_safe_y_range",
    "chyron_overlap_fraction",
    "classify_band",
    "cluster_boxes_into_bands",
    "crop_slices_chyrons",
    "default_sample_times",
    "detect_chyrons",
]
