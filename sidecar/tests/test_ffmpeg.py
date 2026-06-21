"""Unit tests for media_studio.ffmpeg.

Subprocess and binary resolution are mocked/injected: no real ffmpeg/ffprobe is
spawned and no binary needs to exist on the box.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from media_studio import ffmpeg
from media_studio.ffmpeg import FfmpegNotFound


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def _make_exe(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n", encoding="utf-8")
    return p


def test_resolve_from_settings_pointing_at_binary(tmp_path: Path):
    exe = _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    got = ffmpeg.resolve_binary("ffmpeg", {"ffmpegPath": str(exe)})
    assert Path(got) == exe


def test_resolve_from_settings_pointing_at_dir(tmp_path: Path):
    _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    got = ffmpeg.resolve_binary("ffmpeg", {"ffmpegPath": str(tmp_path)})
    assert Path(got).name == f"ffmpeg{ffmpeg._EXE}"


def test_resolve_ffprobe_sibling_when_setting_names_ffmpeg(tmp_path: Path):
    # ffmpegPath names the ffmpeg binary; ffprobe must be found beside it
    _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    probe = _make_exe(tmp_path / f"ffprobe{ffmpeg._EXE}")
    got = ffmpeg.resolve_binary("ffprobe", {"ffmpegPath": str(tmp_path / f"ffmpeg{ffmpeg._EXE}")})
    assert Path(got) == probe


def test_resolve_from_env(monkeypatch, tmp_path: Path):
    exe = _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    monkeypatch.setenv("MEDIA_STUDIO_FFMPEG", str(exe))
    got = ffmpeg.resolve_binary("ffmpeg", {})
    assert Path(got) == exe


def test_resolve_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("MEDIA_STUDIO_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")
    # make sure bundled dir does not accidentally exist
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    got = ffmpeg.resolve_binary("ffmpeg", {})
    assert got == "/usr/bin/ffmpeg"


def test_resolve_raises_when_nothing_found(monkeypatch):
    monkeypatch.delenv("MEDIA_STUDIO_FFMPEG", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    monkeypatch.setattr(ffmpeg, "_BUNDLED_DIR", Path("/nonexistent/bin"))
    with pytest.raises(FfmpegNotFound):
        ffmpeg.resolve_binary("ffmpeg", {})


def test_settings_precedes_env(monkeypatch, tmp_path: Path):
    setting_exe = _make_exe(tmp_path / "s" / f"ffmpeg{ffmpeg._EXE}")
    env_exe = _make_exe(tmp_path / "e" / f"ffmpeg{ffmpeg._EXE}")
    monkeypatch.setenv("MEDIA_STUDIO_FFMPEG", str(env_exe))
    got = ffmpeg.resolve_binary("ffmpeg", {"ffmpegPath": str(setting_exe)})
    assert Path(got) == setting_exe


def test_ffmpeg_path_and_ffprobe_path_helpers(monkeypatch, tmp_path: Path):
    _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    _make_exe(tmp_path / f"ffprobe{ffmpeg._EXE}")
    s = {"ffmpegPath": str(tmp_path)}
    assert Path(ffmpeg.ffmpeg_path(s)).name == f"ffmpeg{ffmpeg._EXE}"
    assert Path(ffmpeg.ffprobe_path(s)).name == f"ffprobe{ffmpeg._EXE}"


# --------------------------------------------------------------------------- #
# argv builders
# --------------------------------------------------------------------------- #
@pytest.fixture
def bins(tmp_path: Path):
    _make_exe(tmp_path / f"ffmpeg{ffmpeg._EXE}")
    _make_exe(tmp_path / f"ffprobe{ffmpeg._EXE}")
    return {"ffmpegPath": str(tmp_path)}


def test_build_probe_argv(bins):
    argv = ffmpeg.build_probe_argv("/in put/v.mp4", bins)
    assert isinstance(argv, list)
    assert Path(argv[0]).name == f"ffprobe{ffmpeg._EXE}"
    assert argv[-1] == "/in put/v.mp4"  # spaces preserved as a single argv element
    assert "format=duration" in argv


def test_build_convert_argv_basic_video(bins):
    argv = ffmpeg.build_convert_argv(
        "/a b/in.mov",
        "/a b/out.mp4",
        {"vcodec": "libx264", "acodec": "aac", "crf": 23, "scale": "1280x720", "fps": 30},
        bins,
    )
    assert Path(argv[0]).name == f"ffmpeg{ffmpeg._EXE}"
    assert "-i" in argv and argv[argv.index("-i") + 1] == "/a b/in.mov"
    assert argv[-1] == "/a b/out.mp4"
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "libx264"
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "aac"
    assert "-crf" in argv and argv[argv.index("-crf") + 1] == "23"
    # scale "1280x720" normalized to ffmpeg "scale=1280:720"
    assert "-vf" in argv and argv[argv.index("-vf") + 1] == "scale=1280:720"
    assert "-r" in argv and argv[argv.index("-r") + 1] == "30"
    # progress wiring present
    assert "-progress" in argv and argv[argv.index("-progress") + 1] == "pipe:1"
    assert "-y" in argv


def test_build_convert_argv_audio_only(bins):
    argv = ffmpeg.build_convert_argv(
        "/in.mp4",
        "/out.mp3",
        {"audioOnly": True, "acodec": "libmp3lame"},
        bins,
    )
    assert "-vn" in argv
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "libmp3lame"
    assert "-c:v" not in argv  # no video codec when audio-only


def test_build_convert_argv_omits_absent_options(bins):
    argv = ffmpeg.build_convert_argv("/in.mp4", "/out.mp4", {}, bins)
    assert "-crf" not in argv
    assert "-vf" not in argv
    assert "-r" not in argv
    assert argv[-1] == "/out.mp4"


# --------------------------------------------------------------------------- #
# progress parsing
# --------------------------------------------------------------------------- #
def test_parse_progress_line():
    assert ffmpeg.parse_progress_line("frame=10") == ("frame", "10")
    assert ffmpeg.parse_progress_line("  out_time=00:00:01.000  ") == ("out_time", "00:00:01.000")
    assert ffmpeg.parse_progress_line("") is None
    assert ffmpeg.parse_progress_line("garbage") is None


def test_out_time_to_seconds():
    assert ffmpeg._out_time_to_seconds("00:01:30.500") == pytest.approx(90.5)
    assert ffmpeg._out_time_to_seconds("12.0") == pytest.approx(12.0)
    assert ffmpeg._out_time_to_seconds("N/A") is None
    assert ffmpeg._out_time_to_seconds("") is None
    assert ffmpeg._out_time_to_seconds("xx:yy:zz") is None


def test_pct_from_progress_out_time_us():
    # out_time_ms is actually microseconds in ffmpeg
    pct = ffmpeg._pct_from_progress("out_time_ms", str(5_000_000), 10.0)
    assert pct == pytest.approx(50.0)


def test_pct_from_progress_out_time_string():
    pct = ffmpeg._pct_from_progress("out_time", "00:00:02.500", 10.0)
    assert pct == pytest.approx(25.0)


def test_pct_from_progress_clamped_and_guarded():
    assert ffmpeg._pct_from_progress("out_time_ms", str(99_000_000), 10.0) == 100.0
    assert ffmpeg._pct_from_progress("out_time_ms", "5", 0.0) is None  # no total
    assert ffmpeg._pct_from_progress("frame", "10", 10.0) is None  # irrelevant key
    assert ffmpeg._pct_from_progress("out_time_ms", "bad", 10.0) is None


# --------------------------------------------------------------------------- #
# run() with a fake Popen
# --------------------------------------------------------------------------- #
class _FakeProc:
    def __init__(self, lines, code=0):
        self.stdout = iter(lines)
        self.stderr = iter([])
        self._code = code
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self._code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _fake_popen_factory(lines, code=0):
    captured = {}

    def factory(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _FakeProc(lines, code)

    factory.captured = captured
    return factory


def test_run_rejects_shell_string():
    with pytest.raises(TypeError):
        ffmpeg.run("ffmpeg -i in.mp4 out.mp4")


def test_run_streams_progress_and_completes():
    lines = [
        "frame=1\n",
        "out_time_ms=2500000\n",  # 2.5s of 10 -> 25%
        "out_time_ms=5000000\n",  # 5.0s -> 50%
        "progress=end\n",
    ]
    events = []
    popen = _fake_popen_factory(lines, code=0)
    code = ffmpeg.run(
        ["ffmpeg", "-i", "in.mp4", "out.mp4"],
        total_sec=10.0,
        on_progress=lambda pct, msg: events.append((round(pct, 1), msg)),
        popen=popen,
    )
    assert code == 0
    # monotonic progress then a final 100/done
    pcts = [e[0] for e in events]
    assert 25.0 in pcts and 50.0 in pcts
    assert events[-1] == (100.0, "done")
    # argv passed through as a list (no shell=True)
    assert popen.captured["argv"] == ["ffmpeg", "-i", "in.mp4", "out.mp4"]
    assert popen.captured["kwargs"].get("shell") in (None, False)


def test_run_skips_non_increasing_progress():
    lines = ["out_time_ms=5000000\n", "out_time_ms=2500000\n", "progress=end\n"]
    pcts = []
    popen = _fake_popen_factory(lines)
    ffmpeg.run(["ffmpeg"], total_sec=10.0, on_progress=lambda p, m: pcts.append(p), popen=popen)
    # 50% then a smaller 25% which must be suppressed; final 100 still fires
    assert pcts == [50.0, 100.0]


def test_run_without_total_sec_emits_only_done():
    lines = ["out_time_ms=5000000\n", "progress=end\n"]
    pcts = []
    popen = _fake_popen_factory(lines)
    ffmpeg.run(["ffmpeg"], total_sec=0.0, on_progress=lambda p, m: pcts.append(p), popen=popen)
    assert pcts == [100.0]  # no total -> no mid progress, but end still reports


def test_run_cooperative_cancel_terminates():
    lines = ["out_time_ms=1000000\n", "out_time_ms=2000000\n", "progress=end\n"]
    popen = _fake_popen_factory(lines, code=0)

    proc_holder = {}
    orig_factory = popen

    def wrap(argv, **kwargs):
        proc = orig_factory(argv, **kwargs)
        proc_holder["proc"] = proc
        return proc

    code = ffmpeg.run(
        ["ffmpeg"],
        total_sec=10.0,
        should_cancel=lambda: True,
        popen=wrap,
    )
    assert proc_holder["proc"].terminated is True
    assert code == 0


def test_run_propagates_nonzero_exit():
    popen = _fake_popen_factory(["progress=end\n"], code=1)
    code = ffmpeg.run(["ffmpeg"], total_sec=5.0, popen=popen)
    assert code == 1


# --------------------------------------------------------------------------- #
# ffprobe_duration
# --------------------------------------------------------------------------- #
def test_ffprobe_duration_parses_stdout(bins):
    class R:
        stdout = "42.123\n"

    got = ffmpeg.ffprobe_duration("/v.mp4", bins, runner=lambda *a, **k: R())
    assert got == pytest.approx(42.123)


def test_ffprobe_duration_handles_garbage(bins):
    class R:
        stdout = "N/A\n"

    assert ffmpeg.ffprobe_duration("/v.mp4", bins, runner=lambda *a, **k: R()) == 0.0


def test_ffprobe_duration_handles_empty(bins):
    class R:
        stdout = ""

    assert ffmpeg.ffprobe_duration("/v.mp4", bins, runner=lambda *a, **k: R()) == 0.0
