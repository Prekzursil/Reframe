"""Embedder seam (WU-A2, resolves G-A1): text -> vector for the semantic index.

The semantic index (``features/semantic_index.py``, WU-A4) and the ``index.*``
handlers (WU-A5) reach the embedding model only through a tiny duck-typed seam:
``Embedder.embed(texts) -> list[list[float]]``. This module is the concrete home
of that seam.

PLAN §WU-A2 explicitly chose a NEW module over extending ``provider.py`` so the
chat transport stays untouched; the embeddings wire protocol is the
OpenAI-compatible ``POST {base_url}/v1/embeddings`` (``{input, model}`` ->
``{data:[{embedding:[...]}]}``). Like ``provider.py`` it is import-light: the one
HTTP call uses **urllib from the stdlib** wrapped behind an injectable transport
so tests NEVER touch the network, and the local backstop is a deterministic,
socket-free embedder so an offline / unconsented run still produces vectors.

Cloud egress is gated upstream — the ``index`` pool is built through
``handlers._text_consented_settings`` (WU-A1) + the budget ack
(``_enforce_cloud_budget_ack``) before any :class:`CloudEmbedder` is reached — so
this module performs no consent/budget logic itself; it is purely the transport +
parse seam, plus the local-only fallback.
"""

from __future__ import annotations

import functools
import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

from ..util import get_logger
from .secrets import scrub_error_body

log = get_logger("media_studio.models.embedder")

# --------------------------------------------------------------------------- #
# Defaults (mirrors provider.py §7 stack choices)
# --------------------------------------------------------------------------- #
#: Default base URL of the local OpenAI-compatible server (matches provider.py).
DEFAULT_LOCAL_BASE_URL: str = "http://127.0.0.1:8088/v1"
#: Default cloud base URL (OpenAI-compatible). Only used with useCloud + a key.
DEFAULT_CLOUD_BASE_URL: str = "https://api.openai.com/v1"
#: A conservative default cloud embedding model (overridable via settings).
DEFAULT_CLOUD_EMBED_MODEL: str = "text-embedding-3-small"
#: HTTP timeout (seconds) for a single embeddings request.
DEFAULT_TIMEOUT: float = 600.0
#: Dimension of the deterministic local-backstop embedder's vectors.
DEFAULT_LOCAL_EMBED_DIM: int = 384

# A transport seam matching provider.Transport: given (url, json-body-dict,
# headers, timeout) it performs an HTTP call and returns the decoded JSON
# response dict. Injected in tests so no socket is ever opened.
Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class EmbedderError(RuntimeError):
    """Raised when an embedder cannot produce vectors (HTTP / parse error).

    Carries a human-readable message; the RPC layer maps it onto a structured
    JSON-RPC error. Never embeds an API key (the key is header-only and the
    error body is scrubbed at the construction site).
    """


@runtime_checkable
class Embedder(Protocol):
    """The text-embedding seam consumed by the semantic index (WU-A4/A5).

    A single method ``embed`` turns a sequence of texts into one dense float
    vector each, in input order. An empty input must short-circuit to ``[]``
    without any network call.
    """

    def embed(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover - interface
        """Return one embedding vector per text, in input order."""
        ...


# --------------------------------------------------------------------------- #
# stdlib urllib transport (the only place a socket is opened) — mirrors
# provider._urllib_request_json but on the /v1/embeddings path.
# --------------------------------------------------------------------------- #
def _urllib_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    secrets: Sequence[str] = (),
) -> dict[str, Any]:  # pragma: no cover - the one real socket; tests inject a fake transport
    """POST ``body`` as JSON to ``url`` and decode the JSON response (stdlib only).

    The single line in this module that opens a socket — excluded from coverage
    exactly like ``provider``'s real transport. Tests inject a fake transport so
    this branch is never executed under the gate. The error body is scrubbed of
    every live key threaded via ``secrets`` (plus any echoed bearer token) BEFORE
    it reaches an :class:`EmbedderError`, so "no live key in any error" holds.
    """
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **headers}
    request = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        # CONTRACT-NOTE: fixed http/https scheme built from settings, never raw
        # attacker input (Bandit B310 satisfied — same posture as provider.py).
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001 - best-effort error body
            detail = ""
        safe_detail = scrub_error_body(detail, secrets) if detail else ""
        reason = scrub_error_body(str(exc.reason), secrets)
        raise EmbedderError(f"embeddings HTTP {exc.code}: {safe_detail or reason}") from exc
    except urllib.error.URLError as exc:
        raise EmbedderError(f"embeddings request failed: {exc.reason}") from exc
    try:
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise EmbedderError(f"embeddings returned non-JSON response: {raw[:200]!r}") from exc
    if not isinstance(decoded, dict):
        raise EmbedderError("embeddings response was not a JSON object")
    return decoded


def _parse_embeddings(response: dict[str, Any], expected: int) -> list[list[float]]:
    """Pull ``data[].embedding`` float vectors from an OpenAI-style response.

    Shape: ``{"data":[{"embedding":[float, ...]}, ...]}``. Raises
    :class:`EmbedderError` for any malformed shape (missing/non-list ``data``, a
    non-object entry, a non-list or non-numeric ``embedding``, or a count that
    does not match the ``expected`` input length) so a bad payload is a hard
    error rather than a silent partial result.
    """
    data = response.get("data")
    if not isinstance(data, list):
        raise EmbedderError("embeddings response had no 'data' list")
    vectors: list[list[float]] = []
    for entry in data:
        if not isinstance(entry, dict):
            raise EmbedderError("embeddings data entry was not an object")
        raw_vec = entry.get("embedding")
        if not isinstance(raw_vec, list):
            raise EmbedderError("embeddings entry had no 'embedding' list")
        try:
            vectors.append([float(x) for x in raw_vec])
        except (TypeError, ValueError) as exc:
            raise EmbedderError("embeddings vector held a non-numeric value") from exc
    if len(vectors) != expected:
        raise EmbedderError(f"embeddings returned {len(vectors)} vectors for {expected} inputs")
    return vectors


# --------------------------------------------------------------------------- #
# CloudEmbedder: OpenAI-compatible /v1/embeddings over the injectable transport
# --------------------------------------------------------------------------- #
class CloudEmbedder:
    """An OpenAI-compatible ``/v1/embeddings`` embedder (stdlib urllib transport).

    Used ONLY when ``settings.useCloud`` + a key (the consent + budget gate runs
    upstream in the handlers, WU-A1/A5). Identical transport posture to
    ``provider.CloudProvider`` but on the embeddings path; the bearer key is
    header-only and never logged.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_CLOUD_BASE_URL,
        model: str = DEFAULT_CLOUD_EMBED_MODEL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("CloudEmbedder requires a non-empty api_key")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        if transport is not None:
            self._transport: Transport = transport
        else:
            # Bind the default urllib transport to this embedder's key (via
            # functools.partial, mirroring provider.py) so the error body is
            # scrubbed of the live key at the construction site — and so there is
            # no Python-level closure body line to leave uncovered; the only
            # uncovered line is the real socket itself (pragma'd above).
            self._transport = functools.partial(_urllib_post_json, secrets=(api_key,))

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` via one POST; empty input short-circuits (no socket)."""
        inputs = list(texts)
        if not inputs:
            return []
        url = f"{self.base_url}/embeddings"
        body: dict[str, Any] = {"input": inputs, "model": self.model}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        log.debug("embeddings -> %s (model=%s, %d inputs)", url, self.model, len(inputs))
        response = self._transport(url, body, headers, self.timeout)
        return _parse_embeddings(response, len(inputs))


# --------------------------------------------------------------------------- #
# LocalEmbedder: deterministic, socket-free local backstop (PLAN §WU-A2)
# --------------------------------------------------------------------------- #
class LocalEmbedder:
    """A deterministic local-backstop embedder — no socket, no key, no model file.

    PLAN §WU-A2 names a "deterministic local embedder seam" as the backstop so an
    offline / unconsented index build still produces vectors. This is a
    hashing-based bag-of-words embedding: stable across runs, distinguishes
    distinct texts, unit-normalized (so cosine similarity behaves), and yields a
    zero vector for empty text. It is NOT a semantic model — it is the privacy/
    offline floor (WU-A3 pins a real local embedding asset as the upgrade path).
    """

    def __init__(self, *, dim: int = DEFAULT_LOCAL_EMBED_DIM) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one deterministic unit vector per text (empty text -> zeros)."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in text.split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = sum(x * x for x in vector) ** 0.5
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]


# --------------------------------------------------------------------------- #
# Factory (mirrors provider.get_provider's local/cloud routing)
# --------------------------------------------------------------------------- #
def get_embedder(
    settings: dict[str, Any] | None = None,
    *,
    transport: Transport | None = None,
) -> Embedder:
    """Return the right :class:`Embedder` for ``settings``.

    A :class:`CloudEmbedder` when ``settings.useCloud`` is truthy AND a non-empty
    ``cloudApiKey`` is present; otherwise the deterministic :class:`LocalEmbedder`
    backstop. ``transport`` is forwarded so tests inject a fake HTTP transport.
    The richer per-function provider-pool routing (consent/budget) is composed in
    the handlers (WU-A5); this factory is the simple single-embedder fall-through.
    """
    settings = settings or {}
    api_key = settings.get("cloudApiKey") or ""
    if settings.get("useCloud") and api_key:
        return CloudEmbedder(
            api_key=str(api_key),
            base_url=str(settings.get("cloudBaseUrl") or DEFAULT_CLOUD_BASE_URL),
            model=str(settings.get("cloudEmbedModel") or DEFAULT_CLOUD_EMBED_MODEL),
            transport=transport,
        )
    return LocalEmbedder()
