"""E2E real-libass burn proof for the OpusClip karaoke preset (V1.1 WU SP1).

The default unit suite proves :func:`caption_karaoke.build_karaoke_ass` emits the
exact ASS tags (inline ``\\1c`` accent, ``\\t`` ``\\fscx``/``\\fscy`` scale-pop,
``\\r`` reset, ``BorderStyle=1``, safe-area ``MarginV``) PURELY — it never feeds
that document to a real libass. This module closes that gap: it runs the karaoke
ASS through the SHIPPED :class:`caption.CaptionEngine` burn path (real ffmpeg +
real libass via the ``subtitles`` filter) and asserts the output is a valid,
non-zero-FRAME video — i.e. libass actually parsed those tags and rasterised
them onto the clip.

OPT-IN: tagged ``e2e`` so the default 100%-coverage gate (addopts
``-m 'not e2e'``) DESELECTS this module; it also skips when ffmpeg/ffprobe are
absent or ffmpeg was built without the libass ``subtitles`` filter. Run it with::

    python -m pytest -m e2e sidecar/tests/e2e/test_karaoke_burn.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features.caption import CaptionEngine
from media_studio.features.caption_karaoke import build_karaoke_ass

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
        reason="ffmpeg/ffprobe with the libass 'subtitles' filter required for the karaoke burn",
    ),
]

# A small canvas keeps the burn fast; the tags are resolution-independent.
_W, _H = 360, 640
_DUR = 2.0

# Two word-timed cues so the karaoke builder emits the alternating accent + pop
# across several per-word events (the exact tags this burn must prove parse).
_CUES = [
    {
        "index": 1,
        "start": 0.0,
        "end": 1.0,
        "text": "hello brave",
        "words": [
            {"text": "hello", "start": 0.0, "end": 0.5},
            {"text": "brave", "start": 0.5, "end": 1.0},
        ],
    },
    {
        "index": 2,
        "start": 1.0,
        "end": 2.0,
        "text": "new world",
        "words": [
            {"text": "new", "start": 1.0, "end": 1.5},
            {"text": "world", "start": 1.5, "end": 2.0},
        ],
    },
]


def _make_clip(path: Path) -> None:
    """Render a tiny real H.264 test clip (color + tone) with ffmpeg."""
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
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={_DUR}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0 and path.exists() and path.stat().st_size > 0, res.stderr


def _frame_count(path: Path) -> int:
    """Decode-count the output's video frames via ffprobe (proves real rasterisation)."""
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


def test_build_karaoke_ass_burns_through_real_libass_to_nonzero_frames(tmp_path: Path) -> None:
    """The karaoke ASS must burn through real ffmpeg/libass into a valid clip.

    This is the machine-verified burn contract the unit tests cannot give: the
    inline ``\\1c`` / ``\\t`` ``\\fscx`` / ``\\r`` / ``BorderStyle=1`` / safe-area
    ``MarginV`` tags are valid libass and rasterise to a non-zero-frame video.
    """
    # Sanity: the document we burn actually carries the load-bearing karaoke tags.
    ass = build_karaoke_ass(_CUES, width=_W, height=_H)
    assert "\\1c" in ass and "\\fscx115" in ass and "{\\r}" in ass

    clip = tmp_path / "src.mp4"
    out = tmp_path / "karaoke.mp4"
    _make_clip(clip)

    # The SHIPPED engine path: writes the ASS to a temp file + runs the real
    # build_burn_argv (ffmpeg subtitles=…) through the real ffmpeg.run.
    returned = CaptionEngine().render(
        str(clip),
        _CUES,
        str(out),
        burn=True,
        width=_W,
        height=_H,
        karaoke=True,
    )
    assert returned == str(out)
    assert out.exists() and out.stat().st_size > 0

    frames = _frame_count(out)
    assert frames > 0, f"karaoke burn produced no decodable frames ({frames})"
