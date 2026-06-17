"""Pre-flight cost / egress budget for cloud AI runs (WU-budget, the PURE half).

Before a cloud AI run the Hub must answer, *without sending anything*: "~N
requests across K providers, sends X bytes (split text vs frames) — proceed?"
(PLAN P1) and it must order the providers the run will fall through on failover
down to the always-available local backstop (PLAN P2).

This module is **PURE**. Its two public functions take their collaborators —
the planned ``request``, the rotation ``pool``, and the static ``catalog`` — as
**parameters** and never construct them, never touch the network, never read a
clock. The collaborators are **duck-typed** (see the Protocols below); the real
implementations land in their own WUs (``models.catalog`` / ``models.provider``)
and the tests inject tiny fakes. This module imports NO heavy dependency and does
NOT cross-import the other Hub modules at runtime.

What the two functions compute:
  * :func:`estimate` → a :class:`Budget` describing the request count, the
    distinct cloud providers involved (the local backstop is never billed),
    the egress bytes split by kind (text vs frames), and whether the estimate
    stays inside every involved provider's catalog free cap.
  * :func:`degrade_chain` → the ordered failover chain ``[provider, …, "local"]``
    used both by rotation and by the "degraded to local" notice. The local
    backstop is always the final, single entry (literal ``"local"``).

The request count NEVER multiplies with the number of providers or keys — a
second same-provider key is failover, not extra quota (PLAN SE2 / DESIGN R5),
and a request is counted exactly once regardless of pool shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# Default target job size (PLAN P1 #6 — PROMOTED to acceptance)
# --------------------------------------------------------------------------- #
#: How many discrete outputs a job produces when the request pins NO size.
#:
#: DOCUMENTED PLACEHOLDER: the concrete value (e.g. one 60-min source → N shorts)
#: is an open product decision for the user (PLAN §5.6). Until the user pins it,
#: :func:`estimate` uses this constant so the pre-flight budget yields a
#: falsifiable request count for an unsized job. Change the value here once the
#: user decides; do not scatter the magic number into callers.
DEFAULT_TARGET_JOB_SIZE: int = 8


# --------------------------------------------------------------------------- #
# Duck-typed collaborator contracts (faked in tests, real impls land elsewhere)
# --------------------------------------------------------------------------- #
@runtime_checkable
class BudgetRequest(Protocol):
    """The planned AI request, from the caller's perspective.

    ``target_size`` is how many discrete outputs the job will produce (e.g.
    shorts). ``None`` (or a non-positive value) means the size is not pinned →
    :func:`estimate` falls back to :data:`DEFAULT_TARGET_JOB_SIZE`. The two byte
    fields are the egress PER request, split by data kind.
    """

    target_size: int | None
    text_bytes: int
    frame_bytes: int


@runtime_checkable
class PoolEntry(Protocol):
    """One entry in the rotation pool: a provider id and a backstop flag.

    ``local`` is ``True`` only for the always-available local backstop, which is
    never billed and never appears as a distinct cloud provider in the budget.
    """

    provider: str
    local: bool


@runtime_checkable
class ProviderPool(Protocol):
    """An ordered pool of :class:`PoolEntry` (cloud first, local backstop last)."""

    entries: object  # an iterable of PoolEntry (iterated, never mutated)


@runtime_checkable
class Catalog(Protocol):
    """The static catalog, queried for a provider's free request cap.

    ``free_cap`` returns the per-provider free request ceiling, or ``None`` when
    the provider is effectively uncapped for this estimate.
    """

    def free_cap(self, provider: str) -> int | None: ...


# --------------------------------------------------------------------------- #
# Result dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EgressKinds:
    """Egress bytes split by data kind (text transcripts vs vision frames)."""

    text: int
    frames: int


@dataclass(frozen=True)
class Budget:
    """A pre-flight estimate for a cloud AI run (no side effects to produce it).

    Attributes:
        requests: how many provider calls the run will make (counted ONCE,
            independent of pool / key count).
        providers: the distinct cloud providers involved, in pool order; the
            local backstop is excluded (it is never billed).
        egressBytes: total bytes leaving the machine (``text + frames``).
        egressKinds: the egress split by kind so the UI can show "sends X text /
            Y frame bytes to provider Z".
        withinFreeLimits: ``False`` iff the request count exceeds the catalog's
            free cap for ANY involved provider; ``True`` when every involved
            provider is under-cap (or uncapped, or there are no cloud providers).
    """

    requests: int
    providers: tuple[str, ...]
    # camelCase fields are the JSON wire shape this Budget serialises to over RPC
    # (PLAN §WU-budget pins these exact names; the renderer reads them verbatim),
    # so the pep8-naming N815 finding is an intentional, file-local suppression.
    egressBytes: int  # noqa: N815 -- RPC/JSON wire field name (PLAN-pinned)
    egressKinds: EgressKinds  # noqa: N815 -- RPC/JSON wire field name (PLAN-pinned)
    withinFreeLimits: bool  # noqa: N815 -- RPC/JSON wire field name (PLAN-pinned)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def _resolve_request_count(target_size: int | None) -> int:
    """The number of requests, falling back to the default for an unpinned size.

    A ``None`` or non-positive ``target_size`` is treated as "not pinned" and
    resolves to :data:`DEFAULT_TARGET_JOB_SIZE` (PLAN P1 #6).
    """
    if target_size is None or target_size <= 0:
        return DEFAULT_TARGET_JOB_SIZE
    return target_size


def _cloud_providers(pool: ProviderPool) -> tuple[str, ...]:
    """Distinct cloud provider ids in pool order (local backstop excluded).

    A provider appearing twice (a second same-provider key) is counted once: an
    extra same-provider key is failover, never additional quota (PLAN SE2).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in pool.entries:  # type: ignore[attr-defined]
        if entry.local:
            continue
        if entry.provider not in seen:
            seen.add(entry.provider)
            ordered.append(entry.provider)
    return tuple(ordered)


def _within_free_limits(requests: int, providers: tuple[str, ...], catalog: Catalog) -> bool:
    """``True`` iff ``requests`` stays at/under every involved provider's cap."""
    for provider in providers:
        cap = catalog.free_cap(provider)
        if cap is not None and requests > cap:
            return False
    return True


def estimate(request: BudgetRequest, pool: ProviderPool, catalog: Catalog) -> Budget:
    """Compute a :class:`Budget` for ``request`` over ``pool`` against ``catalog``.

    PURE: reads only the three duck-typed collaborators, mutates nothing, and
    performs zero I/O. The request count comes from the request's pinned
    ``target_size`` (or :data:`DEFAULT_TARGET_JOB_SIZE` when unpinned) and is
    NOT multiplied by the number of providers/keys. Egress is the per-request
    byte cost times the request count, split into text vs frames.
    """
    requests = _resolve_request_count(request.target_size)
    text_egress = requests * request.text_bytes
    frame_egress = requests * request.frame_bytes
    providers = _cloud_providers(pool)
    return Budget(
        requests=requests,
        providers=providers,
        egressBytes=text_egress + frame_egress,
        egressKinds=EgressKinds(text=text_egress, frames=frame_egress),
        withinFreeLimits=_within_free_limits(requests, providers, catalog),
    )


def degrade_chain(pool: ProviderPool) -> list[str]:
    """The ordered failover chain for ``pool``: cloud providers then ``"local"``.

    PURE: returns the distinct cloud provider ids in pool order (deduped — a
    same-provider second key is failover, not a new hop) followed by exactly one
    final ``"local"`` entry, the always-available backstop. ``"local"`` is
    appended unconditionally so the chain ALWAYS ends in the local backstop,
    even when the pool declared no backstop entry.
    """
    chain = list(_cloud_providers(pool))
    chain.append("local")
    return chain
