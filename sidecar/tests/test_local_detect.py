"""Unit tests for media_studio.models.local_detect (WU-pool detection half).

``detect_local_servers(settings, *, transport)`` probes the two well-known
local OpenAI-compatible servers — Ollama (``:11434/v1``) and LM Studio
(``:1234/v1``) — through the SAME injectable ``Transport`` seam the provider
module uses, so no socket is ever opened under test. A successful ``GET /models``
probe yields a pool entry (a light ``PoolEntry``-shaped dict); a connection
error (or an empty/garbage model list) yields no entry for that server and is
NEVER raised — detection failure degrades silently to "no extra providers"
(WU-pool acceptance: "detection failure degrades silently").
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import local_detect as ld
from media_studio.models.local_detect import (
    LM_STUDIO_BASE_URL,
    OLLAMA_BASE_URL,
    PoolEntry,
    detect_local_servers,
)
from media_studio.models.provider import ProviderError


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _models_response(*model_ids: str) -> dict[str, Any]:
    """An OpenAI-style ``GET /models`` success envelope: ``{"data":[{"id":..}]}``."""
    return {"object": "list", "data": [{"id": mid, "object": "model"} for mid in model_ids]}


class MappingTransport:
    """A fake transport returning a per-URL canned response (or raising per-URL).

    ``responses`` maps a probe URL -> a response dict; ``errors`` maps a probe URL
    -> a :class:`ProviderError` to raise (simulating connection refused). A URL in
    neither map raises a generic ProviderError (server absent).
    """

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        errors: dict[str, ProviderError] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if url in self.errors:
            raise self.errors[url]
        if url in self.responses:
            return self.responses[url]
        raise ProviderError(f"LLM request failed: nothing at {url}")


def _ollama_url() -> str:
    return f"{OLLAMA_BASE_URL}/models"


def _lmstudio_url() -> str:
    return f"{LM_STUDIO_BASE_URL}/models"


# --------------------------------------------------------------------------- #
# both servers present -> two pool entries
# --------------------------------------------------------------------------- #
def test_detects_both_ollama_and_lm_studio() -> None:
    transport = MappingTransport(
        responses={
            _ollama_url(): _models_response("llama3.2", "qwen2.5"),
            _lmstudio_url(): _models_response("local-model"),
        }
    )
    entries = detect_local_servers({}, transport=transport)
    by_kind = {e["kind"]: e for e in entries}
    assert set(by_kind) == {"ollama", "lmstudio"}

    ollama = by_kind["ollama"]
    assert ollama["base_url"] == OLLAMA_BASE_URL
    assert ollama["model"] == "llama3.2"  # first reported model
    assert ollama["capabilities"] == ["chat"]
    assert ollama["unit"] == "req"
    assert ollama["id"] == "ollama"

    lmstudio = by_kind["lmstudio"]
    assert lmstudio["base_url"] == LM_STUDIO_BASE_URL
    assert lmstudio["model"] == "local-model"


def test_returns_pool_entry_typeddict_shape() -> None:
    transport = MappingTransport(responses={_ollama_url(): _models_response("m")})
    [entry] = [e for e in detect_local_servers({}, transport=transport) if e["kind"] == "ollama"]
    # Every PoolEntry key is present and well-typed.
    assert set(entry) == {"id", "kind", "base_url", "model", "capabilities", "unit"}
    assert isinstance(entry["capabilities"], list)
    entry_typed: PoolEntry = entry  # static + runtime: the dict satisfies PoolEntry
    assert entry_typed["unit"] == "req"


# --------------------------------------------------------------------------- #
# probe issues a GET /models with no body and a sane timeout
# --------------------------------------------------------------------------- #
def test_probe_hits_models_endpoint_with_empty_body() -> None:
    transport = MappingTransport(responses={_ollama_url(): _models_response("m")})
    detect_local_servers({}, transport=transport)
    ollama_calls = [c for c in transport.calls if c["url"] == _ollama_url()]
    assert ollama_calls, "ollama /models endpoint was probed"
    call = ollama_calls[0]
    assert call["url"].endswith("/models")
    assert call["body"] == {}  # a probe, not a chat completion
    assert call["timeout"] > 0


# --------------------------------------------------------------------------- #
# graceful degradation: connection error / absent server -> skipped, no raise
# --------------------------------------------------------------------------- #
def test_connection_error_yields_empty_no_raise() -> None:
    transport = MappingTransport(
        errors={
            _ollama_url(): ProviderError("LLM request failed: Connection refused"),
            _lmstudio_url(): ProviderError("LLM request failed: Connection refused"),
        }
    )
    # No server up at all -> empty list, NEVER raises.
    assert detect_local_servers({}, transport=transport) == []


def test_one_up_one_down_returns_only_the_live_server() -> None:
    transport = MappingTransport(
        responses={_lmstudio_url(): _models_response("studio")},
        errors={_ollama_url(): ProviderError("LLM request failed: Connection refused")},
    )
    entries = detect_local_servers({}, transport=transport)
    assert [e["kind"] for e in entries] == ["lmstudio"]


def test_unexpected_transport_exception_is_swallowed() -> None:
    # Any non-ProviderError failure from a misbehaving transport must also degrade
    # silently (detection is best-effort, never fatal to the app).
    def boom(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        raise RuntimeError("unexpected")

    assert detect_local_servers({}, transport=boom) == []


# --------------------------------------------------------------------------- #
# empty / malformed model lists -> server skipped (a probe that 200s but has no
# usable model id is treated as "not a real server" rather than crashing)
# --------------------------------------------------------------------------- #
def test_empty_model_list_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): _models_response()})
    assert detect_local_servers({}, transport=transport) == []


def test_data_not_a_list_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): {"object": "list", "data": "nope"}})
    assert detect_local_servers({}, transport=transport) == []


def test_missing_data_key_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): {"object": "list"}})
    assert detect_local_servers({}, transport=transport) == []


def test_model_entry_without_id_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): {"data": [{"object": "model"}]}})
    assert detect_local_servers({}, transport=transport) == []


def test_model_entry_with_blank_id_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): {"data": [{"id": ""}]}})
    assert detect_local_servers({}, transport=transport) == []


def test_first_model_entry_not_a_dict_skips_server() -> None:
    transport = MappingTransport(responses={_ollama_url(): {"data": ["just-a-string"]}})
    assert detect_local_servers({}, transport=transport) == []


# --------------------------------------------------------------------------- #
# settings may override the probe base URLs (e.g. a non-default port)
# --------------------------------------------------------------------------- #
def test_settings_override_base_urls() -> None:
    custom_ollama = "http://127.0.0.1:9999/v1"
    transport = MappingTransport(responses={f"{custom_ollama}/models": _models_response("m")})
    entries = detect_local_servers(
        {"ollamaBaseUrl": custom_ollama}, transport=transport
    )
    assert [e["base_url"] for e in entries] == [custom_ollama]


def test_none_settings_uses_defaults() -> None:
    transport = MappingTransport(responses={_ollama_url(): _models_response("m")})
    entries = detect_local_servers(None, transport=transport)
    assert [e["base_url"] for e in entries] == [OLLAMA_BASE_URL]


def test_blank_settings_override_falls_back_to_default() -> None:
    # An explicitly-empty override string must not blank out the probe URL.
    transport = MappingTransport(responses={_lmstudio_url(): _models_response("m")})
    entries = detect_local_servers(
        {"lmStudioBaseUrl": ""}, transport=transport
    )
    assert [e["kind"] for e in entries] == ["lmstudio"]


# --------------------------------------------------------------------------- #
# the module stays import-light + sleep-free (mirrors the provider no-sleep rule)
# --------------------------------------------------------------------------- #
def test_module_does_not_import_time_or_asyncio() -> None:
    assert not hasattr(ld, "time")
    assert not hasattr(ld, "asyncio")


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
