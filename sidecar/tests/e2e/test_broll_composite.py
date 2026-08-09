"""E2E real-ffmpeg proof that the auto-b-roll composite renders the PIXELS.

``tests/test_broll_compose.py`` asserts the exact argv and the exact
``filter_complex``. That proves the STRING. It cannot prove ffmpeg accepts the
graph, that the time-shift puts frame 0 of an asset at second S, that the
``enable`` gate really closes, that the inset lands in the corner the expression
names, or that the speaker's audio survives — every one of which is a way this
feature can be green and broken.

So this module renders for real and probes the OUTPUT:

* a 1080x1920 blue "speaker" clip with a tone,
* a RED still composited as a full-frame cutaway over ``[2, 5]``,
* a GREEN clip composited as a top-right PiP over ``[6, 8]``,

then samples mean RGB inside chosen rectangles at chosen timestamps. Every
assertion carries a CONTROL — a timestamp outside the window, or the opposite
corner — because "the frame changed" is not the same claim as "the b-roll landed
in the right place at the right time", and only the control separates them.

OPT-IN: tagged ``e2e`` so the default 100%-coverage gate (addopts
``-m 'not e2e'``) deselects it. Run it with::

    python -m pytest -m e2e sidecar/tests/e2e/test_broll_composite.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features import broll_compose as bc

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe required for the b-roll composite proof"),
]

# The export canvas the builder defaults to; kept explicit so the crop maths below
# is readable rather than derived three files away.
_W, _H = bc.DEFAULT_CANVAS_W, bc.DEFAULT_CANVAS_H
_TOTAL = 10.0
#: PiP geometry the top-right corner expression + a 4:3 asset must produce:
#: width = even(1080 * 34%) = 366; height = 366 * 480/640 = 274 (already even).
_PIP_W, _PIP_H = 366, 274
_PIP_X, _PIP_Y = _W - _PIP_W - bc.DEFAULT_PIP_PADDING, bc.DEFAULT_PIP_PADDING

_CUTAWAY = (2.0, 5.0)
_PIP = (6.0, 8.0)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=600)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    """Render the composite once; every assertion below probes this one file."""
    tmp = tmp_path_factory.mktemp("broll-e2e")
    main, still, clip, out = (tmp / n for n in ("talk.mp4", "red.png", "green.mp4", "out.mp4"))

    # A blue speaker with audio, so a dropped audio map is detectable.
    assert (
        _run(
            [
                _FFMPEG,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=blue:s={_W}x{_H}:d={_TOTAL}:r=25",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={_TOTAL}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(main),
            ]
        ).returncode
        == 0
    )
    assert (
        _run(
            [
                _FFMPEG,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=640x480:d=1",
                "-frames:v",
                "1",
                str(still),
            ]
        ).returncode
        == 0
    )
    assert (
        _run(
            [
                _FFMPEG,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=640x480:d=6:r=25",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(clip),
            ]
        ).returncode
        == 0
    )

    insertions = [
        {
            "segmentIndex": 0,
            "start": _CUTAWAY[0],
            "end": _CUTAWAY[1],
            "duration": _CUTAWAY[1] - _CUTAWAY[0],
            "sourceStart": 0.0,
            "assetId": "a-red",
            "path": str(still),
            "kind": "image",
            "score": 0.9,
            "reason": "r",
            "layout": "cutaway",
        },
        {
            # sourceStart is non-zero so the -ss seek is exercised, not just present.
            "segmentIndex": 1,
            "start": _PIP[0],
            "end": _PIP[1],
            "duration": _PIP[1] - _PIP[0],
            "sourceStart": 1.0,
            "assetId": "a-green",
            "path": str(clip),
            "kind": "video",
            "score": 0.8,
            "reason": "r",
            "layout": "pip",
        },
    ]
    proc = _run(bc.build_broll_argv(str(main), insertions, str(out)))
    assert proc.returncode == 0, f"ffmpeg rejected the generated filtergraph:\n{proc.stderr[-2000:]}"
    return out


def _mean_rgb(path: Path, when: float, crop: str) -> tuple[int, int, int]:
    """Mean RGB of ``crop`` at ``when`` (``flags=area`` = a true box average)."""
    raw = subprocess.run(
        [
            _FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{when}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop={crop},scale=1:1:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout
    assert len(raw) == 3, "expected exactly one RGB triple"
    return (raw[0], raw[1], raw[2])


_FULL = f"{_W}:{_H}:0:0"
_PIP_BOX = f"{_PIP_W}:{_PIP_H}:{_PIP_X}:{_PIP_Y}"
#: Same-size rectangle in the OPPOSITE corner. This is the control that
#: distinguishes "the inset is where the corner expression says" from "the
#: frame changed somewhere".
_CONTROL_BOX = f"{_PIP_W}:{_PIP_H}:{bc.DEFAULT_PIP_PADDING}:{_H - _PIP_H - bc.DEFAULT_PIP_PADDING}"


def test_output_geometry_and_duration_survive(rendered):
    out = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "csv=p=0",
            str(rendered),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.split()
    assert out[0] == f"{_W},{_H}"
    assert float(out[1]) == pytest.approx(_TOTAL, abs=0.25)


def test_the_speakers_audio_stream_survives_the_composite(rendered):
    # -map 0:a? is the only audio map; if it were dropped (or pointed at the
    # b-roll input) this count changes.
    streams = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            str(rendered),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.split()
    assert len(streams) == 1


def test_the_cutaway_covers_the_frame_inside_its_window(rendered):
    r, g, b = _mean_rgb(rendered, 3.5, _FULL)
    assert r > 200 and b < 60, f"expected a red full-frame cutaway at t=3.5s, got {(r, g, b)}"


@pytest.mark.parametrize("when", [1.0, 5.5, 9.0])
def test_the_frame_is_the_untouched_speaker_outside_every_window(rendered, when):
    # The CONTROL for the cutaway assertion: before it, between the two windows,
    # and after both, the picture must be the original blue speaker.
    r, _g, b = _mean_rgb(rendered, when, _FULL)
    assert b > 200 and r < 60, f"expected the untouched blue speaker at t={when}s, got {(r, _g, b)}"


def test_the_pip_lands_in_the_corner_the_expression_names(rendered):
    inset = _mean_rgb(rendered, 7.0, _PIP_BOX)
    control = _mean_rgb(rendered, 7.0, _CONTROL_BOX)
    # ffmpeg's lavfi `green` is CSS green (0,128,0), not (0,255,0).
    assert inset[1] > 100 and inset[2] < 60, f"expected the green inset in the top-right box, got {inset}"
    assert control[2] > 200 and control[1] < 60, f"the opposite corner must stay speaker-blue, got {control}"


def test_the_pip_is_absent_before_its_window_opens(rendered):
    # Same rectangle, earlier timestamp: the enable gate must really be closed.
    before = _mean_rgb(rendered, 1.0, _PIP_BOX)
    assert before[2] > 200 and before[1] < 60, f"the PiP box must be speaker-blue at t=1.0s, got {before}"
