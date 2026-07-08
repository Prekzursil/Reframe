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
from collections.abc import Sequence
from typing import Any

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
def _ok_response(content: str) -> dict[str, Any]:
    """An OpenAI-style chat-completions success envelope."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class RecordingTransport:
    """A fake transport recording every (url, body, headers, timeout) call.

    Returns a preconfigured response dict (default: assistant content "hi").
    """

    def __init__(self, response: dict[str, Any] | None = None):
        self.response = response if response is not None else _ok_response("hi")
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
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

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


def test_urllib_post_json_happy_path(monkeypatch):
    captured: dict[str, Any] = {}

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
        raise prov.urllib.error.HTTPError(url="http://x", code=500, msg="boom", hdrs=None, fp=None)

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    assert "500" in str(ei.value)
    # M4: the originating HTTP status is carried on the error for cooldown triage.
    assert ei.value.status_code == 500


def test_provider_error_status_code_defaults_none() -> None:
    # A non-HTTP ProviderError (connection/parse) carries no status_code.
    assert ProviderError("boom").status_code is None


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
    captured: dict[str, Any] = {}

    def transport(url, body, headers, timeout):  # noqa: ANN001
        captured["body"] = body
        return _ok_response('{"clips": []}')

    p = LocalServerProvider(transport=transport)

    # Mimic select.py's exact call shape:
    def fake_select_ask(provider: Provider, messages: Sequence[dict[str, str]]) -> str:
        return provider.chat(messages, temperature=0.4, max_tokens=6000)

    result = fake_select_ask(p, [{"role": "user", "content": "pick clips"}])
    assert result == '{"clips": []}'
    assert captured["body"]["temperature"] == 0.4


# --------------------------------------------------------------------------- #
# extra branch coverage: HTTPError body-read failure + the abstract chat body
# --------------------------------------------------------------------------- #
def test_urllib_post_json_httperror_body_read_failure_is_tolerated(monkeypatch):
    # When reading the HTTPError body itself raises, the inner best-effort except
    # swallows it and the error falls back to exc.reason (provider lines 104-105).
    class _BadHTTPError(prov.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__(url="http://x", code=503, msg="unavail", hdrs=None, fp=None)

        def read(self, *_a: Any, **_k: Any) -> bytes:
            raise OSError("body stream broken")

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise _BadHTTPError()

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "503" in msg
    # Body was unreadable -> falls back to the reason string, not a body detail.
    assert "unavail" in msg


# --------------------------------------------------------------------------- #
# WU-keys ENFORCEABLE SCRUB: a forced provider 4xx whose error body echoes the
# live key must NEVER carry that key in the resulting ProviderError. The scrub is
# enforced at the construction site (provider threads secrets= into the default
# _urllib_post_json), asserted DIRECTLY on the ProviderError — not via a log spy.
# --------------------------------------------------------------------------- #
def test_forced_429_error_body_scrubs_live_key(monkeypatch):
    live_key = "sk-live-DEADBEEF1234"

    class _KeyEchoHTTPError(prov.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__(url="http://x", code=429, msg="Too Many Requests", hdrs=None, fp=None)

        def read(self, *_a: Any, **_k: Any) -> bytes:
            # The server echoes our Authorization header (and the bare key) back
            # in its 429 body — exactly the leak the scrub must close.
            body = '{"error":"rate_limited","seen":"Authorization: Bearer ' + live_key + '","raw":"' + live_key + '"}'
            return body.encode("utf-8")

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise _KeyEchoHTTPError()

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    # CloudProvider holds the key; its DEFAULT transport binds secrets=[key].
    p = CloudProvider(api_key=live_key)
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "429" in msg
    assert live_key not in msg  # the live key is gone — enforced at construction
    assert "[REDACTED]" in msg  # and visibly scrubbed, not silently truncated


def test_local_provider_no_secret_still_scrubs_bearer(monkeypatch):
    # A keyless provider (no secrets to thread) still strips an echoed bearer
    # token from the error body via scrub_error_body's bearer regex.
    class _BearerEchoHTTPError(prov.urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__(url="http://x", code=400, msg="bad", hdrs=None, fp=None)

        def read(self, *_a: Any, **_k: Any) -> bytes:
            return b"detail Authorization: Bearer leaked-upstream-token rest"

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise _BearerEchoHTTPError()

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()  # keyless; secrets=()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "leaked-upstream-token" not in msg
    assert "[REDACTED]" in msg


# --------------------------------------------------------------------------- #
# WU-F1 SCRUB SYMMETRY: the URLError branch and the non-JSON branch construct a
# ProviderError from attacker/server-influenced text (``exc.reason`` / the raw
# response body) exactly like the HTTPError branch — so they MUST route through
# the same ``scrub_error_body`` guard. A live key echoed there must never survive.
# --------------------------------------------------------------------------- #
def test_urlerror_reason_scrubs_live_key(monkeypatch):
    live_key = "sk-live-URLERR-9988"

    def fake_urlopen(request, timeout):  # noqa: ANN001
        # A URLError whose reason string echoes the bearer we sent (e.g. a proxy
        # error page URL carrying the key) — the leak this scrub site must close.
        reason = f"tunnel refused (Authorization: Bearer {live_key}; raw {live_key})"
        raise prov.urllib.error.URLError(reason)

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = CloudProvider(api_key=live_key)  # default transport binds secrets=[key]
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "failed" in msg.lower()
    assert live_key not in msg  # the live key is gone — enforced at construction
    assert "[REDACTED]" in msg  # and visibly scrubbed, not silently dropped


def test_non_json_body_scrubs_live_key(monkeypatch):
    live_key = "sk-live-NONJSON-4321"

    def fake_urlopen(request, timeout):  # noqa: ANN001
        # A 200 with a non-JSON HTML/text body that happens to echo the key.
        body = f"<html>proxy error, key={live_key} Authorization: Bearer {live_key}</html>"
        return _FakeResp(body.encode("utf-8"))

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = CloudProvider(api_key=live_key)  # default transport binds secrets=[key]
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "non-JSON" in msg
    assert live_key not in msg  # the live key is gone — enforced at construction
    assert "[REDACTED]" in msg  # and visibly scrubbed, not silently dropped


def test_non_json_body_keyless_still_scrubs_bearer(monkeypatch):
    # A keyless provider (secrets=()) still strips an echoed bearer token from a
    # non-JSON body via scrub_error_body's bearer regex (symmetry with HTTPError).
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeResp(b"not json: Authorization: Bearer leaked-nonjson-token tail")

    monkeypatch.setattr(prov.urllib.request, "urlopen", fake_urlopen)
    p = LocalServerProvider()  # keyless; secrets=()
    with pytest.raises(ProviderError) as ei:
        p.chat([{"role": "user", "content": "q"}])
    msg = str(ei.value)
    assert "leaked-nonjson-token" not in msg
    assert "[REDACTED]" in msg


def test_abstract_chat_body_raises_not_implemented():
    # A subclass that defers to Provider.chat reaches the abstract method body
    # (the bare ``raise NotImplementedError`` on line 167).
    class _PassThrough(Provider):
        def chat(self, messages, *, temperature=0.4, max_tokens=4096, **kwargs):  # noqa: ANN001
            return Provider.chat(self, messages, temperature=temperature, max_tokens=max_tokens, **kwargs)

    with pytest.raises(NotImplementedError):
        _PassThrough().chat([{"role": "user", "content": "q"}])
