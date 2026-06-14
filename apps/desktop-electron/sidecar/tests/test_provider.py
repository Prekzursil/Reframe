"""Unit tests for media_studio.models.provider.

The HTTP transport is MOCKED at the injectable seam: no socket is ever opened and
``urllib`` is never reached on the happy path. The tests pin the interface that
``features/select.py`` and ``features/subtitles.py`` actually call:

  * select.py:   provider.chat(messages, temperature=..., max_tokens=...)  -> str
  * subtitles.py: provider.chat(messages)  (no kwargs)                      -> str

plus the OpenAI-compatible request body, the response parsing, the complete()
wrapper, the factory routing (local vs cloud), and the urllib error mapping (the
one place urllib is exercised, with urlopen itself monkeypatched).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

import pytest

from media_studio.models import provider as prov
from media_studio.models.provider import (
    CloudProvider,
    LocalServerProvider,
    Provider,
    ProviderError,
    get_provider,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _ok_response(content: str) -> Dict[str, Any]:
    """An OpenAI-style chat-completions success envelope."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class RecordingTransport:
    """A fake transport recording every (url, body, headers, timeout) call.

    Returns a preconfigured response dict (default: assistant content "hi").
    """

    def __init__(self, response: Dict[str, Any] | None = None):
        self.response = response if response is not None else _ok_response("hi")
        self.calls: List[Dict[str, Any]] = []

    def __call__(
        self, url: str, body: Dict[str, Any], headers: Dict[str, str], timeout: float
    ) -> Dict[str, Any]:
        self.calls.append(
            {"url": url, "body": body, "headers": headers, "timeout": timeout}
        )
        return self.response


# --------------------------------------------------------------------------- #
# interface match: chat(messages, *, temperature, max_tokens) -> str
# --------------------------------------------------------------------------- #
def test_chat_returns_assistant_content_string():
    t = RecordingTransport(_ok_response("the answer"))
    p = LocalServerProvider(transport=t)
    out = p.chat([{"role": "user", "content": "q"}], temperature=0.4, max_tokens=6000)
    assert out == "the answer"
    assert isinstance(out, str)


def test_chat_matches_select_py_keyword_call():
    # select.py calls: provider.chat(messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    p.chat(msgs, temperature=0.4, max_tokens=6000)
    body = t.calls[0]["body"]
    assert body["temperature"] == 0.4
    assert body["max_tokens"] == 6000
    assert body["messages"] == msgs


def test_chat_matches_subtitles_py_bare_call():
    # subtitles.py calls: provider.chat(messages)  -- no temperature/max_tokens.
    t = RecordingTransport(_ok_response("traduction"))
    p = LocalServerProvider(transport=t)
    out = p.chat(
        [
            {"role": "system", "content": "translate to fr"},
            {"role": "user", "content": "hello"},
        ]
    )
    assert out == "traduction"
    # defaults applied so the body is still well-formed
    body = t.calls[0]["body"]
    assert body["temperature"] == prov.DEFAULT_TEMPERATURE
    assert body["max_tokens"] == prov.DEFAULT_MAX_TOKENS


def test_chat_accepts_and_ignores_unknown_kwargs():
    # The seam must swallow extra kwargs (subtitles uses **kwargs in its Protocol).
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    out = p.chat([{"role": "user", "content": "q"}], stream=False, foo="bar")
    assert out == "hi"
    assert "foo" not in t.calls[0]["body"]
    assert "stream" not in t.calls[0]["body"]


def test_chat_forwards_whitelisted_sampling_kwargs():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    p.chat([{"role": "user", "content": "q"}], top_p=0.9, seed=7, stop=["</s>"])
    body = t.calls[0]["body"]
    assert body["top_p"] == 0.9
    assert body["seed"] == 7
    assert body["stop"] == ["</s>"]


def test_chat_copies_messages_not_aliases_caller_list():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    msgs = [{"role": "user", "content": "q"}]
    p.chat(msgs)
    sent = t.calls[0]["body"]["messages"]
    assert sent == msgs
    assert sent[0] is not msgs[0]  # defensive copy of each message dict


# --------------------------------------------------------------------------- #
# request shaping: URL, model, endpoint
# --------------------------------------------------------------------------- #
def test_local_provider_posts_to_chat_completions_endpoint():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["url"] == "http://127.0.0.1:8088/v1/chat/completions"


def test_local_provider_default_base_url_and_model():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert p.base_url == "http://127.0.0.1:8088/v1"
    assert t.calls[0]["body"]["model"] == prov.DEFAULT_LOCAL_MODEL


def test_base_url_trailing_slash_normalized():
    t = RecordingTransport()
    p = LocalServerProvider(base_url="http://host:9000/v1/", transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["url"] == "http://host:9000/v1/chat/completions"


def test_local_provider_sends_no_auth_header():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert "Authorization" not in t.calls[0]["headers"]


# --------------------------------------------------------------------------- #
# complete() convenience wraps chat()
# --------------------------------------------------------------------------- #
def test_complete_wraps_prompt_as_single_user_message():
    t = RecordingTransport(_ok_response("done"))
    p = LocalServerProvider(transport=t)
    out = p.complete("summarize this")
    assert out == "done"
    msgs = t.calls[0]["body"]["messages"]
    assert msgs == [{"role": "user", "content": "summarize this"}]


def test_complete_includes_system_when_given():
    t = RecordingTransport()
    p = LocalServerProvider(transport=t)
    p.complete("hi", system="be terse")
    msgs = t.calls[0]["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "be terse"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_provider_is_abc_cannot_instantiate_directly():
    with pytest.raises(TypeError):
        Provider()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# response parsing / errors
# --------------------------------------------------------------------------- #
def test_extract_content_from_bare_text_field():
    t = RecordingTransport({"choices": [{"text": "legacy text field"}]})
    p = LocalServerProvider(transport=t)
    assert p.chat([{"role": "user", "content": "q"}]) == "legacy text field"


def test_chat_raises_on_no_choices():
    t = RecordingTransport({"choices": []})
    p = LocalServerProvider(transport=t)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "q"}])


def test_chat_raises_on_missing_content():
    t = RecordingTransport({"choices": [{"message": {"role": "assistant"}}]})
    p = LocalServerProvider(transport=t)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "q"}])


def test_chat_raises_on_non_object_choice():
    t = RecordingTransport({"choices": ["nope"]})
    p = LocalServerProvider(transport=t)
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "q"}])


# --------------------------------------------------------------------------- #
# CloudProvider
# --------------------------------------------------------------------------- #
def test_cloud_provider_sends_bearer_auth_header():
    t = RecordingTransport()
    p = CloudProvider(api_key="sk-secret", transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["headers"]["Authorization"] == "Bearer sk-secret"


def test_cloud_provider_default_base_url_and_model():
    t = RecordingTransport()
    p = CloudProvider(api_key="k", transport=t)
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert t.calls[0]["body"]["model"] == prov.DEFAULT_CLOUD_MODEL


def test_cloud_provider_requires_api_key():
    with pytest.raises(ValueError):
        CloudProvider(api_key="")


def test_cloud_provider_never_logs_key_in_error(monkeypatch):
    # An HTTP error must not embed the api key (it lives header-only).
    def boom(url, body, headers, timeout):
        raise ProviderError("LLM HTTP 401: unauthorized")

    p = CloudProvider(api_key="sk-very-secret", transport=boom)
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    assert "sk-very-secret" not in str(ei.value)


# --------------------------------------------------------------------------- #
# get_provider factory (CONTRACTS.md §2 settings.*)
# --------------------------------------------------------------------------- #
def test_factory_returns_local_by_default():
    p = get_provider({})
    assert isinstance(p, LocalServerProvider)


def test_factory_returns_local_when_use_cloud_false():
    p = get_provider({"useCloud": False, "cloudApiKey": "k"})
    assert isinstance(p, LocalServerProvider)


def test_factory_returns_cloud_when_use_cloud_and_key():
    p = get_provider({"useCloud": True, "cloudApiKey": "k"})
    assert isinstance(p, CloudProvider)


def test_factory_falls_back_to_local_when_use_cloud_but_no_key():
    # useCloud requested but key empty -> local (stays usable offline, lean §0).
    p = get_provider({"useCloud": True, "cloudApiKey": ""})
    assert isinstance(p, LocalServerProvider)


def test_factory_honors_local_overrides():
    t = RecordingTransport()
    p = get_provider(
        {"localBaseUrl": "http://gpu-box:9999/v1", "localModel": "qwen3-8b"},
        transport=t,
    )
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["url"] == "http://gpu-box:9999/v1/chat/completions"
    assert t.calls[0]["body"]["model"] == "qwen3-8b"


def test_factory_honors_cloud_overrides():
    t = RecordingTransport()
    p = get_provider(
        {
            "useCloud": True,
            "cloudApiKey": "k",
            "cloudBaseUrl": "https://api.together.xyz/v1",
            "cloudModel": "Qwen/Qwen2.5-7B",
        },
        transport=t,
    )
    p.chat([{"role": "user", "content": "q"}])
    assert t.calls[0]["url"] == "https://api.together.xyz/v1/chat/completions"
    assert t.calls[0]["body"]["model"] == "Qwen/Qwen2.5-7B"


def test_factory_forwards_transport():
    t = RecordingTransport(_ok_response("via factory"))
    p = get_provider({}, transport=t)
    assert p.chat([{"role": "user", "content": "q"}]) == "via factory"


def test_factory_none_settings_is_local():
    assert isinstance(get_provider(None), LocalServerProvider)


# --------------------------------------------------------------------------- #
# urllib transport: the ONLY place urllib is exercised (urlopen monkeypatched).
# No real network: we patch urllib.request.urlopen with in-memory fakes.
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_urllib_post_json_happy_path(monkeypatch):
    captured: Dict[str, Any] = {}

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["method"] = request.get_method()
        captured["ctype"] = request.headers.get("Content-type")
        return _FakeResp(json.dumps(_ok_response("urllib says hi")).encode("utf-8"))

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()  # default transport = real _urllib_post_json
    out = p.chat([{"role": "user", "content": "q"}])
    assert out == "urllib says hi"
    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:8088/v1/chat/completions"
    # body was JSON-encoded
    assert json.loads(captured["data"].decode("utf-8"))["messages"][0]["content"] == "q"


def test_urllib_post_json_maps_httperror(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise prov.urllib.error.HTTPError(
            url="http://x", code=500, msg="boom", hdrs=None, fp=None
        )

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    assert "500" in str(ei.value)


def test_urllib_post_json_maps_urlerror(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise prov.urllib.error.URLError("connection refused")

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    assert "failed" in str(ei.value).lower()


def test_urllib_post_json_raises_on_non_json_body(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResp(b"<html>not json</html>")

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "q"}])


def test_urllib_post_json_raises_on_non_object_json(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResp(b"[1, 2, 3]")

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError):
        p.chat([{"role": "user", "content": "q"}])


# --------------------------------------------------------------------------- #
# end-to-end: a fake provider satisfies the duck-typed consumer Protocols.
# This proves the concrete provider is substitutable wherever select/subtitles
# expect a `Provider` (structural typing).
# --------------------------------------------------------------------------- #
def test_concrete_provider_satisfies_consumer_chat_signature():
    captured: Dict[str, Any] = {}

    def transport(url, body, headers, timeout):  # noqa: ANN001
        captured["body"] = body
        return _ok_response('{"clips": []}')

    p = LocalServerProvider(transport=transport)

    # Mimic select.py's exact call shape:
    def fake_select_ask(provider: Provider, messages: Sequence[Dict[str, str]]) -> str:
        return provider.chat(messages, temperature=0.4, max_tokens=6000)

    result = fake_select_ask(p, [{"role": "user", "content": "pick clips"}])
    assert result == '{"clips": []}'
    assert captured["body"]["temperature"] == 0.4
