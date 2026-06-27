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
    # The live key never appears in the row — only the redacted last-4.
    assert row["key"] == "…1234"
    assert "LIVEKEY" not in row["key"]
    # ...but it DOES ride the Authorization header (and only there).
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-or-LIVEKEY1234"
    assert transport.calls[0]["url"] == oru.OPENROUTER_KEY_URL


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
