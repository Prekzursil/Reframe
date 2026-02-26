from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models import Organization, Subscription


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _enable_billing(monkeypatch) -> None:
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    monkeypatch.setenv("REFRAME_STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("REFRAME_STRIPE_PRICE_ENTERPRISE", "price_enterprise")
    get_settings.cache_clear()


def _set_subscription_stripe_ids(org_id: str, *, customer_id: str, subscription_id: str) -> None:
    engine = get_engine()
    with Session(engine) as session:
        sub = session.exec(select(Subscription).where(Subscription.org_id == UUID(org_id))).first()
        assert sub is not None
        sub.stripe_customer_id = customer_id
        sub.stripe_subscription_id = subscription_id
        session.add(sub)
        session.commit()


def _get_org(org_id: str) -> Organization:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        assert org is not None
        return org


def test_checkout_session_accepts_seat_limit_and_forwards_quantity(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    _enable_billing(monkeypatch)

    user = _register(client, email="billing-owner@team.test", organization_name="Billing Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    captured: dict[str, object] = {}

    def fake_checkout_session(**kwargs):
        captured.update(kwargs)
        return {"id": "cs_test", "url": "https://checkout.test/session"}

    monkeypatch.setattr("app.billing_api.build_checkout_session", fake_checkout_session)

    resp = client.post(
        "/api/v1/billing/checkout-session",
        headers=headers,
        json={"plan_code": "pro", "seat_limit": 4},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == "cs_test"
    assert captured.get("quantity") == 4
    metadata = captured.get("metadata") or {}
    assert isinstance(metadata, dict)
    assert metadata.get("org_id") == user["org_id"]
    assert metadata.get("seat_limit") == "4"


def test_webhook_syncs_org_seat_limit_from_subscription_quantity(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    _enable_billing(monkeypatch)

    user = _register(client, email="webhook-owner@team.test", organization_name="Webhook Org")

    checkout_event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_123",
                "metadata": {
                    "org_id": user["org_id"],
                    "plan_code": "pro",
                    "seat_limit": "6",
                },
            }
        },
    }
    first = client.post("/api/v1/billing/webhook", json=checkout_event)
    assert first.status_code == 204, first.text

    subscription_event = {
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "current_period_start": 1_709_000_000,
                "current_period_end": 1_711_000_000,
                "cancel_at_period_end": False,
                "items": {
                    "data": [
                        {
                            "quantity": 6,
                            "price": {"id": "price_pro"},
                        }
                    ]
                },
            }
        },
    }
    second = client.post("/api/v1/billing/webhook", json=subscription_event)
    assert second.status_code == 204, second.text

    org = _get_org(user["org_id"])
    assert org.seat_limit == 6


def test_billing_seat_usage_and_update_limit(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    _enable_billing(monkeypatch)

    user = _register(client, email="seat-owner@team.test", organization_name="Seat Billing Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    _set_subscription_stripe_ids(user["org_id"], customer_id="cus_seat", subscription_id="sub_seat")

    updated: dict[str, object] = {}

    def fake_update_seats(*, subscription_id: str, quantity: int):
        updated["subscription_id"] = subscription_id
        updated["quantity"] = quantity

    monkeypatch.setattr("app.billing_api.update_subscription_seat_limit", fake_update_seats)

    seat_usage = client.get("/api/v1/billing/seat-usage", headers=headers)
    assert seat_usage.status_code == 200, seat_usage.text
    usage_payload = seat_usage.json()
    assert usage_payload["active_members"] == 1
    assert usage_payload["seat_limit"] >= 1

    patch_resp = client.patch("/api/v1/billing/seat-limit", headers=headers, json={"seat_limit": 5})
    assert patch_resp.status_code == 200, patch_resp.text
    payload = patch_resp.json()
    assert payload["seat_limit"] == 5
    assert updated.get("subscription_id") == "sub_seat"
    assert updated.get("quantity") == 5
