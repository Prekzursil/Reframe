"""AI-Job envelope (WU-envelope, PLAN §WU-envelope).

A typed substrate ``{inputs, route, costEst, cacheKey, preview, result, cancel}``
that every AI call rides, so cost-preview, cache, budget, graceful-degradation and
universal progress / cancel / reveal (UX6) hang off ONE object. It is built on the
existing ``jobs.py`` ``Job`` / ``JobContext`` / ``JobRegistry`` — there is NO second
job bus here; :func:`run_ai_job` executes the work on a ``ctx.jobs`` job and emits
``job.progress`` / ``job.done`` through the existing :class:`JobContext`.

Two layers, mirroring the rest of the Hub:

  * :func:`plan_ai_job` is **PURE** — it assembles the envelope's ``route``,
    ``costEst`` (via :mod:`models.budget`), and ``cacheKey`` (via
    :class:`models.ai_cache.AiCache`) from the request + the rotation ``pool`` +
    the static ``catalog`` WITHOUT touching the network or a provider. It is the
    engine behind the ``ai.planJob`` pre-flight RPC, which must perform ZERO
    provider calls.
  * :func:`run_ai_job` executes the planned envelope on a job: it consults the
    cache FIRST (a hit skips the provider entirely and flags ``cacheHit``), runs
    the resolved provider on a miss, enforces the budget's degrade chain, and
    emits a single ``degraded`` notice when a run falls through to the local
    backstop.

The collaborators (``jobs``, ``provider_factory``, ``cache``, ``budget``) are all
injected so the unit tests drive the whole flow with tiny fakes and never open a
socket, spawn a model, or read a real clock. This module imports only its sibling
PURE helpers (``budget``, ``ai_cache``) — never the heavy provider transport.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from . import budget as _budget
from .ai_cache import AiCache, Message
from .budget import Budget

# --------------------------------------------------------------------------- #
# Route — the resolved plan flags the envelope carries to the UI
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AiRoute:
    """How a planned AI call WILL run (no side effects to compute it).

    Attributes:
        providers: the distinct cloud providers the call may use, in failover
            order (the local backstop is excluded — it is the implicit last hop).
        degradeChain: the full failover order ``[provider, …, "local"]`` the run
            will fall through, ending in the always-available local backstop.
        cacheHit: ``True`` iff the cache already holds this exact request, so the
            run will return instantly with ZERO provider calls.
        willEgress: ``True`` iff running WOULD send bytes off the machine — i.e.
            there is at least one cloud provider AND it is not a cache hit. A
            cache hit or a local-only pool never egresses.
    """

    providers: tuple[str, ...]
    degradeChain: tuple[str, ...]  # noqa: N815 -- RPC/JSON wire field (PLAN-pinned)
    cacheHit: bool  # noqa: N815 -- RPC/JSON wire field (PLAN-pinned)
    willEgress: bool  # noqa: N815 -- RPC/JSON wire field (PLAN-pinned)


# --------------------------------------------------------------------------- #
# AiJob — the envelope
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AiJob:
    """The typed envelope every AI call rides (PLAN §WU-envelope).

    ``inputs`` is the canonical request (messages + model + params) the cache key
    and provider call are derived from. ``route`` / ``costEst`` / ``cacheKey`` are
    filled by :func:`plan_ai_job`. ``preview`` is the human-readable pre-flight
    summary surfaced before a cloud run. ``result`` / ``cancel`` are the outcome
    fields :func:`run_ai_job` populates on a freshly-derived copy — the planned
    envelope itself stays immutable.
    """

    inputs: AiInputs
    route: AiRoute
    costEst: Budget  # noqa: N815 -- RPC/JSON wire field (PLAN-pinned)
    cacheKey: str  # noqa: N815 -- RPC/JSON wire field (PLAN-pinned)
    preview: str
    result: Any = None
    cancel: bool = False

    def planned(self) -> dict[str, Any]:
        """The pre-flight JSON the ``ai.planJob`` RPC returns (NO execution).

        Shape (PLAN acceptance): ``{route, costEst, cacheHit, willEgress, budget}``
        — ``costEst`` and ``budget`` are the same :class:`Budget`, surfaced under
        both the plan's pinned ``costEst`` name and the budget-acceptance
        ``budget`` name so either reader finds it.
        """
        return {
            "route": _route_json(self.route),
            "costEst": _budget_json(self.costEst),
            "cacheHit": self.route.cacheHit,
            "willEgress": self.route.willEgress,
            "budget": _budget_json(self.costEst),
            "preview": self.preview,
            "cacheKey": self.cacheKey,
        }


@dataclass(frozen=True)
class AiInputs:
    """The canonical AI request: messages + model + sampling params + a budget shape.

    ``params`` are the sampling knobs that participate in the cache key (so a
    temperature change misses). ``request`` is the duck-typed budget request
    (``target_size`` / ``text_bytes`` / ``frame_bytes``) the cost estimate reads.
    ``capability`` is what the provider must serve (``"text"`` / ``"vision"``).
    """

    messages: tuple[Message, ...]
    model: str
    params: Mapping[str, Any] = field(default_factory=dict)
    request: _budget.BudgetRequest | None = None
    capability: str = "text"


# --------------------------------------------------------------------------- #
# Collaborator contracts (faked in tests)
# --------------------------------------------------------------------------- #
@runtime_checkable
class _PoolLike(Protocol):
    """The rotation-pool surface :mod:`ai_job` reads (a :class:`Budget` pool)."""

    entries: object  # iterable of entries carrying ``provider`` + ``local``


@runtime_checkable
class _ChatProvider(Protocol):
    """The minimal provider surface :func:`run_ai_job` drives."""

    def chat(self, messages: Sequence[Message], **kwargs: Any) -> str: ...


# A provider factory: returns the resolved (rotating) provider for the run. It is
# called at most ONCE, only on a cache miss — a cache hit never builds a provider.
ProviderFactory = Any  # Callable[[], _ChatProvider]; kept loose for the closure path


# --------------------------------------------------------------------------- #
# JSON serialization (the wire shapes the renderer reads verbatim)
# --------------------------------------------------------------------------- #
def _budget_json(b: Budget) -> dict[str, Any]:
    """Serialize a :class:`Budget` to its pinned camelCase wire shape."""
    return {
        "requests": b.requests,
        "providers": list(b.providers),
        "egressBytes": b.egressBytes,
        "egressKinds": {"text": b.egressKinds.text, "frames": b.egressKinds.frames},
        "withinFreeLimits": b.withinFreeLimits,
    }


def _route_json(r: AiRoute) -> dict[str, Any]:
    """Serialize an :class:`AiRoute` to its pinned camelCase wire shape."""
    return {
        "providers": list(r.providers),
        "degradeChain": list(r.degradeChain),
        "cacheHit": r.cacheHit,
        "willEgress": r.willEgress,
    }


# --------------------------------------------------------------------------- #
# plan_ai_job — PURE: assemble the envelope (the ai.planJob engine)
# --------------------------------------------------------------------------- #
def _default_request(inputs: AiInputs) -> _budget.BudgetRequest:
    """The budget request for ``inputs`` — the explicit one, or a text-sized fallback.

    When the inputs pin no budget request we derive a single-output text request
    whose ``text_bytes`` is the encoded size of the messages, so an unsized plan
    still yields a falsifiable, non-zero estimate.
    """
    if inputs.request is not None:
        return inputs.request
    text_bytes = sum(len(str(m.get("content", "")).encode("utf-8")) for m in inputs.messages)
    return _TextRequest(target_size=1, text_bytes=text_bytes, frame_bytes=0)


@dataclass
class _TextRequest:
    """A minimal :class:`budget.BudgetRequest` for an unsized text-only call.

    Non-frozen so its fields are *writable* and the instance structurally
    satisfies the duck-typed ``budget.BudgetRequest`` protocol (whose members are
    mutable attributes); it is constructed once and never mutated in practice.
    """

    target_size: int | None
    text_bytes: int
    frame_bytes: int


def plan_ai_job(
    inputs: AiInputs,
    *,
    pool: _PoolLike,
    catalog: _budget.Catalog,
    cache: AiCache,
) -> AiJob:
    """Assemble an :class:`AiJob` envelope for ``inputs`` (PURE — no provider call).

    Builds the cache key (so a hit is known before any run), the budget estimate
    (cost + egress, via :mod:`models.budget`), and the route flags. A cache hit
    forces ``willEgress=False`` (the run will not leave the machine); otherwise
    ``willEgress`` is true iff the pool has at least one cloud provider.
    """
    cache_key = cache.key(list(inputs.messages), inputs.model, dict(inputs.params))
    cache_hit = cache.get(cache_key) is not None
    cost = _budget.estimate(_default_request(inputs), pool, catalog)
    chain = tuple(_budget.degrade_chain(pool))
    will_egress = (not cache_hit) and bool(cost.providers)
    route = AiRoute(
        providers=cost.providers,
        degradeChain=chain,
        cacheHit=cache_hit,
        willEgress=will_egress,
    )
    return AiJob(
        inputs=inputs,
        route=route,
        costEst=cost,
        cacheKey=cache_key,
        preview=_preview_text(cost, cache_hit),
    )


def _preview_text(cost: Budget, cache_hit: bool) -> str:
    """A one-line human pre-flight summary (UX6 reveal/confirm copy)."""
    if cache_hit:
        return "Cached — returns instantly, sends nothing."
    if not cost.providers:
        return f"Local only — {cost.requests} request(s), sends nothing off the machine."
    providers = ", ".join(cost.providers)
    kb = cost.egressBytes / 1024
    return (
        f"~{cost.requests} request(s) across {providers}; "
        f"sends ~{kb:.1f} KB ({cost.egressKinds.text} text / "
        f"{cost.egressKinds.frames} frame bytes)."
    )


# --------------------------------------------------------------------------- #
# run_ai_job — execute the envelope on a job (cache-first, degrade-aware)
# --------------------------------------------------------------------------- #
# A custom work body: given the live JobContext + the planned envelope, do the
# handler-specific work and return its own result dict (the job.done payload).
# When supplied, it REPLACES the default single-chat body but keeps the
# envelope's cancel-check + progress framing. The provider it consumes is built
# by ``provider_factory`` and handed in so degrade-tracking still applies.
AiWork = Callable[[Any, AiJob, Any], dict[str, Any]]

# A completion hook fired with the planned envelope AFTER a run that actually
# egressed (a real cloud call — including one that degraded to local). It is NOT
# fired on a cache hit, a local-only pool, a cancel-before-call, or a provider
# error. The handler passes a closure that records the run's cost in the
# spend ledger (WU-spend-cap record-at-completion); the default ``None`` keeps the
# substrate persistence-free for every non-billed caller.
OnEgress = Callable[[AiJob], None]


def run_ai_job(
    envelope: AiJob,
    *,
    jobs: Any,
    provider_factory: ProviderFactory,
    cache: AiCache,
    budget: object | None = None,  # noqa: ARG001 - reserved; degrade chain rides the envelope
    work: AiWork | None = None,
    feature: str = "ai",
    label: str = "AI",
    videoId: str | None = None,  # noqa: N803 - wire-name kwarg (matches JobRegistry)
    on_egress: OnEgress | None = None,
) -> Any:
    """Run ``envelope`` on a ``jobs`` job; return the created :class:`jobs.Job`.

    Two modes share the SAME envelope framing (cancel-check first, the one job
    bus, degrade tracking):

      * **default chat** (no ``work``) — cache-first: a cache hit returns the
        stored result with ZERO provider calls (the ``provider_factory`` is never
        invoked); a miss builds the provider once, drives one ``chat``, caches
        the fresh result, and flags ``degraded`` when the run fell through to
        local. The done payload is ``{result, cacheHit, degraded}``.
      * **custom work** (``work`` supplied) — the handler-specific body (e.g.
        ``select_unified`` / ``translate``) runs through the envelope so it gets
        the shared cancel-check + a degrade-aware provider, and returns its OWN
        result shape verbatim to ``job.done`` (preserving each handler's existing
        ``{candidates}`` / ``{track}`` contract).

    Cancellation is honored via ``ctx.cancelled`` before any provider work — a
    cancelled job makes no call.
    """

    def job_body(ctx: Any) -> dict[str, Any]:
        if ctx.cancelled:
            return {"cancelled": True}
        ctx.progress(0.0, "planning")
        if work is not None:
            return _execute_work(ctx, envelope, provider_factory, work, on_egress)
        cached = cache.get(envelope.cacheKey)
        if cached is not None:
            ctx.progress(100.0, "cache hit")
            return {"result": cached, "cacheHit": True, "degraded": False}
        return _execute_uncached(ctx, envelope, provider_factory, cache, on_egress)

    return jobs.start(job_body, feature=feature, label=label, videoId=videoId)


def _execute_work(
    ctx: Any,
    envelope: AiJob,
    provider_factory: ProviderFactory,
    work: AiWork,
    on_egress: OnEgress | None = None,
) -> dict[str, Any]:
    """Run a custom ``work`` body with a degrade-aware provider; return its result.

    The provider is built once and a ``degraded`` notice is emitted if the run
    fell through to the local backstop, so the handler-specific work inherits the
    same graceful-degradation visibility as the default chat path. When the run
    would egress (a cloud pool), ``on_egress`` is fired AFTER the work completes
    so the cost is recorded only for a run that ran to completion.
    """
    provider = provider_factory()
    degraded_flag = {"hit_local": False}
    _subscribe_degrade(provider, degraded_flag)
    result = work(ctx, envelope, provider)
    if degraded_flag["hit_local"]:
        ctx.progress(99.0, "degraded: fell back to local")
    _fire_on_egress(envelope, on_egress)
    return result


def _execute_uncached(
    ctx: Any,
    envelope: AiJob,
    provider_factory: ProviderFactory,
    cache: AiCache,
    on_egress: OnEgress | None = None,
) -> dict[str, Any]:
    """Build the provider, run the chat, store the result, and flag degradation.

    Reached ONLY on a real cache miss (``job_body`` returns earlier on a hit), so
    firing ``on_egress`` here after the chat records cost exclusively for a run
    that genuinely called a provider — a runtime cache hit, a cancel-before-call,
    and a provider error each return / raise before the record line.
    """
    provider = provider_factory()
    degraded_flag = {"hit_local": False}
    _subscribe_degrade(provider, degraded_flag)
    if ctx.cancelled:
        return {"cancelled": True}
    ctx.progress(10.0, "calling provider")
    result = provider.chat(list(envelope.inputs.messages), **dict(envelope.inputs.params))
    if degraded_flag["hit_local"]:
        ctx.progress(90.0, "degraded: fell back to local")
    cache.put(envelope.cacheKey, result)
    ctx.progress(100.0, "done")
    _fire_on_egress(envelope, on_egress)
    return {"result": result, "cacheHit": False, "degraded": degraded_flag["hit_local"]}


def _fire_on_egress(envelope: AiJob, on_egress: OnEgress | None) -> None:
    """Invoke ``on_egress`` iff a callback is set AND the run would egress.

    A local-only pool (``willEgress`` False) never sends bytes off the machine and
    therefore costs nothing — it is not recorded even though the local provider
    ran. A degraded-to-local run kept ``willEgress`` True (it attempted cloud) and
    IS recorded: for a spend ceiling, over-counting stops the user sooner (the safe
    direction) and keeps the record decision free of the degrade flag.
    """
    if on_egress is not None and envelope.route.willEgress:
        on_egress(envelope)


def _subscribe_degrade(provider: Any, flag: dict[str, bool]) -> None:
    """Register a rotation listener that flips ``flag`` when the run hits local.

    The rotation pool emits a :class:`provider.RotationEvent` per failover; a
    failover whose target provider is the local backstop (``"local"``) means the
    run degraded. Providers without an ``on_rotation`` hook (the plain local /
    cloud providers) simply never degrade — the call is a graceful no-op.
    """
    on_rotation = getattr(provider, "on_rotation", None)
    if not callable(on_rotation):
        return

    def _listener(event: Any) -> None:
        if getattr(event, "provider", "") == "local":
            flag["hit_local"] = True

    on_rotation(_listener)


# --------------------------------------------------------------------------- #
# Catalog adapter (WAVE-1 CARRYFORWARD #1)
# --------------------------------------------------------------------------- #
# The real ``models.catalog`` keys ``per_task_tier`` by a ``Task`` enum and has
# no ``all()`` / ``free_cap()`` — its free limits are a human string
# (``free_limits`` like "30 RPM / 1K RPD / 200K TPD"), NOT a structured numeric
# per-request cap. :func:`budget.estimate` needs a ``Catalog`` with
# ``free_cap(provider) -> int | None`` where ``None`` means "uncapped for this
# estimate". This adapter bridges the two WITHOUT duplicating the catalog: it
# returns ``None`` for every provider, so the budget never FALSELY claims an
# over-cap from a limit it cannot parse numerically. A structured per-provider
# numeric cap (parsing the RPD/TPD string) is a LATER refinement; until then the
# honest answer is "uncapped" and ``withinFreeLimits`` stays ``True`` here.
class CatalogFreeCapAdapter:
    """Adapts the real catalog module to :func:`budget.estimate`'s ``Catalog``.

    Holds the catalog reference for forward-compat (a future version can parse a
    provider's ``free_limits`` into a numeric RPD cap); today every provider is
    reported uncapped (``None``) — the honest answer given the string-only limits.
    """

    def __init__(self, catalog_module: Any | None = None) -> None:
        self._catalog = catalog_module

    def free_cap(self, provider: str) -> int | None:  # noqa: ARG002 - uncapped today
        """Return the per-provider free request cap, or ``None`` (uncapped)."""
        return None


__all__ = [
    "AiInputs",
    "AiJob",
    "AiRoute",
    "CatalogFreeCapAdapter",
    "plan_ai_job",
    "run_ai_job",
]
