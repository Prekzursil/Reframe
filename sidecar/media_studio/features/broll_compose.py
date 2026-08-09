"""PURE N-window b-roll compositing argv builder (v1.5 flagship #3, WU BR5).

Generalises the shipped single-overlay :mod:`brandkit` pattern from ONE still
logo to **N time-gated windows in a single ffmpeg pass** — which is the only
genuinely net-new engineering in auto-b-roll, and the design's highest-risk
surface. Everything here is a pure string/list builder: no subprocess, no disk,
no ffmpeg. The caller runs the argv through the existing drained
:func:`media_studio.ffmpeg.run` seam.

The graph, for insertion ``i`` on ffmpeg input ``i+1`` (input 0 is the clip):

``cutaway``
    ``[i+1:v]scale=W:H:force_original_aspect_ratio=increase,crop=W:H,
    setpts=PTS-STARTPTS+S/TB[bi]`` then overlaid at ``0:0``. The b-roll fills
    the frame for its window.
``pip``
    ``[i+1:v]scale=<even px>:-2,setpts=…[bi]`` then overlaid in a padded corner.

Three details that are load-bearing and easy to get wrong:

* **``setpts=PTS-STARTPTS+S/TB`` is not decoration.** ``overlay``'s ``enable``
  gate only chooses *whether* to draw; it does not re-time the overlay input. A
  b-roll left at PTS 0 would already be ``S`` seconds into itself by the moment
  its window opens. The shift puts frame 0 of the asset at second ``S`` of the
  main timeline.
* **The b-roll's audio is muted by construction, not by a filter.** Only
  ``-map [vout]`` and ``-map 0:a?`` are emitted, so the speaker's audio survives
  and no b-roll audio stream is ever selected.
* **The asset is bounded at INPUT time** (``-loop 1 -t D`` for a still,
  ``-ss srcStart -t D`` for a clip), so a 10-minute stock clip does not get
  decoded in full to fill a 4-second window.

Times are formatted to millisecond precision so the argv is byte-deterministic
and diffable in a test.

NOT covered here, stated plainly: nothing in this module proves ffmpeg accepts
the graph or renders the pixels. That is the real-ffmpeg tier (design WU BR8:
ffprobe dims/duration, an in-window frame NCC against the source asset, audio
intact) and it does NOT run on this branch.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import brandkit

#: Default export canvas (the 9:16 short this project exists to produce).
DEFAULT_CANVAS_W = 1080
DEFAULT_CANVAS_H = 1920

#: PiP inset width, as a percentage of the CANVAS width.
DEFAULT_PIP_SCALE_PCT = 34.0
#: The inset corner + padding reuse the brand-kit overlay conventions.
DEFAULT_PIP_CORNER = brandkit.DEFAULT_CORNER
DEFAULT_PIP_PADDING = brandkit.DEFAULT_PADDING

#: Asset kinds. Anything that is not ``video`` is treated as a still.
KIND_VIDEO = "video"

#: Supported window layouts (mirrors ``broll_plan.LAYOUTS``).
LAYOUTS: tuple[str, ...] = ("cutaway", "pip")

#: The final labelled video pad the muxer maps.
VOUT = "[vout]"

Insertion = Mapping[str, Any]


def _t(seconds: float) -> str:
    """Millisecond-precision time token (keeps the argv byte-deterministic)."""
    return f"{float(seconds):.3f}"


def _even(value: float) -> int:
    """The largest EVEN integer <= ``value``, floored at 2.

    libx264 rejects odd dimensions, so a PiP width must be even; ``-2`` on the
    height then lets ffmpeg keep the aspect ratio and stay even too.
    """
    n = int(value)
    n -= n % 2
    return max(n, 2)


def _duration(insertion: Insertion) -> float:
    """The window length, preferring an explicit ``duration`` over end-start."""
    if "duration" in insertion:
        return float(insertion["duration"])
    return float(insertion["end"]) - float(insertion["start"])


def build_input_args(insertions: Sequence[Insertion]) -> list[str]:
    """The ``-i`` argument groups for every b-roll asset, in insertion order.

    A still is ``-loop 1 -t D`` (one image stretched across the window); a video
    is ``-ss srcStart -t D`` (fast-seek to the asset's own offset, then take
    exactly the window's worth). Both bound the decode to the window.
    """
    args: list[str] = []
    for insertion in insertions:
        duration = _t(_duration(insertion))
        if str(insertion.get("kind", "")) == KIND_VIDEO:
            args += ["-ss", _t(insertion.get("sourceStart", 0.0)), "-t", duration]
        else:
            args += ["-loop", "1", "-t", duration]
        args += ["-i", str(insertion.get("path", ""))]
    return args


def _prepare_chain(
    insertion: Insertion,
    input_index: int,
    label: str,
    *,
    canvas_w: int,
    canvas_h: int,
    pip_corner: str,
    pip_padding: int,
    pip_scale_pct: float,
) -> tuple[str, str]:
    """The per-asset prepare chain and the ``overlay`` x:y for its layout."""
    layout = str(insertion.get("layout", "cutaway"))
    shift = f"setpts=PTS-STARTPTS+{_t(insertion['start'])}/TB"
    if layout == "cutaway":
        scale = f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h}"
        return f"[{input_index}:v]{scale},{shift}[{label}]", "0:0"
    if layout == "pip":
        if pip_scale_pct <= 0:
            raise ValueError(f"pipScalePct must be > 0, got {pip_scale_pct}")
        width = _even(canvas_w * pip_scale_pct / 100.0)
        # brandkit._corner_xy is the SINGLE source of the corner expression
        # table; calling it (rather than re-deriving the four cases) is what
        # keeps the b-roll inset and the brand logo from drifting apart. It also
        # validates the corner name for us.
        return f"[{input_index}:v]scale={width}:-2,{shift}[{label}]", brandkit._corner_xy(pip_corner, pip_padding)
    raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")


def build_filtergraph(
    insertions: Sequence[Insertion],
    *,
    canvas_w: int = DEFAULT_CANVAS_W,
    canvas_h: int = DEFAULT_CANVAS_H,
    pip_corner: str = DEFAULT_PIP_CORNER,
    pip_padding: int = DEFAULT_PIP_PADDING,
    pip_scale_pct: float = DEFAULT_PIP_SCALE_PCT,
) -> str:
    """One ``filter_complex`` compositing every window onto the main video.

    Each asset is prepared (scaled/cropped or inset, then time-shifted onto the
    main timeline) and overlaid with its OWN ``enable='between(t,S,E)'`` gate,
    chaining ``[v0] -> [v1] -> …`` so all N windows land in a single pass. The
    graph ends ``format=yuv420p`` so the result plays everywhere.
    """
    if not insertions:
        raise ValueError("compositing needs at least one insertion")
    prepares: list[str] = []
    overlays: list[str] = []
    source = "[0:v]"
    last = ""
    for index, insertion in enumerate(insertions):
        label = f"b{index}"
        chain, xy = _prepare_chain(
            insertion,
            index + 1,
            label,
            canvas_w=canvas_w,
            canvas_h=canvas_h,
            pip_corner=pip_corner,
            pip_padding=pip_padding,
            pip_scale_pct=pip_scale_pct,
        )
        prepares.append(chain)
        last = f"v{index}"
        gate = f"enable='between(t,{_t(insertion['start'])},{_t(insertion['end'])})'"
        overlays.append(f"{source}[{label}]overlay={xy}:eof_action=pass:{gate}[{last}]")
        source = f"[{last}]"
    return ";".join([*prepares, *overlays, f"[{last}]format=yuv420p{VOUT}"])


def build_broll_argv(
    clip_path: str,
    insertions: Sequence[Insertion],
    out_path: str,
    *,
    settings: Mapping[str, Any] | None = None,
    canvas_w: int = DEFAULT_CANVAS_W,
    canvas_h: int = DEFAULT_CANVAS_H,
    pip_corner: str = DEFAULT_PIP_CORNER,
    pip_padding: int = DEFAULT_PIP_PADDING,
    pip_scale_pct: float = DEFAULT_PIP_SCALE_PCT,
) -> list[str]:
    """argv compositing every b-roll window over ``clip_path`` in ONE pass.

    Input 0 is the speaker's clip and its audio is stream-copied through
    ``-map 0:a?``; inputs 1..N are the b-roll assets, whose audio is never
    mapped. ``-progress pipe:1 -nostats`` so :func:`ffmpeg.run` drains stdout
    (the proven seam — never a re-implemented drain). argv LIST only, never
    ``shell=True``.
    """
    if not clip_path:
        raise ValueError("b-roll compositing requires a clip path")
    if not out_path:
        raise ValueError("b-roll compositing requires an output path")
    if not insertions:
        raise ValueError("compositing needs at least one insertion")
    for insertion in insertions:
        if not str(insertion.get("path", "")):
            raise ValueError("every insertion needs an asset path")
        if _duration(insertion) <= 0:
            raise ValueError(f"insertion duration must be > 0, got {_duration(insertion)}")

    from .. import ffmpeg as _ffmpeg  # lazy: keep module import-light

    filter_complex = build_filtergraph(
        insertions,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        pip_corner=pip_corner,
        pip_padding=pip_padding,
        pip_scale_pct=pip_scale_pct,
    )
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        clip_path,
        *build_input_args(insertions),
        "-filter_complex",
        filter_complex,
        "-map",
        VOUT,
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]


__all__ = [
    "DEFAULT_CANVAS_H",
    "DEFAULT_CANVAS_W",
    "DEFAULT_PIP_CORNER",
    "DEFAULT_PIP_PADDING",
    "DEFAULT_PIP_SCALE_PCT",
    "KIND_VIDEO",
    "LAYOUTS",
    "VOUT",
    "build_broll_argv",
    "build_filtergraph",
    "build_input_args",
]
