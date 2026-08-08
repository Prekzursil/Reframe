"""Tests for the encoder-capability gate (``media_studio.encoders``).

WHY THIS SUITE EXISTS
---------------------
Reframe shipped a build whose bundled ffmpeg (BtbN win64-**LGPL**, configured
``--disable-libx264 --disable-libx265``) CANNOT encode H.264, while nine sidecar
modules pass the literal string ``libx264`` to ``-c:v``. Every export therefore
died with ``Unknown encoder 'libx264'`` on the shipped product -- and every gate
was green, because CI installs ffmpeg from apt/choco (a GPL build that HAS
libx264). The gate measured a binary the user never runs.

The tests below pin the missing check: given the ffmpeg that will actually be
invoked, does it list every encoder the pipeline hardcodes? The two fixture
blobs are REAL ``ffmpeg -encoders`` output captured from two real binaries on
the authoring machine (see the constants), so the parser is exercised against
the exact bytes it must handle, not an idealised mock.

Fully hermetic: every probe runs through an injected ``probe_runner`` (or a
monkeypatched ``subprocess.run``), so this suite never spawns ffmpeg and never
touches the network -- it stays green on a machine with no ffmpeg at all.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from media_studio import encoders

# --------------------------------------------------------------------------- #
# REAL captured `ffmpeg -encoders` output (trimmed to the load-bearing lines).
# --------------------------------------------------------------------------- #
# Captured from the SHIPPED binary: D:/Program Files/Reframe/resources/bin/ffmpeg.exe
# ffmpeg n7.1.5-1-g7d0e842004-20260703, configured --disable-libx264 --disable-libx265
# --enable-libopenh264. This is the state that shipped broken.
LGPL_ENCODERS = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 .F.... = Frame-level multithreading
 ..S... = Slice-level multithreading
 ...X.. = Codec is experimental
 ....B. = Supports draw_horiz_band
 .....D = Supports direct rendering method 1
 ------
 V....D a64multi             Multicolor charset for Commodore 64 (codec a64_multi)
 V....D libopenh264          OpenH264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder
 A....D aac                  AAC (Advanced Audio Coding)
 A....D aac_mf               AAC via MediaFoundation (codec aac)
 A....D pcm_s16le            PCM signed 16-bit little-endian
 S....D srt                  SubRip subtitle
"""

# Captured from a GPL build on PATH (WinGet ffmpeg) -- the state CI measures.
GPL_ENCODERS = """Encoders:
 V..... = Video
 A..... = Audio
 S..... = Subtitle
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libx264rgb           libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 RGB (codec h264)
 V....D libx265              libx265 H.265 / HEVC (codec hevc)
 A....D aac                  AAC (Advanced Audio Coding)
 A....D pcm_s16le            PCM signed 16-bit little-endian
"""


class _ProbeResult:
    """Minimal ``subprocess.CompletedProcess`` stand-in for the probe seam.

    Deliberately NOT ``test_boundary._FakeCompleted``: that one is a stderr-only
    stand-in (``__init__(self, stderr)``) for the silencedetect parser, and has
    no ``stdout``. The encoder listing arrives on stdout on most builds and on
    stderr on some, so this stub carries both plus a return code.
    """

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _runner(stdout: str = "", stderr: str = "", returncode: int = 0) -> Any:
    """A ``probe_runner`` that returns fixed output and records the argv it saw."""

    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: Any) -> _ProbeResult:
        calls.append(list(argv))
        return _ProbeResult(stdout, stderr, returncode)

    run.calls = calls  # type: ignore[attr-defined]
    return run


# --------------------------------------------------------------------------- #
# parse_encoders -- the pure parser
# --------------------------------------------------------------------------- #
def test_parse_encoders_reads_names_from_the_real_lgpl_listing():
    got = encoders.parse_encoders(LGPL_ENCODERS)
    assert "libopenh264" in got
    assert "aac" in got
    assert "libsvtav1" in got
    assert "srt" in got


def test_parse_encoders_does_not_invent_libx264_on_the_lgpl_build():
    """THE REGRESSION: the shipped binary must NOT report libx264."""
    assert "libx264" not in encoders.parse_encoders(LGPL_ENCODERS)


def test_parse_encoders_finds_libx264_on_a_gpl_build():
    got = encoders.parse_encoders(GPL_ENCODERS)
    assert "libx264" in got
    assert "libx265" in got


def test_parse_encoders_ignores_the_flag_legend_header():
    """` V..... = Video` must not be parsed as an encoder named `=`."""
    got = encoders.parse_encoders(LGPL_ENCODERS)
    assert "=" not in got
    assert "Video" not in got
    assert "Encoders:" not in got


def test_parse_encoders_on_empty_text_is_empty():
    assert encoders.parse_encoders("") == frozenset()


def test_parse_encoders_without_a_separator_yields_nothing():
    """Fail CLOSED: unrecognised output must not be read as `everything is fine`."""
    assert encoders.parse_encoders("total garbage\nno separator here\n") == frozenset()


def test_parse_encoders_skips_non_row_lines_after_the_separator():
    """A blank line or a wrapped description after `------` is not an encoder."""
    text = " ------\n\n   continued description text\n V....D real  Real encoder\n"
    assert encoders.parse_encoders(text) == frozenset({"real"})


# --------------------------------------------------------------------------- #
# build_encoders_probe_argv
# --------------------------------------------------------------------------- #
def test_build_probe_argv_targets_the_resolved_binary(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    argv = encoders.build_encoders_probe_argv({"ffmpegPath": str(exe)})
    assert argv[0] == str(exe)
    assert "-encoders" in argv


def encoders_exe_suffix() -> str:
    """`.exe` on Windows, empty elsewhere (mirrors ffmpeg._EXE)."""
    return ".exe" if sys.platform.startswith("win") else ""


# --------------------------------------------------------------------------- #
# available_encoders -- the injected probe
# --------------------------------------------------------------------------- #
def test_available_encoders_parses_the_probe_stdout(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    run = _runner(stdout=GPL_ENCODERS)
    got = encoders.available_encoders({"ffmpegPath": str(exe)}, probe_runner=run)
    assert "libx264" in got


def test_available_encoders_also_reads_stderr(tmp_path: Path):
    """Some builds print the listing on stderr; both streams are folded."""
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    run = _runner(stdout="", stderr=GPL_ENCODERS)
    assert "libx264" in encoders.available_encoders({"ffmpegPath": str(exe)}, probe_runner=run)


def test_available_encoders_is_empty_when_ffmpeg_cannot_be_resolved(monkeypatch: pytest.MonkeyPatch):
    """Fail CLOSED: no ffmpeg => no encoders => the gate reports missing."""
    monkeypatch.setattr(
        encoders,
        "build_encoders_probe_argv",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no ffmpeg")),
    )
    assert encoders.available_encoders({}, probe_runner=_runner()) == frozenset()


def test_available_encoders_is_empty_when_the_probe_raises(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")

    def boom(_argv: list[str], **_kwargs: Any) -> _ProbeResult:
        raise OSError("spawn failed")

    assert encoders.available_encoders({"ffmpegPath": str(exe)}, probe_runner=boom) == frozenset()


def test_available_encoders_defaults_to_subprocess_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The default runner is subprocess.run (exercises the `is None` arm)."""
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=GPL_ENCODERS))
    assert "libx264" in encoders.available_encoders({"ffmpegPath": str(exe)})


# --------------------------------------------------------------------------- #
# missing_encoders -- the verdict
# --------------------------------------------------------------------------- #
def test_missing_encoders_names_libx264_on_the_shipped_lgpl_build(tmp_path: Path):
    """THE SHIPPED DEFECT, reproduced as a unit assertion."""
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    missing = encoders.missing_encoders(
        settings={"ffmpegPath": str(exe)}, probe_runner=_runner(stdout=LGPL_ENCODERS)
    )
    # EXACTLY libx264: the shipped LGPL build really does provide aac and
    # pcm_s16le, so a broader "missing" set would mean the parser is wrong
    # rather than the binary being incapable.
    assert missing == ("libx264",)


def test_missing_encoders_is_empty_on_a_gpl_build(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    missing = encoders.missing_encoders(
        settings={"ffmpegPath": str(exe)}, probe_runner=_runner(stdout=GPL_ENCODERS)
    )
    assert missing == ()


def test_missing_encoders_honours_an_explicit_required_set(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    missing = encoders.missing_encoders(
        required=("libx264", "libvvenc"),
        settings={"ffmpegPath": str(exe)},
        probe_runner=_runner(stdout=GPL_ENCODERS),
    )
    assert missing == ("libvvenc",)


def test_missing_encoders_returns_sorted_output(tmp_path: Path):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    missing = encoders.missing_encoders(
        required=("zzz", "aaa"),
        settings={"ffmpegPath": str(exe)},
        probe_runner=_runner(stdout=GPL_ENCODERS),
    )
    assert missing == ("aaa", "zzz")


# --------------------------------------------------------------------------- #
# REQUIRED_ENCODERS <-> the real source tree (anti-drift)
# --------------------------------------------------------------------------- #
def test_required_encoders_declares_libx264_and_aac():
    assert "libx264" in encoders.REQUIRED_ENCODERS
    assert "aac" in encoders.REQUIRED_ENCODERS


def test_scan_source_encoders_finds_the_hardcoded_libx264_in_the_real_tree():
    """The scanner must SEE the nine modules that hardcode libx264."""
    found = encoders.scan_source_encoders(encoders.PACKAGE_ROOT)
    assert "libx264" in found
    # features/shortmaker.py is one of the known sites (the export stage).
    assert any("shortmaker" in site for site in found["libx264"])


def test_required_encoders_covers_every_encoder_hardcoded_in_the_tree():
    """ANTI-DRIFT: add a new `-c:v <enc>` anywhere and this fails until declared.

    Without this, a future module could hardcode an encoder the bundled ffmpeg
    lacks and the capability gate would never look for it -- the exact blind spot
    that let libx264 ship.
    """
    found = set(encoders.scan_source_encoders(encoders.PACKAGE_ROOT))
    undeclared = sorted(found - set(encoders.REQUIRED_ENCODERS))
    assert undeclared == [], f"hardcoded but not declared in REQUIRED_ENCODERS: {undeclared}"


def test_scan_source_encoders_reads_c_v_argv_literals(tmp_path: Path):
    (tmp_path / "m.py").write_text('argv = ["ffmpeg", "-c:v", "libtest", "out.mp4"]\n')
    found = encoders.scan_source_encoders(tmp_path)
    assert "libtest" in found


def test_scan_source_encoders_reads_c_a_argv_literals(tmp_path: Path):
    (tmp_path / "m.py").write_text('argv = ["ffmpeg", "-c:a", "atest", "out.mp4"]\n')
    assert "atest" in encoders.scan_source_encoders(tmp_path)


def test_scan_source_encoders_reads_vcodec_and_acodec_dict_values(tmp_path: Path):
    (tmp_path / "m.py").write_text('opts = {"vcodec": "vdict", "acodec": "adict"}\n')
    found = encoders.scan_source_encoders(tmp_path)
    assert "vdict" in found
    assert "adict" in found


def test_scan_source_encoders_ignores_copy_and_dynamic_values(tmp_path: Path):
    """`copy` is a stream-copy directive, not an encoder; non-literals are skipped."""
    (tmp_path / "m.py").write_text(
        'a = ["-c:v", "copy"]\nb = ["-c:a", chosen]\nc = {"vcodec": other}\n'
    )
    assert encoders.scan_source_encoders(tmp_path) == {}


def test_scan_source_encoders_skips_unparseable_files(tmp_path: Path):
    """A syntactically broken file must not crash the scan."""
    (tmp_path / "bad.py").write_text("def (((\n")
    (tmp_path / "ok.py").write_text('a = ["-c:v", "libok"]\n')
    assert "libok" in encoders.scan_source_encoders(tmp_path)


def test_scan_source_encoders_ignores_a_trailing_flag(tmp_path: Path):
    """`-c:v` as the LAST element has no value to read."""
    (tmp_path / "m.py").write_text('a = ["ffmpeg", "-c:v"]\n')
    assert encoders.scan_source_encoders(tmp_path) == {}


def test_scan_source_encoders_records_the_site(tmp_path: Path):
    (tmp_path / "m.py").write_text('a = ["-c:v", "libsite"]\n')
    sites = encoders.scan_source_encoders(tmp_path)["libsite"]
    assert any("m.py" in s for s in sites)


# --------------------------------------------------------------------------- #
# main() -- the CLI gate (ci-hygiene.md 1: terminal marker, fail-closed)
# --------------------------------------------------------------------------- #
def test_main_fails_and_names_the_missing_encoder_on_the_lgpl_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=LGPL_ENCODERS))
    rc = encoders.main(["--ffmpeg", str(exe)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED:encoder-capability" in out
    assert "libx264" in out


def test_main_succeeds_on_a_gpl_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=GPL_ENCODERS))
    rc = encoders.main(["--ffmpeg", str(exe)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SUCCESS:encoder-capability" in out


def test_main_reports_the_binary_it_probed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A gate that does not name the binary it measured is unfalsifiable."""
    exe = tmp_path / f"ffmpeg{encoders_exe_suffix()}"
    exe.write_text("stub")
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=GPL_ENCODERS))
    encoders.main(["--ffmpeg", str(exe)])
    assert str(exe) in capsys.readouterr().out


def test_main_with_no_args_probes_the_default_resolution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=GPL_ENCODERS))
    monkeypatch.setattr(encoders.ffmpeg, "resolve_binary", lambda *_a, **_k: "ffmpeg")
    assert encoders.main([]) == 0
    assert "SUCCESS:encoder-capability" in capsys.readouterr().out


def test_main_fails_closed_when_ffmpeg_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """No ffmpeg at all is a FAILED gate, never a silent pass."""

    def unresolvable(*_a: Any, **_k: Any) -> str:
        raise encoders.ffmpeg.FfmpegNotFound("nope")

    monkeypatch.setattr(encoders.ffmpeg, "resolve_binary", unresolvable)
    rc = encoders.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED:encoder-capability" in out


def test_main_defaults_argv_to_sys_argv(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """`argv=None` reads sys.argv[1:] (the `python -m` entry point)."""
    monkeypatch.setattr(sys, "argv", ["media_studio.encoders"])
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: _ProbeResult(stdout=GPL_ENCODERS))
    monkeypatch.setattr(encoders.ffmpeg, "resolve_binary", lambda *_a, **_k: "ffmpeg")
    assert encoders.main() == 0
    assert "SUCCESS:encoder-capability" in capsys.readouterr().out
