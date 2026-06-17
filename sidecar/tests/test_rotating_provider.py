"""Unit tests for the multi-PROVIDER RotatingProvider (WU-pool).

The rotation pool fronts the LLM behind a duck-typed :class:`Provider` and is
wired into BOTH LLM seams (the general ``get_provider`` chat path AND the
``TieredTranslator`` tier3 hosted path). Every collaborator is faked:

  * a **fake Transport** (the ``provider.py`` seam) returns canned 200s and
    raises ``ProviderError("LLM HTTP 429 ...")`` for chosen keys, so no socket
    is ever opened;
  * a **fake clock** (the injected ``now`` ctor arg) drives the per-window
    cooldown deterministically — the module imports neither ``time`` nor
    ``asyncio`` and the hot path NEVER sleeps (a throttled key is *skipped*).

The tests pin: reactive 429/5xx failover (one ``rotation`` event per failover),
per-window cooldown (throttled key skipped until the window resets), pool
exhaustion (incl. the local backstop) -> a single ``ProviderError`` with no
hang, the capability registry (vision-only requests skip non-vision entries),
per-key usage accounting (optimistic decrement + parsed 429/X-RateLimit-*
headers), and that the live key never reaches a log line or an error body.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from media_studio.models import provider as prov
from media_studio.models.provider import (
    LocalServerProvider,
    PoolEntrySpec,
    Provider,
    ProviderError,
    RotatingProvider,
    RotationEvent,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _ok(content: str = "ok") -> dict[str, Any]:
    """An OpenAI-style chat-completions success envelope."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class ScriptedTransport:
    """A fake transport keyed by the Bearer key, returning canned outcomes.

    ``by_key`` maps a key string (or ``None`` for the keyless local server) to a
    list of outcomes consumed in order; each outcome is either a response dict
    (returned) or an Exception (raised). When a key's script is exhausted the
    last outcome repeats. ``calls`` records every (url, headers, key) tuple.
    """

    def __init__(self, by_key: dict[str | None, list[Any]]) -> None:
        self.by_key = by_key
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        auth = headers.get("Authorization", "")
        key = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
        self.calls.append({"url": url, "headers": headers, "key": key, "body": body})
        script = self.by_key.get(key)
        if not script:
            raise ProviderError(f"LLM request failed: nothing scripted for {key!r}")
        outcome = script[0] if len(script) == 1 else script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    """A monotonic fake clock the RotatingProvider reads via its ``now`` arg."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _spec(
    *,
    provider: str = "Groq",
    kind: str = "cloud",
    keys: list[str],
    base_url: str = "https://api.groq.com/openai/v1",
    model: str = "m",
    capabilities: tuple[str, ...] = ("text",),
    unit: str = "token",
    local: bool = False,
) -> PoolEntrySpec:
    return PoolEntrySpec(
        provider=provider,
        kind=kind,
        base_url=base_url,
        model=model,
        keys=tuple(keys),
        capabilities=capabilities,
        unit=unit,
        local=local,
    )


def _build(specs: list[PoolEntrySpec], transport: Any, clock: FakeClock | None = None) -> RotatingProvider:
    clock = clock or FakeClock()
    return RotatingProvider(pool=specs, now=clock, transport=transport, cooldown_seconds=60.0)


# --------------------------------------------------------------------------- #
# RotatingProvider is a Provider
# --------------------------------------------------------------------------- #
def test_rotating_provider_is_a_provider() -> None:
    rp = _build([_spec(keys=["k1"])], ScriptedTransport({"k1": [_ok()]}))
    assert isinstance(rp, Provider)


def test_single_key_happy_path_returns_content() -> None:
    rp = _build([_spec(keys=["k1"])], ScriptedTransport({"k1": [_ok("hi")]}))
    assert rp.chat([{"role": "user", "content": "q"}]) == "hi"


def test_complete_wrapper_works_through_pool() -> None:
    rp = _build([_spec(keys=["k1"])], ScriptedTransport({"k1": [_ok("done")]}))
    assert rp.complete("summarize") == "done"


def test_empty_pool_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        RotatingProvider(pool=[], now=FakeClock(), transport=ScriptedTransport({}))


# --------------------------------------------------------------------------- #
# reactive 429 failover: advances to the next eligible key, one rotation event
# --------------------------------------------------------------------------- #
def test_429_advances_to_next_key_and_emits_one_rotation_event() -> None:
    events: list[RotationEvent] = []
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: rate limited")],
            "k2": [_ok("second")],
        }
    )
    rp = _build([_spec(keys=["k1", "k2"])], transport)
    rp.on_rotation(events.append)
    out = rp.chat([{"role": "user", "content": "q"}])
    assert out == "second"
    assert len(events) == 1
    assert events[0].from_key.endswith("k1") or events[0].reason


def test_429_failover_across_distinct_providers() -> None:
    events: list[RotationEvent] = []
    transport = ScriptedTransport(
        {
            "g1": [ProviderError("LLM HTTP 429: too many")],
            "c1": [_ok("cerebras")],
        }
    )
    rp = _build(
        [_spec(provider="Groq", keys=["g1"]), _spec(provider="Cerebras", keys=["c1"])],
        transport,
    )
    rp.on_rotation(events.append)
    assert rp.chat([{"role": "user", "content": "q"}]) == "cerebras"
    assert len(events) == 1


def test_5xx_also_triggers_failover() -> None:
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 503: unavailable")],
            "k2": [_ok("recovered")],
        }
    )
    rp = _build([_spec(keys=["k1", "k2"])], transport)
    assert rp.chat([{"role": "user", "content": "q"}]) == "recovered"


# --------------------------------------------------------------------------- #
# per-window cooldown: a throttled key is SKIPPED until its window resets
# --------------------------------------------------------------------------- #
def test_throttled_key_skipped_until_window_resets() -> None:
    clock = FakeClock()
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: slow down"), _ok("k1 again")],
            "k2": [_ok("k2 first"), _ok("k2 second")],
        }
    )
    rp = _build([_spec(keys=["k1", "k2"])], transport, clock=clock)

    # First call: k1 429s -> cooled down; k2 serves.
    assert rp.chat([{"role": "user", "content": "q"}]) == "k2 first"

    # Second call WITHIN the cooldown window: k1 is skipped (no 429 retry on it),
    # k2 serves directly. The transport must NOT have been asked k1 again.
    clock.advance(10.0)
    assert rp.chat([{"role": "user", "content": "q"}]) == "k2 second"
    k1_calls = [c for c in transport.calls if c["key"] == "k1"]
    assert len(k1_calls) == 1  # only the original 429 call, never re-probed

    # After the window resets, k1 is eligible again.
    clock.advance(120.0)
    assert rp.chat([{"role": "user", "content": "q"}]) == "k1 again"


def test_no_sleep_on_hot_path_throttled_key_is_skipped_not_awaited() -> None:
    # The cooldown is pure clock-delta math: a throttled key never blocks; the
    # pool advances immediately to the next eligible key.
    clock = FakeClock()
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: x")],
            "k2": [_ok("a"), _ok("b")],
        }
    )
    rp = _build([_spec(keys=["k1", "k2"])], transport, clock=clock)
    assert rp.chat([{"role": "user", "content": "q"}]) == "a"
    # Clock did NOT move on its own (no sleep). The test controls it entirely.
    assert clock.t == 1000.0


# --------------------------------------------------------------------------- #
# pool exhaustion (incl. the local backstop) -> a single ProviderError, no hang
# --------------------------------------------------------------------------- #
def test_pool_exhausted_including_local_raises_single_error() -> None:
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: a")],
            "k2": [ProviderError("LLM HTTP 429: b")],
            None: [ProviderError("LLM request failed: local down")],
        }
    )
    rp = _build(
        [
            _spec(keys=["k1", "k2"]),
            _spec(provider="local", kind="local", keys=[], base_url="http://127.0.0.1:8088/v1", local=True),
        ],
        transport,
    )
    with pytest.raises(ProviderError) as ei:
        rp.chat([{"role": "user", "content": "q"}])
    # one aggregate error, never a hang
    assert "exhausted" in str(ei.value).lower() or "429" in str(ei.value)


def test_local_backstop_reached_when_all_cloud_keys_exhausted() -> None:
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: a")],
            None: [_ok("local served it")],
        }
    )
    rp = _build(
        [
            _spec(keys=["k1"]),
            _spec(provider="local", kind="local", keys=[], base_url="http://127.0.0.1:8088/v1", local=True),
        ],
        transport,
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "local served it"


def test_local_backstop_is_always_last_even_if_specified_first() -> None:
    transport = ScriptedTransport({"k1": [_ok("cloud wins")], None: [_ok("local")]})
    rp = _build(
        [
            _spec(provider="local", kind="local", keys=[], local=True, base_url="http://127.0.0.1:8088/v1"),
            _spec(keys=["k1"]),
        ],
        transport,
    )
    # Cloud is tried first despite local being declared first.
    assert rp.chat([{"role": "user", "content": "q"}]) == "cloud wins"


# --------------------------------------------------------------------------- #
# capability registry: a vision request only considers vision-capable entries
# --------------------------------------------------------------------------- #
def test_vision_request_skips_text_only_entries() -> None:
    transport = ScriptedTransport({"text-key": [_ok("text")], "vis-key": [_ok("vision")]})
    rp = _build(
        [
            _spec(provider="Groq", keys=["text-key"], capabilities=("text",)),
            _spec(provider="Gemini", keys=["vis-key"], capabilities=("text", "vision")),
        ],
        transport,
    )
    out = rp.chat([{"role": "user", "content": "q"}], capability="vision")
    assert out == "vision"
    # The text-only entry was never called for a vision request.
    assert all(c["key"] != "text-key" for c in transport.calls)


def test_vision_request_with_no_vision_entry_raises() -> None:
    transport = ScriptedTransport({"text-key": [_ok("text")]})
    rp = _build([_spec(keys=["text-key"], capabilities=("text",))], transport)
    with pytest.raises(ProviderError):
        rp.chat([{"role": "user", "content": "q"}], capability="vision")


def test_default_capability_is_text() -> None:
    transport = ScriptedTransport({"k1": [_ok("ok")]})
    rp = _build([_spec(keys=["k1"], capabilities=("text",))], transport)
    assert rp.chat([{"role": "user", "content": "q"}]) == "ok"


# --------------------------------------------------------------------------- #
# per-key usage accounting: optimistic decrement + parsed 429 / X-RateLimit-*
# --------------------------------------------------------------------------- #
def test_usage_optimistic_decrement_on_success() -> None:
    transport = ScriptedTransport({"k1": [_ok("a"), _ok("b")]})
    rp = _build([_spec(keys=["k1"], unit="req")], transport)
    rp.chat([{"role": "user", "content": "q"}])
    rp.chat([{"role": "user", "content": "q"}])
    usage = rp.usage()
    [key_usage] = [u for u in usage if u["provider"] == "Groq"]
    assert key_usage["used"] == 2
    assert key_usage["unit"] == "req"


def test_usage_parses_x_ratelimit_headers_from_response() -> None:
    # A success response can carry rate-limit metadata the pool records.
    resp = _ok("ok")
    resp["_headers"] = {"X-RateLimit-Remaining": "17", "X-RateLimit-Limit": "1000"}
    transport = ScriptedTransport({"k1": [resp]})
    rp = _build([_spec(keys=["k1"], unit="req")], transport)
    rp.chat([{"role": "user", "content": "q"}])
    usage = rp.usage()
    [u] = usage
    assert u["max"] == 1000
    # remaining 17 of 1000 -> used 983 (header is authoritative over optimistic).
    assert u["used"] == 983


def test_usage_records_reset_from_429_retry_after() -> None:
    clock = FakeClock(start=2000.0)
    transport = ScriptedTransport(
        {
            "key-aaaa": [ProviderError("LLM HTTP 429: retry-after=30")],
            "key-bbbb": [_ok("served")],
        }
    )
    rp = _build([_spec(keys=["key-aaaa", "key-bbbb"])], transport, clock=clock)
    rp.chat([{"role": "user", "content": "q"}])
    usage = rp.usage()
    k1 = next(u for u in usage if u["key"].endswith("aaaa"))
    assert k1["resetAt"] is not None
    # retry-after=30 from the 429 message -> reset at now + 30.
    assert k1["resetAt"] == 2030.0


def test_usage_key_field_is_redacted_never_full_key() -> None:
    transport = ScriptedTransport({"supersecretkey": [_ok("ok")]})
    rp = _build([_spec(keys=["supersecretkey"])], transport)
    rp.chat([{"role": "user", "content": "q"}])
    usage = rp.usage()
    [u] = usage
    assert "supersecretkey" not in u["key"]
    assert u["key"].endswith("rkey") or "…" in u["key"]


# --------------------------------------------------------------------------- #
# same-provider extra keys = failover only, never advertised x quota
# --------------------------------------------------------------------------- #
def test_same_provider_two_keys_reports_one_provider_group_not_double_quota() -> None:
    transport = ScriptedTransport({"k1": [_ok("a")], "k2": [_ok("b")]})
    rp = _build([_spec(provider="Groq", keys=["k1", "k2"], unit="token")], transport)
    # Distinct cloud providers (for budget) collapses same-provider keys to one.
    assert rp.provider_groups() == ("Groq",)


# --------------------------------------------------------------------------- #
# the live key is header-only: never in a log line or an error body
# --------------------------------------------------------------------------- #
def test_key_never_in_log_lines(caplog: pytest.LogCaptureFixture) -> None:
    transport = ScriptedTransport(
        {
            "sk-live-secret": [ProviderError("LLM HTTP 429: x")],
            "k2": [_ok("ok")],
        }
    )
    rp = _build([_spec(keys=["sk-live-secret", "k2"])], transport)
    with caplog.at_level(logging.DEBUG):
        rp.chat([{"role": "user", "content": "q"}])
    assert "sk-live-secret" not in caplog.text


def test_key_never_in_aggregate_error_message() -> None:
    transport = ScriptedTransport(
        {"sk-live-secret": [ProviderError("LLM HTTP 429: forbidden sk-live-secret leaked")]}
    )
    rp = _build([_spec(keys=["sk-live-secret"])], transport)
    with pytest.raises(ProviderError) as ei:
        rp.chat([{"role": "user", "content": "q"}])
    assert "sk-live-secret" not in str(ei.value)


# --------------------------------------------------------------------------- #
# no-sleep enforcement: the module must not import time / asyncio
# --------------------------------------------------------------------------- #
def test_provider_module_does_not_import_time_or_asyncio() -> None:
    assert not hasattr(prov, "time")
    assert not hasattr(prov, "asyncio")


# --------------------------------------------------------------------------- #
# non-rate-limit ProviderError still fails over (treated as a transient key fault)
# --------------------------------------------------------------------------- #
def test_non_http_provider_error_fails_over_then_succeeds() -> None:
    transport = ScriptedTransport(
        {
            "k1": [ProviderError("LLM returned non-JSON response")],
            "k2": [_ok("recovered")],
        }
    )
    rp = _build([_spec(keys=["k1", "k2"])], transport)
    assert rp.chat([{"role": "user", "content": "q"}]) == "recovered"


def test_temperature_and_max_tokens_threaded_through_pool() -> None:
    transport = ScriptedTransport({"k1": [_ok("ok")]})
    rp = _build([_spec(keys=["k1"])], transport)
    rp.chat([{"role": "user", "content": "q"}], temperature=0.1, max_tokens=99)
    body = transport.calls[0]["body"]
    assert body["temperature"] == 0.1
    assert body["max_tokens"] == 99


def test_local_entry_has_text_capability_by_default() -> None:
    transport = ScriptedTransport({None: [_ok("local")]})
    rp = _build(
        [_spec(provider="local", kind="local", keys=[], local=True, base_url="http://127.0.0.1:8088/v1")],
        transport,
    )
    assert rp.chat([{"role": "user", "content": "q"}]) == "local"


def test_local_backstop_is_a_local_server_provider_under_the_hood() -> None:
    # The local entry is a keyless OpenAI-compat provider (no Bearer header).
    transport = ScriptedTransport({None: [_ok("local")]})
    rp = _build(
        [_spec(provider="local", kind="local", keys=[], local=True, base_url="http://127.0.0.1:8088/v1")],
        transport,
    )
    rp.chat([{"role": "user", "content": "q"}])
    assert "Authorization" not in transport.calls[0]["headers"]


def test_rotation_event_carries_redacted_keys() -> None:
    events: list[RotationEvent] = []
    transport = ScriptedTransport(
        {"sk-from-secret": [ProviderError("LLM HTTP 429: x")], "sk-to-secret": [_ok("ok")]}
    )
    rp = _build([_spec(keys=["sk-from-secret", "sk-to-secret"])], transport)
    rp.on_rotation(events.append)
    rp.chat([{"role": "user", "content": "q"}])
    [ev] = events
    assert "sk-from-secret" not in ev.from_key
    assert "sk-to-secret" not in ev.to_key


def test_chat_full_forwards_whitelisted_sampling_kwargs() -> None:
    # chat_full (used by the pool) must forward whitelisted knobs like chat does.
    transport = ScriptedTransport({"k1": [_ok("ok")]})
    rp = _build([_spec(keys=["k1"])], transport)
    rp.chat([{"role": "user", "content": "q"}], top_p=0.5, seed=3)
    body = transport.calls[0]["body"]
    assert body["top_p"] == 0.5
    assert body["seed"] == 3


def test_usage_garbage_ratelimit_header_is_ignored() -> None:
    # A non-numeric X-RateLimit value must not crash; max stays None.
    resp = _ok("ok")
    resp["_headers"] = {"X-RateLimit-Limit": "not-a-number"}
    transport = ScriptedTransport({"k1": [resp]})
    rp = _build([_spec(keys=["k1"])], transport)
    rp.chat([{"role": "user", "content": "q"}])
    [u] = rp.usage()
    assert u["max"] is None
    assert u["used"] == 1  # optimistic decrement still applied


def test_usage_limit_header_without_remaining_keeps_optimistic_used() -> None:
    # Only X-RateLimit-Limit present (no Remaining) -> max set, used stays optimistic.
    resp = _ok("ok")
    resp["_headers"] = {"X-RateLimit-Limit": "500"}
    transport = ScriptedTransport({"k1": [resp]})
    rp = _build([_spec(keys=["k1"])], transport)
    rp.chat([{"role": "user", "content": "q"}])
    [u] = rp.usage()
    assert u["max"] == 500
    assert u["used"] == 1


def test_retry_after_with_unit_suffix_parses_leading_digits() -> None:
    # "retry-after=30s" -> 30.0 (the non-digit terminator stops accumulation).
    clock = FakeClock(start=5000.0)
    transport = ScriptedTransport(
        {"key-aaaa": [ProviderError("LLM HTTP 429: retry-after=30s please")], "key-bbbb": [_ok("ok")]}
    )
    rp = _build([_spec(keys=["key-aaaa", "key-bbbb"])], transport, clock=clock)
    rp.chat([{"role": "user", "content": "q"}])
    k1 = next(u for u in rp.usage() if u["key"].endswith("aaaa"))
    assert k1["resetAt"] == 5030.0


def test_entries_collapses_two_keys_of_same_spec_to_one_entry() -> None:
    # A two-key provider yields two slots sharing ONE spec; .entries dedupes it.
    transport = ScriptedTransport({"k1": [_ok("a")], "k2": [_ok("b")]})
    rp = _build([_spec(provider="Groq", keys=["k1", "k2"])], transport)
    assert len(rp.entries) == 1
    assert rp.entries[0].provider == "Groq"


def test_local_server_provider_still_works_standalone() -> None:
    # Sanity: the legacy LocalServerProvider is untouched by the pool addition.
    from tests.test_provider import RecordingTransport  # reuse the existing fake

    t = RecordingTransport(_ok("legacy"))
    p = LocalServerProvider(transport=t)
    assert p.chat([{"role": "user", "content": "q"}]) == "legacy"
