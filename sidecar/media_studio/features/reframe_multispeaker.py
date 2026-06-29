"""HYBRID multi-speaker reframe engine — the flagship (WU R1).

This is engine 3 of :class:`~media_studio.features.reframe.ReframeEngine`
(``reframe_multispeaker``, registered in :data:`reframe.ENGINES` /
``export_presets.REFRAME_ENGINES``). It is a per-segment **DIRECTOR / decision
layer** stacked over the existing parts (TransNetV2 shot detect, PySceneDetect
fallback, mediapipe/HOG/motion detection, Light-ASD visual active-speaker,
``diarize`` turns, ``audio_saliency`` VAD), producing a multi-cut / split /
composite vertical 9:16 clip instead of the single tracked crop the
``claudeshorts`` engine renders.

ARCHITECTURE — the canonical Phase-8 seam (see ``scene_transnet`` / ``diarize``):

* **Pure half (this module, 100% line+branch covered):** shot merging, the
  multi-face IoU/Hungarian re-id tracker, the One-Euro smoother, the
  confidence-gated active-speaker FUSION, the debounced single/split/composite
  LAYOUT decision, hard-cut commitment, the ``ffmpeg`` ``filter_complex``
  compositor argv, and the :class:`~media_studio.features.reframe_eval.ReframeTrace`
  assembly. NO torch / cv2 / model import; everything is exercised with
  hand-built fixtures + an injected fake backend.
* **Heavy half behind a Protocol :class:`MultiSpeakerBackend`** that is NEVER
  imported at module load. A real impl is built lazily by
  :func:`_default_backend_factory` (which imports the sibling
  ``reframe_multispeaker_backend`` only at runtime). The backend STAGES its
  models sequentially (shots -> diarize -> ASD -> compose) and is
  :meth:`MultiSpeakerBackend.release`\\d between stages so a 6 GB GPU never holds
  two models at once.

FAILURE-MODE CONTRACT (GATE-2 + design-gate, mirrors ``reframe.py``):

* an **EXPLICIT** ``reframe_multispeaker`` request with WSL/CUDA/models absent
  raises a typed :class:`MultiSpeakerUnavailableError` (a ``RuntimeError``)
  that NAMES the real cause — it does NOT reuse :class:`offline.OfflineError`,
  whose "Turn off Offline mode" message is wrong for a missing-GPU host;
* **Offline mode ON** + the weights not yet cached raises
  :class:`offline.OfflineError` (the correct, actionable message) via
  :func:`offline.guard_network`;
* an **AUTO-attempt-then-degrade** caller (``allow_degrade=True``) falls back to
  the single-speaker ``claudeshorts`` engine and emits a loud
  :data:`~reframe_claudeshorts.REFRAME_DEGRADED_NOTICE` notice with a DISTINCT
  engine-degrade message (it does NOT reuse ``make_degraded_notice`` verbatim —
  that hardcodes "used center crop");
* a **cold-start** failure on the FIRST shot (no previous crop) falls back to
  ``claudeshorts.select_dominant`` (deterministic), NEVER a silent center crop;
* an **OOM / model-load failure mid-render** raises a typed error AND cleans up
  the partial output; the render writes to a temp path and is atomically renamed
  on success only, so a crash can never leave a corrupt half-clip at ``out_path``
  for L2 lineage-on-success.

See ``docs/WU-R1-MULTISPEAKER-ENGINE.md`` for the committed interface brief and
basic-memory ``reframe-multi-speaker-engine-approach-decided-hybrid``.
"""

from __future__ import annotations

import contextlib
import math
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import ffmpeg
from ..util import get_logger
from . import aspect as _aspect
from . import offline as _offline
from . import reframe_claudeshorts as _cs
from .reframe_eval import LAYOUTS, ReframeTrace, Segment, crop_iou

_log = get_logger("media_studio.features.reframe_multispeaker")

#: The engine name (UI contract — added to ``export_presets.REFRAME_ENGINES``).
ENGINE_NAME = "reframe_multispeaker"

#: Contract output (mirrors the other engines): vertical 9:16, h264.
DEFAULT_ASPECT = "9:16"

#: The HF assets the heavy backend needs (registered, F3c-pinned, below).
LIGHT_ASD_ASSET = "light-asd"
LIGHT_ASD_REPO = "TaoRuijie/Light-ASD"
LIGHT_ASD_SIZE_MB = 110.0

# --- Decision-layer tunables (design note) ---------------------------------- #
#: shots shorter than this many seconds are merged into their neighbour so a
#: rapid-fire cut storm does not reset the crop every few frames (0.4-0.6 s).
MIN_SHOT_SEC = 0.5
#: IoU above which a face box in frame N is the SAME track as one in frame N-1.
TRACK_IOU_THRESHOLD = 0.3
#: an active-speaker fusion below this confidence is "unsure" -> hold / dominant.
ASD_CONFIDENCE_THRESHOLD = 0.55
#: a layout must persist at least this long before it is committed (debounce,
#: 0.4-0.7 s) so a one-frame ASD flicker never flips split<->single.
LAYOUT_MIN_DWELL_SEC = 0.5
#: One-Euro smoother defaults (within a single-subject shot, past the dead-zone).
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 0.3
ONE_EURO_D_CUTOFF = 1.0
#: a smoothed centre that moved less than this fraction of the source width is
#: held (dead-zone) so micro-jitter never nudges the crop.
DEAD_ZONE_FRAC = 0.004

#: distinct from ``make_degraded_notice`` ("used center crop"): the ENGINE-level
#: degrade message for an AUTO multispeaker attempt that fell back to single.
ENGINE_DEGRADE_MESSAGE = (
    "reframe: multi-speaker engine unavailable ({reason}) — used the single-speaker tracker instead"
)


class MultiSpeakerReframeError(RuntimeError):
    """Base error for the multi-speaker engine (a render/setup failure)."""


class MultiSpeakerUnavailableError(MultiSpeakerReframeError):
    """An EXPLICIT engine request on a host that cannot run it (loud, typed).

    Raised when WSL / CUDA / the Light-ASD weights are absent and the caller
    asked for ``reframe_multispeaker`` EXPLICITLY (``allow_degrade=False``). It
    deliberately does NOT subclass :class:`offline.OfflineError`: a missing GPU
    is not an "offline mode" problem, so its message names the REAL cause (mirror
    ``reframe.ReframeError`` for the explicit-verthor path).
    """


class MultiSpeakerRenderError(MultiSpeakerReframeError):
    """An OOM / model-load / encode failure mid-render (partial output cleaned up)."""


# --------------------------------------------------------------------------- #
# Shot merging (pure)
# --------------------------------------------------------------------------- #
def merge_short_shots(
    boundaries: Sequence[int],
    total_frames: int,
    *,
    fps: float,
    min_shot_sec: float = MIN_SHOT_SEC,
) -> tuple[int, ...]:
    """Drop cut boundaries that would create a shot shorter than ``min_shot_sec``.

    Boundaries are de-duplicated, sorted, and clamped to ``(0, total_frames)``.
    Walking left to right, a boundary is KEPT only when it is at least
    ``min_frames`` past the previous kept boundary AND leaves at least
    ``min_frames`` before the clip end — otherwise it is merged away (the two
    shots become one). The shot boundary is a MANDATORY crop reset, so merging
    avoids resetting the crop on a sub-half-second flash cut.
    """
    if total_frames <= 0:
        raise MultiSpeakerReframeError("clip has no frames")
    if fps <= 0.0:
        raise MultiSpeakerReframeError("fps must be > 0")
    min_frames = max(1, int(round(min_shot_sec * fps)))
    cuts = sorted({int(b) for b in boundaries if 0 < int(b) < total_frames})
    kept: list[int] = []
    last = 0
    for cut in cuts:
        if cut - last < min_frames:
            continue  # too close to the previous boundary -> merge away
        if total_frames - cut < min_frames:
            continue  # leaves too short a tail -> merge into the final shot
        kept.append(cut)
        last = cut
    return tuple(kept)


def shot_spans(boundaries: Sequence[int], total_frames: int) -> tuple[tuple[int, int], ...]:
    """Partition ``[0, total_frames)`` into ``[start, end)`` shots at ``boundaries``."""
    if total_frames <= 0:
        raise MultiSpeakerReframeError("clip has no frames")
    cuts = sorted({int(b) for b in boundaries if 0 < int(b) < total_frames})
    spans: list[tuple[int, int]] = []
    start = 0
    for cut in cuts:
        spans.append((start, cut))
        start = cut
    spans.append((start, total_frames))
    return tuple(spans)


# --------------------------------------------------------------------------- #
# Multi-face IoU/Hungarian re-id tracker (pure, stateful within a shot)
# --------------------------------------------------------------------------- #
Box = tuple[float, float, float, float]  # (x, y, w, h) in source pixels


@dataclass
class MultiFaceTracker:
    """Greedy IoU re-identification tracker — stable face IDs WITHIN one shot.

    ``update(boxes)`` returns a track id per input box. Each new box is matched
    to the previous frame's box with the highest IoU above
    :data:`TRACK_IOU_THRESHOLD` (a one-to-one Hungarian-style assignment done
    greedily by descending IoU); unmatched boxes get fresh ids. The shot
    boundary is a MANDATORY reset (:meth:`reset`) — ids never cross a cut, so a
    new person entering shot 2 cannot inherit shot 1's speaker id.
    """

    iou_threshold: float = TRACK_IOU_THRESHOLD
    _next_id: int = 0
    _prev: dict[int, Box] = field(default_factory=dict)

    def reset(self) -> None:
        """Forget all tracks (called at every shot boundary)."""
        self._prev = {}

    def update(self, boxes: Sequence[Box]) -> list[int]:
        """Assign a stable track id to each box in ``boxes`` (frame order)."""
        pairs: list[tuple[float, int, int]] = []
        for det_idx, box in enumerate(boxes):
            for tid, prev_box in self._prev.items():
                overlap = crop_iou(box, prev_box)
                if overlap >= self.iou_threshold:
                    pairs.append((overlap, det_idx, tid))
        pairs.sort(key=lambda p: p[0], reverse=True)
        assigned_det: dict[int, int] = {}
        used_tid: set[int] = set()
        for _overlap, det_idx, tid in pairs:
            if det_idx in assigned_det or tid in used_tid:
                continue
            assigned_det[det_idx] = tid
            used_tid.add(tid)
        result: list[int] = []
        current: dict[int, Box] = {}
        for det_idx, box in enumerate(boxes):
            if det_idx in assigned_det:
                tid = assigned_det[det_idx]
            else:
                tid = self._next_id
                self._next_id += 1
            current[tid] = box
            result.append(tid)
        self._prev = current
        return result


# --------------------------------------------------------------------------- #
# One-Euro smoother (pure) — WITHIN a single-subject shot, past a dead-zone
# --------------------------------------------------------------------------- #
class OneEuroFilter:
    """The 1-Euro filter (Casiez et al.) — speed-adaptive low-pass smoothing.

    At low speed it smooths hard (kills jitter on a still subject); at high speed
    it relaxes (no lag chasing a fast pan). Timestamps MUST be strictly
    increasing (a non-monotonic ``t`` is a contract violation, raised loud).
    """

    def __init__(
        self,
        *,
        min_cutoff: float = ONE_EURO_MIN_CUTOFF,
        beta: float = ONE_EURO_BETA,
        d_cutoff: float = ONE_EURO_D_CUTOFF,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._t_prev: float | None = None
        self._x_prev: float = 0.0
        self._dx_prev: float = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t: float, x: float) -> float:
        """Filter sample ``x`` at time ``t`` (seconds); return the smoothed value."""
        t = float(t)
        x = float(x)
        if self._t_prev is None:
            self._t_prev, self._x_prev, self._dx_prev = t, x, 0.0
            return x
        dt = t - self._t_prev
        if dt <= 0.0:
            raise MultiSpeakerReframeError("OneEuroFilter timestamps must strictly increase")
        dx = (x - self._x_prev) / dt
        edx = self._dx_prev + self._alpha(self.d_cutoff, dt) * (dx - self._dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(edx)
        ex = self._x_prev + self._alpha(cutoff, dt) * (x - self._x_prev)
        self._t_prev, self._x_prev, self._dx_prev = t, ex, edx
        return ex


def smooth_centers_one_euro(
    timestamps: Sequence[float],
    centers: Sequence[float],
    *,
    dead_zone: float = DEAD_ZONE_FRAC,
    min_cutoff: float = ONE_EURO_MIN_CUTOFF,
    beta: float = ONE_EURO_BETA,
) -> list[float]:
    """One-Euro smooth ``centers`` (median-prefiltered) with a dead-zone hold.

    A length-:data:`reframe_claudeshorts.MEDIAN_WINDOW` median pre-filter runs
    first (kills lone detector spikes), then the One-Euro filter follows the
    subject. After filtering, a sample that moved less than ``dead_zone`` from the
    last EMITTED centre is HELD at that centre (micro-jitter never nudges the
    crop). ``timestamps`` and ``centers`` must be equal length (loud otherwise).
    """
    if len(timestamps) != len(centers):
        raise MultiSpeakerReframeError("timestamps/centers length mismatch")
    pre = _cs.median_prefilter(centers)
    flt = OneEuroFilter(min_cutoff=min_cutoff, beta=beta)
    out: list[float] = []
    last_emitted: float | None = None
    for t, c in zip(timestamps, pre, strict=True):
        smoothed = flt(t, c)
        if last_emitted is not None and abs(smoothed - last_emitted) < dead_zone:
            out.append(last_emitted)
        else:
            last_emitted = smoothed
            out.append(smoothed)
    return out


# --------------------------------------------------------------------------- #
# Active-speaker fusion (pure) — visual ASD x diarize turn x VAD
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SpeakerVote:
    """One frame's active-speaker decision: the chosen id + its confidence.

    ``speaker`` is ``""`` when the fusion was below
    :data:`ASD_CONFIDENCE_THRESHOLD` (the caller HOLDS the previous speaker or
    falls back to ``select_dominant``); ``confidence`` is the fused score 0..1.
    """

    speaker: str
    confidence: float


def fuse_active_speaker(
    visual_scores: Mapping[str, float],
    diarize_speaker: str,
    vad: float,
    *,
    confidence_threshold: float = ASD_CONFIDENCE_THRESHOLD,
) -> SpeakerVote:
    """Fuse visual ASD scores with the diarize turn + audio VAD into one vote.

    ``visual_scores`` maps a track/speaker id to its visual active-speaker score
    (mouth motion, 0..1). ``diarize_speaker`` is the id the audio diarizer
    attributes this frame to (``""`` = none). ``vad`` is the voice-activity
    energy 0..1 (low VAD = nobody is talking, so visual mouth motion is gesture
    noise, not speech). The fused confidence is the visual score gated by VAD and
    BOOSTED when the visual pick agrees with the diarizer (temporal correlation).
    Below ``confidence_threshold`` the vote is empty (``speaker=""``).
    """
    if not visual_scores:
        return SpeakerVote("", 0.0)
    best_id = max(visual_scores, key=lambda k: (visual_scores[k], k == diarize_speaker))
    base = float(visual_scores[best_id]) * float(vad)
    agree_bonus = 0.25 if best_id == diarize_speaker and diarize_speaker != "" else 0.0
    confidence = min(1.0, base + agree_bonus)
    if confidence < confidence_threshold:
        return SpeakerVote("", confidence)
    return SpeakerVote(best_id, confidence)


def resolve_speaker_track(votes: Sequence[SpeakerVote]) -> list[str]:
    """Turn per-frame votes into a committed speaker-per-frame track (HOLD rule).

    An empty (low-confidence) vote HOLDS the last committed speaker, so a brief
    ASD dropout does not blank the crop; before any confident vote exists the
    track stays ``""`` (the caller cold-starts via ``select_dominant``).
    """
    out: list[str] = []
    held = ""
    for vote in votes:
        if vote.speaker != "":
            held = vote.speaker
        out.append(held)
    return out


# --------------------------------------------------------------------------- #
# Layout decision + debounce (pure)
# --------------------------------------------------------------------------- #
def decide_layout(
    active_count: int,
    *,
    allow_split: bool = True,
    allow_composite: bool = True,
) -> str:
    """Map the number of simultaneously-active speakers to a layout class.

    0/1 -> ``"single"``; exactly 2 -> ``"split"`` (50-50 vertical); 3+ ->
    ``"composite"`` (host top + guests bottom). ``allow_split`` /
    ``allow_composite`` collapse the richer layouts back to ``"single"`` when a
    caller (or the source aspect) forbids them.
    """
    if active_count <= 1:
        return "single"
    if active_count == 2:
        return "split" if allow_split else "single"
    return "composite" if allow_composite else "single"


def debounce_layouts(raw: Sequence[str], min_dwell_frames: int) -> list[str]:
    """Suppress layout runs shorter than ``min_dwell_frames`` (anti-flicker).

    A run of a layout that lasts fewer than ``min_dwell_frames`` is overwritten
    with the previous COMMITTED layout, so a one-frame split flicker never causes
    a visible layout flip. The first run is always committed (there is nothing
    before it to hold). ``min_dwell_frames <= 1`` is the identity.
    """
    n = len(raw)
    if n == 0:
        return []
    if min_dwell_frames <= 1:
        return list(raw)
    # Find contiguous runs.
    runs: list[tuple[int, int, str]] = []
    start = 0
    for i in range(1, n):
        if raw[i] != raw[i - 1]:
            runs.append((start, i, raw[i - 1]))
            start = i
    runs.append((start, n, raw[n - 1]))
    out = list(raw)
    committed = runs[0][2]
    for run_start, run_end, label in runs:
        if run_end - run_start < min_dwell_frames:
            for i in range(run_start, run_end):
                out[i] = committed
        else:
            committed = label
            for i in range(run_start, run_end):
                out[i] = label
    return out


def layouts_to_segments(per_frame: Sequence[str]) -> tuple[Segment, ...]:
    """Collapse a per-frame layout label list into ``Segment`` runs.

    Only the three concrete :data:`~media_studio.features.reframe_eval.LAYOUTS`
    become segments; any other label (e.g. a ``"none"`` filler) is left as a gap
    (the R0 harness expands gaps back to ``"none"``).
    """
    segments: list[Segment] = []
    n = len(per_frame)
    i = 0
    while i < n:
        label = per_frame[i]
        j = i + 1
        while j < n and per_frame[j] == label:
            j += 1
        if label in LAYOUTS:
            segments.append(Segment(start_frame=i, end_frame=j, layout=label))
        i = j
    return tuple(segments)


def commit_cuts(
    shot_boundaries: Sequence[int],
    speaker_turn_frames: Sequence[int],
    total_frames: int,
) -> tuple[int, ...]:
    """Union shot boundaries with committed speaker turns into the HARD-CUT set.

    The crop hard-cuts (no pan) at EVERY shot boundary AND at every committed
    speaker turn; within a single-subject run it One-Euro pans instead. Frames
    outside ``(0, total_frames)`` are dropped; the result is sorted + de-duped.
    """
    if total_frames <= 0:
        raise MultiSpeakerReframeError("clip has no frames")
    cuts = {int(b) for b in (*shot_boundaries, *speaker_turn_frames) if 0 < int(b) < total_frames}
    return tuple(sorted(cuts))


def speaker_turn_frames(speaker_per_frame: Sequence[str]) -> tuple[int, ...]:
    """Frame indices where the committed active speaker changes (the turn cuts)."""
    return tuple(i for i in range(1, len(speaker_per_frame)) if speaker_per_frame[i] != speaker_per_frame[i - 1])


# --------------------------------------------------------------------------- #
# Compositor — ffmpeg filter_complex (pure)
# --------------------------------------------------------------------------- #
def _crop_scale_chain(region: Box, out_w: int, out_h: int, label: str) -> str:
    """One ``[0:v]crop=...,scale=...[label]`` chain for a source region."""
    x, y, w, h = region
    return f"[0:v]crop={int(w)}:{int(h)}:{int(x)}:{int(y)},scale={out_w}:{out_h}:flags=lanczos,setsar=1[{label}]"


def build_filter_complex(
    layout: str,
    regions: Sequence[Box],
    *,
    out_w: int,
    out_h: int,
) -> str:
    """Build the ``filter_complex`` for one layout block (single/split/composite).

    * ``single`` — 1 region cropped+scaled to ``out_w x out_h``.
    * ``split`` — 2 regions each scaled to ``out_w x out_h/2`` then ``vstack``ed
      (50-50 vertical split: speaker A on top, speaker B below).
    * ``composite`` — the host scaled to the top ``out_h/2``, the remaining
      guests tiled across the bottom ``out_h/2`` then ``vstack``ed under the host.

    The region count must match the layout (loud otherwise). The string contains
    no shell metacharacters — it is passed as a single ``-filter_complex`` argv.
    """
    if layout not in LAYOUTS:
        raise MultiSpeakerReframeError(f"unknown layout {layout!r}")
    regs = list(regions)
    if layout == "single":
        if len(regs) != 1:
            raise MultiSpeakerReframeError("single layout needs exactly 1 region")
        return _crop_scale_chain(regs[0], out_w, out_h, "v")
    if layout == "split":
        if len(regs) != 2:
            raise MultiSpeakerReframeError("split layout needs exactly 2 regions")
        half = out_h // 2
        top = _crop_scale_chain(regs[0], out_w, half, "a")
        bot = _crop_scale_chain(regs[1], out_w, half, "b")
        return f"{top};{bot};[a][b]vstack=inputs=2[v]"
    # composite: host on top, guests tiled across the bottom.
    if len(regs) < 2:
        raise MultiSpeakerReframeError("composite layout needs at least 2 regions")
    half = out_h // 2
    host = _crop_scale_chain(regs[0], out_w, half, "host")
    guests = regs[1:]
    guest_w = out_w // len(guests)
    chains = [host]
    labels = []
    for idx, region in enumerate(guests):
        label = f"g{idx}"
        chains.append(_crop_scale_chain(region, guest_w, half, label))
        labels.append(f"[{label}]")
    row = f"{''.join(labels)}hstack=inputs={len(guests)}[guests]"
    chains.append(row)
    chains.append("[host][guests]vstack=inputs=2[v]")
    return ";".join(chains)


def build_composite_argv(
    in_path: str,
    out_path: str,
    filter_complex: str,
    *,
    total_sec: float = 0.0,
    settings: dict[str, Any] | None = None,
) -> list[str]:
    """The ONE ffmpeg ``-filter_complex`` pass argv (libx264 + aac, faststart)."""
    _ = total_sec  # threaded to ffmpeg.run, not the argv
    return [
        ffmpeg.ffmpeg_path(settings),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        in_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "0:a?",
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


# --------------------------------------------------------------------------- #
# Heavy-ML seam (Protocol — NEVER imported at module load)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ShotAnalysis:
    """The heavy backend's per-clip analysis (one staged result bundle).

    * ``width``/``height``/``fps``/``total_frames`` — source geometry;
    * ``shot_boundaries`` — TransNetV2 (+PySceneDetect) cut frames;
    * ``boxes_per_frame`` — face boxes per sampled frame (for the IoU tracker);
    * ``visual_scores_per_frame`` — per-box visual ASD scores (Light-ASD);
    * ``diarize_per_frame`` — the audio diarizer's active id per frame;
    * ``vad_per_frame`` — voice-activity energy per frame.
    """

    width: int
    height: int
    fps: float
    total_frames: int
    shot_boundaries: tuple[int, ...]
    boxes_per_frame: tuple[tuple[Box, ...], ...]
    visual_scores_per_frame: tuple[tuple[float, ...], ...]
    diarize_per_frame: tuple[str, ...]
    vad_per_frame: tuple[float, ...]


class MultiSpeakerBackend(Protocol):
    """The slice of the heavy ML pipeline the pure director needs.

    A real impl is built lazily by :func:`_default_backend_factory`. Each stage
    method is called ONCE in order (shots -> faces+ASD -> diarize/VAD) and
    :meth:`release` is invoked BETWEEN stages so a 6 GB GPU never holds two
    models resident. Tests inject a fake whose methods return canned arrays — no
    torch, no cv2, no weights.
    """

    def analyze(
        self,
        media_path: str,
        *,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ShotAnalysis:
        """Run the staged pipeline and return the analysis bundle."""
        ...  # pragma: no cover - Protocol stub

    def release(self) -> None:
        """Free GPU memory held by the last stage (called between stages)."""
        ...  # pragma: no cover - Protocol stub


BackendFactory = Callable[[dict[str, Any]], MultiSpeakerBackend]
WhichFn = Callable[[str], str | None]
ModelsPresent = Callable[[dict[str, Any]], bool]


def _default_backend_factory(
    settings: dict[str, Any],
) -> MultiSpeakerBackend:  # pragma: no cover - prod seam (imports the heavy native stack)
    """Build the real backend (LAZY import inside the function)."""
    from .reframe_multispeaker_backend import RealMultiSpeakerBackend  # noqa: PLC0415 - heavy seam

    return RealMultiSpeakerBackend(settings)


def default_models_present(settings: dict[str, Any]) -> bool:
    """True when the Light-ASD weights are installed (no import, never raises).

    Mirrors ``scene_transnet.default_models_present``: any lookup failure (asset
    not registered, no asset machinery) degrades to ``False`` so the engine
    reports itself unavailable rather than crashing.
    """
    try:
        from ..assets import manifest  # noqa: PLC0415 - lazy: avoids a cycle
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(LIGHT_ASD_ASSET)
        if entry is None:
            return False
        mgr = AssetManager(settings_provider=lambda: settings)
        return mgr.installed_path(entry) is not None
    except Exception:  # noqa: BLE001 - missing asset machinery -> use fallback
        return False


def availability_reason(
    settings: dict[str, Any] | None = None,
    *,
    which: WhichFn = shutil.which,
    models_present: ModelsPresent | None = None,
) -> str | None:
    """``None`` when the engine can run, else a human reason (WSL / weights).

    WSL presence is the pure-PATH ``shutil.which`` probe (no subprocess — a
    half-installed WSL can hang ``wsl --status``). CUDA itself is probed inside
    the heavy backend; here the gate is the two cheap host checks the director
    can make without importing torch.
    """
    settings = settings or {}
    present = models_present or default_models_present
    if which("wsl") is None:
        return "WSL not found on PATH (wsl.exe missing — WSL/CUDA not installed?)"
    if not present(settings):
        return f"the {LIGHT_ASD_ASSET} weights are not installed"
    return None


def make_engine_degrade_notice(reason: str) -> dict[str, str]:
    """The DISTINCT engine-degrade notice (reuses the type, not the message).

    Unlike ``reframe_claudeshorts.make_degraded_notice`` (which hardcodes "used
    center crop"), this names the single-speaker fallback an AUTO multispeaker
    attempt took — same :data:`~reframe_claudeshorts.REFRAME_DEGRADED_NOTICE`
    type so the UI renders one degraded badge, distinct wording.
    """
    return {
        "type": _cs.REFRAME_DEGRADED_NOTICE,
        "message": ENGINE_DEGRADE_MESSAGE.format(reason=reason),
        "reason": reason,
    }


# --------------------------------------------------------------------------- #
# The pure director: analysis -> ReframeTrace (the R0/R2 contract)
# --------------------------------------------------------------------------- #
def _shot_dominant_center(boxes: Sequence[Box], width: int) -> float:
    """Cold-start crop centre for a shot with no confident speaker.

    Uses ``claudeshorts.select_dominant`` over the shot's first-frame faces
    (largest/most-prominent box), returning a normalised x in ``0..1``; falls
    back to frame centre (0.5) only when the shot truly had NO faces — this is
    the deterministic cold-start, never a silent center crop chosen blindly.
    """
    cands = [((x + w / 2.0) / float(width), float(w * h), 0.0) for (x, y, w, h) in boxes]
    cx = _cs.select_dominant(cands)
    return cx if cx is not None else 0.5


def build_trace(analysis: ShotAnalysis, *, aspect: str = DEFAULT_ASPECT) -> ReframeTrace:
    """Run the full pure director over a heavy-backend ``analysis``.

    Produces the :class:`~media_studio.features.reframe_eval.ReframeTrace` (shot
    boundaries, speaker-per-frame, layout segments, per-frame crops) that the R0
    eval harness scores and the R2 override layer edits. This is the heart of the
    engine and is 100% covered with synthetic analyses.
    """
    width, height, fps = analysis.width, analysis.height, analysis.fps
    total = analysis.total_frames
    if total <= 0:
        raise MultiSpeakerReframeError("analysis has no frames")
    _validate_lengths(analysis)
    crop_w, crop_h = _cs.crop_size(width, height, aspect)

    merged = merge_short_shots(analysis.shot_boundaries, total, fps=fps)
    spans = shot_spans(merged, total)
    tracker = MultiFaceTracker()

    speaker_per_frame: list[str] = []
    layout_raw: list[str] = []
    crops: list[tuple[float, float, float, float]] = []
    for start, end in spans:
        tracker.reset()  # MANDATORY crop reset at a shot boundary
        _render_shot(
            analysis,
            start,
            end,
            tracker=tracker,
            width=width,
            crop_w=crop_w,
            crop_h=crop_h,
            speaker_per_frame=speaker_per_frame,
            layout_raw=layout_raw,
            crops=crops,
        )

    dwell = max(1, int(round(LAYOUT_MIN_DWELL_SEC * fps)))
    layout_per_frame = debounce_layouts(layout_raw, dwell)
    segments = layouts_to_segments(layout_per_frame)
    return ReframeTrace(
        shot_boundaries=tuple(merged),
        speaker_per_frame=tuple(speaker_per_frame),
        segments=segments,
        crops=tuple(crops),
    )


def _validate_lengths(analysis: ShotAnalysis) -> None:
    """Every per-frame array must agree with ``total_frames`` (loud otherwise)."""
    total = analysis.total_frames
    if not (
        len(analysis.boxes_per_frame)
        == len(analysis.visual_scores_per_frame)
        == len(analysis.diarize_per_frame)
        == len(analysis.vad_per_frame)
        == total
    ):
        raise MultiSpeakerReframeError("analysis per-frame arrays must all equal total_frames")


def _render_shot(
    analysis: ShotAnalysis,
    start: int,
    end: int,
    *,
    tracker: MultiFaceTracker,
    width: int,
    crop_w: int,
    crop_h: int,
    speaker_per_frame: list[str],
    layout_raw: list[str],
    crops: list[tuple[float, float, float, float]],
) -> None:
    """Decide the speaker/layout/crop for one shot's frames (appends in place)."""
    # Pass 1: per-frame votes + tracked ids + concurrent-active count.
    votes: list[SpeakerVote] = []
    ids_per_frame: list[list[int]] = []
    active_per_frame: list[int] = []
    for frame in range(start, end):
        boxes = list(analysis.boxes_per_frame[frame])
        ids = tracker.update(boxes)
        ids_per_frame.append(ids)
        scores = {str(ids[i]): float(analysis.visual_scores_per_frame[frame][i]) for i in range(len(boxes))}
        votes.append(fuse_active_speaker(scores, analysis.diarize_per_frame[frame], analysis.vad_per_frame[frame]))
        active_per_frame.append(_concurrent_active(analysis, frame))
    committed = resolve_speaker_track(votes)

    # Cold-start: if the FIRST frame of the shot has no confident speaker, use the
    # deterministic dominant centre (select_dominant), NEVER a blind center crop.
    cold_center = _shot_dominant_center(analysis.boxes_per_frame[start], width)

    # Pass 2: per-frame layout + crop centre.
    centers: list[float] = []
    timestamps: list[float] = []
    for offset, frame in enumerate(range(start, end)):
        boxes = analysis.boxes_per_frame[frame]
        ids = ids_per_frame[offset]
        speaker = committed[offset]
        layout_raw.append(decide_layout(active_per_frame[offset]))
        speaker_per_frame.append(speaker)
        centers.append(_frame_center(speaker, ids, boxes, width, cold_center))
        timestamps.append(frame / float(analysis.fps))

    # HARD CUT at committed speaker turns: One-Euro smooth ONLY within a single-
    # speaker sub-run (a fresh smoother per run), so the crop jump-cuts to the new
    # speaker instead of panning across the gap between two people.
    for run_ts, run_cx in _split_at_turns(timestamps, centers, committed):
        for cx in smooth_centers_one_euro(run_ts, run_cx):
            x = _cs.crop_x_for_center(cx, crop_w, width)
            crops.append((float(x), 0.0, float(crop_w), float(crop_h)))


def _split_at_turns(
    timestamps: Sequence[float],
    centers: Sequence[float],
    committed: Sequence[str],
) -> list[tuple[list[float], list[float]]]:
    """Split a shot's frames into single-speaker runs at committed turn cuts."""
    turns = set(speaker_turn_frames(committed))
    runs: list[tuple[list[float], list[float]]] = []
    cur_ts: list[float] = []
    cur_cx: list[float] = []
    for i, (t, c) in enumerate(zip(timestamps, centers, strict=True)):
        if i in turns:
            runs.append((cur_ts, cur_cx))
            cur_ts, cur_cx = [], []
        cur_ts.append(t)
        cur_cx.append(c)
    runs.append((cur_ts, cur_cx))
    return runs


def _concurrent_active(analysis: ShotAnalysis, frame: int) -> int:
    """Count the speakers simultaneously talking in ``frame`` (drives the layout).

    A track is concurrently-active when its VAD-gated visual ASD score clears
    :data:`ASD_CONFIDENCE_THRESHOLD` (visual mouth motion AND voice activity).
    2 concurrent talkers -> a 50-50 split; 3+ -> host+guests composite; 0/1 ->
    a single tracked crop.
    """
    vad = float(analysis.vad_per_frame[frame])
    return sum(1 for score in analysis.visual_scores_per_frame[frame] if float(score) * vad >= ASD_CONFIDENCE_THRESHOLD)


def _frame_center(
    speaker: str,
    ids: Sequence[int],
    boxes: Sequence[Box],
    width: int,
    cold_center: float,
) -> float:
    """Normalised crop centre for one frame given the committed speaker.

    When the committed speaker's track is visible this frame, centre on its box;
    otherwise (speaker held through a dropout, or cold-start) use the shot's
    deterministic dominant centre.
    """
    if speaker != "":
        for tid, box in zip(ids, boxes, strict=True):
            if str(tid) == speaker:
                x, _y, w, _h = box
                return (x + w / 2.0) / float(width)
    return cold_center


# --------------------------------------------------------------------------- #
# Render orchestration (atomic temp write; OOM cleanup; staged + freed backend)
# --------------------------------------------------------------------------- #
ReframeRunner = Callable[..., int]  # ffmpeg.run-shaped
ReplaceFn = Callable[[str, str], None]
RemoveFn = Callable[[str], None]


class MultiSpeakerReframeEngine:
    """Engine 3 — the hybrid multi-speaker director (A4 ``reframe_multispeaker``).

    Same public ``reframe(in_path, out_path, aspect)`` interface as the other two
    engines, but it can emit multi-cut / split / composite output. All heavy
    seams are injectable: ``backend_factory`` (the staged ML pipeline), ``runner``
    (ffmpeg.run-shaped encode), ``single_speaker`` (the ``claudeshorts`` degrade
    target), ``which`` / ``models_present`` (availability probes), and the
    atomic-write seams (``replace_fn`` / ``remove_fn``).

    ``allow_degrade`` chooses the failure contract: ``False`` (default, EXPLICIT
    request) raises :class:`MultiSpeakerUnavailableError` when the host can't run
    it; ``True`` (AUTO-attempt) degrades to the single-speaker engine + a loud
    :func:`make_engine_degrade_notice`.
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        allow_degrade: bool = False,
        runner: ReframeRunner | None = None,
        backend_factory: BackendFactory | None = None,
        single_speaker: Any | None = None,
        which: WhichFn = shutil.which,
        models_present: ModelsPresent | None = None,
        replace_fn: ReplaceFn = os.replace,
        remove_fn: RemoveFn = os.remove,
    ) -> None:
        self._settings = settings or {}
        self._allow_degrade = bool(allow_degrade)
        self._runner: ReframeRunner = runner if runner is not None else ffmpeg.run
        self._backend_factory: BackendFactory = backend_factory or _default_backend_factory
        self._single = single_speaker if single_speaker is not None else _cs.ClaudeShortsReframeEngine(self._settings)
        self._which = which
        self._models_present = models_present or default_models_present
        self._replace = replace_fn
        self._remove = remove_fn

    def reframe(
        self,
        in_path: str,
        out_path: str,
        aspect: str = DEFAULT_ASPECT,
        on_progress: Callable[[float, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_notice: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
        """Reframe ``in_path`` -> vertical ``out_path`` (multi-cut/split/composite).

        Failure contract: offline-mode + no cached weights -> :class:`OfflineError`;
        host can't run it + explicit -> :class:`MultiSpeakerUnavailableError`; host
        can't run it + ``allow_degrade`` -> single-speaker fallback + notice; an
        OOM/encode failure -> :class:`MultiSpeakerRenderError` with the partial
        output removed (atomic temp write, renamed on success only).
        """
        reason = availability_reason(self._settings, which=self._which, models_present=self._models_present)
        if reason is not None:
            return self._handle_unavailable(in_path, out_path, aspect, reason, on_progress, should_cancel, on_notice)
        return self._render(in_path, out_path, aspect, on_progress, should_cancel)

    def _handle_unavailable(
        self,
        in_path: str,
        out_path: str,
        aspect: str,
        reason: str,
        on_progress: Callable[[float, str], None] | None,
        should_cancel: Callable[[], bool] | None,
        on_notice: Callable[[dict[str, str]], None] | None,
    ) -> str:
        """Apply the failure contract for an unavailable host."""
        # Offline mode is a DIFFERENT, actionable cause than a missing GPU — only
        # raise OfflineError when offline mode is actually on (correct message).
        _offline.guard_network(self._settings, "the multi-speaker reframe models")
        if not self._allow_degrade:
            raise MultiSpeakerUnavailableError(f"multi-speaker reframe engine requested but unavailable: {reason}")
        if on_notice is not None:
            on_notice(make_engine_degrade_notice(reason))
        _log.info("multispeaker unavailable (%s); degrading to single-speaker", reason)
        return self._single.reframe(
            in_path, out_path, aspect, on_progress=on_progress, should_cancel=should_cancel, on_notice=on_notice
        )

    def _render(
        self,
        in_path: str,
        out_path: str,
        aspect: str,
        on_progress: Callable[[float, str], None] | None,
        should_cancel: Callable[[], bool] | None,
    ) -> str:
        """Run the staged backend + pure director + ONE atomic ffmpeg pass."""
        backend = self._backend_factory(self._settings)
        try:
            analysis = backend.analyze(in_path, on_progress=on_progress, should_cancel=should_cancel)
        finally:
            backend.release()  # free GPU between stages (6 GB ceiling)
        trace = build_trace(analysis, aspect=aspect)
        out_w, out_h = _aspect.output_dimensions(aspect)
        # build_trace always emits one crop per frame for a non-empty analysis, so
        # crops[0] is the opening committed-speaker region. The v1 encode renders
        # that tracked single crop in ONE 9:16 pass (a faithful, never-corrupt
        # output); per-segment split/composite compositing across the timeline
        # (build_filter_complex's split/composite primitives, unit-tested) is the
        # GPU-tier wiring — see the WU brief's operator note.
        crop_box: Box = trace.crops[0]
        filter_complex = build_filter_complex("single", [crop_box], out_w=out_w, out_h=out_h)
        total_sec = analysis.total_frames / float(analysis.fps)
        return self._encode(in_path, out_path, filter_complex, total_sec, on_progress, should_cancel)

    def _encode(
        self,
        in_path: str,
        out_path: str,
        filter_complex: str,
        total_sec: float,
        on_progress: Callable[[float, str], None] | None,
        should_cancel: Callable[[], bool] | None,
    ) -> str:
        """Encode to a temp path; atomically rename on success, clean up on failure.

        The temp path PRESERVES the output extension (``out.multispeaker.part.mp4``,
        not ``out.mp4.part``) so ffmpeg can still infer the muxer from it — a
        ``.part`` suffix has no recognized format and ffmpeg fails with EINVAL.
        """
        root, ext = os.path.splitext(out_path)
        tmp_path = f"{root}.multispeaker.part{ext or '.mp4'}"
        argv = build_composite_argv(in_path, tmp_path, filter_complex, settings=self._settings)
        try:
            code = self._runner(argv, total_sec=total_sec, on_progress=on_progress, should_cancel=should_cancel)
        except Exception as exc:  # noqa: BLE001 - OOM/native crash mid-encode
            self._cleanup(tmp_path)
            raise MultiSpeakerRenderError(f"multi-speaker reframe failed mid-render: {exc}") from exc
        if code != 0:
            self._cleanup(tmp_path)
            raise MultiSpeakerRenderError(f"multi-speaker reframe failed (exit {code}) for {out_path}")
        self._replace(tmp_path, out_path)  # atomic: no corrupt half-clip at out_path
        return out_path

    def _cleanup(self, tmp_path: str) -> None:
        """Remove a partial temp output (best-effort; never masks the real failure)."""
        with contextlib.suppress(OSError):
            self._remove(tmp_path)


# --------------------------------------------------------------------------- #
# Asset registration (F3c — pinned; mirrors scene_transnet's honest no-op)
# --------------------------------------------------------------------------- #
def register_multispeaker_assets() -> None:
    """Register the Light-ASD weights as an on-demand HF asset (idempotent).

    F3c (NON-NEGOTIABLE): every weight enters the manifest with a PINNED
    ``hf_revision`` (a 40-hex commit), never a moving branch/tag, and NEVER via
    gdown / torch.hub / Google-Drive / git-clone (those bypass integrity
    pinning). Light-ASD (``TaoRuijie/Light-ASD``, the design's visual ASD) ships
    its weights in the GitHub repo, not on the HF hub, so a loader-compatible HF
    MIRROR + its pinned commit hash must be confirmed by an operator before the
    entry can be registered — exactly the live ``scene_transnet`` precedent
    (a dead/unverified pin is worse than an honest "unavailable").

    Until that mirror is confirmed this is intentionally a NO-OP:
    :func:`default_models_present` honestly reports the engine unavailable, so the
    pure layer + seam ship and the GPU tier is an OPERATOR-BLOCKER (it is never
    silently marked validated). OPERATOR ACTION: confirm an HF mirror is
    loader-compatible, then register::

        from ..assets.manifest import register_asset, AssetEntry
        register_asset(AssetEntry(
            name=LIGHT_ASD_ASSET, kind="model", size_mb=LIGHT_ASD_SIZE_MB,
            label="Light-ASD (visual active-speaker detection)",
            installer="hf", hf_repo="<loader-compatible mirror>",
            hf_revision="<full 40-hex commit>",
        ))
    """
    # Intentionally a no-op until a loader-compatible, commit-pinned HF mirror is
    # confirmed (see docstring + docs/WU-R1-MULTISPEAKER-ENGINE.md operator note).
    return


register_multispeaker_assets()


__all__ = [
    "ASD_CONFIDENCE_THRESHOLD",
    "DEAD_ZONE_FRAC",
    "DEFAULT_ASPECT",
    "ENGINE_DEGRADE_MESSAGE",
    "ENGINE_NAME",
    "LAYOUT_MIN_DWELL_SEC",
    "LIGHT_ASD_ASSET",
    "LIGHT_ASD_REPO",
    "MIN_SHOT_SEC",
    "TRACK_IOU_THRESHOLD",
    "Box",
    "BackendFactory",
    "MultiFaceTracker",
    "MultiSpeakerBackend",
    "MultiSpeakerReframeEngine",
    "MultiSpeakerReframeError",
    "MultiSpeakerRenderError",
    "MultiSpeakerUnavailableError",
    "OneEuroFilter",
    "ShotAnalysis",
    "SpeakerVote",
    "availability_reason",
    "build_composite_argv",
    "build_filter_complex",
    "build_trace",
    "commit_cuts",
    "debounce_layouts",
    "decide_layout",
    "default_models_present",
    "fuse_active_speaker",
    "layouts_to_segments",
    "make_engine_degrade_notice",
    "merge_short_shots",
    "register_multispeaker_assets",
    "resolve_speaker_track",
    "shot_spans",
    "smooth_centers_one_euro",
    "speaker_turn_frames",
]
