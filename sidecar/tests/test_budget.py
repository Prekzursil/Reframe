"""Unit tests for media_studio.models.budget (WU-budget, pure half).

This module is PURE: ``estimate`` and ``degrade_chain`` take their collaborators
(``request``, ``pool``, ``catalog``) as duck-typed parameters and never touch the
network, a clock, or any heavy dependency. Every collaborator here is a tiny fake
so the assertions are real behavioural checks, not mock-echoes.

Acceptance pinned (PLAN §WU-budget):
  * ``estimate`` pure for text-only / frame / mixed requests.
  * ``degrade_chain`` ordering (cloud providers in pool order, ``"local"`` last).
  * ``withinFreeLimits`` false when the estimate exceeds a provider's free cap.
  * ``DEFAULT_TARGET_JOB_SIZE`` yields a falsifiable request count when the
    request pins no size.
  * a request is never double-counted.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from media_studio.models import budget as budget_mod
from media_studio.models.budget import (
    DEFAULT_TARGET_JOB_SIZE,
    Budget,
    EgressKinds,
    degrade_chain,
    estimate,
)


# --------------------------------------------------------------------------- #
# duck-typed fakes (the collaborators estimate/degrade_chain accept)
# --------------------------------------------------------------------------- #
class FakeRequest:
    """A planned AI request: how many target units, and the per-unit egress.

    ``target_size`` is the number of discrete outputs (e.g. shorts) the job will
    produce; ``None`` means "not pinned" → estimate falls back to the default.
    ``text_bytes`` / ``frame_bytes`` are the bytes egressed PER request.
    """

    def __init__(
        self,
        *,
        target_size: int | None,
        text_bytes: int = 0,
        frame_bytes: int = 0,
    ) -> None:
        self.target_size = target_size
        self.text_bytes = text_bytes
        self.frame_bytes = frame_bytes


class FakeEntry:
    """A pool entry: a provider id, whether it is the local backstop, and unit."""

    def __init__(self, provider: str, *, local: bool = False, unit: str = "req") -> None:
        self.provider = provider
        self.local = local
        self.unit = unit


class FakePool:
    """An ordered pool of entries (cloud first, local backstop last)."""

    def __init__(self, entries: list[FakeEntry]) -> None:
        self.entries = entries


class FakeCatalog:
    """A catalog exposing a per-provider free request cap (``None`` = uncapped)."""

    def __init__(self, caps: dict[str, int | None]) -> None:
        self._caps = caps

    def free_cap(self, provider: str) -> int | None:
        return self._caps.get(provider)


def _cloud_pool() -> FakePool:
    return FakePool(
        [
            FakeEntry("groq"),
            FakeEntry("cerebras"),
            FakeEntry("local-backstop", local=True),
        ]
    )


# --------------------------------------------------------------------------- #
# Budget dataclass shape
# --------------------------------------------------------------------------- #
def test_budget_is_frozen_and_carries_all_fields() -> None:
    b = Budget(
        requests=3,
        providers=("groq",),
        egressBytes=12,
        egressKinds=EgressKinds(text=12, frames=0),
        withinFreeLimits=True,
    )
    assert b.requests == 3
    assert b.providers == ("groq",)
    assert b.egressBytes == 12
    assert b.egressKinds.text == 12
    assert b.egressKinds.frames == 0
    assert b.withinFreeLimits is True
    with pytest.raises(FrozenInstanceError):
        b.requests = 9  # type: ignore[misc]


def test_egresskinds_is_frozen() -> None:
    k = EgressKinds(text=1, frames=2)
    with pytest.raises(FrozenInstanceError):
        k.text = 5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# estimate — text-only / frame / mixed (purity + egress split)
# --------------------------------------------------------------------------- #
def test_estimate_text_only_splits_egress_to_text() -> None:
    req = FakeRequest(target_size=2, text_bytes=100)
    cat = FakeCatalog({"groq": 1000})
    b = estimate(req, _cloud_pool(), cat)
    assert b.requests == 2
    assert b.egressKinds.text == 200  # 2 requests × 100 text bytes
    assert b.egressKinds.frames == 0
    assert b.egressBytes == 200


def test_estimate_frame_only_splits_egress_to_frames() -> None:
    req = FakeRequest(target_size=3, frame_bytes=500)
    cat = FakeCatalog({"groq": 1000})
    b = estimate(req, _cloud_pool(), cat)
    assert b.requests == 3
    assert b.egressKinds.text == 0
    assert b.egressKinds.frames == 1500  # 3 × 500
    assert b.egressBytes == 1500


def test_estimate_mixed_sums_both_kinds() -> None:
    req = FakeRequest(target_size=2, text_bytes=100, frame_bytes=500)
    cat = FakeCatalog({"groq": 1000})
    b = estimate(req, _cloud_pool(), cat)
    assert b.requests == 2
    assert b.egressKinds.text == 200
    assert b.egressKinds.frames == 1000
    assert b.egressBytes == 1200


def test_estimate_is_pure_no_collaborator_mutation() -> None:
    req = FakeRequest(target_size=2, text_bytes=10)
    pool = _cloud_pool()
    cat = FakeCatalog({"groq": 1000})
    before = [e.provider for e in pool.entries]
    estimate(req, pool, cat)
    assert [e.provider for e in pool.entries] == before  # pool untouched


# --------------------------------------------------------------------------- #
# providers list — cloud entries only, deduped, never the local backstop
# --------------------------------------------------------------------------- #
def test_estimate_providers_excludes_local_backstop() -> None:
    req = FakeRequest(target_size=1, text_bytes=1)
    b = estimate(req, _cloud_pool(), FakeCatalog({}))
    assert "local-backstop" not in b.providers
    assert b.providers == ("groq", "cerebras")


def test_estimate_providers_deduped() -> None:
    pool = FakePool(
        [FakeEntry("groq"), FakeEntry("groq"), FakeEntry("local", local=True)]
    )
    req = FakeRequest(target_size=1, text_bytes=1)
    b = estimate(req, pool, FakeCatalog({}))
    assert b.providers == ("groq",)  # second key = failover, not extra provider


# --------------------------------------------------------------------------- #
# default target job size (P1 #6) — falsifiable count
# --------------------------------------------------------------------------- #
def test_estimate_uses_default_target_job_size_when_unpinned() -> None:
    req = FakeRequest(target_size=None, text_bytes=10)
    b = estimate(req, _cloud_pool(), FakeCatalog({"groq": 1000}))
    assert b.requests == DEFAULT_TARGET_JOB_SIZE
    assert b.egressKinds.text == DEFAULT_TARGET_JOB_SIZE * 10


def test_default_target_job_size_is_a_positive_constant() -> None:
    assert isinstance(DEFAULT_TARGET_JOB_SIZE, int)
    assert DEFAULT_TARGET_JOB_SIZE > 0


def test_estimate_zero_or_negative_target_size_falls_back_to_default() -> None:
    # A non-positive pinned size is meaningless → use the documented default.
    req = FakeRequest(target_size=0, text_bytes=10)
    b = estimate(req, _cloud_pool(), FakeCatalog({"groq": 1000}))
    assert b.requests == DEFAULT_TARGET_JOB_SIZE


# --------------------------------------------------------------------------- #
# withinFreeLimits — false when estimate exceeds the catalog's per-provider cap
# --------------------------------------------------------------------------- #
def test_within_free_limits_true_when_under_cap() -> None:
    req = FakeRequest(target_size=5, text_bytes=1)
    cat = FakeCatalog({"groq": 1000, "cerebras": 1000})
    b = estimate(req, _cloud_pool(), cat)
    assert b.withinFreeLimits is True


def test_within_free_limits_false_when_exceeds_a_providers_cap() -> None:
    req = FakeRequest(target_size=50, text_bytes=1)
    # groq capped at 30 < 50 requests → over the free cap for that provider.
    cat = FakeCatalog({"groq": 30, "cerebras": 1000})
    b = estimate(req, _cloud_pool(), cat)
    assert b.withinFreeLimits is False


def test_within_free_limits_true_when_provider_uncapped() -> None:
    req = FakeRequest(target_size=10_000, text_bytes=1)
    cat = FakeCatalog({"groq": None, "cerebras": None})  # None = uncapped
    b = estimate(req, _cloud_pool(), cat)
    assert b.withinFreeLimits is True


def test_within_free_limits_true_when_no_cloud_providers() -> None:
    # local-only pool: nothing egresses, no cap can be exceeded.
    pool = FakePool([FakeEntry("local", local=True)])
    req = FakeRequest(target_size=10_000, text_bytes=1)
    b = estimate(req, pool, FakeCatalog({}))
    assert b.providers == ()
    assert b.withinFreeLimits is True


# --------------------------------------------------------------------------- #
# degrade_chain — cloud in pool order, "local" last exactly once
# --------------------------------------------------------------------------- #
def test_degrade_chain_orders_cloud_then_local() -> None:
    chain = degrade_chain(_cloud_pool())
    assert chain == ["groq", "cerebras", "local"]


def test_degrade_chain_dedupes_same_provider_keys() -> None:
    pool = FakePool(
        [FakeEntry("groq"), FakeEntry("groq"), FakeEntry("cerebras"), FakeEntry("x", local=True)]
    )
    assert degrade_chain(pool) == ["groq", "cerebras", "local"]


def test_degrade_chain_always_ends_in_local_even_with_no_backstop() -> None:
    pool = FakePool([FakeEntry("groq")])
    chain = degrade_chain(pool)
    assert chain[-1] == "local"
    assert chain == ["groq", "local"]


def test_degrade_chain_local_only_pool() -> None:
    pool = FakePool([FakeEntry("local", local=True)])
    assert degrade_chain(pool) == ["local"]


def test_degrade_chain_does_not_mutate_pool() -> None:
    pool = _cloud_pool()
    before = [e.provider for e in pool.entries]
    degrade_chain(pool)
    assert [e.provider for e in pool.entries] == before


# --------------------------------------------------------------------------- #
# never double-count a request (gate-2/DESIGN R5)
# --------------------------------------------------------------------------- #
def test_request_count_independent_of_provider_count() -> None:
    # Same target size; one pool has many cloud keys, one has few. The request
    # COUNT must be identical (requests are not multiplied by providers/keys).
    req = FakeRequest(target_size=4, text_bytes=1)
    many = FakePool(
        [FakeEntry("a"), FakeEntry("b"), FakeEntry("c"), FakeEntry("l", local=True)]
    )
    few = FakePool([FakeEntry("a"), FakeEntry("l", local=True)])
    cat = FakeCatalog({"a": 1000, "b": 1000, "c": 1000})
    assert estimate(req, many, cat).requests == 4
    assert estimate(req, few, cat).requests == 4


# --------------------------------------------------------------------------- #
# module hygiene — pure (no time / network imports)
# --------------------------------------------------------------------------- #
def test_module_imports_no_clock_or_network() -> None:
    for forbidden in ("time", "asyncio", "urllib", "httpx", "socket"):
        assert not hasattr(budget_mod, forbidden), f"{forbidden} leaked into budget module"


def test_estimate_accepts_any_duck_typed_collaborators() -> None:
    # A minimal collaborator exposing only what the contract names still works.
    class MiniReq:
        target_size = 1
        text_bytes = 7
        frame_bytes = 0

    class MiniEntry:
        provider = "p"
        local = False

    class MiniPool:
        entries = [MiniEntry()]

    class MiniCatalog:
        def free_cap(self, provider: str) -> int | None:
            return 100

    b = estimate(MiniReq(), MiniPool(), MiniCatalog())  # type: ignore[arg-type]
    assert b.requests == 1
    assert b.egressKinds.text == 7
