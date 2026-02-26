from __future__ import annotations

from pathlib import Path

from media_core.diarize.models import SpeakerSegment


def _upload_fake_video(client, *, content: bytes = b"fake-video", filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_end_to_end_video_to_srt_with_speaker_labels_job(test_client, monkeypatch):
    client, _enqueued, worker, _media_root = test_client

    video = _upload_fake_video(client)

    resp = client.post(
        "/api/v1/captions/jobs",
        json={
            "video_asset_id": video["id"],
            "options": {"formats": ["srt"], "speaker_labels": True, "diarization_backend": "pyannote"},
        },
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    def fake_extract(_video_path: Path, output_path: Path, runner=None) -> None:  # noqa: ARG001
        output_path.write_bytes(b"fake-wav")

    def fake_diarize(_audio_path: Path, _config) -> list[SpeakerSegment]:  # noqa: ANN001
        return [SpeakerSegment(start=0.0, end=10.0, speaker="SPEAKER_01")]

    monkeypatch.setattr(worker, "_extract_audio_wav_for_diarization", fake_extract)
    monkeypatch.setattr(worker, "diarize_audio", fake_diarize)

    worker.generate_captions(
        job["id"],
        video["id"],
        {"formats": ["srt"], "speaker_labels": True, "diarization_backend": "pyannote"},
    )

    refreshed = client.get(f"/api/v1/jobs/{job['id']}")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_job = refreshed.json()
    assert refreshed_job["status"] == "completed"
    assert refreshed_job["output_asset_id"]

    asset = client.get(f"/api/v1/assets/{refreshed_job['output_asset_id']}").json()
    download = client.get(f"/api/v1/assets/{asset['id']}/download")
    assert download.status_code == 200, download.text
    assert b"SPEAKER_01:" in download.content
