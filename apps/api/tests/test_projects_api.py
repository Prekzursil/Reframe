from __future__ import annotations


def test_projects_crud_and_filters(test_client):
    client, _enqueued, _worker, _media_root = test_client

    create_project = client.post("/api/v1/projects", json={"name": "Campaign A", "description": "Spring content"})
    assert create_project.status_code == 201, create_project.text
    project = create_project.json()

    listed = client.get("/api/v1/projects")
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == project["id"] for item in listed.json())

    upload = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video", "project_id": project["id"]},
        files={"file": ("clip.mp4", b"video-bytes", "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    assert asset["project_id"] == project["id"]

    job_resp = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": asset["id"], "project_id": project["id"], "options": {"formats": ["srt"]}},
    )
    assert job_resp.status_code == 201, job_resp.text
    job = job_resp.json()
    assert job["project_id"] == project["id"]

    project_jobs = client.get(f"/api/v1/projects/{project['id']}/jobs")
    assert project_jobs.status_code == 200, project_jobs.text
    assert any(item["id"] == job["id"] for item in project_jobs.json())

    project_assets = client.get(f"/api/v1/projects/{project['id']}/assets")
    assert project_assets.status_code == 200, project_assets.text
    assert any(item["id"] == asset["id"] for item in project_assets.json())


def test_create_job_with_unknown_project_is_rejected(test_client):
    client, _enqueued, _worker, _media_root = test_client
    upload = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": ("clip.mp4", b"video-bytes", "video/mp4")},
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()

    resp = client.post(
        "/api/v1/captions/jobs",
        json={
            "video_asset_id": asset["id"],
            "project_id": "00000000-0000-0000-0000-000000000099",
            "options": {"formats": ["srt"]},
        },
    )
    assert resp.status_code == 404, resp.text
