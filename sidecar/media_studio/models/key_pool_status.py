"""Per-key cooldown classification for the OpenRouter key pool (M4).

PURE + dependency-free: turns one probe outcome into the key's pool ``status``
(``active`` / ``cooldown``) and a human ``reason``. A parked key is marked
``cooldown`` — it is NEVER deleted (M4 "cooldown-not-delete"), so the user keeps
seeing *why* it parked and it re-activates on its own once the condition clears.

Cooldown triggers (DESIGN §2.2):
  * a ``402`` (insufficient credits) or ``429`` (rate-limited) response from the
    ``GET /api/v1/key`` probe, and
  * the free-tier rule — an ``is_free_tier`` key whose remaining credit has
    fallen below the **10-credit floor** is capped at 50 ``:free`` requests/day,
    so it is surfaced as a cooldown with that cap as the reason.

Anything else stays ``active``. This module imports NOTHING from the rest of
``models/`` so the rule is provable in isolation.
"""

from __future__ import annotations

from typing import Any

#: A key that can serve requests right now.
STATUS_ACTIVE: str = "active"

#: A key parked (NOT deleted) until its cooldown condition clears.
STATUS_COOLDOWN: str = "cooldown"

#: Free-tier accounts (under 10 purchased credits) are capped at 50 ``:free``
#: requests/day; a free key with remaining credit below this floor is parked.
FREE_TIER_CREDIT_FLOOR: float = 10.0

#: HTTP error codes that park a key, mapped to the user-facing cooldown reason.
_COOLDOWN_REASONS: dict[int, str] = {
    402: "out of credits (HTTP 402) — top up to resume",
    429: "rate-limited (HTTP 429) — cooling down before retry",
}

#: The free-tier-cap cooldown reason (surfaced so the user sees why it parked).
FREE_CAP_REASON: str = "free tier under 10 credits — capped at 50 :free requests/day (add ≥10 credits to lift)"


def cooldown_reason_for_code(code: int | None) -> str | None:
    """The cooldown reason for an HTTP error ``code``, or ``None`` if it doesn't park a key.

    Only ``402`` / ``429`` park a key; any other code (e.g. ``401`` for a bad key,
    or ``None`` for a non-HTTP failure) returns ``None`` so the caller treats it as
    a connectivity/config error, NOT a recoverable cooldown.
    """
    if code is None:
        return None
    return _COOLDOWN_REASONS.get(code)


def free_cap_reason(*, is_free_tier: bool, remaining_usd: float | None) -> str | None:
    """The free-tier-cap reason when a free key has under 10 credits left, else ``None``.

    Returns :data:`FREE_CAP_REASON` only for an ``is_free_tier`` key whose KNOWN
    remaining credit is below :data:`FREE_TIER_CREDIT_FLOOR`. A paid key, or a free
    key with unknown (``None``) or sufficient remaining credit, returns ``None``.
    """
    if is_free_tier and remaining_usd is not None and remaining_usd < FREE_TIER_CREDIT_FLOOR:
        return FREE_CAP_REASON
    return None


def classify_success(parsed: dict[str, Any]) -> tuple[str, str | None]:
    """``(status, reason)`` for a SUCCESSFUL probe: free-cap cooldown vs active.

    ``parsed`` is the :func:`openrouter_usage.parse_key_usage` shape. A free key
    below the credit floor is parked (cooldown + reason); everything else is
    ``active`` with no reason.
    """
    reason = free_cap_reason(
        is_free_tier=bool(parsed.get("isFreeTier")),
        remaining_usd=parsed.get("remainingUsd"),
    )
    if reason is not None:
        return STATUS_COOLDOWN, reason
    return STATUS_ACTIVE, None


__all__ = [
    "FREE_CAP_REASON",
    "FREE_TIER_CREDIT_FLOOR",
    "STATUS_ACTIVE",
    "STATUS_COOLDOWN",
    "classify_success",
    "cooldown_reason_for_code",
    "free_cap_reason",
]
