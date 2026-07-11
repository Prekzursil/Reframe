"""Text-function LLM pools enforce per-provider TEXT consent (bug-sweep fix).

Confirmed HIGH from the discovery sweep: ``_provider_for_function`` (used by the
star Make-Shorts ``select`` path plus other text functions) built its cloud
rotation pool from RAW settings with NO text-consent filter — so transcript text
could egress to a cloud provider the user never granted TEXT consent to, unlike
the index-embedder (``_text_consented_settings``) and vision-frame
(``_frame_consented_vision_settings``) gates which DO filter per entry.

The fix mirrors those gates: a cloud entry without ``consent.perProvider[p].text``
is DROPPED before the pool is built, so it can never receive transcript text
(``select`` degrades to the local LLM backstop rather than egressing).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.handlers import Services
from media_studio.models import provider as _pm
from media_studio.models import routing_policy as _rp


def _cloud_entry(pid: str) -> dict[str, Any]:
    return {
        "id": pid,
        "provider": pid,
        "kind": "cloud",
        "apiKeys": ["k"],
        "enabled": True,
        "capabilities": ["text"],
        "baseUrl": f"http://{pid}",
        "model": "m",
    }


def test_provider_for_function_drops_non_text_consented_cloud(tmp_path: Path, monkeypatch) -> None:
    """A cloud provider WITHOUT text consent is dropped from the pool; a consented
    one is kept — so select's transcript can only reach a consented target."""
    svc = Services(data_dir=tmp_path / "data")
    monkeypatch.setattr(_rp, "resolve_route", lambda function, settings: {"mode": "cloud"})
    captured: dict[str, list[str]] = {}

    def spy_get_provider(settings, *, prefer=None, ensure=None):
        captured["providers"] = [str(p.get("provider")) for p in settings.get("providers", [])]
        return object()

    monkeypatch.setattr(_pm, "get_provider", spy_get_provider)
    svc.settings.set(
        {
            "providers": [_cloud_entry("yes"), _cloud_entry("no")],
            "consent": {"perProvider": {"yes": {"text": True}, "no": {"text": False}}},
        }
    )
    svc._provider_for_function("select")
    assert captured["providers"] == ["yes"], "non-text-consented cloud entry was NOT dropped from the pool"


def test_provider_for_function_keeps_text_consented_cloud(tmp_path: Path, monkeypatch) -> None:
    """The gate must NOT block a user who DID grant text consent (control)."""
    svc = Services(data_dir=tmp_path / "data")
    monkeypatch.setattr(_rp, "resolve_route", lambda function, settings: {"mode": "cloud"})
    captured: dict[str, list[str]] = {}

    def spy_get_provider(settings, *, prefer=None, ensure=None):
        captured["providers"] = [str(p.get("provider")) for p in settings.get("providers", [])]
        return object()

    monkeypatch.setattr(_pm, "get_provider", spy_get_provider)
    svc.settings.set(
        {
            "providers": [_cloud_entry("yes")],
            "consent": {"perProvider": {"yes": {"text": True}}},
        }
    )
    svc._provider_for_function("select")
    assert captured["providers"] == ["yes"]
