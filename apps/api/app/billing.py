from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import get_settings


@dataclass(frozen=True)
class PlanPolicy:
    code: str
    max_concurrent_jobs: int
    monthly_job_minutes: int
    monthly_storage_gb: int
    seat_limit: int
    overage_per_minute_cents: int


DEFAULT_PLAN_POLICIES: dict[str, PlanPolicy] = {
    "free": PlanPolicy(
        code="free",
        max_concurrent_jobs=1,
        monthly_job_minutes=120,
        monthly_storage_gb=2,
        seat_limit=1,
        overage_per_minute_cents=0,
    ),
    "pro": PlanPolicy(
        code="pro",
        max_concurrent_jobs=3,
        monthly_job_minutes=1200,
        monthly_storage_gb=50,
        seat_limit=5,
        overage_per_minute_cents=2,
    ),
    "enterprise": PlanPolicy(
        code="enterprise",
        max_concurrent_jobs=12,
        monthly_job_minutes=20_000,
        monthly_storage_gb=1_000,
        seat_limit=200,
        overage_per_minute_cents=1,
    ),
}


def get_plan_policy(code: str) -> PlanPolicy:
    return DEFAULT_PLAN_POLICIES.get((code or "").strip().lower(), DEFAULT_PLAN_POLICIES["free"])


def _get_stripe():
    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise RuntimeError("stripe is not installed; install with `pip install stripe`") from exc
    return stripe


def build_checkout_session(
    *,
    customer_id: Optional[str],
    price_id: str,
    success_url: str,
    cancel_url: str,
    metadata: Optional[dict[str, str]] = None,
) -> dict:
    settings = get_settings()
    if not settings.enable_billing:
        raise RuntimeError("Billing is disabled.")
    if not settings.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")
    stripe = _get_stripe()
    stripe.api_key = settings.stripe_secret_key
    kwargs = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if customer_id:
        kwargs["customer"] = customer_id
    if metadata:
        kwargs["metadata"] = metadata
    session = stripe.checkout.Session.create(**kwargs)
    return {"id": session.get("id"), "url": session.get("url")}


def build_customer_portal_session(*, customer_id: str, return_url: str) -> dict:
    settings = get_settings()
    if not settings.enable_billing:
        raise RuntimeError("Billing is disabled.")
    if not settings.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")
    stripe = _get_stripe()
    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return {"id": session.get("id"), "url": session.get("url")}
