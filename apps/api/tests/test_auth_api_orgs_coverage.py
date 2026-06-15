"""Branch-coverage tests for :mod:`app.auth_api` org management, keys, and invites."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import Session

from app import auth_api
from app.database import get_engine
from app.models import Organization


def _register(client, *, email: str, organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": "Password123!"}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _set_seat_limit(org_id: str, seat_limit: int) -> None:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        org.seat_limit = seat_limit
        session.add(org)
        session.commit()


# ---------------------------------------------------------------------------
# org_me / list_orgs / create_org
# ---------------------------------------------------------------------------


def test_org_me_and_list_orgs(test_client):
    client, *_ = test_client
    user = _register(client, email="om@test.dev", organization_name="OM Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    me = client.get("/api/v1/orgs/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["members"]
    listed = client.get("/api/v1/orgs", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(o["org_id"] == user["org_id"] for o in listed.json())


def test_org_me_requires_auth(test_client):
    client, *_ = test_client
    assert client.get("/api/v1/orgs/me").status_code == 401
    assert client.get("/api/v1/orgs").status_code == 401


def test_create_org_and_validation(test_client):
    client, *_ = test_client
    user = _register(client, email="co@test.dev", organization_name="CO Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    ok = client.post("/api/v1/orgs", headers=headers, json={"name": "New Team", "seat_limit": 4})
    assert ok.status_code == 201, ok.text
    assert ok.json()["name"] == "New Team"
    # Missing name -> 422.
    bad = client.post("/api/v1/orgs", headers=headers, json={"name": "  "})
    assert bad.status_code == 422, bad.text
    # No auth -> 401.
    assert client.post("/api/v1/orgs", json={"name": "x"}).status_code == 401


def test_create_org_slug_collision(test_client):
    client, *_ = test_client
    user = _register(client, email="slug@test.dev", organization_name="Slug Org")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    a = client.post("/api/v1/orgs", headers=headers, json={"name": "Same Name", "slug": "dup-slug"})
    assert a.status_code == 201, a.text
    b = client.post("/api/v1/orgs", headers=headers, json={"name": "Same Name", "slug": "dup-slug"})
    assert b.status_code == 201, b.text
    assert a.json()["slug"] != b.json()["slug"]


# ---------------------------------------------------------------------------
# org members
# ---------------------------------------------------------------------------


def test_add_member_errors_and_success(test_client):
    client, *_ = test_client
    owner = _register(client, email="addm-owner@test.dev", organization_name="AddM Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 5)

    # invalid email
    assert (
        client.post(
            f"/api/v1/orgs/{org_id}/members", headers=headers, json={"email": "bad", "role": "viewer"}
        ).status_code
        == 422
    )
    # invalid role
    _register(client, email="addm-target@test.dev", organization_name="Target Personal")
    assert (
        client.post(
            f"/api/v1/orgs/{org_id}/members",
            headers=headers,
            json={"email": "addm-target@test.dev", "role": "wizard"},
        ).status_code
        == 422
    )
    # user not found
    assert (
        client.post(
            f"/api/v1/orgs/{org_id}/members",
            headers=headers,
            json={"email": "ghost-addm@test.dev", "role": "viewer"},
        ).status_code
        == 404
    )
    # success
    ok = client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "addm-target@test.dev", "role": "editor"},
    )
    assert ok.status_code == 201, ok.text
    # duplicate -> conflict
    dup = client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "addm-target@test.dev", "role": "editor"},
    )
    assert dup.status_code == 409, dup.text


def test_add_owner_member_requires_owner_manager(test_client):
    client, *_ = test_client
    owner = _register(client, email="ownadd-owner@test.dev", organization_name="OwnAdd Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 5)
    # Add an admin member, then have the admin try to add an owner.
    admin = _register(client, email="ownadd-admin@test.dev", organization_name="Admin Personal")
    client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "ownadd-admin@test.dev", "role": "admin"},
    )
    from app.security import create_access_token

    admin_token = create_access_token(
        user_id=UUID(admin["user_id"]), org_id=UUID(org_id), role="admin"
    )
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    _register(client, email="ownadd-newowner@test.dev", organization_name="NewOwner Personal")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=admin_headers,
        json={"email": "ownadd-newowner@test.dev", "role": "owner"},
    )
    assert resp.status_code == 401, resp.text


def test_add_member_seat_limit_reached(test_client):
    client, *_ = test_client
    owner = _register(client, email="seatlim-owner@test.dev", organization_name="SeatLim Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 1)  # owner already takes the single seat
    _register(client, email="seatlim-target@test.dev", organization_name="Target Personal")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "seatlim-target@test.dev", "role": "viewer"},
    )
    assert resp.status_code == 409, resp.text


def test_remove_org_member_last_owner_protected(test_client):
    client, *_ = test_client
    owner = _register(client, email="rmlast-owner@test.dev", organization_name="RmLast Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    # Removing the only owner -> conflict.
    resp = client.delete(
        f"/api/v1/orgs/{org_id}/members/{owner['user_id']}", headers=headers
    )
    assert resp.status_code == 409, resp.text
    # Removing a non-member -> 404.
    missing = client.delete(f"/api/v1/orgs/{org_id}/members/{uuid4()}", headers=headers)
    assert missing.status_code == 404, missing.text


# ---------------------------------------------------------------------------
# api keys
# ---------------------------------------------------------------------------


def test_api_key_lifecycle(test_client):
    client, *_ = test_client
    owner = _register(client, email="apikey@test.dev", organization_name="ApiKey Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]

    # missing name -> 422
    assert (
        client.post(f"/api/v1/orgs/{org_id}/api-keys", headers=headers, json={"name": "  "}).status_code
        == 422
    )
    created = client.post(
        f"/api/v1/orgs/{org_id}/api-keys",
        headers=headers,
        json={"name": "CI Key", "scopes": ["read", " "]},
    )
    assert created.status_code == 201, created.text
    key_id = created.json()["id"]
    assert created.json()["secret"]

    listed = client.get(f"/api/v1/orgs/{org_id}/api-keys", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(k["id"] == key_id for k in listed.json())

    # revoke twice (second is a no-op since already revoked)
    assert client.delete(f"/api/v1/orgs/{org_id}/api-keys/{key_id}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/orgs/{org_id}/api-keys/{key_id}", headers=headers).status_code == 204
    # revoke missing key -> 404
    assert (
        client.delete(f"/api/v1/orgs/{org_id}/api-keys/{uuid4()}", headers=headers).status_code == 404
    )


# ---------------------------------------------------------------------------
# audit events
# ---------------------------------------------------------------------------


def test_audit_events(test_client):
    client, *_ = test_client
    owner = _register(client, email="audit@test.dev", organization_name="Audit Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    # create_org emits an audit event for the new org.
    client.post("/api/v1/orgs", headers=headers, json={"name": "Audited Team"})
    resp = client.get("/api/v1/audit-events", headers=headers)
    assert resp.status_code == 200, resp.text
    assert client.get("/api/v1/audit-events").status_code == 401  # no auth


# ---------------------------------------------------------------------------
# invites
# ---------------------------------------------------------------------------


def test_invite_lifecycle(test_client):
    client, *_ = test_client
    owner = _register(client, email="inv-owner@test.dev", organization_name="Invite Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 5)

    # invalid email
    assert (
        client.post("/api/v1/orgs/invites", headers=headers, json={"email": "bad", "role": "viewer"}).status_code
        == 422
    )
    # invalid role
    assert (
        client.post(
            "/api/v1/orgs/invites", headers=headers, json={"email": "x@y.dev", "role": "boss"}
        ).status_code
        == 422
    )
    # invalid expiry
    assert (
        client.post(
            "/api/v1/orgs/invites",
            headers=headers,
            json={"email": "x@y.dev", "role": "viewer", "expires_in_days": 99},
        ).status_code
        == 422
    )
    # success
    created = client.post(
        "/api/v1/orgs/invites",
        headers=headers,
        json={"email": "invitee@team.dev", "role": "editor"},
    )
    assert created.status_code == 201, created.text
    token = created.json()["invite_url"].split("token=", 1)[1]
    invite_id = created.json()["id"]

    # NOTE: re-posting the same pending invite would exercise the duplicate-detection
    # branch at auth_api.py:1238, but on SQLite the stored ``expires_at`` is naive while
    # ``_now_utc()`` is tz-aware, so the comparison raises TypeError. That is a pre-existing
    # cross-backend bug (reported under ISSUES); we do not assert that branch here to avoid
    # depending on a defect.

    # list invites
    listed = client.get("/api/v1/orgs/invites", headers=headers)
    assert listed.status_code == 200, listed.text

    # resolve token
    resolved = client.get(f"/api/v1/orgs/invites/resolve?token={token}")
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["email"] == "invitee@team.dev"

    # accept by the invited user
    invitee = _register(client, email="invitee@team.dev", organization_name="Invitee Personal")
    invitee_headers = {"Authorization": f"Bearer {invitee['access_token']}"}
    accepted = client.post(
        "/api/v1/orgs/invites/accept", headers=invitee_headers, json={"token": token}
    )
    assert accepted.status_code == 200, accepted.text

    # revoke an already-resolved invite still returns 200 (no state change)
    revoke = client.post(f"/api/v1/orgs/invites/{invite_id}/revoke", headers=headers)
    assert revoke.status_code == 200, revoke.text


def test_invite_accept_email_mismatch(test_client):
    client, *_ = test_client
    owner = _register(client, email="mm-owner@test.dev", organization_name="MM Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    created = client.post(
        "/api/v1/orgs/invites", headers=headers, json={"email": "intended@team.dev", "role": "viewer"}
    )
    token = created.json()["invite_url"].split("token=", 1)[1]
    # A different user tries to accept.
    other = _register(client, email="wrong-user@team.dev", organization_name="Wrong Personal")
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    resp = client.post("/api/v1/orgs/invites/accept", headers=other_headers, json={"token": token})
    assert resp.status_code == 401, resp.text


def test_invite_revoke_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="invrev-404@test.dev", organization_name="InvRev Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    resp = client.post(f"/api/v1/orgs/invites/{uuid4()}/revoke", headers=headers)
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# member role updates
# ---------------------------------------------------------------------------


def test_update_member_role_flows(test_client):
    client, *_ = test_client
    owner = _register(client, email="role-owner@test.dev", organization_name="Role Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 5)
    member = _register(client, email="role-member@test.dev", organization_name="Role Member Personal")
    client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "role-member@test.dev", "role": "viewer"},
    )

    # invalid role
    assert (
        client.patch(
            f"/api/v1/orgs/members/{member['user_id']}/role", headers=headers, json={"role": "boss"}
        ).status_code
        == 422
    )
    # member not found
    assert (
        client.patch(
            f"/api/v1/orgs/members/{uuid4()}/role", headers=headers, json={"role": "editor"}
        ).status_code
        == 404
    )
    # success
    ok = client.patch(
        f"/api/v1/orgs/members/{member['user_id']}/role", headers=headers, json={"role": "admin"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["role"] == "admin"


def test_demote_last_owner_protected(test_client):
    client, *_ = test_client
    owner = _register(client, email="demote-owner@test.dev", organization_name="Demote Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    resp = client.patch(
        f"/api/v1/orgs/members/{owner['user_id']}/role", headers=headers, json={"role": "admin"}
    )
    assert resp.status_code == 409, resp.text


def test_remove_member_self_route_flows(test_client):
    client, *_ = test_client
    owner = _register(client, email="rmself-owner@test.dev", organization_name="RmSelf Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 5)
    member = _register(client, email="rmself-member@test.dev", organization_name="RmSelf Member")
    client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=headers,
        json={"email": "rmself-member@test.dev", "role": "editor"},
    )
    # remove the member via the /orgs/members/{user_id} route
    ok = client.delete(f"/api/v1/orgs/members/{member['user_id']}", headers=headers)
    assert ok.status_code == 204, ok.text
    # missing member -> 404
    assert client.delete(f"/api/v1/orgs/members/{uuid4()}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# Direct helper unit tests
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone

import pytest

from app.errors import ApiError
from app.models import InviteStatus, OrgInvite, OrgMembership, User
from app.security import AuthPrincipal


def test_normalize_email_and_slugify():
    assert auth_api._normalize_email("  Foo@BAR.com ") == "foo@bar.com"
    assert auth_api._normalize_email(None) == ""
    assert auth_api._slugify("My Org!! Name") == "my-org-name"
    assert auth_api._slugify("***") == "org"


def test_as_utc_naive_and_aware():
    naive = datetime(2030, 1, 1, 12, 0, 0)
    assert auth_api._as_utc(naive).tzinfo is timezone.utc
    aware = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert auth_api._as_utc(aware) == aware


def test_hash_helpers_and_seat_limit():
    assert auth_api._hash_invite_token("tok") == auth_api._hash_invite_token("tok")
    assert auth_api._hash_api_key_secret("s") == auth_api._hash_api_key_secret("s")

    class _Org:
        seat_limit = 0

    assert auth_api._seat_limit_for_org(_Org()) == 1


def test_current_membership_requires_auth(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError):
            auth_api._current_membership(session, AuthPrincipal(org_id=None, user_id=None))


def test_current_membership_requires_membership(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError) as exc:
            auth_api._current_membership(
                session, AuthPrincipal(org_id=uuid4(), user_id=uuid4())
            )
        assert exc.value.status_code == 401


def test_require_org_manager_rejects_non_manager(test_client):
    engine = get_engine()
    org_id = uuid4()
    user_id = uuid4()
    with Session(engine) as session:
        session.add(OrgMembership(org_id=org_id, user_id=user_id, role="viewer"))
        session.commit()
        with pytest.raises(ApiError) as exc:
            auth_api._require_org_manager(
                session, AuthPrincipal(org_id=org_id, user_id=user_id, role="viewer")
            )
        assert exc.value.status_code == 401


def test_require_org_manager_for_mismatch_and_no_auth(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError):
            auth_api._require_org_manager_for(
                session, AuthPrincipal(org_id=None, user_id=None), uuid4()
            )
        with pytest.raises(ApiError) as exc:
            auth_api._require_org_manager_for(
                session, AuthPrincipal(org_id=uuid4(), user_id=uuid4()), uuid4()
            )
        assert exc.value.status_code == 401


def test_coerce_pending_invite_not_found(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError) as exc:
            auth_api._coerce_pending_invite(session, "no-such-token")
        assert exc.value.status_code == 404


def test_coerce_pending_invite_not_pending(test_client):
    engine = get_engine()
    with Session(engine) as session:
        token = "revoked-token-xyz"
        invite = OrgInvite(
            org_id=uuid4(),
            email="x@y.dev",
            role="viewer",
            token_hash=auth_api._hash_invite_token(token),
            status=InviteStatus.revoked,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        session.add(invite)
        session.commit()
        with pytest.raises(ApiError) as exc:
            auth_api._coerce_pending_invite(session, token)
        assert exc.value.status_code == 409


def test_coerce_pending_invite_expired(test_client):
    engine = get_engine()
    with Session(engine) as session:
        token = "expired-token-xyz"
        invite = OrgInvite(
            org_id=uuid4(),
            email="x@y.dev",
            role="viewer",
            token_hash=auth_api._hash_invite_token(token),
            status=InviteStatus.pending,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        session.add(invite)
        session.commit()
        with pytest.raises(ApiError) as exc:
            auth_api._coerce_pending_invite(session, token)
        # Expired pending invites are flagged expired then surfaced as conflict.
        assert exc.value.status_code in (404, 409)


def test_serialize_api_key_without_secret(test_client):
    from app.models import ApiKey

    key = ApiKey(
        org_id=uuid4(),
        created_by_user_id=uuid4(),
        name="k",
        key_prefix="rf_xxxxxxxx",
        key_hash="h",
        scopes=["read"],
    )
    view = auth_api._serialize_api_key(key)
    assert view.secret is None
    assert view.scopes == ["read"]
