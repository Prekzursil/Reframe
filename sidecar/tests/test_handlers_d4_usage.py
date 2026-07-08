"""WU D4 — usage handlers: honest spend estimate flag + usage-availability RPC.

Completes the usage surface without fakes:
  * ``providers.spend`` now carries ``isEstimate`` so the month-to-date figure —
    derived from PLACEHOLDER pricing (no catalog carries a real per-request price)
    — is labelled an ESTIMATE rather than shown as a real invoiced charge.
  * ``providers.usageAvailability`` states, per configured cloud provider, whether
    a provider-side usage API exists — OpenRouter yes, everything else an honest
    "Usage API not available for <provider>" (never a fabricated 0).
  * the LOCAL request/token counters keep incrementing on real ops (the pool's
    per-key ``used`` is always surfaced).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from media_studio import protocol
from media_studio.handlers import Services, register_all
from media_studio.protocol import RpcContext


class SpyProvider:
    def chat(self, messages: Sequence[Any], **_kw: Any) -> str:
        return "ok"


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _svc(tmp_path: Path, **kw: Any) -> Services:
    return Services(data_dir=tmp_path, provider=SpyProvider(), library=None, **kw)


def _with_providers(svc: Services) -> Services:
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "kind": "cloud",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "apiKeys": ["gsk-secret-ABCDWXYZ"],
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": "token",
                },
                {
                    "id": "openrouter",
                    "provider": "OpenRouter",
                    "kind": "cloud",
                    "baseUrl": "https://openrouter.ai/api/v1",
                    "apiKeys": ["sk-or-secret-MNOP"],
                    "enabled": True,
                    "capabilities": ["text"],
                    "unit": "req",
                },
            ]
        }
    )
    return svc


# --------------------------------------------------------------------------- #
# providers.spend — the honest ESTIMATE flag
# --------------------------------------------------------------------------- #
def test_spend_is_flagged_estimate_when_only_placeholder_pricing(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc._spend_ledger().record(123)
    out = svc.providers_spend({}, _ctx())
    assert out["monthToDateCents"] == 123
    # No catalog model has a real per-request price today, so the figure is an
    # estimate — the UI must NOT present it as a real charge.
    assert out["isEstimate"] is True


def test_spend_estimate_flag_flips_when_real_pricing_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from media_studio.models import provider_pricing

    monkeypatch.setitem(provider_pricing.PRICE_CENTS_PER_REQUEST, "priced-model", 5)
    svc = _svc(tmp_path)
    svc._spend_ledger().record(10)
    out = svc.providers_spend({}, _ctx())
    assert out["isEstimate"] is False


def test_spend_still_reports_caps_and_month(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc.settings.set({"monthlySoftLimitCents": 500, "monthlyHardLimitCents": 2000})
    out = svc.providers_spend({}, _ctx())
    assert out["softLimitCents"] == 500
    assert out["hardLimitCents"] == 2000
    assert "month" in out


# --------------------------------------------------------------------------- #
# providers.usageAvailability — honest per-provider provider-side-API notes
# --------------------------------------------------------------------------- #
def test_usage_availability_lists_each_provider_honestly(tmp_path: Path) -> None:
    svc = _with_providers(_svc(tmp_path))
    out = svc.providers_usage_availability({}, _ctx())
    rows = out["availability"]
    by_provider = {r["provider"]: r for r in rows}
    assert by_provider["OpenRouter"]["hasUsageApi"] is True
    assert by_provider["Groq"]["hasUsageApi"] is False
    assert "Usage API not available for Groq" in by_provider["Groq"]["message"]


def test_usage_availability_is_key_free(tmp_path: Path) -> None:
    import json

    svc = _with_providers(_svc(tmp_path))
    out = svc.providers_usage_availability({}, _ctx())
    assert "gsk-secret-ABCDWXYZ" not in json.dumps(out)
    assert "sk-or-secret-MNOP" not in json.dumps(out)


def test_usage_availability_empty_with_no_providers(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    out = svc.providers_usage_availability({}, _ctx())
    assert out == {"availability": []}


def test_usage_availability_tolerates_non_list_providers(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    svc.settings.set({"providers": "corrupt"})
    out = svc.providers_usage_availability({}, _ctx())
    assert out == {"availability": []}


def test_usage_availability_registered(tmp_path: Path) -> None:
    protocol.METHODS.clear()
    register_all(_svc(tmp_path))
    assert "providers.usageAvailability" in protocol.METHODS


# --------------------------------------------------------------------------- #
# LOCAL counters always surface (real, never fabricated)
# --------------------------------------------------------------------------- #
def test_local_usage_counters_always_present(tmp_path: Path) -> None:
    svc = _with_providers(_svc(tmp_path))
    rows = svc.providers_usage({}, _ctx())["usage"]
    # Every configured key has a local row with a real (>=0) used counter and unit.
    groq = [r for r in rows if r["provider"] == "Groq"]
    assert groq and groq[0]["used"] >= 0 and groq[0]["unit"] == "token"
