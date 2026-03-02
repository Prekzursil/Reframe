from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from app.database import get_engine
from app.models import Organization


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _set_seat_limit(org_id: str, seat_limit: int) -> None:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        assert org is not None
        org.seat_limit = seat_limit
        session.add(org)
        session.commit()


def test_okta_sso_config_start_and_callback_jit_login(test_client):
    client, _enqueued, _worker, _media_root = test_client
    owner = _register(client, email="owner-okta@test.dev", organization_name="Okta Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 3)

    config_resp = client.put(
        f"/api/v1/orgs/{owner['org_id']}/sso/config",
        headers=owner_headers,
        json={
            "enabled": True,
            "issuer_url": "https://example.okta.com/oauth2/default",
            "client_id": "okta-client",
            "client_secret_ref": "vault://okta/client-secret",
            "default_role": "editor",
            "jit_enabled": True,
            "allow_email_link": True,
            "config": {"env": "test"},
        },
    )
    assert config_resp.status_code == 200, config_resp.text
    config_payload = config_resp.json()
    assert config_payload["enabled"] is True
    assert config_payload["default_role"] == "editor"

    start_resp = client.get("/api/v1/auth/sso/okta/start", headers=owner_headers)
    assert start_resp.status_code == 200, start_resp.text
    start_payload = start_resp.json()
    assert start_payload["provider"] == "okta"
    assert "authorize" in start_payload["authorize_url"]
    assert start_payload["org_id"] == owner["org_id"]

    callback_resp = client.get(
        "/api/v1/auth/sso/okta/callback",
        params={
            "state": start_payload["state"],
            "email": "jit-user@test.dev",
            "sub": "okta-sub-123",
            "groups": "video-team,editors",
        },
    )
    assert callback_resp.status_code == 200, callback_resp.text
    callback_payload = callback_resp.json()
    assert callback_payload["org_id"] == owner["org_id"]
    assert callback_payload["role"] == "editor"
    assert callback_payload["access_token"]
    assert callback_payload["refresh_token"]

    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {callback_payload['access_token']}"},
    )
    assert me_resp.status_code == 200, me_resp.text
    me_payload = me_resp.json()
    assert me_payload["email"] == "jit-user@test.dev"
    assert me_payload["org_id"] == owner["org_id"]


def test_okta_callback_respects_org_seat_limits(test_client):
    client, _enqueued, _worker, _media_root = test_client
    owner = _register(client, email="owner-seat-okta@test.dev", organization_name="Seat Guard Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 1)

    config_resp = client.put(
        f"/api/v1/orgs/{owner['org_id']}/sso/config",
        headers=owner_headers,
        json={
            "enabled": True,
            "issuer_url": "https://example.okta.com/oauth2/default",
            "client_id": "okta-client",
            "default_role": "viewer",
            "jit_enabled": True,
            "allow_email_link": True,
            "config": {},
        },
    )
    assert config_resp.status_code == 200, config_resp.text

    start_resp = client.get("/api/v1/auth/sso/okta/start", headers=owner_headers)
    assert start_resp.status_code == 200, start_resp.text
    state = start_resp.json()["state"]

    denied = client.get(
        "/api/v1/auth/sso/okta/callback",
        params={"state": state, "email": "blocked-seat@test.dev", "sub": "seat-sub-1"},
    )
    assert denied.status_code in {409, 422}, denied.text
