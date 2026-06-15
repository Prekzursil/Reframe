"""Tail branch-coverage for auth_api/identity_api guards, owner-protection, and get_principal."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models import Organization, OrgInvite, InviteStatus, OrgMembership, User
from app.security import create_access_token


def _register(client, *, email: str, organization_name: str = "Tail Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "organization_name": organization_name},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _set_seat_limit(org_id: str, n: int) -> None:
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(org_id))
        org.seat_limit = n
        session.add(org)
        session.commit()


def _promote_second_owner(client, owner, owner_headers, email):
    """Register a user, add them to the org, and promote to owner. Returns their user_id."""
    member = _register(client, email=email, organization_name="Second Personal")
    add = client.post(
        f"/api/v1/orgs/{owner['org_id']}/members",
        headers=owner_headers,
        json={"email": email, "role": "admin"},
    )
    assert add.status_code == 201, add.text
    promote = client.patch(
        f"/api/v1/orgs/members/{member['user_id']}/role",
        headers=owner_headers,
        json={"role": "owner"},
    )
    assert promote.status_code == 200, promote.text
    return member["user_id"]


# ---------------------------------------------------------------------------
# get_principal branches
# ---------------------------------------------------------------------------


def test_get_principal_bad_scheme(test_client):
    client, *_ = test_client
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401, resp.text


def test_get_principal_bad_token(test_client):
    client, *_ = test_client
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert resp.status_code == 401, resp.text


def test_get_principal_inactive_user(test_client):
    client, *_ = test_client
    user = _register(client, email="inactive@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    engine = get_engine()
    with Session(engine) as session:
        row = session.get(User, UUID(user["user_id"]))
        row.is_active = False
        session.add(row)
        session.commit()
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401, resp.text


def test_get_principal_hosted_mode_requires_auth(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_HOSTED_MODE", "true")
    get_settings.cache_clear()
    # No auth in hosted mode -> 401 from get_principal.
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401, resp.text
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# me: principal not found
# ---------------------------------------------------------------------------


def test_me_principal_not_found(test_client):
    client, *_ = test_client
    user = _register(client, email="menf@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # Delete the org row so /auth/me cannot resolve it.
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(user["org_id"]))
        session.delete(org)
        session.commit()
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# owner-protection branches (2-owner org)
# ---------------------------------------------------------------------------


def test_remove_owner_requires_owner_manager_via_self_route(test_client):
    client, *_ = test_client
    owner = _register(client, email="twoown-owner@test.dev", organization_name="TwoOwn Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    second_owner_id = _promote_second_owner(
        client, owner, owner_headers, "twoown-second@test.dev"
    )
    # An admin (non-owner) manager tries to remove an owner -> 401.
    admin = _register(client, email="twoown-admin@test.dev", organization_name="Admin Personal")
    client.post(
        f"/api/v1/orgs/{owner['org_id']}/members",
        headers=owner_headers,
        json={"email": "twoown-admin@test.dev", "role": "admin"},
    )
    admin_token = create_access_token(
        user_id=UUID(admin["user_id"]), org_id=UUID(owner["org_id"]), role="admin"
    )
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    resp = client.delete(
        f"/api/v1/orgs/members/{second_owner_id}", headers=admin_headers
    )
    assert resp.status_code == 401, resp.text


def test_remove_second_owner_succeeds(test_client):
    client, *_ = test_client
    owner = _register(client, email="rmown-owner@test.dev", organization_name="RmOwn Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    second_owner_id = _promote_second_owner(client, owner, owner_headers, "rmown-second@test.dev")
    # With two owners, an owner can remove the second owner.
    resp = client.delete(
        f"/api/v1/orgs/{owner['org_id']}/members/{second_owner_id}", headers=owner_headers
    )
    assert resp.status_code == 204, resp.text


def test_demote_owner_with_two_owners(test_client):
    client, *_ = test_client
    owner = _register(client, email="demote2-owner@test.dev", organization_name="Demote2 Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    second_owner_id = _promote_second_owner(
        client, owner, owner_headers, "demote2-second@test.dev"
    )
    # With two owners, the second owner can be demoted.
    resp = client.patch(
        f"/api/v1/orgs/members/{second_owner_id}/role",
        headers=owner_headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"


# ---------------------------------------------------------------------------
# invite list expiry sweep
# ---------------------------------------------------------------------------


def test_list_invites_expires_stale(test_client):
    client, *_ = test_client
    owner = _register(client, email="invexp-owner@test.dev", organization_name="InvExp Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 10)
    created = client.post(
        "/api/v1/orgs/invites",
        headers=owner_headers,
        json={"email": "stale@team.dev", "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    # Backdate the invite expiry so list_org_invites flips it to expired.
    engine = get_engine()
    with Session(engine) as session:
        invite = session.exec(
            select(OrgInvite).where(OrgInvite.org_id == UUID(owner["org_id"]))
        ).first()
        invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        session.add(invite)
        session.commit()
    listed = client.get("/api/v1/orgs/invites", headers=owner_headers)
    assert listed.status_code == 200, listed.text
    assert any(item["status"] == "expired" for item in listed.json())


def test_invite_revoke_already_resolved_invite(test_client):
    client, *_ = test_client
    owner = _register(client, email="invrev2-owner@test.dev", organization_name="InvRev2 Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 10)
    created = client.post(
        "/api/v1/orgs/invites",
        headers=owner_headers,
        json={"email": "resolved@team.dev", "role": "viewer"},
    )
    invite_id = created.json()["id"]
    # Mark the invite revoked already, then revoke again (no state change branch).
    engine = get_engine()
    with Session(engine) as session:
        invite = session.get(OrgInvite, UUID(invite_id))
        invite.status = InviteStatus.revoked
        session.add(invite)
        session.commit()
    resp = client.post(f"/api/v1/orgs/invites/{invite_id}/revoke", headers=owner_headers)
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# identity_api: okta start org-not-found-after-auth + require_org_manager
# ---------------------------------------------------------------------------


def test_okta_start_org_deleted(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-del@test.dev", organization_name="Okta Del Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    # Delete the org row but keep the valid token -> org not found.
    engine = get_engine()
    with Session(engine) as session:
        org = session.get(Organization, UUID(owner["org_id"]))
        session.delete(org)
        session.commit()
    resp = client.get("/api/v1/auth/sso/okta/start", headers=headers)
    assert resp.status_code == 404, resp.text


def test_sso_config_non_manager_member(test_client):
    client, *_ = test_client
    owner = _register(client, email="ssomgr-owner@test.dev", organization_name="SsoMgr Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    member = _register(client, email="ssomgr-member@test.dev", organization_name="Member Personal")
    client.post(
        f"/api/v1/orgs/{owner['org_id']}/members",
        headers=owner_headers,
        json={"email": "ssomgr-member@test.dev", "role": "viewer"},
    )
    member_token = create_access_token(
        user_id=UUID(member["user_id"]), org_id=UUID(owner["org_id"]), role="viewer"
    )
    member_headers = {"Authorization": f"Bearer {member_token}"}
    # A plain member cannot read the SSO config (manager required).
    resp = client.get(f"/api/v1/orgs/{owner['org_id']}/sso/config", headers=member_headers)
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# auth_api: oauth callback config guards + helper edge cases
# ---------------------------------------------------------------------------


def test_oauth_callback_disabled(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_ENABLE_OAUTH", "false")
    get_settings.cache_clear()
    resp = client.get("/api/v1/auth/oauth/google/callback?code=c&state=s")
    assert resp.status_code == 400, resp.text
    get_settings.cache_clear()


def test_oauth_callback_not_configured(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_ENABLE_OAUTH", "true")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("REFRAME_OAUTH_GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()
    resp = client.get("/api/v1/auth/oauth/google/callback?code=c&state=s")
    assert resp.status_code == 400, resp.text
    get_settings.cache_clear()


def test_unique_org_slug_collision(test_client):
    from app import auth_api

    engine = get_engine()
    with Session(engine) as session:
        # Seed an org with the slug that the helper would first try.
        session.add(Organization(name="Collide", slug="collide", seat_limit=1))
        session.commit()
        slug = auth_api._unique_org_slug(session, "Collide")
        assert slug != "collide"
        assert slug.startswith("collide-")


def test_ensure_personal_org_missing_org_row(test_client):
    from app import auth_api

    engine = get_engine()
    with Session(engine) as session:
        user = User(email="orphan@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)
        # Membership references a non-existent org -> not_found.
        session.add(OrgMembership(org_id=uuid4(), user_id=user.id, role="owner"))
        session.commit()
        try:
            auth_api.ensure_personal_org(session, user)
            raise AssertionError("expected ApiError")
        except auth_api.ApiError as exc:
            assert exc.status_code == 404


# ---------------------------------------------------------------------------
# identity_api: scim token bearer parse + require_org_manager direct
# ---------------------------------------------------------------------------


def test_scim_token_invalid_for_revoked(test_client):
    from app import identity_api
    from app.models import ScimToken

    engine = get_engine()
    with Session(engine) as session:
        token_value = "rscim_revoked_value"
        token = ScimToken(
            org_id=uuid4(),
            token_hint="rscim_...ue",
            token_hash=identity_api._hash_token(token_value),
            scopes=["users:write"],
            revoked_at=datetime.now(timezone.utc),
        )
        session.add(token)
        session.commit()
        try:
            identity_api._resolve_scim_token(session, token_value)
            raise AssertionError("expected ApiError")
        except identity_api.ApiError as exc:
            assert exc.status_code == 401
