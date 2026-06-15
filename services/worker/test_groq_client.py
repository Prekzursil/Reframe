"""Tests for the minimal OpenAI-compatible Groq chat client."""

from __future__ import annotations

import json

import pytest

from services.worker import groq_client  # pylint: disable=import-error


def test_truthy_env(monkeypatch):
    """``_truthy_env`` recognises common truthy flag values."""
    monkeypatch.delenv("SOME", raising=False)
    assert groq_client._truthy_env("SOME") is False
    monkeypatch.setenv("SOME", "On")
    assert groq_client._truthy_env("SOME") is True


def test_get_client_offline(monkeypatch):
    """No client is built when offline mode is enabled."""
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    assert groq_client.get_groq_chat_client_from_env() is None


def test_get_client_no_api_key(monkeypatch):
    """No client is built when the API key is missing."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq_client.get_groq_chat_client_from_env() is None


def test_get_client_builds_with_env(monkeypatch):
    """A client is built from env vars, defaulting base_url and timeout."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "12.5")
    client = groq_client.get_groq_chat_client_from_env()
    assert client is not None
    assert client.base_url == "https://api.groq.com/openai/v1"
    assert client.timeout_seconds == 12.5


def test_get_client_invalid_timeout(monkeypatch):
    """An unparsable timeout falls back to the 30s default."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("GROQ_BASE_URL", "https://custom/api")
    client = groq_client.get_groq_chat_client_from_env()
    assert client.timeout_seconds == 30.0
    assert client.base_url == "https://custom/api"


def test_create_offline_refuses(monkeypatch):
    """``create`` refuses to make a network call in offline mode."""
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    client = groq_client.GroqChatClient(api_key="k")
    with pytest.raises(RuntimeError, match="OFFLINE_MODE"):
        client.create(model="m", messages=[{"role": "user", "content": "hi"}])


def test_create_returns_message_content(monkeypatch):
    """``create`` POSTs a payload and returns the OpenAI-shaped content."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "hello back"}}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=None):  # pylint: disable=unused-argument
        captured["data"] = json.loads(req.data.decode("utf-8"))
        captured["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(groq_client.urllib.request, "urlopen", fake_urlopen)
    client = groq_client.GroqChatClient(api_key="k")
    resp = client.create(
        model="llama3",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        response_format={"type": "json_object"},
    )
    assert resp.choices[0].message.content == "hello back"
    assert captured["data"]["max_tokens"] == 64
    assert captured["data"]["response_format"] == {"type": "json_object"}
    assert captured["url"].endswith("/chat/completions")


def test_create_malformed_response(monkeypatch):
    """A response without the expected shape yields empty content."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"unexpected": True}).encode("utf-8")

    monkeypatch.setattr(
        groq_client.urllib.request, "urlopen", lambda req, timeout=None: _Resp()
    )
    client = groq_client.GroqChatClient(api_key="k")
    resp = client.create(model="m", messages=[])
    assert resp.choices[0].message.content == ""
