"""Tests for protocol.py + rpc.py — framing, dispatch, notifications, jobs over stdio.

No heavy-ML imports. The server is driven with in-memory streams (FakeStreams).
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from media_studio import protocol
from media_studio.protocol import (
    ErrorCode,
    ParsedRequest,
    RpcContext,
    RpcError,
    make_done,
    make_error,
    make_progress,
    make_response,
    parse_request,
)
from media_studio.rpc import RpcServer


# ===========================================================================
# protocol.py — framing builders
# ===========================================================================


def test_make_response_shape():
    assert make_response(7, {"a": 1}) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"a": 1},
    }


def test_make_error_shape():
    obj = make_error(7, RpcError("bad", ErrorCode.INVALID_PARAMS))
    assert obj == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": ErrorCode.INVALID_PARAMS, "message": "bad"},
    }


def test_make_error_includes_data_when_present():
    obj = make_error(1, RpcError("oops", ErrorCode.INTERNAL_ERROR, data={"x": 1}))
    assert obj["error"]["data"] == {"x": 1}


def test_make_progress_field_names_match_contract():
    # §2: job.progress params = {jobId, pct, message}
    note = make_progress("job-1", 50, "halfway")
    assert note == {
        "jsonrpc": "2.0",
        "method": "job.progress",
        "params": {"jobId": "job-1", "pct": 50, "message": "halfway"},
    }


def test_make_done_field_names_match_contract():
    # §2: job.done params = {jobId, result}
    note = make_done("job-1", {"transcript": "hi"})
    assert note == {
        "jsonrpc": "2.0",
        "method": "job.done",
        "params": {"jobId": "job-1", "result": {"transcript": "hi"}},
    }


# ===========================================================================
# protocol.py — request validation
# ===========================================================================


def test_parse_request_minimal():
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert isinstance(req, ParsedRequest)
    assert req.id == 1
    assert req.method == "ping"
    assert req.params == {}
    assert req.is_notification is False


def test_parse_request_notification_has_no_id():
    req = parse_request({"jsonrpc": "2.0", "method": "job.progress", "params": {}})
    assert req.is_notification is True
    assert req.id is None


def test_parse_request_id_null_is_still_a_request():
    # An explicit null id is present -> a request, not a notification.
    req = parse_request({"jsonrpc": "2.0", "id": None, "method": "ping"})
    assert req.is_notification is False


@pytest.mark.parametrize(
    "bad",
    [
        [],
        "string",
        42,
        {"id": 1, "method": "ping"},  # missing jsonrpc
        {"jsonrpc": "1.0", "id": 1, "method": "ping"},  # wrong version
        {"jsonrpc": "2.0", "id": 1},  # missing method
        {"jsonrpc": "2.0", "id": 1, "method": ""},  # empty method
    ],
)
def test_parse_request_rejects_bad_envelopes(bad):
    with pytest.raises(RpcError) as ei:
        parse_request(bad)
    assert ei.value.code == ErrorCode.INVALID_REQUEST


def test_parse_request_rejects_non_object_params():
    with pytest.raises(RpcError) as ei:
        parse_request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1, 2]})
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_parse_request_null_params_defaults_to_empty():
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None})
    assert req.params == {}


# ===========================================================================
# protocol.py — METHODS registry + dispatch
# ===========================================================================


def test_method_decorator_registers_and_dispatches():
    @protocol.method("test.echo")
    def _echo(params, ctx):
        return {"echo": params.get("v")}

    assert "test.echo" in protocol.METHODS
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "test.echo", "params": {"v": 9}})
    out = protocol.dispatch(req, RpcContext(emit_notification=lambda o: None))
    assert out == {"echo": 9}


def test_duplicate_method_registration_raises():
    protocol.register("test.dup", lambda p, c: None)
    with pytest.raises(ValueError):
        protocol.register("test.dup", lambda p, c: None)


def test_dispatch_unknown_method_raises_method_not_found():
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "does.not.exist"})
    with pytest.raises(RpcError) as ei:
        protocol.dispatch(req, RpcContext(emit_notification=lambda o: None))
    assert ei.value.code == ErrorCode.METHOD_NOT_FOUND


def test_clear_methods_empties_registry():
    protocol.clear_methods()
    assert protocol.METHODS == {}


# ===========================================================================
# protocol.py — built-in handlers
# ===========================================================================


def test_ping_returns_pong_and_version():
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    out = protocol.dispatch(req, RpcContext(emit_notification=lambda o: None))
    # §2: ping() -> {pong:true, version:str}
    assert out["pong"] is True
    assert isinstance(out["version"], str) and out["version"]


def test_job_cancel_requires_jobId():
    server = RpcServer()
    req = parse_request({"jsonrpc": "2.0", "id": 1, "method": "job.cancel", "params": {}})
    with pytest.raises(RpcError) as ei:
        protocol.dispatch(req, server.ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_job_cancel_returns_ok():
    server = RpcServer()
    job = server.jobs.create(lambda ctx: None)
    req = parse_request(
        {"jsonrpc": "2.0", "id": 1, "method": "job.cancel", "params": {"jobId": job.id}}
    )
    out = protocol.dispatch(req, server.ctx)
    assert out == {"ok": True}  # §2
    assert job.cancel_requested is True


def test_job_status_returns_status_and_pct():
    server = RpcServer()
    job = server.jobs.create(lambda ctx: None)
    req = parse_request(
        {"jsonrpc": "2.0", "id": 1, "method": "job.status", "params": {"jobId": job.id}}
    )
    out = protocol.dispatch(req, server.ctx)
    # §2: job.status -> {status, pct}
    assert out == {"status": "pending", "pct": 0}


def test_job_status_unknown_job_raises():
    server = RpcServer()
    req = parse_request(
        {"jsonrpc": "2.0", "id": 1, "method": "job.status", "params": {"jobId": "ghost"}}
    )
    with pytest.raises(RpcError) as ei:
        protocol.dispatch(req, server.ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


# ===========================================================================
# rpc.py — server framing over in-memory streams
# ===========================================================================


def _server_for(make_streams, lines):
    streams = make_streams(lines)
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    return server, streams


def test_serve_reads_newline_delimited_and_writes_response(make_streams):
    server, streams = _server_for(
        make_streams, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    )
    server.serve()
    out = streams.output_objects()
    assert len(out) == 1
    assert out[0]["id"] == 1
    assert out[0]["result"]["pong"] is True


def test_multiple_requests_one_per_line(make_streams):
    server, streams = _server_for(
        make_streams,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ],
    )
    server.serve()
    out = streams.output_objects()
    assert [o["id"] for o in out] == [1, 2]


def test_blank_lines_are_ignored(make_streams):
    streams = make_streams([])
    # Manually craft an input with blank lines interleaved.
    streams.instream = __import__("io").StringIO(
        '\n   \n{"jsonrpc":"2.0","id":5,"method":"ping"}\n\n'
    )
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    server.serve()
    out = streams.output_objects()
    assert len(out) == 1 and out[0]["id"] == 5


def test_notification_produces_no_response(make_streams):
    # A request without an id is a notification -> no response written.
    server, streams = _server_for(
        make_streams, [{"jsonrpc": "2.0", "method": "ping"}]
    )
    server.serve()
    assert streams.output_objects() == []


def test_parse_error_yields_error_response_with_null_id(make_streams):
    streams = make_streams([])
    streams.instream = __import__("io").StringIO("{not valid json}\n")
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    server.serve()
    out = streams.output_objects()
    assert len(out) == 1
    assert out[0]["id"] is None
    assert out[0]["error"]["code"] == ErrorCode.PARSE_ERROR


def test_invalid_request_envelope_error_response(make_streams):
    server, streams = _server_for(
        make_streams, [{"jsonrpc": "1.0", "id": 3, "method": "ping"}]
    )
    server.serve()
    out = streams.output_objects()
    assert out[0]["id"] == 3
    assert out[0]["error"]["code"] == ErrorCode.INVALID_REQUEST


def test_unknown_method_error_response(make_streams):
    server, streams = _server_for(
        make_streams, [{"jsonrpc": "2.0", "id": 4, "method": "no.such.method"}]
    )
    server.serve()
    out = streams.output_objects()
    assert out[0]["error"]["code"] == ErrorCode.METHOD_NOT_FOUND


def test_handler_crash_becomes_internal_error_and_loop_survives(make_streams):
    @protocol.method("test.boom")
    def _boom(params, ctx):
        raise RuntimeError("explode")

    server, streams = _server_for(
        make_streams,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "test.boom"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},  # loop must survive
        ],
    )
    server.serve()
    out = streams.output_objects()
    assert out[0]["id"] == 1
    assert out[0]["error"]["code"] == ErrorCode.INTERNAL_ERROR
    assert out[1]["id"] == 2  # survived
    assert out[1]["result"]["pong"] is True


def test_logs_never_pollute_stdout(make_streams):
    # Only framed JSON should appear on stdout; every line must be valid JSON.
    server, streams = _server_for(
        make_streams, [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    )
    server.serve()
    for raw in streams.outstream.getvalue().splitlines():
        if raw.strip():
            json.loads(raw)  # raises if any non-JSON log leaked to stdout


# ===========================================================================
# rpc.py — long job lifecycle over stdio (jobId -> progress -> done)
# ===========================================================================


def test_long_job_streams_progress_then_done(make_streams):
    # A handler that starts a registry job and returns {jobId} immediately.
    @protocol.method("demo.longjob")
    def _longjob(params, ctx):
        def work(jctx):
            jctx.progress(20, "step 1")
            jctx.progress(80, "step 2")
            return {"value": 99}

        job = ctx.jobs.start(work)
        return {"jobId": job.id}

    streams = make_streams([{"jsonrpc": "2.0", "id": 1, "method": "demo.longjob"}])
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    server.serve()
    server.jobs.join(timeout=5)

    out = streams.output_objects()
    # First object: the immediate {jobId} response.
    response = next(o for o in out if o.get("id") == 1)
    job_id = response["result"]["jobId"]

    progress = [o for o in out if o.get("method") == "job.progress"]
    done = [o for o in out if o.get("method") == "job.done"]

    assert [p["params"]["pct"] for p in progress] == [20, 80]
    assert all(p["params"]["jobId"] == job_id for p in progress)
    assert len(done) == 1
    assert done[0]["params"] == {"jobId": job_id, "result": {"value": 99}}


def test_job_cancel_over_stdio_marks_cancelled(make_streams):
    started = threading.Event()
    release = threading.Event()

    @protocol.method("demo.cancellable")
    def _cancellable(params, ctx):
        def work(jctx):
            started.set()
            while not jctx.cancelled:
                release.wait(timeout=0.01)
            return "unreached"

        job = ctx.jobs.start(work)
        return {"jobId": job.id}

    streams = make_streams([{"jsonrpc": "2.0", "id": 1, "method": "demo.cancellable"}])
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    server.serve()  # registers + starts the job, returns {jobId}

    assert started.wait(timeout=5)
    response = next(o for o in streams.output_objects() if o.get("id") == 1)
    job_id = response["result"]["jobId"]

    # Cancel directly through the server's context (simulating a second line).
    server.handle_line(
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "job.cancel", "params": {"jobId": job_id}})
    )
    release.set()
    server.jobs.get(job_id).wait(timeout=5)

    from media_studio.jobs import JobStatus

    assert server.jobs.get(job_id).status is JobStatus.CANCELLED
    # No job.done for a cancelled job.
    assert all(o.get("method") != "job.done" for o in streams.output_objects())


def test_concurrent_job_writes_are_well_framed(make_streams):
    # Two jobs emitting progress concurrently must never interleave a line.
    @protocol.method("demo.multi")
    def _multi(params, ctx):
        def work(jctx):
            for p in (10, 40, 70, 100):
                jctx.progress(p, f"{jctx.job_id}:{p}")
                time.sleep(0.001)
            return {"ok": True}

        a = ctx.jobs.start(work)
        b = ctx.jobs.start(work)
        return {"jobs": [a.id, b.id]}

    streams = make_streams([{"jsonrpc": "2.0", "id": 1, "method": "demo.multi"}])
    server = RpcServer(instream=streams.instream, outstream=streams.outstream)
    server.serve()
    server.jobs.join(timeout=5)

    # Every stdout line must independently parse as JSON (no torn writes).
    for raw in streams.outstream.getvalue().splitlines():
        if raw.strip():
            json.loads(raw)
