"""Pure-tier tests for the manual per-shot override layer (WU R2).

Every dataclass parser/serialiser, the trace->plan derivation, the override apply
+ clamp + validation, the affected-shot computation, and the two RPCs run on
synthetic, path-free fixtures — NO video, NO GPU, NO model import. This file IS the
100% line+branch coverage tier for ``media_studio.features.reframe_override``.
"""

from __future__ import annotations

import json
from dataclasses import replace
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
    # SCOPE FIX (O-2): the method set GREW — `reframe.shotPlanFor` is the
    # renderer-reachable half of the trust loop (the pure `reframe.shotPlan`
    # needs a trace the renderer has no way to obtain). The assertion is
    # widened to the new exact set, not weakened to a subset check.
    assert set(registry.methods) == {
        "reframe.shotPlan",
        "reframe.shotPlanFor",
        "reframe.applyOverrides",
    }


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


# --------------------------------------------------------------------------- #
# O-2 — the decision SIDECAR: the renderer-reachable trace producer
#
# `reframe.shotPlan` is pure and needs a `trace`, but no renderer code can ever
# obtain one (docs/validation/v15-audit-ledger.md:1911). These cover the sidecar
# the multi-speaker engine drops next to a rendered clip and the
# `reframe.shotPlanFor {clip}` RPC that turns it into an editable plan.
# --------------------------------------------------------------------------- #


def _sidecar_payload() -> dict[str, Any]:
    return ro.build_decision_sidecar(
        engine="reframe_multispeaker",
        aspect="9:16",
        source_path="/v/in.mp4",
        source_width=1920,
        source_height=1080,
        fps=30.0,
        trace=re.ReframeTrace.from_dict(_TRACE),
    )


def test_sidecar_path_appends_the_suffix() -> None:
    assert ro.sidecar_path("/out/clip.mp4") == "/out/clip.mp4.reframe.json"


def test_trace_to_dict_round_trips_through_the_r0_parser() -> None:
    parsed = re.ReframeTrace.from_dict(_TRACE)
    assert re.ReframeTrace.from_dict(ro.trace_to_dict(parsed)) == parsed


def test_build_decision_sidecar_carries_everything_a_rerender_needs() -> None:
    payload = _sidecar_payload()
    assert payload["version"] == ro.SIDECAR_VERSION
    assert payload["engine"] == "reframe_multispeaker"
    assert payload["aspect"] == "9:16"
    assert payload["sourcePath"] == "/v/in.mp4"
    assert (payload["sourceWidth"], payload["sourceHeight"], payload["fps"]) == (1920, 1080, 30.0)
    assert payload["trace"]["speakerPerFrame"] == list(_TRACE["speakerPerFrame"])


def test_load_decision_sidecar_absent_is_none_not_an_error() -> None:
    def missing(path: str) -> str:
        raise FileNotFoundError(path)

    assert ro.load_decision_sidecar("/out/clip.mp4", read_text=missing) is None


def test_load_decision_sidecar_is_loud_on_corruption() -> None:
    with pytest.raises(ro.OverrideError, match="not valid JSON"):
        ro.load_decision_sidecar("/c.mp4", read_text=lambda _p: "{oops")
    with pytest.raises(ro.OverrideError, match="must be a JSON object"):
        ro.load_decision_sidecar("/c.mp4", read_text=lambda _p: "[1]")
    with pytest.raises(ro.OverrideError, match="unsupported reframe sidecar version"):
        ro.load_decision_sidecar("/c.mp4", read_text=lambda _p: '{"version": 99}')


def test_load_decision_sidecar_happy_reads_the_clip_suffixed_path() -> None:
    seen: list[str] = []

    def reader(path: str) -> str:
        seen.append(path)
        return json.dumps(_sidecar_payload())

    payload = ro.load_decision_sidecar("/out/clip.mp4", read_text=reader)
    assert seen == ["/out/clip.mp4.reframe.json"]
    assert payload is not None
    assert payload["engine"] == "reframe_multispeaker"


def test_default_read_text_reads_a_real_file(tmp_path: Any) -> None:
    target = tmp_path / "s.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    assert ro._read_text(str(target)) == '{"a": 1}'


def test_plan_from_sidecar_derives_the_editable_plan() -> None:
    plan = ro.plan_from_sidecar(_sidecar_payload())
    assert [s.index for s in plan.shots] == [0, 1]
    assert plan.source_width == 1920
    assert plan.fps == 30.0


def test_rpc_shot_plan_for_absent_sidecar_returns_a_null_plan() -> None:
    registry = _Registry()

    def missing(path: str) -> str:
        raise FileNotFoundError(path)

    ro.register(register_fn=registry.reg, read_text=missing)
    out = registry.methods["reframe.shotPlanFor"]({"clip": "/out/clip.mp4"}, None)
    # HONEST empty state: a clip the multi-speaker engine never rendered has NO
    # per-shot decisions, so the UI must be able to say so rather than mount a
    # panel over invented data.
    assert out == {"plan": None, "engine": "", "aspect": ""}


def test_rpc_shot_plan_for_happy() -> None:
    registry = _Registry()
    ro.register(register_fn=registry.reg, read_text=lambda _p: json.dumps(_sidecar_payload()))
    out = registry.methods["reframe.shotPlanFor"]({"clip": "/out/clip.mp4"}, None)
    assert out["engine"] == "reframe_multispeaker"
    assert out["aspect"] == "9:16"
    assert out["plan"] is not None
    assert len(out["plan"]["shots"]) == 2


def test_shot_override_to_dict_omits_absent_fields() -> None:
    assert ro.ShotOverride(index=2).to_dict() == {"index": 2}
    assert ro.ShotOverride(index=1, speaker="b", layout="split", crop=(1.0, 2.0, 3.0, 4.0)).to_dict() == {
        "index": 1,
        "speaker": "b",
        "layout": "split",
        "crop": [1.0, 2.0, 3.0, 4.0],
    }


def test_speaker_candidate_crops_is_the_first_crop_each_speaker_held() -> None:
    trace = re.ReframeTrace.from_dict(
        {
            "shotBoundaries": [],
            "speakerPerFrame": ["a", "b", "a"],
            "segments": [],
            "crops": [[0, 0, 10, 10], [50, 0, 10, 10], [99, 0, 10, 10]],
        }
    )
    shot = ro.plan_from_trace(
        {
            "shotBoundaries": [],
            "speakerPerFrame": ["a", "b", "a"],
            "segments": [],
            "crops": [[0, 0, 10, 10], [50, 0, 10, 10], [99, 0, 10, 10]],
        },
        source_width=100,
        source_height=100,
        fps=25.0,
    ).shots[0]
    assert ro.speaker_candidate_crops(trace, shot) == {
        "a": (0.0, 0.0, 10.0, 10.0),
        "b": (50.0, 0.0, 10.0, 10.0),
    }


def test_resolved_crop_follows_a_speaker_flip_but_a_hand_moved_crop_wins() -> None:
    base = ro.ShotDecision(0, 0, 3, "a", "single", (0.0, 0.0, 10.0, 10.0), ("a", "b"))
    cands = {"a": (0.0, 0.0, 10.0, 10.0), "b": (50.0, 0.0, 10.0, 10.0)}
    # untouched -> unchanged
    assert ro.resolved_crop(base, base, cands) == (0.0, 0.0, 10.0, 10.0)
    # speaker flip with no crop edit -> the crop MOVES to that speaker, otherwise
    # "flip the speaker" would re-render the same wrong face.
    flipped = replace(base, speaker="b")
    assert ro.resolved_crop(base, flipped, cands) == (50.0, 0.0, 10.0, 10.0)
    # a hand-moved crop is literal intent and wins over the candidate.
    moved = replace(flipped, crop=(7.0, 0.0, 10.0, 10.0))
    assert ro.resolved_crop(base, moved, cands) == (7.0, 0.0, 10.0, 10.0)
    # a flip to a speaker with no recorded crop keeps the current rectangle.
    assert ro.resolved_crop(base, replace(base, speaker="zz"), cands) == (0.0, 0.0, 10.0, 10.0)


def test_effective_overrides_are_absolute_and_only_cover_changed_shots() -> None:
    trace = re.ReframeTrace.from_dict(_TRACE)
    base = _plan()
    resolved = ro.apply_shot_overrides(base, [ro.ShotOverride(index=0, speaker="b")])
    eff = ro.effective_overrides(base, resolved, trace)
    assert [o.index for o in eff] == [0]
    # Absolute, not a delta: every field is carried so a replay is idempotent.
    assert eff[0].speaker == "b"
    assert eff[0].layout == "single"
    assert eff[0].crop == base.shots[0].crop  # 'b' shares the fixture crop
    assert ro.effective_overrides(base, base, trace) == ()


def test_with_overrides_merges_by_index_new_wins() -> None:
    payload = _sidecar_payload()
    once = ro.with_overrides(payload, [ro.ShotOverride(index=0, speaker="b")])
    twice = ro.with_overrides(once, [ro.ShotOverride(index=0, speaker="c"), ro.ShotOverride(index=1, layout="single")])
    assert {o["index"]: o for o in twice["overrides"]}[0]["speaker"] == "c"
    assert len(twice["overrides"]) == 2
    # The ORIGINAL trace is untouched, so the candidate speaker list survives every
    # round and the user can keep flipping.
    assert twice["trace"] == payload["trace"]


def test_plan_from_sidecar_applies_persisted_overrides() -> None:
    payload = ro.with_overrides(_sidecar_payload(), [ro.ShotOverride(index=0, speaker="b")])
    plan = ro.plan_from_sidecar(payload)
    assert plan.shots[0].speaker == "b"
    assert plan.shots[0].speakers == ("a", "b")  # candidates preserved
    with pytest.raises(ro.OverrideError, match="sidecar.overrides must be an array"):
        ro.plan_from_sidecar({**payload, "overrides": "nope"})


def test_rpc_shot_plan_for_is_loud_on_a_bad_clip_and_a_bad_sidecar() -> None:
    registry = _Registry()
    ro.register(register_fn=registry.reg, read_text=lambda _p: "{oops")
    fn = registry.methods["reframe.shotPlanFor"]
    with pytest.raises(RpcError) as err:
        fn({"clip": 5}, None)
    assert err.value.code == ErrorCode.INVALID_PARAMS
    with pytest.raises(RpcError) as err:
        fn({"clip": "/out/clip.mp4"}, None)
    assert err.value.code == ErrorCode.INVALID_PARAMS
