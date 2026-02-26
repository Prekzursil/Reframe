from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import jwt

from app.config import get_settings


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required")
    salt = os.urandom(16)
    iterations = 390_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, hashed_password: str | None) -> bool:
    if not password or not hashed_password:
        return False
    try:
        algo, iter_raw, salt_raw, digest_raw = hashed_password.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
    except Exception:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


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
    body = (
        f"{provider}|{int(issued.timestamp())}|{int((issued + timedelta(minutes=max(1, ttl_minutes))).timestamp())}|"
        f"{redirect_to or ''}"
    ).encode("utf-8")
    sig = hmac.new(settings.oauth_state_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(sig)}"


def parse_oauth_state(state: str) -> tuple[str, Optional[str]]:
    settings = get_settings()
    if "." not in state:
        raise ValueError("Invalid OAuth state format")
    body_raw, sig_raw = state.split(".", 1)
    body = _b64decode(body_raw)
    sig = _b64decode(sig_raw)
    expected = hmac.new(settings.oauth_state_secret.encode("utf-8"), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid OAuth state signature")
    provider, _issued_raw, expires_raw, redirect_to = body.decode("utf-8").split("|", 3)
    if int(expires_raw) < int(_now_utc().timestamp()):
        raise ValueError("OAuth state expired")
    return provider, (redirect_to or None)


@dataclass
class AuthPrincipal:
    user_id: Optional[UUID] = None
    org_id: Optional[UUID] = None
    role: str = "owner"
