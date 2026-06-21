"""Auto punch-in zoom — pure ffmpeg filter-string builder (P4 §8b / C16).

OpusClip-style "auto zoom" keeps the frame subtly drifting inward (a slow Ken
Burns push) and adds a quick **punch-in** at emphasis beats so a line lands with
energy. This module computes that as a **pure** ffmpeg ``zoompan`` expression
from the clip's cues alone — NO subprocess, NO randomness — so it is fully unit
testable and composes with the rest of the export pipeline through the existing
drained :func:`ffmpeg.run` seam (C16 — we do NOT re-implement a joined drain).

Beat source (v1, SHIPPABLE — PLAN-P4 C16):
    sentence-starts taken from the cues handed to the export stage. A cue whose
    text begins a sentence (first cue, or a cue right after one ending in
    sentence-final punctuation) marks a punch-in beat.

Audio-RMS beats (``astats`` / ``silencedetect`` peaks) are an OPTIONAL phase-2
upgrade. The seam for them is :func:`build_zoom_filter`'s ``beats`` parameter:
a caller that has computed RMS-peak timestamps passes them directly and the
sentence-start derivation is bypassed. v1 never blocks on that pass.

The output is a single ``zoompan=...`` filter string suitable for ffmpeg's
``-vf`` / ``-filter:v``. It is built against the clip-local timeline (t=0 at the
clip's first frame) — the orchestrator runs zoom on the REFRAMED clip, which is
already re-based to t=0, so beat times must likewise be clip-local.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# A Cue is the contract's ``{index:int, start:float, end:float, text:str}``; we
# accept it duck-typed as a Mapping so this module stays import-light (mirrors
# emphasis.CueLike / caption.CueLike).
CueLike = Mapping[str, Any]

# --------------------------------------------------------------------------- #
# tunables (FROZEN — keep the look deterministic across runs)
# --------------------------------------------------------------------------- #
#: Output frame rate the zoompan expression assumes for the ``d``/``fps`` math.
#: 30 fps matches the §4 vertical export pipeline.
DEFAULT_FPS = 30

#: The baseline slow push: total extra zoom accrued over the whole clip on top of
#: 1.0 (e.g. 0.06 = a gentle 6% drift in). Kept subtle so it never looks like a
#: crash-zoom by itself.
SLOW_ZOOM_TOTAL = 0.06

#: A punch-in adds this much zoom on top of the slow push, ...
PUNCH_ZOOM = 0.08

#: ... ramped in over this many seconds (a quick snap, then it relaxes back into
#: the slow drift). Short enough to read as a "punch", long enough to avoid a
#: single-frame jump.
PUNCH_RAMP_SEC = 0.35

#: Hard ceiling on the instantaneous zoom so the crop never starves the frame.
MAX_ZOOM = 1.5

#: Sentence-final punctuation: a cue that ENDS with one of these marks the NEXT
#: cue as a sentence start (a punch beat).
_SENTENCE_END = (".", "!", "?", "…")


def _is_sentence_end(text: str) -> bool:
    """Whether ``text`` ends a sentence (trailing sentence-final punctuation)."""
    stripped = str(text or "").rstrip().rstrip("\"'")
    return bool(stripped) and stripped.endswith(_SENTENCE_END)


def sentence_start_beats(cues: Sequence[CueLike], *, source_start: float = 0.0) -> list[float]:
    """Clip-local beat times (seconds) at every sentence start in ``cues``.

    A beat is the ``start`` of the first cue and of any cue that immediately
    follows a cue ending in sentence-final punctuation. Times are re-based to the
    clip's t=0 by subtracting ``source_start`` (the cues arrive in original-video
    time, like captions), clamped to >= 0, de-duplicated, and sorted. Pure +
    deterministic — the v1 beat source (PLAN-P4 C16).
    """
    beats: list[float] = []
    prev_ended_sentence = True  # the first cue always starts a "sentence"
    for cue in cues or []:
        text = str(cue.get("text", "") or "")
        if not text.strip():
            continue
        if prev_ended_sentence:
            try:
                local = float(cue.get("start", 0.0)) - float(source_start)
            except (TypeError, ValueError):
                local = 0.0
            beats.append(max(0.0, local))
        prev_ended_sentence = _is_sentence_end(text)
    # de-dup (stable) + sort: identical beats collapse so the expression stays lean.
    seen: set[float] = set()
    unique: list[float] = []
    for b in sorted(beats):
        key = round(b, 3)
        if key not in seen:
            seen.add(key)
            unique.append(b)
    return unique


def _slow_zoom_expr(total_sec: float, fps: int) -> str:
    """The base slow-push term: 1.0 + SLOW_ZOOM_TOTAL * (elapsed / total).

    ``on`` is zoompan's output-frame counter; ``elapsed = on / fps``. When the
    duration is unknown / non-positive the push is omitted (constant 1.0 base).
    """
    if total_sec <= 0 or fps <= 0:
        return "1"
    per_frame = SLOW_ZOOM_TOTAL / (total_sec * fps)
    # 1 + per_frame*on  — a linear drift from 1.0 to ~1+SLOW_ZOOM_TOTAL.
    return f"1+{per_frame:.10f}*on"


def _punch_term(beat: float, fps: int) -> str:
    """One additive punch term: PUNCH_ZOOM ramped in over PUNCH_RAMP_SEC at ``beat``.

    Implemented in ffmpeg expr language on the frame counter ``on``:
      t  = on/fps                                  (current time, seconds)
      dt = t - beat                                (time since the beat)
      f  = clip(dt / PUNCH_RAMP_SEC, 0, 1)         (0 before the beat -> 1 ramped)
    The term contributes ``PUNCH_ZOOM * f`` so the zoom snaps in then holds; the
    slow-push base keeps drifting underneath. (A held punch reads cleaner than a
    decaying one for short OpusClip-style clips.)
    """
    ramp = max(PUNCH_RAMP_SEC, 1.0 / max(fps, 1))
    # gte(t,beat) gates the term to AFTER the beat; min(...) ramps it to 1.
    return f"{PUNCH_ZOOM:.6f}*gte(on/{fps},{beat:.3f})*min((on/{fps}-{beat:.3f})/{ramp:.3f}\\,1)"


def build_zoom_expr(
    *,
    duration_sec: float,
    beats: Sequence[float],
    fps: int = DEFAULT_FPS,
) -> str:
    """The full clip-local ``z`` expression for zoompan (pure string).

    ``z = min(MAX_ZOOM, slow_push + sum(punch_terms))``. With no beats it is just
    the slow push (subtle Ken-Burns); each beat adds a quick punch-in. The whole
    thing is clamped to :data:`MAX_ZOOM` so the crop never over-zooms.
    """
    base = _slow_zoom_expr(duration_sec, fps)
    terms = [base]
    for beat in beats or []:
        try:
            b = float(beat)
        except (TypeError, ValueError):
            continue
        if b < 0:
            continue
        terms.append(_punch_term(b, fps))
    summed = "+".join(terms)
    return f"min({summed}\\,{MAX_ZOOM})"


def build_zoom_filter(
    *,
    width: int,
    height: int,
    duration_sec: float,
    beats: Sequence[float] | None = None,
    cues: Sequence[CueLike] | None = None,
    source_start: float = 0.0,
    fps: int = DEFAULT_FPS,
) -> str:
    """Build the full ``zoompan=...`` filter string for the auto punch-in zoom.

    Beat resolution (PLAN-P4 C16): an explicit ``beats`` list (e.g. phase-2
    audio-RMS peaks) wins; otherwise beats are derived from ``cues`` via
    :func:`sentence_start_beats` (the v1 sentence-start source). With neither,
    the filter is just the subtle slow push.

    The expression keeps the output frame the SAME size (``s=WxH``) and centers
    the zoom (``x``/``y`` track the zoom so the crop stays centered), ``d=1`` so
    each input frame maps to one output frame, ``fps`` fixes the timebase the
    ``on``-based ``z`` expression assumes. Pure: returns a string only — the
    orchestrator runs it through the drained :func:`ffmpeg.run` (C16).
    """
    if width <= 0 or height <= 0:
        raise ValueError("zoom filter requires positive width/height")
    resolved_beats: list[float]
    if beats is not None:
        resolved_beats = [float(b) for b in beats]
    elif cues is not None:
        resolved_beats = sentence_start_beats(cues, source_start=source_start)
    else:
        resolved_beats = []
    z_expr = build_zoom_expr(duration_sec=duration_sec, beats=resolved_beats, fps=fps)
    # x/y keep the zoom centered: as z grows the visible window shrinks toward the
    # frame center (iw/2 - (iw/zoom)/2). 'd=1' = one output frame per input frame.
    return (
        f"zoompan=z='{z_expr}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={int(width)}x{int(height)}:fps={int(fps)}"
    )


def build_zoom_argv(
    in_path: str,
    out_path: str,
    *,
    width: int,
    height: int,
    duration_sec: float,
    beats: Sequence[float] | None = None,
    cues: Sequence[CueLike] | None = None,
    source_start: float = 0.0,
    fps: int = DEFAULT_FPS,
    settings: Mapping[str, Any] | None = None,
) -> list[str]:
    """ffmpeg argv applying the auto punch-in zoom (argv LIST only, no shell).

    Re-encodes the video with the :func:`build_zoom_filter` ``-filter:v`` and
    copies the audio (zoom is a video-only transform). ``-progress pipe:1
    -nostats`` so :func:`ffmpeg.run` drains stdout (C16 — reuse the proven seam).
    """
    from .. import ffmpeg as _ffmpeg  # lazy: keep module import-light

    vf = build_zoom_filter(
        width=width,
        height=height,
        duration_sec=duration_sec,
        beats=beats,
        cues=cues,
        source_start=source_start,
        fps=fps,
    )
    return [
        _ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-filter:v",
        vf,
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
    "DEFAULT_FPS",
    "MAX_ZOOM",
    "PUNCH_RAMP_SEC",
    "PUNCH_ZOOM",
    "SLOW_ZOOM_TOTAL",
    "build_zoom_argv",
    "build_zoom_expr",
    "build_zoom_filter",
    "sentence_start_beats",
]
