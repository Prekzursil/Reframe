from __future__ import annotations

import base64
import hashlib
import os

import pytest

from app.security import create_oauth_state, hash_password, parse_oauth_state, verify_password


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _legacy_pbkdf2_sha512(password: str, *, iterations: int = 390_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha512${iterations}${_b64(salt)}${_b64(digest)}"


def test_hash_password_uses_argon2id_format():
    hashed = hash_password("CorrectHorseBatteryStaple123!")
    assert hashed.startswith("$argon2id$")


def test_verify_password_supports_legacy_pbkdf2_sha512():
    secret = "legacy-secret-42"
    hashed = _legacy_pbkdf2_sha512(secret)
    assert verify_password(secret, hashed) is True
    assert verify_password("wrong-secret", hashed) is False


def test_oauth_state_round_trip_and_tamper_guard():
    state = create_oauth_state(provider="github", redirect_to="http://localhost:5173/projects", ttl_minutes=5)
    provider, redirect_to = parse_oauth_state(state)
    assert provider == "github"
    assert redirect_to == "http://localhost:5173/projects"

    with pytest.raises(ValueError):
        parse_oauth_state(f"{state}tampered")
