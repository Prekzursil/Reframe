"""ClaudeShortsReframeEngine — engine 2 of ReframeEngine (CONTRACTS.md A4).

Port of **Route A** from the vendored claude-shorts project (MIT, pinned
``a369fad``): ``scripts/compute_reframe.py`` + ``ENGINE1_BUILD_RECIPE.md``.
Route A's verdict: claude-shorts' own renderer applies the crop in Remotion
(node/Chrome); the node-free path is to compute the crop RECTANGLE with the
Python detection logic and then apply it ffmpeg-side with ONE ``crop`` +
``scale`` pass. That is exactly what this engine does — fully **in-sidecar**,
no WSL, no node, no Remotion:

  1. probe the source geometry/duration (ffprobe, argv list);
  2. sample one frame per time window and detect the subject's horizontal
     center — **mediapipe** face detection when importable (A6: it MUST be
     pre-imported by ``__main__._preimport_native_modules``; see
     :data:`NATIVE_MODULES_FOR_PREIMPORT`), else an **OpenCV haar**-cascade
     face fallback, else a plain **center** crop;
  3. smooth the per-window centers with simple exponential easing and convert
     them to clamped crop-x keyframes (deduped, Route A style);
  4. apply ONE ffmpeg pass: ``crop=W:H:'x(t)':Y,scale=1080:1920`` (a static x
     when the subject doesn't move; a piecewise-linear ``x(t)`` expression when
     it does), h264 output at the contract's 1080x1920 for 9:16.

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
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from typing import Any

from .. import ffmpeg
from ..util import get_logger

_log = get_logger("media_studio.reframe_claudeshorts")

# Contract (A4 / base §4): vertical 9:16 output at exactly this resolution, h264.
DEFAULT_ASPECT = "9:16"
OUT_WIDTH = 1080
OUT_HEIGHT = 1920

# Sampling/smoothing knobs (Route A used 5 samples per clip; per-window sampling
# generalizes that to clip length while bounding frame-extraction cost).
WINDOW_SEC = 2.0
MAX_WINDOWS = 24
# Exponential-easing factor: 0=frozen, 1=no smoothing. Dialled WAY down from the
# original 0.35 (which let per-window face-detector noise leak straight into the
# crop, producing the visible 9:16 jitter on a near-static talking head). 0.15
# heavily damps that noise while still tracking a genuinely moving subject.
SMOOTH_ALPHA = 0.15
# DEADZONE (the jitter fix): the crop center is HELD until the smoothed subject
# center drifts more than this fraction of the SOURCE WIDTH (normalized 0..1
# center space). A sitting speaker whose detected center merely wobbles a few
# percent therefore yields a STATIC crop — no micro-pan. 7% is the spec's 6-8%.
DEADZONE_FRAC = 0.07
# Route A drops keyframes whose x moved < this fraction of the crop width; the
# same threshold decides "the track is effectively static -> one static crop".
# Raised from 2% so low-variance tracks bias toward a single static crop (the
# deadzone already pins the centers; this is the belt-and-braces static gate in
# crop-pixel space, matched to the deadzone band).
KEYFRAME_MIN_DELTA_FRAC = 0.06
STATIC_EPSILON_FRAC = 0.06

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


# --------------------------------------------------------------------------- #
# aspect handling (kept in sync with features.reframe — see module docstring)
# --------------------------------------------------------------------------- #
def _parse_aspect(aspect: str) -> tuple[int, int]:
    """Parse ``"W:H"`` (or ``"WxH"``) into a positive ``(w, h)`` int tuple."""
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


def _even(n: int) -> int:
    """Round a dimension up to even (h264 requires even output sizes)."""
    return n if n % 2 == 0 else n + 1


def output_dimensions(aspect: str = DEFAULT_ASPECT) -> tuple[int, int]:
    """(width, height) of the encode target for ``aspect`` (9:16 -> 1080x1920)."""
    w, h = _parse_aspect(aspect)
    if (w, h) == (9, 16):
        return OUT_WIDTH, OUT_HEIGHT
    if h >= w:
        return _even(int(round(OUT_HEIGHT * (w / h)))), OUT_HEIGHT
    return OUT_HEIGHT, _even(int(round(OUT_HEIGHT * (h / w))))


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
# track smoothing + keyframes (pure)
# --------------------------------------------------------------------------- #
def smooth_centers(centers: Sequence[float], alpha: float = SMOOTH_ALPHA) -> list[float]:
    """Exponential-easing smoothing of subject centers (simple easing).

    ``out[i] = out[i-1] + alpha * (centers[i] - out[i-1])`` — each step eases
    toward the new measurement, damping detector jitter while still following a
    genuinely moving subject.
    """
    out: list[float] = []
    prev: float | None = None
    for c in centers:
        c = float(c)
        prev = c if prev is None else prev + float(alpha) * (c - prev)
        out.append(prev)
    return out


def apply_deadzone(centers: Sequence[float], deadzone: float = DEADZONE_FRAC) -> list[float]:
    """Hold the subject center until it drifts more than ``deadzone`` (the fix).

    Walks the (already-smoothed) normalized centers and emits a HELD value that
    only snaps to a new center once the new measurement deviates from the held
    one by more than ``deadzone`` (a fraction of source width, in 0..1 center
    space). A near-static talking head whose detected center merely jitters
    within the band therefore yields a single constant center -> a STATIC crop
    (no per-window micro-pan). A genuine move past the band updates the hold,
    so a real pan is still followed.
    """
    out: list[float] = []
    held: float | None = None
    for c in centers:
        c = float(c)
        if held is None or abs(c - held) > float(deadzone):
            held = c
        out.append(held)
    return out


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
    """Pick the detection backend: ``mediapipe`` | ``haar`` | ``center``.

    mediapipe needs cv2 too (frame decode), so the mediapipe backend requires
    BOTH. ``importer`` is injectable so tests exercise the fallback chain with
    no native modules present. NOTE (A6): in production these imports only
    *re-find* modules already loaded by ``__main__._preimport_native_modules``.
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
    except Exception:  # noqa: BLE001
        return "center"


def _make_face_finder(backend: str) -> tuple[Callable[[Any], float | None] | None, Callable[[], None]]:
    """Build ``(find(img_bgr) -> cx_norm|None, close())`` for ``backend``."""
    if backend == "mediapipe":
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)
        import mediapipe as mp  # noqa: PLC0415 - job-time native (pre-imported)  # pyright: ignore[reportMissingImports]  # optional runtime dep

        detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

        def find_mp(img: Any) -> float | None:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = detector.process(rgb)
            detections = getattr(results, "detections", None)
            if not detections:
                return None
            best = max(
                detections,
                key=lambda d: (
                    d.location_data.relative_bounding_box.width * d.location_data.relative_bounding_box.height
                ),
            )
            bbox = best.location_data.relative_bounding_box
            return float(bbox.xmin + bbox.width / 2.0)

        return find_mp, detector.close

    if backend == "haar":
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        # cv2.data is a real runtime submodule; the opencv type stubs omit it.
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")  # pyright: ignore[reportAttributeAccessIssue]
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            _log.warning("haar cascade missing at %s; using center crop", cascade_path)
            return None, lambda: None

        def find_haar(img: Any) -> float | None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
            if faces is None or len(faces) == 0:
                return None
            x, _y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
            return float((x + w / 2.0) / img.shape[1])

        return find_haar, lambda: None

    return None, lambda: None


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
    ``capture_output``), runs the backend's face finder, and returns
    ``[(t, cx_norm)]`` for the frames where a subject was found. An empty list
    means "no subject anywhere" -> the caller keeps the centered crop.
    """
    backend = backend or detect_backend()
    if backend == "center":
        return []
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    find, close = _make_face_finder(backend)
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
    ) -> None:
        self._settings = settings or {}
        # A6 lesson 2: the default encode runner is ffmpeg.run — it drains
        # stderr on a daemon thread, so the long encode can never pipe-deadlock.
        self._runner: Runner = runner if runner is not None else ffmpeg.run
        self._prober: Prober = prober or (lambda path: probe_video(path, self._settings))
        self._detector: Detector = detector or (
            lambda path, ts: detect_subject_centers(path, ts, settings=self._settings)
        )

    def compute_plan(
        self, in_path: str, aspect: str = DEFAULT_ASPECT
    ) -> tuple[dict[str, int], list[dict[str, float]], float]:
        """Compute ``(crop_rect, keyframes, durationSec)`` for ``in_path``.

        Pure planning (probe + detect + smooth + keyframe), no encoding. The
        returned keyframes list is empty when a single static crop suffices.
        """
        src_w, src_h, duration = self._prober(in_path)
        crop = centered_crop(src_w, src_h, aspect)
        timestamps = window_timestamps(duration)
        try:
            samples = list(self._detector(in_path, timestamps) or [])
        except Exception:  # noqa: BLE001 - detection is best-effort by design
            # "else center": a broken detector degrades to the centered crop —
            # the encode still runs; only subject tracking is lost.
            _log.warning("subject detection failed; using centered crop", exc_info=True)
            samples = []
        if not samples:
            return crop, [], duration

        smoothed = smooth_centers([c for _, c in samples])
        # DEADZONE: pin the center until it drifts past the band, so detector
        # jitter on a near-static subject never reaches the crop (the jitter fix).
        held = apply_deadzone(smoothed)
        xs = [crop_x_for_center(c, crop["w"], src_w) for c in held]
        kfs = build_keyframes([t for t, _ in samples], xs)
        kfs = dedupe_keyframes(kfs, min_delta=crop["w"] * KEYFRAME_MIN_DELTA_FRAC)
        if is_static(kfs, epsilon=crop["w"] * STATIC_EPSILON_FRAC):
            # Stable subject -> ONE static crop centered on it (Route A's
            # face-track average), clamped into frame.
            avg_x = int(round(sum(k["x"] for k in kfs) / len(kfs)))
            crop = {**crop, "x": max(0, min(avg_x, max(0, src_w - crop["w"])))}
            return crop, [], duration
        # Moving subject -> animated x(t); the static x stays the track average
        # (the fallback value also used before the first keyframe segment).
        avg_x = int(round(sum(k["x"] for k in kfs) / len(kfs)))
        crop = {**crop, "x": max(0, min(avg_x, max(0, src_w - crop["w"])))}
        return crop, kfs, duration

    def reframe(
        self,
        in_path: str,
        out_path: str,
        aspect: str = DEFAULT_ASPECT,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Reframe ``in_path`` -> vertical ``out_path`` in ONE ffmpeg pass.

        Raises :class:`ClaudeShortsReframeError` on a non-zero encode exit (the
        shortmaker job converts that into the job.done error payload — A6 #3).
        """
        crop, keyframes, duration = self.compute_plan(in_path, aspect)
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
