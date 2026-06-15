"""Branch-coverage tests for :mod:`app.api` asset/job/usage/project route handlers."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlmodel import Session

from app.database import get_engine
from app.models import MediaAsset


def _register(client, *, email: str, organization_name: str = "Routes Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "organization_name": organization_name},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    body.setdefault("email", email)
    return body


def _upload(client, headers, *, kind="video", filename="a.mp4", content=b"data", ctype="video/mp4"):
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": kind},
        files={"file": (filename, content, ctype)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project(client, headers, name="RP") -> dict:
    resp = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# assets: list / get / delete / download-url / download
# ---------------------------------------------------------------------------


def test_list_assets_with_filters(test_client):
    client, *_ = test_client
    user = _register(client, email="la@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    _upload(client, headers, kind="video", filename="v.mp4")
    _upload(client, headers, kind="subtitle", filename="s.vtt", content=b"WEBVTT", ctype="text/vtt")

    all_assets = client.get("/api/v1/assets", headers=headers)
    assert all_assets.status_code == 200, all_assets.text
    # kind filter
    vids = client.get("/api/v1/assets?kind=video&limit=5", headers=headers)
    assert vids.status_code == 200, vids.text
    assert all(a["kind"] == "video" for a in vids.json())
    # project filter (empty result is fine; exercises the _ensure_project_exists path)
    proj = client.get(f"/api/v1/assets?project_id={project['id']}", headers=headers)
    assert proj.status_code == 200, proj.text


def test_get_asset_404(test_client):
    client, *_ = test_client
    user = _register(client, email="ga404@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.get(f"/api/v1/assets/{uuid4()}", headers=headers)
    assert resp.status_code == 404, resp.text


def test_delete_asset_success_and_404(test_client):
    client, *_ = test_client
    user = _register(client, email="da@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    asset = _upload(client, headers, kind="subtitle", filename="d.vtt", content=b"WEBVTT", ctype="text/vtt")
    ok = client.delete(f"/api/v1/assets/{asset['id']}", headers=headers)
    assert ok.status_code == 204, ok.text
    missing = client.delete(f"/api/v1/assets/{uuid4()}", headers=headers)
    assert missing.status_code == 404, missing.text


def test_delete_asset_referenced_by_job_conflict(test_client):
    client, *_ = test_client
    user = _register(client, email="daref@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    video = _upload(client, headers, kind="video", filename="ref.mp4")
    # Create a captions job referencing the asset.
    job = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    )
    assert job.status_code == 201, job.text
    resp = client.delete(f"/api/v1/assets/{video['id']}", headers=headers)
    assert resp.status_code == 409, resp.text


def test_asset_download_url_presign_and_no_uri(test_client):
    client, *_ = test_client
    user = _register(client, email="dlurl@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    asset = _upload(client, headers, kind="subtitle", filename="u.vtt", content=b"WEBVTT", ctype="text/vtt")
    presigned = client.get(f"/api/v1/assets/{asset['id']}/download-url?presign=true", headers=headers)
    assert presigned.status_code == 200, presigned.text
    plain = client.get(f"/api/v1/assets/{asset['id']}/download-url?presign=false", headers=headers)
    assert plain.status_code == 200, plain.text
    # 404 for unknown asset
    assert client.get(f"/api/v1/assets/{uuid4()}/download-url", headers=headers).status_code == 404

    # Asset with no URI -> 404
    engine = get_engine()
    with Session(engine) as session:
        row = session.get(MediaAsset, UUID(asset["id"]))
        row.uri = ""
        session.add(row)
        session.commit()
    assert client.get(f"/api/v1/assets/{asset['id']}/download-url", headers=headers).status_code == 404


def test_download_asset_local_and_404(test_client):
    client, *_ = test_client
    user = _register(client, email="dla@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    asset = _upload(client, headers, kind="subtitle", filename="dl.vtt", content=b"WEBVTT body", ctype="text/vtt")
    ok = client.get(f"/api/v1/assets/{asset['id']}/download", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.content
    assert client.get(f"/api/v1/assets/{uuid4()}/download", headers=headers).status_code == 404


def test_download_remote_asset_unavailable(test_client):
    client, *_ = test_client
    user = _register(client, email="dlr@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    asset = _upload(client, headers, kind="subtitle", filename="r.vtt", content=b"WEBVTT", ctype="text/vtt")
    # Rewrite to a remote URI that the local backend cannot produce a download URL for.
    engine = get_engine()
    with Session(engine) as session:
        row = session.get(MediaAsset, UUID(asset["id"]))
        row.uri = "s3://unknown-bucket/key.vtt"
        session.add(row)
        session.commit()
    resp = client.get(f"/api/v1/assets/{asset['id']}/download", headers=headers)
    # Local backend get_download_url returns the uri itself, so the proxy attempt yields
    # a remote-download failure (or an unavailable url) -> non-2xx.
    assert resp.status_code in (404, 422, 500), resp.text


# ---------------------------------------------------------------------------
# jobs: get / list filters
# ---------------------------------------------------------------------------


def test_get_job_404(test_client):
    client, *_ = test_client
    user = _register(client, email="gj404@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    assert client.get(f"/api/v1/jobs/{uuid4()}", headers=headers).status_code == 404


def test_list_jobs_with_filters(test_client):
    client, *_ = test_client
    user = _register(client, email="lj@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    video = _upload(client, headers, kind="video", filename="lj.mp4")
    client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    )
    # status filter
    queued = client.get("/api/v1/jobs?status_filter=queued", headers=headers)
    assert queued.status_code == 200, queued.text
    # project filter
    by_project = client.get(f"/api/v1/jobs?project_id={project['id']}", headers=headers)
    assert by_project.status_code == 200, by_project.text


# ---------------------------------------------------------------------------
# usage summary / costs
# ---------------------------------------------------------------------------


def test_usage_summary_and_costs(test_client):
    client, *_ = test_client
    user = _register(client, email="us@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    summary = client.get("/api/v1/usage/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    # with date filters
    filtered = client.get(
        "/api/v1/usage/summary?from=2020-01-01T00:00:00Z&to=2999-01-01T00:00:00Z",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    costs = client.get("/api/v1/usage/costs", headers=headers)
    assert costs.status_code == 200, costs.text


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def test_get_project_and_404(test_client):
    client, *_ = test_client
    user = _register(client, email="gp@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    project = _create_project(client, headers)
    ok = client.get(f"/api/v1/projects/{project['id']}", headers=headers)
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/v1/projects/{uuid4()}", headers=headers).status_code == 404


def test_workflow_templates_listed(test_client):
    client, *_ = test_client
    user = _register(client, email="wt@test.dev")
    headers = {"Authorization": f"Bearer {user['access_token']}"}
    resp = client.get("/api/v1/workflows/templates", headers=headers)
    assert resp.status_code == 200, resp.text
