from __future__ import annotations

from app.rate_limit import RateLimiter


def test_heavy_job_endpoints_use_separate_limit_policy(test_client, monkeypatch):
    client, _, _, _ = test_client

    import app.rate_limit as rate_limit_module

    heavy = RateLimiter(limit=1, window_seconds=60)
    monkeypatch.setitem(rate_limit_module.policy_limiters, "heavy_jobs", heavy)

    upload = client.post(
        "/api/v1/assets/upload",
        files={"file": ("source.mp4", b"fake-video", "video/mp4")},
        data={"kind": "video"},
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()

    first = client.post(
        "/api/v1/shorts/jobs",
        json={"video_asset_id": asset["id"], "max_clips": 1, "min_duration": 2, "max_duration": 3},
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/v1/shorts/jobs",
        json={"video_asset_id": asset["id"], "max_clips": 1, "min_duration": 2, "max_duration": 3},
    )
    assert second.status_code == 429, second.text
    body = second.json()
    assert body["code"] == "RATE_LIMITED"
    assert body["details"]["policy"] == "heavy_jobs"


def test_upload_init_uses_upload_policy_limit(test_client, monkeypatch):
    client, _, _, _ = test_client

    import app.rate_limit as rate_limit_module

    upload_limiter = RateLimiter(limit=1, window_seconds=60)
    monkeypatch.setitem(rate_limit_module.policy_limiters, "uploads", upload_limiter)

    first = client.post(
        "/api/v1/assets/upload-init",
        json={"kind": "video", "filename": "clip.mp4", "mime_type": "video/mp4"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/v1/assets/upload-init",
        json={"kind": "video", "filename": "clip-2.mp4", "mime_type": "video/mp4"},
    )
    assert second.status_code == 429, second.text
    payload = second.json()
    assert payload["code"] == "RATE_LIMITED"
    assert payload["details"]["policy"] == "uploads"
