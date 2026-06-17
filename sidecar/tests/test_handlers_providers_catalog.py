"""Tests for the ``providers.catalog`` RPC handler (WU-catalog).

``providers.catalog`` returns the static curated model catalog as JSON: every
provider/model with its per-task tiers, privacy / train-on-input flags, unit, the
editorial top-pick per task, and the dated ``asOfDate`` stamp. The tests pin: the
method is registered through ``register_all`` (the single composition root); the
payload spans >=3 providers + 5 task tiers; the Gemini AVOID / Groq SAFE flags;
``asOfDate`` present; and NO secret (key / url) ever appears in the payload.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from media_studio import handlers, protocol
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


@pytest.fixture
def svc(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", library=None)


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def test_providers_catalog_registered() -> None:
    protocol.clear_methods()
    handlers.register_all()
    assert "providers.catalog" in protocol.METHODS
    protocol.clear_methods()


def test_providers_catalog_spans_three_providers_and_five_tiers(svc: Services, ctx: RpcContext) -> None:
    out = svc.providers_catalog({}, ctx)
    assert set(out) == {"asOfDate", "unit", "tasks", "topPicks", "providers"}
    providers = out["providers"]
    # >=3 distinct providers.
    distinct = {p["provider"] for p in providers}
    assert len(distinct) >= 3
    # 5 task tiers on every entry.
    assert len(out["tasks"]) == 5
    for entry in providers:
        assert len(entry["perTaskTier"]) == 5


def test_providers_catalog_gemini_avoid_groq_safe(svc: Services, ctx: RpcContext) -> None:
    out = svc.providers_catalog({}, ctx)
    by_id = {p["id"]: p for p in out["providers"]}
    assert by_id["gemini-2.5-flash"]["privacyTier"] == "AVOID"
    assert by_id["gemini-2.5-flash"]["trainsOnInput"] is True
    assert by_id["groq-gpt-oss-120b"]["privacyTier"] == "SAFE"
    assert by_id["groq-gpt-oss-120b"]["trainsOnInput"] is False


def test_providers_catalog_has_as_of_date(svc: Services, ctx: RpcContext) -> None:
    out = svc.providers_catalog({}, ctx)
    assert out["asOfDate"]
    assert all(p["asOfDate"] for p in out["providers"])


def test_providers_catalog_has_no_secrets(svc: Services, ctx: RpcContext) -> None:
    out = svc.providers_catalog({}, ctx)
    blob = json.dumps(out)
    for forbidden in ("apiKey", "apiKeys", "Bearer", "baseUrl", "secret"):
        assert forbidden not in blob
