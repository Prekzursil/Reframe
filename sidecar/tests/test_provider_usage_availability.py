"""WU D4 — honest per-provider usage-API availability (no fabricated numbers).

Only OpenRouter exposes a per-KEY usage/cost endpoint reachable with a normal
stored key (``GET /api/v1/key``). OpenAI and Anthropic gate their usage/cost
reports behind an ORGANIZATION ADMIN key (``sk-admin`` / ``sk-ant-admin``), which
a stored project key cannot use; other cloud providers publish nothing per-key.
:func:`provider_usage_availability.usage_availability` states this HONESTLY — one
row per configured cloud provider saying whether a provider-side usage API exists,
so the UI can show "Usage API not available for <provider>" instead of a fake 0.
"""

from __future__ import annotations

from media_studio.models.provider_usage_availability import usage_availability


def _entry(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "x", "provider": "X", "kind": "cloud", "apiKeys": ["k"]}
    base.update(kw)
    return base


def test_openrouter_reports_available() -> None:
    rows = usage_availability([_entry(id="openrouter", provider="OpenRouter", baseUrl="https://openrouter.ai/api/v1")])
    assert len(rows) == 1
    assert rows[0]["provider"] == "OpenRouter"
    assert rows[0]["hasUsageApi"] is True


def test_openai_reports_unavailable_with_admin_key_reason() -> None:
    rows = usage_availability([_entry(id="openai", provider="OpenAI", baseUrl="https://api.openai.com/v1")])
    assert rows[0]["hasUsageApi"] is False
    msg = rows[0]["message"]
    assert "Usage API not available for OpenAI" in msg
    assert "admin key" in msg


def test_anthropic_reports_unavailable_with_admin_key_reason() -> None:
    rows = usage_availability([_entry(id="anthropic", provider="Anthropic", baseUrl="https://api.anthropic.com/v1")])
    assert rows[0]["hasUsageApi"] is False
    assert "Usage API not available for Anthropic" in rows[0]["message"]
    assert "admin key" in rows[0]["message"]


def test_generic_cloud_provider_reports_unavailable() -> None:
    rows = usage_availability([_entry(id="groq", provider="Groq", baseUrl="https://api.groq.com/openai/v1")])
    assert rows[0]["hasUsageApi"] is False
    assert rows[0]["message"] == "Usage API not available for Groq."


def test_provider_name_falls_back_to_id() -> None:
    rows = usage_availability([{"id": "groq", "kind": "cloud", "apiKeys": ["k"]}])
    assert rows[0]["provider"] == "groq"
    assert rows[0]["message"] == "Usage API not available for groq."


def test_multiple_keys_collapse_to_one_row_per_provider() -> None:
    rows = usage_availability([_entry(id="groq", provider="Groq", apiKeys=["k1", "k2"])])
    assert len(rows) == 1


def test_multiple_providers_each_get_a_row_in_order() -> None:
    rows = usage_availability(
        [
            _entry(id="groq", provider="Groq"),
            _entry(id="openrouter", provider="OpenRouter", baseUrl="https://openrouter.ai/api/v1"),
        ]
    )
    assert [r["provider"] for r in rows] == ["Groq", "OpenRouter"]


def test_local_backstop_entry_is_skipped() -> None:
    rows = usage_availability([{"id": "local", "provider": "local", "kind": "local"}])
    assert rows == []


def test_entry_without_identity_is_skipped() -> None:
    rows = usage_availability([{"kind": "cloud", "apiKeys": ["k"]}, "not-a-dict"])  # type: ignore[list-item]
    assert rows == []


def test_keyless_cloud_entry_is_still_listed() -> None:
    # A provider added from the picker before pasting a key still deserves an honest
    # "no provider-side usage API" note (it is configured, just not yet keyed).
    rows = usage_availability([{"id": "groq", "provider": "Groq", "kind": "cloud"}])
    assert len(rows) == 1
    assert rows[0]["hasUsageApi"] is False


def test_empty_providers_returns_empty() -> None:
    assert usage_availability([]) == []
