"""WU-keys RAW-vs-REDACTED AUDIT (the mandatory partition deliverable).

PLAN §WU-keys: enumerate EVERY settings-read that ultimately feeds a
provider/translator a key, and prove each consumes the RAW (full) key — while
every RPC-facing read returns the REDACTED (last-4) view. The four feed callers:

  1. ``provider.get_provider``           (the general LLM seam)
  2. ``translation.TieredTranslator._hosted_provider`` (the tier3 hosted seam)
  3. the ``RotatingProvider`` pool build (``provider.build_pool_provider``)
  4. ``handlers.Services`` construction  (``_get_provider`` / ``_get_translator``)

This test holds the partition: each feed path carries the full key; every
RPC read (``settings.get`` / ``providers.list``) carries only last-4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.handlers import Services
from media_studio.models import provider as provider_mod
from media_studio.models.provider import RotatingProvider
from media_studio.protocol import RpcContext

RAW_KEY = "gsk-RAWFULL-SECRET-PQRS"


def _settings_with_pool() -> dict[str, Any]:
    return {
        "providers": [
            {
                "id": "groq",
                "provider": "Groq",
                "kind": "cloud",
                "baseUrl": "https://api.groq.com/openai/v1",
                "model": "m",
                "apiKeys": [RAW_KEY],
                "enabled": True,
                "capabilities": ["text"],
                "unit": "token",
            }
        ]
    }


def _pool_keys(pool: RotatingProvider) -> list[str | None]:
    """Every live key the pool actually holds in its slots (the RAW truth)."""
    return [slot.key for slot in pool._slots]  # noqa: SLF001 - audit needs the internals


# --------------------------------------------------------------------------- #
# FEED CALLER 1 + 3: get_provider builds a RotatingProvider from RAW keys
# --------------------------------------------------------------------------- #
def test_feed1_get_provider_carries_raw_key() -> None:
    pool = provider_mod.get_provider(_settings_with_pool())
    assert isinstance(pool, RotatingProvider)
    assert RAW_KEY in _pool_keys(pool)


def test_feed3_build_pool_provider_carries_raw_key() -> None:
    pool = provider_mod.build_pool_provider(_settings_with_pool(), detect_local=False)
    assert RAW_KEY in _pool_keys(pool)


def test_legacy_cloud_path_carries_raw_cloud_api_key() -> None:
    # The legacy single-cloud fall-through also reads RAW (no pool configured).
    prov = provider_mod.get_provider({"useCloud": True, "cloudApiKey": RAW_KEY})
    assert prov._api_key == RAW_KEY  # noqa: SLF001 - audit needs the internals


# --------------------------------------------------------------------------- #
# FEED CALLER 2: TieredTranslator._hosted_provider builds from RAW keys
# --------------------------------------------------------------------------- #
def test_feed2_hosted_provider_carries_raw_key() -> None:
    from media_studio.models import translation as translation_mod

    translator = translation_mod.get_translator(_settings_with_pool())
    hosted = translator._hosted_provider()  # noqa: SLF001
    assert isinstance(hosted, RotatingProvider)
    assert RAW_KEY in _pool_keys(hosted)


def test_feed2_hosted_provider_legacy_cloud_key_is_raw() -> None:
    from media_studio.models import translation as translation_mod

    translator = translation_mod.get_translator({"cloudApiKey": RAW_KEY})
    hosted = translator._hosted_provider()  # noqa: SLF001
    assert hosted._api_key == RAW_KEY  # noqa: SLF001


# --------------------------------------------------------------------------- #
# FEED CALLER 4: Services._get_provider / _get_translator consume RAW
# --------------------------------------------------------------------------- #
def test_feed4_handler_get_provider_carries_raw_key(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)
    svc.settings.set(_settings_with_pool())
    pool = svc._get_provider()
    assert isinstance(pool, RotatingProvider)
    assert RAW_KEY in _pool_keys(pool)


def test_feed4_handler_get_translator_carries_raw_key(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)
    svc.settings.set(_settings_with_pool())
    translator = svc._get_translator()
    assert translator is not None
    hosted = translator._hosted_provider()  # noqa: SLF001
    assert RAW_KEY in _pool_keys(hosted)


# --------------------------------------------------------------------------- #
# THE PARTITION: every RPC read returns REDACTED — no full key crosses RPC
# --------------------------------------------------------------------------- #
def test_rpc_reads_return_redacted_not_raw(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path)
    svc.settings.set(_settings_with_pool())
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)

    settings_view = svc.settings_get({}, ctx)
    providers_view = svc.providers_list({}, ctx)

    import json

    for view in (settings_view, providers_view):
        assert RAW_KEY not in json.dumps(view)
    assert providers_view["providers"][0]["apiKeys"] == ["…PQRS"]
    assert settings_view["providers"][0]["apiKeys"] == ["…PQRS"]

    # And the FACTORY truth still has the RAW key (the two sides genuinely differ).
    assert RAW_KEY in svc.settings.get_raw()["providers"][0]["apiKeys"]
