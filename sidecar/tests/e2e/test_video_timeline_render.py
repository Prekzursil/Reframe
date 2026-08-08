"""E2E real-ffmpeg proof that a rendered video timeline lands FRAME-ACCURATELY.

The default unit suite proves the argv: that a single-source timeline delegates
BYTE-IDENTICALLY to the shipped cutter (``fillers.build_segment_cut_argv``) and
that the model's frame indices survive the round-trip into the filter graph. What
it cannot prove is that the graph ffmpeg actually executes produces a file of the
promised LENGTH — and a timeline editor whose export is a different duration than
the timeline showed is exactly the "looks functional, silently drops edits"
failure this feature must not have.

So this module runs the REAL argv through the REAL ffmpeg and ffprobes the result:

* single-source (the common trim/razor/reorder case) -> delegated argv;
* MULTI-source (two different files on the timeline) -> the N-input argv this
  module adds, which the shipped cutter cannot express and which therefore has no
  inherited real-ffmpeg proof at all.

Duration is asserted to within HALF A FRAME of the sum of the segment durations.
That tolerance is not slack for the cut math: it is the container's own
timestamp/duration rounding (a muxed duration is not exact to the nanosecond),
and half a frame is tighter than any edit error this feature could make.

OPT-IN: tagged ``e2e`` so the default 100%-coverage gate (addopts
``-m 'not e2e'``) DESELECTS it, and skipped when ffmpeg/ffprobe are absent. Run::

    python -m pytest -m e2e sidecar/tests/e2e/test_video_timeline_render.py -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features import video_tracks as vt

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (_FFMPEG and _FFPROBE),
        reason="real ffmpeg + ffprobe are required to prove the rendered duration",
    ),
]

FPS = 30
SETTINGS: dict[str, object] = {}
# A tiny canvas keeps each encode well under a second; the cut math is
# resolution-independent.
_W, _H = 160, 120


def _make_clip(path: Path, seconds: float, hue: str) -> None:
    """Render a tiny real H.264+AAC clip (colour + tone) at exactly ``seconds``."""
    res = subprocess.run(  # noqa: S603 - argv list, no shell, local test binary
        [
            _FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={hue}:s={_W}x{_H}:r={FPS}:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
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
    assert res.returncode == 0, res.stderr
    assert path.is_file() and path.stat().st_size > 0


def _probe(path: Path) -> dict[str, object]:
    """ffprobe the container: its duration and its stream codec types."""
    res = subprocess.run(  # noqa: S603 - argv list, no shell, local test binary
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _render(segments: list[dict[str, object]], out_path: Path) -> None:
    argv = vt.build_timeline_render_argv(segments, str(out_path), SETTINGS)
    res = subprocess.run(argv, capture_output=True, text=True, check=False)  # noqa: S603 - argv list from the builder
    assert res.returncode == 0, f"{argv}\n{res.stderr}"


def _assert_lands(out_path: Path, expected_sec: float) -> None:
    """The rendered file exists, carries A/V, and is expected_sec +/- half a frame."""
    probe = _probe(out_path)
    kinds = sorted(str(s.get("codec_type")) for s in probe["streams"])  # type: ignore[index]
    assert kinds == ["audio", "video"], kinds
    actual = float(probe["format"]["duration"])  # type: ignore[index,call-overload]
    half_frame = 0.5 / FPS
    assert abs(actual - expected_sec) <= half_frame, (
        f"rendered {actual:.4f}s, timeline promised {expected_sec:.4f}s "
        f"(off by {abs(actual - expected_sec) * FPS:.2f} frames)"
    )


def _lanes(clips: list[dict[str, object]]) -> list[dict[str, object]]:
    return [vt.normalize_video_track({"id": "vt1", "index": 0, "clips": clips}, fps=FPS)]


def test_single_source_timeline_renders_the_promised_duration(tmp_path: Path) -> None:
    """Razor + reorder on ONE source: two kept spans, rendered through the
    delegated shipped cutter."""
    src = tmp_path / "a.mp4"
    _make_clip(src, 3.0, "red")
    lanes = _lanes(
        [
            # deliberately authored out of timeline order: flatten sorts them
            {"id": "c2", "path": str(src), "srcIn": 2.0, "srcOut": 2.5, "timelineStart": 0.5},
            {"id": "c1", "path": str(src), "srcIn": 0.0, "srcOut": 0.5, "timelineStart": 0.0},
        ]
    )
    segments = vt.flatten_timeline(lanes, fps=FPS)
    assert [s["srcIn"] for s in segments] == [0.0, 2.0]
    out = tmp_path / "single.mp4"
    _render(segments, out)
    _assert_lands(out, vt.timeline_duration(segments))  # 0.5 + 0.5 == 1.0s


def test_multi_source_timeline_renders_the_promised_duration(tmp_path: Path) -> None:
    """TWO different files on one timeline — the N-input argv this module owns.

    The shipped cutter cannot express multiple inputs, so this path has NO
    inherited real-ffmpeg proof; without this test its correctness would rest on
    an inference from the single-source graph's shape.
    """
    a = tmp_path / "a.mp4"
    b = tmp_path / "b.mp4"
    _make_clip(a, 2.0, "red")
    _make_clip(b, 2.0, "blue")
    lanes = _lanes(
        [
            {"id": "c1", "path": str(a), "srcIn": 0.0, "srcOut": 0.5, "timelineStart": 0.0},
            {"id": "c2", "path": str(b), "srcIn": 1.0, "srcOut": 1.5, "timelineStart": 0.5},
            # back to the FIRST file: proves an input is reused, not re-added
            {"id": "c3", "path": str(a), "srcIn": 1.5, "srcOut": 2.0, "timelineStart": 1.0},
        ]
    )
    segments = vt.flatten_timeline(lanes, fps=FPS)
    argv = vt.build_timeline_render_argv(segments, str(tmp_path / "x.mp4"), SETTINGS)
    assert argv.count("-i") == 2, "the two distinct sources must dedup to two inputs"
    out = tmp_path / "multi.mp4"
    _render(segments, out)
    _assert_lands(out, vt.timeline_duration(segments))  # 3 x 0.5 == 1.5s


def test_a_trimmed_clip_renders_exactly_the_trimmed_length(tmp_path: Path) -> None:
    """The EDIT itself lands: trim the tail by 15 frames and the file is 15
    frames shorter. This is the timing contract measured end to end, on bytes."""
    src = tmp_path / "a.mp4"
    _make_clip(src, 2.0, "green")
    clip = vt.normalize_video_clip(
        {"id": "c1", "path": str(src), "srcIn": 0.0, "srcOut": 1.0, "timelineStart": 0.0},
        fps=FPS,
    )
    trimmed = vt.trim_clip_edge(clip, "end", 1.0 - 15 / FPS, fps=FPS)
    assert vt.frame_span(trimmed, FPS) == vt.frame_source_span(trimmed, FPS) == 15
    segments = vt.flatten_timeline(_lanes([trimmed]), fps=FPS)
    out = tmp_path / "trimmed.mp4"
    _render(segments, out)
    _assert_lands(out, 15 / FPS)
