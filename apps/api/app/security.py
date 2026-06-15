"""Password hashing and JWT token helpers for authentication and OAuth state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jwt import ExpiredSignatureError, InvalidTokenError

from app.config import get_settings

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
)

_INVALID_OAUTH_STATE_SIGNATURE = "Invalid OAuth state signature"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    """Return an Argon2 hash for the given non-empty password."""
    if not password:
        raise ValueError("Password is required")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    """Return True if the password matches the stored Argon2 hash."""
    if not password or not hashed_password:
        return False
    if hashed_password.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(hashed_password, password)
        except (VerificationError, InvalidHashError):
            return False
    return False


def create_access_token(*, user_id: UUID, org_id: Optional[UUID], role: str) -> str:
    """Return a signed JWT access token for the given user, org, and role."""
    settings = get_settings()
    now = _now_utc()
    access_ttl = timedelta(minutes=max(1, int(settings.jwt_access_ttl_minutes)))
    payload = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + access_ttl).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(*, user_id: UUID, org_id: Optional[UUID], role: str) -> str:
    """Return a signed JWT refresh token for the given user, org, and role."""
    settings = get_settings()
    now = _now_utc()
    payload = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "role": role,
        "typ": "refresh",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=max(1, int(settings.jwt_refresh_ttl_days)))).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_refresh_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an access token, returning its claims payload."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise ValueError("Invalid access token type")
    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a refresh token, returning its claims payload."""
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
    if payload.get("typ") != "refresh":
        raise ValueError("Invalid refresh token type")
    return payload


def create_oauth_state(
    *, provider: str, redirect_to: str | None = None, ttl_minutes: int = 10
) -> str:
    """Return a signed JWT encoding the OAuth provider and redirect target."""
    settings = get_settings()
    issued = _now_utc()
    expires = issued + timedelta(minutes=max(1, ttl_minutes))
    payload = {
        "typ": "oauth_state",
        "provider": provider.strip().lower(),
        "redirect_to": redirect_to or "",
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.oauth_state_secret, algorithm="HS256")


def parse_oauth_state(state: str) -> tuple[str, Optional[str]]:
    """Validate an OAuth state token and return its provider and redirect."""
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.oauth_state_secret, algorithms=["HS256"])
    except ExpiredSignatureError as exc:
        raise ValueError("OAuth state expired") from exc
    except InvalidTokenError as exc:
        raise ValueError(_INVALID_OAUTH_STATE_SIGNATURE) from exc

    if payload.get("typ") != "oauth_state":
        raise ValueError(_INVALID_OAUTH_STATE_SIGNATURE)

    provider = str(payload.get("provider") or "").strip().lower()
    if not provider:
        raise ValueError(_INVALID_OAUTH_STATE_SIGNATURE)
    redirect_to_raw = payload.get("redirect_to")
    if redirect_to_raw is not None and not isinstance(redirect_to_raw, str):
        raise ValueError(_INVALID_OAUTH_STATE_SIGNATURE)
    redirect_to = redirect_to_raw or ""
    return provider, (redirect_to or None)


@dataclass
class AuthPrincipal:
    """Authenticated request context: user, organization, and role."""

    user_id: Optional[UUID] = None
    org_id: Optional[UUID] = None
    role: str = "owner"
