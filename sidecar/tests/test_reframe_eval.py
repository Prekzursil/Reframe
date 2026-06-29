"""Pure-tier tests for the Reframe ML eval harness (WU R0).

Every metric, the data-contract validators, the gate aggregation, the ``reframe.eval``
RPC, and the CLI run on canned/synthetic, path-injected fixtures — NO torch / cv2 /
real video / private golden bytes. This file IS the 100% line+branch coverage tier
for ``media_studio.features.reframe_eval``. The current-engine jitter baseline is
re-derived from the REAL shipped engine (``reframe_claudeshorts``) so a drift in the
smoother trips the guard rather than silently moving the gate.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any

import pytest
from media_studio.features import reframe_claudeshorts as cs
from media_studio.features import reframe_eval as re
from media_studio.protocol import ErrorCode, RpcError

# --------------------------------------------------------------------------- #
# Fixtures: a labelled reference trace + a perfect (passing) predicted trace.
# --------------------------------------------------------------------------- #

_REFERENCE: dict[str, Any] = {
    "shotBoundaries": [3],
    "speakerPerFrame": ["a", "a", "a", "b", "b", "b"],
    "segments": [
        {"startFrame": 0, "endFrame": 3, "layout": "single"},
        {"startFrame": 3, "endFrame": 6, "layout": "split"},
    ],
    "crops": [[100.0, 0.0, 608.0, 1080.0]] * 6,
}


def _trace(overrides: dict[str, Any] | None = None) -> re.ReframeTrace:
    raw = dict(_REFERENCE)
    if overrides:
        raw.update(overrides)
    return re.ReframeTrace.from_dict(raw)


# --------------------------------------------------------------------------- #
# Data contract validators
# --------------------------------------------------------------------------- #


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(re.HarnessError, match="object"):
        re.ReframeTrace.from_dict([1, 2, 3])


def test_from_dict_defaults_empty_fields() -> None:
    trace = re.ReframeTrace.from_dict({})
    assert trace.shot_boundaries == ()
    assert trace.speaker_per_frame == ()
    assert trace.segments == ()
    assert trace.crops == ()


def test_from_dict_parses_full_trace() -> None:
    trace = _trace()
    assert trace.shot_boundaries == (3,)
    assert trace.segments[0] == re.Segment(0, 3, "single")
    assert trace.crops[0] == (100.0, 0.0, 608.0, 1080.0)


@pytest.mark.parametrize("bad", ["scalar", 5, b"bytes"])
def test_seq_rejects_non_arrays(bad: Any) -> None:
    with pytest.raises(re.HarnessError, match="array"):
        re.ReframeTrace.from_dict({"shotBoundaries": bad})


def test_as_int_rejects_bool_and_non_numeric() -> None:
    with pytest.raises(re.HarnessError, match="integers"):
        re.ReframeTrace.from_dict({"shotBoundaries": [True]})
    with pytest.raises(re.HarnessError, match="integers"):
        re.ReframeTrace.from_dict({"shotBoundaries": ["3"]})


def test_int_list_accepts_int_and_float() -> None:
    trace = re.ReframeTrace.from_dict({"shotBoundaries": [3, 4.0]})
    assert trace.shot_boundaries == (3, 4)


def test_str_list_rejects_non_string() -> None:
    with pytest.raises(re.HarnessError, match="strings"):
        re.ReframeTrace.from_dict({"speakerPerFrame": [1]})


def test_segments_reject_non_mapping_item() -> None:
    with pytest.raises(re.HarnessError, match="object"):
        re.ReframeTrace.from_dict({"segments": [["nope"]]})


def test_segments_reject_unknown_layout() -> None:
    with pytest.raises(re.HarnessError, match="layout"):
        re.ReframeTrace.from_dict({"segments": [{"startFrame": 0, "endFrame": 1, "layout": "diagonal"}]})


def test_crops_reject_wrong_arity() -> None:
    with pytest.raises(re.HarnessError, match=r"\[x, y, w, h\]"):
        re.ReframeTrace.from_dict({"crops": [[1.0, 2.0, 3.0]]})


def test_as_float_rejects_bool() -> None:
    with pytest.raises(re.HarnessError, match="numbers"):
        re.ReframeTrace.from_dict({"crops": [[True, 0.0, 1.0, 1.0]]})


# --------------------------------------------------------------------------- #
# shot_boundary_f1
# --------------------------------------------------------------------------- #


def test_shot_f1_rejects_negative_tolerance() -> None:
    with pytest.raises(re.HarnessError, match="tolerance"):
        re.shot_boundary_f1([1], [1], tolerance=-1)


def test_shot_f1_perfect() -> None:
    out = re.shot_boundary_f1([10, 20], [10, 20])
    assert out["f1"] == 1.0
    assert out["tp"] == 2.0
    assert out["fp"] == 0.0
    assert out["fn"] == 0.0


def test_shot_f1_within_tolerance() -> None:
    out = re.shot_boundary_f1([12], [10], tolerance=2)
    assert out["tp"] == 1.0


def test_shot_f1_no_match_counts_fp_and_fn() -> None:
    out = re.shot_boundary_f1([100], [10])
    assert out["tp"] == 0.0
    assert out["fp"] == 1.0
    assert out["fn"] == 1.0
    assert out["f1"] == 0.0


def test_shot_f1_greedy_picks_closest_and_marks_used() -> None:
    # Two refs (10, 11) and two preds (11, 50): ref 10 should take pred 11 (dist 1)
    # over leaving it; ref 11 then finds none in tolerance -> tp=1.
    out = re.shot_boundary_f1([11, 50], [10, 11], tolerance=2)
    assert out["tp"] == 1.0
    # closeness preference: pred 9 and 11 both near ref 10; 11 is exact-ish — ensure
    # the closer (smaller dist) candidate is chosen via the dist<best_dist branch.
    out2 = re.shot_boundary_f1([7, 10], [10], tolerance=3)
    assert out2["tp"] == 1.0
    assert out2["fp"] == 1.0


def test_shot_f1_empty_inputs() -> None:
    out = re.shot_boundary_f1([], [])
    assert out["precision"] == 0.0
    assert out["recall"] == 0.0
    assert out["f1"] == 0.0


def test_shot_f1_empty_pred_only() -> None:
    out = re.shot_boundary_f1([], [5])
    assert out["recall"] == 0.0
    assert out["precision"] == 0.0


# --------------------------------------------------------------------------- #
# crop_iou
# --------------------------------------------------------------------------- #


def test_crop_iou_rejects_negative_dims() -> None:
    with pytest.raises(re.HarnessError, match="non-negative"):
        re.crop_iou((0.0, 0.0, -1.0, 1.0), (0.0, 0.0, 1.0, 1.0))


def test_crop_iou_identical() -> None:
    assert re.crop_iou((0.0, 0.0, 2.0, 2.0), (0.0, 0.0, 2.0, 2.0)) == 1.0


def test_crop_iou_partial_overlap() -> None:
    # 2x2 boxes overlapping in a 1x1 corner -> inter=1, union=7.
    assert re.crop_iou((0.0, 0.0, 2.0, 2.0), (1.0, 1.0, 2.0, 2.0)) == pytest.approx(1.0 / 7.0)


def test_crop_iou_disjoint_is_zero() -> None:
    assert re.crop_iou((0.0, 0.0, 1.0, 1.0), (10.0, 10.0, 1.0, 1.0)) == 0.0


def test_crop_iou_zero_area_is_zero() -> None:
    assert re.crop_iou((0.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 0.0)) == 0.0


# --------------------------------------------------------------------------- #
# static_shot_jitter
# --------------------------------------------------------------------------- #


def test_static_jitter_too_few_frames_is_zero() -> None:
    assert re.static_shot_jitter([]) == 0.0
    assert re.static_shot_jitter([(0.0, 0.0, 2.0, 2.0)]) == 0.0


def test_static_jitter_constant_track_is_zero() -> None:
    assert re.static_shot_jitter([(0.0, 0.0, 2.0, 2.0)] * 4) == 0.0


def test_static_jitter_moving_track() -> None:
    crops = [(0.0, 0.0, 2.0, 2.0), (3.0, 0.0, 2.0, 2.0), (3.0, 4.0, 2.0, 2.0)]
    # centre travels 3 then 4 -> mean 3.5.
    assert re.static_shot_jitter(crops) == pytest.approx(3.5)


def test_static_jitter_baseline_matches_current_engine() -> None:
    """The pinned baseline IS the shipped engine's residual on the sway track.

    Re-derive it from the REAL ``reframe_claudeshorts`` smoother + crop math; a
    change to the smoother must update :data:`STATIC_JITTER_BASELINE`, not drift
    the gate silently.
    """
    smoothed = cs.smooth_centers(re.BASELINE_SWAY_CENTERS)
    crop_w, crop_h = cs.crop_size(re.BASELINE_SOURCE_WIDTH, re.BASELINE_SOURCE_HEIGHT, "9:16")
    crops = [
        (float(cs.crop_x_for_center(c, crop_w, re.BASELINE_SOURCE_WIDTH)), 0.0, float(crop_w), float(crop_h))
        for c in smoothed
    ]
    assert re.static_shot_jitter(crops) == pytest.approx(re.STATIC_JITTER_BASELINE, abs=1e-9)
    assert re.GATE_THRESHOLDS["static_jitter_max"] == re.STATIC_JITTER_BASELINE


# --------------------------------------------------------------------------- #
# static_shot_jitter_within_segments (the segment-aware gate metric)
# --------------------------------------------------------------------------- #


def test_within_segment_jitter_empty_is_zero() -> None:
    """No segments -> no in-segment steps -> 0.0 (outer loop never runs)."""
    crops = [(0.0, 0.0, 2.0, 2.0), (100.0, 0.0, 2.0, 2.0)]
    assert re.static_shot_jitter_within_segments(crops, []) == 0.0


def test_within_segment_jitter_single_frame_segment_is_zero() -> None:
    """A one-frame segment has no internal step -> 0.0 (inner loop never runs)."""
    crops = [(0.0, 0.0, 2.0, 2.0), (100.0, 0.0, 2.0, 2.0)]
    assert re.static_shot_jitter_within_segments(crops, [re.Segment(0, 1, "single")]) == 0.0


def test_within_segment_jitter_single_segment_matches_whole_track() -> None:
    """One segment spanning every frame == the raw whole-track travel."""
    crops = [(0.0, 0.0, 2.0, 2.0), (3.0, 0.0, 2.0, 2.0), (3.0, 4.0, 2.0, 2.0)]
    seg = [re.Segment(0, len(crops), "single")]
    assert re.static_shot_jitter_within_segments(crops, seg) == pytest.approx(re.static_shot_jitter(crops))


def test_within_segment_jitter_excludes_cut_boundary() -> None:
    """The deliberate jump at a hard-cut boundary is NOT charged as jitter.

    Two stone-still segments separated by a large crop jump: the within-segment
    metric sees 0.0 (no motion inside either shot) even though the raw whole-track
    metric is huge — proving the boundary step is excluded.
    """
    crops = [(0.0, 0.0, 2.0, 2.0)] * 3 + [(1000.0, 0.0, 2.0, 2.0)] * 3
    segs = [re.Segment(0, 3, "single"), re.Segment(3, 6, "split")]
    assert re.static_shot_jitter_within_segments(crops, segs) == 0.0
    # The OLD whole-track metric WOULD have charged the boundary jump (and blown the gate).
    assert re.static_shot_jitter(crops) > re.GATE_THRESHOLDS["static_jitter_max"]


def test_within_segment_jitter_clamps_out_of_range_segment() -> None:
    """Segment bounds outside the crop range are clamped (length-mismatch safety)."""
    crops = [(0.0, 0.0, 2.0, 2.0), (4.0, 0.0, 2.0, 2.0)]
    # start<0 and end>len(crops): clamped to [0, 2) -> one 4.0 step.
    assert re.static_shot_jitter_within_segments(crops, [re.Segment(-5, 99, "single")]) == pytest.approx(4.0)


def test_gate_passes_clean_multi_cut_trace() -> None:
    """A multi-cut trace (still WITHIN each shot) now PASSES the jitter gate.

    Under the old whole-clip metric the deliberate boundary jumps would fail it;
    the segment-aware gate correctly passes it.
    """
    predicted = _trace(
        {
            "segments": [
                {"startFrame": 0, "endFrame": 3, "layout": "single"},
                {"startFrame": 3, "endFrame": 6, "layout": "split"},
            ],
            "crops": [[0.0, 0.0, 2.0, 2.0]] * 3 + [[900.0, 0.0, 2.0, 2.0]] * 3,
        }
    )
    report = re.run_harness(predicted, _trace())
    assert report["metrics"]["staticJitter"] == 0.0
    assert report["gate"]["staticJitter"]["passed"] is True


def test_gate_fails_jittery_single_segment() -> None:
    """A genuinely-wobbly single (uncut) segment STILL fails the jitter gate."""
    predicted = _trace(
        {
            "shotBoundaries": [],
            "segments": [{"startFrame": 0, "endFrame": 6, "layout": "single"}],
            "crops": [[float(10 * i), 0.0, 2.0, 2.0] for i in range(6)],
        }
    )
    report = re.run_harness(predicted, _trace())
    assert report["metrics"]["staticJitter"] > re.GATE_THRESHOLDS["static_jitter_max"]
    assert report["gate"]["staticJitter"]["passed"] is False


# --------------------------------------------------------------------------- #
# segments_to_per_frame
# --------------------------------------------------------------------------- #


def test_segments_to_per_frame_rejects_negative_total() -> None:
    with pytest.raises(re.HarnessError, match="total_frames"):
        re.segments_to_per_frame([], -1)


def test_segments_to_per_frame_with_gap() -> None:
    labels = re.segments_to_per_frame([re.Segment(0, 2, "single")], 4)
    assert labels == ["single", "single", "none", "none"]


@pytest.mark.parametrize(
    "seg",
    [
        re.Segment(-1, 2, "single"),  # start < 0
        re.Segment(0, 5, "single"),  # end > total
        re.Segment(2, 2, "single"),  # non-positive length
    ],
)
def test_segments_to_per_frame_out_of_range(seg: re.Segment) -> None:
    with pytest.raises(re.HarnessError, match="range"):
        re.segments_to_per_frame([seg], 4)


def test_segments_to_per_frame_overlap() -> None:
    segs = [re.Segment(0, 3, "single"), re.Segment(2, 4, "split")]
    with pytest.raises(re.HarnessError, match="overlap"):
        re.segments_to_per_frame(segs, 4)


# --------------------------------------------------------------------------- #
# layout / speaker accuracy
# --------------------------------------------------------------------------- #


def test_layout_match_length_mismatch() -> None:
    with pytest.raises(re.HarnessError, match="length"):
        re.layout_match_accuracy(["single"], ["single", "split"])


def test_layout_match_empty_is_zero() -> None:
    assert re.layout_match_accuracy([], []) == 0.0


def test_layout_match_partial() -> None:
    assert re.layout_match_accuracy(["single", "split"], ["single", "single"]) == 0.5


def test_speaker_accuracy_length_mismatch() -> None:
    with pytest.raises(re.HarnessError, match="length"):
        re.speaker_attribution_accuracy(["a"], ["a", "b"])


def test_speaker_accuracy_empty_is_zero() -> None:
    assert re.speaker_attribution_accuracy([], []) == 0.0


def test_speaker_accuracy_partial() -> None:
    assert re.speaker_attribution_accuracy(["a", "b"], ["a", "a"]) == 0.5


# --------------------------------------------------------------------------- #
# switch frames + latency
# --------------------------------------------------------------------------- #


def test_switch_frames() -> None:
    assert re.switch_frames([]) == []
    assert re.switch_frames(["a", "a", "b", "b", "a"]) == [2, 4]


def test_switch_latency_rejects_bad_fps() -> None:
    with pytest.raises(re.HarnessError, match="fps"):
        re.switch_latency([1], [1], fps=0.0)


def test_switch_latency_empty_reference() -> None:
    out = re.switch_latency([5], [], fps=30.0)
    assert out["maxMs"] == 0.0
    assert out["meanMs"] == 0.0
    assert out["withinThreshold"] is True


def test_switch_latency_nearest_within_threshold() -> None:
    out = re.switch_latency([10, 30], [11], fps=30.0)
    # nearest pred to ref 11 is 10 -> 1 frame / 30 fps = 33.3 ms.
    assert out["maxMs"] == pytest.approx(1000.0 / 30.0)
    assert out["withinThreshold"] is True


def test_switch_latency_over_threshold() -> None:
    out = re.switch_latency([0], [100], fps=30.0)
    assert out["maxMs"] > re.GATE_THRESHOLDS["switch_latency_max_ms"]
    assert out["withinThreshold"] is False


def test_switch_latency_missing_prediction_is_infinite() -> None:
    out = re.switch_latency([], [5], fps=30.0)
    assert out["latenciesMs"] == [math.inf]
    assert out["withinThreshold"] is False


# --------------------------------------------------------------------------- #
# mean_crop_iou
# --------------------------------------------------------------------------- #


def test_mean_crop_iou_length_mismatch() -> None:
    with pytest.raises(re.HarnessError, match="length"):
        re.mean_crop_iou([(0.0, 0.0, 1.0, 1.0)], [])


def test_mean_crop_iou_empty_is_zero() -> None:
    assert re.mean_crop_iou([], []) == 0.0


def test_mean_crop_iou_mean() -> None:
    pred = [(0.0, 0.0, 2.0, 2.0), (0.0, 0.0, 2.0, 2.0)]
    ref = [(0.0, 0.0, 2.0, 2.0), (10.0, 10.0, 2.0, 2.0)]
    assert re.mean_crop_iou(pred, ref) == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# run_harness + gate
# --------------------------------------------------------------------------- #


def test_run_harness_perfect_passes() -> None:
    report = re.run_harness(_trace(), _trace())
    assert report["passed"] is True
    assert report["metrics"]["shotBoundaryF1"]["f1"] == 1.0
    assert report["metrics"]["cropIoU"] == 1.0
    assert report["metrics"]["speakerAttribution"] == 1.0
    assert report["gate"]["staticJitter"]["passed"] is True
    assert report["thresholds"] == re.GATE_THRESHOLDS
    assert report["thresholds"] is not re.GATE_THRESHOLDS  # defensive copy


def test_run_harness_regression_fails_gate() -> None:
    predicted = _trace({"shotBoundaries": [], "crops": _REFERENCE["crops"]})
    report = re.run_harness(predicted, _trace())
    assert report["passed"] is False
    assert report["gate"]["shotF1"]["passed"] is False


# --------------------------------------------------------------------------- #
# reframe.eval RPC
# --------------------------------------------------------------------------- #


def _register() -> dict[str, Any]:
    registered: dict[str, Any] = {}
    re.register(register_fn=lambda name, handler: registered.__setitem__(name, handler))
    return registered


def test_register_wires_reframe_eval() -> None:
    registered = _register()
    assert set(registered) == {"reframe.eval"}


def test_reframe_eval_rpc_returns_report() -> None:
    handler = _register()["reframe.eval"]
    out = handler({"predicted": _REFERENCE, "reference": _REFERENCE, "fps": 30.0}, None)
    assert out["passed"] is True


def test_reframe_eval_rpc_defaults_fps() -> None:
    handler = _register()["reframe.eval"]
    out = handler({"predicted": _REFERENCE, "reference": _REFERENCE}, None)
    assert out["passed"] is True


def test_reframe_eval_rpc_bad_input_is_invalid_params() -> None:
    handler = _register()["reframe.eval"]
    with pytest.raises(RpcError) as excinfo:
        handler({"predicted": "nope", "reference": _REFERENCE}, None)
    assert excinfo.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _write(tmp_path: Path, name: str, payload: dict[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_default_engine_runner_unwired_raises() -> None:
    with pytest.raises(re.HarnessError, match="no reframe engine runner"):
        re.default_engine_runner("video.mp4", "multispeaker")


def test_cli_predicted_pass_returns_zero(tmp_path: Path) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    pred = _write(tmp_path, "pred.json", _REFERENCE)
    out = io.StringIO()
    rc = re.main(["--reference", ref, "--predicted", pred, "--fps", "30"], out=out)
    assert rc == 0
    assert json.loads(out.getvalue())["passed"] is True


def test_cli_predicted_fail_returns_one(tmp_path: Path) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    bad = dict(_REFERENCE)
    bad["shotBoundaries"] = []
    pred = _write(tmp_path, "pred.json", bad)
    out = io.StringIO()
    rc = re.main(["--reference", ref, "--predicted", pred], out=out)
    assert rc == 1


def test_cli_writes_out_file(tmp_path: Path) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    pred = _write(tmp_path, "pred.json", _REFERENCE)
    out_path = tmp_path / "report.json"
    rc = re.main(["--reference", ref, "--predicted", pred, "--out", str(out_path)])
    assert rc == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["passed"] is True


def test_cli_prints_to_stdout_when_no_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    pred = _write(tmp_path, "pred.json", _REFERENCE)
    rc = re.main(["--reference", ref, "--predicted", pred])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_cli_source_with_injected_runner(tmp_path: Path) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    out = io.StringIO()
    rc = re.main(
        ["--reference", ref, "--source", "video.mp4", "--engine", "multispeaker"],
        out=out,
        engine_runner=lambda _src, _eng: _REFERENCE,
    )
    assert rc == 0


def test_cli_source_without_engine_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    rc = re.main(["--reference", ref, "--source", "video.mp4"])
    assert rc == 2
    assert "requires --engine" in capsys.readouterr().err


def test_cli_neither_predicted_nor_source_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    rc = re.main(["--reference", ref])
    assert rc == 2
    assert "one of --predicted or --source" in capsys.readouterr().err


def test_cli_source_default_runner_raises(tmp_path: Path) -> None:
    ref = _write(tmp_path, "ref.json", _REFERENCE)
    with pytest.raises(re.HarnessError, match="no reframe engine runner"):
        re.main(["--reference", ref, "--source", "video.mp4", "--engine", "x"])
