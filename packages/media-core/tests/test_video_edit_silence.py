from media_core.video_edit.ffmpeg import detect_silence


class DummyCompleted:
    def __init__(self, stderr: bytes = b""):
        self.returncode = 0
        self.stdout = b""
        self.stderr = stderr


def test_detect_silence_parses_intervals(monkeypatch, tmp_path):
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)

    stderr = (
        b"[silencedetect @ 0x1] silence_start: 0\n"
        b"[silencedetect @ 0x1] silence_end: 1.23 | silence_duration: 1.23\n"
        b"[silencedetect @ 0x1] silence_start: 4.56\n"
        b"[silencedetect @ 0x1] silence_end: 5.00 | silence_duration: 0.44\n"
    )

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        return DummyCompleted(stderr=stderr)

    intervals = detect_silence(media, runner=runner)
    assert intervals == [(0.0, 1.23), (4.56, 5.0)]


def test_detect_silence_closes_open_interval(monkeypatch, tmp_path):
    media = tmp_path / "sample.mp4"
    media.write_bytes(b"fake")

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr("media_core.video_edit.ffmpeg.probe_media", lambda *_args, **_kwargs: {"duration": 10.0})

    stderr = b"[silencedetect @ 0x1] silence_start: 2.0\n"

    def runner(cmd, check=True, capture_output=True):  # noqa: ARG001
        return DummyCompleted(stderr=stderr)

    intervals = detect_silence(media, runner=runner)
    assert intervals == [(2.0, 10.0)]
