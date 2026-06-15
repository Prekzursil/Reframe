"""Branch-coverage tests for :mod:`app.publish_api` routes and helpers."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app import publish_api
from app.errors import ApiError
from app.models import PublishConnection
from app.security import create_oauth_state


def _register(client, *, email: str, organization_name: str = "Pub Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "organization_name": organization_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_video(client, headers) -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": "video"},
        files={"file": ("v.mp4", b"video-bytes", "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_provider_display():
    assert publish_api._provider_display("youtube") == "YouTube"
    assert publish_api._provider_display("vimeo") == "Vimeo"  # title-cased fallback


def test_validate_provider_rejects_unknown():
    with pytest.raises(ApiError) as exc:
        publish_api._validate_provider("myspace")
    assert exc.value.status_code == 422


def test_hash_secret():
    assert publish_api._hash_secret(None) is None
    assert publish_api._hash_secret("") is None
    assert publish_api._hash_secret("abc") is not None


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------


def test_routes_require_hosted_principal(test_client):
    client, *_ = test_client
    # No auth -> 401 across publish routes.
    assert client.get("/api/v1/publish/providers").status_code == 401
    assert client.get("/api/v1/publish/youtube/connections").status_code == 401
    assert client.get("/api/v1/publish/jobs").status_code == 401


# ---------------------------------------------------------------------------
# connections list / callback / revoke
# ---------------------------------------------------------------------------


def test_list_connections_empty(test_client):
    client, *_ = test_client
    user = _register(client, email="conn-list@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.get("/api/v1/publish/youtube/connections", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_complete_connection_invalid_state(test_client):
    client, *_ = test_client
    user = _register(client, email="cb-badstate@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # State for a different org/provider prefix -> 401.
    bad_state = create_oauth_state(provider="publish:youtube:other-org", redirect_to=None)
    resp = client.get(
        f"/api/v1/publish/youtube/connect/callback?state={bad_state}&code=abc", headers=headers
    )
    assert resp.status_code == 401, resp.text


def test_complete_connection_missing_code(test_client):
    client, *_ = test_client
    user = _register(client, email="cb-nocode@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    state = create_oauth_state(
        provider=f"publish:youtube:{user['org_id']}", redirect_to=None
    )
    resp = client.get(
        f"/api/v1/publish/youtube/connect/callback?state={state}", headers=headers
    )
    assert resp.status_code == 401, resp.text


def test_connect_start_and_complete_and_revoke(test_client):
    client, *_ = test_client
    user = _register(client, email="cb-ok@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    start = client.get("/api/v1/publish/youtube/connect/start", headers=headers)
    assert start.status_code == 200, start.text
    state = start.json()["state"]
    cb = client.get(
        f"/api/v1/publish/youtube/connect/callback?state={state}&code=authcode"
        "&account_id=acc1&account_label=My Channel",
        headers=headers,
    )
    assert cb.status_code == 200, cb.text
    connection_id = cb.json()["id"]

    revoke = client.delete(
        f"/api/v1/publish/youtube/connections/{connection_id}", headers=headers
    )
    assert revoke.status_code == 204, revoke.text


def test_revoke_connection_not_found(test_client):
    client, *_ = test_client
    user = _register(client, email="revoke-404@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.delete(
        f"/api/v1/publish/youtube/connections/{uuid4()}", headers=headers
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# publish jobs
# ---------------------------------------------------------------------------


def test_create_publish_job_connection_not_found(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="job-noconn@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    video = _upload_video(client, headers)
    resp = client.post(
        "/api/v1/publish/jobs",
        headers=headers,
        json={"provider": "youtube", "connection_id": str(uuid4()), "asset_id": video["id"]},
    )
    assert resp.status_code == 404, resp.text


def _make_connection(client, headers, user) -> str:
    start = client.get("/api/v1/publish/youtube/connect/start", headers=headers)
    state = start.json()["state"]
    cb = client.get(
        f"/api/v1/publish/youtube/connect/callback?state={state}&code=c", headers=headers
    )
    return cb.json()["id"]


def test_create_publish_job_asset_not_found(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="job-noasset@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    conn_id = _make_connection(client, headers, user)
    resp = client.post(
        "/api/v1/publish/jobs",
        headers=headers,
        json={"provider": "youtube", "connection_id": conn_id, "asset_id": str(uuid4())},
    )
    assert resp.status_code == 404, resp.text


def test_create_list_get_retry_publish_job(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="job-full@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    video = _upload_video(client, headers)
    conn_id = _make_connection(client, headers, user)
    monkeypatch.setattr(publish_api, "_dispatch_publish_task", lambda job: "task-abc")

    create = client.post(
        "/api/v1/publish/jobs",
        headers=headers,
        json={
            "provider": "youtube",
            "connection_id": conn_id,
            "asset_id": video["id"],
            "title": "My Video",
            "description": "desc",
            "tags": ["a", " ", "b"],
            "workflow_run_id": str(uuid4()),
        },
    )
    assert create.status_code == 201, create.text
    job_id = create.json()["id"]
    assert create.json()["task_id"] == "task-abc"

    # list with provider + status filters.
    listed = client.get(
        "/api/v1/publish/jobs?provider=youtube&status=queued", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert any(j["id"] == job_id for j in listed.json())

    got = client.get(f"/api/v1/publish/jobs/{job_id}", headers=headers)
    assert got.status_code == 200, got.text

    # retry while queued -> 409 conflict (not retryable).
    conflict = client.post(f"/api/v1/publish/jobs/{job_id}/retry", headers=headers)
    assert conflict.status_code == 409, conflict.text


def test_get_publish_job_not_found(test_client):
    client, *_ = test_client
    user = _register(client, email="getjob-404@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.get(f"/api/v1/publish/jobs/{uuid4()}", headers=headers)
    assert resp.status_code == 404, resp.text


def test_retry_publish_job_not_found(test_client):
    client, *_ = test_client
    user = _register(client, email="retry-404@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.post(f"/api/v1/publish/jobs/{uuid4()}/retry", headers=headers)
    assert resp.status_code == 404, resp.text


def test_retry_failed_publish_job_redispatches(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="retry-ok@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    video = _upload_video(client, headers)
    conn_id = _make_connection(client, headers, user)
    monkeypatch.setattr(publish_api, "_dispatch_publish_task", lambda job: "task-1")

    create = client.post(
        "/api/v1/publish/jobs",
        headers=headers,
        json={
            "provider": "youtube",
            "connection_id": conn_id,
            "asset_id": video["id"],
        },
    )
    assert create.status_code == 201, create.text
    job_id = create.json()["id"]

    # Force a failed state and an invalid stored workflow_run_id so the retry path
    # exercises both the retryable-status branch and the UUID parse-failure branch.
    from sqlmodel import Session
    from sqlalchemy.orm.attributes import flag_modified

    from app.database import get_engine
    from app.models import PublishJob
    from uuid import UUID

    engine = get_engine()
    with Session(engine) as session:
        job = session.get(PublishJob, UUID(job_id))
        job.status = "failed"
        payload = dict(job.payload or {})
        payload["workflow_run_id"] = "not-a-uuid"
        job.payload = payload
        flag_modified(job, "payload")
        session.add(job)
        session.commit()

    monkeypatch.setattr(publish_api, "_dispatch_publish_task", lambda job: "task-2")
    retry = client.post(f"/api/v1/publish/jobs/{job_id}/retry", headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["retry_count"] == 1


def test_list_jobs_status_filter_only(test_client, monkeypatch):
    client, *_ = test_client
    user = _register(client, email="job-statusonly@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    # status filter without provider exercises the 478->480 branch path.
    resp = client.get("/api/v1/publish/jobs?status=queued", headers=headers)
    assert resp.status_code == 200, resp.text


def test_celery_app_and_dispatch(monkeypatch):
    # Exercise _celery_app construction (no broker connection attempted at build time).
    publish_api._celery_app.cache_clear()
    app = publish_api._celery_app()
    assert app is not None
    publish_api._celery_app.cache_clear()

    # Exercise _dispatch_publish_task with a fake celery app (no real broker).
    class _FakeResult:
        id = "dispatched-id"

    class _FakeCelery:
        def send_task(self, name, args):
            assert name == "tasks.publish_asset"
            return _FakeResult()

    monkeypatch.setattr(publish_api, "_celery_app", lambda: _FakeCelery())

    class _Job:
        id = uuid4()

    assert publish_api._dispatch_publish_task(_Job()) == "dispatched-id"
