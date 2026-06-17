"""Per-key usage accounting model + cache merge/stale logic (PLAN §WU-usage-ui).

The rotation pool (``provider.RotatingProvider.usage``) already produces per-key
usage rows ``{provider, key(redacted), used, max, unit, resetAt}`` from optimistic
decrement + parsed ``X-RateLimit-*`` headers — there is NO poller. This module is
the small PURE half WU-usage-ui adds on top:

  * :class:`UsageUnit` — the REQ/TOKEN limit dimension. Req-limited and
    token-limited keys are NEVER summed (DESIGN §13); the renderer groups by unit
    and the budget/UI read the canonical string off this enum.
  * :func:`merge_usage_cache` — fold a freshly-read pool snapshot over the
    persisted (timestamped) cache so the UI shows immediately on launch
    (DESIGN §15-Q1) without re-polling. A live row with real counts (``used`` or
    ``max`` known) supersedes a stale cached row; a freshly-built pool (all-zero,
    no ``max``) does NOT clobber a cached row that carried real numbers.
  * :func:`flag_stale` — stamp each row with ``lastCheckedAt`` + ``stale`` from a
    wall-clock ``now`` and the >10-min threshold; the renderer desaturates stale
    bars and shows "last checked Xm ago".

Pure data + arithmetic only — no I/O, no heavy imports. The handler owns the pool
read, the settings persistence, and the ``now`` seam.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

#: Usage older than this many seconds is flagged ``stale`` (DESIGN §15-Q1: 10 min).
STALE_AFTER_SECONDS: float = 10 * 60.0


class UsageUnit(StrEnum):
    """The limit dimension a key's quota is measured in (DESIGN §13).

    ``REQ`` = request-count limited; ``TOKEN`` = token limited. The two are
    DISTINCT dimensions and are never summed into one bar — the renderer groups
    by unit. Subclassing ``str`` keeps the wire/JSON value the plain lowercase
    string the pool/catalog already emit (``"req"`` / ``"token"``).
    """

    REQ = "req"
    TOKEN = "token"

    @classmethod
    def coerce(cls, value: Any) -> UsageUnit:
        """Map any wire string onto a :class:`UsageUnit` (unknown -> ``REQ``).

        The catalog/pool store the unit as a free string; this normalizes it so
        the grouping is total. Anything that is not a recognized token-unit falls
        back to ``REQ`` (the safe per-request default).
        """
        text = str(value).strip().lower()
        return cls.TOKEN if text == cls.TOKEN.value else cls.REQ


def _row_key(row: dict[str, Any]) -> tuple[str, str]:
    """The identity of a usage row: ``(provider, redacted-key)``."""
    return (str(row.get("provider", "")), str(row.get("key", "")))


def _has_real_data(row: dict[str, Any]) -> bool:
    """True iff a row carries real accounting (a nonzero ``used`` or a known ``max``).

    A freshly-built pool reports ``used == 0`` and ``max is None`` for every key
    (the in-memory counters reset each process); such a row must NOT clobber a
    persisted cache row that recorded real numbers from an earlier run.
    """
    used = row.get("used")
    has_used = isinstance(used, (int, float)) and used > 0
    return bool(has_used or row.get("max") is not None)


def merge_usage_cache(
    live_rows: list[dict[str, Any]],
    cached_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fold ``live_rows`` over ``cached_rows`` (keyed by provider+redacted-key).

    A live row with real data wins; an all-zero live row keeps the cached numbers
    (but always carries the live row's identity/unit). Cached-only rows (a key no
    longer in the live pool) are dropped — the pool is the source of truth for
    which keys exist. Output order follows ``live_rows``.
    """
    by_key = {_row_key(row): row for row in cached_rows}
    merged: list[dict[str, Any]] = []
    for live in live_rows:
        cached = by_key.get(_row_key(live))
        if cached is not None and not _has_real_data(live) and _has_real_data(cached):
            row = {**live, "used": cached.get("used", live.get("used")), "max": cached.get("max")}
            if cached.get("resetAt") is not None:
                row["resetAt"] = cached.get("resetAt")
        else:
            row = dict(live)
        merged.append(row)
    return merged


def flag_stale(
    rows: list[dict[str, Any]],
    *,
    now: float,
    checked_at: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Stamp ``lastCheckedAt`` + ``stale`` on each row from ``now`` + the threshold.

    ``checked_at`` maps a row's ``(provider, key)`` (joined by ``"\\x00"``) to the
    wall-clock it was last observed; a row absent from the map is treated as
    just-observed (``now``, fresh). A row whose age exceeds
    :data:`STALE_AFTER_SECONDS` is flagged ``stale`` so the bar desaturates.
    """
    stamps = checked_at or {}
    out: list[dict[str, Any]] = []
    for row in rows:
        ident = "\x00".join(_row_key(row))
        last = stamps.get(ident, now)
        out.append({**row, "lastCheckedAt": last, "stale": (now - last) > STALE_AFTER_SECONDS})
    return out
