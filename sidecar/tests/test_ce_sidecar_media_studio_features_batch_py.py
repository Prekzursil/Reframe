"""Cross-edit tests — ``Batch.plan`` (the WU9 dry-run consent surface).

``batch.plan`` mirrors :meth:`Batch.start`'s consent computation but starts NO
job and, unlike :meth:`Batch._build_consent` (whose gate-OFF pass-through
collapses to ``None``), ALWAYS returns a fully-populated
``decisions``/``willRun``/``willSkip`` surface by calling :func:`plan_consent`
directly — so the renderer can render the §9.1 card before deciding to start.

These tests are isolated in a uniquely-named module (they never collide with the
main ``test_batch.py`` suite) and exercise BOTH sides of every branch the new
``plan`` method introduces, so ``features/batch.py`` stays at 100% branch
coverage:

  * ``state is None``            — unknown-batch raise / happy path
  * ``state.get("templateId") or ""`` — truthy templateId / empty templateId
  * ``self._shape_of or (lambda …)``  — injected seam / default template shape
  * ``self._plan_job or self._default_plan_job`` — injected seam / default
    ``ai.planJob`` by name
  * comprehension ``if not is_terminal_status(...)`` — a pending source kept /
    a terminal source filtered out
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.features import batch
from media_studio.protocol import RpcContext, RpcError

# --------------------------------------------------------------------------- #
# fixtures — pure plan shapes + a job-free ctx (plan starts NO job)
# --------------------------------------------------------------------------- #
#: A plan that egresses (a cloud run that would send bytes off the machine).
_EGRESS_PLAN: dict[str, Any] = {
    "route": {"providers": ["openai"], "willEgress": True, "cacheHit": False},
    "costEst": {"requests": 5, "egressBytes": 1000, "withinFreeLimits": True},
    "budget": {"requests": 5, "egressBytes": 1000, "withinFreeLimits": True},
    "cacheHit": False,
    "willEgress": True,
    "cacheKey": "ck-egress",
}
#: A plan that stays local (never egresses — local-only routing).
_LOCAL_PLAN: dict[str, Any] = {
    "route": {"providers": [], "willEgress": False, "cacheHit": False},
    "costEst": {"requests": 0, "egressBytes": 0, "withinFreeLimits": True},
    "budget": {"requests": 0, "egressBytes": 0, "withinFreeLimits": True},
    "cacheHit": False,
    "willEgress": False,
    "cacheKey": "ck-local",
}


def _ctx() -> RpcContext:
    """A ctx with no job registry — ``plan`` never touches ``ctx.jobs``."""
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


def _fake_plan_job(by_shape: dict[Any, dict[str, Any]]):
    """A fake ``ai.planJob`` seam: ``shape_key -> plan`` recording every call."""
    calls: list[Any] = []

    def plan_job(shape_key: Any) -> dict[str, Any]:
        calls.append(shape_key)
        return by_shape[shape_key]

    return plan_job, calls


def _service(tmp_path, **kwargs) -> batch.Batch:
    """A :class:`batch.Batch` over a tmp ``batches/`` dir with injected seams."""
    return batch.Batch(batch.BatchStore(tmp_path / "batches"), **kwargs)


def _created(service: batch.Batch, ids=("v1",)) -> str:
    out = service.create({"name": "B", "templateId": "tpl", "sourceVideoIds": list(ids)}, _ctx())
    return out["batch"]["id"]


class TestBatchServicePlan:
    def test_plan_requires_id(self, tmp_path):
        # ``_require_id`` rejects a missing id before any store access.
        service = _service(tmp_path)
        with pytest.raises(RpcError, match="id"):
            service.plan({}, _ctx())

    def test_plan_unknown_batch_raises(self, tmp_path):
        # state is None -> loud INVALID_PARAMS (the ``state is None`` True branch).
        service = _service(tmp_path)
        with pytest.raises(RpcError, match="unknown batch"):
            service.plan({"id": "nope"}, _ctx())

    def test_plan_gate_on_unacked_egress_skips_with_reason(self, tmp_path):
        # Gate ON + no ack: an egressing source is a visible ``skip`` with its
        # reason (never a silent absence). Covers: state present, templateId
        # truthy, injected shape_of + plan_job, a pending (non-terminal) source.
        plan_job, calls = _fake_plan_job({"eg": _EGRESS_PLAN})
        service = _service(tmp_path, shape_of=lambda _vid: "eg", plan_job=plan_job)
        batch_id = _created(service, ids=["v1"])
        out = service.plan({"id": batch_id, "confirmCloudBudget": True, "acknowledged": False}, _ctx())
        consent = out["consent"]
        assert calls == ["eg"]
        assert consent["willRun"] == 0
        assert consent["willSkip"] == 1
        decision = consent["decisions"][0]
        assert decision["videoId"] == "v1"
        assert decision["action"] == "skip"
        assert decision["skipReason"] == batch.SKIP_WOULD_EGRESS
        assert decision["confirmBudget"] is None
        assert decision["willEgress"] is True

    def test_plan_gate_on_acked_runs_and_threads_confirm_budget(self, tmp_path):
        # Gate ON + ack: the egressing source RUNS and carries the plan's cacheKey
        # as the ``confirmBudget`` token (the acknowledged branch of the decision).
        plan_job, _ = _fake_plan_job({"eg": _EGRESS_PLAN})
        service = _service(tmp_path, shape_of=lambda _vid: "eg", plan_job=plan_job)
        batch_id = _created(service, ids=["v1"])
        out = service.plan({"id": batch_id, "confirmCloudBudget": True, "acknowledged": True}, _ctx())
        consent = out["consent"]
        assert consent["willRun"] == 1
        assert consent["willSkip"] == 0
        decision = consent["decisions"][0]
        assert decision["action"] == "run"
        assert decision["confirmBudget"] == "ck-egress"

    def test_plan_gate_off_still_returns_populated_surface(self, tmp_path):
        # THE contract that separates ``plan`` from ``_build_consent``: with the
        # gate OFF (confirmCloudBudget absent -> default False, acknowledged
        # default False), ``_build_consent`` returns None, but ``plan`` ALWAYS
        # returns a fully-populated surface (every source ``run``, willSkip==0).
        plan_job, _ = _fake_plan_job({"eg": _EGRESS_PLAN})
        service = _service(tmp_path, shape_of=lambda _vid: "eg", plan_job=plan_job)
        batch_id = _created(service, ids=["v1", "v2"])
        out = service.plan({"id": batch_id}, _ctx())
        consent = out["consent"]
        assert consent is not None
        assert len(consent["decisions"]) == 2
        assert consent["willRun"] == 2
        assert consent["willSkip"] == 0
        assert all(d["action"] == "run" for d in consent["decisions"])

    def test_plan_filters_terminal_sources_keeps_pending(self, tmp_path):
        # Mixed batch: v1 terminal (done) is filtered OUT of ``pending`` while v2
        # (queued) is kept — exercises BOTH sides of the comprehension filter in
        # a single pass; only the pending source appears in the surface.
        plan_job, _ = _fake_plan_job({"eg": _EGRESS_PLAN})
        service = _service(tmp_path, shape_of=lambda _vid: "eg", plan_job=plan_job)
        batch_id = _created(service, ids=["v1", "v2"])
        service.store.update_item(batch_id, "v1", status="done", results={"source": "v1"})
        out = service.plan({"id": batch_id, "confirmCloudBudget": True, "acknowledged": False}, _ctx())
        decisions = out["consent"]["decisions"]
        assert [d["videoId"] for d in decisions] == ["v2"]

    def test_plan_all_terminal_yields_empty_surface(self, tmp_path):
        # Every source already terminal -> empty pending -> empty decisions and a
        # zero run/skip split; the planner is NEVER invoked (no pending sources).
        plan_job, calls = _fake_plan_job({"eg": _EGRESS_PLAN})
        service = _service(tmp_path, shape_of=lambda _vid: "eg", plan_job=plan_job)
        batch_id = _created(service, ids=["v1", "v2"])
        service.store.update_item(batch_id, "v1", status="done", results={"source": "v1"})
        service.store.update_item(batch_id, "v2", status="skipped", skipReason="x")
        out = service.plan({"id": batch_id, "confirmCloudBudget": True, "acknowledged": True}, _ctx())
        consent = out["consent"]
        assert consent["decisions"] == []
        assert consent["willRun"] == 0
        assert consent["willSkip"] == 0
        assert calls == []

    def test_plan_default_seams_collapse_to_template_shape(self, tmp_path):
        # No shape_of / plan_job injected -> the DEFAULT seams fire: shape_of
        # collapses every source to the batch's (truthy) templateId shape and
        # plan_job calls ``ai.planJob`` by name once per distinct shape.
        seen: list[dict[str, Any]] = []

        def fake_plan(params, ctx):
            seen.append(params)
            return _EGRESS_PLAN

        service = _service(tmp_path, methods_provider=lambda: {"ai.planJob": fake_plan})
        batch_id = _created(service, ids=["v1", "v2"])
        out = service.plan({"id": batch_id, "confirmCloudBudget": True, "acknowledged": True}, _ctx())
        assert seen == [{"capability": "tpl"}]
        assert out["consent"]["willRun"] == 2

    def test_plan_falsy_template_id_uses_empty_shape(self, tmp_path):
        # A stored batch whose templateId is empty (``create`` would reject it, so
        # it is written directly) drives the ``state.get("templateId") or ""``
        # FALSY branch: the default shape lambda collapses to the empty shape.
        seen: list[dict[str, Any]] = []

        def fake_plan(params, ctx):
            seen.append(params)
            return _LOCAL_PLAN

        batches_dir = tmp_path / "batches"
        batches_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "id": "b-empty",
            "name": "n",
            "templateId": "",
            "status": "queued",
            "createdAt": 1,
            "items": [{"videoId": "v1", "status": "queued"}],
        }
        (batches_dir / "b-empty.json").write_text(json.dumps(state), encoding="utf-8")
        service = batch.Batch(batch.BatchStore(batches_dir), methods_provider=lambda: {"ai.planJob": fake_plan})
        out = service.plan({"id": "b-empty", "confirmCloudBudget": True, "acknowledged": True}, _ctx())
        assert seen == [{"capability": ""}]
        assert out["consent"]["willRun"] == 1
