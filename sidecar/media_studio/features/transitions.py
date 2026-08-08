"""Boundary TRANSITIONS between joined clips — dissolve, fade-through, wipe, slide.

Before this module every join in Reframe was a HARD CUT: ``director_op_engines``
wired ``join`` to ffmpeg's concat *filter*, which butts clip B onto the end of
clip A with nothing in between, and there was no other way to express a boundary
treatment anywhere in the product.

The primitive here is ffmpeg's ``xfade`` (video) paired with ``acrossfade``
(audio). The one fact that makes a transition structurally different from a join:

    join      -> output duration == sum(parts)          (clips are ADJACENT)
    transition-> output duration == sum(parts) - N*D     (clips OVERLAP by D)

so a transition can never be a re-timing of a concat — it composites two clips at
the same instant, for ``D`` seconds, at each boundary.

RE-ENCODE HONESTY (the thing not to paper over): ``xfade`` must DECODE both sides
of every boundary and emit new frames, so a transition render can never be a
stream copy. That cost is exposed as a first-class, testable string —
:func:`reencode_note` — rather than a comment, so the UI can show it to the user
before they commit to the render.

Two neighbouring paths are deliberately NOT changed by this module, because both
were measured and neither is a transition:

  * ``director_op_engines.build_join_argv`` ALREADY re-encodes (concat filter,
    ``-c:v libx264`` at ``:359-362``). Adding transitions therefore regresses
    nothing there — ``join`` was never a stream copy, so "every join now
    re-encodes" was never on the table.
  * ``reframe_multispeaker.build_concat_argv`` IS a real ``-c copy`` stream-copy
    stitch (``:721-750``), but it stitches per-segment crops of ONE source clip
    inside the active-speaker reframe pass. It does not go through ``join`` and
    nothing here touches it, so that fast path stays intact.

PURE: stdlib + :mod:`media_studio.ffmpeg` binary resolution only. Every function
below is a string/number builder — no subprocess, no filesystem. The engine
adapter that runs the argv lives in ``director_op_engines.make_transition_engine``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from media_studio import ffmpeg as _ffmpeg

#: Wire/UI transition ids -> the literal ffmpeg ``xfade`` transition name.
#:
#: The keys are camelCase because they travel on the RPC wire and into the
#: renderer's TS union; the VALUES are ffmpeg's own lowercase names and must not
#: drift. Deliberately a CURATED subset of xfade's ~50 transitions: each one below
#: is a boundary treatment an editor actually reaches for, and each has been in
#: ffmpeg since ``xfade`` landed in 4.3 — so the set does not depend on a bleeding
#: -edge binary. ``dissolve`` maps to xfade's ``fade`` (the classic cross-dissolve);
#: xfade also has a *separate* filter literally named ``dissolve`` (a noise-mask
#: wipe), which is NOT what an editor means by "dissolve" — hence the remap.
TRANSITION_STYLES: dict[str, str] = {
    "dissolve": "fade",
    "fadeBlack": "fadeblack",
    "fadeWhite": "fadewhite",
    "wipeLeft": "wipeleft",
    "wipeRight": "wiperight",
    "wipeUp": "wipeup",
    "wipeDown": "wipedown",
    "slideLeft": "slideleft",
    "slideRight": "slideright",
    "circleOpen": "circleopen",
    "circleClose": "circleclose",
}

#: The style ids in a stable, sorted order (the renderer renders them in this
#: order, and a set-vs-list drift between the two sides would be invisible).
STYLE_IDS: tuple[str, ...] = tuple(sorted(TRANSITION_STYLES))

#: The style applied when an op omits ``params['style']`` — a cross-dissolve, the
#: least opinionated boundary treatment.
DEFAULT_STYLE = "dissolve"

#: Transition length when an op omits ``params['durationMs']``. 500ms is the
#: conventional dissolve length; short enough not to eat a short clip.
DEFAULT_DURATION_MS = 500
#: Floor: below ~100ms a dissolve is indistinguishable from a hard cut.
MIN_DURATION_MS = 100
#: Ceiling: 5s. Past this the transition dominates the clips it joins, and every
#: clip would have to be longer than the transition (see :func:`xfade_offsets`).
MAX_DURATION_MS = 5000

#: Output frame rate used to conform inputs when the caller does not supply one.
DEFAULT_FPS = 30


class TransitionError(ValueError):
    """Raised on an impossible transition request (unknown style, clip too short).

    A :class:`ValueError` subclass so callers may catch either. The engine adapter
    re-raises it as a ``DirectorEngineError``, which ``apply_plan`` records as the
    op's ``status="failed"`` + reason with an auto-rollback — never a silent no-op
    and never a corrupt render.
    """


def normalize_style(raw: Any) -> str:
    """Resolve a wire style id to its ffmpeg ``xfade`` transition name.

    ``None`` (the param was omitted) yields :data:`DEFAULT_STYLE`. Anything else
    that is not a known id is REJECTED rather than silently defaulted: a user who
    asked for a star wipe must not quietly receive a cross-dissolve and be left
    thinking that is what a star wipe looks like.
    """
    if raw is None:
        return TRANSITION_STYLES[DEFAULT_STYLE]
    if isinstance(raw, str) and raw in TRANSITION_STYLES:
        return TRANSITION_STYLES[raw]
    raise TransitionError(f"unknown transition style: {raw!r} (known: {', '.join(STYLE_IDS)})")


def normalize_duration_ms(raw: Any) -> int:
    """Coerce a requested transition length to a whole number of ms, CLAMPED.

    ``None`` yields :data:`DEFAULT_DURATION_MS`; a number is truncated to int and
    clamped into ``[MIN_DURATION_MS, MAX_DURATION_MS]``. A non-number is rejected.

    ``bool`` is excluded explicitly: it is an ``int`` subclass in Python, so a
    stray ``True`` would otherwise become ``1`` and then clamp up to the floor —
    a nonsense value laundered into a plausible one.
    """
    if raw is None:
        return DEFAULT_DURATION_MS
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise TransitionError(f"transition duration must be a number of milliseconds, got {raw!r}")
    return max(MIN_DURATION_MS, min(MAX_DURATION_MS, int(raw)))


def xfade_offsets(durations_sec: Sequence[float], duration_sec: float) -> list[float]:
    """Start time of each ``xfade`` boundary, in output-timeline seconds.

    ``xfade`` takes an ``offset`` measured on ITS OWN first input. Chained, that
    first input is the running output of the previous stage, which has already
    lost ``duration_sec`` per boundary consumed. So for boundary ``k``::

        offset_k = sum(durations[0..k]) - (k + 1) * duration_sec

    Every clip must be strictly LONGER than the transition: a clip that is not
    would be wholly consumed by the overlap and drive the offset negative, which
    ffmpeg renders as garbage rather than an error. Rejected loudly instead.
    """
    if len(durations_sec) < 2:
        raise TransitionError(f"a transition needs at least two clips, got {len(durations_sec)}")
    for index, clip_sec in enumerate(durations_sec):
        if clip_sec <= duration_sec:
            raise TransitionError(
                f"clip {index} ({clip_sec:.3f}s) is shorter than the {duration_sec:.3f}s "
                "transition it must host (a clip must outlast its transition)"
            )
    offsets: list[float] = []
    running = 0.0
    for index in range(len(durations_sec) - 1):
        running += durations_sec[index]
        offsets.append(running - (index + 1) * duration_sec)
    return offsets


def total_duration_sec(durations_sec: Sequence[float], duration_sec: float) -> float:
    """Output duration: the sum of the parts MINUS one overlap per boundary.

    This is the single strongest non-no-op proof that a transition ran rather than
    a concat: concat sums, a transition sums-then-subtracts.
    """
    return sum(durations_sec) - max(0, len(durations_sec) - 1) * duration_sec


def video_out_label(count: int) -> str:
    """Filtergraph label carrying the final composited VIDEO for ``count`` inputs."""
    return f"[vx{count - 1}]"


def audio_out_label(count: int) -> str:
    """Filtergraph label carrying the final crossfaded AUDIO for ``count`` inputs."""
    return f"[ax{count - 1}]"


def _conform_chain(index: int, width: int, height: int, fps: int) -> str:
    """Per-input conform stage: geometry, SAR, frame rate, pixel format.

    ``xfade`` REFUSES inputs whose size, SAR, frame rate or pixel format differ —
    it is a per-pixel blend of two frames, so they must be the same shape. This
    stage is therefore not cosmetic: it is what lets a transition join arbitrary
    clips at all, the same tolerance ``build_join_argv``'s concat filter has.
    Letterboxes rather than distorts (``force_original_aspect_ratio=decrease`` +
    centred ``pad``), so a 4:3 insert keeps its geometry instead of being stretched.
    """
    return (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:-1:-1:color=black,setsar=1,fps={fps},format=yuv420p[tv{index}]"
    )


def build_transition_filtergraph(
    *,
    count: int,
    xfade_name: str,
    duration_sec: float,
    offsets: Sequence[float],
    width: int,
    height: int,
    fps: int,
) -> str:
    """Build the full ``-filter_complex`` graph: conform -> xfade chain -> acrossfade chain.

    Video and audio are chained in LOCKSTEP — one ``xfade`` and one ``acrossfade``
    per boundary, both shortening their stream by ``duration_sec`` — so A/V stay in
    sync across every boundary. ``acrossfade`` needs no offset: it always crossfades
    the end of its first input with the start of its second, which is exactly the
    junction ``xfade`` is treating.

    Known scope limit, stated here rather than in a trailing caveat: for
    ``fadeBlack``/``fadeWhite`` the VIDEO dips through a colour while the AUDIO
    still cross-fades directly. A true fade-through-silence would need a separate
    ``afade`` out/in pair; that is not built. Settling experiment: render a
    ``fadeBlack`` and confirm the audio at the midpoint is a blend of both clips
    rather than silence.
    """
    if len(offsets) != count - 1:
        raise TransitionError(f"offset count {len(offsets)} does not match {count} inputs (need {count - 1})")
    stages = [_conform_chain(index, width, height, fps) for index in range(count)]
    for index, offset in enumerate(offsets):
        video_in = "[tv0]" if index == 0 else f"[vx{index}]"
        stages.append(
            f"{video_in}[tv{index + 1}]xfade=transition={xfade_name}:"
            f"duration={duration_sec:.3f}:offset={offset:.3f}[vx{index + 1}]"
        )
    for index in range(count - 1):
        audio_in = "[0:a]" if index == 0 else f"[ax{index}]"
        stages.append(f"{audio_in}[{index + 1}:a]acrossfade=d={duration_sec:.3f}:c1=tri:c2=tri[ax{index + 1}]")
    return ";".join(stages)


def build_transition_argv(
    inputs: Sequence[str],
    out_path: str,
    *,
    style: Any,
    duration_ms: Any,
    durations_sec: Sequence[float],
    width: int,
    height: int,
    fps: int = DEFAULT_FPS,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """argv that joins ``inputs`` with a transition at every boundary.

    ``durations_sec`` must carry the probed duration of EVERY input (the offset
    math is meaningless without them). Encodes H.264/AAC at CRF 18 with an explicit
    ``-preset``/``-pix_fmt`` — the same rate-control discipline
    ``reframe_multispeaker.build_segment_argv`` uses, deliberately NOT the bare
    ``-c:v libx264`` (default CRF 23, no floor) that the older Director builders
    pass, because a transition is by definition a generational re-encode and should
    not also silently drop quality.
    """
    if len(durations_sec) != len(inputs):
        raise TransitionError(f"need one duration per clip: {len(durations_sec)} durations for {len(inputs)} clips")
    xfade_name = normalize_style(style)
    duration_sec = normalize_duration_ms(duration_ms) / 1000.0
    offsets = xfade_offsets(durations_sec, duration_sec)
    graph = build_transition_filtergraph(
        count=len(inputs),
        xfade_name=xfade_name,
        duration_sec=duration_sec,
        offsets=offsets,
        width=width,
        height=height,
        fps=fps,
    )
    argv = [_ffmpeg.ffmpeg_path(settings), "-hide_banner", "-nostdin", "-y"]
    for path in inputs:
        argv += ["-i", path]
    argv += [
        "-filter_complex",
        graph,
        "-map",
        video_out_label(len(inputs)),
        "-map",
        audio_out_label(len(inputs)),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        out_path,
    ]
    return argv


def reencode_note(count: int) -> str:
    """The user-facing cost disclosure for a transition render.

    A first-class, asserted string rather than a source comment, because the cost
    is the user's to accept: ``xfade`` composites two decoded frames per boundary,
    so this render cannot be a stream copy under any settings.
    """
    if count < 2:
        raise TransitionError(f"a transition needs at least two clips, got {count}")
    boundaries = count - 1
    word = "boundary" if boundaries == 1 else "boundaries"
    return (
        f"Transitions re-encode. xfade decodes and recomposites both clips at each of the "
        f"{boundaries} transition {word}, so unlike a plain join this render can never be a "
        f"stream copy — and the result is shorter than the sum of the clips by one overlap "
        f"at every {word if boundaries == 1 else 'boundary'}."
    )


__all__ = [
    "DEFAULT_DURATION_MS",
    "DEFAULT_FPS",
    "DEFAULT_STYLE",
    "MAX_DURATION_MS",
    "MIN_DURATION_MS",
    "STYLE_IDS",
    "TRANSITION_STYLES",
    "TransitionError",
    "audio_out_label",
    "build_transition_argv",
    "build_transition_filtergraph",
    "normalize_duration_ms",
    "normalize_style",
    "reencode_note",
    "total_duration_sec",
    "video_out_label",
    "xfade_offsets",
]
