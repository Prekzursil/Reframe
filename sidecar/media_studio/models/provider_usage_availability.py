"""Honest per-provider usage-API availability (WU-D4 — no fabricated numbers).

The LOCAL request/token counters (``provider.RotatingProvider.usage``) are always
surfaced, and OpenRouter uniquely exposes a per-KEY cost endpoint reachable with a
normal stored key (``GET /api/v1/key`` — see :mod:`openrouter_usage`). Every OTHER
cloud provider either gates usage behind an ORGANIZATION ADMIN key that a stored
project key cannot use (OpenAI's ``/v1/organization/usage`` needs an ``sk-admin``
key; Anthropic's ``/v1/organizations/usage_report`` needs an ``sk-ant-admin`` key)
or publishes no per-key usage endpoint at all.

Rather than invent a 0 (or reuse the 1c/request placeholder) for those providers,
:func:`usage_availability` states the truth: one row per configured cloud provider
saying whether a provider-side usage API exists and, when it does not, an honest
"Usage API not available for <provider>" message the UI shows verbatim.

Pure classification over the configured (RAW-keyed) provider entries — it reads no
keys and returns none (rows carry the provider display name only, never a key).
"""

from __future__ import annotations

from typing import Any, TypedDict

from . import openrouter_usage as _oru
from .provider import LOCAL_PROVIDER_ID


class UsageAvailabilityRow(TypedDict):
    """One provider's provider-side-usage-API availability (never carries a key)."""

    provider: str
    hasUsageApi: bool
    message: str


#: Host / id fragments for the admin-key-gated providers, with the phrase naming
#: the credential their usage API actually requires (so the note is specific, not
#: a hand-wave). Matched against the entry's base-url host and its id/name.
_ADMIN_KEY_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("api.openai.com", "openai"),
    ("api.anthropic.com", "anthropic"),
)


def _provider_name(entry: dict[str, Any]) -> str:
    """The display provider name for a row (falls back to id)."""
    return str(entry.get("provider") or entry.get("id") or "")


def _is_local(entry: dict[str, Any]) -> bool:
    """Whether an entry is the local backstop (no provider-side usage API applies)."""
    identity = str(entry.get("provider") or entry.get("id") or "").strip().lower()
    return str(entry.get("kind") or "").strip().lower() == "local" or identity == LOCAL_PROVIDER_ID


def _needs_admin_key(entry: dict[str, Any]) -> bool:
    """Whether this provider's usage API is gated behind an organization admin key."""
    base_url = str(entry.get("baseUrl") or "").lower()
    identity = str(entry.get("provider") or entry.get("id") or "").strip().lower()
    return any(host in base_url or ident == identity for host, ident in _ADMIN_KEY_PROVIDERS)


def _classify(entry: dict[str, Any]) -> UsageAvailabilityRow:
    """Classify ONE configured cloud entry into an honest availability row."""
    name = _provider_name(entry)
    if _oru.is_openrouter(entry):
        return UsageAvailabilityRow(
            provider=name,
            hasUsageApi=True,
            message=f"Live per-key credit usage is available from {name}.",
        )
    if _needs_admin_key(entry):
        return UsageAvailabilityRow(
            provider=name,
            hasUsageApi=False,
            message=f"Usage API not available for {name} without an organization admin key.",
        )
    return UsageAvailabilityRow(
        provider=name,
        hasUsageApi=False,
        message=f"Usage API not available for {name}.",
    )


def usage_availability(providers: list[Any]) -> list[UsageAvailabilityRow]:
    """One honest availability row per configured CLOUD provider (deduped, in order).

    Skips non-dict entries, entries with no id/name, and the local backstop (which
    has no provider-side usage API to speak of). Multiple keys for the same
    provider collapse to a single row. No key is ever read or returned.
    """
    rows: list[UsageAvailabilityRow] = []
    seen: set[str] = set()
    for entry in providers:
        if not isinstance(entry, dict) or _is_local(entry):
            continue
        name = _provider_name(entry)
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(_classify(entry))
    return rows


__all__ = ["UsageAvailabilityRow", "usage_availability"]
