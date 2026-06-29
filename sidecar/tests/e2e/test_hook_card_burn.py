"""E2E real-libass burn proof for the OpusClip HOOK CARD (V1.1 WU SP2).

The default unit suite proves :func:`caption.build_ass` (``hook_card=True``)
emits the exact hook-card ASS — a ``BorderStyle=3`` opaque (white) box, bold
black ``PrimaryColour``, top-centre ``Alignment=8``, and a first-~5 s time-boxed
``Dialogue`` — PURELY. This module closes the burn gap: it runs that document
through the SHIPPED :class:`caption.CaptionEngine` burn path (real ffmpeg + real
libass via the ``subtitles`` filter) and asserts the output is a valid,
non-zero-FRAME video — i.e. libass actually parsed the opaque-box card tags and
rasterised them onto the clip.

OPT-IN: tagged ``e2e`` so the default 100%-coverage gate (addopts
``-m 'not e2e'``) DESELECTS this module; it also skips when ffmpeg/ffprobe are
absent or ffmpeg was built without the libass ``subtitles`` filter. Run it with::

    python -m pytest -m e2e sidecar/tests/e2e/test_hook_card_burn.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features.caption import CaptionEngine, build_ass

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _ffmpeg_has_libass() -> bool:
    """True when this ffmpeg exposes the libass-backed ``subtitles`` filter."""
    if not _FFMPEG:
        return False
    res = subprocess.run(
        [_FFMPEG, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    return res.returncode == 0 and "subtitles" in res.stdout


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (_FFMPEG and _FFPROBE and _ffmpeg_has_libass()),
        reason="ffmpeg/ffprobe with the libass 'subtitles' filter required for the hook-card burn",
    ),
]

# A small canvas keeps the burn fast; the tags are resolution-independent.
_W, _H = 360, 640
_DUR = 6.0

_CUES = [{"index": 1, "start": 0.0, "end": _DUR, "text": "the body caption"}]


def _make_clip(path: Path) -> None:
    """Render a tiny real H.264 test clip (colour + tone) with ffmpeg."""
    res = subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={_W}x{_H}:rate=24:duration={_DUR}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0 and path.exists() and path.stat().st_size > 0, res.stderr


def _frame_count(path: Path) -> int:
    """Decode-count the output's video frames via ffprobe (proves rasterisation)."""
    res = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = res.stdout.strip().split("\n")[0].strip().rstrip(",")
    return int(raw) if raw.isdigit() else 0


def test_hook_card_burns_through_real_libass_to_nonzero_frames(tmp_path: Path) -> None:
    """The hook-card ASS must burn through real ffmpeg/libass into a valid clip.

    Machine-verifies the opaque-box card (BorderStyle 3 + white OutlineColour +
    black PrimaryColour + top Alignment 8 + the first-~5 s time-box) is valid
    libass that rasterises to a non-zero-frame video.
    """
    ass = build_ass(
        _CUES,
        width=_W,
        height=_H,
        hook_title="You wont believe what happens next",
        total_sec=_DUR,
        hook_card=True,
        hook_card_sec=5.0,
    )
    # Sanity: the document carries the load-bearing card tags + the 5 s time-box.
    style = next(line for line in ass.splitlines() if line.startswith("Style: HookCard,"))
    fields = style.split(",")
    assert fields[15] == "3"  # BorderStyle 3 (opaque box)
    assert fields[18] == "8"  # top-centre alignment
    card_event = next(line for line in ass.splitlines() if line.startswith("Dialogue:") and "HookCard" in line)
    assert "0:00:05.00" in card_event  # first-~5 s time-box

    clip = tmp_path / "src.mp4"
    out = tmp_path / "hookcard.mp4"
    _make_clip(clip)

    returned = CaptionEngine().render(
        str(clip),
        _CUES,
        str(out),
        burn=True,
        width=_W,
        height=_H,
        total_sec=_DUR,
        hook_title="You wont believe what happens next",
        hook_card=True,
        hook_card_sec=5.0,
    )
    assert returned == str(out)
    assert out.exists() and out.stat().st_size > 0

    frames = _frame_count(out)
    assert frames > 0, f"hook-card burn produced no decodable frames ({frames})"
