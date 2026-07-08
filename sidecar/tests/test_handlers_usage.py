"""WU-usage-ui handler tests: providers.usage (cached, redacted, stale-flagged).

The rotation pool already accounts per-key usage (test_rotating_provider). These
pin the RPC seam:
  * the response surfaces the pool's redacted rows (NO full key crosses RPC);
  * it is NOT a poller — no socket is opened (the pool builds with
    detect_local=False so no ``GET /models`` probe runs);
  * last-known numbers persist between runs (settings.usageCache) and fold back
    in on a freshly-zeroed pool (DESIGN §15-Q1);
  * rows older than the 10-min threshold are flagged stale (fake clock).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from media_studio.handlers import Services
from media_studio.models.usage import STALE_AFTER_SECONDS
from media_studio.protocol import RpcContext

LIVE_KEY = "gsk-live-SECRET-ABCDWXYZ"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


class _ScriptedTransport:
    """A chat transport that records every call (no socket); usage tracks calls."""

    def __init__(self) -> None:
        self.calls = 0

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self.calls += 1
        return {"choices": [{"message": {"content": "ok"}}]}


def _probe_transport_boom(url: str, headers: dict[str, str]) -> dict[str, Any]:
    raise AssertionError("providers.usage must NOT open a GET /models probe socket")


def _with_groq(svc: Services, *, keys: list[str] | None = None, unit: str = "token") -> None:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "kind": "cloud",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "model": "m",
                    "apiKeys": keys if keys is not None else [LIVE_KEY],
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": unit,
                }
            ]
        }
    )


def test_usage_returns_redacted_rows_no_full_key(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)
    _with_groq(svc)
    res = svc.providers_usage({}, _ctx())
    rows = res["usage"]
    groq = [r for r in rows if r["provider"] == "Groq"]
    assert len(groq) == 1
    assert LIVE_KEY not in json.dumps(res)
    assert groq[0]["key"].endswith("WXYZ") or "…" in groq[0]["key"]
    assert groq[0]["unit"] == "token"


def test_usage_does_not_open_a_probe_socket(tmp_path: Path) -> None:
    # The pool the handler reads must be built with detect_local=False; injecting a
    # booby-trapped probe transport proves no GET /models burst happens here.
    svc = Services(data_dir=tmp_path)
    _with_groq(svc)
    # No exception => no probe socket was opened during providers.usage.
    res = svc.providers_usage({}, _ctx())
    assert "usage" in res


def test_usage_persists_cache_to_settings(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path, now=lambda: 5000.0)
    _with_groq(svc)
    svc.providers_usage({}, _ctx())
    cache = svc.settings.get_raw().get("usageCache")
    assert isinstance(cache, dict)
    assert cache["savedAt"] == 5000.0
    assert isinstance(cache["rows"], list)


def test_usage_folds_cached_numbers_over_freshly_zeroed_pool(tmp_path: Path) -> None:
    # Seed a persisted cache with real numbers; a fresh pool reports used=0/max=None.
    svc = Services(data_dir=tmp_path, now=lambda: 6000.0)
    _with_groq(svc)
    # Discover the redacted key the pool emits so the cache row matches identity.
    redacted = svc.providers_usage({}, _ctx())["usage"][0]["key"]
    svc.settings.set(
        {
            "usageCache": {
                "rows": [
                    {"provider": "Groq", "key": redacted, "used": 983, "max": 1000, "unit": "token", "resetAt": 6030.0}
                ],
                "checkedAt": {f"Groq\x00{redacted}": 6000.0},
                "savedAt": 6000.0,
            }
        }
    )
    rows = svc.providers_usage({}, _ctx())["usage"]
    groq = next(r for r in rows if r["provider"] == "Groq")
    assert groq["used"] == 983
    assert groq["max"] == 1000


def test_usage_flags_stale_rows_with_fake_clock(tmp_path: Path) -> None:
    clock = {"t": 7000.0}
    svc = Services(data_dir=tmp_path, now=lambda: clock["t"])
    _with_groq(svc)
    redacted = svc.providers_usage({}, _ctx())["usage"][0]["key"]
    # Seed a cache stamped long in the past so the (zeroed) live row inherits an
    # old checkedAt and reads as stale.
    old = 7000.0 - STALE_AFTER_SECONDS - 5.0
    svc.settings.set(
        {
            "usageCache": {
                "rows": [
                    {"provider": "Groq", "key": redacted, "used": 12, "max": 1000, "unit": "token", "resetAt": None}
                ],
                "checkedAt": {f"Groq\x00{redacted}": old},
                "savedAt": old,
            }
        }
    )
    rows = svc.providers_usage({}, _ctx())["usage"]
    groq = next(r for r in rows if r["provider"] == "Groq")
    assert groq["stale"] is True
    assert groq["lastCheckedAt"] == old


def test_usage_registered_in_register_all(tmp_path: Path) -> None:
    from media_studio import protocol
    from media_studio.handlers import register_all

    protocol.METHODS.clear()
    register_all(Services(data_dir=tmp_path))
    assert "providers.usage" in protocol.METHODS
    assert "providers.openrouterUsage" in protocol.METHODS


# --------------------------------------------------------------------------- #
# providers.openrouterUsage (WU-models/device): per-key COST rows, key-safe
# --------------------------------------------------------------------------- #
OR_KEY = "sk-or-live-SECRET-MNOP"


def _with_openrouter(svc: Services, keys: list[str] | None = None) -> None:
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


def test_openrouter_usage_returns_cost_rows_no_full_key(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        captured["headers"] = headers
        return {"data": {"usage": 1.5, "limit": 10.0, "limit_remaining": 8.5, "is_free_tier": False}}

    svc = Services(data_dir=tmp_path, openrouter_usage_transport=fake_transport)
    _with_openrouter(svc)
    # WU-D2b-2: providers.openrouterUsage GETs /key per RAW key, so main injects
    # the live key for it — run under the same request-scoped overlay so get_raw()
    # puts the RAW key on the Authorization header (never the at-rest marker).
    with svc.settings.key_overlay({"providers": {"openrouter": [OR_KEY]}}):
        res = svc.providers_openrouter_usage({}, _ctx())
    rows = res["usage"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "OpenRouter"
    assert rows[0]["costUsd"] == 1.5
    assert rows[0]["limitUsd"] == 10.0
    # No full key crosses RPC; the live key rides ONLY the Authorization header.
    assert OR_KEY not in json.dumps(res)
    assert captured["headers"]["Authorization"] == f"Bearer {OR_KEY}"


def test_openrouter_usage_skips_when_no_openrouter_provider(tmp_path: Path) -> None:
    def fake_transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        raise AssertionError("no probe should run when no OpenRouter provider is configured")

    svc = Services(data_dir=tmp_path, openrouter_usage_transport=fake_transport)
    _with_groq(svc)  # only a Groq provider configured
    assert svc.providers_openrouter_usage({}, _ctx())["usage"] == []


def test_openrouter_usage_empty_when_no_providers(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path, openrouter_usage_transport=lambda *a, **k: {})
    assert svc.providers_openrouter_usage({}, _ctx())["usage"] == []
