"""Unit tests for the WU-B2 local-LLM auto-start seam (fixes ``LLM 10061``).

The llama backstop slot must lazily ensure the local llama.cpp server is up
before a chat reaches it. This module pins the two NEW provider-side pieces:

  * :func:`provider.readiness_probe` — a bounded wall-clock poll of ``GET
    /health`` that returns on a ``200``, keeps waiting on ``503`` / a refused
    connection, fails fast when the child process exits, and RAISES a
    :class:`ProviderError` on timeout (so it NEVER hangs);
  * the ``ensure`` callback injected into :class:`RotatingProvider` — invoked
    lazily ONLY for the ``local`` backstop slot (``provider == "local"``), only
    after the cloud entries ahead of it are exhausted, and NEVER for a detected
    Ollama / LM-Studio server (those are probed live, not managed).

Every collaborator is faked: a scripted GET transport (no socket), a fake clock
(deterministic deadline), a fake ``sleep`` (no real pacing), and a
``child_exited`` predicate.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import provider as prov
from media_studio.models.provider import (
    DEFAULT_LOCAL_BASE_URL,
    PoolEntrySpec,
    ProviderError,
    RotatingProvider,
    RotationEvent,
    health_url_from_base,
    readiness_probe,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _ok(content: str = "ok") -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class ScriptedTransport:
    """A fake chat transport keyed by Bearer key (mirrors test_rotating_provider)."""

    def __init__(self, by_key: dict[str | None, list[Any]]) -> None:
        self.by_key = by_key
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        auth = headers.get("Authorization", "")
        key = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
        self.calls.append({"url": url, "key": key})
        script = self.by_key.get(key)
        if not script:
            raise ProviderError(f"LLM request failed: nothing scripted for {key!r}")
        outcome = script[0] if len(script) == 1 else script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _spec(*, provider: str, keys: tuple[str, ...] = (), local: bool = False, capabilities=("text",)) -> PoolEntrySpec:
    return PoolEntrySpec(
        provider=provider,
        kind="local" if local else "cloud",
        base_url="https://api.example/v1" if not local else DEFAULT_LOCAL_BASE_URL,
        model="m",
        keys=keys,
        capabilities=capabilities,
        local=local,
    )


# --------------------------------------------------------------------------- #
# health_url_from_base
# --------------------------------------------------------------------------- #
def test_health_url_strips_v1_suffix() -> None:
    assert health_url_from_base("http://127.0.0.1:8088/v1") == "http://127.0.0.1:8088/health"


def test_health_url_strips_trailing_slash_then_v1() -> None:
    assert health_url_from_base("http://127.0.0.1:8088/v1/") == "http://127.0.0.1:8088/health"


def test_health_url_without_v1_just_appends() -> None:
    assert health_url_from_base("http://host:9000") == "http://host:9000/health"


# --------------------------------------------------------------------------- #
# readiness_probe
# --------------------------------------------------------------------------- #
class ProbeTransport:
    """A GET transport whose per-call outcome drives the readiness_probe status.

    Each queued outcome is either a dict (a 200), or a ProviderError carrying a
    status_code (503 = loading) / None (connection refused). The last outcome
    repeats once the queue is exhausted.
    """

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls += 1
        outcome = self.outcomes[0] if len(self.outcomes) == 1 else self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _probe(transport: Any, *, clock: FakeClock, child_exited: Any, sleeps: list[float], **kw: Any) -> None:
    readiness_probe(
        "http://127.0.0.1:8088/health",
        transport=transport,
        now=clock,
        sleep=sleeps.append,
        child_exited=child_exited,
        **kw,
    )


def test_readiness_probe_returns_immediately_on_200() -> None:
    sleeps: list[float] = []
    transport = ProbeTransport([_ok()])
    _probe(transport, clock=FakeClock(), child_exited=lambda: False, sleeps=sleeps)
    assert transport.calls == 1
    assert sleeps == []  # ready first poll -> never paced


def test_readiness_probe_waits_through_503_then_ready() -> None:
    sleeps: list[float] = []
    transport = ProbeTransport([ProviderError("LLM HTTP 503", status_code=503), _ok()])
    _probe(transport, clock=FakeClock(), child_exited=lambda: False, sleeps=sleeps, poll_interval_s=0.5)
    assert transport.calls == 2
    assert sleeps == [0.5]  # one wait between the 503 and the ready 200


def test_readiness_probe_waits_through_connection_refused() -> None:
    sleeps: list[float] = []
    # status_code None == connection refused (URLError) -> keep waiting.
    transport = ProbeTransport([ProviderError("LLM request failed: refused"), _ok()])
    _probe(transport, clock=FakeClock(), child_exited=lambda: False, sleeps=sleeps)
    assert transport.calls == 2


def test_readiness_probe_raises_when_child_exits() -> None:
    transport = ProbeTransport([ProviderError("LLM request failed: refused")])
    with pytest.raises(ProviderError, match="exited before becoming ready"):
        _probe(transport, clock=FakeClock(), child_exited=lambda: True, sleeps=[])
    assert transport.calls == 0  # child-exit is checked BEFORE the GET


def test_readiness_probe_raises_on_timeout_not_hang() -> None:
    clock = FakeClock(start=100.0)
    # Never-ready: every poll is a refused connection; advance the clock past the
    # deadline on each sleep so the loop terminates deterministically.
    transport = ProbeTransport([ProviderError("LLM request failed: refused")])

    def _sleep(_seconds: float) -> None:
        clock.advance(100.0)  # jump past the deadline

    with pytest.raises(ProviderError, match="not ready within"):
        readiness_probe(
            "http://127.0.0.1:8088/health",
            transport=transport,
            now=clock,
            sleep=_sleep,
            child_exited=lambda: False,
            timeout_s=10.0,
        )


# --------------------------------------------------------------------------- #
# RotatingProvider ensure hook
# --------------------------------------------------------------------------- #
def _rp(specs: list[PoolEntrySpec], transport: Any, ensure: Any) -> RotatingProvider:
    return RotatingProvider(pool=specs, now=FakeClock(), transport=transport, ensure=ensure)


def test_ensure_fires_for_local_backstop_and_warms_it() -> None:
    fired: list[str] = []
    rp = _rp(
        [_spec(provider="local", local=True)],
        ScriptedTransport({None: [_ok("local-hi")]}),
        ensure=lambda: fired.append("ensure"),
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "local-hi"
    assert fired == ["ensure"]  # ensure() ran before the local chat succeeded


def test_ensure_only_after_cloud_entries_are_exhausted() -> None:
    fired: list[str] = []
    # cloud key fails (429) -> rotate to the local backstop -> ensure() then fires.
    transport = ScriptedTransport({"ck": [ProviderError("LLM HTTP 429", status_code=429)], None: [_ok("fallback")]})
    rp = _rp(
        [_spec(provider="Groq", keys=("ck",)), _spec(provider="local", local=True)],
        transport,
        ensure=lambda: fired.append("ensure"),
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "fallback"
    # ensure fired exactly once, and only when the local slot was reached.
    assert fired == ["ensure"]
    assert transport.calls[0]["key"] == "ck"  # cloud tried first
    assert transport.calls[-1]["key"] is None  # then the local backstop


def test_ensure_not_called_when_cloud_succeeds() -> None:
    fired: list[str] = []
    rp = _rp(
        [_spec(provider="Groq", keys=("ck",)), _spec(provider="local", local=True)],
        ScriptedTransport({"ck": [_ok("cloud")], None: [_ok("local")]}),
        ensure=lambda: fired.append("ensure"),
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "cloud"
    assert fired == []  # local slot never reached -> ensure never runs


def test_ensure_not_called_for_detected_ollama_local_server() -> None:
    """A detected Ollama/LM-Studio slot is ``local=True`` but NOT provider=='local'."""
    fired: list[str] = []
    rp = _rp(
        [_spec(provider="ollama", local=True)],
        ScriptedTransport({None: [_ok("ollama")]}),
        ensure=lambda: fired.append("ensure"),
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "ollama"
    assert fired == []  # ensure is llama-backstop-only, never for Ollama


def test_ensure_timeout_raises_provider_error_and_pool_exhausts() -> None:
    def _boom() -> None:
        raise ProviderError("local model server not ready within 60s")

    rp = _rp([_spec(provider="local", local=True)], ScriptedTransport({None: [_ok()]}), ensure=_boom)
    with pytest.raises(ProviderError, match="provider pool exhausted"):
        rp.chat([{"role": "user", "content": "q"}])


def test_ensure_failure_after_cloud_emits_rotation_event() -> None:
    events: list[RotationEvent] = []

    def _boom() -> None:
        raise ProviderError("local not ready")

    transport = ScriptedTransport({"ck": [ProviderError("LLM HTTP 429", status_code=429)]})
    rp = _rp(
        [_spec(provider="Groq", keys=("ck",)), _spec(provider="local", local=True)],
        transport,
        ensure=_boom,
    )
    rp.on_rotation(events.append)
    with pytest.raises(ProviderError, match="provider pool exhausted"):
        rp.chat([{"role": "user", "content": "q"}])
    # a rotation event was emitted for the cloud->local failover even though the
    # local ensure() then failed.
    assert any(e.provider == "local" for e in events)


def test_rotating_provider_ensure_defaults_to_none() -> None:
    # No ensure injected -> the local backstop is used as-is (back-compat).
    rp = RotatingProvider(pool=[_spec(provider="local", local=True)], transport=ScriptedTransport({None: [_ok("x")]}))
    assert rp.chat([{"role": "user", "content": "q"}]) == "x"


# --------------------------------------------------------------------------- #
# get_provider / build_pool_provider ensure threading
# --------------------------------------------------------------------------- #
def test_build_pool_provider_threads_ensure_into_local_only_pool() -> None:
    fired: list[str] = []
    rp = prov.build_pool_provider(
        {},
        transport=ScriptedTransport({None: [_ok("y")]}),
        prefer=prov.LOCAL_PROVIDER_ID,
        ensure=lambda: fired.append("e"),
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "y"
    assert fired == ["e"]


def test_get_provider_bare_local_fallthrough_uses_ensure_pool() -> None:
    fired: list[str] = []
    # No cloud providers configured, no prefer -> the legacy bare-local fall-through,
    # but an injected ensure reroutes it through a local-only pool so auto-start works.
    provider = prov.get_provider({}, transport=ScriptedTransport({None: [_ok("z")]}), ensure=lambda: fired.append("e"))
    assert provider.chat([{"role": "user", "content": "q"}]) == "z"
    assert fired == ["e"]


def test_get_provider_without_ensure_returns_bare_local_server() -> None:
    provider = prov.get_provider({}, transport=ScriptedTransport({None: [_ok("bare")]}))
    # A plain LocalServerProvider (no pool, no ensure) — unchanged legacy behaviour.
    assert isinstance(provider, prov.LocalServerProvider)
    assert provider.chat([{"role": "user", "content": "q"}]) == "bare"
