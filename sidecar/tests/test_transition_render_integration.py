"""REAL-ffmpeg proof that a transition actually OVERLAPS (v1.5 transitions lane).

Everything else about this feature is asserted against a STRING: the unit tests
check that the right filtergraph text is built, with a fake runner standing in for
ffmpeg. That proves the builder is self-consistent and proves nothing about
whether ffmpeg accepts the graph — a mistyped filter name, a bad label, or an
offset ffmpeg rejects would sail through every one of them.

This file closes that hole with the only assertion ffmpeg itself can settle:
**the rendered file is SHORTER than the sum of its parts.** Concat sums, a
transition sums-then-subtracts one overlap per boundary, and the two answers are
0.5s apart on a 1.5s clip — so a probe of the real output discriminates "the
transition ran" from "it silently degraded to a join", which no string assertion
can do.

The inputs are deliberately DIFFERENT SIZES (320x240 joined to 160x120), because
``xfade`` refuses mismatched frames: if the conform stage in
``transitions._conform_chain`` were wrong or missing, ffmpeg would exit non-zero
here rather than quietly produce something. The output is then probed to confirm
it conformed to the SOURCE geometry rather than the smaller input's.

Marked ``integration`` like ``test_director_render_integration`` (the pinned
coverage command runs it; a host without ffmpeg skips cleanly rather than
red-failing).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features.director_op_engines import DirectorEngineError, build_engines
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp

pytestmark = pytest.mark.integration

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_SKIP = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")

#: Each source clip's length. Must exceed the transition (see xfade_offsets).
_CLIP_SEC = 1.5
#: The transition length used throughout, in ms and seconds.
_TRANSITION_MS = 500
_TRANSITION_SEC = _TRANSITION_MS / 1000.0
#: mp4 container timing is not exact; 0.25s still discriminates 2.5s from 3.0s.
_TOLERANCE = 0.25


def _make_clip(path: Path, *, width: int, height: int, freq: int) -> None:
    """Render a tiny real testsrc clip (video + audio) at a given geometry."""
    subprocess.run(  # noqa: S603 - fixed argv, no shell, test-only sample generation
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=15:duration={_CLIP_SEC}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={_CLIP_SEC}",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-t",
            str(_CLIP_SEC),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _duration(path: Path) -> float:
    """Probe the container duration of ``path`` (also proves it is readable)."""
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return float(out)


def _dims(path: Path) -> tuple[int, int]:
    """Return the ``(width, height)`` of ``path``'s first video stream."""
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    width, height = out.split("x")
    return int(width), int(height)


def _copy_at(tmp_path: Path, src: Path) -> ProjectCopy:
    manifest = tmp_path / ".director-copy" / "project.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    return ProjectCopy(data={"video": {"path": str(src)}}, manifest_path=manifest)


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """A 320x240 source plus two extra clips, one deliberately a DIFFERENT size."""
    if not _HAVE_FFMPEG:  # pragma: no cover - skipped wholesale when ffmpeg absent
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("transition-clips")
    source = root / "source.mp4"
    same = root / "same.mp4"
    smaller = root / "smaller.mp4"
    _make_clip(source, width=320, height=240, freq=440)
    _make_clip(same, width=320, height=240, freq=660)
    _make_clip(smaller, width=160, height=120, freq=880)
    return source, same, smaller


@_SKIP
def test_a_real_transition_render_is_shorter_than_a_concat(tmp_path: Path, clips: tuple[Path, Path, Path]) -> None:
    source, same, _smaller = clips
    project_copy = _copy_at(tmp_path, source)
    op = EditOp(id="tx", kind="transition", params={"clips": [str(same)], "durationMs": _TRANSITION_MS})

    build_engines()["transition"](op, project_copy)

    rendered = Path(project_copy.data["video"]["path"])
    assert rendered.exists()
    measured = _duration(rendered)
    concat_would_be = _CLIP_SEC * 2
    overlapped = concat_would_be - _TRANSITION_SEC
    # THE assertion: 2.5s, not 3.0s. A join that silently replaced the transition
    # would land on `concat_would_be` and fail here.
    assert measured == pytest.approx(overlapped, abs=_TOLERANCE)
    assert abs(measured - concat_would_be) > _TOLERANCE


@_SKIP
def test_a_real_transition_conforms_a_differently_sized_clip(tmp_path: Path, clips: tuple[Path, Path, Path]) -> None:
    # xfade refuses mismatched frames, so joining 320x240 to 160x120 exercises the
    # conform stage for real: without it ffmpeg exits non-zero and this red-fails.
    source, _same, smaller = clips
    project_copy = _copy_at(tmp_path, source)
    op = EditOp(id="tx", kind="transition", params={"clips": [str(smaller)], "durationMs": _TRANSITION_MS})

    build_engines()["transition"](op, project_copy)

    rendered = Path(project_copy.data["video"]["path"])
    assert _dims(rendered) == (320, 240)  # the SOURCE geometry, not the smaller input's
    assert _duration(rendered) == pytest.approx(_CLIP_SEC * 2 - _TRANSITION_SEC, abs=_TOLERANCE)


@_SKIP
def test_a_real_three_clip_chain_subtracts_both_overlaps(tmp_path: Path, clips: tuple[Path, Path, Path]) -> None:
    # Two boundaries: the second xfade's offset is computed against the ALREADY
    # shortened running output, so a naive offset would desync or fail here.
    source, same, smaller = clips
    project_copy = _copy_at(tmp_path, source)
    op = EditOp(
        id="tx",
        kind="transition",
        params={
            "clips": [str(same), str(smaller)],
            "style": "wipeLeft",
            "durationMs": _TRANSITION_MS,
        },
    )

    build_engines()["transition"](op, project_copy)

    rendered = Path(project_copy.data["video"]["path"])
    assert _duration(rendered) == pytest.approx(_CLIP_SEC * 3 - 2 * _TRANSITION_SEC, abs=_TOLERANCE)


@_SKIP
def test_a_real_render_refuses_a_clip_shorter_than_the_transition(
    tmp_path: Path, clips: tuple[Path, Path, Path]
) -> None:
    # The guard must fire BEFORE ffmpeg is spawned — a negative xfade offset is
    # rendered as garbage rather than refused, so "ffmpeg would have caught it"
    # is not true and the precondition has to be ours.
    source, same, _smaller = clips
    project_copy = _copy_at(tmp_path, source)
    op = EditOp(
        id="tx",
        kind="transition",
        # 2000ms transition against 1.5s clips: nothing can host it.
        params={"clips": [str(same)], "durationMs": 2000},
    )

    with pytest.raises(DirectorEngineError, match="shorter than"):
        build_engines()["transition"](op, project_copy)
