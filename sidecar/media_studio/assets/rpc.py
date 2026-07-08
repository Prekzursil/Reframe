"""RPC surface for the assets subsystem (CONTRACTS.md A2).

Registers (imperatively, mirroring the other feature modules — the wiring
agent calls :func:`register` from ``handlers.register_all``):

  * ``assets.list()`` -> ``{assets: [AssetInfo]}``
  * ``assets.ensure({names: [str]})`` -> ``{jobId}`` (long job: streams
    ``job.progress``; ``job.done.result`` = ``{installed, assets}``)
  * ``assets.cancel({jobId})`` -> ``{ok: true}``

CONTRACT-NOTE: A2 freezes ``assets.list``/``assets.ensure``. ``assets.cancel``
is a thin alias over the base contract's ``job.cancel`` (same semantics, same
params) added per the U4 build brief so the Assets panel has a same-namespace
cancel; ``job.cancel`` keeps working for these jobs too.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import manifest
from .manager import AssetManager

log = get_logger("media_studio.assets.rpc")

#: A registered RPC handler: ``(params, ctx) -> result`` (the §2 wire shape).
RpcHandler = Callable[[dict[str, Any], RpcContext], dict[str, Any]]


def make_list_handler(manager: AssetManager) -> RpcHandler:
    """Build the ``assets.list`` handler (direct-return)."""

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        return {"assets": manager.list_assets()}

    return handler


def _validate_custom(params: dict[str, Any]) -> list[str] | None:
    """The optional ``custom`` asset-name list for a Custom profile (WU C1)."""
    custom = params.get("custom")
    if custom is None:
        return None
    if not isinstance(custom, list) or not all(isinstance(n, str) and n for n in custom):
        raise RpcError("custom must be an array of asset names", ErrorCode.INVALID_PARAMS)
    return custom


def make_ensure_handler(manager: AssetManager) -> RpcHandler:
    """Build the ``assets.ensure`` handler (long job, returns ``{jobId}``).

    Accepts EITHER a ``profile`` (Minimum/Default/Full/Custom — resolved to a
    component set via the manifest, WU C1) OR an explicit ``names`` list (the
    original A2 surface, unchanged). A Minimum / empty-Custom profile resolves to
    an empty set and still runs as a (no-op) job for a uniform ``{jobId}`` reply.
    """

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        profile = params.get("profile")
        if profile is not None:
            if not isinstance(profile, str) or not profile:
                raise RpcError("profile (str) is required", ErrorCode.INVALID_PARAMS)
            custom = _validate_custom(params)
            try:
                names: list[str] = manifest.resolve_profile(profile, custom)
            except ValueError as exc:
                raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc
        else:
            raw = params.get("names")
            if not isinstance(raw, list) or not raw or not all(isinstance(n, str) and n for n in raw):
                raise RpcError("names (non-empty array of str) is required", ErrorCode.INVALID_PARAMS)
            names = raw
            unknown = [n for n in names if manifest.get_asset(n) is None]
            if unknown:
                raise RpcError(f"unknown asset(s): {', '.join(unknown)}", ErrorCode.INVALID_PARAMS)
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)

        requested = list(names)

        def job_body(job_ctx: Any) -> dict[str, Any]:
            # Failures (disk preflight, HTTP errors, sha mismatch, env install)
            # raise and surface via the job.done error payload (A6 lesson 3);
            # a single failing item is skipped + noted (WU C1 graceful failure).
            return manager.ensure(requested, job_ctx)

        job = ctx.jobs.start(job_body)
        return {"jobId": job.id}

    return handler


def make_plan_handler(manager: AssetManager) -> RpcHandler:
    """Build the ``assets.plan`` handler (direct-return, WU C1).

    Given a ``profile`` (+ optional ``custom`` names), returns the components it
    would install — each with plain-English what (label) / why + size + installed
    state — plus ``totalMB`` and ``toDownloadMB`` so the UI can show what a
    multi-GB profile buys BEFORE the download starts.
    """

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        profile = params.get("profile")
        if not isinstance(profile, str) or not profile:
            raise RpcError("profile (str) is required", ErrorCode.INVALID_PARAMS)
        custom = _validate_custom(params)
        try:
            return manager.plan(profile, custom)
        except ValueError as exc:
            raise RpcError(str(exc), ErrorCode.INVALID_PARAMS) from exc

    return handler


def make_cancel_handler() -> RpcHandler:
    """Build the ``assets.cancel`` handler (delegates to the job registry)."""

    def handler(params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        job_id = params.get("jobId")
        if not isinstance(job_id, str) or not job_id:
            raise RpcError("jobId (str) is required", ErrorCode.INVALID_PARAMS)
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        # Same no-op-on-unknown semantics as job.cancel (§2).
        ctx.jobs.cancel(job_id)
        return {"ok": True}

    return handler


def register(
    manager: AssetManager | None = None,
    *,
    root: Any | None = None,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> AssetManager:
    """Register the assets.* methods on the shared METHODS registry.

    Called by the composition root (``handlers.register_all``) with the
    services' data dir + settings getter; tests pass a prebuilt manager and/or
    a fake ``register_fn``. Returns the manager so the caller can keep it.
    """
    mgr = manager or AssetManager(root=root, settings_provider=settings_provider)
    reg = register_fn if register_fn is not None else protocol.register
    reg("assets.list", make_list_handler(mgr))
    reg("assets.plan", make_plan_handler(mgr))
    reg("assets.ensure", make_ensure_handler(mgr))
    reg("assets.cancel", make_cancel_handler())
    log.info("registered assets.list / assets.plan / assets.ensure / assets.cancel")
    return mgr
