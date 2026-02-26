from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID

from sqlmodel import Session, select

from app.database import get_engine
from app.models import Organization


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_org_seat_limit(org_id: str, seat_limit: int) -> None:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        assert org is not None
        org.seat_limit = seat_limit
        session.add(org)
        session.commit()


def _extract_invite_token(invite_url: str) -> str:
    parsed = urlparse(invite_url)
    values = parse_qs(parsed.query)
    token_values = values.get("token") or []
    assert token_values
    return token_values[0]


def test_invite_lifecycle_create_list_resolve_accept_and_revoke(test_client):
    client, _enqueued, _worker, _media_root = test_client

    owner = _register(client, email="owner@team.test", organization_name="Team Org")
    _set_org_seat_limit(owner["org_id"], 3)
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}

    create_resp = client.post(
        "/api/v1/orgs/invites",
        headers=owner_headers,
        json={"email": "editor@team.test", "role": "editor", "expires_in_days": 7},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["status"] == "pending"
    assert created["email"] == "editor@team.test"
    assert created["role"] == "editor"
    assert "invite_url" in created

    list_resp = client.get("/api/v1/orgs/invites", headers=owner_headers)
    assert list_resp.status_code == 200, list_resp.text
    invite_ids = [item["id"] for item in list_resp.json()]
    assert created["id"] in invite_ids

    token = _extract_invite_token(created["invite_url"])
    resolve_resp = client.get(f"/api/v1/orgs/invites/resolve?token={token}", headers=owner_headers)
    assert resolve_resp.status_code == 200, resolve_resp.text
    resolved = resolve_resp.json()
    assert resolved["email"] == "editor@team.test"
    assert resolved["role"] == "editor"
    assert resolved["status"] == "pending"

    invited_user = _register(client, email="editor@team.test", organization_name="Personal Workspace")
    invited_headers = {"Authorization": f"Bearer {invited_user['access_token']}"}

    accept_resp = client.post("/api/v1/orgs/invites/accept", headers=invited_headers, json={"token": token})
    assert accept_resp.status_code == 200, accept_resp.text
    accepted = accept_resp.json()
    assert accepted["org_id"] == owner["org_id"]
    assert accepted["role"] == "editor"

    switched_headers = {"Authorization": f"Bearer {accepted['access_token']}"}
    me_resp = client.get("/api/v1/auth/me", headers=switched_headers)
    assert me_resp.status_code == 200, me_resp.text
    me_payload = me_resp.json()
    assert me_payload["org_id"] == owner["org_id"]

    revoke_resp = client.post(
        f"/api/v1/orgs/invites/{created['id']}/revoke",
        headers=owner_headers,
    )
    assert revoke_resp.status_code == 200, revoke_resp.text



def test_seat_limit_blocks_invite_create_and_accept(test_client):
    client, _enqueued, _worker, _media_root = test_client

    owner = _register(client, email="owner-seat@team.test", organization_name="Seat Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}

    _set_org_seat_limit(owner["org_id"], 1)

    blocked = client.post(
        "/api/v1/orgs/invites",
        headers=owner_headers,
        json={"email": "invite-a@team.test", "role": "viewer"},
    )
    assert blocked.status_code in {409, 422}, blocked.text

    _set_org_seat_limit(owner["org_id"], 2)
    created = client.post(
        "/api/v1/orgs/invites",
        headers=owner_headers,
        json={"email": "invite-b@team.test", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    token = _extract_invite_token(created.json()["invite_url"])

    invitee = _register(client, email="invite-b@team.test", organization_name="Invitee Org")
    invitee_headers = {"Authorization": f"Bearer {invitee['access_token']}"}

    _set_org_seat_limit(owner["org_id"], 1)
    denied = client.post("/api/v1/orgs/invites/accept", headers=invitee_headers, json={"token": token})
    assert denied.status_code in {409, 422}, denied.text



def test_cannot_demote_or_remove_last_owner(test_client):
    client, _enqueued, _worker, _media_root = test_client

    owner = _register(client, email="solo-owner@team.test", organization_name="Solo Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}

    demote = client.patch(
        f"/api/v1/orgs/members/{owner['user_id']}/role",
        headers=owner_headers,
        json={"role": "viewer"},
    )
    assert demote.status_code in {400, 409}, demote.text

    remove = client.delete(f"/api/v1/orgs/members/{owner['user_id']}", headers=owner_headers)
    assert remove.status_code in {400, 409}, remove.text
