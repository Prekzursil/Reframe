from __future__ import annotations

from pathlib import Path


def _upload_fake_video(client, *, content: bytes = b"fake-video", filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_delete_job_rejects_active_jobs(test_client):
    client, _enqueued, _worker, _media_root = test_client

    video = _upload_fake_video(client)
    resp = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    delete = client.delete(f"/api/v1/jobs/{job['id']}")
    assert delete.status_code == 409, delete.text


def test_delete_job_can_delete_derived_assets(test_client):
    client, _enqueued, worker, media_root = test_client

    video = _upload_fake_video(client)
    resp = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.generate_captions(job["id"], video["id"], {"formats": ["srt"]})

    done = client.get(f"/api/v1/jobs/{job['id']}")
    assert done.status_code == 200, done.text
    done_job = done.json()
    assert done_job["status"] == "completed"

    out_asset_id = done_job["output_asset_id"]
    assert out_asset_id
    asset = client.get(f"/api/v1/assets/{out_asset_id}").json()

    out_path = media_root / Path(asset["uri"]).relative_to("/media")
    assert out_path.exists()

    delete = client.delete(f"/api/v1/jobs/{job['id']}?delete_assets=true")
    assert delete.status_code == 204, delete.text

    assert client.get(f"/api/v1/jobs/{job['id']}").status_code == 404
    assert client.get(f"/api/v1/assets/{out_asset_id}").status_code == 404
    assert not out_path.exists()


def test_delete_asset_conflicts_when_referenced_by_job(test_client):
    client, _enqueued, _worker, _media_root = test_client

    video = _upload_fake_video(client)
    resp = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert resp.status_code == 201, resp.text

    delete = client.delete(f"/api/v1/assets/{video['id']}")
    assert delete.status_code == 409, delete.text

