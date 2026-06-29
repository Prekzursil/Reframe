"""Unit tests for media_studio.models.openrouter_usage (per-key COST rows).

Probes OpenRouter ``GET /api/v1/key`` through the SAME injectable Transport seam
the pool uses, so no socket is opened. Asserts: cost/limit parsing, OpenRouter
detection, best-effort skip on a dead key, keyless/non-OpenRouter skip, and that a
live key never leaves the row (redacted last-4 only) but DOES ride the Bearer
header.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import openrouter_usage as oru
from media_studio.models.provider import ProviderError


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class RecordingTransport:
    """A fake transport returning a canned response and recording the calls."""

    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return self.response


def _key_response(usage: float, limit: float | None, remaining: float | None, free: bool = False) -> dict[str, Any]:
    return {"data": {"usage": usage, "limit": limit, "limit_remaining": remaining, "is_free_tier": free}}


# --------------------------------------------------------------------------- #
# parse_key_usage
# --------------------------------------------------------------------------- #
def test_parse_key_usage_full() -> None:
    parsed = oru.parse_key_usage(_key_response(1.25, 10.0, 8.75, free=True))
    assert parsed == {"costUsd": 1.25, "limitUsd": 10.0, "remainingUsd": 8.75, "isFreeTier": True}


def test_parse_key_usage_missing_data_all_none() -> None:
    assert oru.parse_key_usage({}) == {
        "costUsd": None,
        "limitUsd": None,
        "remainingUsd": None,
        "isFreeTier": False,
    }


def test_parse_key_usage_data_not_a_dict() -> None:
    assert oru.parse_key_usage({"data": "nope"})["costUsd"] is None


def test_parse_key_usage_null_limit_and_garbage_usage() -> None:
    parsed = oru.parse_key_usage({"data": {"usage": "x", "limit": None, "is_free_tier": True}})
    assert parsed == {"costUsd": None, "limitUsd": None, "remainingUsd": None, "isFreeTier": True}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1.0), (1.5, 1.5), (None, None), ("1", None), (True, None)],
)
def test_as_float(value: Any, expected: float | None) -> None:
    assert oru._as_float(value) == expected


# --------------------------------------------------------------------------- #
# is_openrouter
# --------------------------------------------------------------------------- #
def test_is_openrouter_by_base_url() -> None:
    assert oru.is_openrouter({"baseUrl": "https://openrouter.ai/api/v1"}) is True


def test_is_openrouter_by_id() -> None:
    assert oru.is_openrouter({"id": "openrouter", "baseUrl": "https://x/v1"}) is True


def test_is_openrouter_by_provider_name() -> None:
    assert oru.is_openrouter({"provider": "OpenRouter"}) is True


def test_is_openrouter_false_for_other_provider() -> None:
    assert oru.is_openrouter({"provider": "Groq", "baseUrl": "https://api.groq.com/v1"}) is False


# --------------------------------------------------------------------------- #
# fetch_usage — the per-key probe
# --------------------------------------------------------------------------- #
def test_fetch_usage_returns_cost_row_with_redacted_key() -> None:
    transport = RecordingTransport(_key_response(2.0, 10.0, 8.0))
    rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": ["sk-or-LIVEKEY1234"]}], transport=transport)
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "OpenRouter"
    assert row["costUsd"] == 2.0
    assert row["limitUsd"] == 10.0
    # A healthy paid key is ACTIVE with no cooldown reason (M4).
    assert row["status"] == "active"
    assert row["cooldownReason"] is None
    # The live key never appears in the row — only the redacted last-4.
    assert row["key"] == "…1234"
    assert "LIVEKEY" not in row["key"]
    # ...but it DOES ride the Authorization header (and only there).
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-or-LIVEKEY1234"
    assert transport.calls[0]["url"] == oru.OPENROUTER_KEY_URL


def test_fetch_usage_free_tier_under_floor_is_cooldown() -> None:
    # A free key under the 10-credit floor is parked (cooldown), NOT deleted.
    transport = RecordingTransport(_key_response(0.0, 10.0, 3.0, free=True))
    rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": ["sk-or-freekey99"]}], transport=transport)
    assert len(rows) == 1  # the row stays — cooldown-not-delete
    assert rows[0]["status"] == "cooldown"
    assert "50 :free" in rows[0]["cooldownReason"]
    assert rows[0]["isFreeTier"] is True


@pytest.mark.parametrize(("code", "marker"), [(402, "402"), (429, "429")])
def test_fetch_usage_402_429_parks_key_not_deleted(code: int, marker: str) -> None:
    # A 402/429 probe error parks the key on cooldown (a row is still returned).
    transport = RecordingTransport(error=ProviderError(f"LLM HTTP {code}: nope", status_code=code))
    rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": ["sk-or-LIVE9876"]}], transport=transport)
    assert len(rows) == 1  # cooldown-not-delete
    row = rows[0]
    assert row["status"] == "cooldown"
    assert marker in row["cooldownReason"]
    # The parked row carries the redacted key only; cost is unknown.
    assert row["key"] == "…9876"
    assert row["costUsd"] is None


def test_fetch_usage_scrubs_probe_error_body_of_live_key(caplog: pytest.LogCaptureFixture) -> None:
    # The probe error body (logged on failure) must NOT contain the live key (M4).
    live = "sk-or-SECRETKEYABCD"
    transport = RecordingTransport(error=ProviderError(f"LLM HTTP 402: balance for {live} is 0", status_code=402))
    with caplog.at_level("DEBUG", logger="media_studio.models.openrouter_usage"):
        rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": [live]}], transport=transport)
    assert rows[0]["status"] == "cooldown"
    assert live not in caplog.text  # the body was scrubbed before logging
    assert "SECRETKEY" not in caplog.text


def test_fetch_usage_bad_key_401_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    # A non-cooldown HTTP error (bad key) is best-effort dropped AND scrubbed.
    live = "sk-or-DEADKEYZZZZ"
    transport = RecordingTransport(error=ProviderError(f"LLM HTTP 401: {live} unauthorized", status_code=401))
    with caplog.at_level("DEBUG", logger="media_studio.models.openrouter_usage"):
        rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": [live]}], transport=transport)
    assert rows == []  # dropped (not a recoverable cooldown)
    assert live not in caplog.text  # still scrubbed


def test_fetch_usage_non_provider_error_is_dropped_and_scrubbed(caplog: pytest.LogCaptureFixture) -> None:
    # A non-ProviderError transport failure is swallowed best-effort and scrubbed.
    live = "sk-or-OOPSKEY7777"
    transport = RecordingTransport(error=ValueError(f"boom {live}"))
    with caplog.at_level("DEBUG", logger="media_studio.models.openrouter_usage"):
        rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": [live]}], transport=transport)
    assert rows == []
    assert live not in caplog.text


def test_fetch_usage_skips_non_openrouter_provider() -> None:
    transport = RecordingTransport(_key_response(2.0, 10.0, 8.0))
    rows = oru.fetch_usage([{"provider": "Groq", "apiKeys": ["gsk_x"]}], transport=transport)
    assert rows == []
    assert transport.calls == []  # no probe issued for a non-OpenRouter provider


def test_fetch_usage_skips_keyless_and_blank_keys() -> None:
    transport = RecordingTransport(_key_response(2.0, 10.0, 8.0))
    rows = oru.fetch_usage(
        [
            {"provider": "OpenRouter", "apiKeys": []},
            {"provider": "OpenRouter", "apiKeys": [""]},
        ],
        transport=transport,
    )
    assert rows == []


def test_fetch_usage_skips_dead_key_best_effort() -> None:
    transport = RecordingTransport(error=ProviderError("LLM HTTP 401: unauthorized"))
    rows = oru.fetch_usage([{"provider": "OpenRouter", "apiKeys": ["sk-or-dead"]}], transport=transport)
    assert rows == []  # a dead key is skipped, never raised


def test_fetch_usage_skips_non_dict_entry() -> None:
    transport = RecordingTransport(_key_response(2.0, 10.0, 8.0))
    assert oru.fetch_usage(["not-a-dict"], transport=transport) == []  # type: ignore[list-item]


def test_fetch_usage_multiple_keys_same_provider() -> None:
    transport = RecordingTransport(_key_response(3.0, None, None))
    rows = oru.fetch_usage(
        [{"provider": "OpenRouter", "apiKeys": ["sk-or-aaaa", "sk-or-bbbb"]}],
        transport=transport,
    )
    assert [r["key"] for r in rows] == ["…aaaa", "…bbbb"]
    assert all(r["limitUsd"] is None for r in rows)


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
