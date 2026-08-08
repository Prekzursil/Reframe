"""Encoder-capability regression: the bundled ffmpeg must be able to encode H.264.

WHY THIS FILE EXISTS (the shipped defect it pins). Nine sidecar modules and the
renderer's export default pass ``libx264`` as a LITERAL argv element, but the
packaged ffmpeg was BtbN's win64-**LGPL** build, configured
``--disable-libx264 --disable-libx265``. Every export in the shipped product died
with ``Unknown encoder 'libx264'`` and produced no output file. The whole gate
stack was green throughout, because CI installs ffmpeg from apt/choco (a GPL build
that HAS libx264) while the packaged binary is a different artifact entirely.

So a test that merely runs ``ffmpeg`` off PATH would have stayed green through the
entire defect and proves nothing. The three layers below each close a different
half of that blindness:

  1. :func:`test_pin_names_a_gpl_asset` — a HERMETIC read of the build script's
     own ffmpeg pin. Fails the moment the pin names an ``-lgpl-`` asset again.
     This is the only layer the Linux CI gate can enforce, and it is the layer
     that would have caught the original regression at review time.
  2. The fixture-driven parser/verdict tests — replayed against the REAL captured
     ``ffmpeg -encoders`` output of BOTH builds (``tests/fixtures/``). The LGPL
     fixture is the KNOWN-BROKEN state: the detector MUST fire on it. A probe that
     is silent in both states measures nothing.
  3. :func:`test_bundled_binary_advertises_the_encoder_we_ask_for` — marked
     ``e2e`` and pointed at the STAGED/BUNDLED binary specifically (never PATH).
     Skips where that binary is not staged.

RESIDUAL, stated inline: layer 3 only executes on a host that has actually staged
``build/ffmpeg/win`` (i.e. the Windows packaging machine); the Linux CI gate skips
it, so the bundled binary's real capability is NOT proven by CI. Layers 1 and 2 are
what CI enforces. The settling experiment for closing that gap fully is a packaged
smoke job that runs the built installer's own ``resources/bin/ffmpeg.exe`` — that
is a CI-topology change and out of this fix's scope.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from media_studio import ffmpeg
from media_studio.features import self_test

# tests/ -> sidecar/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Real captured `ffmpeg -hide_banner -encoders` stdout from the two BtbN builds
#: of the SAME upstream commit (n7.1.5-1-g7d0e842004). Only the licence build
#: differs, which is exactly what makes them a clean both-states pair.
_LGPL_DUMP = _FIXTURES / "ffmpeg-encoders-btbn-win64-lgpl.txt"
_GPL_DUMP = _FIXTURES / "ffmpeg-encoders-btbn-win64-gpl.txt"

_SETUP_SCRIPT = _REPO_ROOT / "build" / "python-embed-setup.ps1"
_STAGED_FFMPEG = _REPO_ROOT / "build" / "ffmpeg" / "win" / "ffmpeg.exe"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# layer 1 — the pin itself (hermetic; the only layer Linux CI can enforce)
# --------------------------------------------------------------------------- #
def test_pin_names_a_gpl_asset() -> None:
    """The staged ffmpeg pin must name BtbN's GPL asset, not the LGPL one.

    BtbN publishes ``…-win64-lgpl-…zip`` and ``…-win64-gpl-…zip`` side by side and
    the names differ by ONE letter, so this is a genuinely easy regression to
    reintroduce. The LGPL asset cannot encode H.264 (``--disable-libx264``), which
    is the whole defect, so the pin is the load-bearing line.
    """
    url_line = next(ln for ln in _read(_SETUP_SCRIPT).splitlines() if "$FfmpegUrl" in ln and "http" in ln)
    assert "-win64-gpl-" in url_line, f"ffmpeg pin must be the GPL asset, got: {url_line.strip()}"
    assert "-win64-lgpl-" not in url_line, (
        "ffmpeg pin points at BtbN's LGPL build, which is --disable-libx264 and "
        f"CANNOT encode the H.264 this codebase hardcodes: {url_line.strip()}"
    )


def test_pin_carries_a_sha256() -> None:
    """The pin stays fail-closed: a 64-hex digest, never an empty/placeholder pin."""
    digest_line = next(ln for ln in _read(_SETUP_SCRIPT).splitlines() if "$ExpectedFfmpegSha256" in ln and "=" in ln)
    assert re.search(r"'[0-9a-f]{64}'", digest_line), f"ffmpeg sha256 pin must be 64 hex chars: {digest_line.strip()}"


# --------------------------------------------------------------------------- #
# layer 2a — the pure parser, replayed against BOTH real dumps
# --------------------------------------------------------------------------- #
def test_parse_encoders_reads_the_real_gpl_dump() -> None:
    """The GPL build advertises the encoder the argv builders hardcode."""
    encoders = ffmpeg.parse_encoders(_read(_GPL_DUMP))
    assert ffmpeg.H264_ENCODER in encoders
    # Sanity that we parsed a whole table, not one lucky line.
    assert len(encoders) > 200
    assert "aac" in encoders and "libx265" in encoders


def test_parse_encoders_on_the_known_broken_lgpl_dump() -> None:
    """THE BOTH-STATES CASE: the LGPL build parses fine and simply lacks libx264.

    This is the state that shipped. The parser must NOT report an empty/garbage
    read here — that would make the detector's silence meaningless. It parses a
    full, healthy table that genuinely does not contain the encoder we ask for.
    """
    encoders = ffmpeg.parse_encoders(_read(_LGPL_DUMP))
    assert len(encoders) > 200, "the LGPL dump must parse as a healthy table"
    assert ffmpeg.H264_ENCODER not in encoders
    # It can still DECODE h264 and encode via OpenH264/hardware — which is exactly
    # why the failure was invisible until an export was actually attempted.
    assert "libopenh264" in encoders


def test_parse_encoders_ignores_the_legend_header() -> None:
    """Rows before the ``------`` separator are legend lines, not encoders."""
    encoders = ffmpeg.parse_encoders(_read(_GPL_DUMP))
    assert "=" not in encoders
    assert "Video" not in encoders


@pytest.mark.parametrize(
    "text",
    [
        "",  # nothing at all
        "Encoders:\n V..... = Video\n",  # header only, no separator -> no rows
        " ------\n",  # separator with no rows
        " ------\nlonelytoken\n",  # a row with too few columns
        " ------\n VD libx264 short flags\n",  # flag column the wrong width
    ],
)
def test_parse_encoders_fails_closed(text: str) -> None:
    """Anything unparseable yields an EMPTY set, never a false positive.

    Fail-closed matters: the verdict below treats "encoder absent" as a problem,
    so a parser that guessed on garbage would invent capability the binary may
    not have.
    """
    assert ffmpeg.parse_encoders(text) == frozenset()


# --------------------------------------------------------------------------- #
# layer 2b — the subprocess seam (injected runner; no real ffmpeg spawned)
# --------------------------------------------------------------------------- #
class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_probe_encoders_uses_an_argv_list_and_the_given_binary() -> None:
    seen: dict[str, object] = {}

    def runner(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return _FakeCompleted(0, _read(_GPL_DUMP))

    got = ffmpeg.probe_encoders("/opt/ff/ffmpeg", runner=runner)
    assert ffmpeg.H264_ENCODER in got
    assert seen["argv"] == ["/opt/ff/ffmpeg", "-hide_banner", "-encoders"]
    # bounded, non-shell, captured — same discipline as every other probe here
    assert seen["kwargs"]["timeout"] == ffmpeg.PROBE_TIMEOUT_SEC
    assert seen["kwargs"]["check"] is False


def test_probe_encoders_fails_closed_on_a_nonzero_exit() -> None:
    got = ffmpeg.probe_encoders("/opt/ff/ffmpeg", runner=lambda *_a, **_k: _FakeCompleted(1, _read(_GPL_DUMP)))
    assert got == frozenset()


def test_probe_encoders_fails_closed_on_empty_stdout() -> None:
    got = ffmpeg.probe_encoders("/opt/ff/ffmpeg", runner=lambda *_a, **_k: _FakeCompleted(0, ""))
    assert got == frozenset()


# --------------------------------------------------------------------------- #
# layer 2c — the self-test verdict the SETUP panel renders
# --------------------------------------------------------------------------- #
def test_encoder_check_passes_on_the_gpl_build() -> None:
    result = self_test.encoder_check(encoders=ffmpeg.parse_encoders(_read(_GPL_DUMP)))
    assert result.ok is True
    assert result.required is True
    assert result.id == "encoder"
    assert ffmpeg.H264_ENCODER in result.detail
    assert result.fix_hint == ""


def test_encoder_check_FAILS_on_the_lgpl_build_that_shipped() -> None:
    """The regression assertion: the exact binary that shipped must be rejected."""
    result = self_test.encoder_check(encoders=ffmpeg.parse_encoders(_read(_LGPL_DUMP)))
    assert result.ok is False
    assert result.required is True, "a build that cannot encode H.264 must BLOCK, not warn"
    assert ffmpeg.H264_ENCODER in result.detail
    assert result.fix_hint == self_test.ENCODER_FIX


def test_encoder_check_reports_a_probe_error() -> None:
    result = self_test.encoder_check(encoders=frozenset(), error="ffmpeg was not found")
    assert result.ok is False
    assert "ffmpeg was not found" in result.detail


def test_encoder_check_names_the_h264_alternatives_it_did_find() -> None:
    """The fix hint is only actionable if it says what the binary CAN do."""
    result = self_test.encoder_check(encoders=ffmpeg.parse_encoders(_read(_LGPL_DUMP)))
    assert "libopenh264" in result.detail


# --------------------------------------------------------------------------- #
# layer 2d — the probe seam inside self_test (fail-open, never raises)
# --------------------------------------------------------------------------- #
def test_probe_encoder_set_without_an_ffmpeg_path() -> None:
    encoders, error = self_test.probe_encoder_set(None)
    assert encoders == frozenset()
    assert error


def test_probe_encoder_set_degrades_when_the_probe_raises() -> None:
    def boom(_path: str) -> frozenset[str]:
        raise OSError("binary is not executable")

    encoders, error = self_test.probe_encoder_set("/opt/ff/ffmpeg", probe=boom)
    assert encoders == frozenset()
    assert "not executable" in error


def test_probe_encoder_set_returns_the_probed_set() -> None:
    encoders, error = self_test.probe_encoder_set(
        "/opt/ff/ffmpeg", probe=lambda _p: ffmpeg.parse_encoders(_read(_GPL_DUMP))
    )
    assert ffmpeg.H264_ENCODER in encoders
    assert error == ""


# --------------------------------------------------------------------------- #
# layer 2e — end-to-end through self_test.run(), the RPC the panel calls
# --------------------------------------------------------------------------- #
class _Hw:
    def detect(self):  # noqa: D102 - trivial stub
        return type("F", (), {"vram_mb": 1, "ram_mb": 2, "cpu_count": 3, "gpu_present": True})()


def _run_report(tmp_path: Path, dump: Path):
    return self_test.run(
        data_dir=tmp_path,
        hardware_probe=_Hw(),
        resolve_tool=lambda name: f"/opt/ff/{name}",
        find_spec=lambda _m: object(),
        probe_encoders=lambda _p: ffmpeg.parse_encoders(_read(dump)),
    )


def test_self_test_run_reports_the_encoder_check(tmp_path: Path) -> None:
    report = _run_report(tmp_path, _GPL_DUMP)
    encoder = next(c for c in report.checks if c.id == "encoder")
    assert encoder.ok is True
    assert report.ok is True


def test_self_test_run_BLOCKS_on_the_lgpl_build(tmp_path: Path) -> None:
    """A binary that cannot encode H.264 must flip the overall verdict to NOT ok.

    Before this fix the same install reported a fully GREEN self-test — ffmpeg
    resolved, so the panel said "Media tools (FFmpeg): ok" — while every export
    failed. That green report is the thing being deleted here.
    """
    report = _run_report(tmp_path, _LGPL_DUMP)
    encoder = next(c for c in report.checks if c.id == "encoder")
    assert encoder.ok is False
    assert report.ok is False, "the blocking verdict must reflect an unusable encoder"
    assert any(ffmpeg.H264_ENCODER in p for p in report.problems)
    # ...and the presence check STILL passes, which is precisely why presence
    # alone was never sufficient.
    assert next(c for c in report.checks if c.id == "ffmpeg").ok is True


# --------------------------------------------------------------------------- #
# layer 3 — the REAL staged binary (opt-in; skipped where it is not staged)
# --------------------------------------------------------------------------- #
@pytest.mark.e2e
@pytest.mark.skipif(
    not _STAGED_FFMPEG.is_file(),
    reason=f"bundled ffmpeg not staged at {_STAGED_FFMPEG} (run build/python-embed-setup.ps1 -WithFfmpeg)",
)
def test_bundled_binary_advertises_the_encoder_we_ask_for() -> None:
    """The packaging gate: the BUNDLED binary — not PATH's — must have libx264.

    Deliberately does NOT use ``shutil.which``: resolving ffmpeg off PATH is the
    exact measurement error that let this ship, because the dev/CI PATH ffmpeg is
    a GPL build while the packaged one was not.
    """
    encoders = ffmpeg.probe_encoders(str(_STAGED_FFMPEG))
    assert ffmpeg.H264_ENCODER in encoders, (
        f"{_STAGED_FFMPEG} does not advertise {ffmpeg.H264_ENCODER}; "
        "the ffmpeg pin is probably back on BtbN's LGPL asset"
    )


@pytest.mark.e2e
@pytest.mark.skipif(not _STAGED_FFMPEG.is_file(), reason="bundled ffmpeg not staged")
def test_bundled_binary_actually_encodes_h264() -> None:
    """Advertising an encoder is a claim; producing an H.264 file is the receipt."""
    ffprobe = _STAGED_FFMPEG.with_name("ffprobe.exe")
    if not ffprobe.is_file():  # pragma: no cover - staged pair is always complete
        pytest.skip("bundled ffprobe not staged beside ffmpeg")
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "probe.mp4"
        enc = subprocess.run(
            [
                str(_STAGED_FFMPEG),
                "-hide_banner",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=15:duration=1",
                "-c:v",
                ffmpeg.H264_ENCODER,
                "-pix_fmt",
                "yuv420p",
                str(clip),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert enc.returncode == 0, f"encode failed: {enc.stderr[-2000:]}"
        assert clip.is_file() and clip.stat().st_size > 0
        probed = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
                str(clip),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        assert probed.stdout.strip() == "h264", probed.stdout
