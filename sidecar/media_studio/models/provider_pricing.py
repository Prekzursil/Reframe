"""Real per-request cloud pricing + the honest "this is an estimate" flag (WU-D4).

The spend ledger stores integer cents but never PRICES a model — the handler
derives a cents estimate and hands it in. Historically that estimate was a flat
1c/request fallback with NO signal it was a stand-in, so the month-to-date
readout looked like a real invoiced amount. This module is the single home that
turns a run into cents HONESTLY:

  * :data:`PRICE_CENTS_PER_REQUEST` — a real per-model price table, populated ONLY
    with prices we can actually cite. Every curated catalog model today is
    FREE/FREEMIUM with no published per-request price (pricing is per-TOKEN, not
    per-request), so the table is HONESTLY empty and every estimate falls back to
    the stand-in.
  * :data:`PLACEHOLDER_CENTS_PER_REQUEST` — the documented non-zero stand-in used
    when no real price is known. Non-zero so an enabled monthly hard cap can still
    trip; it is NEVER presented as a real charge (see :func:`is_estimated`).
  * :func:`request_cents` / :func:`is_estimated` / :func:`spend_is_estimated` —
    the per-model price, whether a per-model cost is a stand-in, and whether the
    aggregate spend figure is estimate-derived (so the UI can label it honestly).

Pure arithmetic + a static table: NO I/O, NO network, NO catalog import (avoids a
cycle). When real pricing is confirmed, add ``"model-id": cents`` entries here —
do not scatter the magic number into callers; every estimate derives from here.
"""

from __future__ import annotations

#: DOCUMENTED STAND-IN rate (cents) for one cloud request when no real per-model
#: price is known. Non-zero so an enabled monthly hard cap can trip; flagged as an
#: estimate by :func:`is_estimated` so it is NEVER shown as a real charge.
PLACEHOLDER_CENTS_PER_REQUEST: int = 1

#: Real per-request price (cents) keyed by model id, populated ONLY with prices we
#: can cite. Empty today: every curated model is free/freemium with no published
#: per-request price. Add ``"model-id": cents`` as real pricing is confirmed.
PRICE_CENTS_PER_REQUEST: dict[str, int] = {}


def request_cents(model: str | None) -> int:
    """The per-request cost (cents) for ``model``: a real price if known, else the stand-in."""
    if isinstance(model, str):
        price = PRICE_CENTS_PER_REQUEST.get(model)
        if price is not None:
            return price
    return PLACEHOLDER_CENTS_PER_REQUEST


def is_estimated(model: str | None) -> bool:
    """True when ``model``'s cost is the STAND-IN (no real price) — label it an estimate."""
    return not (isinstance(model, str) and model in PRICE_CENTS_PER_REQUEST)


def spend_is_estimated() -> bool:
    """True while the aggregate spend figure is derived from stand-in pricing.

    The month-to-date total is an estimate as long as we hold NO real per-request
    price at all (every model falls back to the stand-in). Once even one real
    price is confirmed, the aggregate is no longer purely stand-in-derived.
    """
    return not PRICE_CENTS_PER_REQUEST


__all__ = [
    "PLACEHOLDER_CENTS_PER_REQUEST",
    "PRICE_CENTS_PER_REQUEST",
    "is_estimated",
    "request_cents",
    "spend_is_estimated",
]
