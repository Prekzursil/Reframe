from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from app.database import get_engine
from app.models import Organization
from app.security import create_access_token


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


def test_project_collaboration_members_comments_approvals_and_activity(test_client):
    client, _enqueued, _worker, _media_root = test_client

    owner = _register(client, email="owner-collab@test.dev", organization_name="Collab Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_seat_limit(owner["org_id"], 3)

    collaborator = _register(client, email="editor-collab@test.dev", organization_name="Editor Personal")
    outsider = _register(client, email="outsider-collab@test.dev", organization_name="Outsider Org")
    outsider_headers = {"Authorization": f"Bearer {outsider['access_token']}"}

    add_org_member = client.post(
        f"/api/v1/orgs/{owner['org_id']}/members",
        headers=owner_headers,
        json={"email": "editor-collab@test.dev", "role": "editor"},
    )
    assert add_org_member.status_code == 201, add_org_member.text
    collaborator_org_token = create_access_token(
        user_id=UUID(add_org_member.json()["user_id"]),
        org_id=UUID(owner["org_id"]),
        role="editor",
    )
    collaborator_headers = {"Authorization": f"Bearer {collaborator_org_token}"}

    create_project = client.post(
        "/api/v1/projects",
        headers=owner_headers,
        json={"name": "Launch Assets", "description": "Collaboration test"},
    )
    assert create_project.status_code == 201, create_project.text
    project_id = create_project.json()["id"]

    add_project_member = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=owner_headers,
        json={"email": "editor-collab@test.dev", "role": "editor"},
    )
    assert add_project_member.status_code == 201, add_project_member.text
    assert add_project_member.json()["role"] == "editor"

    list_members = client.get(f"/api/v1/projects/{project_id}/members", headers=owner_headers)
    assert list_members.status_code == 200, list_members.text
    assert any(item["email"] == "editor-collab@test.dev" for item in list_members.json())

    comment_resp = client.post(
        f"/api/v1/projects/{project_id}/comments",
        headers=collaborator_headers,
        json={"body": "Ready for approval."},
    )
    assert comment_resp.status_code == 201, comment_resp.text
    comment_id = comment_resp.json()["id"]

    approval_req = client.post(
        f"/api/v1/projects/{project_id}/approvals/request",
        headers=collaborator_headers,
        json={"summary": "Please approve final cut"},
    )
    assert approval_req.status_code == 201, approval_req.text
    approval_id = approval_req.json()["id"]
    assert approval_req.json()["status"] == "pending"

    approve_resp = client.post(
        f"/api/v1/projects/{project_id}/approvals/{approval_id}/approve",
        headers=owner_headers,
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["status"] == "approved"

    comments = client.get(f"/api/v1/projects/{project_id}/comments", headers=owner_headers)
    assert comments.status_code == 200, comments.text
    assert any(item["id"] == comment_id for item in comments.json())

    activity = client.get(f"/api/v1/projects/{project_id}/activity", headers=owner_headers)
    assert activity.status_code == 200, activity.text
    event_types = {item["event_type"] for item in activity.json()}
    assert "project.member_upserted" in event_types
    assert "project.comment_created" in event_types
    assert "project.approval_requested" in event_types
    assert "project.approval_approved" in event_types

    outsider_denied = client.get(f"/api/v1/projects/{project_id}/activity", headers=outsider_headers)
    assert outsider_denied.status_code in {401, 403}, outsider_denied.text

    delete_comment = client.delete(f"/api/v1/projects/{project_id}/comments/{comment_id}", headers=owner_headers)
    assert delete_comment.status_code == 204, delete_comment.text
