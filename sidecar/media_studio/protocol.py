"""JSON-RPC 2.0 framing + the METHODS registry (name -> handler).

This module is the public surface map (CONTRACTS.md §2). It is intentionally
transport-agnostic and dependency-free: ``rpc.py`` owns stdin/stdout; this owns
the *shape* of requests, responses, and notifications and the method table.

Handlers register via the ``@method("name")`` decorator. A handler signature is
``handler(params: dict, ctx: RpcContext) -> Any`` and returns the ``result``
payload (or raises :class:`RpcError` to produce a structured error response).

P2 (ADDENDUM A2): ``dispatch`` records the originating method+params on the job
registry for every job-returning handler (result carries a ``jobId``), and the
built-ins gain ``job.list`` (JobInfo list) + ``job.retry`` (re-dispatch the
stored request as a NEW job) beside ``job.cancel`` / ``job.status``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

JSONRPC_VERSION = "2.0"

# Handler signature: (params, ctx) -> result payload.
Handler = Callable[[dict[str, Any], "RpcContext"], Any]

# The public method registry (name -> handler). Populated by @method.
METHODS: dict[str, Handler] = {}


# -- JSON-RPC 2.0 standard error codes (subset we use) ---------------------
class ErrorCode:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


class RpcError(Exception):
    """A handler-raised error that maps to a JSON-RPC ``error`` object."""

    def __init__(self, message: str, code: int = ErrorCode.INTERNAL_ERROR, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_error_obj(self) -> dict[str, Any]:
        obj: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            obj["data"] = self.data
        return obj


@dataclass
class RpcContext:
    """Ambient services a handler may use.

    ``emit_notification`` lets a handler push arbitrary notifications (e.g. via
    the job registry's progress sink). ``jobs`` is the active :class:`JobRegistry`
    (typed loosely to keep this module import-light / free of cycles).
    """

    emit_notification: Callable[[dict[str, Any]], None]
    jobs: Any = None


def method(name: str) -> Callable[[Handler], Handler]:
    """Register ``func`` in :data:`METHODS` under ``name``. Returns it unchanged.

    Raises if ``name`` is already registered, so duplicate/typo method names fail
    loudly at import time rather than silently shadowing a contract method.
    """

    def decorator(func: Handler) -> Handler:
        if name in METHODS:
            raise ValueError(f"duplicate RPC method registration: {name!r}")
        METHODS[name] = func
        return func

    return decorator


def register(name: str, func: Handler) -> None:
    """Imperatively register a handler (for feature modules built elsewhere)."""
    if name in METHODS:
        raise ValueError(f"duplicate RPC method registration: {name!r}")
    METHODS[name] = func


def clear_methods() -> None:
    """Empty the registry (test isolation only)."""
    METHODS.clear()


# -- framing builders ------------------------------------------------------


def make_response(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a success response object for ``request_id``."""
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def make_error(request_id: Any, error: RpcError) -> dict[str, Any]:
    """Build an error response object for ``request_id``."""
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error.to_error_obj()}


def make_notification(rpc_method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build a notification (no id)."""
    return {"jsonrpc": JSONRPC_VERSION, "method": rpc_method, "params": params}


def make_progress(job_id: str, pct: int, message: str) -> dict[str, Any]:
    """Build a ``job.progress`` notification (§2)."""
    return make_notification("job.progress", {"jobId": job_id, "pct": pct, "message": message})


def make_done(job_id: str, result: Any) -> dict[str, Any]:
    """Build a ``job.done`` notification (§2)."""
    return make_notification("job.done", {"jobId": job_id, "result": result})


# -- request validation ----------------------------------------------------


@dataclass
class ParsedRequest:
    """A validated inbound request. ``id`` is None for notifications."""

    id: Any
    method: str
    params: dict[str, Any]
    is_notification: bool


def parse_request(obj: Any) -> ParsedRequest:
    """Validate a decoded JSON object as a JSON-RPC request.

    Raises :class:`RpcError` (INVALID_REQUEST) on a malformed envelope. ``params``
    defaults to ``{}`` when omitted (the contract's methods all take object
    params). A missing ``id`` marks the request a notification.
    """
    if not isinstance(obj, dict):
        raise RpcError("request must be a JSON object", ErrorCode.INVALID_REQUEST)
    if obj.get("jsonrpc") != JSONRPC_VERSION:
        raise RpcError("jsonrpc must be '2.0'", ErrorCode.INVALID_REQUEST)
    rpc_method = obj.get("method")
    if not isinstance(rpc_method, str) or not rpc_method:
        raise RpcError("method must be a non-empty string", ErrorCode.INVALID_REQUEST)
    params = obj.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        # CONTRACT-NOTE: every method in §2 takes object params; we reject
        # positional/array params rather than guess a mapping.
        raise RpcError("params must be an object", ErrorCode.INVALID_PARAMS)
    has_id = "id" in obj
    return ParsedRequest(
        id=obj.get("id"),
        method=rpc_method,
        params=params,
        is_notification=not has_id,
    )


def dispatch(req: ParsedRequest, ctx: RpcContext) -> Any:
    """Look up + invoke the handler for ``req.method``.

    Returns the handler's result payload. Raises :class:`RpcError`
    (METHOD_NOT_FOUND) for an unknown method. Other handler exceptions propagate
    to the caller, which wraps them as INTERNAL_ERROR.

    A2 retry hook: when the handler's result is a job envelope (a dict carrying
    a ``jobId``) and the context's job registry exposes ``record_request``, the
    originating method+params are recorded on the registry so ``job.retry`` can
    re-dispatch the same request later as a NEW job.
    """
    handler = METHODS.get(req.method)
    if handler is None:
        raise RpcError(f"method not found: {req.method}", ErrorCode.METHOD_NOT_FOUND)
    result = handler(req.params, ctx)
    _maybe_record_job_request(req, ctx, result)
    return result


def _maybe_record_job_request(req: ParsedRequest, ctx: RpcContext, result: Any) -> None:
    """Record method+params on the registry for a job-returning handler (A2).

    The registry enforces first-write-wins, so a ``job.retry`` dispatch (whose
    result also carries the new job's id) cannot overwrite the REAL request the
    inner re-dispatch already recorded for that job. Tolerates a missing/fake
    registry (no ``record_request``) so test doubles keep working.
    """
    if not isinstance(result, dict):
        return
    job_id = result.get("jobId")
    if not isinstance(job_id, str) or not job_id:
        return
    record = getattr(ctx.jobs, "record_request", None) if ctx.jobs is not None else None
    if record is None:
        return
    record(job_id, req.method, req.params)


# -- built-in methods ------------------------------------------------------

# CONTRACT-NOTE: §0 / "lean plan" — no separate version source of truth exists in
# the contract, so the protocol version string lives here and ping() returns it.
PROTOCOL_VERSION = "0.1.0"


@method("ping")
def _ping(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """Liveness check. -> {"pong": true, "version": str} (§2)."""
    return {"pong": True, "version": PROTOCOL_VERSION}


@method("job.cancel")
def _job_cancel(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """Request cooperative cancellation of a job. -> {"ok": true} (§2)."""
    job_id = params.get("jobId")
    if not isinstance(job_id, str):
        raise RpcError("jobId (str) is required", ErrorCode.INVALID_PARAMS)
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    ctx.jobs.cancel(job_id)
    # §2: job.cancel -> {ok:true}. Cancelling an unknown/finished job is a no-op.
    return {"ok": True}


@method("job.status")
def _job_status(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """Report a job's lifecycle state. -> {"status", "pct"} (§2)."""
    job_id = params.get("jobId")
    if not isinstance(job_id, str):
        raise RpcError("jobId (str) is required", ErrorCode.INVALID_PARAMS)
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    job = ctx.jobs.get(job_id)
    if job is None:
        raise RpcError(f"unknown job: {job_id}", ErrorCode.INVALID_PARAMS)
    return job.snapshot()


@method("job.list")
def _job_list(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """List jobs as JobInfo, most-recent-first, bounded 100. -> {"jobs"} (A2/A3)."""
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    return {"jobs": ctx.jobs.list_info()}


@method("job.retry")
def _job_retry(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
    """Re-dispatch a job's stored request as a NEW job. -> {"jobId"} (A2).

    Requires the original dispatch to have recorded the request (every
    job-returning method dispatched through :func:`dispatch` is recorded). The
    re-dispatch goes back through :func:`dispatch`, so the NEW job gets its own
    stored request and is itself retryable.

    CONTRACT-NOTE: A2 does not restrict retry to terminal jobs, so a running
    job may be retried too (it simply starts a second job from the same
    request); the UI is expected to offer retry on error/cancelled jobs.
    """
    job_id = params.get("jobId")
    if not isinstance(job_id, str):
        raise RpcError("jobId (str) is required", ErrorCode.INVALID_PARAMS)
    if ctx.jobs is None:
        raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
    if ctx.jobs.get(job_id) is None:
        raise RpcError(f"unknown job: {job_id}", ErrorCode.INVALID_PARAMS)
    stored = ctx.jobs.get_request(job_id)
    if stored is None:
        raise RpcError(
            f"job has no stored request (not retryable): {job_id}",
            ErrorCode.INVALID_PARAMS,
        )
    retry_req = ParsedRequest(
        id=None,
        method=stored["method"],
        params=copy.deepcopy(stored.get("params") or {}),
        is_notification=True,
    )
    result = dispatch(retry_req, ctx)
    new_id = result.get("jobId") if isinstance(result, dict) else None
    if not isinstance(new_id, str) or not new_id:
        raise RpcError(
            f"retry of {stored['method']} did not return a job",
            ErrorCode.INTERNAL_ERROR,
        )
    return {"jobId": new_id}
