from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID


@dataclass(frozen=True)
class ShareTokenPayload:
    asset_id: UUID
    project_id: UUID
    expires_at: datetime


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _normalize_secret(secret: str) -> bytes:
    cleaned = (secret or "").strip().encode("utf-8")
    if cleaned:
        return cleaned
    return b"reframe-dev-share-secret"


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_share_token(*, asset_id: UUID, project_id: UUID, expires_at: datetime, secret: str) -> str:
    exp = int(_to_utc(expires_at).timestamp())
    body = json.dumps(
        {
            "asset_id": str(asset_id),
            "project_id": str(project_id),
            "exp": exp,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(_normalize_secret(secret), body, hashlib.sha256).digest()
    return f"{_b64url_encode(body)}.{_b64url_encode(signature)}"


def build_share_token_with_ttl(*, asset_id: UUID, project_id: UUID, ttl_hours: int, secret: str) -> tuple[str, datetime]:
    hours = max(1, min(int(ttl_hours or 24), 24 * 30))
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    token = build_share_token(asset_id=asset_id, project_id=project_id, expires_at=expires_at, secret=secret)
    return token, expires_at


def parse_and_validate_share_token(token: str, *, secret: str, now: datetime | None = None) -> ShareTokenPayload:
    if not token or "." not in token:
        raise ValueError("Invalid token format")

    body_part, sig_part = token.split(".", 1)
    body = _b64url_decode(body_part)
    signature = _b64url_decode(sig_part)
    expected = hmac.new(_normalize_secret(secret), body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid token signature")

    payload = json.loads(body.decode("utf-8"))
    asset_id = UUID(str(payload["asset_id"]))
    project_id = UUID(str(payload["project_id"]))
    expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)

    current = _to_utc(now or datetime.now(timezone.utc))
    if expires_at < current:
        raise ValueError("Token expired")

    return ShareTokenPayload(asset_id=asset_id, project_id=project_id, expires_at=expires_at)
