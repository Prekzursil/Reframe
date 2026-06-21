"""Persisted month-keyed cumulative spend ledger (WU-spend-cap).

The per-run budget gate (``models.budget`` + ``handlers._enforce_cloud_budget_ack``)
answers "does THIS run fit?", but nothing remembers what earlier approved runs
already cost — so many small cloud-AI jobs accumulate unbounded spend across a
month. This module is the persisted memory that closes that gap: a single JSON
document, keyed by calendar month (``"YYYY-MM"``), holding the cumulative cost in
**integer cents** for each month.

  * :func:`month_key` derives the ``"YYYY-MM"`` bucket for a unix timestamp (UTC,
    so the month boundary is stable regardless of the host timezone).
  * :class:`SpendLedger` records each cloud-AI job's actual-or-estimated cost at
    COMPLETION (:meth:`record`) and answers month-to-date spend
    (:meth:`month_to_date`). The clock is injected so tests are deterministic; the
    file round-trips atomically (temp + ``os.replace``) and a corrupt/missing/
    malformed file degrades to an empty ledger rather than crashing — mirroring
    :class:`settings_store.SettingsStore`.

Pure logic + filesystem I/O only: NO heavy-ML imports, NO network, NO provider.
The cost VALUE is supplied by the caller (the handler derives a cents estimate);
this module never prices a model — it only stores and sums what it is given.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.spend_ledger")

#: The on-disk document version (future-proofing; readers tolerate its absence).
_LEDGER_VERSION = 1

#: DOCUMENTED PLACEHOLDER rate: the nominal cost (in cents) attributed to a single
#: cloud-AI request when the catalog carries no structured numeric price (every
#: curated model today is FREE/FREEMIUM with only a human ``free_limits`` string —
#: see ``ai_job.CatalogFreeCapAdapter``). The monthly cap needs a NON-ZERO per-job
#: cost or an enabled hard cap could never trip; this constant is that falsifiable
#: stand-in (mirrors ``budget.DEFAULT_TARGET_JOB_SIZE``). Replace it with a real
#: per-model price once the catalog gains structured pricing; do not scatter the
#: magic number into callers — derive every job estimate from this one place.
PLACEHOLDER_CENTS_PER_REQUEST: int = 1


def month_key(now_seconds: float) -> str:
    """The ``"YYYY-MM"`` calendar-month bucket for a unix timestamp (UTC).

    UTC is used deliberately so the month boundary is identical across hosts and
    does not drift with the local timezone or DST — the ledger is a stable,
    machine-independent record.
    """
    moment = _dt.datetime.fromtimestamp(now_seconds, tz=_dt.UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


class SpendLedger:
    """A JSON-backed, month-keyed cumulative spend store (integer cents).

    The document shape is ``{"version": 1, "months": {"YYYY-MM": <cents:int>}}``.
    ``record`` folds a cost into a month's running total; ``month_to_date`` reads
    one month's total (defaulting to the clock's current month). The clock is an
    injected ``() -> float`` seam (defaults to :func:`time.time`).
    """

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock: Callable[[], float] = clock or time.time

    # ---- I/O ---------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        """Load the ledger document, degrading any read failure to ``{}``.

        A missing file, unreadable file, invalid JSON, or non-object payload all
        yield an empty document so a corrupt ledger can never brick a job — the
        next :meth:`record` simply rewrites a clean file.
        """
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("spend ledger unreadable (%s); using empty ledger", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically persist ``data`` (temp file + ``os.replace``)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _months(data: dict[str, Any]) -> dict[str, Any]:
        """The ``months`` sub-map, tolerating its absence / a non-dict value."""
        months = data.get("months")
        return months if isinstance(months, dict) else {}

    # ---- public surface ----------------------------------------------------
    def current_month(self) -> str:
        """The clock's current ``"YYYY-MM"`` month bucket."""
        return month_key(self._clock())

    def month_to_date(self, now_month: str | None = None) -> int:
        """Cumulative spend (cents) for ``now_month`` (defaults to this month).

        A month with no recorded spend — or a stored value that is not a finite
        number — reads as ``0``.
        """
        month = now_month if now_month is not None else self.current_month()
        value = self._months(self._read()).get(month)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return int(value)

    def record(self, cost_cents: float, month: str | None = None) -> int:
        """Add ``cost_cents`` to ``month``'s running total; return the new total.

        ``month`` defaults to the clock's current month. The cost is coerced to a
        non-negative integer (cents are whole-number money; a negative cost is a
        programming error and raises ``ValueError``). The fold is read-modify-write
        against the persisted document so concurrent instances each see the latest
        on-disk total.
        """
        cents = int(cost_cents)
        if cents < 0:
            raise ValueError("spend cost must be non-negative")
        target = month if month is not None else self.current_month()
        data = self._read()
        months = dict(self._months(data))
        previous = months.get(target)
        prior = int(previous) if isinstance(previous, (int, float)) and not isinstance(previous, bool) else 0
        new_total = prior + cents
        months[target] = new_total
        data["version"] = _LEDGER_VERSION
        data["months"] = months
        self._write(data)
        return new_total


__all__ = ["SpendLedger", "month_key"]
