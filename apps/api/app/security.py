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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required")
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not password or not hashed_password:
        return False
    if hashed_password.startswith("$argon2"):
        try:
            return _PASSWORD_HASHER.verify(hashed_password, password)
        except (VerificationError, InvalidHashError):
            return False
    return False


def create_access_token(*, user_id: UUID, org_id: Optional[UUID], role: str) -> str:
    settings = get_settings()
    now = _now_utc()
    payload = {
        "sub": str(user_id),
        "org": str(org_id) if org_id else None,
        "role": role,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=max(1, int(settings.jwt_access_ttl_minutes)))).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(*, user_id: UUID, org_id: Optional[UUID], role: str) -> str:
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
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise ValueError("Invalid access token type")
    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
    if payload.get("typ") != "refresh":
        raise ValueError("Invalid refresh token type")
    return payload


def create_oauth_state(*, provider: str, redirect_to: str | None = None, ttl_minutes: int = 10) -> str:
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
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.oauth_state_secret, algorithms=["HS256"])
    except ExpiredSignatureError as exc:
        raise ValueError("OAuth state expired") from exc
    except InvalidTokenError as exc:
        raise ValueError("Invalid OAuth state signature") from exc

    if payload.get("typ") != "oauth_state":
        raise ValueError("Invalid OAuth state signature")

    provider = str(payload.get("provider") or "").strip().lower()
    if not provider:
        raise ValueError("Invalid OAuth state signature")
    redirect_to_raw = payload.get("redirect_to")
    if redirect_to_raw is not None and not isinstance(redirect_to_raw, str):
        raise ValueError("Invalid OAuth state signature")
    redirect_to = redirect_to_raw or ""
    return provider, (redirect_to or None)


@dataclass
class AuthPrincipal:
    user_id: Optional[UUID] = None
    org_id: Optional[UUID] = None
    role: str = "owner"
