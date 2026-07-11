"""Network-touching provider handlers honor Offline mode (bug-sweep fix).

``providers.testKey`` and ``providers.openrouterUsage`` issued a live HTTP
request carrying the RAW api key even when Offline mode was on — bypassing the
app's offline switch. They now call ``guard_network`` before touching the
network, so Offline mode refuses the egress (typed OfflineError) and the raw key
never leaves the machine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features.offline import OfflineError
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def test_test_key_refused_when_offline(tmp_path: Path) -> None:
    """providers.testKey refuses (typed) when offline and never touches the network."""
    hits = {"n": 0}

    def spy_transport(url: str, body: Any, headers: Any, timeout: Any) -> dict[str, Any]:
        hits["n"] += 1
        return {"choices": [{"message": {"content": "pong"}}]}

    svc = Services(data_dir=tmp_path / "d")
    svc._test_key_transport = spy_transport  # type: ignore[attr-defined]
    svc.settings.set({"offline": True})
    with pytest.raises(OfflineError):
        svc.providers_test_key({"baseUrl": "http://x", "apiKey": "sk-secret"}, _ctx())
    assert hits["n"] == 0, "testKey egressed to the network despite Offline mode"


def test_openrouter_usage_refused_when_offline(tmp_path: Path) -> None:
    """providers.openrouterUsage refuses (typed) when offline; the raw key stays local."""
    hits = {"n": 0}

    def spy_get(url: str, body: Any, headers: Any, timeout: Any) -> dict[str, Any]:
        hits["n"] += 1
        return {"data": {}}

    svc = Services(data_dir=tmp_path / "d")
    svc._openrouter_usage_transport = spy_get  # type: ignore[attr-defined]
    svc.settings.set(
        {
            "offline": True,
            "providers": [
                {
                    "id": "or",
                    "provider": "OpenRouter",
                    "kind": "cloud",
                    "apiKeys": ["sk-secret"],
                    "baseUrl": "https://openrouter.ai/api/v1",
                    "model": "m",
                    "enabled": True,
                },
            ],
        }
    )
    with pytest.raises(OfflineError):
        svc.providers_openrouter_usage({}, _ctx())
    assert hits["n"] == 0, "openrouterUsage egressed the raw key despite Offline mode"


def test_translator_forces_local_pool_when_offline(tmp_path: Path, monkeypatch) -> None:
    """subtitles.translate's tier3 hosted pool is forced LOCAL-only when offline, so a
    cloud-routed translation can never egress transcript text (bug-sweep fix)."""
    from media_studio.models import provider as _pm
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy_get_translator(settings, *, runner=None, prefer=None, ensure=None):
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy_get_translator)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "offline": True,
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            "providers": [
                {
                    "id": "cloudy",
                    "provider": "cloudy",
                    "kind": "cloud",
                    "apiKeys": ["k"],
                    "enabled": True,
                    "capabilities": ["text"],
                    "baseUrl": "http://c",
                    "model": "m",
                },
            ],
        }
    )
    svc._translator_for_function("translation")
    assert captured["prefer"] == _pm.LOCAL_PROVIDER_ID, "offline translation did not force a local-only pool"
