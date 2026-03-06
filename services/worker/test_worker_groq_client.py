from __future__ import annotations

import json


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_get_groq_chat_client_from_env_modes(monkeypatch):
    from services.worker import groq_client

    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "true")
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    _expect(groq_client.get_groq_chat_client_from_env() is None, "Expected offline mode to disable Groq client")

    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "false")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    _expect(groq_client.get_groq_chat_client_from_env() is None, "Expected missing API key to disable Groq client")

    monkeypatch.setenv("GROQ_API_KEY", "abc")
    monkeypatch.setenv("GROQ_BASE_URL", "https://example.groq/v1")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "not-a-number")
    client = groq_client.get_groq_chat_client_from_env()
    _expect(client is not None, "Expected client when API key exists")
    _expect(client.base_url == "https://example.groq/v1", "Expected env base URL")
    _expect(client.timeout_seconds == 30.0, "Expected timeout fallback on invalid env value")


def test_groq_chat_client_create_success_and_fallback_content(monkeypatch):
    from services.worker.groq_client import GroqChatClient

    captured = {"url": None, "method": None, "auth": None}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["auth"] = req.headers.get("Authorization")
        _expect(timeout == 12.5, "Expected timeout to be forwarded")
        return _Response({"choices": [{"message": {"content": "hola"}}]})

    monkeypatch.setattr("services.worker.groq_client.urllib.request.urlopen", fake_urlopen)

    client = GroqChatClient(api_key="secret", timeout_seconds=12.5)
    result = client.create(model="llama", messages=[{"role": "user", "content": "hi"}], max_tokens=42)

    _expect(captured["url"].endswith("/chat/completions"), "Expected chat completions endpoint")
    _expect(captured["method"] == "POST", "Expected POST request")
    _expect(captured["auth"] == "Bearer secret", "Expected bearer auth header")
    _expect(result.choices[0].message.content == "hola", "Expected parsed Groq content")

    monkeypatch.setattr(
        "services.worker.groq_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response({"choices": []}),
    )
    empty = client.create(model="llama", messages=[{"role": "user", "content": "hi"}])
    _expect(empty.choices[0].message.content == "", "Expected graceful fallback on malformed payload")


def test_groq_chat_client_create_refuses_offline_mode(monkeypatch):
    from services.worker.groq_client import GroqChatClient

    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    client = GroqChatClient(api_key="secret")
    try:
        client.create(model="llama", messages=[{"role": "user", "content": "hi"}])
        raise AssertionError("Expected offline mode guard to raise")
    except RuntimeError as exc:
        _expect("REFRAME_OFFLINE_MODE" in str(exc), "Expected offline mode error message")
