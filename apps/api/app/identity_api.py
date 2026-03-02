from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated, Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from sqlmodel import Session, SQLModel, select

from app.auth_api import PrincipalDep
from app.config import get_settings
from app.database import get_session
from app.errors import ApiError, ErrorCode, ErrorResponse, conflict, not_found, unauthorized
from app.models import (
    AuditEvent,
    OAuthAccount,
    OrgMembership,
    Organization,
    RoleMapping,
    ScimIdentity,
    ScimToken,
    SsoConnection,
    User,
)
from app.security import create_access_token, create_oauth_state, create_refresh_token, parse_oauth_state

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]

ROLE_VALUES = {"owner", "admin", "editor", "viewer"}
ORG_MANAGER_ROLES = {"owner", "admin"}
SCIM_SCOPE_DEFAULTS = ["users:read", "users:write", "groups:read", "groups:write"]
SCIM_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"


class SsoConfigView(SQLModel):
    org_id: UUID
    provider: str
    enabled: bool
    issuer_url: Optional[str] = None
    client_id: Optional[str] = None
    audience: Optional[str] = None
    default_role: str
    jit_enabled: bool
    allow_email_link: bool
    config: dict = {}
    updated_at: datetime


class SsoConfigUpdateRequest(SQLModel):
    enabled: bool = False
    issuer_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret_ref: Optional[str] = None
    audience: Optional[str] = None
    default_role: str = "viewer"
    jit_enabled: bool = True
    allow_email_link: bool = True
    config: dict = {}


class ScimTokenCreateRequest(SQLModel):
    scopes: list[str] = SCIM_SCOPE_DEFAULTS


class ScimTokenView(SQLModel):
    id: UUID
    org_id: UUID
    token_hint: str
    scopes: list[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    token: Optional[str] = None


class SsoStartResponse(SQLModel):
    provider: str
    authorize_url: str
    state: str
    redirect_uri: str
    org_id: UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _mask_token(raw: str) -> str:
    if len(raw) <= 8:
        return raw
    return f"{raw[:6]}...{raw[-2:]}"


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _emit_audit(
    session: Session,
    *,
    org_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            org_id=org_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
        )
    )


def _require_org_manager(session: Session, principal, org_id: UUID) -> OrgMembership:
    if not principal.user_id or principal.org_id != org_id:
        raise unauthorized("Owner or admin role is required")
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == org_id) & (OrgMembership.user_id == principal.user_id))
    ).first()
    if not membership or membership.role not in ORG_MANAGER_ROLES:
        raise unauthorized("Owner or admin role is required")
    return membership


def _serialize_sso_config(connection: SsoConnection | None, org_id: UUID) -> SsoConfigView:
    settings = get_settings()
    now = _now()
    if not connection:
        return SsoConfigView(
            org_id=org_id,
            provider="okta",
            enabled=False,
            issuer_url=settings.okta_issuer_url or None,
            client_id=settings.okta_client_id or None,
            audience=settings.okta_audience or None,
            default_role="viewer",
            jit_enabled=True,
            allow_email_link=True,
            config={},
            updated_at=now,
        )
    return SsoConfigView(
        org_id=org_id,
        provider=connection.provider,
        enabled=connection.enabled,
        issuer_url=connection.issuer_url,
        client_id=connection.client_id,
        audience=connection.audience,
        default_role=connection.default_role,
        jit_enabled=connection.jit_enabled,
        allow_email_link=connection.allow_email_link,
        config=dict(connection.config or {}),
        updated_at=connection.updated_at,
    )


def _upsert_sso_connection(session: Session, org_id: UUID, payload: SsoConfigUpdateRequest) -> SsoConnection:
    connection = session.exec(select(SsoConnection).where(SsoConnection.org_id == org_id)).first()
    now = _now()
    if connection is None:
        connection = SsoConnection(
            org_id=org_id,
            provider="okta",
            enabled=bool(payload.enabled),
            issuer_url=(payload.issuer_url or "").strip() or None,
            client_id=(payload.client_id or "").strip() or None,
            client_secret_ref=(payload.client_secret_ref or "").strip() or None,
            audience=(payload.audience or "").strip() or None,
            default_role=(payload.default_role or "viewer").strip().lower(),
            jit_enabled=bool(payload.jit_enabled),
            allow_email_link=bool(payload.allow_email_link),
            config=dict(payload.config or {}),
            created_at=now,
            updated_at=now,
        )
    else:
        connection.enabled = bool(payload.enabled)
        connection.issuer_url = (payload.issuer_url or "").strip() or None
        connection.client_id = (payload.client_id or "").strip() or None
        if payload.client_secret_ref is not None:
            connection.client_secret_ref = (payload.client_secret_ref or "").strip() or None
        connection.audience = (payload.audience or "").strip() or None
        role = (payload.default_role or "viewer").strip().lower()
        connection.default_role = role if role in ROLE_VALUES else "viewer"
        connection.jit_enabled = bool(payload.jit_enabled)
        connection.allow_email_link = bool(payload.allow_email_link)
        connection.config = dict(payload.config or {})
        connection.updated_at = now
    if connection.default_role not in ROLE_VALUES:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported default role",
            details={"default_role": connection.default_role},
        )
    session.add(connection)
    return connection


def _create_scim_token_secret() -> str:
    prefix = (get_settings().scim_token_prefix or "rscim_").strip() or "rscim_"
    return f"{prefix}{secrets.token_urlsafe(32)}"


def _serialize_scim_token(token: ScimToken, raw_secret: str | None = None) -> ScimTokenView:
    return ScimTokenView(
        id=token.id,
        org_id=token.org_id,
        token_hint=token.token_hint,
        scopes=list(token.scopes or []),
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        token=raw_secret,
    )


def _parse_scim_bearer(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    if not raw:
        raise unauthorized("SCIM bearer token is required")
    scheme, _, token = raw.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized("Invalid SCIM bearer token")
    return token.strip()


def _resolve_scim_token(session: Session, token_value: str) -> ScimToken:
    token_hash = _hash_token(token_value)
    token = session.exec(select(ScimToken).where(ScimToken.token_hash == token_hash)).first()
    if not token or token.revoked_at is not None:
        raise unauthorized("Invalid SCIM token")
    token.last_used_at = _now()
    token.updated_at = _now()
    session.add(token)
    session.commit()
    session.refresh(token)
    return token


def _active_membership_count(session: Session, org_id: UUID) -> int:
    rows = session.exec(select(OrgMembership).where(OrgMembership.org_id == org_id)).all()
    return len(rows)


def _ensure_org_seat_available(session: Session, org_id: UUID) -> None:
    org = session.get(Organization, org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(org_id)})
    seat_limit = max(1, int(org.seat_limit or 1))
    if _active_membership_count(session, org_id) >= seat_limit:
        raise conflict("Seat limit reached", details={"seat_limit": seat_limit})


def _role_for_groups(session: Session, org_id: UUID, groups: list[str], default_role: str) -> str:
    normalized = {(group or "").strip() for group in groups if (group or "").strip()}
    if not normalized:
        return default_role
    mappings = session.exec(select(RoleMapping).where((RoleMapping.org_id == org_id) & (RoleMapping.provider == "okta"))).all()
    for mapping in mappings:
        if mapping.external_value in normalized and (mapping.role or "").strip().lower() in ROLE_VALUES:
            return mapping.role.strip().lower()
    return default_role


def _scim_user_resource(user: User, membership: OrgMembership | None) -> dict[str, Any]:
    display_name = (user.display_name or "").strip() or user.email
    return {
        "schemas": [SCIM_USER_SCHEMA],
        "id": str(user.id),
        "userName": user.email,
        "name": {"formatted": display_name},
        "emails": [{"value": user.email, "primary": True}],
        "active": bool(membership and user.is_active),
        "meta": {"resourceType": "User"},
    }


def _extract_scim_email(payload: dict[str, Any]) -> str:
    direct = _normalize_email(str(payload.get("userName") or ""))
    if direct:
        return direct
    emails = payload.get("emails")
    if isinstance(emails, list):
        for item in emails:
            if isinstance(item, dict):
                value = _normalize_email(str(item.get("value") or ""))
                if value:
                    return value
    return ""


def _extract_scim_display_name(payload: dict[str, Any]) -> str | None:
    name = payload.get("name")
    if isinstance(name, dict):
        formatted = (name.get("formatted") or "").strip()
        if formatted:
            return formatted
    display_name = (payload.get("displayName") or "").strip()
    return display_name or None


def _scim_group_resource(mapping: RoleMapping, members: list[str] | None = None) -> dict[str, Any]:
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": str(mapping.id),
        "displayName": mapping.external_value,
        "members": [{"value": member_id} for member_id in (members or [])],
        "meta": {"resourceType": "Group"},
    }


def _issue_tokens(*, user_id: UUID, org_id: UUID, role: str) -> dict[str, Any]:
    return {
        "access_token": create_access_token(user_id=user_id, org_id=org_id, role=role),
        "refresh_token": create_refresh_token(user_id=user_id, org_id=org_id, role=role),
        "token_type": "bearer",
        "user_id": str(user_id),
        "org_id": str(org_id),
        "role": role,
    }


@router.get(
    "/orgs/{org_id}/sso/config",
    response_model=SsoConfigView,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_org_sso_config(org_id: UUID, session: SessionDep, principal: PrincipalDep) -> SsoConfigView:
    _require_org_manager(session, principal, org_id)
    org = session.get(Organization, org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(org_id)})
    connection = session.exec(select(SsoConnection).where(SsoConnection.org_id == org_id)).first()
    return _serialize_sso_config(connection, org_id)


@router.put(
    "/orgs/{org_id}/sso/config",
    response_model=SsoConfigView,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_org_sso_config(org_id: UUID, payload: SsoConfigUpdateRequest, session: SessionDep, principal: PrincipalDep) -> SsoConfigView:
    _require_org_manager(session, principal, org_id)
    if not session.get(Organization, org_id):
        raise not_found("Organization not found", {"org_id": str(org_id)})
    connection = _upsert_sso_connection(session, org_id, payload)
    _emit_audit(
        session,
        org_id=org_id,
        actor_user_id=principal.user_id,
        event_type="sso.config_updated",
        entity_type="sso_connection",
        entity_id=str(connection.id),
        payload={
            "provider": "okta",
            "enabled": connection.enabled,
            "default_role": connection.default_role,
            "jit_enabled": connection.jit_enabled,
        },
    )
    session.commit()
    session.refresh(connection)
    return _serialize_sso_config(connection, org_id)


@router.post(
    "/orgs/{org_id}/sso/scim-tokens",
    response_model=ScimTokenView,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def create_org_scim_token(
    org_id: UUID,
    payload: ScimTokenCreateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> ScimTokenView:
    _require_org_manager(session, principal, org_id)
    if not session.get(Organization, org_id):
        raise not_found("Organization not found", {"org_id": str(org_id)})
    raw = _create_scim_token_secret()
    token = ScimToken(
        org_id=org_id,
        created_by_user_id=principal.user_id,
        token_hint=_mask_token(raw),
        token_hash=_hash_token(raw),
        scopes=list(payload.scopes or SCIM_SCOPE_DEFAULTS),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(token)
    _emit_audit(
        session,
        org_id=org_id,
        actor_user_id=principal.user_id,
        event_type="scim.token_created",
        entity_type="scim_token",
        entity_id=str(token.id),
        payload={"scopes": list(token.scopes or [])},
    )
    session.commit()
    session.refresh(token)
    return _serialize_scim_token(token, raw_secret=raw)


@router.delete(
    "/orgs/{org_id}/sso/scim-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def revoke_org_scim_token(org_id: UUID, token_id: UUID, session: SessionDep, principal: PrincipalDep) -> Response:
    _require_org_manager(session, principal, org_id)
    token = session.get(ScimToken, token_id)
    if not token or token.org_id != org_id:
        raise not_found("SCIM token not found", {"token_id": str(token_id)})
    token.revoked_at = _now()
    token.updated_at = _now()
    session.add(token)
    _emit_audit(
        session,
        org_id=org_id,
        actor_user_id=principal.user_id,
        event_type="scim.token_revoked",
        entity_type="scim_token",
        entity_id=str(token.id),
        payload={},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/auth/sso/okta/start",
    response_model=SsoStartResponse,
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def start_okta_sso(
    session: SessionDep,
    principal: PrincipalDep,
    redirect_to: str | None = Query(default=None),
) -> SsoStartResponse:
    if not principal.org_id:
        raise unauthorized("Organization authentication is required")
    org = session.get(Organization, principal.org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(principal.org_id)})
    connection = session.exec(select(SsoConnection).where(SsoConnection.org_id == principal.org_id)).first()
    if not connection or not connection.enabled:
        raise conflict("Okta SSO is not enabled for this organization")

    settings = get_settings()
    issuer = (connection.issuer_url or settings.okta_issuer_url or "").rstrip("/")
    client_id = (connection.client_id or settings.okta_client_id or "").strip()
    if not issuer or not client_id:
        raise conflict("Okta configuration is incomplete", details={"issuer_url": bool(issuer), "client_id": bool(client_id)})

    provider = f"okta:{principal.org_id}"
    state = create_oauth_state(provider=provider, redirect_to=redirect_to)
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/api/v1/auth/sso/okta/callback"
    authorize_url = (
        f"{issuer}/v1/authorize"
        f"?client_id={client_id}"
        "&response_type=code"
        "&scope=openid%20profile%20email%20groups"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return SsoStartResponse(
        provider="okta",
        authorize_url=authorize_url,
        state=state,
        redirect_uri=redirect_uri,
        org_id=principal.org_id,
    )


@router.get(
    "/auth/sso/okta/callback",
    tags=["Auth"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def okta_sso_callback(
    state: str,
    session: SessionDep,
    code: str | None = Query(default=None),
    email: str | None = Query(default=None),
    sub: str | None = Query(default=None),
    groups: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> dict[str, Any]:
    if error:
        raise unauthorized("Okta authentication failed", details={"error": error})
    provider, _redirect = parse_oauth_state(state)
    if not provider.startswith("okta:"):
        raise unauthorized("Invalid SSO state provider")
    org_id = UUID(provider.split(":", 1)[1])
    org = session.get(Organization, org_id)
    if not org:
        raise not_found("Organization not found", {"org_id": str(org_id)})

    connection = session.exec(select(SsoConnection).where(SsoConnection.org_id == org_id)).first()
    if not connection or not connection.enabled:
        raise conflict("Okta SSO is not enabled for this organization")

    effective_email = _normalize_email(email)
    if not effective_email and code and code.startswith("dev-email:"):
        effective_email = _normalize_email(code.split(":", 1)[1])
    if not effective_email:
        raise unauthorized("Unable to resolve user email from Okta callback")

    user = session.exec(select(User).where(User.email == effective_email)).first()
    if user is None:
        if not connection.jit_enabled:
            raise unauthorized("JIT provisioning is disabled for this organization")
        user = User(email=effective_email, display_name=effective_email.split("@")[0], is_active=True, created_at=_now(), updated_at=_now())
        session.add(user)
        session.commit()
        session.refresh(user)

    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == org_id) & (OrgMembership.user_id == user.id))
    ).first()
    group_values = [item.strip() for item in (groups or "").split(",") if item.strip()]
    desired_role = _role_for_groups(session, org_id, group_values, connection.default_role)
    if membership is None:
        _ensure_org_seat_available(session, org_id)
        membership = OrgMembership(org_id=org_id, user_id=user.id, role=desired_role, created_at=_now(), updated_at=_now())
        session.add(membership)
    elif desired_role in ROLE_VALUES and membership.role != desired_role:
        membership.role = desired_role
        membership.updated_at = _now()
        session.add(membership)

    oauth_account = session.exec(
        select(OAuthAccount).where((OAuthAccount.provider == "okta") & (OAuthAccount.user_id == user.id))
    ).first()
    provider_subject = (sub or f"okta-{user.id}").strip()
    if oauth_account is None:
        oauth_account = OAuthAccount(
            user_id=user.id,
            provider="okta",
            provider_subject=provider_subject,
            email=user.email,
            created_at=_now(),
            updated_at=_now(),
        )
    else:
        oauth_account.provider_subject = provider_subject
        oauth_account.email = user.email
        oauth_account.updated_at = _now()
    session.add(oauth_account)

    identity = session.exec(
        select(ScimIdentity).where(
            (ScimIdentity.org_id == org_id)
            & (ScimIdentity.provider == "okta")
            & (ScimIdentity.external_id == provider_subject)
            & (ScimIdentity.resource_type == "user")
        )
    ).first()
    if identity is None:
        identity = ScimIdentity(
            org_id=org_id,
            user_id=user.id,
            provider="okta",
            external_id=provider_subject,
            resource_type="user",
            email=user.email,
            active=True,
            created_at=_now(),
            updated_at=_now(),
        )
    else:
        identity.user_id = user.id
        identity.email = user.email
        identity.active = True
        identity.updated_at = _now()
    session.add(identity)

    _emit_audit(
        session,
        org_id=org_id,
        actor_user_id=user.id,
        event_type="sso.okta_login",
        entity_type="user",
        entity_id=str(user.id),
        payload={"groups": group_values, "role": membership.role},
    )
    session.commit()
    session.refresh(membership)
    return _issue_tokens(user_id=user.id, org_id=org_id, role=membership.role)


@router.get("/scim/v2/Users", tags=["Auth"])
def scim_list_users(
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    filter: str | None = Query(default=None),
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    memberships = session.exec(select(OrgMembership).where(OrgMembership.org_id == token.org_id)).all()
    users: list[dict[str, Any]] = []
    for membership in memberships:
        user = session.get(User, membership.user_id)
        if not user:
            continue
        if filter and "userName eq" in filter:
            needle = filter.split("userName eq", 1)[1].strip().strip('"').strip("'")
            if _normalize_email(needle) != _normalize_email(user.email):
                continue
        users.append(_scim_user_resource(user, membership))
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": len(users), "Resources": users}


@router.post("/scim/v2/Users", tags=["Auth"], status_code=status.HTTP_201_CREATED)
def scim_create_user(
    payload: Annotated[dict[str, Any], Body()],
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    email = _extract_scim_email(payload)
    if not email:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="SCIM user payload is missing userName/email",
        )
    display_name = _extract_scim_display_name(payload)
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, display_name=display_name, is_active=True, created_at=_now(), updated_at=_now())
        session.add(user)
        session.commit()
        session.refresh(user)
    elif display_name:
        user.display_name = display_name
        user.updated_at = _now()
        session.add(user)

    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.user_id == user.id))
    ).first()
    if membership is None:
        _ensure_org_seat_available(session, token.org_id)
        membership = OrgMembership(org_id=token.org_id, user_id=user.id, role="viewer", created_at=_now(), updated_at=_now())
        session.add(membership)

    external_id = str(payload.get("externalId") or payload.get("id") or user.id)
    identity = session.exec(
        select(ScimIdentity).where(
            (ScimIdentity.org_id == token.org_id)
            & (ScimIdentity.provider == "okta")
            & (ScimIdentity.external_id == external_id)
            & (ScimIdentity.resource_type == "user")
        )
    ).first()
    if identity is None:
        identity = ScimIdentity(
            org_id=token.org_id,
            user_id=user.id,
            provider="okta",
            external_id=external_id,
            resource_type="user",
            email=user.email,
            active=True,
            attributes={"source": "scim"},
            created_at=_now(),
            updated_at=_now(),
        )
    else:
        identity.user_id = user.id
        identity.email = user.email
        identity.active = True
        identity.updated_at = _now()
    session.add(identity)
    _emit_audit(
        session,
        org_id=token.org_id,
        actor_user_id=None,
        event_type="scim.user_upserted",
        entity_type="user",
        entity_id=str(user.id),
        payload={"external_id": external_id, "email": email},
    )
    session.commit()
    session.refresh(user)
    return _scim_user_resource(user, membership)


@router.patch("/scim/v2/Users/{user_id}", tags=["Auth"])
def scim_patch_user(
    user_id: UUID,
    payload: Annotated[dict[str, Any], Body()],
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    user = session.get(User, user_id)
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.user_id == user_id))
    ).first()
    if not user or not membership:
        raise not_found("SCIM user not found", {"user_id": str(user_id)})

    operations = payload.get("Operations") if isinstance(payload.get("Operations"), list) else []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "").strip().lower()
        path = str(operation.get("path") or "").strip().lower()
        value = operation.get("value")
        if op in {"replace", "add"} and path in {"active", "urn:ietf:params:scim:schemas:core:2.0:user:active"}:
            is_active = bool(value)
            user.is_active = is_active
            user.updated_at = _now()
            if not is_active and membership:
                session.delete(membership)
                membership = None
            elif is_active and membership is None:
                _ensure_org_seat_available(session, token.org_id)
                membership = OrgMembership(org_id=token.org_id, user_id=user.id, role="viewer", created_at=_now(), updated_at=_now())
                session.add(membership)
        elif op in {"replace", "add"} and path in {"username", "userName".lower()}:
            maybe_email = _normalize_email(str(value or ""))
            if maybe_email:
                user.email = maybe_email
                user.updated_at = _now()
        elif op in {"replace", "add"} and path in {"name.formatted", "displayname"}:
            display_name = (str(value or "")).strip()
            if display_name:
                user.display_name = display_name
                user.updated_at = _now()

    session.add(user)
    session.commit()
    current_membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.user_id == user.id))
    ).first()
    return _scim_user_resource(user, current_membership)


@router.delete("/scim/v2/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
def scim_delete_user(
    user_id: UUID,
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    membership = session.exec(
        select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.user_id == user_id))
    ).first()
    if membership:
        session.delete(membership)
    identities = session.exec(
        select(ScimIdentity).where(
            (ScimIdentity.org_id == token.org_id) & (ScimIdentity.user_id == user_id) & (ScimIdentity.resource_type == "user")
        )
    ).all()
    for identity in identities:
        identity.active = False
        identity.updated_at = _now()
        session.add(identity)
    _emit_audit(
        session,
        org_id=token.org_id,
        actor_user_id=None,
        event_type="scim.user_deleted",
        entity_type="user",
        entity_id=str(user_id),
        payload={},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/scim/v2/Groups", tags=["Auth"])
def scim_list_groups(
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    mappings = session.exec(
        select(RoleMapping).where((RoleMapping.org_id == token.org_id) & (RoleMapping.provider == "okta")).order_by(RoleMapping.external_value.asc())
    ).all()
    resources = []
    for mapping in mappings:
        members = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.role == mapping.role))
        ).all()
        resources.append(_scim_group_resource(mapping, members=[str(item.user_id) for item in members]))
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"], "totalResults": len(resources), "Resources": resources}


@router.post("/scim/v2/Groups", tags=["Auth"], status_code=status.HTTP_201_CREATED)
def scim_create_group(
    payload: Annotated[dict[str, Any], Body()],
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    display_name = (str(payload.get("displayName") or "")).strip()
    if not display_name:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="SCIM group displayName is required",
        )

    desired_role = (str(payload.get("role") or "viewer")).strip().lower()
    if desired_role not in ROLE_VALUES:
        desired_role = "viewer"

    mapping = session.exec(
        select(RoleMapping).where(
            (RoleMapping.org_id == token.org_id) & (RoleMapping.provider == "okta") & (RoleMapping.external_value == display_name)
        )
    ).first()
    now = _now()
    if mapping is None:
        mapping = RoleMapping(org_id=token.org_id, provider="okta", external_value=display_name, role=desired_role, created_at=now, updated_at=now)
    else:
        mapping.role = desired_role
        mapping.updated_at = now
    session.add(mapping)

    external_id = (str(payload.get("externalId") or display_name)).strip()
    identity = session.exec(
        select(ScimIdentity).where(
            (ScimIdentity.org_id == token.org_id)
            & (ScimIdentity.provider == "okta")
            & (ScimIdentity.external_id == external_id)
            & (ScimIdentity.resource_type == "group")
        )
    ).first()
    if identity is None:
        identity = ScimIdentity(
            org_id=token.org_id,
            provider="okta",
            external_id=external_id,
            resource_type="group",
            group_name=display_name,
            active=True,
            attributes={"role": desired_role},
            created_at=now,
            updated_at=now,
        )
    else:
        identity.group_name = display_name
        identity.active = True
        identity.attributes = {"role": desired_role}
        identity.updated_at = now
    session.add(identity)
    session.commit()
    session.refresh(mapping)
    return _scim_group_resource(mapping)


@router.patch("/scim/v2/Groups/{group_id}", tags=["Auth"])
def scim_patch_group(
    group_id: UUID,
    payload: Annotated[dict[str, Any], Body()],
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> dict[str, Any]:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    mapping = session.get(RoleMapping, group_id)
    if not mapping or mapping.org_id != token.org_id:
        raise not_found("SCIM group not found", {"group_id": str(group_id)})

    operations = payload.get("Operations") if isinstance(payload.get("Operations"), list) else []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or "").strip().lower()
        if op not in {"add", "replace"}:
            continue
        path = str(operation.get("path") or "").strip().lower()
        value = operation.get("value")
        if path in {"displayname", "displayName".lower()}:
            display_name = (str(value or "")).strip()
            if display_name:
                mapping.external_value = display_name
        elif path in {"role", "members"}:
            if path == "role":
                role = (str(value or "")).strip().lower()
                if role in ROLE_VALUES:
                    mapping.role = role
            elif isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    user_id = item.get("value")
                    if not user_id:
                        continue
                    try:
                        member_uuid = UUID(str(user_id))
                    except ValueError:
                        continue
                    membership = session.exec(
                        select(OrgMembership).where((OrgMembership.org_id == token.org_id) & (OrgMembership.user_id == member_uuid))
                    ).first()
                    if membership:
                        membership.role = mapping.role
                        membership.updated_at = _now()
                        session.add(membership)
    mapping.updated_at = _now()
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    return _scim_group_resource(mapping)


@router.delete("/scim/v2/Groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
def scim_delete_group(
    group_id: UUID,
    session: SessionDep,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response:
    token = _resolve_scim_token(session, _parse_scim_bearer(authorization))
    mapping = session.get(RoleMapping, group_id)
    if not mapping or mapping.org_id != token.org_id:
        raise not_found("SCIM group not found", {"group_id": str(group_id)})
    session.delete(mapping)
    identities = session.exec(
        select(ScimIdentity).where(
            (ScimIdentity.org_id == token.org_id) & (ScimIdentity.resource_type == "group") & (ScimIdentity.group_name == mapping.external_value)
        )
    ).all()
    for identity in identities:
        identity.active = False
        identity.updated_at = _now()
        session.add(identity)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
