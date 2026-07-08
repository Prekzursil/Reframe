"""WU-8 — ``readiness.summary`` RPC (read-only readiness roll-up) tests.

The handler rolls the three readiness sources (model tiers / providers / consent)
into ``{items:[{capability, status, blockedBy, action}]}``. It is READ-ONLY: it
triggers NO download (no ``assets.ensure``) and opens NO socket (no provider call
ever). These tests pin the §WU-8 falsifiable acceptance criteria, driving every
status with FAKE seams so no real ffmpeg/model/provider/network is touched.

Model-tier readiness is derived purely from the installed-weight map (the
``_models_present_map`` seam, overridden here with a pure fake) + Offline mode —
no hardware probe / dependency-import is consulted, so the statuses are
deterministic on any machine.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from media_studio import handlers
from media_studio.handlers import Services, _missing_tier_assets, _provider_has_key
from media_studio.protocol import RpcContext


def _register_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every mapped tier asset as manifest-KNOWN (deterministic readiness).

    B1 filters the ``assets.ensure`` target list to manifest-registered assets.
    Tests asserting a tier goes ``needsDownload`` pin its assets as registered
    here so they do not depend on which feature modules register assets on the
    real tree (the readiness tiers reference re-host assets not yet registered).
    """
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(_manifest, "get_asset", lambda _n: SimpleNamespace(label="", size_mb=0))


_ALL_MODELS = (
    "saliency",
    "audio_saliency",
    "scene_transnet",
    "vlm_backbone",
    "quality_gate",
    "smolvlm2",
)


def _services(
    tmp_path: Path,
    *,
    settings: dict[str, Any] | None = None,
    models_present: dict[str, bool] | None = None,
) -> Services:
    svc = Services(data_dir=tmp_path / "data")
    if settings:
        svc.settings.set(settings)
    # Override the (AssetManager-backed) installed-state probe with a pure fake so
    # the test NEVER touches the real manifest/filesystem install probe.
    present = models_present if models_present is not None else {}
    svc._models_present_map = lambda _s: dict(present)  # type: ignore[method-assign]
    return svc


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _by_cap(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["capability"]: item for item in result["items"]}


# --------------------------------------------------------------------------- #
# model-tier capabilities
# --------------------------------------------------------------------------- #
def test_tier_all_models_present_online_is_ready(tmp_path: Path, ctx: RpcContext) -> None:
    # Every model weight installed + online -> the multimodal tier is ready.
    svc = _services(tmp_path, models_present=dict.fromkeys(_ALL_MODELS, True))
    items = _by_cap(svc.readiness_summary({}, ctx))
    tier1 = items["tier1-multimodal"]
    assert tier1["status"] == "ready"
    assert tier1["blockedBy"] == ""
    assert tier1["action"] is None


def test_tier_missing_weight_online_needs_download(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missing (but REGISTERED) weight + online -> needsDownload with an
    # assets.ensure action targeting the registered asset names.
    _register_all(monkeypatch)
    svc = _services(tmp_path, models_present={})
    items = _by_cap(svc.readiness_summary({}, ctx))
    tier1 = items["tier1-multimodal"]
    assert tier1["status"] == "needsDownload"
    assert tier1["blockedBy"]
    assert tier1["action"]["kind"] == "assets.ensure"
    # The action names the missing assets so the panel can target assets.ensure.
    assert tier1["action"]["assets"]


def test_tier_missing_weight_offline_is_unavailable(tmp_path: Path, ctx: RpcContext) -> None:
    # Offline + a missing weight -> unavailable (download blocked); no action.
    svc = _services(tmp_path, settings={"offline": True}, models_present={})
    items = _by_cap(svc.readiness_summary({}, ctx))
    tier1 = items["tier1-multimodal"]
    assert tier1["status"] == "unavailable"
    assert tier1["action"] is None


def test_tier0_numeric_is_always_ready(tmp_path: Path, ctx: RpcContext) -> None:
    # Tier-0 is the zero-download CPU floor: ready even with no weights installed.
    svc = _services(tmp_path, models_present={})
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["tier0-numeric"]["status"] == "ready"
    assert items["tier0-numeric"]["action"] is None


def test_tier2_only_needs_its_own_model(tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch) -> None:
    # Tier-2 (smolvlm2 only): present that one weight and it is ready even though
    # tier-1 weights are missing (per-tier independence is the falsifiable claim).
    _register_all(monkeypatch)
    svc = _services(tmp_path, models_present={"smolvlm2": True})
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["tier2-vlm"]["status"] == "ready"
    assert items["tier1-multimodal"]["status"] == "needsDownload"


# --------------------------------------------------------------------------- #
# provider / function capabilities
# --------------------------------------------------------------------------- #
def _cloud_routing(*functions: str) -> dict[str, Any]:
    fns = functions or ("select", "subtitles", "translation")
    return {"routing": {"perFunction": {fn: {"provider": "gpt", "fallback": []} for fn in fns}}}


def test_function_routed_cloud_no_key_needs_key(tmp_path: Path, ctx: RpcContext) -> None:
    # A cloud-routed function with no provider key -> needsKey + openProviders.
    svc = _services(tmp_path, settings=_cloud_routing())
    items = _by_cap(svc.readiness_summary({}, ctx))
    sel = items["ai.select"]
    assert sel["status"] == "needsKey"
    assert sel["blockedBy"]
    assert sel["action"]["kind"] == "openProviders"


def test_function_routed_cloud_keyed_no_consent_needs_consent(tmp_path: Path, ctx: RpcContext) -> None:
    # Key present but text consent OFF -> needsConsent + a setConsent action.
    settings = {
        **_cloud_routing(),
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real-key"]}],
        "consent": {"perProvider": {"gpt": {"text": False}}},
    }
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    sel = items["ai.select"]
    assert sel["status"] == "needsConsent"
    assert sel["action"]["kind"] == "setConsent"
    assert sel["action"]["provider"] == "gpt"


def test_function_routed_cloud_keyed_and_consented_is_ready(tmp_path: Path, ctx: RpcContext) -> None:
    settings = {
        **_cloud_routing(),
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real-key"]}],
        "consent": {"perProvider": {"gpt": {"text": True}}},
    }
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["ai.select"]["status"] == "ready"
    assert items["ai.select"]["action"] is None


def test_function_routed_local_is_ready_without_key(tmp_path: Path, ctx: RpcContext) -> None:
    # A function routed to LOCAL needs neither key nor consent -> ready.
    settings = {"routing": {"perFunction": {"select": {"provider": "local", "fallback": []}}}}
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["ai.select"]["status"] == "ready"


def test_function_unrouted_defaults_local_ready(tmp_path: Path, ctx: RpcContext) -> None:
    # No routing at all -> every function is the local-safe default -> ready.
    svc = _services(tmp_path)
    items = _by_cap(svc.readiness_summary({}, ctx))
    for fn in ("select", "subtitles", "translation", "vision", "editPlan"):
        assert items[f"ai.{fn}"]["status"] == "ready"
        assert items[f"ai.{fn}"]["action"] is None


def test_vision_function_uses_frame_consent(tmp_path: Path, ctx: RpcContext) -> None:
    # The vision function checks FRAME consent (not text); frames OFF -> needsConsent.
    settings = {
        "routing": {"perFunction": {"vision": {"provider": "gpt", "fallback": []}}},
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real-key"]}],
        "consent": {"perProvider": {"gpt": {"frames": False, "text": True}}},
    }
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["ai.vision"]["status"] == "needsConsent"


def test_provider_entry_keyed_by_provider_field_or_id(tmp_path: Path, ctx: RpcContext) -> None:
    # A provider whose key match is on the "provider" field (id differs) still
    # resolves its key + consent (the lookup tolerates either identifier).
    settings = {
        "routing": {"perFunction": {"select": {"provider": "gpt", "fallback": []}}},
        "providers": [{"id": "my-openai", "provider": "gpt", "apiKeys": ["sk-real-key"]}],
        "consent": {"perProvider": {"gpt": {"text": True}}},
    }
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["ai.select"]["status"] == "ready"


def test_provider_empty_keys_list_needs_key(tmp_path: Path, ctx: RpcContext) -> None:
    # An entry present but with an empty apiKeys list still counts as no key.
    settings = {
        **_cloud_routing("select"),
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": []}],
    }
    svc = _services(tmp_path, settings=settings)
    items = _by_cap(svc.readiness_summary({}, ctx))
    assert items["ai.select"]["status"] == "needsKey"


# --------------------------------------------------------------------------- #
# read-only invariants + registration
# --------------------------------------------------------------------------- #
def test_summary_makes_no_provider_or_ensure_call(tmp_path: Path, ctx: RpcContext) -> None:
    # The read-only invariant: a provider seam wired to EXPLODE is never invoked,
    # and the data dir is never created (no asset ensured/downloaded).
    def _boom(*_a: Any, **_k: Any) -> Any:  # pragma: no cover - must never run
        raise AssertionError("readiness.summary must not call a provider")

    settings = {
        **_cloud_routing(),
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real-key"]}],
        "consent": {"perProvider": {"gpt": {"text": True}}},
    }
    svc = _services(tmp_path, settings=settings)
    svc._provider = _boom  # any provider use would explode
    result = svc.readiness_summary({}, ctx)
    assert result["items"]  # produced a roll-up without ever touching the provider
    assert not (svc.data_dir / "models").exists()


def test_summary_leaks_no_full_key(tmp_path: Path, ctx: RpcContext) -> None:
    settings = {
        **_cloud_routing(),
        "providers": [{"id": "gpt", "provider": "gpt", "apiKeys": ["sk-super-secret-full-key"]}],
        "consent": {"perProvider": {"gpt": {"text": True}}},
    }
    svc = _services(tmp_path, settings=settings)
    result = svc.readiness_summary({}, ctx)

    def _walk(obj: Any) -> list[str]:
        if isinstance(obj, dict):
            return [s for v in obj.values() for s in _walk(v)]
        if isinstance(obj, list):
            return [s for v in obj for s in _walk(v)]
        if isinstance(obj, str):
            return [obj]
        return []  # pragma: no cover - defensive; payload is str/dict/list only

    for value in _walk(result):
        assert "sk-super-secret-full-key" not in value


def test_missing_tier_assets_dedups_and_skips_assetless(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``aesthetic`` and ``vlm_backbone`` SHARE the SigLIP-2 asset, and ``motion``
    # is a zero-download floor with no asset: a tier mixing them collapses the
    # shared asset to ONE name and skips the asset-less component entirely.
    _register_all(monkeypatch)
    missing = _missing_tier_assets(("vlm_backbone", "aesthetic", "motion"), {})
    assert missing == ["siglip2-so400m"]
    # When the shared weight IS installed, nothing is reported missing.
    assert _missing_tier_assets(("vlm_backbone", "aesthetic"), {"vlm_backbone": True, "aesthetic": True}) == []


def test_missing_tier_assets_filters_deregistered(monkeypatch: pytest.MonkeyPatch) -> None:
    # B1: a mapped-but-DE-REGISTERED asset (manifest.get_asset is None) is dropped
    # from the missing list — only manifest-known asset names are ever emitted.
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(
        _manifest,
        "get_asset",
        lambda n: SimpleNamespace(label="", size_mb=0) if n == "siglip2-so400m" else None,
    )
    # saliency -> vinet-s-saliency (de-registered) is dropped; vlm_backbone ->
    # siglip2-so400m (registered) survives.
    assert _missing_tier_assets(("saliency", "vlm_backbone"), {}) == ["siglip2-so400m"]


def test_tier_deregistered_assets_dropped_from_ensure_action(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B1: a tier whose missing weights are a MIX of registered + de-registered
    # assets emits an assets.ensure action listing ONLY the registered names; the
    # de-registered names never surface (they would trip the "unknown asset" gate).
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(
        _manifest,
        "get_asset",
        lambda n: SimpleNamespace(label="", size_mb=0) if n == "siglip2-so400m" else None,
    )
    svc = _services(tmp_path, models_present={})  # every tier-1 weight missing
    items = _by_cap(svc.readiness_summary({}, ctx))
    tier1 = items["tier1-multimodal"]
    assert tier1["status"] == "needsDownload"
    assert tier1["action"]["kind"] == "assets.ensure"
    assert tier1["action"]["assets"] == ["siglip2-so400m"]
    blob = repr(tier1)
    for deregistered in ("vinet-s-saliency", "panns-cnn14", "transnetv2-pytorch", "dover-mobile-quality"):
        assert deregistered not in blob
    assert "unknown asset" not in blob


def test_tier_all_deregistered_missing_is_unavailable_no_action(
    tmp_path: Path, ctx: RpcContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    # B1: when EVERY missing weight maps to a de-registered asset, the tier cannot
    # offer a working download button (that would emit an unknown asset name), so
    # it reports `unavailable` with NO action rather than a false `ready`. Pinned
    # via monkeypatch (all assets de-registered) so it is isolation-proof.
    from media_studio.assets import manifest as _manifest

    monkeypatch.setattr(_manifest, "get_asset", lambda _n: None)
    svc = _services(tmp_path, models_present={})
    items = _by_cap(svc.readiness_summary({}, ctx))
    tier1 = items["tier1-multimodal"]
    assert tier1["status"] == "unavailable"
    assert tier1["action"] is None
    blob = repr(tier1)
    assert "unknown asset" not in blob
    assert "vinet-s-saliency" not in blob


def test_provider_has_key_skips_non_matching_entries(tmp_path: Path, ctx: RpcContext) -> None:
    # A list whose FIRST entry does not match the routed id: the loop must walk
    # past it and find the key on the matching second entry.
    providers = [
        {"id": "other", "provider": "claude", "apiKeys": ["sk-other"]},
        {"id": "gpt", "provider": "gpt", "apiKeys": ["sk-real-key"]},
    ]
    assert _provider_has_key("gpt", providers) is True
    # No entry matches at all -> no key.
    assert _provider_has_key("absent", providers) is False


def test_readiness_summary_is_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "readiness.summary" in registered
