from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


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


def _upload_video(client, content: bytes, filename: str = "sample.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        data={"kind": "video"},
        files={"file": (filename, content, "video/mp4")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_end_to_end_cut_clip_job(test_client, tmp_path: Path):
    client, _enqueued, worker, media_root = test_client

    video_bytes = _generate_test_video_bytes(tmp_path, duration_seconds=4.0)
    video = _upload_video(client, video_bytes, filename="source.mp4")

    resp = client.post(
        "/api/v1/utilities/cut-clip",
        json={"video_asset_id": video["id"], "start": 0.5, "end": 1.5},
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()

    worker.cut_clip_asset(job["id"], video["id"], 0.5, 1.5, {"start": 0.5, "end": 1.5})

    done = client.get(f"/api/v1/jobs/{job['id']}")
    assert done.status_code == 200, done.text
    done_job = done.json()
    assert done_job["status"] == "completed"
    assert done_job["output_asset_id"]

    asset = client.get(f"/api/v1/assets/{done_job['output_asset_id']}").json()
    assert asset["kind"] == "video"
    assert asset["uri"].endswith(".mp4")

    out_path = media_root / Path(asset["uri"]).relative_to("/media")
    assert out_path.exists()
    assert out_path.stat().st_size > 0

