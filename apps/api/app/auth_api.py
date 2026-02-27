from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, Query, status
from sqlmodel import Session, SQLModel, select

from app.billing import DEFAULT_PLAN_POLICIES
from app.config import get_settings
from app.database import get_session
from app.errors import ErrorCode, ErrorResponse, ApiError, conflict, not_found, unauthorized
from app.models import InviteStatus, OAuthAccount, OrgInvite, OrgMembership, Organization, Plan, Subscription, User
from app.security import (
    AuthPrincipal,
    create_access_token,
    create_oauth_state,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    parse_oauth_state,
    verify_password,
)

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]


class AuthRegisterRequest(SQLModel):
    email: str
    password: str
    display_name: Optional[str] = None
    organization_name: Optional[str] = None


class AuthLoginRequest(SQLModel):
    email: str
    password: str


class TokenRefreshRequest(SQLModel):
    refresh_token: str


class AuthTokenResponse(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: UUID
    org_id: UUID
    role: str


class AuthMeResponse(SQLModel):
    user_id: UUID
    email: str
    display_name: Optional[str] = None
    org_id: UUID
    org_name: str
    role: str


class OAuthStartResponse(SQLModel):
    provider: str
    authorize_url: str
    state: str


class OrgMemberView(SQLModel):
    user_id: UUID
    email: str
    display_name: Optional[str]
    role: str


class OrgContextResponse(SQLModel):
    org_id: UUID
    org_name: str
    slug: str
    role: str
    members: list[OrgMemberView]


class OrgInviteRequest(SQLModel):
    email: str
    role: str = "viewer"
    expires_in_days: int = 7


class OrgInviteResolveRequest(SQLModel):
    token: str


class OrgInviteView(SQLModel):
    id: UUID
    org_id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    invite_url: Optional[str] = None


class OrgInviteResolveResponse(SQLModel):
    org_id: UUID
    org_name: str
    email: str
    role: str
    status: str
    expires_at: datetime


class OrgMemberRoleUpdateRequest(SQLModel):
    role: str


def _normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return base or "org"


ORG_ROLES = {"owner", "admin", "editor", "viewer"}
ORG_MANAGER_ROLES = {"owner", "admin"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _seat_limit_for_org(org: Organization) -> int:
    return max(1, int(org.seat_limit or 1))


def _active_members_count(session: Session, org_id: UUID) -> int:
    return len(session.exec(select(OrgMembership).where(OrgMembership.org_id == org_id)).all())


def _pending_invite_count(session: Session, org_id: UUID) -> int:
    now = _now_utc()
    return len(
        session.exec(
            select(OrgInvite).where(
                (OrgInvite.org_id == org_id) & (OrgInvite.status == InviteStatus.pending) & (OrgInvite.expires_at > now)
            )
        ).all()
    )


def _current_membership(session: Session, principal: AuthPrincipal) -> OrgMembership:
    if not principal.org_id or not principal.user_id:
        raise unauthorized("Authentication required")
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.user_id == principal.user_id))
    ).first()
    if not membership:
        raise unauthorized("Organization membership is required")
    return membership


def _require_org_manager(session: Session, principal: AuthPrincipal) -> OrgMembership:
    membership = _current_membership(session, principal)
    if membership.role not in ORG_MANAGER_ROLES:
        raise unauthorized("Owner or admin role is required")
    return membership


def _invite_url(token: str) -> str:
    settings = get_settings()
    base = settings.app_base_url.rstrip("/")
    return f"{base}/invites/accept?token={token}"


def _serialize_invite(invite: OrgInvite, *, include_token: str | None = None) -> OrgInviteView:
    return OrgInviteView(
        id=invite.id,
        org_id=invite.org_id,
        email=invite.email,
        role=invite.role,
        status=invite.status.value if isinstance(invite.status, InviteStatus) else str(invite.status),
        expires_at=invite.expires_at,
        invite_url=_invite_url(include_token) if include_token else None,
    )


def _coerce_pending_invite(session: Session, token: str) -> OrgInvite:
    token_hash = _hash_invite_token(token.strip())
    invite = session.exec(select(OrgInvite).where(OrgInvite.token_hash == token_hash)).first()
    if not invite:
        raise not_found("Invite not found")
    if invite.status != InviteStatus.pending:
        status_value = invite.status.value if isinstance(invite.status, InviteStatus) else str(invite.status)
        raise conflict("Invite is no longer pending", details={"status": status_value})
    if _as_utc(invite.expires_at) <= _now_utc():
        invite.status = InviteStatus.expired
        invite.updated_at = _now_utc()
        session.add(invite)
        session.commit()
        raise conflict("Invite is expired", details={"status": "expired"})
    return invite


def ensure_default_plans(session: Session) -> None:
    changed = False
    for code, policy in DEFAULT_PLAN_POLICIES.items():
        plan = session.get(Plan, code)
        if not plan:
            plan = Plan(
                code=code,
                name=code.capitalize(),
                max_concurrent_jobs=policy.max_concurrent_jobs,
                monthly_job_minutes=policy.monthly_job_minutes,
                monthly_storage_gb=policy.monthly_storage_gb,
                seat_limit=policy.seat_limit,
                overage_per_minute_cents=policy.overage_per_minute_cents,
                active=True,
            )
            session.add(plan)
            changed = True
    if changed:
        session.commit()


def _unique_org_slug(session: Session, name: str) -> str:
    base = _slugify(name)
    slug = base
    idx = 1
    while session.exec(select(Organization).where(Organization.slug == slug)).first():
        idx += 1
        slug = f"{base}-{idx}"
    return slug


def ensure_personal_org(session: Session, user: User, organization_name: str | None = None) -> tuple[Organization, OrgMembership]:
    existing = session.exec(select(OrgMembership).where(OrgMembership.user_id == user.id)).first()
    if existing:
        org = session.get(Organization, existing.org_id)
        if not org:
            raise not_found("Organization missing", {"org_id": str(existing.org_id)})
        return org, existing

    org_name = (organization_name or "").strip() or f"{(user.display_name or user.email).split('@')[0]} workspace"
    org = Organization(name=org_name, slug=_unique_org_slug(session, org_name), tier="free", seat_limit=1)
    session.add(org)
    session.commit()
    session.refresh(org)

    membership = OrgMembership(org_id=org.id, user_id=user.id, role="owner")
    session.add(membership)
    session.commit()
    session.refresh(membership)

    if not session.exec(select(Subscription).where(Subscription.org_id == org.id)).first():
        session.add(Subscription(org_id=org.id, plan_code="free", status="active"))
        session.commit()

    return org, membership


def _issue_tokens(*, user_id: UUID, org_id: UUID, role: str) -> AuthTokenResponse:
    return AuthTokenResponse(
        access_token=create_access_token(user_id=user_id, org_id=org_id, role=role),
        refresh_token=create_refresh_token(user_id=user_id, org_id=org_id, role=role),
        user_id=user_id,
        org_id=org_id,
        role=role,
    )


def get_principal(
    session: SessionDep,
    authorization: Annotated[Optional[str], Header(alias="Authorization")] = None,
) -> AuthPrincipal:
    settings = get_settings()
    if not authorization:
        if settings.hosted_mode:
            raise unauthorized("Authentication required")
        return AuthPrincipal()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized("Invalid authorization header")

    try:
        payload = decode_access_token(token)
        user_id = UUID(str(payload["sub"]))
        org_id = UUID(str(payload["org"])) if payload.get("org") else None
        role = str(payload.get("role") or "viewer")
    except Exception as exc:
        raise unauthorized("Invalid access token", details={"reason": str(exc)}) from exc

    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise unauthorized("User is inactive")

    if settings.hosted_mode and not org_id:
        raise unauthorized("Organization context missing")

    return AuthPrincipal(user_id=user_id, org_id=org_id, role=role)


PrincipalDep = Annotated[AuthPrincipal, Depends(get_principal)]


def _oauth_provider_config(provider: str) -> dict[str, str]:
    settings = get_settings()
    provider = provider.strip().lower()
    if provider == "google":
        return {
            "provider": "google",
            "client_id": settings.oauth_google_client_id,
            "client_secret": settings.oauth_google_client_secret,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
            "scope": "openid email profile",
        }
    if provider == "github":
        return {
            "provider": "github",
            "client_id": settings.oauth_github_client_id,
            "client_secret": settings.oauth_github_client_secret,
            "authorize_url": "https://github.com/login/oauth/authorize",
            "token_url": "https://github.com/login/oauth/access_token",
            "userinfo_url": "https://api.github.com/user",
            "scope": "read:user user:email",
        }
    raise ApiError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=ErrorCode.VALIDATION_ERROR,
        message="Unsupported OAuth provider",
        details={"provider": provider},
    )


def _oauth_callback_url(provider: str) -> str:
    settings = get_settings()
    return f"{settings.api_base_url.rstrip('/')}/api/v1/auth/oauth/{provider}/callback"


@router.post(
    "/auth/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def register(payload: AuthRegisterRequest, session: SessionDep) -> AuthTokenResponse:
    ensure_default_plans(session)
    email = _normalize_email(payload.email)
    if not email or "@" not in email:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Valid email is required",
        )
    if len(payload.password or "") < 8:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Password must be at least 8 characters",
        )
    if session.exec(select(User).where(User.email == email)).first():
        raise conflict("Email is already registered", details={"email": email})

    user = User(email=email, password_hash=hash_password(payload.password), display_name=(payload.display_name or "").strip() or None)
    session.add(user)
    session.commit()
    session.refresh(user)

    org, membership = ensure_personal_org(session, user, organization_name=payload.organization_name)
    return _issue_tokens(user_id=user.id, org_id=org.id, role=membership.role)


@router.post("/auth/login", response_model=AuthTokenResponse, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def login(payload: AuthLoginRequest, session: SessionDep) -> AuthTokenResponse:
    email = _normalize_email(payload.email)
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise unauthorized("Invalid credentials")
    org, membership = ensure_personal_org(session, user)
    return _issue_tokens(user_id=user.id, org_id=org.id, role=membership.role)


@router.post("/auth/refresh", response_model=AuthTokenResponse, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def refresh_token(payload: TokenRefreshRequest, session: SessionDep) -> AuthTokenResponse:
    try:
        claims = decode_refresh_token(payload.refresh_token)
        user_id = UUID(str(claims["sub"]))
        org_id = UUID(str(claims["org"])) if claims.get("org") else None
        role = str(claims.get("role") or "viewer")
    except Exception as exc:
        raise unauthorized("Invalid refresh token", details={"reason": str(exc)}) from exc

    user = session.get(User, user_id)
    if not user or not user.is_active or not org_id:
        raise unauthorized("Invalid refresh context")
    return _issue_tokens(user_id=user_id, org_id=org_id, role=role)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
def logout() -> None:
    return None


@router.get("/auth/me", response_model=AuthMeResponse, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def me(session: SessionDep, principal: PrincipalDep) -> AuthMeResponse:
    if not principal.user_id or not principal.org_id:
        raise unauthorized("Authentication required")
    user = session.get(User, principal.user_id)
    org = session.get(Organization, principal.org_id)
    if not user or not org:
        raise unauthorized("Principal not found")
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == org.id) & (OrgMembership.user_id == user.id))
    ).first()
    role = membership.role if membership else principal.role
    return AuthMeResponse(user_id=user.id, email=user.email, display_name=user.display_name, org_id=org.id, org_name=org.name, role=role)


@router.get("/auth/oauth/{provider}/start", response_model=OAuthStartResponse, tags=["Auth"], responses={400: {"model": ErrorResponse}})
def oauth_start(provider: str, redirect_to: Optional[str] = None) -> OAuthStartResponse:
    settings = get_settings()
    if not settings.enable_oauth:
        raise ApiError(status_code=status.HTTP_400_BAD_REQUEST, code=ErrorCode.VALIDATION_ERROR, message="OAuth is disabled")
    cfg = _oauth_provider_config(provider)
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise ApiError(status_code=status.HTTP_400_BAD_REQUEST, code=ErrorCode.VALIDATION_ERROR, message="OAuth provider is not configured")

    state = create_oauth_state(provider=cfg["provider"], redirect_to=redirect_to)
    callback = _oauth_callback_url(cfg["provider"])
    if cfg["provider"] == "google":
        url = (
            f"{cfg['authorize_url']}?client_id={cfg['client_id']}&redirect_uri={callback}"
            f"&response_type=code&scope={cfg['scope']}&access_type=offline&prompt=consent&state={state}"
        )
    else:
        url = (
            f"{cfg['authorize_url']}?client_id={cfg['client_id']}&redirect_uri={callback}"
            f"&scope={cfg['scope']}&state={state}"
        )
    return OAuthStartResponse(provider=cfg["provider"], authorize_url=url, state=state)


@router.get("/auth/oauth/{provider}/callback", response_model=AuthTokenResponse, tags=["Auth"])
def oauth_callback(
    provider: str,
    code: str,
    state: str,
    session: SessionDep,
    redirect_to: Optional[str] = Query(default=None),
) -> AuthTokenResponse:
    settings = get_settings()
    if not settings.enable_oauth:
        raise ApiError(status_code=status.HTTP_400_BAD_REQUEST, code=ErrorCode.VALIDATION_ERROR, message="OAuth is disabled")
    cfg = _oauth_provider_config(provider)
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise ApiError(status_code=status.HTTP_400_BAD_REQUEST, code=ErrorCode.VALIDATION_ERROR, message="OAuth provider is not configured")

    state_provider, _state_redirect = parse_oauth_state(state)
    if state_provider != cfg["provider"]:
        raise unauthorized("OAuth state/provider mismatch")

    callback = _oauth_callback_url(cfg["provider"])
    with httpx.Client(timeout=20.0) as client:
        token_resp = client.post(
            cfg["token_url"],
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "code": code,
                "redirect_uri": callback,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        token_resp.raise_for_status()
        token_payload = token_resp.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise unauthorized("OAuth token exchange failed")

        user_resp = client.get(
            cfg["userinfo_url"],
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        user_resp.raise_for_status()
        user_payload = user_resp.json()

    if cfg["provider"] == "google":
        provider_subject = str(user_payload.get("sub") or "")
        email = _normalize_email(str(user_payload.get("email") or ""))
        display_name = str(user_payload.get("name") or "").strip() or None
    else:
        provider_subject = str(user_payload.get("id") or "")
        email = _normalize_email(str(user_payload.get("email") or ""))
        display_name = str(user_payload.get("name") or user_payload.get("login") or "").strip() or None
        if not email:
            with httpx.Client(timeout=20.0) as client:
                email_resp = client.get(
                    "https://api.github.com/user/emails",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
                if email_resp.is_success:
                    email_items = email_resp.json()
                    primary = next((item for item in email_items if item.get("primary")), None)
                    if primary:
                        email = _normalize_email(str(primary.get("email") or ""))

    if not provider_subject or not email:
        raise unauthorized("OAuth account is missing subject/email")

    oauth = session.exec(
        select(OAuthAccount).where((OAuthAccount.provider == cfg["provider"]) & (OAuthAccount.provider_subject == provider_subject))
    ).first()
    user: User | None = None
    if oauth:
        user = session.get(User, oauth.user_id)

    if not user:
        user = session.exec(select(User).where(User.email == email)).first()

    if not user:
        user = User(email=email, display_name=display_name, password_hash=None, is_active=True)
        session.add(user)
        session.commit()
        session.refresh(user)

    if not oauth:
        oauth = OAuthAccount(user_id=user.id, provider=cfg["provider"], provider_subject=provider_subject, email=email)
        session.add(oauth)
        session.commit()

    org, membership = ensure_personal_org(session, user)
    _ = redirect_to  # reserved for frontend callback orchestration
    return _issue_tokens(user_id=user.id, org_id=org.id, role=membership.role)


@router.get("/orgs/me", response_model=OrgContextResponse, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def org_me(session: SessionDep, principal: PrincipalDep) -> OrgContextResponse:
    if not principal.org_id or not principal.user_id:
        raise unauthorized("Authentication required")
    org = session.get(Organization, principal.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(principal.org_id)})

    memberships = session.exec(select(OrgMembership).where(OrgMembership.org_id == org.id)).all()
    members: list[OrgMemberView] = []
    role = principal.role
    for m in memberships:
        user = session.get(User, m.user_id)
        if user:
            members.append(OrgMemberView(user_id=user.id, email=user.email, display_name=user.display_name, role=m.role))
        if m.user_id == principal.user_id:
            role = m.role

    return OrgContextResponse(org_id=org.id, org_name=org.name, slug=org.slug, role=role, members=members)


@router.post(
    "/orgs/invites",
    response_model=OrgInviteView,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_org_invite(payload: OrgInviteRequest, session: SessionDep, principal: PrincipalDep) -> OrgInviteView:
    manager = _require_org_manager(session, principal)
    if not principal.org_id:
        raise unauthorized("Authentication required")
    org = session.get(Organization, principal.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(principal.org_id)})

    email = _normalize_email(payload.email)
    if not email or "@" not in email:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Valid invite email is required",
        )

    role = (payload.role or "").strip().lower() or "viewer"
    if role not in ORG_ROLES:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported role",
            details={"role": role},
        )
    if role == "owner" and manager.role != "owner":
        raise unauthorized("Only owners can invite another owner")

    expires_in_days = int(payload.expires_in_days or 7)
    if expires_in_days < 1 or expires_in_days > 30:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="expires_in_days must be between 1 and 30",
        )

    active_members = _active_members_count(session, org.id)
    pending_invites = _pending_invite_count(session, org.id)
    if (active_members + pending_invites) >= _seat_limit_for_org(org):
        raise conflict(
            "Seat limit reached; increase seat limit before inviting",
            details={
                "active_members": active_members,
                "pending_invites": pending_invites,
                "seat_limit": org.seat_limit,
            },
        )

    existing_pending = session.exec(
        select(OrgInvite).where(
            (OrgInvite.org_id == org.id) & (OrgInvite.email == email) & (OrgInvite.status == InviteStatus.pending)
        )
    ).first()
    if existing_pending and existing_pending.expires_at > _now_utc():
        raise conflict("A pending invite already exists for this email", details={"email": email})

    token = secrets.token_urlsafe(32)
    now = _now_utc()
    invite = OrgInvite(
        org_id=org.id,
        email=email,
        role=role,
        token_hash=_hash_invite_token(token),
        status=InviteStatus.pending,
        invited_by_user_id=manager.user_id,
        expires_at=now + timedelta(days=expires_in_days),
        created_at=now,
        updated_at=now,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _serialize_invite(invite, include_token=token)


@router.get("/orgs/invites", response_model=list[OrgInviteView], tags=["Auth"], responses={401: {"model": ErrorResponse}})
def list_org_invites(session: SessionDep, principal: PrincipalDep) -> list[OrgInviteView]:
    _require_org_manager(session, principal)
    if not principal.org_id:
        raise unauthorized("Authentication required")
    now = _now_utc()
    invites = session.exec(select(OrgInvite).where(OrgInvite.org_id == principal.org_id).order_by(OrgInvite.created_at.desc())).all()
    changed = False
    for invite in invites:
        if invite.status == InviteStatus.pending and _as_utc(invite.expires_at) <= now:
            invite.status = InviteStatus.expired
            invite.updated_at = now
            session.add(invite)
            changed = True
    if changed:
        session.commit()
    return [_serialize_invite(invite) for invite in invites]


@router.post("/orgs/invites/{invite_id}/revoke", response_model=OrgInviteView, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def revoke_org_invite(invite_id: UUID, session: SessionDep, principal: PrincipalDep) -> OrgInviteView:
    _require_org_manager(session, principal)
    if not principal.org_id:
        raise unauthorized("Authentication required")
    invite = session.exec(select(OrgInvite).where((OrgInvite.id == invite_id) & (OrgInvite.org_id == principal.org_id))).first()
    if not invite:
        raise not_found("Invite not found", {"invite_id": str(invite_id)})
    if invite.status == InviteStatus.pending:
        invite.status = InviteStatus.revoked
        invite.updated_at = _now_utc()
        session.add(invite)
        session.commit()
        session.refresh(invite)
    return _serialize_invite(invite)


@router.get("/orgs/invites/resolve", response_model=OrgInviteResolveResponse, tags=["Auth"])
def resolve_org_invite(token: str, session: SessionDep) -> OrgInviteResolveResponse:
    invite = _coerce_pending_invite(session, token)
    org = session.get(Organization, invite.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(invite.org_id)})
    return OrgInviteResolveResponse(
        org_id=org.id,
        org_name=org.name,
        email=invite.email,
        role=invite.role,
        status=invite.status.value if isinstance(invite.status, InviteStatus) else str(invite.status),
        expires_at=invite.expires_at,
    )


@router.post("/orgs/invites/accept", response_model=AuthTokenResponse, tags=["Auth"], responses={401: {"model": ErrorResponse}})
def accept_org_invite(payload: OrgInviteResolveRequest, session: SessionDep, principal: PrincipalDep) -> AuthTokenResponse:
    if not principal.user_id:
        raise unauthorized("Authentication required")
    user = session.get(User, principal.user_id)
    if not user:
        raise unauthorized("User not found")

    invite = _coerce_pending_invite(session, payload.token)
    if _normalize_email(user.email) != invite.email:
        raise unauthorized("Invite email does not match current user")

    org = session.get(Organization, invite.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(invite.org_id)})

    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == org.id) & (OrgMembership.user_id == user.id))
    ).first()
    if not membership:
        active_members = _active_members_count(session, org.id)
        if active_members >= _seat_limit_for_org(org):
            raise conflict(
                "Seat limit reached; cannot accept invite",
                details={"active_members": active_members, "seat_limit": org.seat_limit},
            )
        membership = OrgMembership(org_id=org.id, user_id=user.id, role=invite.role)
        session.add(membership)
        session.commit()
        session.refresh(membership)

    invite.status = InviteStatus.accepted
    invite.accepted_by_user_id = user.id
    invite.updated_at = _now_utc()
    session.add(invite)
    session.commit()
    return _issue_tokens(user_id=user.id, org_id=org.id, role=membership.role)


@router.patch(
    "/orgs/members/{user_id}/role",
    response_model=OrgMemberView,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def update_member_role(
    user_id: UUID,
    payload: OrgMemberRoleUpdateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> OrgMemberView:
    manager = _require_org_manager(session, principal)
    if not principal.org_id:
        raise unauthorized("Authentication required")
    next_role = (payload.role or "").strip().lower()
    if next_role not in ORG_ROLES:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported role",
            details={"role": next_role},
        )

    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.user_id == user_id))
    ).first()
    if not membership:
        raise not_found("Organization member not found", {"user_id": str(user_id)})

    if membership.role == "owner" and next_role != "owner":
        owners = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.role == "owner"))
        ).all()
        if len(owners) <= 1:
            raise conflict("Cannot demote the last owner")
    if next_role == "owner" and manager.role != "owner":
        raise unauthorized("Only owners can promote another owner")
    if membership.role == "owner" and manager.role != "owner":
        raise unauthorized("Only owners can change owner roles")

    membership.role = next_role
    membership.updated_at = _now_utc()
    session.add(membership)
    session.commit()
    user = session.get(User, membership.user_id)
    if not user:
        raise not_found("User not found", {"user_id": str(user_id)})
    return OrgMemberView(user_id=user.id, email=user.email, display_name=user.display_name, role=membership.role)


@router.delete(
    "/orgs/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def remove_member(user_id: UUID, session: SessionDep, principal: PrincipalDep) -> None:
    manager = _require_org_manager(session, principal)
    if not principal.org_id:
        raise unauthorized("Authentication required")
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.user_id == user_id))
    ).first()
    if not membership:
        raise not_found("Organization member not found", {"user_id": str(user_id)})
    if membership.role == "owner":
        owners = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == principal.org_id) & (OrgMembership.role == "owner"))
        ).all()
        if len(owners) <= 1:
            raise conflict("Cannot remove the last owner")
        if manager.role != "owner":
            raise unauthorized("Only owners can remove another owner")
    session.delete(membership)
    session.commit()
    return None
