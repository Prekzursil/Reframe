from __future__ import annotations

from uuid import UUID

from sqlmodel import Session

from app.database import get_engine
from app.models import Job, JobStatus


def _upload_fake_video(client, *, content: bytes = b"fake-video", filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_caption_job_idempotency_key_dedupes(test_client):
    client, enqueued, _worker, _media_root = test_client
    video = _upload_fake_video(client)

    payload = {
        "video_asset_id": video["id"],
        "options": {"formats": ["srt"]},
        "idempotency_key": "caption-idem-001",
    }
    first = client.post("/api/v1/captions/jobs", json=payload)
    assert first.status_code == 201, first.text

    second = client.post("/api/v1/captions/jobs", json=payload)
    assert second.status_code == 200, second.text

    assert first.json()["id"] == second.json()["id"]
    assert len(enqueued) == 1


def test_retry_job_respects_idempotency_key(test_client):
    client, enqueued, _worker, _media_root = test_client
    video = _upload_fake_video(client)

    created = client.post("/api/v1/captions/jobs", json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}})
    assert created.status_code == 201, created.text
    original_job = created.json()

    with Session(get_engine()) as session:
        job = session.get(Job, UUID(original_job["id"]))
        assert job is not None
        job.status = JobStatus.failed
        session.add(job)
        session.commit()

    headers = {"Idempotency-Key": "retry-idem-001"}
    retry_1 = client.post(f"/api/v1/jobs/{original_job['id']}/retry", headers=headers)
    assert retry_1.status_code == 201, retry_1.text

    retry_2 = client.post(f"/api/v1/jobs/{original_job['id']}/retry", headers=headers)
    assert retry_2.status_code == 200, retry_2.text
    assert retry_1.json()["id"] == retry_2.json()["id"]

    # Initial enqueue + one retry enqueue only.
    assert len(enqueued) == 2
