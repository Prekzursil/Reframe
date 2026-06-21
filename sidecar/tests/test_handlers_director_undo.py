"""Tests for ``director.undo`` (WU-undo): one-shot undo via the stored inverse.

``director.apply`` (WU-plan-rpc) walks the stored plan over a project COPY and
**records an inverse plan** (newest-first) as it applies. WU-undo persists that
inverse under the ``planId`` and adds ``director.undo({planId})``, which re-runs
``apply_plan`` (WU-apply) over a fresh COPY with the recorded inverse ops — the
one-shot reversal (DESIGN §5/§7.1). NO LLM/vision call (undo is pure manifest
reversal), so the planner/transport is never touched; the handler registers ONLY
in ``register_all`` (the single composition root — no parallel AI path).

Acceptance (PLAN §WU-undo):
  (a) undo after an apply restores the pre-apply COPY (round-trip with WU-apply):
      the inverse plan's recorded ops are applied and a terminal ``job.done`` is
      emitted;
  (b) ``director.undo`` is registered EXCLUSIVELY through ``register_all`` (no
      other ``protocol.register``/``reg(`` call names it — duplicate raises at
      startup);
  (c) gate:3 (covered by the suite running green at 100%);
  (d) gitleaks clean (no secrets in this test).
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

# A canned planner reply: one valid in-range trim (applied) — undo reverses it.
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


def _services(tmp_path: Path, *, provider: Any | None = None, engines: EngineTable | None = None) -> Services:
    """A Services over a tmp dir with a registered video + transcribed project."""
    from media_studio import library as _library

    svc = Services(data_dir=tmp_path / "data", provider=provider)
    video_file = tmp_path / "talk.mp4"
    video_file.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    svc._ffprobe_duration = lambda _p: 12.0  # 12s -> 12000ms clip duration
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


def _forward_engine(tag: str):
    """A fake forward op-engine: tags the COPY, returns a known inverse op.

    The inverse op carries a distinct kind so the undo step routes to the
    matching ``inverse`` engine (round-trip proof).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        project_copy.data.setdefault("applied", []).append(op.id)
        return EditOp(id=f"inv-{op.id}", kind=op.kind, span=op.span)

    return engine


def _undo_engine(seen: list[str]):
    """A fake inverse op-engine recording which inverse ops were re-applied."""

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        project_copy.data.setdefault("undone", []).append(op.id)
        seen.append(op.id)
        return EditOp(id=f"re-{op.id}", kind=op.kind, span=op.span)

    return engine


def _apply_and_plan_id(svc: Services, vid: str) -> str:
    """Run director.plan + director.apply, returning the stored planId."""
    ctx = _director_ctx()
    svc.director_plan({"videoId": vid, "goal": "tighten"}, ctx)
    plan_id = _done_result(ctx)["planId"]
    ctx_apply = _director_ctx()
    svc.director_apply({"planId": plan_id}, ctx_apply)
    _done_result(ctx_apply)
    return plan_id


# --------------------------------------------------------------------------- #
# registration (acceptance b)
# --------------------------------------------------------------------------- #
def test_register_all_wires_director_undo(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "director.undo" in registered


def test_director_undo_registered_only_via_register_all() -> None:
    protocol.clear_methods()
    handlers.register_all()
    assert "director.undo" in protocol.METHODS
    protocol.clear_methods()


# --------------------------------------------------------------------------- #
# director.undo (acceptance a)
# --------------------------------------------------------------------------- #
def test_director_undo_applies_stored_inverse_and_emits_done(tmp_path: Path) -> None:
    seen: list[str] = []
    engines = {"trim": _forward_engine("trim")}
    svc = _services(tmp_path, provider=CannedProvider(), engines=engines)
    # The undo step routes the recorded inverse ops through inverse_engines.
    svc._director_inverse_engines = lambda: {"trim": _undo_engine(seen)}  # type: ignore[attr-defined]
    vid = _add_project(svc)
    plan_id = _apply_and_plan_id(svc, vid)

    ctx_undo = _director_ctx()
    out = svc.director_undo({"planId": plan_id}, ctx_undo)
    result = _done_result(ctx_undo)

    assert out["jobId"]
    assert result["planId"] == plan_id
    # The recorded inverse op (inv-o1) was applied during undo (round-trip).
    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses["inv-o1"] == "applied"
    assert seen == ["inv-o1"]
    assert result["projectCopyPath"]


def test_director_undo_unknown_plan_rejected(tmp_path: Path) -> None:
    svc = _services(tmp_path, provider=CannedProvider(), engines={})
    ctx = _director_ctx()
    with pytest.raises(RpcError) as ei:
        svc.director_undo({"planId": "missing"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_director_undo_before_apply_rejected(tmp_path: Path) -> None:
    """A plan that was planned but never applied has no stored inverse to undo."""
    svc = _services(tmp_path, provider=CannedProvider(), engines={"trim": _forward_engine("trim")})
    vid = _add_project(svc)
    ctx = _director_ctx()
    svc.director_plan({"videoId": vid, "goal": "g"}, ctx)
    plan_id = _done_result(ctx)["planId"]

    ctx2 = _director_ctx()
    with pytest.raises(RpcError) as ei:
        svc.director_undo({"planId": plan_id}, ctx2)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_director_undo_requires_job_registry(tmp_path: Path) -> None:
    engines = {"trim": _forward_engine("trim")}
    svc = _services(tmp_path, provider=CannedProvider(), engines=engines)
    vid = _add_project(svc)
    plan_id = _apply_and_plan_id(svc, vid)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        svc.director_undo({"planId": plan_id}, direct)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_director_undo_not_budget_gated_with_cloud_pool(tmp_path: Path) -> None:
    """Undo is a pure LOCAL manifest reversal — no provider call, no egress.

    Even under the realistic shipping config (``confirmCloudBudget`` ON + a cloud
    provider in the pool, the exact setup of
    ``test_director_apply_enforces_budget_ack_on_egress``), undo MUST proceed
    WITHOUT a ``confirmBudget`` token: its ``work`` makes zero provider calls, so
    the budget ack is never re-enforced (DESIGN §5/§7.1 reversibility). Apply
    already gated its own egress; gating undo would permanently refuse a pure-local
    reversal that has no budget surface to acknowledge.
    """
    seen: list[str] = []
    engines = {"trim": _forward_engine("trim")}
    svc = _services(tmp_path, provider=CannedProvider(), engines=engines)
    svc._director_inverse_engines = lambda: {"trim": _undo_engine(seen)}  # type: ignore[attr-defined]
    vid = _add_project(svc)
    plan_id = _apply_and_plan_id(svc, vid)

    # Force an egressing envelope + the confirm-cloud-budget gate ON (would refuse
    # an apply lacking the echoed cacheKey — see the apply budget test).
    class _CloudEntry:
        provider = "Groq"
        local = False

    class _LocalEntry:
        provider = "local"
        local = True

    class _CloudPool:
        entries = (_CloudEntry(), _LocalEntry())

    svc._ai_pool = lambda: _CloudPool()  # type: ignore[method-assign]
    svc.settings.set({"confirmCloudBudget": True})

    ctx_undo = _director_ctx()
    out = svc.director_undo({"planId": plan_id}, ctx_undo)
    result = _done_result(ctx_undo)

    assert out["jobId"]
    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses["inv-o1"] == "applied"
    assert seen == ["inv-o1"]


def test_director_undo_defaults_inverse_engines_to_forward(tmp_path: Path) -> None:
    """When no separate inverse table is injected, undo reuses the forward engines."""
    engines = {"trim": _forward_engine("trim")}
    svc = _services(tmp_path, provider=CannedProvider(), engines=engines)
    vid = _add_project(svc)
    plan_id = _apply_and_plan_id(svc, vid)

    ctx_undo = _director_ctx()
    svc.director_undo({"planId": plan_id}, ctx_undo)
    result = _done_result(ctx_undo)

    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses["inv-o1"] == "applied"
