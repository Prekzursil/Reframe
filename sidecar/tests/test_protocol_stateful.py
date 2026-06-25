"""Stateful + property tests for the protocol.py RPC dispatch layer (WU-B).

A Hypothesis ``RuleBasedStateMachine`` fuzzes SEQUENCES of RPC calls against a
real :class:`JobRegistry` to flush out ordering bugs the example tests can't:
dispatch a job-returning method, then interleave ``job.status`` / ``job.list`` /
``job.retry`` / ``job.cancel`` in arbitrary order. The invariants are the §2 /
A2 contract promises:

  * every job-returning dispatch RECORDS its originating method+params
    (first-write-wins), so the job is retryable,
  * ``job.retry`` re-dispatches the stored request as a NEW job (distinct id)
    that is itself retryable,
  * ``job.status`` / ``job.retry`` of an unknown id raise INVALID_PARAMS,
  * ``job.cancel`` of any id (known/unknown/finished) is a no-op returning
    ``{"ok": True}``,
  * ``job.list`` is bounded at 100 and never lists more jobs than created.

Plus flat property tests for ``parse_request`` envelope validation.

Append-only: ADDS coverage; no source/existing-test change. Uses the
deterministic ``ci`` Hypothesis profile (conftest).
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule
from media_studio import protocol
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, ParsedRequest, RpcContext, RpcError, parse_request


def _job_returning_handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """A minimal §2-shaped handler: creates a job and returns its envelope."""
    job = ctx.jobs.create(lambda jc: None)
    return {"jobId": job.id}


class RpcJobMachine(RuleBasedStateMachine):
    """Drive arbitrary RPC sequences against a real registry + dispatch."""

    def __init__(self) -> None:
        super().__init__()
        # Fresh registry per run; protocol.METHODS is snapshot/restored by the
        # autouse conftest fixture, but we register our own method name here and
        # tolerate a re-run by clearing it first.
        self.jobs = JobRegistry(emit_progress=lambda *a: None, emit_done=lambda *a: None)
        self.ctx = RpcContext(emit_notification=lambda o: None, jobs=self.jobs)
        protocol.METHODS.pop("wub.makejob", None)
        protocol.register("wub.makejob", _job_returning_handler)
        self.created_ids: list[str] = []

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        req = ParsedRequest(id=None, method=method, params=params, is_notification=True)
        return protocol.dispatch(req, self.ctx)

    # -- rules --------------------------------------------------------------
    @rule()
    def make_job(self) -> None:
        out = self._dispatch("wub.makejob", {"seed": len(self.created_ids)})
        job_id = out["jobId"]
        assert isinstance(job_id, str) and job_id
        # the dispatch recorded the originating request (A2)
        stored = self.jobs.get_request(job_id)
        assert stored is not None
        assert stored["method"] == "wub.makejob"
        self.created_ids.append(job_id)

    @precondition(lambda self: bool(self.created_ids))
    @rule(data=st.data())
    def status_known(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(self.created_ids))
        out = self._dispatch("job.status", {"jobId": job_id})
        assert set(out) >= {"status", "pct"}

    @rule(ghost=st.text(min_size=1, max_size=8))
    def status_unknown_raises(self, ghost: str) -> None:
        if ghost in self.created_ids:
            return
        with pytest.raises(RpcError) as ei:
            self._dispatch("job.status", {"jobId": ghost})
        assert ei.value.code == ErrorCode.INVALID_PARAMS

    @precondition(lambda self: bool(self.created_ids))
    @rule(data=st.data())
    def retry_creates_new_retryable_job(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(self.created_ids))
        out = self._dispatch("job.retry", {"jobId": job_id})
        new_id = out["jobId"]
        assert isinstance(new_id, str) and new_id
        assert new_id != job_id
        # the NEW job got its OWN recorded request (itself retryable)
        assert self.jobs.get_request(new_id) is not None
        self.created_ids.append(new_id)

    @rule(ghost=st.text(min_size=1, max_size=8))
    def retry_unknown_raises(self, ghost: str) -> None:
        if ghost in self.created_ids:
            return
        with pytest.raises(RpcError) as ei:
            self._dispatch("job.retry", {"jobId": ghost})
        assert ei.value.code == ErrorCode.INVALID_PARAMS

    @rule(target_id=st.text(min_size=1, max_size=10))
    def cancel_is_noop_ok(self, target_id: str) -> None:
        # cancel of ANY id (known/unknown/finished) returns {ok:true}
        assert self._dispatch("job.cancel", {"jobId": target_id}) == {"ok": True}

    @precondition(lambda self: bool(self.created_ids))
    @rule(data=st.data())
    def cancel_known_ok(self, data: st.DataObject) -> None:
        job_id = data.draw(st.sampled_from(self.created_ids))
        assert self._dispatch("job.cancel", {"jobId": job_id}) == {"ok": True}

    # -- invariants ---------------------------------------------------------
    @invariant()
    def job_list_bounded_and_consistent(self) -> None:
        out = self._dispatch("job.list", {})
        jobs = out["jobs"]
        assert isinstance(jobs, list)
        assert len(jobs) <= 100  # §A2/A3: list_info is bounded at 100
        assert len(jobs) <= len(self.created_ids)


TestRpcJobMachine = RpcJobMachine.TestCase


# --------------------------------------------------------------------------- #
# flat property tests: parse_request envelope validation
# --------------------------------------------------------------------------- #
@st.composite
def _valid_envelope(draw: st.DrawFn) -> dict[str, Any]:
    env: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": draw(st.text(st.characters(min_codepoint=0x61, max_codepoint=0x7A), min_size=1, max_size=10)),
    }
    if draw(st.booleans()):
        env["id"] = draw(st.integers())
    if draw(st.booleans()):
        env["params"] = draw(st.dictionaries(st.text(max_size=4), st.integers(), max_size=3))
    return env


@given(env=_valid_envelope())
def test_parse_valid_request(env: dict[str, Any]) -> None:
    req = parse_request(env)
    assert req.method == env["method"]
    assert isinstance(req.params, dict)
    assert req.is_notification == ("id" not in env)


@given(obj=st.one_of(st.integers(), st.text(), st.lists(st.integers()), st.none()))
def test_parse_non_object_raises_invalid_request(obj: Any) -> None:
    with pytest.raises(RpcError) as ei:
        parse_request(obj)
    assert ei.value.code == ErrorCode.INVALID_REQUEST


@given(version=st.text(max_size=5).filter(lambda v: v != "2.0"))
def test_parse_bad_version_raises(version: str) -> None:
    with pytest.raises(RpcError) as ei:
        parse_request({"jsonrpc": version, "method": "ping"})
    assert ei.value.code == ErrorCode.INVALID_REQUEST


@given(method=st.one_of(st.just(""), st.integers(), st.none()))
def test_parse_bad_method_raises(method: Any) -> None:
    with pytest.raises(RpcError) as ei:
        parse_request({"jsonrpc": "2.0", "method": method})
    assert ei.value.code == ErrorCode.INVALID_REQUEST


@given(params=st.one_of(st.integers(), st.text(min_size=1), st.lists(st.integers(), min_size=1)))
def test_parse_non_object_params_raises_invalid_params(params: Any) -> None:
    with pytest.raises(RpcError) as ei:
        parse_request({"jsonrpc": "2.0", "method": "ping", "params": params})
    assert ei.value.code == ErrorCode.INVALID_PARAMS
