"""Cross-edit tests for ``handlers/director_ops.py`` (feature-completion reconcile).

Covers the two wired-in behaviours added by the reconcile pass:

* Finding L550 — the ROUTING-LOCAL GATE in ``_editplan_provider_or_refuse``: a
  RoutingPolicy ``director`` route resolved to ``local`` short-circuits
  ``director.plan`` to a LOCAL-ONLY provider pool (no transcript egress), while a
  ``cloud`` route falls through to the normal editPlan resolution.
* Finding #1 — the reviewer op-status/order MERGE in ``director.apply``: the
  storyboard "keep/drop + reorder" edits (``opOverrides`` / ``order``) are folded
  over the STORED plan immutably before render, with a LOUD ``INVALID_PARAMS`` on
  any unknown id, unknown status, or non-permutation ``order``; the absent-review
  path applies the stored plan verbatim.

Written in a UNIQUELY-NAMED file so it never collides with the consolidated
``test_handlers_director.py`` owned by another partition; coverage is by source
file, so these isolated tests still count toward the 100% branch gate for
``handlers/director_ops.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features.apply_engine import EngineTable
from media_studio.features.project_copy import ProjectCopy
from media_studio.handlers import Services
from media_studio.handlers._shared import _DirectorPlanEntry
from media_studio.jobs import JobRegistry
from media_studio.models.edit_plan import EditOp, EditPlan
from media_studio.protocol import ErrorCode, RpcContext, RpcError

# --------------------------------------------------------------------------- #
# fakes / seams (no heavy imports, no subprocess, no network)
# --------------------------------------------------------------------------- #


class CannedProvider:
    """A legacy injected provider; ``director.apply``'s work never calls ``chat``."""

    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:  # pragma: no cover - unused by apply
        raise AssertionError("director.apply performs ZERO provider calls in work()")


def _fake_engine(tag: str):
    """A fake op-engine: records the applied op id on the COPY, returns an inverse."""

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        project_copy.data.setdefault("log", []).append(op.id)
        return EditOp(id=f"inv-{op.id}", kind=op.kind, span=op.span)

    return engine


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


def _services(tmp_path: Path) -> Services:
    """A Services over a tmp dir with a registered video + a stored two-op plan."""
    from media_studio import library as _library

    svc = Services(data_dir=tmp_path / "data", provider=CannedProvider())
    video_file = tmp_path / "talk.mp4"
    video_file.write_bytes(b"\x00fake")
    svc.library = _library.Library(svc.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    svc._ffprobe_duration = lambda _p: 12.0
    svc._director_engines = lambda: {"trim": _fake_engine("trim")}  # type: ignore[method-assign]
    return svc


def _seed_plan(svc: Services) -> str:
    """Register a project and stash a two-op ``planned`` plan; return its plan id."""
    video = svc.library.add(str(svc.data_dir.parent / "talk.mp4"))
    vid = video["id"]
    project = svc._load_or_create_project(vid)
    project.data["transcript"] = "hello world"
    project.save()
    plan = EditPlan(
        plan_id="p1",
        video_id=vid,
        goal="g",
        source_hash="h",
        ops=(
            EditOp(id="o1", kind="trim", span=(0, 1000)),
            EditOp(id="o2", kind="trim", span=(0, 2000)),
        ),
    )
    svc._director_plans["p1"] = _DirectorPlanEntry(
        plan=plan, video_id=vid, messages=({"role": "user", "content": "g"},)
    )
    return "p1"


# --------------------------------------------------------------------------- #
# Finding #1 — reviewer op-status / order merge in director.apply
# --------------------------------------------------------------------------- #
def test_apply_op_override_drops_op_and_leaves_stored_plan_immutable(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()

    out = svc.director_apply({"planId": plan_id, "opOverrides": [{"id": "o1", "status": "dropped"}]}, ctx)
    result = _done_result(ctx)

    assert out["jobId"]
    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses["o1"] == "dropped"  # reviewer keep/drop honoured
    assert statuses["o2"] == "applied"
    # The STORED entry is never mutated (immutable merge).
    assert svc._director_plans[plan_id].plan.ops[0].status == "planned"


def test_apply_order_reorders_render_sequence(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()

    out = svc.director_apply({"planId": plan_id, "order": ["o2", "o1"]}, ctx)
    result = _done_result(ctx)

    assert out["jobId"]
    assert [op["id"] for op in result["opsStatus"]] == ["o2", "o1"]  # reordered
    # Stored plan order is unchanged (immutable merge).
    assert [op.id for op in svc._director_plans[plan_id].plan.ops] == ["o1", "o2"]


def test_apply_unknown_override_id_raises_loud(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()
    with pytest.raises(RpcError) as ei:
        svc.director_apply({"planId": plan_id, "opOverrides": [{"id": "nope", "status": "dropped"}]}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_apply_unknown_override_status_raises_loud(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()
    with pytest.raises(RpcError) as ei:
        svc.director_apply({"planId": plan_id, "opOverrides": [{"id": "o1", "status": "bogus"}]}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_apply_order_not_a_permutation_raises_loud(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()
    with pytest.raises(RpcError) as ei:
        svc.director_apply({"planId": plan_id, "order": ["o1", "nope"]}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_apply_absent_review_applies_stored_plan_verbatim(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()

    svc.director_apply({"planId": plan_id}, ctx)
    result = _done_result(ctx)

    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses == {"o1": "applied", "o2": "applied"}
    # entry.plan is applied by identity (no merge copy).
    assert svc._director_plans[plan_id].plan.ops[0].status == "planned"


def test_apply_override_and_order_combined(tmp_path: Path) -> None:
    """Both levers together: drop o2 AND reorder — exercises status_by_id hit under reorder."""
    svc = _services(tmp_path)
    plan_id = _seed_plan(svc)
    ctx = _director_ctx()

    out = svc.director_apply(
        {"planId": plan_id, "opOverrides": [{"id": "o2", "status": "dropped"}], "order": ["o2", "o1"]},
        ctx,
    )
    result = _done_result(ctx)

    assert out["jobId"]
    assert [op["id"] for op in result["opsStatus"]] == ["o2", "o1"]
    statuses = {op["id"]: op["status"] for op in result["opsStatus"]}
    assert statuses["o2"] == "dropped"
    assert statuses["o1"] == "applied"


# --------------------------------------------------------------------------- #
# Finding L550 — routing-local gate in _editplan_provider_or_refuse
# --------------------------------------------------------------------------- #
def _cloud_editplan_settings(mode: str) -> dict[str, Any]:
    """Settings with a cloud editPlan target + TEXT consent, under a routing ``mode``."""
    return {
        "providers": [
            {
                "id": "Groq",
                "provider": "Groq",
                "baseUrl": "https://groq.example/v1",
                "model": "m",
                "apiKeys": ["sk-real"],
            }
        ],
        "routing": {"perFunction": {"editPlan": {"provider": "Groq"}}},
        "consent": {"perProvider": {"Groq": {"text": True}}},
        "confirmCloudBudget": False,
        "routingPolicy": {"global": mode, "overrides": {}},
    }


def test_editplan_local_route_returns_local_only_pool(tmp_path: Path) -> None:
    """A RoutingPolicy ``director`` -> local short-circuits to a LOCAL-ONLY pool.

    Even with a fully consented cloud editPlan target configured, the resolved
    provider has NO cloud entry (no transcript egress possible).
    """
    svc = Services(data_dir=tmp_path / "data")  # provider=None -> routing resolves
    svc.settings.set(_cloud_editplan_settings("local"))

    provider = svc._editplan_provider_or_refuse()

    entries = getattr(provider, "entries", ())
    assert entries, "expected a built provider pool"
    assert all(getattr(e, "local", False) for e in entries), "local route must build NO cloud entry"


def test_editplan_cloud_route_keeps_cloud_target(tmp_path: Path) -> None:
    """A RoutingPolicy ``director`` -> cloud falls through to the editPlan cloud pool."""
    svc = Services(data_dir=tmp_path / "data")  # provider=None -> routing resolves
    svc.settings.set(_cloud_editplan_settings("cloud"))

    provider = svc._editplan_provider_or_refuse()

    entries = getattr(provider, "entries", ())
    assert any(not getattr(e, "local", False) for e in entries), "cloud route must keep the consented cloud entry"


def test_editplan_injected_provider_short_circuits_before_routing(tmp_path: Path) -> None:
    """An injected ``_provider`` seam wins outright — routing is never consulted."""
    sentinel = CannedProvider()
    svc = Services(data_dir=tmp_path / "data", provider=sentinel)
    svc.settings.set(_cloud_editplan_settings("local"))

    assert svc._editplan_provider_or_refuse() is sentinel
