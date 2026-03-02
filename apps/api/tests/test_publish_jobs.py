from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlmodel import Session

from app.database import get_engine
from app.models import PublishJob


class _FakeResult:
    def __init__(self, task_id: str):
        self.id = task_id


class _FakeCelery:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def send_task(self, task_name: str, args: list[Any], queue: str | None = None):
        self.calls.append({"task_name": task_name, "args": args, "queue": queue})
        return _FakeResult(f"workflow-task-{len(self.calls)}")


def _register(client, *, email: str, password: str = "Password123!", organization_name: str | None = None) -> dict:
    payload: dict[str, str] = {"email": email, "password": password}
    if organization_name:
        payload["organization_name"] = organization_name
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _upload_fake_video(client, headers: dict[str, str], content: bytes = b"video", filename: str = "publish.mp4") -> dict:
    response = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_publish_connection_and_job_lifecycle(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    owner = _register(client, email="owner-publish@test.dev", organization_name="Publish Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    video = _upload_fake_video(client, headers=headers)

    monkeypatch.setattr("app.publish_api._dispatch_publish_task", lambda _job: "publish-task-1")

    start = client.get("/api/v1/publish/youtube/connect/start", headers=headers)
    assert start.status_code == 200, start.text
    state = start.json()["state"]

    callback = client.get(
        "/api/v1/publish/youtube/connect/callback",
        headers=headers,
        params={"state": state, "code": "oauth-code-123", "account_id": "yt-channel-1", "account_label": "Main Channel"},
    )
    assert callback.status_code == 200, callback.text
    connection = callback.json()
    assert connection["provider"] == "youtube"
    assert connection["external_account_id"] == "yt-channel-1"

    providers = client.get("/api/v1/publish/providers", headers=headers)
    assert providers.status_code == 200, providers.text
    provider_row = next(item for item in providers.json() if item["provider"] == "youtube")
    assert provider_row["connected_count"] >= 1

    create_job = client.post(
        "/api/v1/publish/jobs",
        headers=headers,
        json={
            "provider": "youtube",
            "connection_id": connection["id"],
            "asset_id": video["id"],
            "title": "Launch trailer",
            "description": "Go-live upload",
            "tags": ["launch", "trailer"],
        },
    )
    assert create_job.status_code == 201, create_job.text
    job = create_job.json()
    assert job["status"] == "queued"
    assert job["task_id"] == "publish-task-1"
    assert job["provider"] == "youtube"

    get_job = client.get(f"/api/v1/publish/jobs/{job['id']}", headers=headers)
    assert get_job.status_code == 200, get_job.text
    assert get_job.json()["id"] == job["id"]

    list_jobs = client.get("/api/v1/publish/jobs?provider=youtube", headers=headers)
    assert list_jobs.status_code == 200, list_jobs.text
    assert any(item["id"] == job["id"] for item in list_jobs.json())

    engine = get_engine()
    with Session(engine) as session:
        db_job = session.get(PublishJob, UUID(job["id"]))
        assert db_job is not None
        db_job.status = "failed"
        db_job.error = "provider timeout"
        session.add(db_job)
        session.commit()

    retry = client.post(f"/api/v1/publish/jobs/{job['id']}/retry", headers=headers)
    assert retry.status_code == 200, retry.text
    retry_payload = retry.json()
    assert retry_payload["status"] == "queued"
    assert retry_payload["retry_count"] == 1

    revoke = client.delete(f"/api/v1/publish/youtube/connections/{connection['id']}", headers=headers)
    assert revoke.status_code == 204, revoke.text


def test_workflow_template_accepts_publish_steps(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    owner = _register(client, email="owner-workflow-publish@test.dev", organization_name="Workflow Publish Org")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    video = _upload_fake_video(client, headers=headers, filename="wf-publish.mp4")

    monkeypatch.setattr("app.publish_api._dispatch_publish_task", lambda _job: "publish-task-2")

    start = client.get("/api/v1/publish/tiktok/connect/start", headers=headers)
    assert start.status_code == 200, start.text
    callback = client.get(
        "/api/v1/publish/tiktok/connect/callback",
        headers=headers,
        params={"state": start.json()["state"], "code": "oauth-code-tt", "account_id": "tt-account-1"},
    )
    assert callback.status_code == 200, callback.text
    connection_id = callback.json()["id"]

    fake_celery = _FakeCelery()
    monkeypatch.setattr("app.api.get_celery_app", lambda: fake_celery)

    template = client.post(
        "/api/v1/workflows/templates",
        headers=headers,
        json={
            "name": "Publish Chain",
            "steps": [
                {"type": "captions", "payload": {"formats": ["srt"]}},
                {"type": "publish_tiktok", "payload": {"connection_id": connection_id}},
            ],
        },
    )
    assert template.status_code == 201, template.text
    template_id = template.json()["id"]

    run = client.post(
        "/api/v1/workflows/runs",
        headers=headers,
        json={"template_id": template_id, "video_asset_id": video["id"]},
    )
    assert run.status_code == 201, run.text
    steps = run.json()["steps"]
    assert any(step["step_type"] == "publish_tiktok" for step in steps)
