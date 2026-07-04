"""WU D3 (Reframe v1.3) — the transient ``providers.revealKey`` reveal contract.

``providers.revealKey({id, index?})`` is the ONE sanctioned exception to the
redact-over-RPC invariant: it returns exactly ONE raw plaintext key, for a
transient masked-by-default display driven by an explicit user click. Every OTHER
``providers.*`` read stays last-4 redacted. These tests pin:

  * the method is registered through ``register_all`` (the single composition root);
  * it returns the RAW stored key at the requested index (default 0) — and ONLY
    that one key (a sibling key at another index never leaks into the response);
  * a round-trip against ``get_raw`` (the FACTORY accessor) matches byte-for-byte;
  * every error arm is a typed INVALID_PARAMS (never a crash, never a silent empty
    reveal): unknown id, out-of-range / negative / non-int / bool index, missing
    id, and an empty stored key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from media_studio import protocol
from media_studio.handlers import Services, register_all
from media_studio.protocol import RpcContext, RpcError

# Distinctive plaintext keys so a leak is unmistakable in the assertions.
KEY_A = "gsk-live-SECRET-AAAA"
KEY_B = "gsk-live-SECRET-BBBB"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path)


def _seed(svc: Services, keys: list[str]) -> Services:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "kind": "cloud",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "model": "llama-3.3-70b",
                    "apiKeys": list(keys),
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": "token",
                }
            ]
        }
    )
    return svc


def test_reveal_key_registered_through_composition_root(tmp_path: Path) -> None:
    protocol.METHODS.clear()
    register_all(Services(data_dir=tmp_path))
    assert "providers.revealKey" in protocol.METHODS
    protocol.METHODS.clear()


def test_reveal_returns_the_raw_key_at_default_index(tmp_path: Path) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A])
    out = svc.providers_reveal_key({"id": "groq"}, _ctx())
    assert out == {"key": KEY_A}
    # Byte-for-byte round-trip against the FACTORY accessor.
    assert out["key"] == svc.settings.get_raw()["providers"][0]["apiKeys"][0]


def test_reveal_selects_the_requested_index_and_leaks_no_sibling(tmp_path: Path) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A, KEY_B])
    out = svc.providers_reveal_key({"id": "groq", "index": 1}, _ctx())
    assert out == {"key": KEY_B}
    # ONLY the requested key is present — the sibling never rides along.
    assert KEY_A not in json.dumps(out)


def test_reveal_unknown_provider_is_invalid_params(tmp_path: Path) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A])
    with pytest.raises(RpcError):
        svc.providers_reveal_key({"id": "nope"}, _ctx())


def test_reveal_index_out_of_range_is_invalid_params(tmp_path: Path) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A])
    with pytest.raises(RpcError):
        svc.providers_reveal_key({"id": "groq", "index": 5}, _ctx())


def test_reveal_missing_id_is_invalid_params(tmp_path: Path) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A])
    with pytest.raises(RpcError):
        svc.providers_reveal_key({}, _ctx())


@pytest.mark.parametrize("bad", [-1, True, "0", 1.0, None])
def test_reveal_non_natural_index_is_invalid_params(tmp_path: Path, bad: object) -> None:
    svc = _seed(_svc(tmp_path), [KEY_A])
    with pytest.raises(RpcError):
        svc.providers_reveal_key({"id": "groq", "index": bad}, _ctx())


def test_reveal_empty_stored_key_is_invalid_params(tmp_path: Path) -> None:
    # A provider row whose slot holds an empty string has nothing to reveal.
    svc = _seed(_svc(tmp_path), [""])
    with pytest.raises(RpcError):
        svc.providers_reveal_key({"id": "groq", "index": 0}, _ctx())


def test_reveal_no_providers_configured_is_invalid_params(tmp_path: Path) -> None:
    # No providers list at all → unknown provider, not a crash.
    svc = _svc(tmp_path)
    with pytest.raises(RpcError):
        svc.providers_reveal_key({"id": "groq"}, _ctx())
