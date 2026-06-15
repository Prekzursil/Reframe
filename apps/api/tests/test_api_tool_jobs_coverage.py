"""Branch-coverage tests for :mod:`app.api` tool-job, workflow, and budget routes."""

from __future__ import annotations

from uuid import uuid4


def _register(client, *, email: str, organization_name: str = "Tool Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "organization_name": organization_name},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _upload(client, headers, *, kind, filename, content, ctype, project_id=None):
    data = {"kind": kind}
    if project_id:
        data["project_id"] = project_id
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data=data,
        files={"file": (filename, content, ctype)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _project(client, headers, name="ToolP") -> dict:
    resp = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _auth(client, email):
    user = _register(client, email=email)
    return user, {"Authorization": f"Bearer {user['access_token']}"}


# ---------------------------------------------------------------------------
# shorts / style / merge / cut tool jobs
# ---------------------------------------------------------------------------


def test_create_shorts_job(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "shorts@test.dev")
    video = _upload(client, headers, kind="video", filename="s.mp4", content=b"v", ctype="video/mp4")
    resp = client.post(
        "/api/v1/shorts/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "max_clips": 2},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_type"] == "shorts"
    # missing video asset -> 404
    miss = client.post(
        "/api/v1/shorts/jobs", headers=headers, json={"video_asset_id": str(uuid4())}
    )
    assert miss.status_code == 404, miss.text


def test_create_style_job(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "style@test.dev")
    video = _upload(client, headers, kind="video", filename="v.mp4", content=b"v", ctype="video/mp4")
    sub = _upload(client, headers, kind="subtitle", filename="s.vtt", content=b"WEBVTT", ctype="text/vtt")
    resp = client.post(
        "/api/v1/subtitles/style",
        headers=headers,
        json={
            "video_asset_id": video["id"],
            "subtitle_asset_id": sub["id"],
            "style": {"font": "Inter"},
            "preview_seconds": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_type"] == "style_subtitles"


def test_create_merge_job(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "merge@test.dev")
    video = _upload(client, headers, kind="video", filename="v.mp4", content=b"v", ctype="video/mp4")
    audio = _upload(client, headers, kind="audio", filename="a.aac", content=b"a", ctype="audio/aac")
    resp = client.post(
        "/api/v1/utilities/merge-av",
        headers=headers,
        json={"video_asset_id": video["id"], "audio_asset_id": audio["id"]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_type"] == "merge_av"


def test_create_cut_clip_job(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "cut@test.dev")
    video = _upload(client, headers, kind="video", filename="v.mp4", content=b"v", ctype="video/mp4")
    resp = client.post(
        "/api/v1/utilities/cut-clip",
        headers=headers,
        json={"video_asset_id": video["id"], "start": 1.0, "end": 5.0},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_type"] == "cut_clip"


# ---------------------------------------------------------------------------
# retry job
# ---------------------------------------------------------------------------


def test_retry_job_flows(test_client):
    client, _enqueued, _worker, _media = test_client
    _user, headers = _auth(client, "retry@test.dev")
    video = _upload(client, headers, kind="video", filename="r.mp4", content=b"v", ctype="video/mp4")
    job = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    ).json()
    # Mark the job failed so retry is allowed.
    from uuid import UUID

    from sqlmodel import Session

    from app.database import get_engine
    from app.models import Job, JobStatus

    engine = get_engine()
    with Session(engine) as session:
        row = session.get(Job, UUID(job["id"]))
        row.status = JobStatus.failed
        session.add(row)
        session.commit()

    retry = client.post(f"/api/v1/jobs/{job['id']}/retry", headers=headers)
    assert retry.status_code in (200, 201), retry.text
    # unknown job -> 404
    assert client.post(f"/api/v1/jobs/{uuid4()}/retry", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# budget policy get / put
# ---------------------------------------------------------------------------


def test_budget_policy_get_and_put(test_client, monkeypatch):
    client, *_ = test_client
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    _user, headers = _auth(client, "budget@test.dev")
    get_resp = client.get("/api/v1/usage/budget-policy", headers=headers)
    assert get_resp.status_code == 200, get_resp.text
    put_resp = client.put(
        "/api/v1/usage/budget-policy",
        headers=headers,
        json={
            "monthly_soft_limit_cents": 1000,
            "monthly_hard_limit_cents": 5000,
            "enforce_hard_limit": True,
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    # update existing policy (apply path)
    put2 = client.put(
        "/api/v1/usage/budget-policy",
        headers=headers,
        json={"monthly_soft_limit_cents": 2000, "enforce_hard_limit": False},
    )
    assert put2.status_code == 200, put2.text
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# workflow template + run lifecycle
# ---------------------------------------------------------------------------


def test_workflow_run_template_not_found(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "wfnf@test.dev")
    video = _upload(client, headers, kind="video", filename="w.mp4", content=b"v", ctype="video/mp4")
    resp = client.post(
        "/api/v1/workflows/runs",
        headers=headers,
        json={"template_id": str(uuid4()), "video_asset_id": video["id"]},
    )
    assert resp.status_code == 404, resp.text


def test_workflow_template_create_and_run(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "wf@test.dev")
    video = _upload(client, headers, kind="video", filename="wf.mp4", content=b"v", ctype="video/mp4")

    # invalid step type -> 422
    bad = client.post(
        "/api/v1/workflows/templates",
        headers=headers,
        json={"name": "BadWF", "steps": [{"type": "nonsense"}]},
    )
    assert bad.status_code == 422, bad.text
    # empty steps -> 422
    empty = client.post(
        "/api/v1/workflows/templates", headers=headers, json={"name": "EmptyWF", "steps": []}
    )
    assert empty.status_code == 422, empty.text

    created = client.post(
        "/api/v1/workflows/templates",
        headers=headers,
        json={"name": "CaptionsWF", "steps": [{"type": "captions", "payload": {}}]},
    )
    assert created.status_code in (200, 201), created.text
    template_id = created.json()["id"]

    run = client.post(
        "/api/v1/workflows/runs",
        headers=headers,
        json={"template_id": template_id, "video_asset_id": video["id"]},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    got = client.get(f"/api/v1/workflows/runs/{run_id}", headers=headers)
    assert got.status_code == 200, got.text
    assert client.get(f"/api/v1/workflows/runs/{uuid4()}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# project jobs list
# ---------------------------------------------------------------------------


def test_list_project_jobs(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "pjobs@test.dev")
    project = _project(client, headers)
    resp = client.get(f"/api/v1/projects/{project['id']}/jobs", headers=headers)
    assert resp.status_code == 200, resp.text
    # unknown project -> 404
    assert client.get(f"/api/v1/projects/{uuid4()}/jobs", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# idempotency replay branches for tool jobs
# ---------------------------------------------------------------------------


def test_captions_job_idempotency_replay(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "capidem@test.dev")
    video = _upload(client, headers, kind="video", filename="ci.mp4", content=b"v", ctype="video/mp4")
    body = {"video_asset_id": video["id"], "options": {"formats": ["vtt"]}}
    h = {**headers, "Idempotency-Key": "cap-key-1"}
    first = client.post("/api/v1/captions/jobs", headers=h, json=body)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/captions/jobs", headers=h, json=body)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]


def test_shorts_job_idempotency_replay(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "shortidem@test.dev")
    video = _upload(client, headers, kind="video", filename="si.mp4", content=b"v", ctype="video/mp4")
    body = {"video_asset_id": video["id"], "idempotency_key": "short-key-1"}
    first = client.post("/api/v1/shorts/jobs", headers=headers, json=body)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/shorts/jobs", headers=headers, json=body)
    assert second.status_code == 200, second.text


def test_style_merge_cut_idempotency(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "smc@test.dev")
    video = _upload(client, headers, kind="video", filename="v.mp4", content=b"v", ctype="video/mp4")
    sub = _upload(client, headers, kind="subtitle", filename="s.vtt", content=b"WEBVTT", ctype="text/vtt")
    audio = _upload(client, headers, kind="audio", filename="a.aac", content=b"a", ctype="audio/aac")

    style_body = {
        "video_asset_id": video["id"],
        "subtitle_asset_id": sub["id"],
        "style": {"font": "Inter"},
        "idempotency_key": "style-key",
    }
    assert client.post("/api/v1/subtitles/style", headers=headers, json=style_body).status_code == 201
    assert client.post("/api/v1/subtitles/style", headers=headers, json=style_body).status_code == 200

    merge_body = {
        "video_asset_id": video["id"],
        "audio_asset_id": audio["id"],
        "options": {"idempotency_key": "merge-key"},
    }
    h = {**headers, "Idempotency-Key": "merge-key"}
    assert client.post("/api/v1/utilities/merge-av", headers=h, json=merge_body).status_code == 201
    assert client.post("/api/v1/utilities/merge-av", headers=h, json=merge_body).status_code == 200

    cut_body = {"video_asset_id": video["id"], "start": 1.0, "end": 5.0}
    hc = {**headers, "Idempotency-Key": "cut-key"}
    assert client.post("/api/v1/utilities/cut-clip", headers=hc, json=cut_body).status_code == 201
    assert client.post("/api/v1/utilities/cut-clip", headers=hc, json=cut_body).status_code == 200


# ---------------------------------------------------------------------------
# job bundle download
# ---------------------------------------------------------------------------


def test_download_job_bundle(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "bundle@test.dev")
    video = _upload(client, headers, kind="video", filename="b.mp4", content=b"vbytes", ctype="video/mp4")
    job = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    ).json()
    resp = client.get(f"/api/v1/jobs/{job['id']}/bundle", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content  # a zip archive
    # unknown job -> 404
    assert client.get(f"/api/v1/jobs/{uuid4()}/bundle", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# usage costs with filters + workflow cancel
# ---------------------------------------------------------------------------


def test_usage_costs_with_date_and_project_filters(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "costsfilt@test.dev")
    project = _project(client, headers)
    # date filters + project filter (project has no jobs -> early return path)
    resp = client.get(
        f"/api/v1/usage/costs?from=2020-01-01T00:00:00Z&to=2999-01-01T00:00:00Z"
        f"&project_id={project['id']}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # unknown project -> 404
    assert (
        client.get(f"/api/v1/usage/costs?project_id={uuid4()}", headers=headers).status_code == 404
    )


def test_usage_summary_with_project_filter(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "sumfilt@test.dev")
    project = _project(client, headers)
    resp = client.get(f"/api/v1/usage/summary?project_id={project['id']}", headers=headers)
    assert resp.status_code == 200, resp.text


def test_cancel_workflow_run(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "wfcancel@test.dev")
    video = _upload(client, headers, kind="video", filename="wc.mp4", content=b"v", ctype="video/mp4")
    template = client.post(
        "/api/v1/workflows/templates",
        headers=headers,
        json={"name": "CancelWF", "steps": [{"type": "captions", "payload": {}}]},
    )
    assert template.status_code in (200, 201), template.text
    run = client.post(
        "/api/v1/workflows/runs",
        headers=headers,
        json={"template_id": template.json()["id"], "video_asset_id": video["id"]},
    )
    run_id = run.json()["id"]
    cancel = client.post(f"/api/v1/workflows/runs/{run_id}/cancel", headers=headers)
    assert cancel.status_code == 200, cancel.text
    # cancelling an unknown run -> 404
    assert client.post(f"/api/v1/workflows/runs/{uuid4()}/cancel", headers=headers).status_code == 404


def test_list_jobs_no_status_no_project(test_client):
    client, *_ = test_client
    _user, headers = _auth(client, "ljall@test.dev")
    resp = client.get("/api/v1/jobs", headers=headers)
    assert resp.status_code == 200, resp.text
