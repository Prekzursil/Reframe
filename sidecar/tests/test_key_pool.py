"""Tests for the M1a key-pool composition (redacted, key-safe).

The ``models.overview`` compose (M1a) surfaces a ``keyPool`` derived PURELY from
the ALREADY-REDACTED ``providers.list`` view. M4 layers live per-key usage /
cooldown (``GET /api/v1/key``) on top; M1a only expands each provider's redacted
keys into stable per-key rows. The invariant under test: NO full key is ever
fabricated — every ``redactedKey`` is exactly the redacted value handed in — and
malformed provider rows are skipped defensively (a bad settings file never
crashes the read).
"""

from __future__ import annotations

from typing import Any

from media_studio.models import key_pool as kp


def test_empty_providers_yields_empty_pool() -> None:
    assert kp.build_key_pool([]) == []


def test_one_provider_one_key() -> None:
    out = kp.build_key_pool([{"id": "groq", "apiKeys": ["…WXYZ"], "unit": "token"}])
    assert out == [{"id": "groq#0", "providerId": "groq", "redactedKey": "…WXYZ", "unit": "token", "status": "active"}]


def test_multiple_keys_get_stable_indexed_ids() -> None:
    out = kp.build_key_pool([{"id": "openrouter", "apiKeys": ["…AAAA", "…BBBB"]}])
    assert [e["id"] for e in out] == ["openrouter#0", "openrouter#1"]
    assert [e["redactedKey"] for e in out] == ["…AAAA", "…BBBB"]
    # default unit when the provider omits it
    assert all(e["unit"] == kp.DEFAULT_UNIT for e in out)
    assert all(e["status"] == kp.DEFAULT_STATUS for e in out)


def test_provider_id_falls_back_to_display_name() -> None:
    """A provider with no ``id`` uses its display ``provider`` name as the id."""
    out = kp.build_key_pool([{"provider": "Groq", "apiKeys": ["…WXYZ"]}])
    assert out[0]["providerId"] == "Groq"
    assert out[0]["id"] == "Groq#0"


def test_non_dict_provider_skipped() -> None:
    out = kp.build_key_pool(["nope", 7, None, {"id": "ok", "apiKeys": ["…WXYZ"]}])
    assert [e["providerId"] for e in out] == ["ok"]


def test_provider_without_usable_id_skipped() -> None:
    out = kp.build_key_pool([{"apiKeys": ["…WXYZ"]}, {"id": "", "apiKeys": ["…WXYZ"]}, {"id": 9, "apiKeys": ["…X"]}])
    assert out == []


def test_provider_without_keys_skipped() -> None:
    out = kp.build_key_pool([{"id": "groq"}, {"id": "g2", "apiKeys": "notalist"}])
    assert out == []


def test_blank_redacted_key_skipped() -> None:
    """A defensively-empty redacted entry is dropped (no blank row)."""
    out = kp.build_key_pool([{"id": "groq", "apiKeys": ["", "…WXYZ"]}])
    assert [e["redactedKey"] for e in out] == ["…WXYZ"]
    assert out[0]["id"] == "groq#1"  # index reflects the original position


def test_blank_unit_falls_back_to_default() -> None:
    out = kp.build_key_pool([{"id": "groq", "apiKeys": ["…WXYZ"], "unit": ""}])
    assert out[0]["unit"] == kp.DEFAULT_UNIT


def test_non_string_key_is_stringified_then_redacted_passthrough() -> None:
    """A non-string redacted entry is coerced to str (defensive, never crashes)."""
    out = kp.build_key_pool([{"id": "groq", "apiKeys": [{"k": 1}]}])  # type: ignore[list-item]
    assert out[0]["redactedKey"] == str({"k": 1})


def test_no_full_key_is_ever_fabricated() -> None:
    """Every emitted redactedKey is exactly the redacted value supplied in."""
    redacted = ["…AAAA", "…BBBB"]
    out = kp.build_key_pool([{"id": "p", "apiKeys": list(redacted)}])
    assert [e["redactedKey"] for e in out] == redacted


def _is_jsonable(value: Any) -> bool:
    import json

    json.dumps(value)
    return True


def test_result_is_json_serializable() -> None:
    out = kp.build_key_pool([{"id": "groq", "apiKeys": ["…WXYZ"]}])
    assert _is_jsonable(out)
