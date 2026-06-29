"""Pure-tier tests for the manual per-shot override layer (WU R2).

Every dataclass parser/serialiser, the trace->plan derivation, the override apply
+ clamp + validation, the affected-shot computation, and the two RPCs run on
synthetic, path-free fixtures — NO video, NO GPU, NO model import. This file IS the
100% line+branch coverage tier for ``media_studio.features.reframe_override``.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.features import reframe_eval as re
from media_studio.features import reframe_override as ro
from media_studio.protocol import ErrorCode, RpcError

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

_TRACE: dict[str, Any] = {
    "shotBoundaries": [3],
    "speakerPerFrame": ["a", "a", "b", "c", "c", "c"],
    "segments": [
        {"startFrame": 0, "endFrame": 3, "layout": "single"},
        {"startFrame": 3, "endFrame": 6, "layout": "split"},
    ],
    "crops": [[100.0, 0.0, 608.0, 1080.0]] * 6,
}


def _plan() -> ro.ShotPlan:
    return ro.plan_from_trace(_TRACE, source_width=1920, source_height=1080, fps=30.0)


# --------------------------------------------------------------------------- #
# Shared validators
# --------------------------------------------------------------------------- #


def test_seq_rejects_scalar_and_string() -> None:
    with pytest.raises(ro.OverrideError, match="must be an array"):
        ro._seq("ab", "field")
    with pytest.raises(ro.OverrideError, match="must be an array"):
        ro._seq(5, "field")
    assert ro._seq([1, 2], "field") == [1, 2]


def test_require_str() -> None:
    assert ro._require_str("x", "f") == "x"
    with pytest.raises(ro.OverrideError, match="must be a string"):
        ro._require_str(3, "f")


def test_as_int_surfaces_override_error() -> None:
    # A non-integer primitive from the reused R0 helper is re-raised as OverrideError.
    with pytest.raises(ro.OverrideError, match="shot.index entries must be integers"):
        ro.ShotDecision.from_dict(
            {
                "index": "x",
                "startFrame": 0,
                "endFrame": 1,
                "speaker": "a",
                "layout": "single",
                "crop": [0, 0, 1, 1],
                "speakers": [],
            }
        )


def test_parse_crop() -> None:
    assert ro._parse_crop([1, 2, 3, 4]) == (1.0, 2.0, 3.0, 4.0)
    with pytest.raises(ro.OverrideError, match=r"\[x, y, w, h\]"):
        ro._parse_crop([1, 2, 3])
    with pytest.raises(ro.OverrideError, match="must be numbers"):
        ro._parse_crop([1, 2, 3, "x"])


# --------------------------------------------------------------------------- #
# ShotDecision parsing / serialising
# --------------------------------------------------------------------------- #


def test_shot_decision_round_trip() -> None:
    raw = {
        "index": 0,
        "startFrame": 0,
        "endFrame": 3,
        "speaker": "a",
        "layout": "single",
        "crop": [1.0, 2.0, 3.0, 4.0],
        "speakers": ["a", "b"],
    }
    shot = ro.ShotDecision.from_dict(raw)
    assert shot.crop == (1.0, 2.0, 3.0, 4.0)
    assert shot.speakers == ("a", "b")
    assert shot.to_dict() == raw


def test_shot_decision_rejects_non_mapping_and_bad_layout() -> None:
    with pytest.raises(ro.OverrideError, match="shot must be a JSON object"):
        ro.ShotDecision.from_dict([1])
    with pytest.raises(ro.OverrideError, match="shot layout"):
        ro.ShotDecision.from_dict({"layout": "grid"})


def test_shot_decision_rejects_bad_speakers_entry() -> None:
    raw = {
        "index": 0,
        "startFrame": 0,
        "endFrame": 1,
        "speaker": "a",
        "layout": "single",
        "crop": [0, 0, 1, 1],
        "speakers": [1],
    }
    with pytest.raises(ro.OverrideError, match="shot.speakers must be a string"):
        ro.ShotDecision.from_dict(raw)


# --------------------------------------------------------------------------- #
# ShotPlan parsing / serialising
# --------------------------------------------------------------------------- #


def test_shot_plan_round_trip() -> None:
    plan = _plan()
    assert ro.ShotPlan.from_dict(plan.to_dict()) == plan


def test_shot_plan_rejects_non_mapping() -> None:
    with pytest.raises(ro.OverrideError, match="plan must be a JSON object"):
        ro.ShotPlan.from_dict("x")


@pytest.mark.parametrize(
    ("patch", "match"),
    [
        ({"sourceWidth": 0}, "source dimensions"),
        ({"sourceHeight": -1}, "source dimensions"),
        ({"fps": 0}, "fps must be"),
    ],
)
def test_shot_plan_rejects_bad_geometry(patch: dict[str, Any], match: str) -> None:
    raw = _plan().to_dict()
    raw.update(patch)
    with pytest.raises(ro.OverrideError, match=match):
        ro.ShotPlan.from_dict(raw)


# --------------------------------------------------------------------------- #
# ShotOverride parsing
# --------------------------------------------------------------------------- #


def test_shot_override_full_and_empty() -> None:
    full = ro.ShotOverride.from_dict({"index": 1, "speaker": "b", "layout": "split", "crop": [0, 0, 1, 1]})
    assert full == ro.ShotOverride(index=1, speaker="b", layout="split", crop=(0.0, 0.0, 1.0, 1.0))
    empty = ro.ShotOverride.from_dict({"index": 2})
    assert empty == ro.ShotOverride(index=2, speaker=None, layout=None, crop=None)


def test_shot_override_rejects_non_mapping_and_bad_speaker() -> None:
    with pytest.raises(ro.OverrideError, match="override must be a JSON object"):
        ro.ShotOverride.from_dict(7)
    with pytest.raises(ro.OverrideError, match="override.speaker must be a string"):
        ro.ShotOverride.from_dict({"index": 0, "speaker": 9})


# --------------------------------------------------------------------------- #
# Shot-span partitioning + majority helpers
# --------------------------------------------------------------------------- #


def test_shot_spans_partition() -> None:
    assert ro._shot_spans([], 4) == [(0, 4)]
    # 0 and >= total are ignored; duplicates collapsed; interior cuts split.
    assert ro._shot_spans([0, 2, 2, 6, 4], 6) == [(0, 2), (2, 4), (4, 6)]


def test_shot_spans_rejects_empty() -> None:
    with pytest.raises(ro.OverrideError, match="no frames"):
        ro._shot_spans([], 0)


def test_majority_layout() -> None:
    assert ro._majority_layout(["none", "none"]) == ro.DEFAULT_LAYOUT
    # "single" and "split" tie at 1 each -> first-seen wins; "none" filler skipped.
    assert ro._majority_layout(["none", "split", "single"]) == "split"
    assert ro._majority_layout(["single", "split", "split"]) == "split"


def test_majority_speaker() -> None:
    assert ro._majority_speaker([]) == ""
    assert ro._majority_speaker(["a", "b", "b"]) == "b"
    # "a","b" tie -> first-seen wins (exercises the count != best skip path).
    assert ro._majority_speaker(["b", "a", "a", "b"]) == "b"


def test_distinct_order() -> None:
    assert ro._distinct(["c", "a", "c", "b", "a"]) == ("c", "a", "b")


# --------------------------------------------------------------------------- #
# plan_from_trace
# --------------------------------------------------------------------------- #


def test_plan_from_trace_derives_shots() -> None:
    plan = _plan()
    assert len(plan.shots) == 2
    first, second = plan.shots
    assert (first.index, first.start_frame, first.end_frame) == (0, 0, 3)
    assert first.speaker == "a"  # a,a,b -> a
    assert first.layout == "single"
    assert first.speakers == ("a", "b")
    assert first.crop == (100.0, 0.0, 608.0, 1080.0)
    assert (second.start_frame, second.end_frame, second.speaker, second.layout) == (3, 6, "c", "split")


def test_plan_from_trace_accepts_parsed_trace() -> None:
    parsed = re.ReframeTrace.from_dict(_TRACE)
    plan = ro.plan_from_trace(parsed, source_width=1920, source_height=1080, fps=30.0)
    assert len(plan.shots) == 2


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"source_width": 0, "source_height": 1, "fps": 30.0}, "source dimensions"),
        ({"source_width": 1, "source_height": 1, "fps": 0.0}, "fps must be"),
    ],
)
def test_plan_from_trace_rejects_bad_geometry(kwargs: dict[str, Any], match: str) -> None:
    with pytest.raises(ro.OverrideError, match=match):
        ro.plan_from_trace(_TRACE, **kwargs)


def test_plan_from_trace_rejects_length_mismatch() -> None:
    bad = dict(_TRACE)
    bad["crops"] = [[0, 0, 1, 1]] * 5
    with pytest.raises(ro.OverrideError, match="lengths differ"):
        ro.plan_from_trace(bad, source_width=10, source_height=10, fps=30.0)


# --------------------------------------------------------------------------- #
# Crop clamp
# --------------------------------------------------------------------------- #


def test_clamp_crop_keeps_inside_frame() -> None:
    # Oversized + off-frame crop is pulled fully inside [0,100]x[0,100].
    assert ro._clamp_crop((-20.0, 200.0, 400.0, 50.0), 100, 100) == (0.0, 50.0, 100.0, 50.0)
    # Already-inside crop is unchanged.
    assert ro._clamp_crop((10.0, 10.0, 20.0, 20.0), 100, 100) == (10.0, 10.0, 20.0, 20.0)


def test_clamp_crop_rejects_degenerate() -> None:
    with pytest.raises(ro.OverrideError, match="width and height must be positive"):
        ro._clamp_crop((0.0, 0.0, 0.0, 10.0), 100, 100)
    with pytest.raises(ro.OverrideError, match="width and height must be positive"):
        ro._clamp_crop((0.0, 0.0, 10.0, -1.0), 100, 100)


# --------------------------------------------------------------------------- #
# apply_shot_overrides
# --------------------------------------------------------------------------- #


def test_apply_flip_speaker_switch_layout_nudge_crop() -> None:
    plan = _plan()
    overrides = [
        ro.ShotOverride(index=0, speaker="b", layout="composite"),
        ro.ShotOverride(index=1, crop=(0.0, 0.0, 200.0, 200.0)),
    ]
    out = apply = ro.apply_shot_overrides(plan, overrides)
    assert out.shots[0].speaker == "b"
    assert out.shots[0].layout == "composite"
    assert out.shots[1].crop == (0.0, 0.0, 200.0, 200.0)
    # Source plan is untouched (immutability).
    assert plan.shots[0].speaker == "a"
    assert apply is not plan


def test_apply_no_change_override_is_noop_copy() -> None:
    plan = _plan()
    out = ro.apply_shot_overrides(plan, [ro.ShotOverride(index=0)])
    assert out.shots[0] == plan.shots[0]


def test_apply_rejects_unknown_speaker() -> None:
    plan = _plan()
    with pytest.raises(ro.OverrideError, match="not a candidate"):
        ro.apply_shot_overrides(plan, [ro.ShotOverride(index=0, speaker="z")])


def test_apply_rejects_bad_layout() -> None:
    plan = _plan()
    with pytest.raises(ro.OverrideError, match="layout must be one of"):
        ro.apply_shot_overrides(plan, [ro.ShotOverride(index=0, layout="grid")])


def test_apply_rejects_unknown_index_and_duplicate() -> None:
    plan = _plan()
    with pytest.raises(ro.OverrideError, match="unknown shot index 9"):
        ro.apply_shot_overrides(plan, [ro.ShotOverride(index=9)])
    with pytest.raises(ro.OverrideError, match="duplicate override"):
        ro.apply_shot_overrides(plan, [ro.ShotOverride(index=0), ro.ShotOverride(index=0)])


# --------------------------------------------------------------------------- #
# affected_shot_indices
# --------------------------------------------------------------------------- #


def test_affected_only_changed_shots() -> None:
    plan = _plan()
    resolved = ro.apply_shot_overrides(plan, [ro.ShotOverride(index=1, speaker="c", layout="composite")])
    # speaker already "c"; layout single->composite still counts as a change.
    assert ro.affected_shot_indices(plan, resolved) == (1,)
    assert ro.affected_shot_indices(plan, plan) == ()


def test_affected_rejects_length_mismatch() -> None:
    plan = _plan()
    shorter = ro.ShotPlan(plan.source_width, plan.source_height, plan.fps, plan.shots[:1])
    with pytest.raises(ro.OverrideError, match="different number of shots"):
        ro.affected_shot_indices(plan, shorter)


def test_affected_rejects_index_mismatch() -> None:
    plan = _plan()
    swapped = ro.ShotPlan(plan.source_width, plan.source_height, plan.fps, plan.shots[::-1])
    with pytest.raises(ro.OverrideError, match="describe different shots"):
        ro.affected_shot_indices(plan, swapped)


# --------------------------------------------------------------------------- #
# RPC registration
# --------------------------------------------------------------------------- #


class _Registry:
    def __init__(self) -> None:
        self.methods: dict[str, Any] = {}

    def reg(self, name: str, fn: Any) -> None:
        self.methods[name] = fn


def test_register_wires_both_methods() -> None:
    registry = _Registry()
    ro.register(register_fn=registry.reg)
    assert set(registry.methods) == {"reframe.shotPlan", "reframe.applyOverrides"}


def test_rpc_shot_plan_happy_and_error() -> None:
    registry = _Registry()
    ro.register(register_fn=registry.reg)
    shot_plan = registry.methods["reframe.shotPlan"]
    out = shot_plan({"trace": _TRACE, "sourceWidth": 1920, "sourceHeight": 1080, "fps": 30.0}, None)
    assert len(out["plan"]["shots"]) == 2
    with pytest.raises(RpcError) as err:
        shot_plan({"trace": _TRACE, "sourceWidth": 0, "sourceHeight": 1080, "fps": 30.0}, None)
    assert err.value.code == ErrorCode.INVALID_PARAMS


def test_rpc_apply_overrides_happy_and_error() -> None:
    registry = _Registry()
    ro.register(register_fn=registry.reg)
    apply_fn = registry.methods["reframe.applyOverrides"]
    plan = _plan().to_dict()
    out = apply_fn({"plan": plan, "overrides": [{"index": 0, "speaker": "b"}]}, None)
    assert out["affected"] == [0]
    assert out["plan"]["shots"][0]["speaker"] == "b"
    # A non-array overrides payload is a loud INVALID_PARAMS.
    with pytest.raises(RpcError) as err:
        apply_fn({"plan": plan, "overrides": "nope"}, None)
    assert err.value.code == ErrorCode.INVALID_PARAMS
