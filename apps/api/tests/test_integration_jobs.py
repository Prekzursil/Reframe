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


def test_end_to_end_video_to_srt_job(test_client):
    client, _enqueued, worker, _media_root = test_client

    video = _upload_fake_video(client)

    resp = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.generate_captions(job["id"], video["id"], {"formats": ["srt"]})

    refreshed = client.get(f"/api/v1/jobs/{job['id']}")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_job = refreshed.json()
    assert refreshed_job["status"] == "completed"
    assert refreshed_job["output_asset_id"]

    asset = client.get(f"/api/v1/assets/{refreshed_job['output_asset_id']}").json()
    assert asset["kind"] == "subtitle"
    assert asset["uri"].endswith(".srt")

    download = client.get(f"/api/v1/assets/{asset['id']}/download")
    assert download.status_code == 200, download.text
    assert b"00:00:00,000 --> 00:00:02,000" in download.content


def test_end_to_end_video_to_tiktok_style_rendered_job(test_client):
    client, _enqueued, worker, _media_root = test_client

    original_bytes = b"fake-video-bytes"
    video = _upload_fake_video(client, content=original_bytes, filename="styled.mp4")

    captions = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["srt"]}},
    )
    assert captions.status_code == 201, captions.text
    captions_job = captions.json()
    worker.generate_captions(captions_job["id"], video["id"], {"formats": ["srt"]})

    captions_done = client.get(f"/api/v1/jobs/{captions_job['id']}").json()
    subtitle_id = captions_done["output_asset_id"]
    assert subtitle_id

    style = {"font": "Inter", "text_color": "#ffffff"}
    styled = client.post(
        "/api/v1/subtitles/style",
        json={"video_asset_id": video["id"], "subtitle_asset_id": subtitle_id, "style": style, "preview_seconds": 5},
    )
    assert styled.status_code == 201, styled.text
    styled_job = styled.json()

    worker.render_styled_subtitles(styled_job["id"], video["id"], subtitle_id, style, {"preview_seconds": 5})

    styled_done = client.get(f"/api/v1/jobs/{styled_job['id']}").json()
    assert styled_done["status"] == "completed"
    assert styled_done["output_asset_id"]

    output_asset = client.get(f"/api/v1/assets/{styled_done['output_asset_id']}").json()
    assert output_asset["kind"] == "video"
    assert output_asset["uri"].endswith(".mp4")

    download = client.get(f"/api/v1/assets/{output_asset['id']}/download")
    assert download.status_code == 200, download.text
    assert download.content == original_bytes


def test_end_to_end_video_to_shorts_with_subtitles_job(test_client):
    client, _enqueued, worker, media_root = test_client

    video = _upload_fake_video(client, content=b"fake-shorts-video", filename="shorts.mp4")

    payload = {
        "video_asset_id": video["id"],
        "max_clips": 2,
        "min_duration": 1,
        "max_duration": 2,
        "aspect_ratio": "9:16",
        "options": {"use_subtitles": True, "style_preset": "TikTok Bold"},
    }
    resp = client.post("/api/v1/shorts/jobs", json=payload)
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.generate_shorts(job["id"], video["id"], {**payload["options"], "max_clips": 2, "min_duration": 1})

    refreshed = client.get(f"/api/v1/jobs/{job['id']}")
    assert refreshed.status_code == 200, refreshed.text
    done = refreshed.json()
    assert done["status"] == "completed"
    assert done["payload"]
    clips = done["payload"].get("clip_assets")
    assert isinstance(clips, list)
    assert len(clips) == 2
    assert all(c.get("subtitle_uri") for c in clips)

    for clip in clips:
        uri = clip.get("subtitle_uri")
        assert isinstance(uri, str)
        assert uri.startswith("/media/")
        path = media_root / Path(uri).relative_to("/media")
        assert path.exists()
