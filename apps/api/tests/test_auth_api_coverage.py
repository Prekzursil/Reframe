"""Branch-coverage tests for :mod:`app.auth_api`: OAuth, login/refresh, orgs, keys, invites."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app import auth_api
from app.config import get_settings
from app.security import create_oauth_state, create_refresh_token


def _register(client, *, email: str, organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": "Password123!"}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _enable_oauth(monkeypatch, *, google=True, github=True) -> None:
    monkeypatch.setenv("REFRAME_ENABLE_OAUTH", "true")
    if google:
        monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_ID", "g-id")
        monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_SECRET", "g-secret")
    if github:
        monkeypatch.setenv("REFRAME_OAUTH_GITHUB_CLIENT_ID", "gh-id")
        monkeypatch.setenv("REFRAME_OAUTH_GITHUB_CLIENT_SECRET", "gh-secret")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# register / login / refresh edge cases
# ---------------------------------------------------------------------------


def test_register_invalid_email(test_client):
    client, *_ = test_client
    resp = client.post("/api/v1/auth/register", json={"email": "noatsign", "password": "Password123!"})
    assert resp.status_code == 422, resp.text


def test_register_short_password(test_client):
    client, *_ = test_client
    resp = client.post("/api/v1/auth/register", json={"email": "p@test.dev", "password": "short"})
    assert resp.status_code == 422, resp.text


def test_register_duplicate_email(test_client):
    client, *_ = test_client
    _register(client, email="dup@test.dev")
    resp = client.post("/api/v1/auth/register", json={"email": "dup@test.dev", "password": "Password123!"})
    assert resp.status_code == 409, resp.text


def test_login_success_and_bad_credentials(test_client):
    client, *_ = test_client
    _register(client, email="login@test.dev")
    ok = client.post("/api/v1/auth/login", json={"email": "login@test.dev", "password": "Password123!"})
    assert ok.status_code == 200, ok.text
    bad = client.post("/api/v1/auth/login", json={"email": "login@test.dev", "password": "wrong"})
    assert bad.status_code == 401, bad.text
    missing = client.post("/api/v1/auth/login", json={"email": "ghost@test.dev", "password": "x"})
    assert missing.status_code == 401, missing.text


def test_refresh_success_and_invalid(test_client):
    client, *_ = test_client
    user = _register(client, email="refresh@test.dev")
    ok = client.post("/api/v1/auth/refresh", json={"refresh_token": user["refresh_token"]})
    assert ok.status_code == 200, ok.text
    bad = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-token"})
    assert bad.status_code == 401, bad.text


def test_refresh_invalid_context_missing_user(test_client):
    client, *_ = test_client
    # A well-formed refresh token for a non-existent user -> invalid context.
    token = create_refresh_token(user_id=uuid4(), org_id=uuid4(), role="owner")
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert resp.status_code == 401, resp.text


def test_logout_and_me(test_client):
    client, *_ = test_client
    user = _register(client, email="me@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    assert client.post("/api/v1/auth/logout").status_code == 204
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert client.get("/api/v1/auth/me").status_code == 401  # no auth


# ---------------------------------------------------------------------------
# OAuth start
# ---------------------------------------------------------------------------


def test_oauth_start_disabled(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_ENABLE_OAUTH", "false")
    get_settings.cache_clear()
    resp = client.get("/api/v1/auth/oauth/google/start")
    assert resp.status_code == 400, resp.text


def test_oauth_start_unsupported_provider(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    resp = client.get("/api/v1/auth/oauth/twitter/start")
    assert resp.status_code == 400, resp.text


def test_oauth_start_not_configured(test_client, monkeypatch):
    client, *_ = test_client
    # OAuth enabled but no client id/secret for google.
    monkeypatch.setenv("REFRAME_ENABLE_OAUTH", "true")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()
    resp = client.get("/api/v1/auth/oauth/google/start")
    assert resp.status_code == 400, resp.text


def test_oauth_start_google_and_github(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    g = client.get("/api/v1/auth/oauth/google/start?redirect_to=/dash")
    assert g.status_code == 200, g.text
    assert "accounts.google.com" in g.json()["authorize_url"]
    gh = client.get("/api/v1/auth/oauth/github/start")
    assert gh.status_code == 200, gh.text
    assert "github.com/login/oauth" in gh.json()["authorize_url"]


# ---------------------------------------------------------------------------
# OAuth callback (mocking the httpx exchange seam)
# ---------------------------------------------------------------------------


def test_oauth_callback_state_mismatch(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    state = create_oauth_state(provider="github", redirect_to=None)  # wrong provider
    resp = client.get(f"/api/v1/auth/oauth/google/callback?code=c&state={state}")
    assert resp.status_code == 401, resp.text


def test_oauth_callback_google_creates_user(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_api,
        "_oauth_exchange_code",
        lambda cfg, code: ("access-tok", {"sub": "google-123", "email": "g@oauth.dev", "name": "G User"}),
    )
    state = create_oauth_state(provider="google", redirect_to=None)
    resp = client.get(f"/api/v1/auth/oauth/google/callback?code=authcode&state={state}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


def test_oauth_callback_github_uses_primary_email_fallback(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_api,
        "_oauth_exchange_code",
        lambda cfg, code: ("access-tok", {"id": "gh-9", "login": "octocat", "email": None}),
    )
    monkeypatch.setattr(auth_api, "_fetch_github_primary_email", lambda token: "octo@github.dev")
    state = create_oauth_state(provider="github", redirect_to=None)
    resp = client.get(f"/api/v1/auth/oauth/github/callback?code=authcode&state={state}")
    assert resp.status_code == 200, resp.text


def test_oauth_callback_missing_subject_or_email(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_api, "_oauth_exchange_code", lambda cfg, code: ("tok", {"sub": "", "email": ""})
    )
    state = create_oauth_state(provider="google", redirect_to=None)
    resp = client.get(f"/api/v1/auth/oauth/google/callback?code=c&state={state}")
    assert resp.status_code == 401, resp.text


def test_oauth_callback_existing_oauth_account_relogin(test_client, monkeypatch):
    client, *_ = test_client
    _enable_oauth(monkeypatch)
    monkeypatch.setattr(
        auth_api,
        "_oauth_exchange_code",
        lambda cfg, code: ("tok", {"sub": "google-relog", "email": "relog@oauth.dev", "name": "R"}),
    )
    state = create_oauth_state(provider="google", redirect_to=None)
    first = client.get(f"/api/v1/auth/oauth/google/callback?code=c1&state={state}")
    assert first.status_code == 200, first.text
    # Second login reuses the stored OAuthAccount + user.
    state2 = create_oauth_state(provider="google", redirect_to=None)
    second = client.get(f"/api/v1/auth/oauth/google/callback?code=c2&state={state2}")
    assert second.status_code == 200, second.text


# ---------------------------------------------------------------------------
# OAuth helper exchange (mock httpx.Client directly for the seam)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, json_data, *, success=True):
        self._json = json_data
        self.is_success = success

    def raise_for_status(self):
        if not self.is_success:
            raise RuntimeError("http error")

    def json(self):
        return self._json


class _FakeHttpClient:
    def __init__(self, token_json, user_json):
        self._token_json = token_json
        self._user_json = user_json

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, data=None, headers=None):
        return _FakeResp(self._token_json)

    def get(self, url, headers=None):
        return _FakeResp(self._user_json)


def test_oauth_exchange_code_success(monkeypatch):
    cfg = auth_api._oauth_provider_config("google")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_ID", "g")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_SECRET", "s")
    get_settings.cache_clear()

    monkeypatch.setattr(
        auth_api.httpx,
        "Client",
        lambda timeout=None: _FakeHttpClient({"access_token": "tok"}, {"sub": "1", "email": "x@y.z"}),
    )
    token, profile = auth_api._oauth_exchange_code(cfg, "code")
    assert token == "tok"
    assert profile["email"] == "x@y.z"


def test_oauth_exchange_code_no_access_token(monkeypatch):
    cfg = auth_api._oauth_provider_config("google")
    monkeypatch.setattr(
        auth_api.httpx,
        "Client",
        lambda timeout=None: _FakeHttpClient({}, {}),
    )
    with pytest.raises(auth_api.ApiError):
        auth_api._oauth_exchange_code(cfg, "code")


def test_fetch_github_primary_email(monkeypatch):
    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResp([{"email": "primary@gh.dev", "primary": True}])

    monkeypatch.setattr(auth_api.httpx, "Client", lambda timeout=None: _C())
    assert auth_api._fetch_github_primary_email("tok") == "primary@gh.dev"


def test_fetch_github_primary_email_failure(monkeypatch):
    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResp([], success=False)

    monkeypatch.setattr(auth_api.httpx, "Client", lambda timeout=None: _C())
    assert auth_api._fetch_github_primary_email("tok") == ""


def test_fetch_github_primary_email_no_primary(monkeypatch):
    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResp([{"email": "x@gh.dev", "primary": False}])

    monkeypatch.setattr(auth_api.httpx, "Client", lambda timeout=None: _C())
    assert auth_api._fetch_github_primary_email("tok") == ""


def test_oauth_provider_config_unsupported():
    with pytest.raises(auth_api.ApiError):
        auth_api._oauth_provider_config("linkedin")
