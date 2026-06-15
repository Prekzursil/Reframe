"""Tests for the worker thumbnail-asset creation helper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from services.worker import worker  # pylint: disable=import-error


def test_create_thumbnail_asset_falls_back_when_ffmpeg_missing(monkeypatch, tmp_path):
    """When ffmpeg is unavailable, a PNG placeholder asset is created."""
    calls = []

    def fake_create_asset(**kwargs):
        calls.append(
            {
                "kind": kwargs.get("kind"),
                "mime_type": kwargs.get("mime_type"),
                "suffix": kwargs.get("suffix"),
                "contents": kwargs.get("contents", b""),
                "source_path": kwargs.get("source_path"),
                "project_id": kwargs.get("project_id"),
            }
        )
        return SimpleNamespace(uri="/media/tmp/fallback.png")

    monkeypatch.setattr(worker, "create_asset", fake_create_asset)
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)

    asset = worker.create_thumbnail_asset(tmp_path / "video.mp4")
    assert asset.uri == "/media/tmp/fallback.png"
    assert calls and calls[-1]["kind"] == "image"
    assert calls[-1]["mime_type"] == "image/png"
    assert calls[-1]["source_path"] is None


def test_create_thumbnail_asset_uses_ffmpeg_when_available(monkeypatch, tmp_path):
    """When ffmpeg is available, it is invoked to render the thumbnail."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    monkeypatch.setattr(worker, "get_media_tmp", lambda: tmp_path)
    monkeypatch.setattr(worker, "uuid4", lambda: UUID(int=0))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    runner_calls = []

    def fake_runner(cmd, check=True, capture_output=True):  # pylint: disable=unused-argument
        runner_calls.append(cmd)
        output = Path(cmd[-1])
        output.write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    created = []

    def fake_create_asset(**kwargs):
        created.append(
            {
                "kind": kwargs.get("kind"),
                "mime_type": kwargs.get("mime_type"),
                "suffix": kwargs.get("suffix"),
                "contents": kwargs.get("contents", b""),
                "source_path": kwargs.get("source_path"),
                "project_id": kwargs.get("project_id"),
            }
        )
        return SimpleNamespace(uri="/media/tmp/thumb.png")

    monkeypatch.setattr(worker, "create_asset", fake_create_asset)

    asset = worker.create_thumbnail_asset(video, runner=fake_runner)

    assert runner_calls, "expected ffmpeg runner to be called"
    assert runner_calls[0][0].endswith("ffmpeg")
    assert "scale=320:-1" in runner_calls[0]
    assert asset.uri == "/media/tmp/thumb.png"
    assert any(entry["source_path"] is not None for entry in created)
