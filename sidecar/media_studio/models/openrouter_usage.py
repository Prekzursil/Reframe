"""OpenRouter per-key COST/credit usage (WU-models/device, deliverable G-2).

The rotation pool's :meth:`provider.RotatingProvider.usage` already surfaces per-key
*request*/*token* quota from parsed ``X-RateLimit-*`` headers (the "calls" axis) —
but it has no notion of spend. OpenRouter, uniquely, exposes a cheap authenticated
``GET /api/v1/key`` that reports the key's cumulative **credit usage (USD)** and
remaining limit. This module turns that endpoint into per-key cost rows for the
"Providers & Keys" usage panel, so the user sees *cost* alongside *calls/tokens*.

Design (mirrors :mod:`local_detect`):
  * PURE + import-light: the HTTP call goes through the SAME injectable
    :data:`provider.Transport` seam, so **no socket is ever opened under test**.
  * Best-effort + key-safe: a key that errors is silently skipped (never raised),
    and the row carries ONLY the REDACTED last-4 — a live key is never logged,
    never returned, and is sent ONLY in the ``Authorization: Bearer`` header.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..util import get_logger
from . import key_pool_status
from .provider import ProviderError, Transport
from .secrets import redact, scrub_error_body

log = get_logger("media_studio.models.openrouter_usage")

#: OpenRouter's authenticated key-status endpoint (cumulative credit usage in USD).
OPENROUTER_KEY_URL: str = "https://openrouter.ai/api/v1/key"

#: How OpenRouter is recognised among the configured providers (any one matches).
_OPENROUTER_HOST: str = "openrouter.ai"
_OPENROUTER_IDS: frozenset[str] = frozenset({"openrouter"})

#: Probe timeout (seconds) — a status read should answer fast or be skipped.
_PROBE_TIMEOUT: float = 4.0


class OpenRouterUsageRow(TypedDict):
    """One OpenRouter key's cost row for the key-pool UI (no live key, ever).

    ``status`` is ``active`` or ``cooldown`` (M4); a parked key is NEVER deleted
    (cooldown-not-delete) — it stays in the pool with ``cooldownReason`` set so the
    user sees *why* it parked (402/429, or the free-tier <10-credit cap).
    """

    provider: str
    key: str  # REDACTED last-4 only
    costUsd: float | None
    limitUsd: float | None
    remainingUsd: float | None
    isFreeTier: bool
    status: str
    cooldownReason: str | None


def _as_float(value: Any) -> float | None:
    """Coerce a wire number to ``float``, or ``None`` for missing/garbage/bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_key_usage(response: dict[str, Any]) -> dict[str, Any]:
    """Parse OpenRouter ``GET /api/v1/key`` into ``{costUsd, limitUsd, remainingUsd, isFreeTier}``.

    Shape: ``{"data": {"usage": <usd>, "limit": <usd|null>,
    "limit_remaining": <usd|null>, "is_free_tier": <bool>}}``. A missing/garbage
    ``data`` block, or any non-numeric field, degrades that field to ``None``
    (``isFreeTier`` to ``False``) rather than raising — a partial answer is still
    useful, a malformed one is not fatal.
    """
    data = response.get("data")
    if not isinstance(data, dict):
        return {"costUsd": None, "limitUsd": None, "remainingUsd": None, "isFreeTier": False}
    return {
        "costUsd": _as_float(data.get("usage")),
        "limitUsd": _as_float(data.get("limit")),
        "remainingUsd": _as_float(data.get("limit_remaining")),
        "isFreeTier": bool(data.get("is_free_tier")),
    }


def is_openrouter(entry: dict[str, Any]) -> bool:
    """Whether a configured provider entry is OpenRouter (by base URL or id/name)."""
    base_url = str(entry.get("baseUrl") or "").lower()
    if _OPENROUTER_HOST in base_url:
        return True
    identity = str(entry.get("provider") or entry.get("id") or "").strip().lower()
    return identity in _OPENROUTER_IDS


def _provider_name(entry: dict[str, Any]) -> str:
    """The display provider name for the row (falls back to id, then 'OpenRouter')."""
    return str(entry.get("provider") or entry.get("id") or "OpenRouter")


def _cooldown_row(provider: str, key: str, reason: str) -> OpenRouterUsageRow:
    """A REDACTED cooldown row for a parked key (cost unknown; M4 cooldown-not-delete)."""
    return OpenRouterUsageRow(
        provider=provider,
        key=redact(key),
        costUsd=None,
        limitUsd=None,
        remainingUsd=None,
        isFreeTier=False,
        status=key_pool_status.STATUS_COOLDOWN,
        cooldownReason=reason,
    )


def _fetch_one(provider: str, key: str, *, transport: Transport) -> OpenRouterUsageRow | None:
    """Fetch ONE key's cost/status row (best-effort). The live key rides only the header.

    On a ``402``/``429`` the key is PARKED on cooldown (a row is still returned —
    M4 cooldown-not-delete), so the user sees *why* it stopped serving. Any other
    failure (bad-key ``401`` / network) returns ``None`` so a single dead key never
    breaks the whole read. The probe error body is SCRUBBED of the live key BEFORE
    it reaches a log line (M4), and the returned row's ``key`` is the REDACTED
    last-4 — the live key never leaves this function.
    """
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = transport(OPENROUTER_KEY_URL, {}, headers, _PROBE_TIMEOUT)
    except ProviderError as exc:
        safe = scrub_error_body(str(exc), [key])
        reason = key_pool_status.cooldown_reason_for_code(exc.status_code)
        if reason is not None:
            log.debug("OpenRouter key %s parked on cooldown: %s", redact(key), safe)
            return _cooldown_row(provider, key, reason)
        log.debug("OpenRouter usage probe failed for %s (%s): %s", provider, redact(key), safe)
        return None
    except Exception as exc:  # noqa: BLE001 - best-effort, must not raise
        log.debug(
            "OpenRouter usage probe failed for %s (%s): %s", provider, redact(key), scrub_error_body(str(exc), [key])
        )
        return None
    parsed = parse_key_usage(response)
    status, reason = key_pool_status.classify_success(parsed)
    return OpenRouterUsageRow(
        provider=provider,
        key=redact(key),
        costUsd=parsed["costUsd"],
        limitUsd=parsed["limitUsd"],
        remainingUsd=parsed["remainingUsd"],
        isFreeTier=parsed["isFreeTier"],
        status=status,
        cooldownReason=reason,
    )


def fetch_usage(providers: list[dict[str, Any]], *, transport: Transport) -> list[OpenRouterUsageRow]:
    """Per-key OpenRouter cost rows from the configured (RAW-keyed) providers.

    Scans ``providers`` for OpenRouter entries (:func:`is_openrouter`), probes
    ``GET /api/v1/key`` per RAW key through the injected ``transport``, and returns
    one cost row per key that answered. Non-OpenRouter entries, keyless entries,
    and dead keys are skipped — the function returns ``[]`` (never raises) when
    nothing is available. No live key is ever returned (rows carry last-4 only).
    """
    rows: list[OpenRouterUsageRow] = []
    for entry in providers:
        if not isinstance(entry, dict) or not is_openrouter(entry):
            continue
        provider = _provider_name(entry)
        for raw_key in entry.get("apiKeys") or []:
            key = str(raw_key)
            if not key:
                continue
            row = _fetch_one(provider, key, transport=transport)
            if row is not None:
                rows.append(row)
    return rows


__all__ = [
    "OPENROUTER_KEY_URL",
    "OpenRouterUsageRow",
    "fetch_usage",
    "is_openrouter",
    "parse_key_usage",
]
