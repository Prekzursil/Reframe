"""Local OpenAI-compatible server detection (WU-pool · PH5).

Pure, import-light detection of the two well-known *local* LLM servers a user is
likely to already be running — **Ollama** (``http://127.0.0.1:11434/v1``) and
**LM Studio** (``http://127.0.0.1:1234/v1``) — so the rotation pool can slot them
in as additional OpenAI-compatible providers (a local backstop richer than just
llama.cpp). Each server is probed with a ``GET /models`` call through the SAME
injectable :data:`~media_studio.models.provider.Transport` seam the provider
module uses, so **no socket is ever opened under test** (the transport is a fake).

Design rules (PLAN §WU-pool):
  * Detection is **best-effort and never fatal**: a connection error, an absent
    server, or a probe that returns no usable model id simply yields *no* entry
    for that server — :func:`detect_local_servers` NEVER raises. ("detection
    failure degrades silently to no extra providers.")
  * The module is **import-light and sleep-free**: it imports neither ``time``
    nor ``asyncio`` (mirrors the provider hot-path no-sleep rule), so there is no
    wall-clock dependency and nothing to ``# pragma`` for coverage.
  * The returned :class:`PoolEntry` is a light dict the pool consumes verbatim —
    ``{id, kind, base_url, model, capabilities, unit}``.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..util import get_logger
from .provider import Transport

log = get_logger("media_studio.models.local_detect")

# --------------------------------------------------------------------------- #
# Well-known local server endpoints (overridable via settings)
# --------------------------------------------------------------------------- #
#: Ollama's OpenAI-compatible base URL (``ollama serve`` default port).
OLLAMA_BASE_URL: str = "http://127.0.0.1:11434/v1"
#: LM Studio's OpenAI-compatible base URL (local server default port).
LM_STUDIO_BASE_URL: str = "http://127.0.0.1:1234/v1"

#: Probe timeout (seconds). Short by design: a local server answers instantly, and
#: an absent one should fail fast rather than stall startup detection.
_PROBE_TIMEOUT: float = 2.0


class PoolEntry(TypedDict):
    """A light pool-entry shape the rotation pool consumes (PLAN §WU-pool).

    ``kind`` is the server family (``"ollama"`` / ``"lmstudio"``); ``unit`` is the
    rate-limit unit (local servers are request-bounded, so ``"req"``);
    ``capabilities`` lists what the entry can do (local detect = ``["chat"]``).
    """

    id: str
    kind: str
    base_url: str
    model: str
    capabilities: list[str]
    unit: str


def _first_model_id(response: dict[str, Any]) -> str | None:
    """Return the first model id from an OpenAI-style ``/models`` response.

    Shape: ``{"data": [{"id": "...", ...}, ...]}``. Returns ``None`` when the
    response is not that shape, the list is empty, the first entry is not an
    object, or its ``id`` is missing/blank — i.e. "this is not a usable server".
    """
    data = response.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    model_id = first.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    return model_id


def _probe_server(
    *, kind: str, base_url: str, transport: Transport
) -> PoolEntry | None:
    """Probe one local server's ``GET /models`` endpoint; build a :class:`PoolEntry`.

    Returns ``None`` (and logs at debug) when the server is absent, errors, or
    reports no usable model id. Any transport exception is swallowed — detection
    is best-effort and must never crash the caller.
    """
    url = f"{base_url}/models"
    try:
        response = transport(url, {}, {}, _PROBE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - best-effort probe, must not raise
        log.debug("local server %s not detected at %s: %s", kind, base_url, exc)
        return None
    model_id = _first_model_id(response)
    if model_id is None:
        log.debug("local server %s at %s reported no usable model", kind, base_url)
        return None
    return PoolEntry(
        id=kind,
        kind=kind,
        base_url=base_url,
        model=model_id,
        capabilities=["chat"],
        unit="req",
    )


def detect_local_servers(
    settings: dict[str, Any] | None,
    *,
    transport: Transport,
) -> list[PoolEntry]:
    """Detect locally-running Ollama / LM Studio servers as pool entries.

    Probes each server's ``GET /models`` via the injected ``transport`` and
    returns a :class:`PoolEntry` for every one that answers with a usable model.
    A server that is down, errors, or reports nothing is silently skipped — the
    function returns ``[]`` (never raises) when no local server is found.

    ``settings`` may override the probe URLs via ``ollamaBaseUrl`` /
    ``lmStudioBaseUrl`` (a blank/missing value falls back to the default port).
    """
    settings = settings or {}
    targets = (
        ("ollama", str(settings.get("ollamaBaseUrl") or OLLAMA_BASE_URL)),
        ("lmstudio", str(settings.get("lmStudioBaseUrl") or LM_STUDIO_BASE_URL)),
    )
    entries: list[PoolEntry] = []
    for kind, base_url in targets:
        entry = _probe_server(kind=kind, base_url=base_url, transport=transport)
        if entry is not None:
            entries.append(entry)
    return entries
