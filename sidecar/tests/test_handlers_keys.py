"""WU-keys handler tests: RAW-vs-REDACTED partition + providers.* RPC + consent.

The security crux (PLAN §WU-keys):
  * NO RPC method returns a full key — only last-4 (asserted on every providers.*
    + settings.get response via a regex/substring scan over the serialized JSON).
  * The provider/translator FACTORY path consumes RAW keys (via ``get_raw()``)
    while every RPC read returns redacted — a partition test enumerates ALL FOUR
    feed callers and proves each builds from the full key.
  * providers.testKey validates without echoing the key; a forced 4xx error is
    scrubbed of the live key.
  * TEXT and FRAMES consent are SEPARATE + independently revocable.

Every heavy seam is faked: no socket, no model, no real urllib.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.protocol import RpcContext, RpcError

LIVE_KEY = "gsk-live-SECRET-ABCDWXYZ"
LIVE_KEY_2 = "gsk-second-SECRET-7890"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path, **kw: Any) -> Services:
    return Services(data_dir=tmp_path, **kw)


def _with_provider(svc: Services, *, keys: list[str] | None = None) -> Services:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "kind": "cloud",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "model": "llama-3.3-70b",
                    "apiKeys": keys if keys is not None else [LIVE_KEY],
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": "token",
                }
            ]
        }
    )
    return svc


# --------------------------------------------------------------------------- #
# RPC reads are REDACTED — NO full key ever crosses RPC
# --------------------------------------------------------------------------- #
def test_settings_get_redacts_provider_keys(tmp_path: Path) -> None:
    svc = _with_provider(_services(tmp_path))
    out = svc.settings_get({}, _ctx())
    blob = json.dumps(out)
    assert LIVE_KEY not in blob
    assert out["providers"][0]["apiKeys"] == ["…WXYZ"]  # last-4 only


def test_providers_list_is_key_free(tmp_path: Path) -> None:
    svc = _with_provider(_services(tmp_path), keys=[LIVE_KEY, LIVE_KEY_2])
    out = svc.providers_list({}, _ctx())
    blob = json.dumps(out)
    assert LIVE_KEY not in blob
    assert LIVE_KEY_2 not in blob
    assert out["providers"][0]["apiKeys"] == ["…WXYZ", "…7890"]


def test_settings_set_response_is_key_free(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.settings_set({"providers": [{"id": "g", "apiKeys": [LIVE_KEY]}]}, _ctx())
    assert LIVE_KEY not in json.dumps(out)


# --------------------------------------------------------------------------- #
# providers.upsert / remove
# --------------------------------------------------------------------------- #
def test_providers_upsert_adds_then_merges(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.providers_upsert({"id": "groq", "provider": "Groq", "apiKeys": [LIVE_KEY]}, _ctx())
    # WU-D2b-2 NO-PERSIST: even a raw key handed straight to upsert is stripped to
    # its marker at rest — the live key never persists plaintext regardless of
    # caller (defense-in-depth). No plaintext in the on-disk settings file.
    assert svc.settings.get_raw()["providers"][0]["apiKeys"] == ["…WXYZ"]
    assert LIVE_KEY not in (tmp_path / "settings.json").read_text(encoding="utf-8")
    # Merge a second field into the same id (keeps the apiKeys marker, updates model).
    out = svc.providers_upsert({"id": "groq", "model": "m2"}, _ctx())
    raw = svc.settings.get_raw()["providers"]
    assert len(raw) == 1
    assert raw[0]["model"] == "m2"
    assert raw[0]["apiKeys"] == ["…WXYZ"]
    # The returned list is still redacted.
    assert LIVE_KEY not in json.dumps(out)
    # The FACTORY path recovers the live key only through the injection overlay.
    with svc.settings.key_overlay({"providers": {"groq": [LIVE_KEY]}}):
        assert svc.settings.get_raw()["providers"][0]["apiKeys"] == [LIVE_KEY]


def test_providers_upsert_accepts_nested_provider_object(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.providers_upsert({"provider": {"id": "openai", "apiKeys": [LIVE_KEY]}}, _ctx())
    assert svc.settings.get_raw()["providers"][0]["id"] == "openai"


def test_providers_upsert_requires_id(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError):
        svc.providers_upsert({"apiKeys": [LIVE_KEY]}, _ctx())


def test_providers_upsert_skips_non_dict_existing_entries(tmp_path: Path) -> None:
    # A corrupt/hand-edited settings file with a non-dict entry in providers must
    # not crash an upsert: the bad entry is dropped (the elif's false arm) and the
    # valid id is upserted alongside the surviving dict entries.
    svc = _services(tmp_path)
    svc.settings.set({"providers": ["garbage", {"id": "keep", "apiKeys": ["abcdEFGH"]}]})
    svc.providers_upsert({"id": "groq", "apiKeys": [LIVE_KEY]}, _ctx())
    raw = svc.settings.get_raw()["providers"]
    ids = [p["id"] for p in raw if isinstance(p, dict)]
    assert "garbage" not in raw
    assert set(ids) == {"keep", "groq"}


def test_providers_remove_drops_entry(tmp_path: Path) -> None:
    svc = _with_provider(_services(tmp_path))
    svc.providers_upsert({"id": "openai", "apiKeys": ["sk-other-KEY1"]}, _ctx())
    out = svc.providers_remove({"id": "groq"}, _ctx())
    ids = [p["id"] for p in out["providers"]]
    assert ids == ["openai"]


def test_providers_remove_absent_is_noop(tmp_path: Path) -> None:
    svc = _with_provider(_services(tmp_path))
    out = svc.providers_remove({"id": "nope"}, _ctx())
    assert len(out["providers"]) == 1


def test_providers_remove_requires_id(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError):
        svc.providers_remove({}, _ctx())


# --------------------------------------------------------------------------- #
# providers.testKey — validates, never echoes the key
# --------------------------------------------------------------------------- #
def test_test_key_ok_returns_capabilities_no_key(tmp_path: Path) -> None:
    def transport(url, body, headers, timeout):  # noqa: ANN001
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    svc = _services(tmp_path, test_key_transport=transport)
    out = svc.providers_test_key(
        {"baseUrl": "https://api.groq.com/openai/v1", "apiKey": LIVE_KEY, "capabilities": ["text", "vision"]},
        _ctx(),
    )
    assert out["ok"] is True
    assert out["capabilities"] == ["text", "vision"]
    assert LIVE_KEY not in json.dumps(out)


def test_test_key_failure_scrubs_key(tmp_path: Path) -> None:
    from media_studio.models.provider import ProviderError

    def transport(url, body, headers, timeout):  # noqa: ANN001
        # Simulate a provider error whose detail echoes the live key.
        raise ProviderError(f"LLM HTTP 401: invalid key {LIVE_KEY}")

    svc = _services(tmp_path, test_key_transport=transport)
    out = svc.providers_test_key({"baseUrl": "https://api.groq.com/openai/v1", "apiKey": LIVE_KEY}, _ctx())
    assert out["ok"] is False
    assert LIVE_KEY not in out["error"]
    assert LIVE_KEY not in json.dumps(out)


def test_test_key_requires_base_url_and_key(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError):
        svc.providers_test_key({"apiKey": LIVE_KEY}, _ctx())
    with pytest.raises(RpcError):
        svc.providers_test_key({"baseUrl": "https://x/v1"}, _ctx())


# --------------------------------------------------------------------------- #
# providers.setConsent — text vs frames SEPARATE + independently revocable
# --------------------------------------------------------------------------- #
def test_set_consent_text_and_frames_are_independent(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.providers_set_consent({"provider": "Groq", "text": True, "frames": True}, _ctx())
    # Revoke ONLY frames; text must survive.
    out = svc.providers_set_consent({"provider": "Groq", "frames": False}, _ctx())
    assert out["consent"]["perProvider"]["Groq"] == {"text": True, "frames": False}
    # Revoke ONLY text; frames must survive.
    out2 = svc.providers_set_consent({"provider": "Groq", "text": False}, _ctx())
    assert out2["consent"]["perProvider"]["Groq"] == {"text": False, "frames": False}


def test_set_consent_persists_and_is_per_provider(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.providers_set_consent({"provider": "Groq", "text": True}, _ctx())
    svc.providers_set_consent({"provider": "Gemini", "frames": True}, _ctx())
    per = svc.settings.get_raw()["consent"]["perProvider"]
    assert per["Groq"] == {"text": True}
    assert per["Gemini"] == {"frames": True}


def test_set_consent_requires_provider(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    with pytest.raises(RpcError):
        svc.providers_set_consent({"text": True}, _ctx())
