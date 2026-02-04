from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _upload_fake_video(client, *, content: bytes = b"fake-video", filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_fake_audio(client, *, content: bytes = b"fake-audio", filename: str = "sample.aac") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "audio"},
        files={"file": (filename, content, "audio/aac")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe not available")
    return ffmpeg


def _generate_test_video_bytes(tmp_path: Path, *, duration_seconds: float = 3.0) -> bytes:
    ffmpeg = _require_ffmpeg()
    out = tmp_path / "fixture.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x240:d={duration_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration_seconds}",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out.read_bytes()


def _generate_test_audio_bytes(tmp_path: Path, *, duration_seconds: float = 3.0) -> bytes:
    ffmpeg = _require_ffmpeg()
    out = tmp_path / "fixture.aac"
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_seconds}",
        "-c:a",
        "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out.read_bytes()


def _generate_test_video_with_silence_bytes(
    tmp_path: Path,
    *,
    silence_seconds: float = 4.0,
    tone_seconds: float = 4.0,
    tone_hz: float = 1000.0,
) -> bytes:
    ffmpeg = _require_ffmpeg()
    total = silence_seconds * 2 + tone_seconds
    out = tmp_path / "fixture_silence.mp4"
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=320x240:d={total}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=16000:cl=mono:d={silence_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={tone_hz}:duration={tone_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r=16000:cl=mono:d={silence_seconds}",
        "-filter_complex",
        "[1:a][2:a][3:a]concat=n=3:v=0:a=1[aout]",
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out.read_bytes()


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
    assert b"00:00:00,000 -->" in download.content


def test_end_to_end_srt_translation_job(test_client):
    client, _enqueued, worker, _media_root = test_client

    video = _upload_fake_video(client)

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

    translate = client.post(
        "/api/v1/subtitles/translate",
        json={"subtitle_asset_id": subtitle_id, "target_language": "es"},
    )
    assert translate.status_code == 201, translate.text
    translate_job = translate.json()

    worker.translate_subtitles(translate_job["id"], subtitle_id, {"target_language": "es"})

    translated_done = client.get(f"/api/v1/jobs/{translate_job['id']}").json()
    assert translated_done["status"] == "completed"
    assert translated_done["output_asset_id"]

    translated_asset = client.get(f"/api/v1/assets/{translated_done['output_asset_id']}").json()
    assert translated_asset["kind"] == "subtitle"
    assert translated_asset["uri"].endswith(".srt")


def test_end_to_end_video_to_tiktok_style_rendered_job(test_client, tmp_path: Path):
    client, _enqueued, worker, media_root = test_client

    video_bytes = _generate_test_video_bytes(tmp_path, duration_seconds=4.0)
    video = _upload_fake_video(client, content=video_bytes, filename="styled.mp4")

    captions = client.post(
        "/api/v1/captions/jobs",
        json={"video_asset_id": video["id"], "options": {"formats": ["vtt"]}},
    )
    assert captions.status_code == 201, captions.text
    captions_job = captions.json()
    worker.generate_captions(captions_job["id"], video["id"], {"formats": ["vtt"]})

    captions_done = client.get(f"/api/v1/jobs/{captions_job['id']}").json()
    subtitle_id = captions_done["output_asset_id"]
    assert subtitle_id
    subtitle_asset = client.get(f"/api/v1/assets/{subtitle_id}").json()
    assert subtitle_asset["uri"].endswith(".vtt")

    style = {"font": "Inter", "text_color": "#ffffff", "highlight_color": "#facc15"}
    styled = client.post(
        "/api/v1/subtitles/style",
        json={"video_asset_id": video["id"], "subtitle_asset_id": subtitle_id, "style": style, "preview_seconds": 2},
    )
    assert styled.status_code == 201, styled.text
    styled_job = styled.json()

    worker.render_styled_subtitles(styled_job["id"], video["id"], subtitle_id, style, {"preview_seconds": 2})

    styled_done = client.get(f"/api/v1/jobs/{styled_job['id']}").json()
    assert styled_done["status"] == "completed"
    assert styled_done["output_asset_id"]

    output_asset = client.get(f"/api/v1/assets/{styled_done['output_asset_id']}").json()
    assert output_asset["kind"] == "video"
    assert output_asset["uri"].endswith(".mp4")

    download = client.get(f"/api/v1/assets/{output_asset['id']}/download")
    assert download.status_code == 200, download.text
    assert download.content

    from media_core.video_edit.ffmpeg import probe_media

    out_path = media_root / Path(output_asset["uri"]).relative_to("/media")
    info = probe_media(out_path)
    assert info["duration"] is not None
    assert float(info["duration"]) <= 2.2


def test_end_to_end_video_to_shorts_with_subtitles_job(test_client, tmp_path: Path):
    client, _enqueued, worker, media_root = test_client

    video_bytes = _generate_test_video_bytes(tmp_path, duration_seconds=4.0)
    video = _upload_fake_video(client, content=video_bytes, filename="shorts.mp4")

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

    worker.generate_shorts(
        job["id"],
        video["id"],
        {"max_clips": 2, "min_duration": 1, "max_duration": 2, "aspect_ratio": "9:16", **payload["options"]},
    )

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


def test_end_to_end_video_to_shorts_trim_silence_prefers_non_silent_segments(test_client, tmp_path: Path):
    client, _enqueued, worker, _media_root = test_client

    video_bytes = _generate_test_video_with_silence_bytes(tmp_path, silence_seconds=4.0, tone_seconds=4.0)
    video = _upload_fake_video(client, content=video_bytes, filename="shorts-silence.mp4")

    payload = {
        "video_asset_id": video["id"],
        "max_clips": 1,
        "min_duration": 3,
        "max_duration": 4,
        "aspect_ratio": "9:16",
        "options": {"trim_silence": True},
    }
    resp = client.post("/api/v1/shorts/jobs", json=payload)
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.generate_shorts(
        job["id"],
        video["id"],
        {"max_clips": 1, "min_duration": 3, "max_duration": 4, "aspect_ratio": "9:16", **payload["options"]},
    )

    done = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert done["status"] == "completed"
    clips = done["payload"].get("clip_assets")
    assert isinstance(clips, list)
    assert len(clips) == 1

    clip = clips[0]
    assert 3.5 <= float(clip.get("start")) <= 4.5, f"expected tone segment around 4s start, got {clip}"


def test_end_to_end_video_audio_merge_job(test_client, tmp_path: Path):
    client, _enqueued, worker, media_root = test_client

    video_bytes = _generate_test_video_bytes(tmp_path, duration_seconds=3.0)
    audio_bytes = _generate_test_audio_bytes(tmp_path, duration_seconds=3.0)
    video = _upload_fake_video(client, content=video_bytes, filename="merge.mp4")
    audio = _upload_fake_audio(client, content=audio_bytes, filename="merge.aac")

    resp = client.post(
        "/api/v1/utilities/merge-av",
        json={"video_asset_id": video["id"], "audio_asset_id": audio["id"], "offset": 0.0, "ducking": True, "normalize": True},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.merge_video_audio(job["id"], video["id"], audio["id"], job["payload"])

    refreshed = client.get(f"/api/v1/jobs/{job['id']}")
    assert refreshed.status_code == 200, refreshed.text
    done = refreshed.json()
    assert done["status"] == "completed"
    assert done["output_asset_id"]

    merged_asset = client.get(f"/api/v1/assets/{done['output_asset_id']}").json()
    assert merged_asset["kind"] == "video"
    assert merged_asset["uri"].endswith(".mp4")

    merged_path = media_root / Path(merged_asset["uri"]).relative_to("/media")
    assert merged_path.exists()
    assert merged_path.stat().st_size > 0

    from media_core.video_edit.ffmpeg import probe_media

    info = probe_media(merged_path)
    assert info["audio_codecs"], "expected an audio track in merged output"
