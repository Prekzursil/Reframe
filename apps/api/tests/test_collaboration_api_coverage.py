"""Branch-coverage tests for :mod:`app.collaboration_api` error and edge paths."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import Session

import pytest

from app import collaboration_api as collab
from app.database import get_engine
from app.errors import ApiError
from app.models import (
    OrgMembership,
    Organization,
    Project,
    ProjectMembership,
    User,
)
from app.security import AuthPrincipal, create_access_token


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


def _create_project(client, headers, name="Collab P") -> dict:
    resp = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _add_org_member(client, owner_headers, org_id, email, role="editor") -> dict:
    # The user must already exist before being added to an organization.
    _register(client, email=email, organization_name="Member Personal Org")
    resp = client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers=owner_headers,
        json={"email": email, "role": role},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# project lookup / permission errors
# ---------------------------------------------------------------------------


def test_list_members_project_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="cm-404@test.dev", organization_name="CM Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    resp = client.get(f"/api/v1/projects/{uuid4()}/members", headers=headers)
    assert resp.status_code == 404, resp.text


def test_list_members_other_org_forbidden(test_client):
    client, *_ = test_client
    owner = _register(client, email="cm-owner@test.dev", organization_name="Owner Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, owner_headers)

    outsider = _register(client, email="cm-outsider@test.dev", organization_name="Outsider Org")
    out_headers = {"Authorization": f"Bearer {outsider['access_token']}"}
    resp = client.get(f"/api/v1/projects/{project['id']}/members", headers=out_headers)
    assert resp.status_code == 403, resp.text


def test_list_members_owner_fallback(test_client):
    client, *_ = test_client
    owner = _register(client, email="cm-fallback@test.dev", organization_name="Fallback Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    # No explicit members -> owner fallback row returned.
    resp = client.get(f"/api/v1/projects/{project['id']}/members", headers=headers)
    assert resp.status_code == 200, resp.text
    members = resp.json()
    assert any(m["role"] == "owner" for m in members)


# ---------------------------------------------------------------------------
# add member errors
# ---------------------------------------------------------------------------


def test_add_member_invalid_role(test_client):
    client, *_ = test_client
    owner = _register(client, email="am-role@test.dev", organization_name="AM Role Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"email": owner["email"], "role": "superuser"},
    )
    assert resp.status_code == 422, resp.text


def test_add_member_user_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="am-nouser@test.dev", organization_name="AM NoUser Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"email": "ghost@test.dev", "role": "editor"},
    )
    assert resp.status_code == 404, resp.text


def test_add_member_not_org_member_conflict(test_client):
    client, *_ = test_client
    owner = _register(client, email="am-conflict@test.dev", organization_name="AM Conflict Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    # An existing user that belongs to a different org.
    other = _register(client, email="am-other@test.dev", organization_name="AM Other Org")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"email": other["email"], "role": "editor"},
    )
    assert resp.status_code == 409, resp.text


def test_add_member_by_user_id_and_update_role(test_client):
    client, *_ = test_client
    owner = _register(client, email="am-uid@test.dev", organization_name="AM UID Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    project = _create_project(client, headers)
    member = _add_org_member(client, headers, owner["org_id"], "am-member@test.dev", role="editor")

    # Add by user_id.
    add = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"user_id": member["user_id"], "role": "viewer"},
    )
    assert add.status_code == 201, add.text

    # Add again (upsert -> role update path).
    upd = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"user_id": member["user_id"], "role": "editor"},
    )
    assert upd.status_code == 201, upd.text
    assert upd.json()["role"] == "editor"

    # PATCH role.
    patch = client.patch(
        f"/api/v1/projects/{project['id']}/members/{member['user_id']}",
        headers=headers,
        json={"role": "admin"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["role"] == "admin"

    # DELETE member.
    delete = client.delete(
        f"/api/v1/projects/{project['id']}/members/{member['user_id']}", headers=headers
    )
    assert delete.status_code == 204, delete.text


def test_update_member_role_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="upd-404@test.dev", organization_name="Upd Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.patch(
        f"/api/v1/projects/{project['id']}/members/{uuid4()}",
        headers=headers,
        json={"role": "editor"},
    )
    assert resp.status_code == 404, resp.text


def test_remove_member_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="rm-404@test.dev", organization_name="Rm Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/members/{uuid4()}", headers=headers
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# comments
# ---------------------------------------------------------------------------


def test_comment_empty_body_rejected(test_client):
    client, *_ = test_client
    owner = _register(client, email="cmt-empty@test.dev", organization_name="Cmt Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/comments",
        headers=headers,
        json={"body": "   "},
    )
    assert resp.status_code == 422, resp.text


def test_comment_parent_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="cmt-parent@test.dev", organization_name="Cmt Parent Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.post(
        f"/api/v1/projects/{project['id']}/comments",
        headers=headers,
        json={"body": "reply", "parent_comment_id": str(uuid4())},
    )
    assert resp.status_code == 404, resp.text


def test_comment_create_list_reply_and_delete(test_client):
    client, *_ = test_client
    owner = _register(client, email="cmt-full@test.dev", organization_name="Cmt Full Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    top = client.post(
        f"/api/v1/projects/{project['id']}/comments", headers=headers, json={"body": "hi"}
    )
    assert top.status_code == 201, top.text
    top_id = top.json()["id"]

    reply = client.post(
        f"/api/v1/projects/{project['id']}/comments",
        headers=headers,
        json={"body": "reply", "parent_comment_id": top_id},
    )
    assert reply.status_code == 201, reply.text

    listed = client.get(f"/api/v1/projects/{project['id']}/comments", headers=headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2

    deleted = client.delete(
        f"/api/v1/projects/{project['id']}/comments/{top_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text


def test_delete_comment_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="cmt-del404@test.dev", organization_name="Cmt Del Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/comments/{uuid4()}", headers=headers
    )
    assert resp.status_code == 404, resp.text


def test_delete_comment_forbidden_for_non_author_viewer(test_client):
    client, *_ = test_client
    owner = _register(client, email="cmt-owner2@test.dev", organization_name="Cmt Owner2 Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    project = _create_project(client, owner_headers)
    # Owner creates a comment.
    top = client.post(
        f"/api/v1/projects/{project['id']}/comments", headers=owner_headers, json={"body": "mine"}
    )
    comment_id = top.json()["id"]

    # A viewer (different user) tries to delete the owner's comment -> 401.
    viewer = _add_org_member(client, owner_headers, owner["org_id"], "cmt-viewer@test.dev", "editor")
    viewer_token = create_access_token(
        user_id=UUID(viewer["user_id"]), org_id=UUID(owner["org_id"]), role="member"
    )
    # Add the viewer to the project with viewer role.
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=owner_headers,
        json={"user_id": viewer["user_id"], "role": "viewer"},
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/comments/{comment_id}", headers=viewer_headers
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# approvals
# ---------------------------------------------------------------------------


def test_approval_request_approve_and_double_resolve(test_client):
    client, *_ = test_client
    owner = _register(client, email="appr@test.dev", organization_name="Appr Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    req = client.post(
        f"/api/v1/projects/{project['id']}/approvals/request",
        headers=headers,
        json={"summary": "please review"},
    )
    assert req.status_code == 201, req.text
    approval_id = req.json()["id"]

    approve = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval_id}/approve", headers=headers
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    # Resolving again -> conflict.
    again = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval_id}/reject", headers=headers
    )
    assert again.status_code == 409, again.text


def test_approval_reject_flow_and_not_found(test_client):
    client, *_ = test_client
    owner = _register(client, email="appr-rej@test.dev", organization_name="Appr Rej Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    req = client.post(
        f"/api/v1/projects/{project['id']}/approvals/request", headers=headers, json={}
    )
    approval_id = req.json()["id"]
    reject = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{approval_id}/reject", headers=headers
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["status"] == "rejected"

    # Unknown approval id -> 404.
    missing = client.post(
        f"/api/v1/projects/{project['id']}/approvals/{uuid4()}/approve", headers=headers
    )
    assert missing.status_code == 404, missing.text


# ---------------------------------------------------------------------------
# Direct helper unit tests (crafted principals / sessions)
# ---------------------------------------------------------------------------


def _seed_user(session, email: str) -> User:
    user = User(email=email, display_name=email.split("@")[0])
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_project_membership_none_user(test_client):
    engine = get_engine()
    with Session(engine) as session:
        assert collab._project_membership(session, uuid4(), None) is None


def test_effective_project_role_no_user_id_is_owner(test_client):
    engine = get_engine()
    with Session(engine) as session:
        project = Project(name="p", org_id=None, owner_user_id=uuid4())
        # No principal.user_id -> legacy/unauthenticated context treated as owner.
        role = collab._effective_project_role(session, project, AuthPrincipal(user_id=None))
        assert role == "owner"


def test_effective_project_role_membership_wins(test_client):
    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "eff-owner@test.dev")
        member = _seed_user(session, "eff-member@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        session.add(
            ProjectMembership(project_id=project.id, user_id=member.id, role="editor")
        )
        session.commit()
        role = collab._effective_project_role(
            session, project, AuthPrincipal(user_id=member.id)
        )
        assert role == "editor"


def test_effective_project_role_owner_match(test_client):
    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "eff-ownmatch@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        role = collab._effective_project_role(
            session, project, AuthPrincipal(user_id=owner.id)
        )
        assert role == "owner"


def test_effective_project_role_org_admin(test_client):
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        admin = _seed_user(session, "eff-orgadmin@test.dev")
        other_owner = uuid4()
        project = Project(name="p", org_id=org_id, owner_user_id=other_owner)
        session.add(project)
        session.add(OrgMembership(org_id=org_id, user_id=admin.id, role="admin"))
        session.commit()
        session.refresh(project)
        role = collab._effective_project_role(
            session, project, AuthPrincipal(user_id=admin.id, org_id=org_id)
        )
        # Org admins get admin role on org projects they don't own.
        assert role == "admin"


def test_effective_project_role_none_when_unrelated(test_client):
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        stranger = _seed_user(session, "eff-stranger@test.dev")
        project = Project(name="p", org_id=org_id, owner_user_id=uuid4())
        session.add(project)
        # stranger is a plain member (not owner/admin) of the org.
        session.add(OrgMembership(org_id=org_id, user_id=stranger.id, role="member"))
        session.commit()
        session.refresh(project)
        role = collab._effective_project_role(
            session, project, AuthPrincipal(user_id=stranger.id, org_id=org_id)
        )
        assert role is None


def test_require_project_role_denies(test_client):
    engine = get_engine()
    with Session(engine) as session:
        project = Project(name="p", org_id=uuid4(), owner_user_id=uuid4())
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            collab._require_project_role(
                session, project, AuthPrincipal(user_id=uuid4(), org_id=uuid4()), "viewer"
            )
        assert exc.value.status_code == 401


def test_member_view_user_not_found(test_client):
    engine = get_engine()
    with Session(engine) as session:
        membership = ProjectMembership(project_id=uuid4(), user_id=uuid4(), role="viewer")
        with pytest.raises(ApiError) as exc:
            collab._member_view(session, membership)
        assert exc.value.status_code == 404


def test_list_members_owner_fallback_with_no_memberships(test_client):
    """Owner fallback row is synthesised when a project has no membership rows."""
    client, *_ = test_client
    owner = _register(client, email="cm-delowner@test.dev", organization_name="Del Owner Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = _create_project(client, headers)
    # create_project auto-adds an owner membership; delete it so the owner-fallback
    # branch (build a synthetic owner row) is exercised on the subsequent list call.
    from sqlmodel import select as _select

    engine = get_engine()
    with Session(engine) as session:
        rows = session.exec(
            _select(ProjectMembership).where(
                ProjectMembership.project_id == UUID(project["id"])
            )
        ).all()
        for row in rows:
            session.delete(row)
        session.commit()
    resp = client.get(f"/api/v1/projects/{project['id']}/members", headers=headers)
    assert resp.status_code == 200, resp.text
    # Owner fallback row present (the real owner user still exists).
    assert any(m["role"] == "owner" for m in resp.json())


def test_add_member_by_email_for_org_member(test_client):
    """Add a project member by email (262->266 email-lookup branch)."""
    client, *_ = test_client
    owner = _register(client, email="email-add-owner@test.dev", organization_name="Email Add Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 5)
    project = _create_project(client, headers)
    member = _add_org_member(
        client, headers, owner["org_id"], "email-add-member@test.dev", role="editor"
    )
    add = client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=headers,
        json={"email": "email-add-member@test.dev", "role": "viewer"},
    )
    assert add.status_code == 201, add.text
    assert str(add.json()["user_id"]) == str(member["user_id"])


def test_add_member_to_project_without_org(test_client):
    """A project with no org_id skips the org-membership check (add_project_member).

    The route's org-scoped access guard cannot be reached with a principal that lacks
    an org, so the no-org code path is driven by calling the route handler directly
    with a crafted no-org principal and a session.
    """
    client, *_ = test_client
    engine = get_engine()
    from app.collaboration_api import add_project_member, ProjectMemberUpsertRequest

    with Session(engine) as session:
        owner = _seed_user(session, "noorg-owner-direct@test.dev")
        target = _seed_user(session, "noorg-target-direct@test.dev")
        project = Project(name="no-org", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        principal = AuthPrincipal(user_id=owner.id, org_id=None, role="owner")
        view = add_project_member(
            project_id=project.id,
            payload=ProjectMemberUpsertRequest(user_id=target.id, role="viewer"),
            session=session,
            principal=principal,
        )
        assert view.role == "viewer"
        assert view.user_id == target.id


# ---------------------------------------------------------------------------
# Direct-handler tests for branches unreachable via the org-scoped HTTP flow
# ---------------------------------------------------------------------------


def test_create_comment_without_user_id_direct(test_client):
    from app.collaboration_api import create_project_comment, ProjectCommentCreateRequest

    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "cmt-nouser@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            create_project_comment(
                project_id=project.id,
                payload=ProjectCommentCreateRequest(body="hi"),
                session=session,
                principal=AuthPrincipal(user_id=None, org_id=None),
            )
        assert exc.value.status_code == 401


def test_request_approval_without_user_id_direct(test_client):
    from app.collaboration_api import request_project_approval, ProjectApprovalCreateRequest

    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "appr-nouser@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            request_project_approval(
                project_id=project.id,
                payload=ProjectApprovalCreateRequest(summary="x"),
                session=session,
                principal=AuthPrincipal(user_id=None, org_id=None),
            )
        assert exc.value.status_code == 401


def test_resolve_approval_without_user_id_direct(test_client):
    from app.collaboration_api import _resolve_project_approval

    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "apprres-nouser@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            _resolve_project_approval(
                project_id=project.id,
                approval_id=uuid4(),
                resolved_status="approved",
                session=session,
                principal=AuthPrincipal(user_id=None, org_id=None),
            )
        assert exc.value.status_code == 401


def test_add_member_user_id_not_found_direct(test_client):
    """user_id supplied but the user row is absent -> 404 (covers 261/266)."""
    from app.collaboration_api import add_project_member, ProjectMemberUpsertRequest

    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "am-uidmissing@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            add_project_member(
                project_id=project.id,
                payload=ProjectMemberUpsertRequest(user_id=uuid4(), role="viewer"),
                session=session,
                principal=AuthPrincipal(user_id=owner.id, org_id=None, role="owner"),
            )
        assert exc.value.status_code == 404


def test_list_members_owner_fallback_owner_user_deleted_direct(test_client):
    """owner_user_id set but the user row is gone -> the ``if owner`` false branch."""
    from app.collaboration_api import list_project_members

    engine = get_engine()
    with Session(engine) as session:
        project = Project(name="p", org_id=None, owner_user_id=uuid4())
        session.add(project)
        session.commit()
        session.refresh(project)
        views = list_project_members(
            project_id=project.id,
            session=session,
            principal=AuthPrincipal(user_id=None, org_id=None),
        )
        # No memberships, owner user missing -> empty list (if owner == False).
        assert views == []


def test_add_member_neither_user_id_nor_email_direct(test_client):
    """Neither user_id nor email supplied -> user stays None -> 404 (262->266 branch)."""
    from app.collaboration_api import add_project_member, ProjectMemberUpsertRequest

    engine = get_engine()
    with Session(engine) as session:
        owner = _seed_user(session, "am-noid-noemail@test.dev")
        project = Project(name="p", org_id=None, owner_user_id=owner.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        with pytest.raises(ApiError) as exc:
            add_project_member(
                project_id=project.id,
                payload=ProjectMemberUpsertRequest(role="viewer"),
                session=session,
                principal=AuthPrincipal(user_id=owner.id, org_id=None, role="owner"),
            )
        assert exc.value.status_code == 404
