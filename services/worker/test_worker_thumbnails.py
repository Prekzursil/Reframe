from __future__ import annotations

from pathlib import Path
from uuid import UUID


def test_create_thumbnail_asset_falls_back_when_ffmpeg_missing(monkeypatch, tmp_path):
    from services.worker import worker

    calls = []

    def fake_create_asset(*, kind, mime_type, suffix, contents=b"", source_path=None):
        calls.append(
            {
                "kind": kind,
                "mime_type": mime_type,
                "suffix": suffix,
                "contents": contents,
                "source_path": source_path,
            }
        )

        class DummyAsset:
            uri = "/media/tmp/fallback.png"

        return DummyAsset()

    monkeypatch.setattr(worker, "create_asset", fake_create_asset)
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)

    asset = worker.create_thumbnail_asset(tmp_path / "video.mp4")
    assert asset.uri == "/media/tmp/fallback.png"
    assert calls and calls[-1]["kind"] == "image"
    assert calls[-1]["mime_type"] == "image/png"
    assert calls[-1]["source_path"] is None


def test_create_thumbnail_asset_uses_ffmpeg_when_available(monkeypatch, tmp_path):
    from services.worker import worker

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake-video")

    monkeypatch.setattr(worker, "get_media_tmp", lambda: tmp_path)
    monkeypatch.setattr(worker, "uuid4", lambda: UUID(int=0))
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    runner_calls = []

    def fake_runner(cmd, check=True, capture_output=True):
        runner_calls.append(cmd)
        output = Path(cmd[-1])
        output.write_bytes(b"png")

        class DummyCompleted:
            returncode = 0
            stdout = b""
            stderr = b""

        return DummyCompleted()

    created = []

    def fake_create_asset(*, kind, mime_type, suffix, contents=b"", source_path=None):
        created.append(
            {
                "kind": kind,
                "mime_type": mime_type,
                "suffix": suffix,
                "contents": contents,
                "source_path": source_path,
            }
        )

        class DummyAsset:
            uri = "/media/tmp/thumb.png"

        return DummyAsset()

    monkeypatch.setattr(worker, "create_asset", fake_create_asset)

    asset = worker.create_thumbnail_asset(video, runner=fake_runner)

    assert runner_calls, "expected ffmpeg runner to be called"
    assert runner_calls[0][0].endswith("ffmpeg")
    assert "scale=320:-1" in runner_calls[0]
    assert asset.uri == "/media/tmp/thumb.png"
    assert any(entry["source_path"] is not None for entry in created)

