from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.database import get_engine
from app.models import Organization


class _FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


class _FakeCelery:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def send_task(self, task_name: str, args: list[Any], queue: str | None = None):
        self.calls.append({"task_name": task_name, "args": args, "queue": queue})
        return _FakeAsyncResult(task_id=f"wf-task-{len(self.calls)}")

    class control:
        @staticmethod
        def revoke(_task_id: str, terminate: bool = False):  # noqa: ARG004
            return None


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    resp = client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_fake_video(client, headers: dict[str, str], content: bytes = b"fake-video", filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
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


def test_enterprise_org_and_workflow_surfaces(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client

    fake_celery = _FakeCelery()
    monkeypatch.setattr("app.api.get_celery_app", lambda: fake_celery)

    owner = _register(client, email="owner-enterprise@test.dev", organization_name="Owner Org")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    _set_org_seat_limit(owner["org_id"], 3)

    orgs_resp = client.get("/api/v1/orgs", headers=owner_headers)
    assert orgs_resp.status_code == 200, orgs_resp.text
    assert any(item["org_id"] == owner["org_id"] for item in orgs_resp.json())

    create_org_resp = client.post("/api/v1/orgs", headers=owner_headers, json={"name": "Second Org"})
    assert create_org_resp.status_code == 201, create_org_resp.text

    teammate = _register(client, email="teammate-enterprise@test.dev", organization_name="Teammate Org")
    add_member_resp = client.post(
        f"/api/v1/orgs/{owner['org_id']}/members",
        headers=owner_headers,
        json={"email": "teammate-enterprise@test.dev", "role": "editor"},
    )
    assert add_member_resp.status_code == 201, add_member_resp.text
    assert add_member_resp.json()["role"] == "editor"

    api_key_resp = client.post(
        f"/api/v1/orgs/{owner['org_id']}/api-keys",
        headers=owner_headers,
        json={"name": "Automation Key", "scopes": ["jobs:write", "assets:read"]},
    )
    assert api_key_resp.status_code == 201, api_key_resp.text
    key_payload = api_key_resp.json()
    assert key_payload["secret"].startswith("rf_")

    list_key_resp = client.get(f"/api/v1/orgs/{owner['org_id']}/api-keys", headers=owner_headers)
    assert list_key_resp.status_code == 200, list_key_resp.text
    assert list_key_resp.json()[0]["secret"] is None

    audit_resp = client.get("/api/v1/audit-events?limit=20", headers=owner_headers)
    assert audit_resp.status_code == 200, audit_resp.text
    event_types = {item["event_type"] for item in audit_resp.json()}
    assert "api_key.created" in event_types
    assert "org.member_added" in event_types

    video = _upload_fake_video(client, headers=owner_headers)

    template_resp = client.post(
        "/api/v1/workflows/templates",
        headers=owner_headers,
        json={
            "name": "Creator Chain",
            "description": "captions + shorts",
            "steps": [
                {"type": "captions", "payload": {"formats": ["srt"]}},
                {"type": "shorts", "payload": {"max_clips": 2, "min_duration": 8, "max_duration": 25}},
            ],
        },
    )
    assert template_resp.status_code == 201, template_resp.text
    template_id = template_resp.json()["id"]

    run_resp = client.post(
        "/api/v1/workflows/runs",
        headers=owner_headers,
        json={"template_id": template_id, "video_asset_id": video["id"]},
    )
    assert run_resp.status_code == 201, run_resp.text
    run = run_resp.json()
    assert run["template_id"] == template_id
    assert run["task_id"] == "wf-task-1"
    assert len(run["steps"]) == 2

    get_run_resp = client.get(f"/api/v1/workflows/runs/{run['id']}", headers=owner_headers)
    assert get_run_resp.status_code == 200, get_run_resp.text

    cancel_resp = client.post(f"/api/v1/workflows/runs/{run['id']}/cancel", headers=owner_headers)
    assert cancel_resp.status_code == 200, cancel_resp.text
    assert str(cancel_resp.json()["status"]).lower().endswith("cancelled")

    costs_resp = client.get("/api/v1/usage/costs", headers=owner_headers)
    assert costs_resp.status_code == 200, costs_resp.text
    costs = costs_resp.json()
    assert costs["currency"] == "usd"
    assert "total_estimated_cost_cents" in costs
