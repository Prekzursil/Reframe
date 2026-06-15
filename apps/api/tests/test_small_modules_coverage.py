"""Targeted unit tests for small support modules to complete branch coverage.

Covers: app.errors, app.security, app.share_links, app.cleanup, app.rate_limit,
app.logging_config, and the health endpoint in app.main.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app import cleanup as cleanup_module
from app import errors
from app import logging_config
from app import security
from app import share_links
from app.rate_limit import (
    RateLimiter,
    enforce_default_rate_limit,
    enforce_rate_limit,
    policy_limiters,
)


# ---------------------------------------------------------------------------
# app.errors
# ---------------------------------------------------------------------------


def test_error_factories_produce_expected_status_and_code():
    assert errors.not_found().status_code == 404
    assert errors.not_found().code == errors.ErrorCode.NOT_FOUND
    assert errors.conflict().status_code == 409
    assert errors.unauthorized().status_code == 401
    assert errors.unauthorized().code == errors.ErrorCode.UNAUTHORIZED
    assert errors.quota_exceeded().status_code == 429
    assert errors.quota_exceeded().code == errors.ErrorCode.QUOTA_EXCEEDED
    assert errors.server_error().status_code == 500
    assert errors.server_error().code == errors.ErrorCode.SERVER_ERROR
    assert errors.rate_limited().status_code == 429
    assert errors.rate_limited().code == errors.ErrorCode.RATE_LIMITED


def test_api_error_carries_details():
    err = errors.server_error("boom", details={"k": "v"})
    assert err.message == "boom"
    assert err.details == {"k": "v"}
    assert str(err) == "boom"


# ---------------------------------------------------------------------------
# app.security
# ---------------------------------------------------------------------------


def test_hash_password_requires_value():
    with pytest.raises(ValueError, match="Password is required"):
        security.hash_password("")


def test_hash_and_verify_password_roundtrip():
    hashed = security.hash_password("s3cret!")
    assert hashed.startswith("$argon2")
    assert security.verify_password("s3cret!", hashed) is True


def test_verify_password_false_for_missing_inputs():
    assert security.verify_password("", "hash") is False
    assert security.verify_password("pw", None) is False


def test_verify_password_false_for_wrong_password():
    hashed = security.hash_password("correct")
    assert security.verify_password("wrong", hashed) is False


def test_verify_password_false_for_non_argon_hash():
    assert security.verify_password("pw", "plaintext-not-argon") is False


def test_access_token_roundtrip():
    uid = uuid4()
    oid = uuid4()
    token = security.create_access_token(user_id=uid, org_id=oid, role="admin")
    payload = security.decode_access_token(token)
    assert payload["sub"] == str(uid)
    assert payload["org"] == str(oid)
    assert payload["role"] == "admin"
    assert payload["typ"] == "access"


def test_decode_access_token_rejects_wrong_type():
    import jwt

    settings = security.get_settings()
    # Sign with the access secret but with a non-access ``typ`` to hit the type guard.
    token = jwt.encode({"typ": "refresh", "sub": "x"}, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid access token type"):
        security.decode_access_token(token)


def test_refresh_token_roundtrip_and_none_org():
    token = security.create_refresh_token(user_id=uuid4(), org_id=None, role="owner")
    payload = security.decode_refresh_token(token)
    assert payload["org"] is None
    assert payload["typ"] == "refresh"


def test_decode_refresh_token_rejects_wrong_type():
    import jwt

    settings = security.get_settings()
    # Sign with the refresh secret but with a non-refresh ``typ`` to hit the type guard.
    token = jwt.encode(
        {"typ": "access", "sub": "x"}, settings.jwt_refresh_secret, algorithm="HS256"
    )
    with pytest.raises(ValueError, match="Invalid refresh token type"):
        security.decode_refresh_token(token)


def test_oauth_state_roundtrip_with_redirect():
    state = security.create_oauth_state(provider="Google", redirect_to="/dashboard")
    provider, redirect = security.parse_oauth_state(state)
    assert provider == "google"
    assert redirect == "/dashboard"


def test_oauth_state_roundtrip_without_redirect():
    state = security.create_oauth_state(provider="github")
    provider, redirect = security.parse_oauth_state(state)
    assert provider == "github"
    assert redirect is None


def test_parse_oauth_state_expired():
    import jwt

    settings = security.get_settings()
    now = security._now_utc()
    payload = {
        "typ": "oauth_state",
        "provider": "google",
        "redirect_to": "",
        "iat": int((now - timedelta(minutes=30)).timestamp()),
        "exp": int((now - timedelta(minutes=20)).timestamp()),
    }
    expired = jwt.encode(payload, settings.oauth_state_secret, algorithm="HS256")
    with pytest.raises(ValueError, match="OAuth state expired"):
        security.parse_oauth_state(expired)


def test_parse_oauth_state_invalid_signature():
    with pytest.raises(ValueError, match="Invalid OAuth state signature"):
        security.parse_oauth_state("not-a-valid-token")


def test_parse_oauth_state_wrong_type():
    import jwt

    settings = security.get_settings()
    now = security._now_utc()
    payload = {
        "typ": "access",
        "provider": "google",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }
    token = jwt.encode(payload, settings.oauth_state_secret, algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid OAuth state signature"):
        security.parse_oauth_state(token)


def test_parse_oauth_state_missing_provider():
    import jwt

    settings = security.get_settings()
    now = security._now_utc()
    payload = {
        "typ": "oauth_state",
        "provider": "",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }
    token = jwt.encode(payload, settings.oauth_state_secret, algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid OAuth state signature"):
        security.parse_oauth_state(token)


def test_parse_oauth_state_non_string_redirect():
    import jwt

    settings = security.get_settings()
    now = security._now_utc()
    payload = {
        "typ": "oauth_state",
        "provider": "google",
        "redirect_to": 123,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=10)).timestamp()),
    }
    token = jwt.encode(payload, settings.oauth_state_secret, algorithm="HS256")
    with pytest.raises(ValueError, match="Invalid OAuth state signature"):
        security.parse_oauth_state(token)


# ---------------------------------------------------------------------------
# app.share_links
# ---------------------------------------------------------------------------


def test_share_token_roundtrip():
    asset_id = uuid4()
    project_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    token = share_links.build_share_token(
        asset_id=asset_id, project_id=project_id, expires_at=expires, secret="sekret"
    )
    payload = share_links.parse_and_validate_share_token(token, secret="sekret")
    assert payload.asset_id == asset_id
    assert payload.project_id == project_id


def test_share_token_with_ttl_clamps():
    asset_id = uuid4()
    project_id = uuid4()
    token, expires = share_links.build_share_token_with_ttl(
        asset_id=asset_id, project_id=project_id, ttl_hours=0, secret="s"
    )
    # ttl 0 -> clamped to >= 1 hour in the future.
    assert expires > datetime.now(timezone.utc)
    payload = share_links.parse_and_validate_share_token(token, secret="s")
    assert payload.asset_id == asset_id


def test_normalize_secret_falls_back_to_default():
    # Empty secret -> the dev fallback secret is used for both sign and verify.
    asset_id = uuid4()
    project_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    token = share_links.build_share_token(
        asset_id=asset_id, project_id=project_id, expires_at=expires, secret=""
    )
    payload = share_links.parse_and_validate_share_token(token, secret="")
    assert payload.asset_id == asset_id


def test_to_utc_handles_naive_datetime():
    naive = datetime(2030, 1, 1, 12, 0, 0)
    asset_id = uuid4()
    project_id = uuid4()
    token = share_links.build_share_token(
        asset_id=asset_id, project_id=project_id, expires_at=naive, secret="s"
    )
    # Token built from naive expiry parses without error (naive treated as UTC).
    payload = share_links.parse_and_validate_share_token(
        token, secret="s", now=datetime(2029, 12, 31, tzinfo=timezone.utc)
    )
    assert payload.asset_id == asset_id


def test_parse_token_invalid_format():
    with pytest.raises(ValueError, match="Invalid token format"):
        share_links.parse_and_validate_share_token("no-dot-here", secret="s")
    with pytest.raises(ValueError, match="Invalid token format"):
        share_links.parse_and_validate_share_token("", secret="s")


def test_parse_token_invalid_signature():
    asset_id = uuid4()
    project_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    token = share_links.build_share_token(
        asset_id=asset_id, project_id=project_id, expires_at=expires, secret="correct"
    )
    with pytest.raises(ValueError, match="Invalid token signature"):
        share_links.parse_and_validate_share_token(token, secret="tampered")


def test_parse_token_expired():
    asset_id = uuid4()
    project_id = uuid4()
    expires = datetime.now(timezone.utc) - timedelta(hours=1)
    token = share_links.build_share_token(
        asset_id=asset_id, project_id=project_id, expires_at=expires, secret="s"
    )
    with pytest.raises(ValueError, match="Token expired"):
        share_links.parse_and_validate_share_token(token, secret="s")


# ---------------------------------------------------------------------------
# app.cleanup
# ---------------------------------------------------------------------------


def test_remove_old_files_noop_for_missing_dir(tmp_path: Path):
    cleanup_module._remove_old_files(tmp_path / "nope", timedelta(hours=1))


def test_remove_old_files_noop_for_non_dir(tmp_path: Path):
    file_path = tmp_path / "afile"
    file_path.write_text("x")
    cleanup_module._remove_old_files(file_path, timedelta(hours=1))


def test_remove_old_files_deletes_stale_keeps_fresh(tmp_path: Path):
    stale = tmp_path / "stale.txt"
    fresh = tmp_path / "fresh.txt"
    stale.write_text("old")
    fresh.write_text("new")
    # Backdate the stale file two hours.
    old_time = time.time() - 7200
    import os

    os.utime(stale, (old_time, old_time))
    cleanup_module._remove_old_files(tmp_path, timedelta(hours=1))
    assert not stale.exists()
    assert fresh.exists()


def test_remove_old_files_skips_subdirectories(tmp_path: Path):
    subdir = tmp_path / "child"
    subdir.mkdir()
    old_time = time.time() - 7200
    import os

    os.utime(subdir, (old_time, old_time))
    cleanup_module._remove_old_files(tmp_path, timedelta(hours=1))
    # Directories are skipped (only is_file entries are removed).
    assert subdir.exists()


def test_remove_old_files_swallows_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "boom.txt"
    target.write_text("x")
    old_time = time.time() - 7200
    import os

    os.utime(target, (old_time, old_time))

    real_unlink = Path.unlink

    def _raise_unlink(self, *args, **kwargs):
        if self.name == "boom.txt":
            raise OSError("locked")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _raise_unlink)
    # Should not raise even though unlink fails.
    cleanup_module._remove_old_files(tmp_path, timedelta(hours=1))


def test_start_cleanup_loop_creates_tmp_and_runs_once(tmp_path, monkeypatch):
    """Drive the loop body exactly once by raising out of time.sleep."""
    captured: dict = {}

    def _fake_thread_factory(*, target, daemon):
        captured["target"] = target
        captured["daemon"] = daemon

        class _T:
            def start(self_inner):
                captured["started"] = True

        return _T()

    monkeypatch.setattr(cleanup_module.threading, "Thread", _fake_thread_factory)

    thread = cleanup_module.start_cleanup_loop(str(tmp_path), interval_seconds=1, ttl_hours=2)
    assert thread is not None
    assert captured["daemon"] is True
    assert captured["started"] is True
    assert (tmp_path / "tmp").is_dir()

    # Run the inner loop body once: stub sleep to break the infinite while loop.
    class _StopLoop(Exception):
        pass

    def _sleep_then_stop(_seconds):
        raise _StopLoop

    monkeypatch.setattr(cleanup_module.time, "sleep", _sleep_then_stop)
    with pytest.raises(_StopLoop):
        captured["target"]()


# ---------------------------------------------------------------------------
# app.rate_limit
# ---------------------------------------------------------------------------


def test_rate_limiter_clamps_and_enforces():
    limiter = RateLimiter(limit=0, window_seconds=0)
    assert limiter.limit == 1
    assert limiter.window_seconds == 1
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False  # second hit exceeds limit of 1


def test_rate_limiter_evicts_old_hits(monkeypatch):
    limiter = RateLimiter(limit=1, window_seconds=10)
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    assert limiter.allow("k") is True
    now[0] += 20  # advance beyond window
    # old hit evicted -> allowed again
    assert limiter.allow("k") is True


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeURL:
    def __init__(self, path):
        self.path = path


class _FakeRequest:
    def __init__(self, host="1.2.3.4", path="/api/x", client=True):
        self.client = _FakeClient(host) if client else None
        self.url = _FakeURL(path)


def test_enforce_default_rate_limit_allows_then_blocks(monkeypatch):
    # Replace the default limiter with a tiny one to force a block deterministically.
    tight = RateLimiter(limit=1, window_seconds=60)
    monkeypatch.setitem(policy_limiters, "default", tight)
    req = _FakeRequest(host="9.9.9.9", path="/api/limited")
    asyncio.run(enforce_default_rate_limit(req))  # first allowed
    with pytest.raises(errors.ApiError) as exc:
        asyncio.run(enforce_default_rate_limit(req))
    assert exc.value.status_code == 429
    assert exc.value.details["policy"] == "default"
    assert exc.value.details["client"] == "9.9.9.9"


def test_enforce_rate_limit_factory_dependency(monkeypatch):
    tight = RateLimiter(limit=1, window_seconds=60)
    monkeypatch.setitem(policy_limiters, "uploads", tight)
    dependency = enforce_rate_limit("uploads")
    req = _FakeRequest(host="5.5.5.5", path="/api/upload")
    asyncio.run(dependency(req))  # first allowed
    with pytest.raises(errors.ApiError) as exc:
        asyncio.run(dependency(req))
    assert exc.value.details["policy"] == "uploads"


def test_enforce_policy_anonymous_client_and_unknown_policy(monkeypatch):
    from app.rate_limit import _enforce_policy

    tight = RateLimiter(limit=1, window_seconds=60)
    monkeypatch.setitem(policy_limiters, "default", tight)
    # client is None -> "anonymous"; unknown policy falls back to default limiter.
    req = _FakeRequest(client=False, path="/api/anon")
    _enforce_policy(req, "does-not-exist")
    with pytest.raises(errors.ApiError) as exc:
        _enforce_policy(req, "does-not-exist")
    assert exc.value.details["client"] == "anonymous"


# ---------------------------------------------------------------------------
# app.logging_config
# ---------------------------------------------------------------------------


def test_json_formatter_includes_extra_and_excludes_reserved():
    formatter = logging_config.JsonFormatter()
    record = logging.LogRecord(
        name="reframe.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.custom_field = "abc"
    record._private = "skip"
    import json

    out = json.loads(formatter.format(record))
    assert out["message"] == "hello world"
    assert out["custom_field"] == "abc"
    assert "_private" not in out
    assert "args" not in out


def test_json_formatter_includes_exception():
    formatter = logging_config.JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="reframe.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    import json

    out = json.loads(formatter.format(record))
    assert "exc_info" in out
    assert "ValueError" in out["exc_info"]


def test_setup_logging_plain_format_branch():
    """Cover the non-json (plain) handler branch by resetting the one-time guard."""
    logger = logging.getLogger("reframe")
    prev_configured = getattr(logger, "_reframe_configured", False)
    prev_handlers = list(logger.handlers)
    prev_propagate = logger.propagate
    prev_level = logger.level
    try:
        if hasattr(logger, "_reframe_configured"):
            delattr(logger, "_reframe_configured")
        logging_config.setup_logging(log_format="plain", log_level="DEBUG")
        assert getattr(logger, "_reframe_configured") is True
        assert logger.level == logging.DEBUG
        # A plain formatter was attached (not JsonFormatter).
        assert any(
            not isinstance(h.formatter, logging_config.JsonFormatter)
            for h in logger.handlers
            if h.formatter is not None
        )
    finally:
        # Restore the logger to its prior state to avoid cross-test pollution.
        logger.handlers = prev_handlers
        logger.propagate = prev_propagate
        logger.setLevel(prev_level)
        if prev_configured:
            setattr(logger, "_reframe_configured", True)
        elif hasattr(logger, "_reframe_configured"):
            delattr(logger, "_reframe_configured")


def test_setup_logging_json_format_branch():
    """Cover the json handler branch by resetting the one-time guard."""
    logger = logging.getLogger("reframe")
    prev_configured = getattr(logger, "_reframe_configured", False)
    prev_handlers = list(logger.handlers)
    prev_propagate = logger.propagate
    prev_level = logger.level
    try:
        if hasattr(logger, "_reframe_configured"):
            delattr(logger, "_reframe_configured")
        logging_config.setup_logging(log_format="json", log_level="INFO")
        assert getattr(logger, "_reframe_configured") is True
        assert any(
            isinstance(h.formatter, logging_config.JsonFormatter) for h in logger.handlers
        )
    finally:
        logger.handlers = prev_handlers
        logger.propagate = prev_propagate
        logger.setLevel(prev_level)
        if prev_configured:
            setattr(logger, "_reframe_configured", True)
        elif hasattr(logger, "_reframe_configured"):
            delattr(logger, "_reframe_configured")


def test_setup_logging_returns_early_when_already_configured():
    logger = logging.getLogger("reframe")
    setattr(logger, "_reframe_configured", True)
    before = list(logger.handlers)
    logging_config.setup_logging(log_format="json")
    # No new handler added because it short-circuits.
    assert logger.handlers == before


# ---------------------------------------------------------------------------
# app.main health endpoint
# ---------------------------------------------------------------------------


def test_health_endpoint(test_client):
    client, _, _, _ = test_client
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    # healthz alias also works
    assert client.get("/healthz").status_code == 200


def test_request_logging_middleware_logs_unhandled_exception(test_client):
    """An unhandled (non-ApiError) exception is logged by the middleware and re-raised.

    Covers the ``except Exception`` request_failed branch in ``app.main.log_requests``.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()

    @app.get("/_boom_test_route")
    def _boom():  # pragma: no cover - body executes via the request below
        raise RuntimeError("kaboom")

    with TestClient(app, raise_server_exceptions=False) as boom_client:
        resp = boom_client.get("/_boom_test_route")
    # The unhandled error surfaces as a 500 after the middleware logs and re-raises.
    assert resp.status_code == 500
