"""ClaudeShortsReframeEngine — engine 2 of ReframeEngine (CONTRACTS.md A4).

Port of **Route A** from the vendored claude-shorts project (MIT, pinned
``a369fad``): ``scripts/compute_reframe.py`` + ``ENGINE1_BUILD_RECIPE.md``.
Route A's verdict: claude-shorts' own renderer applies the crop in Remotion
(node/Chrome); the node-free path is to compute the crop RECTANGLE with the
Python detection logic and then apply it ffmpeg-side with ONE ``crop`` +
``scale`` pass. That is exactly what this engine does — fully **in-sidecar**,
no WSL, no node, no Remotion:

  1. probe the source geometry/duration (ffprobe, argv list);
  2. sample ~one frame per second and locate the SPEAKER's horizontal center
     with a fallback chain so the crop never collapses to a center crop the
     moment a face turns away: **mediapipe** face detection when importable (A6:
     it MUST be pre-imported by ``__main__._preimport_native_modules``; see
     :data:`NATIVE_MODULES_FOR_PREIMPORT`) or an **OpenCV haar**-cascade face,
     then a **HOG person/body** detector for profile/turned shots, then **motion
     saliency** (inter-frame diff centroid) as a last resort, else — only when
     all three find nothing across the clip — a plain **center** crop;
  3. heavily smooth the per-window centers with a zero-phase (forward+backward)
     EMA so the crop FOLLOWS the speaker steadily with no frame-to-frame jitter,
     and convert them to finely-spaced crop-x keyframes;
  4. apply ONE ffmpeg pass: ``crop=W:H:'x(t)':Y,scale=1080:1920`` — a static x
     ONLY when the subject genuinely never moves, otherwise an interpolated
     piecewise-linear ``x(t)`` (no stepped teleports), h264 at 1080x1920 for 9:16.

A6 hard lessons honoured here:
  * native modules (mediapipe, cv2) are imported ONLY inside job-time function
    bodies and are flagged for ``__main__`` pre-import (deadlock proven);
  * the encode subprocess runs through :func:`media_studio.ffmpeg.run`, which
    drains stderr on a thread (the proven 29-min freeze otherwise); the small
    frame-extraction/probe calls use ``subprocess.run(capture_output=True)``
    which also drains both pipes;
  * failures raise :class:`ClaudeShortsReframeError`, which the shortmaker job
    surfaces via the job.done error payload;
  * every subprocess call is an **argv list** (never ``shell=True``).

This module deliberately does NOT import ``features.reframe`` (the verthor
adapter + engine registry) — the registry imports US, and a cycle would break
both. The few lines of aspect math are duplicated and kept in sync with the
contract's pinned 1080x1920 output.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import shutil
import statistics
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from typing import Any

from .. import ffmpeg
from ..util import get_logger
from . import aspect as _aspect

_log = get_logger("media_studio.reframe_claudeshorts")

# Contract (A4 / base §4): vertical 9:16 output at exactly this resolution, h264.
DEFAULT_ASPECT = "9:16"
OUT_WIDTH = 1080
OUT_HEIGHT = 1920

# Sampling/smoothing knobs. The original Route A used 5 samples per clip; we
# sample ~1/sec so the smoothed track has enough resolution to FOLLOW a speaker
# steadily (a coarse 2s window aliased fast pans into visible teleports).
WINDOW_SEC = 1.0
MAX_WINDOWS = 90
# Heavy temporal EMA: a LOW alpha makes the crop follow the speaker steadily
# with no frame-to-frame jitter (0=frozen, 1=no smoothing). 0.35 was visibly
# jittery on real footage; ~0.15 tracks the subject without chasing detector
# noise. Smoothing is applied forward+backward (zero-phase) so the steady track
# has no directional lag bias toward the start of the clip.
SMOOTH_ALPHA = 0.15
# Outlier-robust median pre-filter window (odd, samples). A single-frame detector
# spike — a stray left detection at the clip start, a mis-detect on a head turn —
# would otherwise seed the zero-phase EMA and drag the OPENING crop off the steady
# subject (empty-studio frames). A length-3 median replaces each lone spike with
# its neighbours' value BEFORE the EMA, while leaving a constant track and a
# sustained step untouched. 1 disables it.
MEDIAN_WINDOW = 3
# Keyframes are kept finely (small min-delta) so x(t) is a smooth piecewise-
# linear pan, NOT a few coarse steps that teleport between sample windows.
KEYFRAME_MIN_DELTA_FRAC = 0.004
# "Fully static" means the subject GENUINELY never moves across the whole clip;
# only then do we collapse to one fixed crop. Kept tight so a speaker who drifts
# is tracked (not frozen at an average x that can land off them).
STATIC_EPSILON_FRAC = 0.01
# A track is only trusted when a subject was located in at least this fraction of
# the sampled windows; below it the detector is too unreliable to track on, so we
# keep the centered crop instead of chasing a couple of stray hits.
MIN_SUBJECT_HIT_FRAC = 0.15
# WU PHASE-5 WIDE-SHOT FRAMING — DOMINANT/ACTIVE single-speaker selection. In a
# wide / two-shot we lock the crop onto ONE subject (the featured speaker), never
# the empty gap between two people. Two subjects whose face/person size is within
# this fraction of the largest count as the SAME size — a symmetric two-shot — so
# the ACTIVE speaker (more mouth/gesture motion) wins the tie instead of an
# arbitrary largest-by-a-pixel pick. A real size gap (one person clearly closer)
# is honoured outright: the larger/closer subject is the dominant one.
DOMINANT_SIZE_TIE_FRAC = 0.2

# Honest V1 capability copy (surfaced in README + docs/ROADMAP.md). V1 frames the
# dominant/active SINGLE speaker even in a wide/two-shot; automatic multi-speaker
# SWITCHING (cutting between people as they talk) is a V2 feature.
SINGLE_SPEAKER_CAPABILITY_NOTE = (
    "V1 follows a single speaker: in a wide or two-shot the crop locks onto the "
    "dominant/active speaker (the largest, most-active face/person) and tracks "
    "them smoothly — it never shows an empty studio or the gap between two people. "
    "Automatic multi-speaker switching (cutting between people as they talk) is a "
    "V2 feature."
)

# A6 LESSON 1 — PRE-IMPORT FLAG (NON-NEGOTIABLE): these native C-extension
# modules are first used INSIDE a job thread by this engine. They MUST be added
# to ``__main__._preimport_native_modules`` (cv2 already is; mediapipe is NEW —
# see WIRING-T4B.md). A first import on a job thread deadlocks the sidecar.
NATIVE_MODULES_FOR_PREIMPORT: tuple[str, ...] = ("mediapipe", "cv2")

# Injectable seams.
Runner = Callable[..., int]  # ffmpeg.run-shaped
SubprocessRunner = Callable[..., Any]  # subprocess.run-shaped
Prober = Callable[[str], tuple[int, int, float]]  # path -> (w, h, durationSec)
# path, timestamps -> [(t, cx_norm)] subject-center samples (cx in 0..1)
Detector = Callable[[str, Sequence[float]], list[tuple[float, float]]]


class ClaudeShortsReframeError(RuntimeError):
    """Raised when the claudeshorts reframe cannot probe or encode."""


class ClaudeShortsBackendUnavailableError(ClaudeShortsReframeError):
    """No native subject-tracking backend (cv2/mediapipe) is importable.

    This is a SETUP/PROVISIONING failure, NOT a per-clip event: without OpenCV
    the engine cannot decode frames to track a speaker at all. It is raised as an
    EXPLICIT signal (never a silent ``center`` fallback) so the job surfaces an
    actionable "install opencv-python/mediapipe" error rather than silently
    degrading every clip to a dumb center crop (WU-3 NO-SILENT-FALLBACK).
    """


# Per-clip "speaker tracking was lost" signal (a RUNTIME degrade, distinct from
# the setup error above). Surfaced via the ``on_notice`` sink so the UI can show a
# real/degraded badge instead of the degrade being swallowed into a center crop.
REFRAME_DEGRADED_NOTICE = "reframe.degraded"


# Appended to a degrade message when the active detector backend is the weaker
# OpenCV/haar face detector because the preferred MODEL (MediaPipe) is not
# installed. NO-SILENT-FALLBACK: a center crop caused by a missing model must
# NAME that model (actionable) rather than reading as an unexplained "no subject".
MEDIAPIPE_MISSING_HINT = (
    " MediaPipe is not installed — the app fell back to lower-quality OpenCV face "
    "detection, which often can't hold turned or profile faces; install mediapipe "
    "for accurate speaker tracking."
)


def make_degraded_notice(reason: str, *, backend: str | None = None) -> dict[str, str]:
    """Build the typed per-clip degraded notice (``{type, message, reason}``).

    ``message`` is the human line a job surfaces via ``job.progress``; ``reason``
    is the specific cause (a detector error, or no trackable subject) so the UI /
    logs can explain WHY the crop fell back to center. When ``backend == "haar"``
    the message also NAMES the missing MediaPipe model (:data:`MEDIAPIPE_MISSING_HINT`)
    so a model-unavailability degrade is surfaced loudly, never silently reduced to
    "no subject" (NO-SILENT-FALLBACK).
    """
    message = f"reframe: speaker tracking unavailable ({reason}) — used center crop"
    if backend == "haar":
        message += MEDIAPIPE_MISSING_HINT
    return {
        "type": REFRAME_DEGRADED_NOTICE,
        "message": message,
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# aspect handling (kept in sync with features.reframe — see module docstring)
# --------------------------------------------------------------------------- #
def _parse_aspect(aspect: str) -> tuple[int, int]:
    """Parse ``"W:H"`` (or ``"WxH"``) into a positive ``(w, h)`` int tuple.

    Thin alias over the shared aspect registry (kept for the engine's local name
    and the ``crop_size`` / ``centered_crop`` call sites).
    """
    return _aspect.parse_aspect(aspect)


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """(width, height) of the encode target for ``aspect`` via the shared registry.

    WU R3: 9:16 -> 1080x1920, 1:1 -> 1080x1080, 4:5 -> 1080x1350; any other
    positive ratio falls back to the original "fit the long edge to 1920" math.
    """
    return _aspect.output_dimensions(aspect)


# --------------------------------------------------------------------------- #
# crop-rect math (pure — ported from compute_reframe.py's compute_crop_*)
# --------------------------------------------------------------------------- #
def crop_size(src_w: int, src_h: int, aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """The largest ``aspect``-shaped crop that fits inside ``src_w`` x ``src_h``.

    For the canonical landscape->9:16 case this is the full source height and
    ``round(h * 9/16)`` width (e.g. 1280x720 -> 405x720), exactly Route A.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"source dimensions must be positive, got {src_w}x{src_h}")
    aw, ah = _parse_aspect(aspect)
    want_w = src_h * (aw / ah)
    if want_w <= src_w:
        return max(1, int(round(want_w))), int(src_h)
    return int(src_w), max(1, int(round(src_w * (ah / aw))))


def centered_crop(src_w: int, src_h: int, aspect: str = DEFAULT_ASPECT) -> dict[str, int]:
    """A centered ``{x, y, w, h}`` crop rect (the no-subject fallback)."""
    w, h = crop_size(src_w, src_h, aspect)
    return {"x": (src_w - w) // 2, "y": (src_h - h) // 2, "w": w, "h": h}


def crop_x_for_center(cx_norm: float, crop_w: int, src_w: int) -> int:
    """Crop-x that centers the crop window on a normalized subject center.

    ``cx_norm`` is 0..1 across the source width. The result is clamped into
    ``[0, src_w - crop_w]`` so the window never leaves the frame.
    """
    x = int(round(float(cx_norm) * src_w - crop_w / 2.0))
    return max(0, min(x, max(0, src_w - crop_w)))


# --------------------------------------------------------------------------- #
# dominant / active single-speaker selection (pure — the wide-shot fix core)
# --------------------------------------------------------------------------- #
def select_dominant(candidates: Sequence[tuple[float, float, float]]) -> float | None:
    """Pick the DOMINANT subject's normalized horizontal center (the wide-shot fix).

    ``candidates`` is a sequence of ``(cx, size, activity)`` for every face/person
    detected in ONE frame: ``cx`` is the normalized horizontal center (0..1),
    ``size`` the subject's relative prominence (face/person area — bigger = closer
    = more dominant), and ``activity`` a motion/active-speaker score used ONLY to
    break a near-size tie. Returns the chosen subject's ``cx``, or ``None`` when
    there are no candidates.

    Selection rule (WU PHASE-5): the LARGEST subject wins outright; when several
    subjects are within :data:`DOMINANT_SIZE_TIE_FRAC` of the largest (a symmetric
    two-shot), the most-ACTIVE one wins (the talking head), then larger size as a
    final, deterministic tie-break (first candidate on an exact tie — the crop
    never flips frame-to-frame on a coin-flip). This is what keeps the crop on the
    featured single speaker in a wide/two-shot instead of the empty gap between
    two people. Choosing exactly ONE subject per frame (never a blend / centroid
    of several) is the structural guard against the empty-studio / edge-cut bug.
    """
    cands = list(candidates)
    if not cands:
        return None
    largest = max(float(c[1]) for c in cands)
    # A real size gap is honoured; only a near-tie opens the activity tie-break.
    # ``largest <= 0`` (degenerate zero-area candidates) -> everyone is a
    # contender and activity (then size) decides.
    threshold = largest * (1.0 - DOMINANT_SIZE_TIE_FRAC) if largest > 0.0 else 0.0
    contenders = [c for c in cands if float(c[1]) >= threshold]
    best = max(contenders, key=lambda c: (float(c[2]), float(c[1])))
    return float(best[0])


# --------------------------------------------------------------------------- #
# track smoothing + keyframes (pure)
# --------------------------------------------------------------------------- #
def _ema_forward(centers: Sequence[float], alpha: float) -> list[float]:
    """One causal EMA pass: ``out[i] = out[i-1] + alpha*(centers[i]-out[i-1])``."""
    out: list[float] = []
    prev: float | None = None
    for c in centers:
        c = float(c)
        prev = c if prev is None else prev + float(alpha) * (c - prev)
        out.append(prev)
    return out


def median_prefilter(centers: Sequence[float], window: int = MEDIAN_WINDOW) -> list[float]:
    """Sliding-window median over ``centers`` (odd ``window``; edges shrink).

    Replaces each lone single-frame spike with its neighbours' median so detector
    outliers cannot seed the EMA. A constant track and a sustained step are both
    returned unchanged (the median of either is the level itself). At the ends the
    window shrinks to the available samples (no out-of-range clamp). ``window<=1``
    (or fewer than 2 samples) is the identity.
    """
    vals = [float(c) for c in centers]
    n = len(vals)
    w = int(window)
    if w <= 1 or n < 2:
        return vals
    w = min(w, n)  # window can't exceed the track length
    half = w // 2
    out: list[float] = []
    for i in range(n):
        # Keep a FULL odd window even at the ends by shifting it inward (forward
        # at the start, backward at the end). A symmetric shrink would leave an
        # edge sample with only one neighbour, so a lone spike AT the first/last
        # index — the opening crop, the worst case — would survive; shifting the
        # window inward lets the steady neighbours outvote the edge spike.
        lo = min(max(0, i - half), n - w)
        out.append(statistics.median(vals[lo : lo + w]))
    return out


def smooth_centers(centers: Sequence[float], alpha: float = SMOOTH_ALPHA) -> list[float]:
    """Heavy zero-phase EMA smoothing of subject centers (outlier-robust).

    A single causal EMA both damps jitter AND lags the true subject (the crop
    trails the speaker). We instead run the EMA forward, then backward over the
    result, and average the two — a zero-phase (forward+backward) filter that
    removes the directional lag while keeping the same low ``alpha`` heavy
    damping. With a LOW alpha (~0.15) the crop FOLLOWS the speaker steadily with
    no frame-to-frame jitter; a constant input is returned unchanged.

    A length-:data:`MEDIAN_WINDOW` median pre-filter runs FIRST so a lone detector
    spike (e.g. a stray left detection at the clip start) cannot seed the EMA and
    drag the opening crop off the steady subject.
    """
    fwd = _ema_forward(median_prefilter(centers), alpha)
    bwd = list(reversed(_ema_forward(list(reversed(fwd)), alpha)))
    return [(f + b) / 2.0 for f, b in zip(fwd, bwd, strict=False)]


def window_timestamps(
    duration: float,
    window_sec: float = WINDOW_SEC,
    max_windows: int = MAX_WINDOWS,
) -> list[float]:
    """Window-center sample timestamps across the clip (Route A's spread).

    One sample per ~``window_sec`` window, capped at ``max_windows``; each
    timestamp is the window's midpoint: ``duration * (i + 0.5) / n``.
    """
    d = max(0.0, float(duration))
    if d <= 0.0:
        return [0.0]
    n = int(min(max_windows, max(1, math.ceil(d / float(window_sec)))))
    return [round(d * (i + 0.5) / n, 3) for i in range(n)]


def build_keyframes(timestamps: Sequence[float], xs: Sequence[int]) -> list[dict[str, float]]:
    """Pair timestamps with crop-x positions into ``{"t", "x"}`` keyframes."""
    return [{"t": float(t), "x": int(x)} for t, x in zip(timestamps, xs, strict=False)]


def dedupe_keyframes(keyframes: list[dict[str, float]], min_delta: float) -> list[dict[str, float]]:
    """Drop middle keyframes that moved less than ``min_delta`` px (Route A)."""
    if len(keyframes) <= 2:
        return list(keyframes)
    filtered = [keyframes[0]]
    for kf in keyframes[1:-1]:
        if abs(kf["x"] - filtered[-1]["x"]) > min_delta:
            filtered.append(kf)
    filtered.append(keyframes[-1])
    return filtered


def is_static(keyframes: Sequence[dict[str, float]], epsilon: float) -> bool:
    """True when the whole track stays within ``epsilon`` px — use a static crop."""
    if not keyframes:
        return True
    xs = [k["x"] for k in keyframes]
    return (max(xs) - min(xs)) <= epsilon


# --------------------------------------------------------------------------- #
# ffmpeg argv builders (pure — no subprocess)
# --------------------------------------------------------------------------- #
def build_crop_x_expr(static_x: int, keyframes: Sequence[dict[str, float]] | None = None) -> str:
    """The ``crop`` filter's x argument: a constant, or a piecewise-linear x(t).

    With <2 keyframes the expression is just the static integer. Otherwise it
    is nested ``if(lt(t,t1), lerp, ...)`` segments — linear interpolation
    between consecutive keyframes, holding the last x afterwards. A keyframe at
    t=0 is prepended (holding the first x) so the pan never extrapolates
    backwards. The string contains no spaces (ffmpeg expression-safe).
    """
    kfs = sorted((dict(k) for k in (keyframes or [])), key=lambda k: float(k["t"]))
    if len(kfs) < 2:
        return str(int(kfs[0]["x"])) if kfs else str(int(static_x))
    if float(kfs[0]["t"]) > 0.0:
        kfs.insert(0, {"t": 0.0, "x": kfs[0]["x"]})
    expr = str(int(kfs[-1]["x"]))  # after the last keyframe: hold its x
    for prev, nxt in zip(reversed(kfs[:-1]), reversed(kfs[1:]), strict=False):
        t0, t1 = float(prev["t"]), float(nxt["t"])
        if t1 <= t0:
            continue  # duplicate timestamp — skip the degenerate segment
        x0, x1 = int(prev["x"]), int(nxt["x"])
        seg = f"{x0}+({x1}-{x0})*(t-{t0:.3f})/({t1 - t0:.3f})"
        expr = f"if(lt(t,{t1:.3f}),{seg},{expr})"
    return expr


def build_reframe_argv(
    in_path: str,
    out_path: str,
    crop: dict[str, int],
    keyframes: Sequence[dict[str, float]] | None = None,
    aspect: str = DEFAULT_ASPECT,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """The ONE ffmpeg crop+scale pass (Route A step A2), as an argv list.

    ``-vf crop=W:H:'x(t)':Y,scale=<out>:flags=lanczos,setsar=1`` then libx264 +
    aac at the contract's output size (1080x1920 for 9:16). The x expression is
    single-quoted for the filtergraph parser (its ``if(...)`` form contains
    commas); since this is argv (no shell), the quotes reach ffmpeg verbatim.
    ``-progress pipe:1 -nostats`` feeds :func:`media_studio.ffmpeg.run`'s
    progress parsing; ``-y`` overwrites the output.
    """
    out_w, out_h = output_dimensions(aspect)
    x_expr = build_crop_x_expr(int(crop["x"]), keyframes)
    vf = (
        f"crop={int(crop['w'])}:{int(crop['h'])}:'{x_expr}':{int(crop['y'])},"
        f"scale={out_w}:{out_h}:flags=lanczos,setsar=1"
    )
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-vf",
        vf,
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


def build_probe_streams_argv(in_path: str, settings: dict[str, Any] | None = None) -> list[str]:
    """ffprobe argv that prints the first video stream + format as JSON."""
    return [
        ffmpeg.ffprobe_path(settings),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "-select_streams",
        "v:0",
        in_path,
    ]


def build_frame_extract_argv(
    in_path: str,
    ts: float,
    frame_path: str,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """ffmpeg argv extracting ONE frame at ``ts`` seconds to ``frame_path``."""
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-ss",
        f"{float(ts):.3f}",
        "-i",
        in_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        frame_path,
    ]


# --------------------------------------------------------------------------- #
# probing
# --------------------------------------------------------------------------- #
def probe_video(
    in_path: str,
    settings: dict[str, Any] | None = None,
    runner: SubprocessRunner = subprocess.run,
) -> tuple[int, int, float]:
    """Probe ``in_path`` -> ``(width, height, durationSec)`` via ffprobe.

    ``runner`` is injectable (subprocess.run-shaped; ``capture_output=True``
    drains both pipes — A6 lesson 2). Raises :class:`ClaudeShortsReframeError`
    when the geometry cannot be determined (we cannot compute any crop without
    it); a missing duration degrades to 0.0 (single-sample detection).
    """
    argv = build_probe_streams_argv(in_path, settings)
    completed = runner(argv, capture_output=True, text=True, check=False)
    out = (getattr(completed, "stdout", "") or "").strip()
    try:
        data = json.loads(out)
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ClaudeShortsReframeError(f"could not probe video geometry for {in_path}") from exc
    fmt = data.get("format") or {}
    raw_duration = fmt.get("duration", stream.get("duration", 0.0))
    try:
        duration = float(raw_duration)
    except (ValueError, TypeError):
        duration = 0.0
    return width, height, duration


# --------------------------------------------------------------------------- #
# subject detection (mediapipe -> haar -> center; natives imported lazily)
# --------------------------------------------------------------------------- #
def detect_backend(importer: Callable[[str], Any] = importlib.import_module) -> str:
    """Pick the detection backend: ``mediapipe`` | ``haar``.

    mediapipe needs cv2 too (frame decode), so the mediapipe backend requires
    BOTH. ``importer`` is injectable so tests exercise the fallback chain with
    no native modules present. NOTE (A6): in production these imports only
    *re-find* modules already loaded by ``__main__._preimport_native_modules``.

    WU-3 NO-SILENT-FALLBACK: when NEITHER mediapipe+cv2 nor cv2 alone is
    importable, subject tracking is impossible — this raises
    :class:`ClaudeShortsBackendUnavailableError` (an EXPLICIT setup/provisioning
    signal) instead of returning a silent ``"center"`` that the rest of the
    pipeline could not distinguish from a legitimate no-subject clip.
    """
    try:
        importer("mediapipe")
        importer("cv2")
        return "mediapipe"
    except Exception:  # noqa: BLE001 - any import failure -> next backend
        pass
    try:
        importer("cv2")
        return "haar"
    except Exception as exc:  # noqa: BLE001
        raise ClaudeShortsBackendUnavailableError(
            "subject tracking requires OpenCV (cv2) — and optionally MediaPipe — "
            "but neither is importable; install opencv-python (and mediapipe) to "
            "enable speaker tracking, or this is a provisioning/setup error"
        ) from exc


def _region_activity(prev_img: Any, cur_img: Any, box: tuple[int, int, int, int]) -> float:
    """Mean inter-frame change inside ``box`` (``x0,y0,x1,y1`` px) — the per-face
    motion score for the active-speaker tie-break.

    Used by :func:`_make_face_finder` to pick the TALKING head in a symmetric
    two-shot (mouth/gesture motion is concentrated on the active speaker's face).
    Returns ``0.0`` when there is no previous frame, the two frames differ in
    shape (a scene cut), or the box is empty / out of range — so the tie-break
    simply falls back to size on the very first frame and on geometry changes.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    if prev_img is None or prev_img.shape != cur_img.shape:
        return 0.0
    h, w = int(cur_img.shape[0]), int(cur_img.shape[1])
    x0 = max(0, min(int(box[0]), w))
    y0 = max(0, min(int(box[1]), h))
    x1 = max(0, min(int(box[2]), w))
    y1 = max(0, min(int(box[3]), h))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    prev_gray = cv2.cvtColor(prev_img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    cur_gray = cv2.cvtColor(cur_img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(prev_gray, cur_gray).mean())


def _make_face_finder(backend: str) -> tuple[Callable[[Any], float | None] | None, Callable[[], None]]:
    """Build ``(find(img_bgr) -> cx_norm|None, close())`` for ``backend``.

    ``find`` returns the DOMINANT/active face's normalized horizontal center via
    :func:`select_dominant`: the largest (closest) face wins outright, and a
    symmetric two-shot is broken toward the ACTIVE speaker using per-face motion
    against the previous frame (held in the closure). This is the wide-shot fix —
    the crop locks onto ONE featured speaker, never a blend of two faces. The
    finder is stateful (it remembers the previous frame) so the motion tie-break
    has something to diff; the first frame has no previous frame, so it falls back
    to pure size selection.
    """
    if backend == "mediapipe":
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)
        import mediapipe as mp  # noqa: PLC0415 - job-time native (pre-imported)  # pyright: ignore[reportMissingImports]  # optional runtime dep

        detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)
        prev: dict[str, Any] = {"img": None}

        def find_mp(img: Any) -> float | None:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb)
            detections = getattr(results, "detections", None)
            h, w = int(img.shape[0]), int(img.shape[1])
            cands: list[tuple[float, float, float]] = []
            for det in detections or []:
                bbox = det.location_data.relative_bounding_box
                cx = float(bbox.xmin + bbox.width / 2.0)
                size = float(bbox.width * bbox.height)
                box = (
                    int(bbox.xmin * w),
                    int(bbox.ymin * h),
                    int((bbox.xmin + bbox.width) * w),
                    int((bbox.ymin + bbox.height) * h),
                )
                cands.append((cx, size, _region_activity(prev["img"], img, box)))
            prev["img"] = img
            return select_dominant(cands)

        return find_mp, detector.close

    if backend == "haar":
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        # cv2.data is a real runtime submodule; the opencv type stubs omit it.
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")  # pyright: ignore[reportAttributeAccessIssue]
        cascade = cv2.CascadeClassifier(cascade_path)  # pyright: ignore[reportAttributeAccessIssue]
        if cascade.empty():
            # NO-SILENT-FALLBACK: a missing/unreadable cascade is a broken OpenCV
            # provisioning (the cascade ships WITH opencv-python), NOT a per-clip
            # event — fail loud with an actionable "reinstall opencv" error rather
            # than quietly returning a no-op finder that collapses to a center crop.
            raise ClaudeShortsBackendUnavailableError(
                f"OpenCV face cascade missing or unreadable at {cascade_path} — the "
                "opencv-python install is incomplete; reinstall it to enable speaker "
                "tracking (this is a provisioning/setup error, not a per-clip degrade)"
            )
        prev = {"img": None}

        def find_haar(img: Any) -> float | None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
            w_img = int(img.shape[1])
            cands: list[tuple[float, float, float]] = []
            for face in faces if faces is not None else []:
                x, y, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                cx = float((x + fw / 2.0) / w_img)
                size = float(fw * fh)
                box = (x, y, x + fw, y + fh)
                cands.append((cx, size, _region_activity(prev["img"], img, box)))
            prev["img"] = img
            return select_dominant(cands)

        return find_haar, lambda: None

    return None, lambda: None


# OpenCV's default people detector uses a 64x128 HOG window; calling
# detectMultiScale on a frame smaller than the window crashes the native code
# (segfault), so we hard-skip sub-window frames.
_HOG_MIN_W = 64
_HOG_MIN_H = 128


def _person_center(img: Any) -> float | None:
    """Normalized horizontal center of the most prominent PERSON in ``img``.

    Uses OpenCV's built-in HOG people detector (ships with opencv — no model
    download, node-free). This is the fallback for profile/turned heads where
    face detection fails but the speaker's BODY is still clearly in frame, so
    the crop stays on the person instead of collapsing to a center crop.
    Frames smaller than the 64x128 HOG window are skipped (calling the detector
    on them crashes the native code). Returns ``None`` when no person is found.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    h, w = int(img.shape[0]), int(img.shape[1])
    if w < _HOG_MIN_W or h < _HOG_MIN_H:
        return None
    hog = cv2.HOGDescriptor()  # pyright: ignore[reportAttributeAccessIssue]
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())  # pyright: ignore[reportAttributeAccessIssue]
    rects, weights = hog.detectMultiScale(img, winStride=(8, 8))
    if rects is None or len(rects) == 0:
        return None
    weights = list(weights) if weights is not None else []
    # WU PHASE-5: in a wide / two-shot pick the DOMINANT person = the LARGEST
    # (closest) body, breaking a same-size tie by detector confidence (weight ~
    # how strongly a body was seen). This frames the featured speaker instead of
    # a smaller, further person who merely scored a higher confidence.
    cands: list[tuple[float, float, float]] = []
    for i, rect in enumerate(rects):
        rx, _ry, rw, rh = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
        cx = float((rx + rw / 2.0) / w)
        area = float(rw * rh)
        activity = float(weights[i]) if i < len(weights) else 0.0
        cands.append((cx, area, activity))
    return select_dominant(cands)


def _dominant_cluster_centroid(col: Sequence[float]) -> float:
    """Intensity-weighted center column of the DOMINANT contiguous motion run.

    ``col`` is a per-column motion profile (a row-sum of the motion mask). Two
    people moving in a wide / two-shot show up as TWO separate nonzero runs with a
    still gap between them; the plain global centroid of all moving pixels lands in
    that gap (the empty-studio bug). We instead split ``col`` into contiguous
    nonzero runs and return the intensity-weighted centroid of the run with the
    most total motion — the single most-active subject. ``col`` is assumed to have
    at least one nonzero entry (the caller checks the total first).
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i in range(len(col)):
        if float(col[i]) > 0.0 and start is None:
            start = i
        elif float(col[i]) <= 0.0 and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(col)))
    lo, hi = max(runs, key=lambda r: sum(float(col[i]) for i in range(r[0], r[1])))
    total = sum(float(col[i]) for i in range(lo, hi))
    weighted = sum(i * float(col[i]) for i in range(lo, hi))
    return weighted / total


def _motion_center(prev: Any, img: Any) -> float | None:
    """Normalized horizontal center of the strongest MOTION between two frames.

    Last-resort saliency: a sitting/standing speaker still moves (head, hands,
    mouth) more than the static studio behind them. We diff consecutive sampled
    frames, threshold the change, and take the intensity-weighted horizontal
    centroid of the DOMINANT motion cluster (:func:`_dominant_cluster_centroid`) —
    so the crop locates ONE speaker even when neither a face nor a full body is
    detectable, and in a wide/two-shot it locks onto the most-active person rather
    than the empty gap between two movers. ``None`` when nothing moved.
    """
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)
    import numpy as np  # noqa: PLC0415 - job-time native (numpy ships with cv2)

    if prev.shape != img.shape:
        return None  # frame geometry changed (e.g. scene cut) — no usable diff
    g0 = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    g1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(g0, g1)
    _thr, mask = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    col = np.asarray(mask, dtype="float64").sum(axis=0)
    if float(col.sum()) <= 0.0:
        return None
    centroid = _dominant_cluster_centroid(col.tolist())
    return centroid / float(img.shape[1])


def _make_subject_finder(
    backend: str,
) -> tuple[Callable[[Any], float | None] | None, Callable[[], None]]:
    """Build a stateful subject finder: face -> person -> motion fallback.

    Returns ``(find(img_bgr) -> cx_norm|None, close())``. ``find`` tries, in
    order: the backend's FACE detector (mediapipe/haar); then a PERSON (HOG body)
    detector for profile/turned shots where the face is weak or absent; then
    MOTION saliency against the previous frame as a last resort. This keeps the
    crop on the SPEAKER instead of falling back to a center-of-frame crop the
    moment a face is not cleanly visible. ``None`` only when none of the three
    locate anything. For the ``center`` backend there is no finder.
    """
    face_find, face_close = _make_face_finder(backend)
    if backend == "center":
        return None, face_close
    prev_frame: dict[str, Any] = {"img": None}

    def find(img: Any) -> float | None:
        cx: float | None = None
        if face_find is not None:
            cx = face_find(img)
        if cx is None:
            cx = _person_center(img)
        if cx is None and prev_frame["img"] is not None:
            cx = _motion_center(prev_frame["img"], img)
        prev_frame["img"] = img
        return cx

    return find, face_close


def detect_subject_centers(
    in_path: str,
    timestamps: Sequence[float],
    *,
    settings: dict[str, Any] | None = None,
    frame_runner: SubprocessRunner = subprocess.run,
    backend: str | None = None,
) -> list[tuple[float, float]]:
    """Detect the subject's normalized horizontal center per sampled window.

    Extracts one frame per timestamp via ffmpeg (argv list, pipes drained by
    ``capture_output``), runs the face->person->motion subject finder, and
    returns ``[(t, cx_norm)]`` for the frames where a subject was located. An
    empty list means "no subject anywhere" -> the caller keeps the centered crop.
    """
    backend = backend or detect_backend()
    if backend == "center":
        return []
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    find, close = _make_subject_finder(backend)
    if find is None:
        return []
    tmpdir = tempfile.mkdtemp(prefix="media_studio_reframe_")
    samples: list[tuple[float, float]] = []
    try:
        for i, ts in enumerate(timestamps):
            frame_path = os.path.join(tmpdir, f"f_{i:04d}.jpg")
            frame_runner(
                build_frame_extract_argv(in_path, ts, frame_path, settings),
                capture_output=True,
                check=False,
            )
            if not os.path.exists(frame_path):
                continue
            img = cv2.imread(frame_path)
            if img is None:
                continue
            cx = find(img)
            if cx is not None:
                samples.append((float(ts), float(cx)))
    finally:
        try:
            close()
        except Exception:  # noqa: BLE001 - cleanup must never mask results
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)
    return samples


# --------------------------------------------------------------------------- #
# the engine
# --------------------------------------------------------------------------- #
class ClaudeShortsReframeEngine:
    """In-sidecar subject-tracked crop reframe (A4 ``claudeshorts`` engine).

    Same public interface as the verthor adapter:
    ``reframe(in_path, out_path, aspect) -> out_path``. All heavy seams are
    injectable for tests: ``runner`` (ffmpeg.run-shaped encode), ``prober``
    (geometry/duration), ``detector`` (subject centers). Defaults bind the real
    implementations lazily, so importing this module stays dependency-light.
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        runner: Runner | None = None,
        prober: Prober | None = None,
        detector: Detector | None = None,
        backend_probe: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings or {}
        # A6 lesson 2: the default encode runner is ffmpeg.run — it drains
        # stderr on a daemon thread, so the long encode can never pipe-deadlock.
        self._runner: Runner = runner if runner is not None else ffmpeg.run
        self._prober: Prober = prober or (lambda path: probe_video(path, self._settings))
        self._detector: Detector = detector or (
            lambda path, ts: detect_subject_centers(path, ts, settings=self._settings)
        )
        # Resolves the active detection backend ("mediapipe" | "haar") so a
        # center-crop degrade can NAME a missing model, and so a total provisioning
        # failure (no cv2) surfaces loudly. Injectable for deterministic tests.
        self._backend_probe: Callable[[], str] = backend_probe or detect_backend

    def compute_plan(
        self,
        in_path: str,
        aspect: str = DEFAULT_ASPECT,
        on_notice: Callable[[dict[str, str]], None] | None = None,
    ) -> tuple[dict[str, int], list[dict[str, float]], float]:
        """Compute ``(crop_rect, keyframes, durationSec)`` for ``in_path``.

        Pure planning (probe + detect + smooth + keyframe), no encoding. The
        returned keyframes list is empty when a single static crop suffices.

        WU-3 NO-SILENT-FALLBACK: when speaker tracking cannot run, the crop still
        degrades to a center crop (the encode never fails for this), but the
        degrade is SURFACED through ``on_notice`` (a structured
        :data:`REFRAME_DEGRADED_NOTICE`) so the UI can show a real/degraded badge
        — it is never swallowed into a silent center crop. A native-backend SETUP
        error (:class:`ClaudeShortsBackendUnavailableError`) is NOT a per-clip
        degrade: it propagates so the job fails loudly (install opencv/mediapipe).
        """
        src_w, src_h, duration = self._prober(in_path)
        crop = centered_crop(src_w, src_h, aspect)
        timestamps = window_timestamps(duration)
        # Resolve the active backend up front so any degrade below can NAME a
        # missing model. A total provisioning failure (no cv2/mediapipe) raises
        # ClaudeShortsBackendUnavailableError here and propagates loudly — never a
        # silent center crop (NO-SILENT-FALLBACK).
        backend = self._backend_probe()
        try:
            samples = list(self._detector(in_path, timestamps) or [])
        except ClaudeShortsBackendUnavailableError:
            # SETUP/provisioning failure (no cv2/mediapipe): fail loud, never a
            # per-clip silent degrade. Re-raise so the job surfaces an actionable
            # "install opencv/mediapipe" error.
            raise
        except Exception as exc:  # noqa: BLE001 - a runtime detector failure -> degrade
            # A broken detector degrades to the centered crop — the encode still
            # runs; only subject tracking is lost. SURFACE it (never swallow).
            _log.warning("subject detection failed; using centered crop", exc_info=True)
            self._notify_degraded(on_notice, f"subject detection failed: {exc}", backend=backend)
            return crop, [], duration
        # Trust gate: a couple of stray hits across many windows is detector noise,
        # not a locatable subject -> keep the centered crop rather than tracking it.
        min_hits = max(1, math.ceil(len(timestamps) * MIN_SUBJECT_HIT_FRAC))
        if len(samples) < min_hits:
            self._notify_degraded(on_notice, "no trackable subject located", backend=backend)
            return crop, [], duration

        smoothed = smooth_centers([c for _, c in samples])
        xs = [crop_x_for_center(c, crop["w"], src_w) for c in smoothed]
        kfs = build_keyframes([t for t, _ in samples], xs)
        kfs = dedupe_keyframes(kfs, min_delta=crop["w"] * KEYFRAME_MIN_DELTA_FRAC)
        if is_static(kfs, epsilon=crop["w"] * STATIC_EPSILON_FRAC):
            # GENUINELY static subject -> ONE fixed crop centered ON THE SUBJECT
            # (the smoothed track sits within epsilon, so any keyframe x is the
            # subject's position — NOT a bias back toward frame center).
            static_x = int(round(sum(k["x"] for k in kfs) / len(kfs)))
            crop = {**crop, "x": max(0, min(static_x, max(0, src_w - crop["w"])))}
            return crop, [], duration
        # Moving subject -> animated x(t) that FOLLOWS the speaker. The static
        # fallback x (used only before the first keyframe / by build_crop_x_expr)
        # is the FIRST tracked position so the crop opens ON the subject, never
        # pre-biased to frame center.
        crop = {**crop, "x": int(kfs[0]["x"])}
        return crop, kfs, duration

    @staticmethod
    def _notify_degraded(
        on_notice: Callable[[dict[str, str]], None] | None,
        reason: str,
        *,
        backend: str | None = None,
    ) -> None:
        """Surface a per-clip degraded notice through ``on_notice`` (when wired).

        The degrade is ALSO logged, but the structured notice is what lets the
        orchestrator/UI render a degraded badge — the "never swallow" contract.
        ``backend`` (the active detector backend) is passed to
        :func:`make_degraded_notice` so a haar/no-MediaPipe degrade names the
        missing model instead of silently reading as "no subject".
        """
        if on_notice is not None:
            on_notice(make_degraded_notice(reason, backend=backend))

    def reframe(
        self,
        in_path: str,
        out_path: str,
        aspect: str = DEFAULT_ASPECT,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_notice: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
        """Reframe ``in_path`` -> vertical ``out_path`` in ONE ffmpeg pass.

        Raises :class:`ClaudeShortsReframeError` on a non-zero encode exit (the
        shortmaker job converts that into the job.done error payload — A6 #3).
        ``on_notice`` is forwarded to :meth:`compute_plan` so a speaker-tracking
        degrade surfaces from this one-shot entry point too (WU-3).
        """
        crop, keyframes, duration = self.compute_plan(in_path, aspect, on_notice=on_notice)
        argv = build_reframe_argv(in_path, out_path, crop, keyframes, aspect, self._settings)
        if not isinstance(argv, list):  # defensive: never a shell string
            raise TypeError("reframe argv must be a list of strings")
        _log.info(
            "claudeshorts reframe: crop=%s keyframes=%d aspect=%s",
            crop,
            len(keyframes),
            aspect,
        )
        code = self._runner(
            argv,
            total_sec=duration,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        if code != 0:
            raise ClaudeShortsReframeError(f"claudeshorts reframe failed (exit {code}) for {out_path}")
        return out_path
