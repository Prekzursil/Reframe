"""Unit tests for Stripe billing helpers in :mod:`app.billing`."""

from __future__ import annotations

import sys
import types

import pytest

from app import billing as billing_module
from app.billing import (
    BILLING_DISABLED_MESSAGE,
    DEFAULT_PLAN_POLICIES,
    STRIPE_SECRET_KEY_MISSING_MESSAGE,
    build_checkout_session,
    build_customer_portal_session,
    get_plan_policy,
    update_subscription_seat_limit,
)
from app.config import get_settings


# ---------------------------------------------------------------------------
# get_plan_policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["free", "pro", "enterprise"])
def test_get_plan_policy_known_codes(code):
    assert get_plan_policy(code).code == code


def test_get_plan_policy_normalizes_case_and_whitespace():
    assert get_plan_policy("  PRO ").code == "pro"


def test_get_plan_policy_unknown_falls_back_to_free():
    assert get_plan_policy("nope") is DEFAULT_PLAN_POLICIES["free"]
    assert get_plan_policy("") is DEFAULT_PLAN_POLICIES["free"]
    assert get_plan_policy(None).code == "free"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _get_stripe import handling
# ---------------------------------------------------------------------------


def test_get_stripe_returns_module():
    stripe = billing_module._get_stripe()
    assert stripe is not None


def test_get_stripe_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch):
    # Simulate stripe missing by removing it from sys.modules and blocking import.
    monkeypatch.setitem(sys.modules, "stripe", None)
    with pytest.raises(RuntimeError, match="stripe is not installed"):
        billing_module._get_stripe()


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.checkout_kwargs: dict | None = None
        self.modify_args: tuple | None = None
        self.modify_kwargs: dict | None = None
        self.portal_kwargs: dict | None = None


def _make_fake_stripe(recorder: _Recorder) -> types.ModuleType:
    fake = types.ModuleType("stripe")
    fake.api_key = None

    class _CheckoutSession:
        @staticmethod
        def create(**kwargs):
            recorder.checkout_kwargs = kwargs
            return {"id": "cs_123", "url": "https://checkout.example/cs_123"}

    class _Checkout:
        Session = _CheckoutSession

    class _Subscription:
        @staticmethod
        def modify(*args, **kwargs):
            recorder.modify_args = args
            recorder.modify_kwargs = kwargs
            return {}

    class _PortalSession:
        @staticmethod
        def create(**kwargs):
            recorder.portal_kwargs = kwargs
            return {"id": "bps_1", "url": "https://portal.example/bps_1"}

    class _BillingPortal:
        Session = _PortalSession

    fake.checkout = _Checkout()
    fake.Subscription = _Subscription
    fake.billing_portal = _BillingPortal()
    return fake


@pytest.fixture()
def billing_enabled(monkeypatch: pytest.MonkeyPatch):
    """Enable billing with a configured stripe key and inject a fake stripe."""
    recorder = _Recorder()
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    monkeypatch.setenv("REFRAME_STRIPE_SECRET_KEY", "sk_test_123")
    get_settings.cache_clear()
    fake = _make_fake_stripe(recorder)
    monkeypatch.setattr(billing_module, "_get_stripe", lambda: fake)
    yield recorder, fake
    get_settings.cache_clear()


@pytest.fixture()
def billing_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def billing_enabled_no_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    monkeypatch.setenv("REFRAME_STRIPE_SECRET_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# build_checkout_session
# ---------------------------------------------------------------------------


def test_build_checkout_session_disabled(billing_disabled):
    with pytest.raises(RuntimeError, match=BILLING_DISABLED_MESSAGE):
        build_checkout_session(
            customer_id=None,
            price_id="price_1",
            success_url="https://ok",
            cancel_url="https://no",
        )


def test_build_checkout_session_missing_key(billing_enabled_no_key):
    with pytest.raises(RuntimeError, match=STRIPE_SECRET_KEY_MISSING_MESSAGE):
        build_checkout_session(
            customer_id=None,
            price_id="price_1",
            success_url="https://ok",
            cancel_url="https://no",
        )


def test_build_checkout_session_with_customer_and_metadata(billing_enabled):
    recorder, fake = billing_enabled
    result = build_checkout_session(
        customer_id="cus_1",
        price_id="price_pro",
        quantity=3,
        success_url="https://ok",
        cancel_url="https://no",
        metadata={"org": "abc"},
    )
    assert result == {"id": "cs_123", "url": "https://checkout.example/cs_123"}
    assert fake.api_key == "sk_test_123"
    kwargs = recorder.checkout_kwargs
    assert kwargs["mode"] == "subscription"
    assert kwargs["line_items"] == [{"price": "price_pro", "quantity": 3}]
    assert kwargs["customer"] == "cus_1"
    assert kwargs["metadata"] == {"org": "abc"}


def test_build_checkout_session_without_customer_or_metadata_and_quantity_floor(billing_enabled):
    recorder, _ = billing_enabled
    build_checkout_session(
        customer_id=None,
        price_id="price_pro",
        quantity=0,
        success_url="https://ok",
        cancel_url="https://no",
    )
    kwargs = recorder.checkout_kwargs
    # quantity 0 is floored to 1.
    assert kwargs["line_items"] == [{"price": "price_pro", "quantity": 1}]
    assert "customer" not in kwargs
    assert "metadata" not in kwargs


# ---------------------------------------------------------------------------
# update_subscription_seat_limit
# ---------------------------------------------------------------------------


def test_update_subscription_seat_limit_disabled(billing_disabled):
    with pytest.raises(RuntimeError, match=BILLING_DISABLED_MESSAGE):
        update_subscription_seat_limit(subscription_id="sub_1", quantity=2)


def test_update_subscription_seat_limit_missing_key(billing_enabled_no_key):
    with pytest.raises(RuntimeError, match=STRIPE_SECRET_KEY_MISSING_MESSAGE):
        update_subscription_seat_limit(subscription_id="sub_1", quantity=2)


def test_update_subscription_seat_limit_success(billing_enabled):
    recorder, fake = billing_enabled
    update_subscription_seat_limit(subscription_id="sub_1", quantity=5)
    assert fake.api_key == "sk_test_123"
    assert recorder.modify_args == ("sub_1",)
    assert recorder.modify_kwargs == {"items": [{"quantity": 5}]}


def test_update_subscription_seat_limit_quantity_floor(billing_enabled):
    recorder, _ = billing_enabled
    update_subscription_seat_limit(subscription_id="sub_1", quantity=0)
    assert recorder.modify_kwargs == {"items": [{"quantity": 1}]}


# ---------------------------------------------------------------------------
# build_customer_portal_session
# ---------------------------------------------------------------------------


def test_build_customer_portal_session_disabled(billing_disabled):
    with pytest.raises(RuntimeError, match=BILLING_DISABLED_MESSAGE):
        build_customer_portal_session(customer_id="cus_1", return_url="https://back")


def test_build_customer_portal_session_missing_key(billing_enabled_no_key):
    with pytest.raises(RuntimeError, match=STRIPE_SECRET_KEY_MISSING_MESSAGE):
        build_customer_portal_session(customer_id="cus_1", return_url="https://back")


def test_build_customer_portal_session_success(billing_enabled):
    recorder, fake = billing_enabled
    result = build_customer_portal_session(customer_id="cus_1", return_url="https://back")
    assert result == {"id": "bps_1", "url": "https://portal.example/bps_1"}
    assert fake.api_key == "sk_test_123"
    assert recorder.portal_kwargs == {"customer": "cus_1", "return_url": "https://back"}
