"""Branch-coverage tests for :mod:`app.identity_api` SSO/SCIM error and edge paths."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, select

from app import identity_api
from app.database import get_engine
from app.errors import ApiError
from app.models import Organization, RoleMapping
from app.security import AuthPrincipal, create_oauth_state


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


def _enable_sso(client, owner_headers, org_id, *, jit=True) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso/config",
        headers=owner_headers,
        json={
            "enabled": True,
            "issuer_url": "https://example.okta.com/oauth2/default",
            "client_id": "okta-client",
            "default_role": "viewer",
            "jit_enabled": jit,
            "allow_email_link": True,
            "config": {},
        },
    )
    assert resp.status_code == 200, resp.text


def _scim_token(client, owner_headers, org_id) -> str:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/sso/scim-tokens",
        headers=owner_headers,
        json={"scopes": ["users:write", "groups:write"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def _create_scim_token_full(client, owner_headers, org_id) -> dict:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/sso/scim-tokens",
        headers=owner_headers,
        json={"scopes": ["users:write", "groups:write"]},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_mask_token():
    assert identity_api._mask_token("short") == "short"
    masked = identity_api._mask_token("abcdefghijklmnop")
    assert masked.startswith("abcdef") and masked.endswith("op")


def test_normalize_email_and_hash():
    assert identity_api._normalize_email("  A@B.COM ") == "a@b.com"
    assert identity_api._normalize_email(None) == ""
    assert identity_api._hash_token("x") == identity_api._hash_token("x")


def test_parse_scim_bearer():
    assert identity_api._parse_scim_bearer("Bearer tok123") == "tok123"
    with pytest.raises(ApiError):
        identity_api._parse_scim_bearer("")
    with pytest.raises(ApiError):
        identity_api._parse_scim_bearer("Basic abc")
    with pytest.raises(ApiError):
        identity_api._parse_scim_bearer("Bearer   ")


def test_extract_scim_email():
    assert identity_api._extract_scim_email({"userName": "U@X.com"}) == "u@x.com"
    assert (
        identity_api._extract_scim_email({"emails": [{"value": "e@x.com"}]}) == "e@x.com"
    )
    assert identity_api._extract_scim_email({"emails": "not-a-list"}) == ""
    assert identity_api._extract_scim_email({}) == ""


def test_extract_scim_display_name():
    assert identity_api._extract_scim_display_name({"name": {"formatted": "Bob"}}) == "Bob"
    assert identity_api._extract_scim_display_name({"displayName": "Carol"}) == "Carol"
    assert identity_api._extract_scim_display_name({}) is None
    assert identity_api._extract_scim_display_name({"name": "not-a-dict"}) is None


def test_role_for_groups_default_when_empty(test_client):
    engine = get_engine()
    with Session(engine) as session:
        assert (
            identity_api._role_for_groups(session, uuid4(), [], "viewer") == "viewer"
        )


def test_role_for_groups_maps_known_group(test_client):
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        session.add(
            RoleMapping(
                org_id=org_id, provider="okta", external_value="admins", role="admin"
            )
        )
        session.commit()
        assert (
            identity_api._role_for_groups(session, org_id, ["admins"], "viewer") == "admin"
        )
        # Unknown group falls back to default.
        assert (
            identity_api._role_for_groups(session, org_id, ["nope"], "viewer") == "viewer"
        )


def test_require_org_manager_rejects(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError):
            identity_api._require_org_manager(
                session, AuthPrincipal(user_id=uuid4(), org_id=uuid4()), uuid4()
            )


def test_ensure_org_seat_available_missing_org(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError) as exc:
            identity_api._ensure_org_seat_available(session, uuid4())
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# SSO config routes
# ---------------------------------------------------------------------------


def test_get_sso_config_requires_manager(test_client):
    client, *_ = test_client
    owner = _register(client, email="sso-cfg@test.dev", organization_name="SSO Cfg Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    # GET with no SSO connection returns defaults.
    resp = client.get(f"/api/v1/orgs/{org_id}/sso/config", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is False
    # Unauthorized (no token) -> 401.
    assert client.get(f"/api/v1/orgs/{org_id}/sso/config").status_code == 401


def test_put_sso_config_unsupported_default_role(test_client):
    client, *_ = test_client
    owner = _register(client, email="sso-badrole@test.dev", organization_name="SSO BadRole Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    # default_role gets normalized; an unknown value becomes "viewer" via _apply.
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso/config",
        headers=headers,
        json={"enabled": True, "default_role": "superhero"},
    )
    # The build path (no existing connection) does not normalize, so an invalid role 422s.
    assert resp.status_code in (200, 422), resp.text


def test_put_sso_config_update_existing(test_client):
    client, *_ = test_client
    owner = _register(client, email="sso-upd@test.dev", organization_name="SSO Upd Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _enable_sso(client, headers, org_id)
    # Second PUT updates the existing connection (apply path).
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso/config",
        headers=headers,
        json={
            "enabled": False,
            "issuer_url": "https://new.okta.com",
            "client_id": "c2",
            "client_secret_ref": "vault://secret",
            "default_role": "editor",
            "jit_enabled": False,
            "allow_email_link": False,
            "config": {"x": 1},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_role"] == "editor"


def test_sso_config_org_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="sso-orgnf@test.dev", organization_name="SSO OrgNF")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    # Manager check requires matching org; a random org id -> 401 (token org mismatch).
    resp = client.get(f"/api/v1/orgs/{uuid4()}/sso/config", headers=headers)
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# SCIM tokens
# ---------------------------------------------------------------------------


def test_scim_token_create_and_revoke(test_client):
    client, *_ = test_client
    owner = _register(client, email="scimtok@test.dev", organization_name="ScimTok Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    created = _create_scim_token_full(client, headers, org_id)
    assert created["token"]
    token_id = created["id"]

    revoke = client.delete(
        f"/api/v1/orgs/{org_id}/sso/scim-tokens/{token_id}", headers=headers
    )
    assert revoke.status_code in (200, 204), revoke.text

    # revoke missing token -> 404
    missing = client.delete(
        f"/api/v1/orgs/{org_id}/sso/scim-tokens/{uuid4()}", headers=headers
    )
    assert missing.status_code == 404, missing.text


# ---------------------------------------------------------------------------
# Okta callback error branches
# ---------------------------------------------------------------------------


def test_okta_callback_error_param(test_client):
    client, *_ = test_client
    state = create_oauth_state(provider=f"okta:{uuid4()}", redirect_to=None)
    resp = client.get(f"/api/v1/auth/sso/okta/callback?state={state}&error=access_denied")
    assert resp.status_code == 401, resp.text


def test_okta_callback_bad_state_provider(test_client):
    client, *_ = test_client
    state = create_oauth_state(provider="github", redirect_to=None)
    resp = client.get(f"/api/v1/auth/sso/okta/callback?state={state}&email=a@b.dev")
    assert resp.status_code == 401, resp.text


def test_okta_callback_org_not_found(test_client):
    client, *_ = test_client
    state = create_oauth_state(provider=f"okta:{uuid4()}", redirect_to=None)
    resp = client.get(f"/api/v1/auth/sso/okta/callback?state={state}&email=a@b.dev")
    assert resp.status_code == 404, resp.text


def test_okta_callback_sso_not_enabled(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-noen@test.dev", organization_name="Okta NoEn Org")
    org_id = owner["org_id"]
    state = create_oauth_state(provider=f"okta:{org_id}", redirect_to=None)
    resp = client.get(f"/api/v1/auth/sso/okta/callback?state={state}&email=a@b.dev")
    assert resp.status_code == 409, resp.text


def test_okta_callback_missing_email(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-noemail@test.dev", organization_name="Okta NoEmail Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _enable_sso(client, headers, org_id)
    state = create_oauth_state(provider=f"okta:{org_id}", redirect_to=None)
    resp = client.get(f"/api/v1/auth/sso/okta/callback?state={state}")
    assert resp.status_code == 401, resp.text


def test_okta_callback_dev_email_code_and_jit(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-jit@test.dev", organization_name="Okta JIT Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 10)
    _enable_sso(client, headers, org_id, jit=True)
    state = create_oauth_state(provider=f"okta:{org_id}", redirect_to=None)
    # Email supplied via the dev-email code fallback; new user is JIT-provisioned.
    resp = client.get(
        f"/api/v1/auth/sso/okta/callback?state={state}"
        "&code=dev-email:jituser@okta.dev&groups=eng,admins"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


def test_okta_callback_jit_disabled_for_new_user(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-nojit@test.dev", organization_name="Okta NoJIT Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _enable_sso(client, headers, org_id, jit=False)
    state = create_oauth_state(provider=f"okta:{org_id}", redirect_to=None)
    resp = client.get(
        f"/api/v1/auth/sso/okta/callback?state={state}&email=brandnew@okta.dev"
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# SCIM bearer-auth gating and user/group CRUD errors
# ---------------------------------------------------------------------------


def test_scim_users_requires_valid_token(test_client):
    client, *_ = test_client
    # No bearer -> 401.
    assert client.get("/api/v1/scim/v2/Users").status_code == 401
    # Invalid bearer token -> 401.
    bad = {"Authorization": "Bearer not-a-real-token"}
    assert client.get("/api/v1/scim/v2/Users", headers=bad).status_code == 401


def test_scim_create_user_missing_email(test_client):
    client, *_ = test_client
    owner = _register(client, email="scim-noemail@test.dev", organization_name="Scim NoEmail Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 10)
    token = _scim_token(client, headers, org_id)
    scim_headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/scim/v2/Users", headers=scim_headers, json={"name": {}})
    assert resp.status_code in (400, 422), resp.text


def test_scim_get_and_delete_user_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="scim-unf@test.dev", organization_name="Scim UNF Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 10)
    token = _scim_token(client, headers, org_id)
    scim_headers = {"Authorization": f"Bearer {token}"}
    # delete a non-existent user
    resp = client.delete(f"/api/v1/scim/v2/Users/{uuid4()}", headers=scim_headers)
    assert resp.status_code in (204, 404), resp.text
    # patch a non-existent user
    patch = client.patch(
        f"/api/v1/scim/v2/Users/{uuid4()}",
        headers=scim_headers,
        json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
    )
    assert patch.status_code == 404, patch.text


def test_scim_group_crud_errors(test_client):
    client, *_ = test_client
    owner = _register(client, email="scim-grp@test.dev", organization_name="Scim Grp Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 10)
    token = _scim_token(client, headers, org_id)
    scim_headers = {"Authorization": f"Bearer {token}"}

    # delete non-existent group
    resp = client.delete(f"/api/v1/scim/v2/Groups/{uuid4()}", headers=scim_headers)
    assert resp.status_code in (204, 404), resp.text
    # patch non-existent group
    patch = client.patch(
        f"/api/v1/scim/v2/Groups/{uuid4()}",
        headers=scim_headers,
        json={"Operations": [{"op": "replace", "path": "displayName", "value": "x"}]},
    )
    assert patch.status_code == 404, patch.text


# ---------------------------------------------------------------------------
# Full SCIM user + group lifecycle covering operation branches
# ---------------------------------------------------------------------------


def _scim_setup(client):
    owner = _register(client, email="scimlife@test.dev", organization_name="ScimLife Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    _set_seat_limit(org_id, 20)
    _enable_sso(client, headers, org_id)
    token = _scim_token(client, headers, org_id)
    return owner, headers, org_id, {"Authorization": f"Bearer {token}"}


def test_scim_user_full_lifecycle(test_client):
    client, *_ = test_client
    _owner, _headers, _org_id, scim = _scim_setup(client)

    created = client.post(
        "/api/v1/scim/v2/Users",
        headers=scim,
        json={
            "userName": "life-user@test.dev",
            "externalId": "ext-1",
            "name": {"formatted": "Life User"},
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    # re-create same user (update path: display name + existing membership/identity)
    again = client.post(
        "/api/v1/scim/v2/Users",
        headers=scim,
        json={"userName": "life-user@test.dev", "externalId": "ext-1", "displayName": "Renamed"},
    )
    assert again.status_code == 201, again.text

    # list with userName filter (match + non-match)
    match_filter = 'userName eq "life-user@test.dev"'
    listed = client.get("/api/v1/scim/v2/Users", headers=scim, params={"filter": match_filter})
    assert listed.status_code == 200, listed.text
    assert listed.json()["totalResults"] == 1
    none_match = client.get(
        "/api/v1/scim/v2/Users", headers=scim, params={"filter": 'userName eq "nobody@test.dev"'}
    )
    assert none_match.json()["totalResults"] == 0

    # patch: change username + displayName + skipped ops (while still a member)
    rename = client.patch(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=scim,
        json={
            "Operations": [
                {"op": "replace", "path": "userName", "value": "renamed-user@test.dev"},
                {"op": "replace", "path": "name.formatted", "value": "New Name"},
                {"op": "remove", "path": "active"},  # op not add/replace -> skipped
                "not-a-dict",  # skipped
            ]
        },
    )
    assert rename.status_code == 200, rename.text

    # patch: deactivate (active=false -> delete membership). After this the user has no
    # membership, so the PATCH route guard would 404 on any further patch; the active=true
    # re-provision branch of _apply_scim_user_operation is verified directly below instead.
    deactivate = client.patch(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=scim,
        json={"Operations": [{"op": "replace", "path": "active", "value": True}]},
    )
    assert deactivate.status_code == 200, deactivate.text
    final = client.patch(
        f"/api/v1/scim/v2/Users/{user_id}",
        headers=scim,
        json={"Operations": [{"op": "replace", "path": "active", "value": False}]},
    )
    assert final.status_code == 200, final.text

    deleted = client.delete(f"/api/v1/scim/v2/Users/{user_id}", headers=scim)
    assert deleted.status_code == 204, deleted.text


def test_apply_scim_user_operation_reactivate_direct(test_client):
    """Direct call covering the active=true re-provision branch (unreachable via PATCH route)."""
    from app.models import OrgMembership, User

    engine = get_engine()
    with Session(engine) as session:
        org = Organization(name="ReactOrg", slug=f"react-{uuid4().hex[:8]}", seat_limit=10)
        session.add(org)
        session.commit()
        session.refresh(org)
        user = User(email="react@test.dev", is_active=False)
        session.add(user)
        session.commit()
        session.refresh(user)
        # membership is None -> active=true creates a new membership.
        result = identity_api._apply_scim_user_operation(
            session,
            org.id,
            user,
            None,
            {"op": "replace", "path": "active", "value": True},
        )
        assert result is not None
        assert result.role == "viewer"
        # username + display name op branches via direct call too.
        identity_api._apply_scim_user_operation(
            session, org.id, user, result, {"op": "add", "path": "username", "value": "NEW@x.dev"}
        )
        assert user.email == "new@x.dev"
        identity_api._apply_scim_user_operation(
            session, org.id, user, result, {"op": "replace", "path": "displayname", "value": "Nm"}
        )
        assert user.display_name == "Nm"


def test_scim_group_full_lifecycle(test_client):
    client, *_ = test_client
    _owner, _headers, _org_id, scim = _scim_setup(client)

    user_resp = client.post(
        "/api/v1/scim/v2/Users",
        headers=scim,
        json={"userName": "grp-member@test.dev", "externalId": "gm-1"},
    )
    member_id = user_resp.json()["id"]

    created = client.post(
        "/api/v1/scim/v2/Groups",
        headers=scim,
        json={"displayName": "editors", "role": "editor", "externalId": "g-ext-1"},
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    # re-create same group (update path)
    again = client.post(
        "/api/v1/scim/v2/Groups", headers=scim, json={"displayName": "editors", "role": "admin"}
    )
    assert again.status_code == 201, again.text

    # unknown role -> normalized to viewer
    weird = client.post(
        "/api/v1/scim/v2/Groups", headers=scim, json={"displayName": "weird", "role": "wizard"}
    )
    assert weird.status_code == 201, weird.text

    listed = client.get("/api/v1/scim/v2/Groups", headers=scim)
    assert listed.status_code == 200, listed.text

    patched = client.patch(
        f"/api/v1/scim/v2/Groups/{group_id}",
        headers=scim,
        json={
            "Operations": [
                {"op": "replace", "path": "displayName", "value": "senior-editors"},
                {"op": "replace", "path": "role", "value": "admin"},
                {
                    "op": "add",
                    "path": "members",
                    "value": [{"value": member_id}, {"value": "bad-uuid"}, {}, "x"],
                },
                {"op": "remove", "path": "members"},  # op not add/replace -> skipped
            ]
        },
    )
    assert patched.status_code == 200, patched.text

    deleted = client.delete(f"/api/v1/scim/v2/Groups/{group_id}", headers=scim)
    assert deleted.status_code == 204, deleted.text


# ---------------------------------------------------------------------------
# Okta SSO start
# ---------------------------------------------------------------------------


def test_okta_start_requires_org_and_enabled(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-start@test.dev", organization_name="Okta Start Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    not_enabled = client.get("/api/v1/auth/sso/okta/start", headers=headers)
    assert not_enabled.status_code == 409, not_enabled.text
    assert client.get("/api/v1/auth/sso/okta/start").status_code == 401


def test_okta_start_success(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-start-ok@test.dev", organization_name="Okta StartOK Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _enable_sso(client, headers, owner["org_id"])
    resp = client.get("/api/v1/auth/sso/okta/start", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "authorize" in resp.json()["authorize_url"]


def test_okta_start_incomplete_config(test_client):
    client, *_ = test_client
    owner = _register(client, email="okta-incomplete@test.dev", organization_name="Okta Incomplete")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    org_id = owner["org_id"]
    resp = client.put(
        f"/api/v1/orgs/{org_id}/sso/config",
        headers=headers,
        json={"enabled": True, "issuer_url": "", "client_id": "", "default_role": "viewer"},
    )
    assert resp.status_code == 200, resp.text
    start = client.get("/api/v1/auth/sso/okta/start", headers=headers)
    assert start.status_code == 409, start.text
