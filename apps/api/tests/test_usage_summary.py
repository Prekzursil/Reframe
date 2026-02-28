from __future__ import annotations

import os

def _hosted_auth_headers(client) -> dict[str, str]:
    hosted_mode = os.getenv("REFRAME_HOSTED_MODE", "").strip().lower() == "true"
    if not hosted_mode:
        return {}

    register = client.post(
        "/api/v1/auth/register",
        json={
            "email": "usage-summary@example.com",
            "password": "password-1234",
            "organization_name": "Usage Summary Team",
        },
    )
    assert register.status_code == 201, register.text
    token = register.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload_video(client, headers: dict[str, str], name: str = "video.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": "video"},
        files={"file": (name, b"video-bytes", "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_usage_summary_counts_jobs_and_outputs(test_client):
    client, _enqueued, worker, _media_root = test_client
    headers = _hosted_auth_headers(client)

    video = _upload_video(client, headers)

    first = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert first.status_code == 201, first.text
    first_job = first.json()

    second = client.post(
        "/api/v1/shorts/jobs",
        headers=headers,
        json={"video_asset_id": video["id"], "max_clips": 1, "min_duration": 1, "max_duration": 2, "aspect_ratio": "9:16"},
    )
    assert second.status_code == 201, second.text

    summary_before = client.get("/api/v1/usage/summary", headers=headers)
    assert summary_before.status_code == 200, summary_before.text
    payload_before = summary_before.json()
    assert payload_before["total_jobs"] >= 2
    assert payload_before["queued_jobs"] >= 2

    worker.generate_captions(first_job["id"], video["id"], {"formats": ["srt"]})

    summary_after = client.get("/api/v1/usage/summary", headers=headers)
    assert summary_after.status_code == 200, summary_after.text
    payload_after = summary_after.json()

    assert payload_after["total_jobs"] >= 2
    assert payload_after["completed_jobs"] >= 1
    assert payload_after["job_type_counts"].get("captions", 0) >= 1
    assert payload_after["output_assets_count"] >= 1
