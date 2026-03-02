from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from app.database import get_engine
from app.models import OrgMembership, Organization, RoleMapping


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _create_scim_token(client, owner_headers: dict[str, str], org_id: str) -> str:
    response = client.post(
        f"/api/v1/orgs/{org_id}/sso/scim-tokens",
        headers=owner_headers,
        json={"scopes": ["users:write", "groups:write"]},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    token = payload.get("token")
    assert isinstance(token, str) and token
    return token


def _set_seat_limit(org_id: str, seat_limit: int) -> None:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        assert org is not None
        org.seat_limit = seat_limit
        session.add(org)
        session.commit()


def test_scim_users_and_groups_lifecycle(test_client):
    client, _enqueued, _worker, _media_root = test_client
    owner = _register(client, email="owner-scim@test.dev", organization_name="SCIM Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 3)

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

    scim_token = _create_scim_token(client, owner_headers, owner["org_id"])
    scim_headers = {"Authorization": f"Bearer {scim_token}"}

    create_user = client.post(
        "/api/v1/scim/v2/Users",
        headers=scim_headers,
        json={
            "userName": "scim-user@test.dev",
            "externalId": "okta-user-1",
            "name": {"formatted": "SCIM User"},
        },
    )
    assert create_user.status_code == 201, create_user.text
    created_user = create_user.json()
    assert created_user["userName"] == "scim-user@test.dev"
    user_id = created_user["id"]

    list_users = client.get("/api/v1/scim/v2/Users", headers=scim_headers)
    assert list_users.status_code == 200, list_users.text
    listed = list_users.json()
    assert listed["totalResults"] >= 1

    create_group = client.post(
        "/api/v1/scim/v2/Groups",
        headers=scim_headers,
        json={"displayName": "content-editors", "role": "editor", "externalId": "okta-group-1"},
    )
    assert create_group.status_code == 201, create_group.text
    group_id = create_group.json()["id"]

    patch_group = client.patch(
        f"/api/v1/scim/v2/Groups/{group_id}",
        headers=scim_headers,
        json={"Operations": [{"op": "add", "path": "members", "value": [{"value": user_id}]}]},
    )
    assert patch_group.status_code == 200, patch_group.text

    engine = get_engine()
    with Session(engine) as session:
        membership = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == UUID(owner["org_id"])) & (OrgMembership.user_id == UUID(user_id)))
        ).first()
        assert membership is not None
        assert membership.role == "editor"
        mapping = session.get(RoleMapping, UUID(group_id))
        assert mapping is not None
        assert mapping.role == "editor"

    patch_user = client.patch(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=scim_headers,
        json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
    )
    assert patch_user.status_code == 200, patch_user.text
    assert patch_user.json()["active"] is False

    delete_group = client.delete(f"/api/v1/scim/v2/Groups/{group_id}", headers=scim_headers)
    assert delete_group.status_code == 204, delete_group.text

    delete_user = client.delete(f"/api/v1/scim/v2/Users/{user_id}", headers=scim_headers)
    assert delete_user.status_code == 204, delete_user.text

    with Session(engine) as session:
        membership = session.exec(
            select(OrgMembership).where((OrgMembership.org_id == UUID(owner["org_id"])) & (OrgMembership.user_id == UUID(user_id)))
        ).first()
        assert membership is None
