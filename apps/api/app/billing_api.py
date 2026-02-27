from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from sqlmodel import Session, SQLModel, select

from app.auth_api import PrincipalDep, ensure_default_plans
from app.billing import build_checkout_session, build_customer_portal_session, get_plan_policy, update_subscription_seat_limit
from app.config import get_settings
from app.database import get_session
from app.errors import ApiError, ErrorCode, ErrorResponse, not_found, unauthorized
from app.models import InviteStatus, InvoiceSnapshot, OrgInvite, OrgMembership, Organization, Plan, Subscription, UsageEvent

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
    seat_limit: Optional[int] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class PortalSessionRequest(SQLModel):
    return_url: Optional[str] = None


class SessionResponse(SQLModel):
    id: str
    url: str


class SeatUsageView(SQLModel):
    org_id: str
    plan_code: str
    active_members: int
    pending_invites: int
    seat_limit: int
    available_seats: int


class SeatLimitUpdateRequest(SQLModel):
    seat_limit: int


class BillingMetricView(SQLModel):
    metric: str
    unit: str
    description: str
    included_in_plan: bool = True


class CostModelResponse(SQLModel):
    currency: str = "usd"
    billable_metrics: list[BillingMetricView]
    plans: list[PlanView]
    notes: list[str] = []


def _require_billing_enabled() -> None:
    settings = get_settings()
    if not settings.enable_billing:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ErrorCode.VALIDATION_ERROR,
            message="Billing is disabled",
        )


def _price_to_plan_code(price_id: str, settings) -> str:
    value = (price_id or "").strip()
    if value and value == settings.stripe_price_enterprise:
        return "enterprise"
    if value and value == settings.stripe_price_pro:
        return "pro"
    return "free"


def _unix_to_datetime(value: object) -> datetime | None:
    try:
        ts = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


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


@router.get("/billing/cost-model", response_model=CostModelResponse, tags=["Billing"])
def get_cost_model(session: SessionDep) -> CostModelResponse:
    plans = list_plans(session)
    return CostModelResponse(
        currency="usd",
        billable_metrics=[
            BillingMetricView(
                metric="job_minutes",
                unit="minute",
                description="Completed-job output duration converted to minutes.",
                included_in_plan=True,
            ),
            BillingMetricView(
                metric="storage_bytes",
                unit="byte",
                description="Generated output bytes retained this billing month.",
                included_in_plan=True,
            ),
            BillingMetricView(
                metric="concurrent_jobs",
                unit="count",
                description="Simultaneous running jobs per organization.",
                included_in_plan=True,
            ),
        ],
        plans=plans,
        notes=[
            "Overage is currently calculated from job_minutes above plan quota.",
            "Storage and concurrency limits are enforced as hard limits on job creation.",
        ],
    )


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


def _active_members_count(session: Session, org_id: UUID) -> int:
    return len(session.exec(select(OrgMembership).where(OrgMembership.org_id == org_id)).all())


def _pending_invites_count(session: Session, org_id: UUID) -> int:
    now = datetime.now(timezone.utc)
    return len(
        session.exec(
            select(OrgInvite).where(
                (OrgInvite.org_id == org_id) & (OrgInvite.status == InviteStatus.pending) & (OrgInvite.expires_at > now)
            )
        ).all()
    )


def _seat_usage(session: Session, *, org_id: UUID, plan_code: str) -> SeatUsageView:
    org = session.get(Organization, org_id)
    seat_limit = max(1, int(org.seat_limit if org else get_plan_policy(plan_code).seat_limit))
    active_members = _active_members_count(session, org_id)
    pending_invites = _pending_invites_count(session, org_id)
    available = max(0, seat_limit - active_members - pending_invites)
    return SeatUsageView(
        org_id=str(org_id),
        plan_code=plan_code,
        active_members=active_members,
        pending_invites=pending_invites,
        seat_limit=seat_limit,
        available_seats=available,
    )


@router.get("/billing/usage-summary", response_model=UsageQuotaView, tags=["Billing"], responses={401: {"model": ErrorResponse}})
def billing_usage_summary(session: SessionDep, principal: PrincipalDep) -> UsageQuotaView:
    if not principal.org_id:
        raise unauthorized("Authentication required")
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    plan_code = sub.plan_code if sub else "free"
    return _calc_usage_quota(session, org_id=principal.org_id, plan_code=plan_code)


@router.get("/billing/seat-usage", response_model=SeatUsageView, tags=["Billing"], responses={401: {"model": ErrorResponse}})
def billing_seat_usage(session: SessionDep, principal: PrincipalDep) -> SeatUsageView:
    if not principal.org_id:
        raise unauthorized("Authentication required")
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    plan_code = sub.plan_code if sub else "free"
    return _seat_usage(session, org_id=principal.org_id, plan_code=plan_code)


@router.patch(
    "/billing/seat-limit",
    response_model=SeatUsageView,
    tags=["Billing"],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_billing_seat_limit(
    payload: SeatLimitUpdateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> SeatUsageView:
    _require_billing_enabled()
    if not principal.org_id:
        raise unauthorized("Authentication required")
    org = session.get(Organization, principal.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(principal.org_id)})
    sub = session.exec(select(Subscription).where(Subscription.org_id == principal.org_id)).first()
    if not sub or not sub.stripe_subscription_id:
        raise not_found("Stripe subscription is required for seat updates")

    requested = max(1, int(payload.seat_limit or 1))
    active_members = _active_members_count(session, org.id)
    pending_invites = _pending_invites_count(session, org.id)
    minimum_required = active_members + pending_invites
    if requested < minimum_required:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="seat_limit cannot be lower than active members + pending invites",
            details={
                "seat_limit": requested,
                "active_members": active_members,
                "pending_invites": pending_invites,
                "minimum_required": minimum_required,
            },
        )

    update_subscription_seat_limit(subscription_id=sub.stripe_subscription_id, quantity=requested)
    org.seat_limit = requested
    session.add(org)
    session.commit()
    return _seat_usage(session, org_id=org.id, plan_code=sub.plan_code)


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
    active_members = _active_members_count(session, principal.org_id)
    policy = get_plan_policy(plan_code)
    requested_seat_limit = int(payload.seat_limit or policy.seat_limit)
    quantity = max(1, requested_seat_limit, active_members)
    result = build_checkout_session(
        customer_id=sub.stripe_customer_id,
        price_id=price_id,
        quantity=quantity,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"org_id": str(principal.org_id), "plan_code": plan_code, "seat_limit": str(quantity)},
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
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    stripe_signature: Annotated[Optional[str], Header(alias="Stripe-Signature")] = None,
) -> None:
    _require_billing_enabled()
    settings = get_settings()
    raw_body = await request.body()
    payload: dict
    if settings.stripe_webhook_secret:
        if not stripe_signature:
            raise ApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=ErrorCode.VALIDATION_ERROR,
                message="Missing Stripe-Signature header",
            )
        try:
            import stripe  # type: ignore
        except ImportError as exc:
            raise ApiError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code=ErrorCode.SERVER_ERROR,
                message="stripe package is required for webhook verification",
            ) from exc
        stripe.api_key = settings.stripe_secret_key
        try:
            event = stripe.Webhook.construct_event(raw_body, stripe_signature, settings.stripe_webhook_secret)
        except Exception as exc:
            raise ApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid Stripe webhook signature",
                details={"reason": str(exc)},
            ) from exc
        payload = event
    else:
        payload = await request.json()

    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload, dict) else {}
    obj = data.get("object") if isinstance(data, dict) else {}

    if event_type == "checkout.session.completed":
        customer_id = str(obj.get("customer") or "")
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        org_id_raw = metadata.get("org_id")
        plan_code_raw = str(metadata.get("plan_code") or "").strip().lower()
        seat_limit_raw = metadata.get("seat_limit")
        if customer_id and org_id_raw:
            try:
                org_id = UUID(str(org_id_raw))
            except Exception:
                org_id = None
            if not org_id:
                return None
            sub = session.exec(select(Subscription).where(Subscription.org_id == org_id)).first()
            if not sub:
                sub = Subscription(org_id=org_id, plan_code="free", status="active")
            if plan_code_raw in {"pro", "enterprise"}:
                sub.plan_code = plan_code_raw
            sub.status = "active"
            sub.stripe_customer_id = customer_id
            session.add(sub)
            org = session.get(Organization, org_id)
            if org and seat_limit_raw is not None:
                try:
                    org.seat_limit = max(1, int(seat_limit_raw))
                    session.add(org)
                except (TypeError, ValueError):
                    # Webhook metadata can be missing/malformed; preserve existing seat limit.
                    pass
            session.commit()

    customer_id = str(obj.get("customer") or "")
    if not customer_id:
        return None
    sub = session.exec(select(Subscription).where(Subscription.stripe_customer_id == customer_id)).first()
    if not sub:
        return None

    if event_type in {"customer.subscription.updated", "customer.subscription.created"}:
        status_value = str(obj.get("status") or "active")
        items = obj.get("items") if isinstance(obj.get("items"), dict) else {}
        data_items = items.get("data") if isinstance(items, dict) else []
        first_item = data_items[0] if isinstance(data_items, list) and data_items else {}
        price = first_item.get("price") if isinstance(first_item, dict) else {}
        quantity = first_item.get("quantity") if isinstance(first_item, dict) else None
        price_id = str(price.get("id") or "")
        sub.status = status_value
        sub.stripe_subscription_id = str(obj.get("id") or sub.stripe_subscription_id or "")
        if price_id:
            sub.plan_code = _price_to_plan_code(price_id, settings)
        sub.current_period_start = _unix_to_datetime(obj.get("current_period_start"))
        sub.current_period_end = _unix_to_datetime(obj.get("current_period_end"))
        sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end") or False)
        session.add(sub)
        org = session.get(Organization, sub.org_id)
        if org and quantity is not None:
            try:
                org.seat_limit = max(1, int(quantity))
                session.add(org)
            except (TypeError, ValueError):
                # Provider payloads may omit/format quantity unexpectedly; keep current value.
                pass
        session.commit()

    if event_type == "customer.subscription.deleted":
        sub.status = "cancelled"
        sub.cancel_at_period_end = False
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
