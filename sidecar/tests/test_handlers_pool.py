"""WU-pool handler-seam tests: handlers resolve the pool-aware provider/translator.

The handler construction (``_get_provider`` / ``_get_translator``) already routes
through ``provider.get_provider`` / ``translation.get_translator`` from settings,
so once those factories become pool-aware (settings.providers -> RotatingProvider)
the wiring is transparent. These tests pin that the handler seam DOES yield the
rotation pool when ``settings.providers`` is configured, and stays on the legacy
local/translator path otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio.handlers import Services
from media_studio.models.provider import LocalServerProvider, RotatingProvider


def _services(tmp_path: Path, settings: dict[str, Any]) -> Services:
    svc = Services(data_dir=tmp_path)
    svc.settings.set(settings)
    return svc


def test_handler_get_provider_yields_rotating_when_providers_configured(tmp_path: Path) -> None:
    svc = _services(
        tmp_path,
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "model": "m",
                    "apiKeys": ["k1"],
                    "enabled": True,
                }
            ]
        },
    )
    provider = svc._get_provider()
    assert isinstance(provider, RotatingProvider)


def test_handler_get_provider_yields_local_when_no_providers(tmp_path: Path) -> None:
    svc = _services(tmp_path, {})
    provider = svc._get_provider()
    assert isinstance(provider, LocalServerProvider)


def test_handler_get_translator_pool_aware(tmp_path: Path) -> None:
    svc = _services(
        tmp_path,
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "baseUrl": "https://api.groq.com/openai/v1",
                    "model": "m",
                    "apiKeys": ["k1"],
                    "enabled": True,
                }
            ],
            # tier3 hosted translator is now per-provider TEXT-consent gated; grant
            # it so the Groq cloud entry survives into the rotation pool.
            "consent": {"perProvider": {"Groq": {"text": True}}},
        },
    )
    translator = svc._get_translator()
    assert translator is not None
    # The tier3 hosted provider resolves to the rotation pool.
    hosted = translator._hosted_provider()
    assert isinstance(hosted, RotatingProvider)


def test_handler_get_translator_none_when_legacy_provider_injected(tmp_path: Path) -> None:
    class _Prov:
        def chat(self, messages, **kwargs):  # noqa: ANN001
            return "x"

    svc = Services(data_dir=tmp_path, provider=_Prov())
    assert svc._get_translator() is None
