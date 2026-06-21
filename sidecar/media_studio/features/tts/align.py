"""Dub alignment — the FROZEN A4 recipe (CONTRACTS.md P2 ADDENDUM, T2).

Per cue:

  1. **target duration** = ``cue.end - cue.start`` (the subtitle slot);
  2. **rate re-synth ask** — when the first synthesis misses the target by
     more than a small threshold, ask the engine to re-synthesize at
     ``rate = actual / target`` (clamped to a sane speaking range);
  3. **ffmpeg atempo, clamped ±15%** — the residual is corrected with the
     ``atempo`` audio filter, factor clamped to ``[0.85, 1.15]`` so the voice
     never sounds chipmunked/slurred;
  4. **pad silence** — when the result is still shorter than the slot, pad
     trailing silence up to the target.

Everything except the actual ffmpeg run is **pure** and unit-tested: the
clamp math, the pad math, the argv builders and the timeline/concat plan.
The ffmpeg invocation goes through the injectable ``run`` seam (defaults to
:func:`media_studio.ffmpeg.run`, which already drains stderr on a thread —
A6 lesson 2 — and takes argv LISTS only — A6 lesson 4).

The per-cue align pass also NORMALIZES the audio (sample rate / channels /
s16le) so the final concat is a trivial stdlib ``wave`` write — no soundfile,
no numpy (nothing new for ``__main__``'s native pre-import list from this
module).
"""

from __future__ import annotations

import contextlib
import os
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ... import ffmpeg
from ...util import clamp, get_logger
from .engine import (
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SAMPLE_WIDTH,
    Cue,
    TtsError,
    wav_duration_sec,
)

log = get_logger("media_studio.tts.align")

# -- FROZEN recipe constants -------------------------------------------------
#: atempo clamp: the corrected speed factor stays within ±15% (A4, frozen).
ATEMPO_MIN = 0.85
ATEMPO_MAX = 1.15
#: skip the atempo pass entirely when the factor is within this of 1.0.
ATEMPO_EPSILON = 0.01
#: re-synth ask only when the first take misses the target by more than this.
RESYNTH_THRESHOLD = 0.02
#: the re-synth rate ask is clamped to a plausible speaking-rate range.
#: CONTRACT-NOTE: A4 freezes the ±15% clamp for *atempo* only; the re-synth
#: rate bound is unpinned, so we use a conservative 0.5..2.0.
RESYNTH_RATE_MIN = 0.5
RESYNTH_RATE_MAX = 2.0

# A resynth ask: (rate, out_wav) -> path of the re-synthesized wav.
ResynthFn = Callable[[float, str], str]
# Injectable duration probe: (wav_path) -> seconds.
DurationFn = Callable[[str], float]
# Injectable ffmpeg runner (mirrors ffmpeg.run).
RunFn = Callable[..., int]


class AlignError(TtsError):
    """Alignment failed (bad ffmpeg exit, unreadable wav, format mismatch)."""


# --------------------------------------------------------------------------- #
# pure math (fully unit-tested)
# --------------------------------------------------------------------------- #
def target_duration(cue: Cue) -> float:
    """The cue's subtitle-slot duration in seconds (never negative)."""
    start = float(cue.get("start", 0.0))
    end = float(cue.get("end", 0.0))
    return max(0.0, end - start)


def resynth_rate(actual_sec: float, target_sec: float) -> float:
    """The speaking-rate to ASK the engine for on the re-synth pass.

    ``actual / target`` (audio 20% too long -> ask 1.2x faster), clamped to
    ``[RESYNTH_RATE_MIN, RESYNTH_RATE_MAX]``. Degenerate inputs -> 1.0.
    """
    if actual_sec <= 0.0 or target_sec <= 0.0:
        return 1.0
    return clamp(actual_sec / target_sec, RESYNTH_RATE_MIN, RESYNTH_RATE_MAX)


def needs_resynth(actual_sec: float, target_sec: float) -> bool:
    """Whether the first take misses the target enough to ask for a re-synth."""
    if actual_sec <= 0.0 or target_sec <= 0.0:
        return False
    return abs(actual_sec / target_sec - 1.0) > RESYNTH_THRESHOLD


def atempo_factor(actual_sec: float, target_sec: float) -> float:
    """The atempo speed factor, CLAMPED to ±15% (the frozen A4 bound).

    ``atempo=f`` makes the output ``actual / f`` seconds long, so the exact
    factor is ``actual / target``; we clamp it into ``[0.85, 1.15]``.
    Degenerate inputs -> 1.0 (no tempo change).
    """
    if actual_sec <= 0.0 or target_sec <= 0.0:
        return 1.0
    return clamp(actual_sec / target_sec, ATEMPO_MIN, ATEMPO_MAX)


def pad_seconds(adjusted_sec: float, target_sec: float) -> float:
    """Trailing silence needed to fill the slot (0 when already long enough)."""
    return max(0.0, float(target_sec) - float(adjusted_sec))


def plan_cue(actual_sec: float, target_sec: float) -> dict[str, float]:
    """The full per-cue alignment plan (pure; the recipe's steps 3+4).

    Returns ``{"atempo", "padSec", "outSec"}`` where ``atempo`` is the clamped
    factor (1.0 = skip), ``padSec`` the trailing silence, and ``outSec`` the
    resulting duration. A clamped-long cue (factor capped at 1.15 but still
    longer than the slot) yields ``outSec > target_sec`` and ``padSec == 0`` —
    the overrun is accepted rather than distorting the voice further.
    """
    factor = atempo_factor(actual_sec, target_sec)
    if abs(factor - 1.0) <= ATEMPO_EPSILON:
        factor = 1.0
    adjusted = actual_sec / factor if factor != 1.0 else actual_sec
    pad = pad_seconds(adjusted, target_sec)
    return {"atempo": factor, "padSec": pad, "outSec": adjusted + pad}


# --------------------------------------------------------------------------- #
# pure argv builder (the one ffmpeg pass: atempo + pad + normalize)
# --------------------------------------------------------------------------- #
def build_align_argv(
    in_wav: str,
    out_wav: str,
    *,
    atempo: float = 1.0,
    pad_sec: float = 0.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """ffmpeg argv for one per-cue align pass (argv LIST — A6 lesson 4).

    Applies ``atempo`` (when != 1.0) then ``apad`` (when > 0), and ALWAYS
    normalizes to ``sample_rate``/``channels``/s16le so the later concat can
    be a plain stdlib ``wave`` write. The atempo factor must already be
    clamped (a single atempo instance supports 0.5..100, our ±15% is in
    range).
    """
    filters: list[str] = []
    if abs(float(atempo) - 1.0) > ATEMPO_EPSILON:
        filters.append(f"atempo={float(atempo):.6g}")
    if pad_sec > 0.0:
        filters.append(f"apad=pad_dur={float(pad_sec):.6g}")
    argv: list[str] = [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_wav,
    ]
    if filters:
        argv += ["-af", ",".join(filters)]
    argv += [
        "-ar",
        str(int(sample_rate)),
        "-ac",
        str(int(channels)),
        "-c:a",
        "pcm_s16le",
        out_wav,
    ]
    return argv


# --------------------------------------------------------------------------- #
# per-cue orchestration (seams injected; the recipe's frozen ORDER lives here)
# --------------------------------------------------------------------------- #
def align_cue_wav(
    in_wav: str,
    target_sec: float,
    out_wav: str,
    *,
    resynth: ResynthFn | None = None,
    run: RunFn = ffmpeg.run,
    duration: DurationFn = wav_duration_sec,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the FROZEN per-cue recipe on one synthesized wav.

    target -> (re-synth ask when off) -> atempo clamp ±15% -> pad silence.
    Returns ``{"path", "outSec", "plan"}``. ``resynth(rate, path)`` is the
    engine re-synth seam (None = engine can't re-rate; skip step 2).
    """
    actual = float(duration(in_wav))
    if actual <= 0.0:
        raise AlignError(f"synthesized wav is empty/unreadable: {in_wav}")

    src = in_wav
    if resynth is not None and target_sec > 0.0 and needs_resynth(actual, target_sec):
        rate = resynth_rate(actual, target_sec)
        resynth_path = str(Path(out_wav).with_name(Path(out_wav).stem + "-resynth.wav"))
        try:
            src = str(resynth(rate, resynth_path))
            re_actual = float(duration(src))
            if re_actual > 0.0:
                actual = re_actual
            else:  # re-synth produced garbage — fall back to the first take
                src = in_wav
        except Exception as exc:  # noqa: BLE001 - re-synth is best-effort (step 2)
            log.warning("re-synth ask failed (%s); aligning the first take", exc)
            src = in_wav

    plan = plan_cue(actual, target_sec)
    argv = build_align_argv(
        src,
        out_wav,
        atempo=plan["atempo"],
        pad_sec=plan["padSec"],
        sample_rate=sample_rate,
        channels=channels,
        settings=settings,
    )
    code = run(argv)
    if code != 0:
        raise AlignError(f"ffmpeg align pass failed (exit {code}) for {src}")
    return {"path": out_wav, "outSec": plan["outSec"], "plan": plan}


# --------------------------------------------------------------------------- #
# timeline concat (pure plan + stdlib wave writer)
# --------------------------------------------------------------------------- #
def concat_plan(
    cues: Sequence[Cue],
    durations: Sequence[float],
    *,
    total_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Plan the dub track timeline: silence gaps + aligned cue audio (pure).

    Each cue is placed at its subtitle ``start``; the gap to the running
    cursor becomes a silence segment. A cue whose predecessor overran (the
    ±15% clamp accepted an overrun) gets a 0 gap — the timeline shifts
    forward rather than truncating speech. ``total_sec`` (the video length)
    appends trailing silence so the track spans the whole picture.

    Returns ``[{"type":"silence","sec":..} | {"type":"cue","index":..}, ...]``.
    """
    if len(cues) != len(durations):
        raise AlignError("concat_plan: cues and durations length mismatch")
    plan: list[dict[str, Any]] = []
    cursor = 0.0
    for i, cue in enumerate(cues):
        start = float(cue.get("start", 0.0))
        gap = max(0.0, start - cursor)
        if gap > 0.0:
            plan.append({"type": "silence", "sec": gap})
            cursor += gap
        plan.append({"type": "cue", "index": i})
        cursor += max(0.0, float(durations[i]))
    if total_sec is not None and total_sec > cursor:
        plan.append({"type": "silence", "sec": total_sec - cursor})
    return plan


def concat_wavs(
    plan: Sequence[dict[str, Any]],
    cue_paths: Sequence[str],
    out_path: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> str:
    """Materialize a :func:`concat_plan` into one WAV (stdlib ``wave`` only).

    Every cue wav must already be normalized to ``sample_rate``/``channels``/
    s16le (the align pass guarantees that); a mismatching file raises
    :class:`AlignError` instead of writing a corrupt track.
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    frame_bytes = channels * DEFAULT_SAMPLE_WIDTH
    with wave.open(str(p), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(DEFAULT_SAMPLE_WIDTH)
        out.setframerate(sample_rate)
        for seg in plan:
            if seg.get("type") == "silence":
                frames = int(round(float(seg.get("sec", 0.0)) * sample_rate))
                if frames > 0:
                    out.writeframes(b"\x00" * (frames * frame_bytes))
                continue
            index = int(seg.get("index", -1))
            if index < 0 or index >= len(cue_paths):
                raise AlignError(f"concat plan references unknown cue index {index}")
            cue_path = cue_paths[index]
            try:
                with wave.open(str(cue_path), "rb") as src:
                    if (
                        src.getframerate() != sample_rate
                        or src.getnchannels() != channels
                        or src.getsampwidth() != DEFAULT_SAMPLE_WIDTH
                    ):
                        raise AlignError(
                            f"cue wav {cue_path} is not normalized "
                            f"({src.getframerate()}Hz/{src.getnchannels()}ch/"
                            f"{src.getsampwidth() * 8}bit, expected "
                            f"{sample_rate}Hz/{channels}ch/16bit)"
                        )
                    out.writeframes(src.readframes(src.getnframes()))
            except (OSError, wave.Error, EOFError) as exc:
                raise AlignError(f"unreadable cue wav {cue_path}: {exc}") from exc
    return str(p)


def remove_quietly(path: str) -> None:
    """Best-effort cleanup of an intermediate file (never raises)."""
    with contextlib.suppress(OSError):
        os.remove(path)


__all__ = [
    "ATEMPO_MIN",
    "ATEMPO_MAX",
    "ATEMPO_EPSILON",
    "RESYNTH_THRESHOLD",
    "RESYNTH_RATE_MIN",
    "RESYNTH_RATE_MAX",
    "AlignError",
    "target_duration",
    "resynth_rate",
    "needs_resynth",
    "atempo_factor",
    "pad_seconds",
    "plan_cue",
    "build_align_argv",
    "align_cue_wav",
    "concat_plan",
    "concat_wavs",
]
