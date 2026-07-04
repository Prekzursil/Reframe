"""WU D1 (Reframe v1.3) — RECONCILE characterization of the Settings key + usage surface.

This is a CHARACTERIZATION baseline. It LOCKS the CURRENT, observable behaviour of the
provider key / usage RPC handlers (``handlers/providers_ops.py``) plus the settings store
(``settings_store.py``) so the WS-D refactors are *diff-visible*: any change to a fact
pinned here MUST update this file, which surfaces the behaviour change in review.

It documents (it does NOT endorse) the confirmed v1.3 settings gaps — see
``docs/reframe-v1.3-settings-gaps.md``:

  * G-1  keys are PLAINTEXT AT REST — the on-disk ``settings.json`` holds the raw key.
          (D2 replaces this with an Electron ``safeStorage`` DPAPI chain.)
  * G-2  the raw key crosses stdio INBOUND as a plain JSON-RPC param on ``providers.upsert``
          / ``providers.testKey`` — there is no encrypted/transient reveal channel yet.
          (D2/D3 rework the inbound key flow.)
  * G-3  there is NO ``providers.revealKey`` handler — a stored key can never be shown.
          (D3 adds a transient, masked reveal contract.)
  * G-4  there is NO edit-in-place / re-validate-a-STORED-key handler — validation
          (``providers.testKey``) ALWAYS requires the caller to re-supply the plaintext
          key inline; you cannot re-validate what is already stored by id alone.
          (D3 adds "Replace" + per-key "Re-validate".)

Every assertion here passes on the CURRENT tree (v1.2.0 + Wave-1). This WU changes NO
production behaviour — it is tests + the gap doc only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.handlers import Services, register_all
from media_studio.protocol import RpcContext, RpcError

# A fake "live" key with a distinctive last-4 so redaction is observable ("…WXYZ").
LIVE_KEY = "gsk-live-SECRET-ABCDWXYZ"
# A distinct OpenRouter key for the cost-usage surface.
OR_KEY = "sk-or-live-SECRET-MNOP"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path, **kw: Any) -> Services:
    return Services(data_dir=tmp_path, **kw)


def _with_groq(svc: Services, *, keys: list[str] | None = None) -> Services:
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


def _with_openrouter(svc: Services, *, keys: list[str] | None = None) -> Services:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "openrouter",
                    "provider": "OpenRouter",
                    "kind": "cloud",
                    "baseUrl": "https://openrouter.ai/api/v1",
                    "model": "deepseek/deepseek-chat:free",
                    "apiKeys": keys if keys is not None else [OR_KEY],
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": "req",
                }
            ]
        }
    )
    return svc


# --------------------------------------------------------------------------- #
# The RPC surface snapshot — documents which providers.* methods EXIST today,
# so adding providers.revealKey (D3) makes the surface change diff-visible.
# --------------------------------------------------------------------------- #
def test_provider_key_and_usage_rpc_surface_snapshot(tmp_path: Path) -> None:
    protocol.METHODS.clear()
    register_all(Services(data_dir=tmp_path))
    surface = sorted(m for m in protocol.METHODS if m.startswith("providers."))
    # The provider RPC surface as of v1.2.0 + Wave-1, PLUS the D3 addition
    # ``providers.revealKey`` (the transient masked-reveal contract that closes G-3)
    # and the D4 addition ``providers.usageAvailability`` (honest per-provider
    # provider-side-usage-API notes — never a fabricated number).
    assert surface == [
        "providers.applyPreset",
        "providers.catalog",
        "providers.firstRun",
        "providers.list",
        "providers.openrouterUsage",
        "providers.remove",
        "providers.revealKey",
        "providers.setConsent",
        "providers.setFunctionModel",
        "providers.spend",
        "providers.testKey",
        "providers.upsert",
        "providers.usage",
        "providers.usageAvailability",
    ]
    # G-3 CLOSED (D3): the transient reveal handler now exists. Re-validate of a
    # stored key (G-4) is orchestrated in the renderer (revealKey -> testKey), so
    # there is deliberately NO separate ``providers.revalidateKey`` sidecar method.
    assert "providers.revealKey" in protocol.METHODS
    assert "providers.revalidateKey" not in protocol.METHODS


# --------------------------------------------------------------------------- #
# The full add -> validate -> list -> remove key flow, as it behaves TODAY.
# WS-D D2/D3 must preserve this externally-observable contract while reworking
# the storage/reveal internals.
# --------------------------------------------------------------------------- #
def test_add_validate_remove_key_flow_is_locked(tmp_path: Path) -> None:
    def transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    svc = _services(tmp_path, test_key_transport=transport)

    # ADD: providers.upsert stores the RAW key; the RESPONSE is redacted to last-4.
    added = svc.providers_upsert(
        {"id": "groq", "provider": "Groq", "baseUrl": "https://api.groq.com/openai/v1", "apiKeys": [LIVE_KEY]},
        _ctx(),
    )
    assert LIVE_KEY not in json.dumps(added)
    assert added["providers"][0]["apiKeys"] == ["…WXYZ"]

    # VALIDATE: providers.testKey issues one ping and returns ok + capabilities,
    # NEVER echoing the key. It takes the plaintext key INLINE (G-2/G-4).
    validated = svc.providers_test_key(
        {"baseUrl": "https://api.groq.com/openai/v1", "apiKey": LIVE_KEY, "capabilities": ["text"]},
        _ctx(),
    )
    assert validated == {"ok": True, "capabilities": ["text"]}
    assert LIVE_KEY not in json.dumps(validated)

    # LIST: the RPC read is redacted, but the FACTORY get_raw() still carries the live key.
    listed = svc.providers_list({}, _ctx())
    assert LIVE_KEY not in json.dumps(listed)
    assert svc.settings.get_raw()["providers"][0]["apiKeys"] == [LIVE_KEY]

    # REMOVE: providers.remove drops the whole provider entry.
    removed = svc.providers_remove({"id": "groq"}, _ctx())
    assert removed["providers"] == []


# --------------------------------------------------------------------------- #
# G-1: keys are PLAINTEXT AT REST — the on-disk settings.json holds the raw key.
# This is the security gap D2 (safeStorage/DPAPI) will close; locking it here
# makes the at-rest change unmissable in review.
# --------------------------------------------------------------------------- #
def test_stored_provider_key_is_plaintext_at_rest_on_disk(tmp_path: Path) -> None:
    svc = _with_groq(_services(tmp_path))
    on_disk = Path(svc.settings.config_path).read_text(encoding="utf-8")
    # GAP G-1: the raw key sits unencrypted in the JSON document at rest.
    assert LIVE_KEY in on_disk
    parsed = json.loads(on_disk)
    assert parsed["providers"][0]["apiKeys"] == [LIVE_KEY]


# --------------------------------------------------------------------------- #
# G-4: there is NO way to re-validate an ALREADY-STORED key by id — testKey
# ALWAYS demands the plaintext key + baseUrl inline (edit/reveal gaps).
# --------------------------------------------------------------------------- #
def test_no_revalidate_of_stored_key_by_id(tmp_path: Path) -> None:
    svc = _with_groq(_services(tmp_path))
    # A provider is stored, yet testKey cannot re-validate it from its id alone:
    # it hard-requires an inline apiKey (and baseUrl). No stored-key reveal path.
    with pytest.raises(RpcError):
        svc.providers_test_key({"id": "groq"}, _ctx())
    with pytest.raises(RpcError):
        svc.providers_test_key({"baseUrl": "https://api.groq.com/openai/v1"}, _ctx())


# --------------------------------------------------------------------------- #
# Usage surfaces (providers.usage + providers.openrouterUsage) are redacted and
# key-free today. D4 extends usage numbers; it must keep these surfaces key-free.
# --------------------------------------------------------------------------- #
def test_usage_surface_is_redacted_and_key_free(tmp_path: Path) -> None:
    svc = _with_groq(_services(tmp_path))
    out = svc.providers_usage({}, _ctx())
    rows = out["usage"]
    groq = [r for r in rows if r["provider"] == "Groq"]
    assert len(groq) == 1
    assert LIVE_KEY not in json.dumps(out)
    assert "…" in groq[0]["key"] or groq[0]["key"].endswith("WXYZ")
    assert groq[0]["unit"] == "token"


def test_openrouter_usage_surface_is_redacted_and_key_free(tmp_path: Path) -> None:
    def or_transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        # The live key rides ONLY the Authorization header — never the returned rows.
        assert headers["Authorization"] == f"Bearer {OR_KEY}"
        return {"data": {"usage": 2.0, "limit": 10.0, "limit_remaining": 8.0, "is_free_tier": False}}

    svc = _services(tmp_path, openrouter_usage_transport=or_transport)
    _with_openrouter(svc)
    out = svc.providers_openrouter_usage({}, _ctx())
    rows = out["usage"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "OpenRouter"
    assert rows[0]["costUsd"] == 2.0
    assert rows[0]["limitUsd"] == 10.0
    assert OR_KEY not in json.dumps(out)
