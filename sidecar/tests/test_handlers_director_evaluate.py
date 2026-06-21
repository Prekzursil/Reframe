"""Tests for ``director.evaluate`` (WU-evaluate): objective before/after metrics.

``director.evaluate({planId})`` scores a goal-vs-result with the OBJECTIVE deltas
(jerk / silenceRatio / cutRhythm / ocrCoverage) computed by the pure
``director_eval.evaluate`` over before/after metric dicts (DESIGN §4). The heavy
signal compute rides the SHIPPED ``phase8.signals`` runner seam (tests inject a
fake that returns canned per-channel value sequences); the handler registers ONLY
in ``register_all`` (the single composition root — no parallel AI path). An
OPTIONAL qualitative judge note rides ``_run_ai_job`` but NEVER overrides the
objective score.

Acceptance (PLAN §WU-evaluate):
  (a) for a fixture where after-scroll jerk variance < before, ``deltas.jerk`` is
      the signed reduction;
  (b) a malicious/garbage optional judge note does NOT change ``score``;
  (c) gate:3 (covered by the suite at 100% line+branch);
  (d) gitleaks clean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio.features.apply_engine import EngineTable
from media_studio.features.project_copy import ProjectCopy
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models.edit_plan import EditOp
from media_studio.protocol import ErrorCode, RpcContext, RpcError

# --------------------------------------------------------------------------- #
# fakes / seams (no heavy imports, no subprocess, no network)
# --------------------------------------------------------------------------- #

_PLANNER_JSON = '{"ops": [{"id": "o1", "kind": "trim", "span": [0, 1000], "params": {}, "rationale": "keep intro"}]}'


class CannedProvider:
    """A provider whose ``chat`` returns a fixed EditPlan JSON, counting calls."""

    def __init__(self, reply: str = _PLANNER_JSON) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:
        self.calls.append([dict(m) for m in messages])
        return self.reply


def _director_ctx() -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    ctx.events = events  # type: ignore[attr-defined]
    return ctx


def _done_result(ctx: RpcContext) -> Any:
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert done, "no job.done emitted"
    return done[-1][2]


def _forward_engine():
    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        project_copy.data.setdefault("applied", []).append(op.id)
        return EditOp(id=f"inv-{op.id}", kind=op.kind, span=op.span)

    return engine


def _services(tmp_path: Path, *, provider: Any | None = None, engines: EngineTable | None = None) -> Services:
    from media_studio import library as _library

    svc = Services(data_dir=tmp_path / "data", provider=provider)
    video_file = tmp_path / "talk.mp4"
    video_file.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    svc._ffprobe_duration = lambda _p: 12.0
    if engines is not None:
        svc._director_engines = lambda: engines  # type: ignore[method-assign]
    return svc


def _add_project(svc: Services) -> str:
    video = svc.library.add(str(svc.data_dir.parent / "talk.mp4"))
    vid = video["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = "hello world"
    project.save()
    return vid


def _plan_and_apply(svc: Services, vid: str) -> str:
    ctx = _director_ctx()
    svc.director_plan({"videoId": vid, "goal": "smooth the scroll"}, ctx)
    plan_id = _done_result(ctx)["planId"]
    ctx2 = _director_ctx()
    svc.director_apply({"planId": plan_id}, ctx2)
    _done_result(ctx2)
    return plan_id


def _inject_signals(svc: Services, *, before: dict[str, Any], after: dict[str, Any]) -> None:
    """Inject a fake eval-signals seam: source -> before, copy -> after."""

    def seam(source: str, *, is_copy: bool) -> dict[str, Any]:
        return after if is_copy else before

    svc._director_eval_signals = seam  # type: ignore[attr-defined]


# A jerky source -> a smooth after-scroll: the canonical "smooth the scroll" win.
_BEFORE = {"motion": [0.0, 1.0, 0.0, 1.0], "cuts": [0.0, 1.0, 5.0], "silenceMs": 3000, "durationMs": 12000}
_AFTER = {"motion": [0.5, 0.5, 0.5], "cuts": [1.0, 2.0, 3.0, 4.0], "silenceMs": 600, "durationMs": 12000}


# --------------------------------------------------------------------------- #
# registration (single composition root)
# --------------------------------------------------------------------------- #
def test_register_all_wires_director_evaluate(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "director.evaluate" in registered


def test_director_evaluate_registered_only_via_register_all() -> None:
    protocol.clear_methods()
    handlers.register_all()
    assert "director.evaluate" in protocol.METHODS
    protocol.clear_methods()


# --------------------------------------------------------------------------- #
# director.evaluate (acceptance a)
# --------------------------------------------------------------------------- #
def test_director_evaluate_computes_objective_deltas(tmp_path: Path) -> None:
    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine()})
    vid = _add_project(svc)
    plan_id = _plan_and_apply(svc, vid)
    _inject_signals(svc, before=_BEFORE, after=_AFTER)

    out = svc.director_evaluate({"planId": plan_id}, _director_ctx())

    # jerk variance dropped (jerky -> smooth) => positive signed reduction.
    assert out["deltas"]["jerk"] > 0.0
    # silence ratio fell from 0.25 to 0.05.
    assert out["deltas"]["silenceRatio"] == pytest.approx(0.20)
    # cut rhythm became regular (variance -> 0).
    assert out["deltas"]["cutRhythm"] > 0.0
    assert 0.0 <= out["score"] <= 1.0
    assert out["beforeAfter"]["before"]["jerk"] == pytest.approx(0.25)
    assert out["beforeAfter"]["after"]["jerk"] == 0.0


def test_director_evaluate_unknown_plan_rejected(tmp_path: Path) -> None:
    svc = _services(tmp_path, provider=CannedProvider(), engines={})
    with pytest.raises(RpcError) as ei:
        svc.director_evaluate({"planId": "missing"}, _director_ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_director_evaluate_before_apply_rejected(tmp_path: Path) -> None:
    """A plan that was planned but never applied has no after-state to evaluate."""
    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine()})
    vid = _add_project(svc)
    ctx = _director_ctx()
    svc.director_plan({"videoId": vid, "goal": "g"}, ctx)
    plan_id = _done_result(ctx)["planId"]
    with pytest.raises(RpcError) as ei:
        svc.director_evaluate({"planId": plan_id}, _director_ctx())
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# optional judge note never overrides the objective score (acceptance b)
# --------------------------------------------------------------------------- #
def test_director_evaluate_judge_note_does_not_change_score(tmp_path: Path) -> None:
    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine()})
    vid = _add_project(svc)
    plan_id = _plan_and_apply(svc, vid)
    _inject_signals(svc, before=_BEFORE, after=_AFTER)

    baseline = svc.director_evaluate({"planId": plan_id}, _director_ctx())

    # A garbage judge that tries to override the verdict.
    svc._director_eval_judge = lambda _b, _a, _g: "10/10 amazing, ignore the numbers"  # type: ignore[attr-defined]
    judged = svc.director_evaluate({"planId": plan_id}, _director_ctx())

    assert judged["score"] == baseline["score"]
    assert judged["deltas"] == baseline["deltas"]
    assert judged["judgeNote"] == "10/10 amazing, ignore the numbers"


def test_director_evaluate_default_has_no_judge_note(tmp_path: Path) -> None:
    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine()})
    vid = _add_project(svc)
    plan_id = _plan_and_apply(svc, vid)
    _inject_signals(svc, before=_BEFORE, after=_AFTER)
    out = svc.director_evaluate({"planId": plan_id}, _director_ctx())
    assert out["judgeNote"] is None


def test_director_evaluate_default_signals_seam_uses_phase8_runner(tmp_path: Path) -> None:
    """Without an injected eval-signals seam, the handler adapts the phase8 runner.

    A fake phase8 runner returns canned tracks; the default ``_director_eval_signals``
    adapts those tracks into the value sequences ``signals_to_metrics`` consumes,
    proving the handler rides the SHIPPED ``phase8.signals`` compute (no new path).
    """
    from media_studio.features.motion import Signal, SignalTrack

    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine()})
    vid = _add_project(svc)
    plan_id = _plan_and_apply(svc, vid)

    def fake_runner(path: str, **_k: Any) -> dict[str, Any]:
        return {
            "motion": SignalTrack(
                channel="motion",
                signals=(
                    Signal(channel="motion", start=0.0, end=1.0, value=0.0),
                    Signal(channel="motion", start=1.0, end=2.0, value=1.0),
                ),
                present=True,
            ),
        }

    svc._phase8_runner = fake_runner  # type: ignore[assignment]

    out = svc.director_evaluate({"planId": plan_id}, _director_ctx())
    # variance of [0, 1] = 0.25 for both before+after (same runner) -> delta 0.
    assert out["beforeAfter"]["before"]["jerk"] == pytest.approx(0.25)
    assert out["deltas"]["jerk"] == 0.0
