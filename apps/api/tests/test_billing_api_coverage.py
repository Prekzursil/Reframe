"""Branch-coverage tests for :mod:`app.billing_api` routes and webhook handlers."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from app import billing_api
from app.config import get_settings
from app.database import get_engine
from app.models import InvoiceSnapshot, Organization, Subscription


def _register(client, *, email: str, organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": "Password123!"}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _enable_billing(monkeypatch, *, webhook_secret: str = "") -> None:
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    monkeypatch.setenv("REFRAME_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_ENTERPRISE", "price_enterprise")
    monkeypatch.setenv("REFRAME_STRIPE_WEBHOOK_SECRET", webhook_secret)
    get_settings.cache_clear()


def _set_subscription_stripe_ids(org_id: str, *, customer_id="", subscription_id="") -> None:
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(select(Subscription).where(Subscription.org_id == UUID(org_id))).first()
        assert sub is not None
        sub.stripe_customer_id = customer_id
        sub.stripe_subscription_id = subscription_id
        session.add(sub)
        session.commit()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_price_to_plan_code(monkeypatch):
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_ENTERPRISE", "price_ent")
    get_settings.cache_clear()
    settings = get_settings()
    assert billing_api._price_to_plan_code("price_ent", settings) == "enterprise"
    assert billing_api._price_to_plan_code("price_pro", settings) == "pro"
    assert billing_api._price_to_plan_code("price_unknown", settings) == "free"
    assert billing_api._price_to_plan_code("", settings) == "free"


def test_unix_to_datetime():
    assert billing_api._unix_to_datetime(None) is None
    assert billing_api._unix_to_datetime("not-a-number") is None
    assert billing_api._unix_to_datetime(0) is None
    assert billing_api._unix_to_datetime(-5) is None
    dt = billing_api._unix_to_datetime(1_709_000_000)
    assert dt is not None and dt.year == 2024


def test_require_billing_enabled_raises_when_disabled(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "false")
    get_settings.cache_clear()
    try:
        billing_api._require_billing_enabled()
        raise AssertionError("expected ApiError")
    except billing_api.ApiError as exc:
        assert exc.status_code == 400
    get_settings.cache_clear()


def test_apply_seat_limit_branches():
    # org None -> no-op; value None -> no-op.
    billing_api._apply_seat_limit(session=None, org=None, value=5)  # type: ignore[arg-type]


def test_apply_seat_limit_swallows_bad_value(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="badseat@team.test", organization_name="Bad Seat Org")
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(user["org_id"]))
        before = org.seat_limit
        # A non-int value triggers the TypeError/ValueError except branch (kept unchanged).
        billing_api._apply_seat_limit(session, org, "not-a-number")
        session.refresh(org)
        assert org.seat_limit == before


def test_apply_seat_limit_sets_value(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="goodseat@team.test", organization_name="Good Seat Org")
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(user["org_id"]))
        billing_api._apply_seat_limit(session, org, 0)  # max(1, 0) -> 1
        session.commit()
        session.refresh(org)
        assert org.seat_limit == 1


# ---------------------------------------------------------------------------
# Subscription / usage / seat endpoints
# ---------------------------------------------------------------------------


def test_get_subscription_creates_free_when_absent(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="sub-owner@team.test", organization_name="Sub Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # Remove any auto-created subscription so the create-when-absent path runs.
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    resp = client.get("/api/v1/billing/subscription", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan_code"] == "free"
    assert body["status"] == "active"


def test_get_subscription_returns_existing(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="sub-exists@team.test", organization_name="Sub Exists Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # First call creates the free subscription; second call returns the existing one
    # (covers the ``if not sub`` false branch / 226->231).
    first = client.get("/api/v1/billing/subscription", headers=headers)
    assert first.status_code == 200, first.text
    second = client.get("/api/v1/billing/subscription", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["org_id"] == user["org_id"]


def test_get_subscription_requires_org(test_client, monkeypatch):
    client, *_ = test_client
    # No auth header -> principal has no org_id -> 401.
    resp = client.get("/api/v1/billing/subscription")
    assert resp.status_code == 401


def test_usage_summary_and_seat_usage(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="usage-owner@team.test", organization_name="Usage Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    usage = client.get("/api/v1/billing/usage-summary", headers=headers)
    assert usage.status_code == 200, usage.text
    assert usage.json()["plan_code"] == "free"
    seat = client.get("/api/v1/billing/seat-usage", headers=headers)
    assert seat.status_code == 200, seat.text
    assert seat.json()["active_members"] == 1


def test_usage_summary_requires_org(test_client):
    client, *_ = test_client
    assert client.get("/api/v1/billing/usage-summary").status_code == 401


def test_seat_usage_requires_org(test_client):
    client, *_ = test_client
    assert client.get("/api/v1/billing/seat-usage").status_code == 401


# ---------------------------------------------------------------------------
# seat-limit update error branches
# ---------------------------------------------------------------------------


def test_update_seat_limit_requires_org(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    resp = client.patch("/api/v1/billing/seat-limit", json={"seat_limit": 3})
    assert resp.status_code == 401


def test_update_seat_limit_without_stripe_subscription(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="noseats@team.test", organization_name="No Seats Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # Subscription exists (free) but no stripe_subscription_id -> 404.
    resp = client.patch("/api/v1/billing/seat-limit", headers=headers, json={"seat_limit": 3})
    assert resp.status_code == 404, resp.text


def test_update_seat_limit_below_minimum(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="below-min@team.test", organization_name="Below Min Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus", subscription_id="sub")
    monkeypatch.setattr(billing_api, "update_subscription_seat_limit", lambda **k: None)
    # 1 active member; requesting 0 (-> floored to 1) is fine, request below members impossible
    # with 1 member, so force minimum by adding pending invites is complex; instead request
    # a value below active+pending by patching counts.
    monkeypatch.setattr(billing_api, "_active_members_count", lambda s, o: 5)
    resp = client.patch("/api/v1/billing/seat-limit", headers=headers, json={"seat_limit": 2})
    assert resp.status_code == 422, resp.text
    assert resp.json()["details"]["minimum_required"] == 5


def test_update_seat_limit_org_missing(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="org-missing@team.test", organization_name="Org Missing")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # Delete the org row so the lookup returns None -> 404.
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(user["org_id"]))
        session.delete(org)
        session.commit()
    resp = client.patch("/api/v1/billing/seat-limit", headers=headers, json={"seat_limit": 3})
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# checkout error branches
# ---------------------------------------------------------------------------


def test_checkout_requires_org(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    resp = client.post("/api/v1/billing/checkout-session", json={"plan_code": "pro"})
    assert resp.status_code == 401


def test_checkout_unsupported_plan(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="badplan@team.test", organization_name="Bad Plan Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan_code": "ultra"}
    )
    assert resp.status_code == 422, resp.text


def test_checkout_missing_price_id(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    monkeypatch.setenv("REFRAME_STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_PRO", "")  # missing price id
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_ENTERPRISE", "")
    get_settings.cache_clear()
    user = _register(client, email="noprice@team.test", organization_name="No Price Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan_code": "pro"}
    )
    assert resp.status_code == 400, resp.text


def test_checkout_creates_subscription_when_absent(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="freshcheckout@team.test", organization_name="Fresh Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # Remove the auto-created subscription so the route's create-when-absent path runs.
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    monkeypatch.setattr(
        billing_api,
        "build_checkout_session",
        lambda **k: {"id": "cs_fresh", "url": "https://checkout/fresh"},
    )
    resp = client.post(
        "/api/v1/billing/checkout-session",
        headers=headers,
        json={"plan_code": "enterprise"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "cs_fresh"


# ---------------------------------------------------------------------------
# portal session
# ---------------------------------------------------------------------------


def test_portal_requires_org(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    resp = client.post("/api/v1/billing/portal-session", json={})
    assert resp.status_code == 401


def test_portal_no_stripe_customer(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="nocustomer@team.test", organization_name="No Cust Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.post("/api/v1/billing/portal-session", headers=headers, json={})
    assert resp.status_code == 404, resp.text


def test_portal_success_with_default_return_url(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="portal-ok@team.test", organization_name="Portal Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_portal", subscription_id="sub_p")
    captured: dict = {}

    def fake_portal(**kwargs):
        captured.update(kwargs)
        return {"id": "bps_1", "url": "https://portal/1"}

    monkeypatch.setattr(billing_api, "build_customer_portal_session", fake_portal)
    resp = client.post("/api/v1/billing/portal-session", headers=headers, json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "bps_1"
    # default return_url derived from app_base_url.
    assert captured["customer_id"] == "cus_portal"
    assert captured["return_url"].endswith("/billing")


def test_portal_success_with_explicit_return_url(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="portal-ret@team.test", organization_name="Portal Ret Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_ret", subscription_id="sub_r")
    captured: dict = {}
    monkeypatch.setattr(
        billing_api,
        "build_customer_portal_session",
        lambda **k: captured.update(k) or {"id": "bps_2", "url": "https://portal/2"},
    )
    resp = client.post(
        "/api/v1/billing/portal-session", headers=headers, json={"return_url": "https://my/return"}
    )
    assert resp.status_code == 200, resp.text
    assert captured["return_url"] == "https://my/return"


# ---------------------------------------------------------------------------
# webhook signature verification branches
# ---------------------------------------------------------------------------


def test_webhook_missing_signature_header(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch, webhook_secret="whsec_123")
    # Webhook secret configured but no Stripe-Signature header -> 400.
    resp = client.post("/api/v1/billing/webhook", json={"type": "ping"})
    assert resp.status_code == 400, resp.text


def test_webhook_invalid_signature(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch, webhook_secret="whsec_123")
    import stripe

    def _raise(*args, **kwargs):
        raise ValueError("bad signature")

    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(_raise))
    resp = client.post(
        "/api/v1/billing/webhook",
        headers={"Stripe-Signature": "t=1,v1=deadbeef"},
        json={"type": "ping"},
    )
    assert resp.status_code == 400, resp.text


def test_webhook_stripe_import_error(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch, webhook_secret="whsec_123")
    import sys

    # Force the lazy ``import stripe`` to fail to exercise the 500 guard.
    monkeypatch.setitem(sys.modules, "stripe", None)
    resp = client.post(
        "/api/v1/billing/webhook",
        headers={"Stripe-Signature": "t=1,v1=x"},
        json={"type": "ping"},
    )
    assert resp.status_code == 500, resp.text


def test_webhook_valid_signature_constructs_event(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch, webhook_secret="whsec_123")
    import stripe

    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        staticmethod(lambda body, sig, secret: {"type": "ping"}),
    )
    resp = client.post(
        "/api/v1/billing/webhook",
        headers={"Stripe-Signature": "t=1,v1=ok"},
        json={"type": "ping"},
    )
    # type "ping" has no customer -> early return 204.
    assert resp.status_code == 204, resp.text


# ---------------------------------------------------------------------------
# webhook dispatch branches (unsigned, json payload)
# ---------------------------------------------------------------------------


def test_webhook_checkout_completed_abort_on_bad_org(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_x", "metadata": {"org_id": "not-a-uuid"}}},
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    # bad org -> _handle_checkout_completed returns False -> early 204.
    assert resp.status_code == 204, resp.text


def test_webhook_checkout_completed_missing_org_continues(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    # No metadata.org_id -> _handle returns True; then no matching sub -> 204.
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"customer": "cus_unknown", "metadata": {}}},
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text


def test_webhook_checkout_completed_creates_subscription_with_plan(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="cc-create@team.test", organization_name="CC Create Org")
    # Delete the auto-created subscription so _handle_checkout_completed builds a new one.
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_ccnew",
                "metadata": {
                    "org_id": user["org_id"],
                    "plan_code": "enterprise",
                    "seat_limit": "8",
                },
            }
        },
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        assert sub is not None
        assert sub.plan_code == "enterprise"
        assert sub.stripe_customer_id == "cus_ccnew"


def test_webhook_checkout_completed_unknown_plan_keeps_free(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="cc-freeplan@team.test", organization_name="CC Free Org")
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_ccfree",
                "metadata": {"org_id": user["org_id"], "plan_code": "starter"},
            }
        },
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        # Unknown plan_code -> stays "free" (the 523->525 not-in-set branch).
        assert sub.plan_code == "free"


def test_webhook_no_customer_returns(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    resp = client.post(
        "/api/v1/billing/webhook",
        json={"type": "customer.subscription.updated", "data": {"object": {}}},
    )
    assert resp.status_code == 204, resp.text


def test_webhook_customer_without_matching_subscription(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    resp = client.post(
        "/api/v1/billing/webhook",
        json={
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_nomatch"}},
        },
    )
    assert resp.status_code == 204, resp.text


def test_webhook_subscription_deleted(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="del-sub@team.test", organization_name="Del Sub Org")
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_del", subscription_id="sub_del")
    resp = client.post(
        "/api/v1/billing/webhook",
        json={
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_del", "id": "sub_del"}},
        },
    )
    assert resp.status_code == 204, resp.text
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        assert sub.status == "cancelled"


def test_webhook_subscription_created_updates_plan_and_period(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="create-sub@team.test", organization_name="Create Sub Org")
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_cr", subscription_id="")
    event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_new",
                "customer": "cus_cr",
                "status": "active",
                "current_period_start": 1_709_000_000,
                "current_period_end": 1_711_000_000,
                "cancel_at_period_end": True,
                "items": {"data": [{"quantity": 3, "price": {"id": "price_enterprise"}}]},
            }
        },
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        assert sub.plan_code == "enterprise"
        assert sub.cancel_at_period_end is True


def test_webhook_subscription_changed_with_empty_price(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="noitems@team.test", organization_name="No Items Org")
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_ni", subscription_id="sub_ni")
    # An item is present but the price dict has no id -> price_id == "" -> plan unchanged.
    # NOTE: the route currently crashes if ``items.data`` is empty (first_item.get("price")
    # returns None, then price.get(...) raises). That is a pre-existing defect in
    # ``_handle_subscription_changed`` and is reported under ISSUES rather than worked around
    # by changing runtime behavior; here we use a well-formed item to exercise the no-price-id
    # branch safely.
    event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "customer": "cus_ni",
                "id": "sub_ni",
                "status": "past_due",
                "items": {"data": [{"quantity": 2, "price": {}}]},
            }
        },
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(
            select(Subscription).where(Subscription.org_id == UUID(user["org_id"]))
        ).first()
        # No price id -> plan unchanged; status updated.
        assert sub.status == "past_due"


def test_webhook_invoice_event_persists_snapshot(test_client, monkeypatch):
    client, *_ = test_client
    _enable_billing(monkeypatch)
    user = _register(client, email="invoice@team.test", organization_name="Invoice Org")
    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_inv", subscription_id="sub_inv")
    event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "customer": "cus_inv",
                "id": "in_123",
                "amount_due": 4200,
                "currency": "usd",
                "status": "paid",
            }
        },
    }
    resp = client.post("/api/v1/billing/webhook", json=event)
    assert resp.status_code == 204, resp.text
    engine = get_engine()
    with Session(engine) as session:
        invoices = session.exec(
            select(InvoiceSnapshot).where(InvoiceSnapshot.org_id == UUID(user["org_id"]))
        ).all()
        assert any(inv.stripe_invoice_id == "in_123" for inv in invoices)
