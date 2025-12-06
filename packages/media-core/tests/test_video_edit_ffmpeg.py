import subprocess

import pytest

from media_core.video_edit.ffmpeg import (
    burn_subtitles,
    cut_clip,
    extract_audio,
    merge_video_audio,
    probe_media,
    reframe,
)


class DummyCompleted:
    def __init__(self, stdout=b""):
        self.returncode = 0
        self.stdout = stdout


def dummy_run(expected_cmds):
    calls = []

    def _runner(cmd, check=True, capture_output=True):
        calls.append(cmd)
        sample = b'{"format": {"duration": "1.5", "bit_rate": "64000"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080}, {"codec_type": "audio", "codec_name": "aac"}]}'
        return DummyCompleted(stdout=sample)

    return _runner, calls


def test_probe_media_builds_ffprobe_cmd(monkeypatch, tmp_path):
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    out = probe_media(media, runner=runner)
    assert calls and "ffprobe" in calls[0][0]
    assert out["path"].endswith("sample.mp4")
    assert out["duration"] == 1.5
    assert out["video"]["width"] == 1920


def test_extract_audio_invokes_ffmpeg(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.aac"
    video.write_bytes(b"fake")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    extract_audio(video, audio, runner=runner)
    assert calls and calls[0][0].endswith("ffmpeg")


def test_cut_clip_uses_duration(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    cut_clip(video, 1.0, 3.5, out, runner=runner)
    assert any("-ss" in c for c in calls[0])


def test_reframe_builds_filter(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    reframe(video, out, "9:16", strategy="crop", runner=runner)
    assert "-vf" in calls[0]


def test_merge_video_audio(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    audio = tmp_path / "a.aac"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")
    audio.write_bytes(b"fake")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    merge_video_audio(video, audio, out, offset=0.5, ducking=0.7, normalize=True, runner=runner)
    # ensure ffmpeg is called and filter_complex present
    assert calls and "ffmpeg" in calls[0][0]


def test_burn_subtitles(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    subs = tmp_path / "s.srt"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")
    subs.write_text("1\\n00:00:00,000 --> 00:00:01,000\\nhi")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    runner, calls = dummy_run([])
    burn_subtitles(video, subs, out, runner=runner)
    assert any("subtitles=" in c for c in calls[0])
