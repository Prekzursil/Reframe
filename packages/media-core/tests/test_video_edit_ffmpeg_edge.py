"""Edge-case coverage for ffmpeg wrappers (command building + error handling)."""

from __future__ import annotations

import subprocess

import pytest

from media_core.video_edit import ffmpeg
from media_core.video_edit.ffmpeg import (
    _ensure_binary,
    _match_value,
    _parse_silence_log,
    _run,
    _SILENCE_END_RE,
    detect_silence,
    merge_video_audio,
    probe_media,
    reframe,
)


class _Completed:
    def __init__(self, stdout=b"", stderr=b""):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = stderr


def _which_ok(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)


# ---------------------------------------------------------------------------
# _ensure_binary / _run
# ---------------------------------------------------------------------------
def test_ensure_binary_missing_raises(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
        _ensure_binary("ffmpeg")


def test_run_logs_and_reraises_on_called_process_error(caplog):
    def failing_runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        raise subprocess.CalledProcessError(
            returncode=2,
            cmd=cmd,
            output=b"some stdout",
            stderr=b"some stderr",
        )

    with pytest.raises(subprocess.CalledProcessError):
        _run(["ffmpeg", "-i", "x"], runner=failing_runner)


def test_run_handles_non_bytes_streams():
    def failing_runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        err = subprocess.CalledProcessError(returncode=1, cmd=cmd)
        err.stdout = None  # exercise the str()/empty branch
        err.stderr = "already-text"
        raise err

    with pytest.raises(subprocess.CalledProcessError):
        _run(["ffmpeg"], runner=failing_runner)


# ---------------------------------------------------------------------------
# probe_media
# ---------------------------------------------------------------------------
def test_probe_media_missing_file_raises(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    with pytest.raises(FileNotFoundError):
        probe_media(tmp_path / "nope.mp4")


# ---------------------------------------------------------------------------
# reframe strategies
# ---------------------------------------------------------------------------
def test_reframe_blur_bg_strategy(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video = tmp_path / "v.mp4"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")

    calls = []

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        calls.append(cmd)
        return _Completed()

    reframe(video, out, "9:16", strategy="blur_bg", runner=runner)
    vf = calls[0][calls[0].index("-vf") + 1]
    assert "boxblur" in vf and "overlay" in vf


def test_reframe_pad_strategy(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video = tmp_path / "v.mp4"
    out = tmp_path / "o.mp4"
    video.write_bytes(b"fake")

    calls = []

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        calls.append(cmd)
        return _Completed()

    reframe(video, out, "9:16", strategy="pad", runner=runner)
    vf = calls[0][calls[0].index("-vf") + 1]
    assert "pad=" in vf


# ---------------------------------------------------------------------------
# merge_video_audio variants
# ---------------------------------------------------------------------------
def _probe_runner_with_audio(calls, *, audio_codecs):
    import json

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        calls.append(cmd)
        if "ffprobe" in cmd[0]:
            streams = [{"codec_type": "video", "codec_name": "h264"}]
            for codec in audio_codecs:
                streams.append({"codec_type": "audio", "codec_name": codec})
            payload = {"format": {"duration": "5.0"}, "streams": streams}
            return _Completed(stdout=json.dumps(payload).encode())
        return _Completed()

    return runner


def test_merge_ducking_true_uses_default_factor(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")
    calls = []
    runner = _probe_runner_with_audio(calls, audio_codecs=["aac"])

    merge_video_audio(video, audio, out, ducking=True, runner=runner)
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    fc = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert "volume=0.25" in fc  # default duck factor for ducking=True


def test_merge_ducking_none_no_volume_filter(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")
    calls = []
    runner = _probe_runner_with_audio(calls, audio_codecs=["aac"])

    merge_video_audio(video, audio, out, ducking=None, runner=runner)
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    fc = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert "anull" in fc and "volume=" not in fc


def test_merge_probe_failure_assumes_audio(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")

    calls = []

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        calls.append(cmd)
        if "ffprobe" in cmd[0]:
            raise RuntimeError("probe failed")
        return _Completed()

    merge_video_audio(video, audio, out, runner=runner)
    # Despite probe failure, it assumes audio exists -> filter_complex with amix.
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    assert "-filter_complex" in ffmpeg_cmd


def test_merge_no_video_audio_with_normalize(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")
    calls = []
    runner = _probe_runner_with_audio(calls, audio_codecs=[])  # no audio stream

    merge_video_audio(video, audio, out, normalize=True, runner=runner)
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    fc = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert fc == "[1:a]loudnorm[aout]"


def test_merge_no_video_audio_without_normalize(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")
    calls = []
    runner = _probe_runner_with_audio(calls, audio_codecs=[])

    merge_video_audio(video, audio, out, normalize=False, runner=runner)
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    # No filter_complex; falls back to direct stream mapping.
    assert "-filter_complex" not in ffmpeg_cmd
    assert "1:a:0" in ffmpeg_cmd


def test_merge_with_audio_and_normalize_appends_loudnorm(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, audio, out = tmp_path / "v.mp4", tmp_path / "a.aac", tmp_path / "o.mp4"
    for p in (video, audio):
        p.write_bytes(b"fake")
    calls = []
    runner = _probe_runner_with_audio(calls, audio_codecs=["aac"])

    merge_video_audio(video, audio, out, normalize=True, runner=runner)
    ffmpeg_cmd = [c for c in calls if c[0].endswith("ffmpeg")][0]
    fc = ffmpeg_cmd[ffmpeg_cmd.index("-filter_complex") + 1]
    assert "loudnorm" in fc and "amix" in fc


# ---------------------------------------------------------------------------
# silence helpers
# ---------------------------------------------------------------------------
def test_burn_subtitles_appends_extra_filters(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    video, subs, out = tmp_path / "v.mp4", tmp_path / "s.srt", tmp_path / "o.mp4"
    video.write_bytes(b"fake")
    subs.write_text("x")
    calls = []

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        calls.append(cmd)
        return _Completed()

    ffmpeg.burn_subtitles(video, subs, out, extra_filters=["eq=contrast=1.2"], runner=runner)
    vf = calls[0][calls[0].index("-vf") + 1]
    assert "subtitles=" in vf and "eq=contrast=1.2" in vf


def test_parse_silence_log_ignores_unrelated_lines():
    # A line that is neither silence_start nor silence_end takes the 233->227
    # (condition False) loop-back branch.
    log = (
        "Some unrelated ffmpeg banner line\n"
        "silence_start: 0.0\n"
        "frame= 100 fps=25\n"  # unrelated -> no end_value, loops back
        "silence_end: 1.0 | silence_duration: 1.0\n"
    )
    intervals, current_start = _parse_silence_log(log)
    assert intervals == [(0.0, 1.0)]
    assert current_start is None


def test_match_value_no_match_returns_none():
    assert _match_value("nothing here", _SILENCE_END_RE) is None


def test_match_value_unparseable_returns_none(monkeypatch):
    import re

    # A pattern whose 'value' group captures a non-float string.
    pattern = re.compile(r"silence_end:\s*(?P<value>\w+)")
    assert _match_value("silence_end: abc", pattern) is None


def test_parse_silence_log_ignores_end_with_negative_span():
    # silence_end < silence_start -> interval dropped, current_start reset.
    log = "silence_start: 5.0\nsilence_end: 1.0\n"
    intervals, current_start = _parse_silence_log(log)
    assert intervals == []
    assert current_start is None


def test_parse_silence_log_returns_unclosed_start():
    log = "silence_start: 3.0\n"
    intervals, current_start = _parse_silence_log(log)
    assert intervals == []
    assert current_start == 3.0


def test_detect_silence_missing_file_raises(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    with pytest.raises(FileNotFoundError):
        detect_silence(tmp_path / "missing.wav")


def test_detect_silence_unclosed_with_probe_failure(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"fake")

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        return _Completed(stderr=b"silence_start: 2.0\n")

    # probe_media raises -> duration becomes None -> open interval is not closed.
    monkeypatch.setattr(
        "media_core.video_edit.ffmpeg.probe_media",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    intervals = detect_silence(media, runner=runner)
    assert intervals == []


def test_detect_silence_unclosed_with_short_duration(monkeypatch, tmp_path):
    _which_ok(monkeypatch)
    media = tmp_path / "clip.wav"
    media.write_bytes(b"fake")

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        return _Completed(stderr=b"silence_start: 5.0\n")

    # Probed duration < current_start -> interval is NOT appended.
    monkeypatch.setattr(
        "media_core.video_edit.ffmpeg.probe_media",
        lambda *_a, **_k: {"duration": 1.0},
    )
    intervals = detect_silence(media, runner=runner)
    assert intervals == []


def test_ffmpeg_module_exports():
    assert hasattr(ffmpeg, "merge_video_audio")
