"""Reframe ML eval harness (WU R0 — the regression gate R1 must clear).

This is the **PURE, dependency-free** scoring layer for the multi-speaker reframe
engine (see basic-memory ``reframe-multi-speaker-engine-approach-decided-hybrid``
and ``docs/V1.1-FEATURES.md`` §GATE-2). It compares an engine's per-clip output
trace against a labelled golden reference and emits an objective metric report
plus a PASS/FAIL gate verdict. R1 may only promote the hybrid engine to a default
once a run of this harness on the golden set ``passed``.

Two tiers, by design (``docs/WU-R0-EVAL-HARNESS.md``):

  * **Pure tier (this module + ``test_reframe_eval.py``):** every metric runs on
    canned / synthetic, path-injected fixtures and is wired into the 100%
    line+branch coverage gate. NO torch / cv2 / model import, NO real video, and
    crucially NO private third-party bytes — the golden clips are never required.
  * **GPU / real-frame tier (``test_reframe_eval_golden_e2e.py``, ``@e2e``):**
    opt-in, EXCLUDED from the coverage gate (``addopts = -m 'not e2e'``), and
    auto-skipped via a collection guard when the gitignored golden path
    (``REFRAME_GOLDEN_DIR``) is absent. It exercises the harness against the real
    OpusClip golden set on a machine that has it.

The six metrics (``docs/WU-R0-EVAL-HARNESS.md`` pins the exact data contract):

  * ``shot_boundary_f1`` — cut-detection F1 with a ±N-frame match tolerance;
  * ``layout_match_accuracy`` — per-frame single/split/composite label agreement;
  * ``switch_latency`` — ms lag of predicted speaker/layout switches vs reference;
  * ``static_shot_jitter`` — mean per-frame crop-centre travel (must NOT regress
    the current engine — :data:`STATIC_JITTER_BASELINE`, captured deterministically);
  * ``crop_iou`` — intersection-over-union of a predicted crop vs a reference rect;
  * ``speaker_attribution_accuracy`` — per-frame active-speaker label agreement.

Failures are LOUD: a malformed trace raises :class:`HarnessError` (never a silent
neutral score).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import IO, Any

#: The three layout classes a per-segment decision may emit (plus the implicit
#: ``"none"`` filler for frames no segment covers).
LAYOUTS: tuple[str, ...] = ("single", "split", "composite")
_NO_LAYOUT = "none"

#: Default frame rate used to convert switch-frame deltas to milliseconds when a
#: caller does not pin one (the OpusClip golden set is 30 fps).
DEFAULT_FPS = 30.0

# --------------------------------------------------------------------------- #
# Captured current-engine baseline (deterministic — NOT a hand-waved "~0.9").
#
# ``STATIC_JITTER_BASELINE`` is the mean per-frame crop-centre travel that the
# SHIPPED single-speaker engine (``reframe_claudeshorts.smooth_centers``)
# produces on the canonical talking-head sway track below, at 1920x1080 -> 9:16.
# The hybrid engine must NOT exceed it (``static_jitter_max`` gate). The value is
# an exact rational of integer pixel positions, so it is byte-reproducible across
# platforms. ``test_reframe_eval.py`` RE-DERIVES it from the real current engine
# and asserts equality, so a change to the smoother trips the guard rather than
# silently drifting the gate. (See ``docs/WU-R0-EVAL-HARNESS.md``.)
# --------------------------------------------------------------------------- #

#: The canonical reference sway: a seated talking head drifting ±0.03 (normalised
#: x) sinusoidally — sustained motion the median pre-filter does NOT erase, so the
#: baseline reflects the smoother's true residual rather than a trivial 0.0.
BASELINE_SWAY_CENTERS: tuple[float, ...] = tuple(round(0.5 + 0.03 * math.sin(i / 3.0), 4) for i in range(24))
#: Source geometry the baseline (and its regression guard) is computed at.
BASELINE_SOURCE_WIDTH = 1920
BASELINE_SOURCE_HEIGHT = 1080
#: The captured value (see module docstring + WU brief).
STATIC_JITTER_BASELINE = 3.1739130434782608

#: Objective gate thresholds (deterministic; rationale in ``docs/WU-R0-EVAL-HARNESS.md``).
GATE_THRESHOLDS: dict[str, float] = {
    "shot_f1_min": 0.90,  # design note: shot-boundary F1 >= ~0.9
    "layout_match_min": 0.85,  # per-frame layout agreement floor
    "switch_latency_max_ms": 150.0,  # design note: switch latency < 150 ms
    "speaker_attr_min": 0.80,  # active-speaker accuracy, within tolerance of OpusClip
    "crop_iou_min": 0.60,  # crop overlap vs the reference rect
    "static_jitter_max": STATIC_JITTER_BASELINE,  # must not regress the current engine
}


class HarnessError(ValueError):
    """A trace/contract violation — raised LOUDLY (never a silent neutral score)."""


# --------------------------------------------------------------------------- #
# Data contract (the committed shapes — see docs/WU-R0-EVAL-HARNESS.md)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Segment:
    """A contiguous ``[start_frame, end_frame)`` run rendered with one ``layout``."""

    start_frame: int
    end_frame: int
    layout: str


@dataclass(frozen=True)
class ReframeTrace:
    """One clip's engine output (or golden reference) — the harness compares two.

    * ``shot_boundaries`` — frame indices of detected hard cuts;
    * ``speaker_per_frame`` — the active-speaker id per frame (``""`` = none);
    * ``segments`` — the per-segment layout decisions (gaps default to ``"none"``);
    * ``crops`` — the per-frame crop rectangle ``(x, y, w, h)``.
    """

    shot_boundaries: tuple[int, ...]
    speaker_per_frame: tuple[str, ...]
    segments: tuple[Segment, ...]
    crops: tuple[tuple[float, float, float, float], ...]

    @classmethod
    def from_dict(cls, raw: Any) -> ReframeTrace:
        """Validate + parse a JSON-shaped trace object (loud on any bad shape)."""
        if not isinstance(raw, Mapping):
            raise HarnessError("trace must be a JSON object")
        return cls(
            shot_boundaries=tuple(_int_list(raw.get("shotBoundaries", []), "shotBoundaries")),
            speaker_per_frame=tuple(_str_list(raw.get("speakerPerFrame", []), "speakerPerFrame")),
            segments=tuple(_segments(raw.get("segments", []))),
            crops=tuple(_crops(raw.get("crops", []))),
        )


def _seq(value: Any, field: str) -> list[Any]:
    """A JSON array (reject scalars and the str/bytes 'iterables')."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise HarnessError(f"{field} must be an array")
    return list(value)


def _as_int(value: Any, field: str) -> int:
    """Coerce a JSON number to ``int`` (loud on a non-numeric/boolean value)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HarnessError(f"{field} entries must be integers")
    return int(value)


def _as_float(value: Any, field: str) -> float:
    """Coerce a JSON number to ``float`` (loud on a non-numeric/boolean value)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HarnessError(f"{field} entries must be numbers")
    return float(value)


def _int_list(value: Any, field: str) -> list[int]:
    return [_as_int(v, field) for v in _seq(value, field)]


def _str_list(value: Any, field: str) -> list[str]:
    out: list[str] = []
    for v in _seq(value, field):
        if not isinstance(v, str):
            raise HarnessError(f"{field} entries must be strings")
        out.append(v)
    return out


def _segments(value: Any) -> list[Segment]:
    out: list[Segment] = []
    for item in _seq(value, "segments"):
        if not isinstance(item, Mapping):
            raise HarnessError("each segment must be an object")
        layout = item.get("layout")
        if layout not in LAYOUTS:
            raise HarnessError(f"segment layout must be one of {LAYOUTS}")
        out.append(
            Segment(
                start_frame=_as_int(item.get("startFrame"), "segment.startFrame"),
                end_frame=_as_int(item.get("endFrame"), "segment.endFrame"),
                layout=layout,
            )
        )
    return out


def _crops(value: Any) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    for rect in _seq(value, "crops"):
        nums = _seq(rect, "crop")
        if len(nums) != 4:
            raise HarnessError("each crop must be [x, y, w, h]")
        x, y, w, h = (_as_float(n, "crop") for n in nums)
        out.append((x, y, w, h))
    return out


# --------------------------------------------------------------------------- #
# Metrics (pure)
# --------------------------------------------------------------------------- #


def shot_boundary_f1(
    predicted: Sequence[int],
    reference: Sequence[int],
    *,
    tolerance: int = 2,
) -> dict[str, float]:
    """Precision/recall/F1 of cut detection with a ±``tolerance``-frame match.

    Greedy one-to-one matching: each reference boundary claims the nearest
    not-yet-used predicted boundary within ``tolerance`` frames. Returns the
    counts (``tp/fp/fn``) alongside ``precision``/``recall``/``f1``.
    """
    if tolerance < 0:
        raise HarnessError("tolerance must be >= 0")
    pred = sorted(int(p) for p in predicted)
    ref = sorted(int(r) for r in reference)
    used = [False] * len(pred)
    tp = 0
    for r in ref:
        best_idx = -1
        best_dist = -1
        for i, p in enumerate(pred):
            if used[i]:
                continue
            dist = abs(p - r)
            if dist <= tolerance and (best_idx < 0 or dist < best_dist):
                best_idx, best_dist = i, dist
        if best_idx >= 0:
            used[best_idx] = True
            tp += 1
    fp = len(pred) - tp
    fn = len(ref) - tp
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(ref) if ref else 0.0
    denom = precision + recall
    f1 = (2.0 * precision * recall / denom) if denom > 0.0 else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": float(tp),
        "fp": float(fp),
        "fn": float(fn),
    }


def crop_iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Intersection-over-union of two ``(x, y, w, h)`` rectangles (0.0 if disjoint)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw < 0 or ah < 0 or bw < 0 or bh < 0:
        raise HarnessError("crop dimensions must be non-negative")
    inter_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = inter_w * inter_h
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0.0 else 0.0


def static_shot_jitter(crops: Sequence[tuple[float, float, float, float]]) -> float:
    """Mean Euclidean per-frame crop-centre travel (lower = stiller; 0 if < 2 frames)."""
    centers = [(x + w / 2.0, y + h / 2.0) for (x, y, w, h) in crops]
    if len(centers) < 2:
        return 0.0
    total = sum(
        math.hypot(centers[i + 1][0] - centers[i][0], centers[i + 1][1] - centers[i][1])
        for i in range(len(centers) - 1)
    )
    return total / (len(centers) - 1)


def segments_to_per_frame(segments: Sequence[Segment], total_frames: int) -> list[str]:
    """Expand ``segments`` into a per-frame layout label list (gaps = ``"none"``).

    Raises on an out-of-range or overlapping segment (an engine must emit a clean
    partition); uncovered frames keep the ``"none"`` filler.
    """
    if total_frames < 0:
        raise HarnessError("total_frames must be >= 0")
    labels = [_NO_LAYOUT] * total_frames
    for seg in segments:
        if seg.start_frame < 0 or seg.end_frame > total_frames or seg.start_frame >= seg.end_frame:
            raise HarnessError("segment out of range or non-positive length")
        for frame in range(seg.start_frame, seg.end_frame):
            if labels[frame] != _NO_LAYOUT:
                raise HarnessError("overlapping segments")
            labels[frame] = seg.layout
    return labels


def layout_match_accuracy(predicted: Sequence[str], reference: Sequence[str]) -> float:
    """Fraction of frames whose layout label matches (0.0 for an empty reference)."""
    if len(predicted) != len(reference):
        raise HarnessError("layout label length mismatch")
    if not reference:
        return 0.0
    matches = sum(1 for p, r in zip(predicted, reference, strict=True) if p == r)
    return matches / len(reference)


def speaker_attribution_accuracy(predicted: Sequence[str], reference: Sequence[str]) -> float:
    """Fraction of frames whose active-speaker label matches (0.0 for empty ref)."""
    if len(predicted) != len(reference):
        raise HarnessError("speaker label length mismatch")
    if not reference:
        return 0.0
    matches = sum(1 for p, r in zip(predicted, reference, strict=True) if p == r)
    return matches / len(reference)


def switch_frames(labels: Sequence[str]) -> list[int]:
    """Frame indices where a per-frame label changes from the previous frame."""
    return [i for i in range(1, len(labels)) if labels[i] != labels[i - 1]]


def switch_latency(
    predicted_switches: Sequence[int],
    reference_switches: Sequence[int],
    *,
    fps: float = DEFAULT_FPS,
) -> dict[str, Any]:
    """Per-reference-switch lag (ms) to the nearest predicted switch.

    A reference switch with NO predicted switch at all scores ``inf`` ms (a missed
    cut is the worst case, not a free pass). ``withinThreshold`` checks the worst
    latency against :data:`GATE_THRESHOLDS`'s ``switch_latency_max_ms``.
    """
    if fps <= 0.0:
        raise HarnessError("fps must be > 0")
    pred = sorted(int(p) for p in predicted_switches)
    latencies: list[float] = []
    for r in reference_switches:
        if pred:
            nearest = min(pred, key=lambda p: abs(p - r))
            latencies.append(abs(nearest - r) / fps * 1000.0)
        else:
            latencies.append(math.inf)
    max_ms = max(latencies) if latencies else 0.0
    mean_ms = sum(latencies) / len(latencies) if latencies else 0.0
    return {
        "latenciesMs": latencies,
        "maxMs": max_ms,
        "meanMs": mean_ms,
        "withinThreshold": max_ms <= GATE_THRESHOLDS["switch_latency_max_ms"],
    }


def mean_crop_iou(
    predicted: Sequence[tuple[float, float, float, float]],
    reference: Sequence[tuple[float, float, float, float]],
) -> float:
    """Mean per-frame crop IoU (0.0 for an empty reference; loud on length mismatch)."""
    if len(predicted) != len(reference):
        raise HarnessError("crop length mismatch")
    if not reference:
        return 0.0
    return sum(crop_iou(p, r) for p, r in zip(predicted, reference, strict=True)) / len(reference)


# --------------------------------------------------------------------------- #
# Aggregation + gate
# --------------------------------------------------------------------------- #


def _ge(value: float, threshold: float) -> dict[str, Any]:
    return {"value": value, "threshold": threshold, "passed": value >= threshold}


def _le(value: float, threshold: float) -> dict[str, Any]:
    return {"value": value, "threshold": threshold, "passed": value <= threshold}


def run_harness(
    predicted: ReframeTrace,
    reference: ReframeTrace,
    *,
    fps: float = DEFAULT_FPS,
) -> dict[str, Any]:
    """Compute every metric for ``predicted`` vs ``reference`` + the gate verdict.

    The reference defines the canonical frame count; the predicted trace must
    agree (loud otherwise). ``passed`` is the AND of every gate check — R1 may
    promote the hybrid engine to a default only when a golden-set run ``passed``.
    """
    total_frames = len(reference.speaker_per_frame)
    metrics: dict[str, Any] = {
        "shotBoundaryF1": shot_boundary_f1(predicted.shot_boundaries, reference.shot_boundaries),
        "layoutMatch": layout_match_accuracy(
            segments_to_per_frame(predicted.segments, total_frames),
            segments_to_per_frame(reference.segments, total_frames),
        ),
        "switchLatency": switch_latency(
            switch_frames(predicted.speaker_per_frame),
            switch_frames(reference.speaker_per_frame),
            fps=fps,
        ),
        "staticJitter": static_shot_jitter(predicted.crops),
        "cropIoU": mean_crop_iou(predicted.crops, reference.crops),
        "speakerAttribution": speaker_attribution_accuracy(predicted.speaker_per_frame, reference.speaker_per_frame),
    }
    gate = {
        "shotF1": _ge(metrics["shotBoundaryF1"]["f1"], GATE_THRESHOLDS["shot_f1_min"]),
        "layoutMatch": _ge(metrics["layoutMatch"], GATE_THRESHOLDS["layout_match_min"]),
        "switchLatency": _le(metrics["switchLatency"]["maxMs"], GATE_THRESHOLDS["switch_latency_max_ms"]),
        "speakerAttribution": _ge(metrics["speakerAttribution"], GATE_THRESHOLDS["speaker_attr_min"]),
        "cropIoU": _ge(metrics["cropIoU"], GATE_THRESHOLDS["crop_iou_min"]),
        "staticJitter": _le(metrics["staticJitter"], GATE_THRESHOLDS["static_jitter_max"]),
    }
    return {
        "metrics": metrics,
        "gate": gate,
        "passed": all(check["passed"] for check in gate.values()),
        "thresholds": dict(GATE_THRESHOLDS),
    }


# --------------------------------------------------------------------------- #
# RPC (pure compose) + CLI (heavy engine run behind an injected seam)
# --------------------------------------------------------------------------- #


def register(*, register_fn: Callable[[str, Callable[..., Any]], None]) -> None:
    """Register ``reframe.eval`` — pure trace-vs-reference scoring over the wire.

    ``register_fn`` is ``protocol.register`` in production; tests pass a fake
    registrar. The heavy real-frame engine run is NOT here — the wire path scores
    two already-computed traces (the engine produces the predicted trace
    out-of-band; the GPU tier wires that in R1).
    """

    def reframe_eval(params: dict[str, Any], _ctx: Any) -> dict[str, Any]:
        """``reframe.eval({predicted, reference, fps?})`` -> the metric report."""
        try:
            predicted = ReframeTrace.from_dict(params.get("predicted"))
            reference = ReframeTrace.from_dict(params.get("reference"))
            fps = _as_float(params.get("fps", DEFAULT_FPS), "fps")
            return run_harness(predicted, reference, fps=fps)
        except HarnessError as exc:
            from ..protocol import ErrorCode, RpcError

            raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc

    register_fn("reframe.eval", reframe_eval)


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def default_engine_runner(source: str, engine: str) -> dict[str, Any]:
    """The seam for ``--source --engine`` — UNWIRED at R0 (raises loudly).

    Running a real engine on real frames is the GPU/real-frame tier; R1 wires a
    concrete runner here (or a test/caller injects one). At R0 the CLI's job is
    the pure scoring of an already-produced trace, so this fails loud rather than
    silently center-cropping or fabricating a trace.
    """
    raise HarnessError(
        f"no reframe engine runner wired for source={source!r} engine={engine!r} "
        "(R0: pass --predicted, inject a runner, or run the e2e/GPU tier)"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    out: IO[str] | None = None,
    engine_runner: Callable[[str, str], dict[str, Any]] | None = None,
) -> int:
    """CLI: score a predicted trace (or an engine run) vs a golden reference.

    ``--reference R --predicted P`` scores two trace files. ``--reference R
    --source V --engine E`` runs ``engine_runner`` (the heavy seam) to produce the
    predicted trace first. Emits the JSON report to ``--out`` (or stdout) and
    returns ``0`` when the gate ``passed``, ``1`` when it did not, ``2`` on a
    usage error — usable directly as the R1 regression gate.
    """
    parser = argparse.ArgumentParser(
        prog="reframe-eval",
        description="Reframe ML eval harness (WU R0) — the regression gate R1 must clear.",
    )
    parser.add_argument("--reference", required=True, help="path to the golden reference trace JSON")
    parser.add_argument("--predicted", help="path to the engine's predicted trace JSON")
    parser.add_argument("--source", help="path to a source video (runs the engine seam)")
    parser.add_argument("--engine", help="engine name for --source (e.g. multispeaker)")
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS, help="frame rate (default 30)")
    parser.add_argument("--out", help="write the report here (default stdout)")
    args = parser.parse_args(argv)

    runner = engine_runner if engine_runner is not None else default_engine_runner
    reference = ReframeTrace.from_dict(_load_json(args.reference))
    if args.predicted is not None:
        predicted = ReframeTrace.from_dict(_load_json(args.predicted))
    elif args.source is not None:
        if args.engine is None:
            print("error: --source requires --engine", file=sys.stderr)
            return 2
        predicted = ReframeTrace.from_dict(runner(args.source, args.engine))
    else:
        print("error: one of --predicted or --source is required", file=sys.stderr)
        return 2

    report = run_harness(predicted, reference, fps=args.fps)
    text = json.dumps(report, indent=2)
    if args.out is not None:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text, file=out if out is not None else sys.stdout)
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - module CLI entry shim
    raise SystemExit(main())
