"""Tests for the ``ai.planJob`` pre-flight RPC handler (WU-envelope).

``ai.planJob`` is the pure pre-flight: it returns ``{route, costEst, cacheHit,
willEgress, budget, preview, cacheKey}`` and performs ZERO provider calls. The
tests pin: the wire shape, that NO provider transport is touched, the request
coercion (dict / non-dict / no-size), the message-coercion branches (list with
non-dict entries filtered; a non-list messages value), and cacheHit detection
from a pre-seeded cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


class ExplodingProvider:
    """A provider whose ``chat`` must NEVER be called during planning."""

    def chat(self, messages: list[dict[str, str]], **_k: Any) -> str:  # pragma: no cover -- must not run
        raise AssertionError("ai.planJob must perform ZERO provider calls")


@pytest.fixture
def svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", provider=ExplodingProvider(), library=None)


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def test_ai_planjob_registered() -> None:
    protocol.clear_methods()
    handlers.register_all()
    assert "ai.planJob" in protocol.METHODS
    protocol.clear_methods()


def test_ai_planjob_returns_preflight_shape_zero_calls(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "hello"}], "model": "m"},
        ctx,
    )
    assert set(out) >= {"route", "costEst", "cacheHit", "willEgress", "budget", "preview", "cacheKey"}
    assert out["route"]["degradeChain"][-1] == "local"
    assert out["cacheHit"] is False
    # ZERO provider calls: the ExplodingProvider was never invoked (no AssertionError).


def test_ai_planjob_with_explicit_request(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {
            "messages": [{"role": "user", "content": "x"}],
            "model": "m",
            "request": {"targetSize": 5, "textBytes": 10, "frameBytes": 2},
        },
        ctx,
    )
    assert out["costEst"]["requests"] == 5
    assert out["costEst"]["egressBytes"] == 5 * (10 + 2)
    assert out["costEst"]["egressKinds"] == {"text": 50, "frames": 10}


def test_ai_planjob_request_without_size_uses_default(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "x"}], "request": {"textBytes": 3}},
        ctx,
    )
    # No targetSize -> _BudgetRequest.target_size is None -> budget default (8).
    assert out["costEst"]["requests"] == 8


def test_ai_planjob_non_dict_request_is_unsized(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "abc"}], "request": "not-a-dict"},
        ctx,
    )
    # request coerces to None -> the derived single-output text request (size 1).
    assert out["costEst"]["requests"] == 1
    assert out["costEst"]["egressBytes"] == len(b"abc")


def test_ai_planjob_filters_non_dict_messages(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job(
        {"messages": [{"role": "user", "content": "keep"}, "junk", 42], "model": "m"},
        ctx,
    )
    # Only the dict message survives; planning still succeeds.
    assert "cacheKey" in out


def test_ai_planjob_non_list_messages_is_empty(svc: Services, ctx: RpcContext) -> None:
    out = svc.ai_plan_job({"messages": "nope", "model": "m"}, ctx)
    # messages -> () ; an empty-message plan still produces a cache key + route.
    assert "cacheKey" in out
    assert out["route"]["degradeChain"][-1] == "local"


def test_ai_planjob_cache_hit_flags_no_egress(svc: Services, ctx: RpcContext) -> None:
    params = {"messages": [{"role": "user", "content": "seeded"}], "model": "m"}
    # Seed the cache at the same key the planner will derive.
    cache = svc._ai_cache()
    inputs_messages = [{"role": "user", "content": "seeded"}]
    key = cache.key(inputs_messages, "m", {})
    cache.put(key, "cached-answer")
    out = svc.ai_plan_job(params, ctx)
    assert out["cacheHit"] is True
    assert out["willEgress"] is False
    assert "Cached" in out["preview"]
