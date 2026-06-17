"""Per-function routing for the translation tier3 hosted seam (WU-presets).

PLAN §WU-presets acceptance (b): the per-function override must change the
provider the ``get_translator`` (translation) seam uses. The translation function
threads its routing-preferred provider id through ``get_translator(prefer=...)``
into the SAME rotation pool the general LLM seam uses, so the tier3 hosted
provider tries that provider first.
"""

from __future__ import annotations

from typing import Any

from media_studio.models import provider as P
from media_studio.models import translation as T


def _settings(*providers: dict[str, Any]) -> dict[str, Any]:
    return {"providers": list(providers)}


_GROQ = {
    "id": "groq-llama-3.3-70b",
    "provider": "Groq",
    "baseUrl": "https://groq.example/v1",
    "model": "llama-3.3-70b",
    "apiKeys": ["gk-aaaa1111"],
    "capabilities": ["text"],
    "unit": "token",
}
_MISTRAL = {
    "id": "mistral-pixtral",
    "provider": "Mistral",
    "baseUrl": "https://mistral.example/v1",
    "model": "pixtral",
    "apiKeys": ["mk-bbbb2222"],
    "capabilities": ["text", "vision"],
    "unit": "token",
}


def test_get_translator_prefer_orders_hosted_pool_provider_first() -> None:
    translator = T.get_translator(_settings(_GROQ, _MISTRAL), prefer="mistral-pixtral")
    hosted = translator._hosted_provider()
    assert isinstance(hosted, P.RotatingProvider)
    assert [e.provider for e in hosted.entries][0] == "Mistral"


def test_get_translator_default_keeps_configured_order() -> None:
    translator = T.get_translator(_settings(_GROQ, _MISTRAL))
    hosted = translator._hosted_provider()
    assert [e.provider for e in hosted.entries][0] == "Groq"


def test_get_translator_prefer_local_is_local_only_hosted() -> None:
    translator = T.get_translator(_settings(_GROQ, _MISTRAL), prefer=P.LOCAL_PROVIDER_ID)
    hosted = translator._hosted_provider()
    assert [e.provider for e in hosted.entries] == ["local"]
