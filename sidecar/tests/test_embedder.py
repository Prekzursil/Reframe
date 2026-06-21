"""Unit tests for media_studio.models.embedder (WU-A2, resolves G-A1).

The HTTP transport is MOCKED at the injectable seam (mirroring
``tests/test_provider.py``): no socket is ever opened and ``urllib`` is never
reached on the happy path. These tests pin the embedder interface the semantic
index (WU-A4/A5) and the routing pool consume:

  * ``Embedder.embed(texts) -> list[list[float]]``
  * one POST to ``{base_url}/v1/embeddings`` with body ``{input:[...], model}``
  * response parse from ``data[].embedding``
  * empty input short-circuits with NO transport call
  * HTTP / parse failures map to a single typed :class:`EmbedderError`
  * the deterministic local-backstop embedder (no socket, no key)
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models.embedder import (
    DEFAULT_CLOUD_EMBED_MODEL,
    DEFAULT_LOCAL_BASE_URL,
    DEFAULT_LOCAL_EMBED_DIM,
    CloudEmbedder,
    Embedder,
    EmbedderError,
    LocalEmbedder,
    get_embedder,
)


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
def _ok_response(*vectors: list[float]) -> dict[str, Any]:
    """An OpenAI-style ``/v1/embeddings`` success envelope for ``vectors``."""
    return {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]}


class RecordingTransport:
    """A fake transport recording every (url, body, headers, timeout) call.

    Returns a preconfigured response dict (default: one 2-d unit vector).
    """

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response if response is not None else _ok_response([1.0, 0.0])
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        return self.response


class RaisingTransport:
    """A fake transport that raises a typed :class:`EmbedderError` like the real one."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        raise self._exc


# --------------------------------------------------------------------------- #
# AC (a): embed issues ONE POST to /v1/embeddings and parses data[].embedding
# --------------------------------------------------------------------------- #
def test_cloud_embed_posts_once_and_returns_vectors() -> None:
    t = RecordingTransport(_ok_response([1.0, 2.0], [3.0, 4.0]))
    emb = CloudEmbedder(api_key="sk-test", model="text-embedding-3-small", transport=t)

    vectors = emb.embed(["a", "b"])

    assert vectors == [[1.0, 2.0], [3.0, 4.0]]
    assert len(t.calls) == 1
    call = t.calls[0]
    assert call["url"].endswith("/v1/embeddings")
    assert call["body"]["input"] == ["a", "b"]
    assert call["body"]["model"] == "text-embedding-3-small"


def test_cloud_embed_sends_bearer_header() -> None:
    t = RecordingTransport(_ok_response([0.0, 1.0]))
    emb = CloudEmbedder(api_key="sk-secret", transport=t)

    emb.embed(["x"])

    assert t.calls[0]["headers"]["Authorization"] == "Bearer sk-secret"
    assert t.calls[0]["body"]["model"] == DEFAULT_CLOUD_EMBED_MODEL


def test_cloud_embed_accepts_sequence_not_just_list() -> None:
    t = RecordingTransport(_ok_response([1.0]))
    emb = CloudEmbedder(api_key="k", transport=t)

    emb.embed(("only",))

    assert t.calls[0]["body"]["input"] == ["only"]


def test_cloud_embed_base_url_trailing_slash_normalized() -> None:
    t = RecordingTransport(_ok_response([1.0]))
    emb = CloudEmbedder(api_key="k", base_url="https://api.example.com/v1/", transport=t)

    emb.embed(["q"])

    assert t.calls[0]["url"] == "https://api.example.com/v1/embeddings"


# --------------------------------------------------------------------------- #
# AC (b): empty input returns [] WITHOUT a transport call
# --------------------------------------------------------------------------- #
def test_cloud_embed_empty_input_no_transport_call() -> None:
    t = RecordingTransport()
    emb = CloudEmbedder(api_key="k", transport=t)

    assert emb.embed([]) == []
    assert t.calls == []


def test_local_embed_empty_input_returns_empty() -> None:
    emb = LocalEmbedder()
    assert emb.embed([]) == []


# --------------------------------------------------------------------------- #
# AC (c): HTTP / malformed responses map to a typed EmbedderError
# --------------------------------------------------------------------------- #
def test_cloud_embed_transport_error_is_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RaisingTransport(EmbedderError("boom")))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_missing_data_key_raises_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RecordingTransport({"nope": []}))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_data_not_a_list_raises_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RecordingTransport({"data": "oops"}))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_entry_not_object_raises_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RecordingTransport({"data": ["bad"]}))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_embedding_not_a_list_raises_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RecordingTransport({"data": [{"embedding": "no"}]}))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_embedding_non_numeric_raises_typed() -> None:
    emb = CloudEmbedder(api_key="k", transport=RecordingTransport({"data": [{"embedding": ["x"]}]}))
    with pytest.raises(EmbedderError):
        emb.embed(["a"])


def test_cloud_embed_count_mismatch_raises_typed() -> None:
    # Two inputs but only one embedding returned.
    t = RecordingTransport(_ok_response([1.0, 2.0]))
    emb = CloudEmbedder(api_key="k", transport=t)
    with pytest.raises(EmbedderError):
        emb.embed(["a", "b"])


# --------------------------------------------------------------------------- #
# CloudEmbedder construction guards
# --------------------------------------------------------------------------- #
def test_cloud_embedder_requires_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        CloudEmbedder(api_key="")


# --------------------------------------------------------------------------- #
# LocalEmbedder: deterministic local backstop seam (no socket, no key)
# --------------------------------------------------------------------------- #
def test_local_embed_is_deterministic_and_fixed_dim() -> None:
    emb = LocalEmbedder()
    out1 = emb.embed(["hello", "world"])
    out2 = emb.embed(["hello", "world"])

    assert out1 == out2
    assert len(out1) == 2
    assert all(len(v) == DEFAULT_LOCAL_EMBED_DIM for v in out1)


def test_local_embed_distinguishes_distinct_texts() -> None:
    emb = LocalEmbedder()
    [a], [b] = emb.embed(["alpha"]), emb.embed(["beta"])
    assert a != b


def test_local_embed_vectors_are_unit_normalized() -> None:
    emb = LocalEmbedder(dim=8)
    [v] = emb.embed(["normalize me"])
    norm = sum(x * x for x in v) ** 0.5
    assert norm == pytest.approx(1.0)


def test_local_embed_empty_text_yields_zero_vector() -> None:
    emb = LocalEmbedder(dim=4)
    [v] = emb.embed([""])
    assert v == [0.0, 0.0, 0.0, 0.0]


# --------------------------------------------------------------------------- #
# Protocol conformance + factory
# --------------------------------------------------------------------------- #
def test_embedders_satisfy_protocol() -> None:
    assert isinstance(LocalEmbedder(), Embedder)
    assert isinstance(CloudEmbedder(api_key="k"), Embedder)


def test_get_embedder_returns_cloud_when_keyed() -> None:
    settings = {"useCloud": True, "cloudApiKey": "sk-x", "cloudEmbedModel": "m"}
    emb = get_embedder(settings, transport=RecordingTransport())
    assert isinstance(emb, CloudEmbedder)
    assert emb.model == "m"


def test_get_embedder_falls_back_to_local_without_key() -> None:
    assert isinstance(get_embedder({"useCloud": True}), LocalEmbedder)


def test_get_embedder_local_when_not_use_cloud() -> None:
    assert isinstance(get_embedder({"cloudApiKey": "sk-x"}), LocalEmbedder)


def test_get_embedder_defaults_to_local_for_no_settings() -> None:
    emb = get_embedder()
    assert isinstance(emb, LocalEmbedder)
    assert DEFAULT_LOCAL_BASE_URL  # exported constant is non-empty
