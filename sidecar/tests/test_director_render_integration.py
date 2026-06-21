"""REAL-ffmpeg integration test for the director op-engines (FIX #7).

These tests use the DEFAULT runner (``ffmpeg.run`` — the real subprocess) over a
real, tiny ``lavfi testsrc`` clip to PROVE the marquee claim: ``director.apply``
renders edited media that is ffprobe-valid (not a no-op manifest copy), and
``director.undo`` round-trips. They are marked ``integration`` (the marker is
declared in ``pyproject.toml``); the pinned coverage command runs them (no ``-m``
filter) since ffmpeg is present in that environment. They skip cleanly if ffmpeg
is unavailable so a no-ffmpeg box never red-fails.

The pure dispatch/branch logic is covered to 100% by ``test_director_op_engines``
with a fake runner; this file is the empirical render proof, kept tiny (a ~1.5 s
clip, two ops) so it adds only a couple of seconds to the suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from media_studio.features import director_op_engines as engines_mod
from media_studio.features.apply_engine import apply_plan
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp, EditPlan

pytestmark = pytest.mark.integration

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_SKIP = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")

_CUES = [{"index": 1, "start": 0.2, "end": 1.0, "text": "real burn"}]


def _make_sample(path: Path, *, seconds: float = 1.5) -> None:
    """Render a tiny real testsrc clip (video + audio) for the engines to edit."""
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
            f"testsrc=size=320x240:rate=15:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-t",
            str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _ffprobe_ok(path: Path) -> float:
    """Return the playable duration of ``path`` (a ffprobe-valid mp4 with video)."""
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


def _project_copy(tmp_path: Path, src: Path, *, tracks: list | None = None) -> ProjectCopy:
    data: dict = {"video": {"path": str(src)}}
    if tracks is not None:
        data["tracks"] = tracks
    manifest = tmp_path / ".director-copy" / "project.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    return ProjectCopy(data=data, manifest_path=manifest)


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not _HAVE_FFMPEG:  # pragma: no cover - skipped wholesale when ffmpeg absent
        pytest.skip("ffmpeg not installed")
    path = tmp_path_factory.mktemp("director-sample") / "sample.mp4"
    _make_sample(path)
    return path


@_SKIP
def test_trim_renders_real_valid_mp4_and_undo_round_trips(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    engines = engines_mod.build_engines()  # DEFAULT runner = real ffmpeg
    op = EditOp(id="trim1", kind="trim", span=(500, 1000))  # drop 0.5s..1.0s

    result = apply_plan(EditPlan("p", "v", "g", "h", ops=(op,)), project_copy=pc, engines=engines)

    assert result.ops_status[0].status == "applied"  # NOT failed (the old bug)
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)  # re-pointed at a NEW file
    assert _ffprobe_ok(rendered) > 0  # a real, playable edited mp4
    # The source clip was never mutated (apply writes only the COPY).
    assert _ffprobe_ok(Path(source_before)) > 0

    # undo: re-apply the recorded inverse -> the COPY points back at the source.
    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_caption_burns_real_subtitles(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample, tracks=[{"id": "cap1", "kind": "hard", "cues": _CUES}])
    source_before = pc.data["video"]["path"]
    engines = engines_mod.build_engines()
    op = EditOp(id="cap1", kind="caption", params={"track": "cap1"})

    result = apply_plan(EditPlan("p", "v", "g", "h", ops=(op,)), project_copy=pc, engines=engines)

    assert result.ops_status[0].status == "applied"
    burned = Path(pc.data["video"]["path"])
    assert burned != Path(source_before)
    assert _ffprobe_ok(burned) > 0  # ffprobe-valid burned-in mp4

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)
