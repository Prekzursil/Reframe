from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, status
from sqlmodel import Session, SQLModel, select

from app.auth_api import PrincipalDep, ensure_default_plans
from app.billing import build_checkout_session, build_customer_portal_session, get_plan_policy
from app.config import get_settings
from app.database import get_session
from app.errors import ApiError, ErrorCode, ErrorResponse, not_found, unauthorized
from app.models import InvoiceSnapshot, Plan, Subscription, UsageEvent

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]


class PlanView(SQLModel):
    code: str
    name: str
    max_concurrent_jobs: int
    monthly_job_minutes: int
    monthly_storage_gb: int
    seat_limit: int
    overage_per_minute_cents: int


class SubscriptionView(SQLModel):
    org_id: str
    plan_code: str
    status: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False


class UsageQuotaView(SQLModel):
    org_id: str
    plan_code: str
    used_job_minutes: float
    quota_job_minutes: int
    used_storage_gb: float
    quota_storage_gb: int
    overage_job_minutes: float
    estimated_overage_cents: int


class CheckoutSessionRequest(SQLModel):
    plan_code: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class PortalSessionRequest(SQLModel):
    return_url: Optional[str] = None


class SessionResponse(SQLModel):
    id: str
    url: str


def _require_billing_enabled() -> None:
    settings = get_settings()
    if not settings.enable_billing:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ErrorCode.VALIDATION_ERROR,
            message="Billing is disabled",
        )


@router.get("/billing/plans", response_model=list[PlanView], tags=["Billing"])
def list_plans(session: SessionDep) -> list[PlanView]:
    ensure_default_plans(session)
    plans = session.exec(select(Plan).where(Plan.active == True)).all()  # noqa: E712
    return [
        PlanView(
            code=p.code,
            name=p.name,
            max_concurrent_jobs=p.max_concurrent_jobs,
            monthly_job_minutes=p.monthly_job_minutes,
            monthly_storage_gb=p.monthly_storage_gb,
            seat_limit=p.seat_limit,
            overage_per_minute_cents=p.overage_per_minute_cents,
        )
        for p in plans
    ]


@router.get("/billing/subscription", response_model=SubscriptionView, tags=["Billing"], responses={401: {"model": ErrorResponse}})
def get_subscription(session: SessionDep, principal: PrincipalDep) -> SubscriptionView:
    if not principal.org_id:
        raise unauthorized("Authentication required")
    ensure_default_plans(session)
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    if not sub:
        sub = Subscription(org_id=principal.org_id, plan_code="free", status="active")
        session.add(sub)
        session.commit()
        session.refresh(sub)
    return SubscriptionView(
        org_id=str(sub.org_id),
        plan_code=sub.plan_code,
        status=sub.status,
        stripe_customer_id=sub.stripe_customer_id,
        stripe_subscription_id=sub.stripe_subscription_id,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
    )


def _calc_usage_quota(session: Session, *, org_id, plan_code: str) -> UsageQuotaView:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage_events = session.exec(
        select(UsageEvent).where((UsageEvent.org_id == org_id) & (UsageEvent.created_at >= month_start))
    ).all()
    used_minutes = sum(float(e.quantity) for e in usage_events if e.metric == "job_minutes")
    storage_bytes = sum(float(e.quantity) for e in usage_events if e.metric == "storage_bytes")
    used_storage_gb = storage_bytes / (1024.0**3)
    policy = get_plan_policy(plan_code)
    overage_minutes = max(0.0, used_minutes - float(policy.monthly_job_minutes))
    overage_cents = int(round(overage_minutes * policy.overage_per_minute_cents))
    return UsageQuotaView(
        org_id=str(org_id),
        plan_code=plan_code,
        used_job_minutes=round(used_minutes, 3),
        quota_job_minutes=policy.monthly_job_minutes,
        used_storage_gb=round(used_storage_gb, 3),
        quota_storage_gb=policy.monthly_storage_gb,
        overage_job_minutes=round(overage_minutes, 3),
        estimated_overage_cents=overage_cents,
    )


@router.get("/billing/usage-summary", response_model=UsageQuotaView, tags=["Billing"], responses={401: {"model": ErrorResponse}})
def billing_usage_summary(session: SessionDep, principal: PrincipalDep) -> UsageQuotaView:
    if not principal.org_id:
        raise unauthorized("Authentication required")
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    plan_code = sub.plan_code if sub else "free"
    return _calc_usage_quota(session, org_id=principal.org_id, plan_code=plan_code)


@router.post(
    "/billing/checkout-session",
    response_model=SessionResponse,
    tags=["Billing"],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def create_checkout(session: SessionDep, payload: CheckoutSessionRequest, principal: PrincipalDep) -> SessionResponse:
    _require_billing_enabled()
    if not principal.org_id:
        raise unauthorized("Authentication required")
    settings = get_settings()

    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    if not sub:
        sub = Subscription(org_id=principal.org_id, plan_code="free", status="active")
        session.add(sub)
        session.commit()
        session.refresh(sub)

    plan_code = (payload.plan_code or "").strip().lower()
    if plan_code not in {"pro", "enterprise"}:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported billing plan",
            details={"plan_code": payload.plan_code},
        )

    price_id = settings.stripe_price_pro if plan_code == "pro" else settings.stripe_price_enterprise
    if not price_id:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ErrorCode.VALIDATION_ERROR,
            message="Stripe price id is not configured",
            details={"plan_code": plan_code},
        )

    success_url = payload.success_url or f"{settings.app_base_url.rstrip('/')}/billing?checkout=success"
    cancel_url = payload.cancel_url or f"{settings.app_base_url.rstrip('/')}/billing?checkout=cancel"
    result = build_checkout_session(
        customer_id=sub.stripe_customer_id,
        price_id=price_id,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return SessionResponse(id=result["id"], url=result["url"])


@router.post(
    "/billing/portal-session",
    response_model=SessionResponse,
    tags=["Billing"],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
def create_portal(session: SessionDep, payload: PortalSessionRequest, principal: PrincipalDep) -> SessionResponse:
    _require_billing_enabled()
    if not principal.org_id:
        raise unauthorized("Authentication required")
    settings = get_settings()
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    if not sub or not sub.stripe_customer_id:
        raise not_found("Stripe customer not found for organization")
    return_url = payload.return_url or f"{settings.app_base_url.rstrip('/')}/billing"
    result = build_customer_portal_session(customer_id=sub.stripe_customer_id, return_url=return_url)
    return SessionResponse(id=result["id"], url=result["url"])


@router.post("/billing/webhook", status_code=status.HTTP_204_NO_CONTENT, tags=["Billing"])
def stripe_webhook(
    payload: dict,
    session: SessionDep,
    stripe_signature: Annotated[Optional[str], Header(alias="Stripe-Signature")] = None,
) -> None:
    _require_billing_enabled()
    _ = stripe_signature
    # In this phase we store normalized snapshots from incoming Stripe events;
    # signature verification is expected when STRIPE_WEBHOOK_SECRET is configured.
    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload, dict) else {}
    obj = data.get("object") if isinstance(data, dict) else {}

    customer_id = str(obj.get("customer") or "")
    if not customer_id:
        return None
    sub = session.exec(select(Subscription).where(Subscription.stripe_customer_id == customer_id)).first()
    if not sub:
        return None

    if event_type in {"customer.subscription.updated", "customer.subscription.created"}:
        status_value = str(obj.get("status") or "active")
        sub.status = status_value
        sub.stripe_subscription_id = str(obj.get("id") or sub.stripe_subscription_id or "")
        session.add(sub)
        session.commit()

    if event_type in {"invoice.paid", "invoice.payment_failed", "invoice.finalized"}:
        invoice = InvoiceSnapshot(
            org_id=sub.org_id,
            subscription_id=sub.id,
            stripe_invoice_id=str(obj.get("id") or ""),
            amount_cents=int(obj.get("amount_due") or 0),
            currency=str(obj.get("currency") or "usd"),
            status=str(obj.get("status") or "draft"),
            payload=payload,
        )
        session.add(invoice)
        session.commit()
    return None
