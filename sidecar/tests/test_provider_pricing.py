"""WU D4 — real per-request cloud pricing + the honest 'estimate' flag.

The spend ledger stores integer cents but never PRICES a model; the handler
derives the cents estimate. Historically that estimate was a flat 1c/request
placeholder with NO signal it was a stand-in, so the month-to-date readout looked
like a real invoiced charge. :mod:`media_studio.models.provider_pricing` is the
single home that turns a run into cents HONESTLY: a real per-model price when we
can cite one, else the documented placeholder — always flagged as an estimate so
the UI never presents the placeholder as a real charge.
"""

from __future__ import annotations

import pytest
from media_studio.models import provider_pricing as pricing


def test_placeholder_is_non_zero() -> None:
    # A non-zero placeholder is required so an enabled monthly hard cap can trip;
    # a zero rate would make the cap un-trippable.
    assert pricing.PLACEHOLDER_CENTS_PER_REQUEST > 0


def test_real_price_table_is_empty_today() -> None:
    # Every curated catalog model is FREE/FREEMIUM with no published per-request
    # price, so the real table is HONESTLY empty — every estimate is a placeholder.
    assert pricing.PRICE_CENTS_PER_REQUEST == {}


def test_unknown_model_falls_back_to_placeholder() -> None:
    assert pricing.request_cents("some-unpriced-model") == pricing.PLACEHOLDER_CENTS_PER_REQUEST


def test_none_model_falls_back_to_placeholder() -> None:
    assert pricing.request_cents(None) == pricing.PLACEHOLDER_CENTS_PER_REQUEST


def test_known_model_uses_the_real_price(monkeypatch: pytest.MonkeyPatch) -> None:
    # When a real per-request price is confirmed and added to the table, it is used
    # verbatim instead of the placeholder (proves the real-price branch).
    monkeypatch.setitem(pricing.PRICE_CENTS_PER_REQUEST, "priced-model", 7)
    assert pricing.request_cents("priced-model") == 7


def test_is_estimated_true_for_unpriced_model() -> None:
    assert pricing.is_estimated("some-unpriced-model") is True


def test_is_estimated_true_for_none_model() -> None:
    assert pricing.is_estimated(None) is True


def test_is_estimated_false_for_known_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pricing.PRICE_CENTS_PER_REQUEST, "priced-model", 7)
    assert pricing.is_estimated("priced-model") is False


def test_spend_is_estimated_true_while_table_empty() -> None:
    # The month-to-date figure is derived from placeholder pricing as long as ANY
    # routable model lacks a real price — which is every model today.
    assert pricing.spend_is_estimated() is True


def test_spend_is_estimated_false_only_when_a_real_price_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pricing.PRICE_CENTS_PER_REQUEST, "priced-model", 7)
    assert pricing.spend_is_estimated() is False
