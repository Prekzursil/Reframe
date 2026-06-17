"""WU-pool wiring tests: GET probe transport + BOTH LLM seams resolve the pool.

Covers (PLAN §WU-pool acceptance):
  * the GET-capable probe path so ``local_detect`` works against real
    Ollama/LM Studio ``GET /models`` (carryforward #2) — a method-aware urllib
    helper + a ready-made GET transport;
  * ``get_provider`` returns a :class:`RotatingProvider` when ``settings.providers``
    is configured (else the existing Local/Cloud fall-through is unchanged);
  * the pool build folds in ``detect_local_servers`` results;
  * the SECOND seam: ``TieredTranslator`` tier3 (``_hosted_provider``) rotates
    through the SAME pool via the default ``hosted_provider_factory``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from media_studio.models import provider as prov
from media_studio.models import translation as tr
from media_studio.models.provider import (
    ProviderError,
    RotatingProvider,
    build_pool_provider,
    get_provider,
)


def _ok(content: str = "ok") -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _models(*ids: str) -> dict[str, Any]:
    return {"object": "list", "data": [{"id": i} for i in ids]}


class KeyTransport:
    """Fake transport keyed on the Bearer key (or None for keyless local)."""

    def __init__(self, by_key: dict[str | None, list[Any]]) -> None:
        self.by_key = by_key
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        auth = headers.get("Authorization", "")
        key = auth[len("Bearer ") :] if auth.startswith("Bearer ") else None
        self.calls.append({"url": url, "key": key, "body": body})
        script = self.by_key.get(key)
        if not script:
            raise ProviderError(f"nothing for {key!r} at {url}")
        outcome = script[0] if len(script) == 1 else script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# --------------------------------------------------------------------------- #
# GET-capable probe transport (carryforward #2)
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        # A real urllib response exposes ``.headers`` (an email.message.Message);
        # a plain dict is items()-compatible for the production header capture.
        self.headers = headers if headers is not None else {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_get_transport_issues_a_GET_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["data"] = request.data
        return _FakeResp(json.dumps(_models("llama3.2")).encode("utf-8"))

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    out = prov.urllib_get_json("http://127.0.0.1:11434/v1/models", {}, {}, 2.0)
    assert captured["method"] == "GET"
    assert captured["data"] is None  # a GET carries no body
    assert out["data"][0]["id"] == "llama3.2"


def test_post_json_captures_response_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    # The real urllib path surfaces response headers under ``_headers`` so the
    # rotation pool can read X-RateLimit-* metadata (covers the headers branch).
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResp(
            json.dumps(_ok("hi")).encode("utf-8"),
            headers={"X-RateLimit-Remaining": "5", "X-RateLimit-Limit": "10"},
        )

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    out = prov._urllib_post_json("http://x/v1/chat/completions", {"model": "m"}, {}, 1.0)
    assert out["_headers"]["X-RateLimit-Remaining"] == "5"


def test_get_transport_maps_httperror(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise prov.urllib.error.HTTPError(url="http://x", code=404, msg="nope", hdrs=None, fp=None)

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ProviderError):
        prov.urllib_get_json("http://x/models", {}, {}, 2.0)


def test_get_transport_used_by_local_detect_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # detect_local_servers must accept the GET transport and parse /models.
    from media_studio.models import local_detect as ld

    def fake_urlopen(request, timeout):  # noqa: ANN001
        assert request.get_method() == "GET"
        return _FakeResp(json.dumps(_models("m")).encode("utf-8"))

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    entries = ld.detect_local_servers({}, transport=prov.urllib_get_json)
    # Both well-known endpoints answer the same fake -> both detected.
    assert {e["kind"] for e in entries} == {"ollama", "lmstudio"}


# --------------------------------------------------------------------------- #
# get_provider returns a RotatingProvider when settings.providers configured
# --------------------------------------------------------------------------- #
def test_get_provider_returns_rotating_when_providers_configured() -> None:
    settings = {
        "providers": [
            {
                "id": "groq",
                "provider": "Groq",
                "kind": "cloud",
                "baseUrl": "https://api.groq.com/openai/v1",
                "model": "gpt-oss-120b",
                "apiKeys": ["k1"],
                "enabled": True,
                "capabilities": ["text"],
                "unit": "token",
            }
        ]
    }
    t = KeyTransport({"k1": [_ok("rotated")]})
    p = get_provider(settings, transport=t)
    assert isinstance(p, RotatingProvider)
    assert p.chat([{"role": "user", "content": "q"}]) == "rotated"


def test_get_provider_unchanged_local_fallthrough_when_no_providers() -> None:
    p = get_provider({})
    assert isinstance(p, prov.LocalServerProvider)


def test_get_provider_unchanged_cloud_fallthrough() -> None:
    p = get_provider({"useCloud": True, "cloudApiKey": "k"})
    assert isinstance(p, prov.CloudProvider)


def test_get_provider_ignores_disabled_providers() -> None:
    settings = {
        "providers": [
            {"id": "d", "provider": "Groq", "baseUrl": "u", "model": "m", "apiKeys": ["k1"], "enabled": False},
        ]
    }
    # All providers disabled -> no pool -> local fall-through.
    p = get_provider(settings)
    assert isinstance(p, prov.LocalServerProvider)


def test_get_provider_skips_provider_with_no_keys_unless_local() -> None:
    settings = {
        "providers": [
            {"id": "nokey", "provider": "Groq", "baseUrl": "u", "model": "m", "apiKeys": [], "enabled": True},
        ]
    }
    p = get_provider(settings)
    assert isinstance(p, prov.LocalServerProvider)


def test_get_provider_ignores_non_dict_provider_entries() -> None:
    # A malformed (non-dict) entry in settings.providers is skipped, not crashed.
    settings = {
        "providers": [
            "garbage",
            {"id": "g", "provider": "Groq", "baseUrl": "u", "model": "m", "apiKeys": ["k1"], "enabled": True},
        ]
    }
    t = KeyTransport({"k1": [_ok("rotated")]})
    p = get_provider(settings, transport=t)
    assert isinstance(p, RotatingProvider)


def test_pool_always_appends_local_backstop() -> None:
    settings = {
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
        "localBaseUrl": "http://127.0.0.1:8088/v1",
    }
    t = KeyTransport({"k1": [ProviderError("LLM HTTP 429: x")], None: [_ok("local backstop")]})
    p = get_provider(settings, transport=t)
    assert isinstance(p, RotatingProvider)
    # Cloud 429s -> falls through to the always-appended local backstop.
    assert p.chat([{"role": "user", "content": "q"}]) == "local backstop"


def test_build_pool_provider_folds_in_detected_local_servers() -> None:
    # Ollama detected via a GET probe is slotted into the pool as an entry.
    settings = {
        "providers": [
            {"id": "groq", "provider": "Groq", "baseUrl": "u", "model": "m", "apiKeys": ["k1"], "enabled": True}
        ]
    }
    chat_transport = KeyTransport(
        {
            "k1": [ProviderError("LLM HTTP 429: x")],
            None: [_ok("ollama answered")],
        }
    )

    def detect_transport(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        # Only Ollama is up.
        if "11434" in url:
            return _models("llama3.2")
        raise ProviderError("down")

    p = build_pool_provider(settings, transport=chat_transport, probe_transport=detect_transport)
    assert isinstance(p, RotatingProvider)
    # Groq 429s -> the detected Ollama (keyless local) serves.
    assert p.chat([{"role": "user", "content": "q"}]) == "ollama answered"
    # Ollama appears as a provider group.
    assert "ollama" in p.provider_groups() or "ollama" in [e.provider for e in p.entries]


def test_build_pool_provider_no_cloud_no_detect_is_local_only() -> None:
    def detect_transport(url, body, headers, timeout):  # noqa: ANN001
        raise ProviderError("down")

    p = build_pool_provider({}, transport=KeyTransport({None: [_ok("local")]}), probe_transport=detect_transport)
    # No cloud + no detected local servers -> still has the llama.cpp backstop.
    assert isinstance(p, RotatingProvider)
    assert p.chat([{"role": "user", "content": "q"}]) == "local"


# --------------------------------------------------------------------------- #
# SECOND seam: TieredTranslator tier3 rotates through the SAME pool
# --------------------------------------------------------------------------- #
def test_translator_tier3_uses_rotating_pool_when_providers_configured() -> None:
    settings = {
        "providers": [
            {
                "id": "groq",
                "provider": "Groq",
                "baseUrl": "https://api.groq.com/openai/v1",
                "model": "m",
                "apiKeys": ["k1", "k2"],
                "enabled": True,
                "capabilities": ["text"],
            }
        ]
    }
    # k1 429s on the hosted translation call -> rotate to k2.
    t = KeyTransport({"k1": [ProviderError("LLM HTTP 429: x")], "k2": [_ok("bonjour")]})
    translator = tr.get_translator(settings, transport=t)
    # 'xx' is not in the routing table -> routes to tier3 (hosted) first.
    line = translator.line_translator("xx")
    assert line("hello") == "bonjour"


def test_translator_tier3_falls_back_to_cloud_provider_when_no_pool() -> None:
    # No settings.providers -> the default hosted factory uses CloudProvider.
    settings = {"cloudApiKey": "sk-test", "cloudBaseUrl": "https://api.openai.com/v1"}
    t = KeyTransport({"sk-test": [_ok("hola")]})
    translator = tr.get_translator(settings, transport=t)
    line = translator.line_translator("xx")
    assert line("hello") == "hola"


def test_translator_tier3_unavailable_when_no_pool_and_no_key() -> None:
    settings: dict[str, Any] = {}
    translator = tr.get_translator(settings, transport=KeyTransport({}))
    line = translator.line_translator("xx")
    with pytest.raises(tr.TranslationError):
        line("hello")


def test_translator_explicit_hosted_factory_still_wins() -> None:
    # An explicitly-injected hosted factory overrides the pool default.
    sentinel = object()

    class _Prov:
        def chat(self, messages, **kwargs):  # noqa: ANN001
            return "explicit"

    translator = tr.get_translator(
        {"providers": [{"id": "x", "provider": "Groq", "baseUrl": "u", "model": "m", "apiKeys": ["k"]}]},
        hosted_provider_factory=lambda: _Prov(),
    )
    assert translator.line_translator("xx")("hi") == "explicit"
    _ = sentinel
