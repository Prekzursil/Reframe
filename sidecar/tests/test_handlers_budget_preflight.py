"""Tests for the WU-budget pre-flight surface on the handlers (PLAN §WU-budget).

Covers the two pieces this WU completes/verifies on top of WU-envelope:

  * ``ai.planJob`` performs ZERO provider calls and carries the budget;
  * the ``confirmCloudBudget`` gate — a cloud run that WOULD egress is refused
    until acknowledged with the planJob ``cacheKey``; a local-only run is never
    gated; disabling the setting bypasses the gate;
  * the all-cloud degraded notice (run falls through to local);
  * ``defaultTargetJobSize`` drives the unsized budget count.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.models.ai_cache import Message
from media_studio.models.provider import ProviderError
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class ExplodingProvider:
    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:  # pragma: no cover -- must not run
        raise AssertionError("planJob must perform ZERO provider calls")


class _CloudEntry:
    provider = "Groq"
    local = False


class _LocalEntry:
    provider = "local"
    local = True


class _CloudPool:
    """A pool with a cloud provider + local backstop (so willEgress is True)."""

    entries = (_CloudEntry(), _LocalEntry())


class DegradingProvider:
    """Fires a 'local' failover then replies (graceful degradation to local)."""

    def __init__(self, reply: str = "from-local") -> None:
        self.reply = reply
        self._cbs: list[Any] = []

    def on_rotation(self, cb: Any) -> None:
        self._cbs.append(cb)

    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        for cb in self._cbs:
            cb(type("E", (), {"provider": "local"})())
        return self.reply


class RaisingProvider:
    def chat(self, messages: Sequence[Message], **_kwargs: Any) -> str:
        raise ProviderError("provider pool exhausted (text): all keys 429")


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


@pytest.fixture
def svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", provider=ExplodingProvider(), library=None)


# --------------------------------------------------------------------------- #
# ai.planJob — zero provider calls + budget present
# --------------------------------------------------------------------------- #
def test_planjob_zero_provider_calls_and_budget(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "hi"}], "model": "m"},
        ctx,
    )
    assert "budget" in out
    assert out["budget"] == out["costEst"]
    # ExplodingProvider never raised -> zero provider calls during planning.


# --------------------------------------------------------------------------- #
# defaultTargetJobSize drives the unsized count
# --------------------------------------------------------------------------- #
def test_default_target_job_size_drives_unsized_budget(svc: Services, ctx: RpcContext) -> None:
    svc.settings.set({"defaultTargetJobSize": 3})
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "x"}], "request": {"textBytes": 5}},
        ctx,
    )
    # No targetSize pinned -> resolves to the configured default (3), not the
    # module constant (8).
    assert out["costEst"]["requests"] == 3
    assert out["costEst"]["egressBytes"] == 3 * 5


def test_default_target_job_size_falls_back_to_constant(svc: Services, ctx: RpcContext) -> None:
    from media_studio.models import budget as _budget

    # A non-positive setting is ignored -> the budget module constant.
    svc.settings.set({"defaultTargetJobSize": 0})
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "x"}], "request": {"textBytes": 1}},
        ctx,
    )
    assert out["costEst"]["requests"] == _budget.DEFAULT_TARGET_JOB_SIZE


def test_default_target_job_size_non_int_setting_falls_back(svc: Services, ctx: RpcContext) -> None:
    from media_studio.models import budget as _budget

    svc.settings.set({"defaultTargetJobSize": "lots"})
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "x"}], "request": {"textBytes": 1}},
        ctx,
    )
    assert out["costEst"]["requests"] == _budget.DEFAULT_TARGET_JOB_SIZE


# --------------------------------------------------------------------------- #
# confirmCloudBudget gate (PLAN §WU-budget)
# --------------------------------------------------------------------------- #
def _envelope(svc: Services, content: str = "q") -> Any:
    from media_studio.models import ai_job as _ai_job

    inputs = _ai_job.AiInputs(messages=({"role": "user", "content": content},), model="m")
    return svc.plan_ai_job_envelope(inputs)


def test_gate_refuses_unacknowledged_cloud_run(svc: Services) -> None:
    # Force an egressing envelope by monkeypatching the pool to a cloud pool.
    svc._ai_pool = lambda: _CloudPool()  # type: ignore[method-assign]
    envelope = _envelope(svc)
    assert envelope.route.willEgress is True
    with pytest.raises(RpcError, match="budget acknowledgement"):
        svc._enforce_cloud_budget_ack(envelope, ack=None)


def test_gate_accepts_matching_ack(svc: Services) -> None:
    svc._ai_pool = lambda: _CloudPool()  # type: ignore[method-assign]
    envelope = _envelope(svc)
    # The cacheKey is the acknowledgement token; passing it lets the run proceed.
    svc._enforce_cloud_budget_ack(envelope, ack=envelope.cacheKey)


def test_gate_skipped_when_setting_disabled(svc: Services) -> None:
    svc._ai_pool = lambda: _CloudPool()  # type: ignore[method-assign]
    svc.settings.set({"confirmCloudBudget": False})
    envelope = _envelope(svc)
    # Disabled -> no ack required even though the run would egress.
    svc._enforce_cloud_budget_ack(envelope, ack=None)


def test_gate_skipped_for_local_only_run(svc: Services) -> None:
    # Default pool (no providers configured) is local-only -> never egresses.
    envelope = _envelope(svc)
    assert envelope.route.willEgress is False
    svc._enforce_cloud_budget_ack(envelope, ack=None)  # no raise


# --------------------------------------------------------------------------- #
# all-cloud-429 degraded notice (graceful degradation invariant)
# --------------------------------------------------------------------------- #
def test_all_cloud_degrades_to_local_with_notice(svc: Services) -> None:
    progress: list[tuple[str, int, str]] = []
    done: list[tuple[str, Any]] = []
    registry = JobRegistry(
        lambda jid, pct, msg: progress.append((jid, pct, msg)),
        lambda jid, res: done.append((jid, res)),
    )
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=registry)

    job = svc._run_ai_job(
        ctx,
        messages=[{"role": "user", "content": "translate"}],
        model="m",
        provider=DegradingProvider("local-answer"),
        work=None,
        feature="ai",
        label="AI",
    )
    registry.join(timeout=5)
    assert job.finished
    assert any("degraded" in m for _, _, m in progress)
    assert done[-1][1]["degraded"] is True
    assert done[-1][1]["result"] == "local-answer"


def test_all_cloud_exhaustion_emits_single_error(svc: Services) -> None:
    done: list[tuple[str, Any]] = []
    registry = JobRegistry(lambda *_a: None, lambda jid, res: done.append((jid, res)))
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=registry)
    svc._run_ai_job(
        ctx,
        messages=[{"role": "user", "content": "x"}],
        model="m",
        provider=RaisingProvider(),
        work=None,
        feature="ai",
        label="AI",
    )
    registry.join(timeout=5)
    assert len(done) == 1
    assert done[-1][1]["error"]["type"] == "ProviderError"
