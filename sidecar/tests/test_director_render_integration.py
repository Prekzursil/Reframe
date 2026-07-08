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
from media_studio.features.edit_validate import Understanding, validate_and_reject
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp, EditPlan

pytestmark = pytest.mark.integration

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_SKIP = pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _drawtext_works() -> bool:
    """ffmpeg ``drawtext`` needs fontconfig. On a host that has ffmpeg but NO
    fontconfig (common on bare Windows) drawtext CRASHES (access violation
    0xC0000005) instead of failing cleanly — hard-red-failing the overlayText /
    lowerThird render tests. Probe a tiny drawtext render so such a host SKIPS the
    drawtext-only tests instead (Linux CI has fontconfig, so it runs there)."""
    if not _HAVE_FFMPEG:
        return False
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.1",
                "-vf",
                "drawtext=text=probe:fontsize=10",
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - host probe
        return False
    return proc.returncode == 0


_HAVE_DRAWTEXT = _drawtext_works()
_SKIP_DRAWTEXT = pytest.mark.skipif(not _HAVE_DRAWTEXT, reason="ffmpeg drawtext/fontconfig unavailable on this host")

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


def _dims(path: Path) -> tuple[int, int]:
    """Return the (width, height) of ``path``'s first video stream."""
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
    w, h = out.split("x")
    return int(w), int(h)


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


def _apply_one(pc: ProjectCopy, op: EditOp):  # noqa: ANN202 - test helper
    """Apply a single-op plan with the REAL engines and return ``(result, engines)``."""
    engines = engines_mod.build_engines()
    return apply_plan(EditPlan("p", "v", "g", "h", ops=(op,)), project_copy=pc, engines=engines), engines


@_SKIP
def test_reframe_renders_real_target_dimensions(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    assert _dims(Path(source_before)) == (320, 240)  # landscape source
    op = EditOp(id="rf1", kind="reframe", span=(0, 1500), params={"aspect": "9:16"})

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _dims(rendered) == (1080, 1920)  # NON-no-op: vertical target dims
    assert _ffprobe_ok(rendered) > 0

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_retime_renders_shorter_duration(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    src_dur = _ffprobe_ok(Path(source_before))
    op = EditOp(id="rt1", kind="retime", span=(0, 1500), params={"factor": 2.0})

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    # 2x speed-up -> roughly half the duration (NON-no-op): clearly shorter.
    assert _ffprobe_ok(rendered) < src_dur * 0.75

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_remove_fillers_renders_shorter_duration(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    src_dur = _ffprobe_ok(Path(source_before))
    # Excise the middle 0.5s of the 1.5s clip.
    op = EditOp(id="rmf1", kind="removeFillers", span=(500, 1000))

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) < src_dur  # NON-no-op: a span was cut out

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_zoom_pan_renders_valid_motion(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    op = EditOp(id="zp1", kind="zoomPan", span=(0, 1500))

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) > 0  # ffprobe-valid re-rasterised mp4

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP_DRAWTEXT
@pytest.mark.parametrize("kind", ["overlayText", "lowerThird"])
def test_drawtext_ops_render_valid_mp4(kind: str, sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    op = EditOp(id="dt1", kind=kind, span=(0, 1500), params={"text": "Real Text 50%"})

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) > 0  # ffprobe-valid drawtext-burned mp4

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP_DRAWTEXT
@pytest.mark.parametrize("kind", ["overlayText", "lowerThird"])
def test_drawtext_op_survives_validation_then_applies(kind: str, sample: Path, tmp_path: Path) -> None:
    # INTEGRATED contract: overlayText/lowerThird are _TRACK_KINDS, so a real op
    # carries BOTH a ``track`` (required by validate_and_reject) AND the ``text``
    # the drawtext engine renders (matching the golden-plan op shape). This proves
    # the op survives validation AND renders REAL media end-to-end (not dropped,
    # not a no-op) — the path the isolated engine tests bypass.
    pc = _project_copy(tmp_path, sample, tracks=[{"id": "overlay", "kind": "overlay", "cues": []}])
    source_before = pc.data["video"]["path"]
    op = EditOp(id="dt1", kind=kind, span=(0, 1500), params={"track": "overlay", "text": "Real 50%"})
    plan = EditPlan("p", "v", "g", "h", ops=(op,))

    # validate against an understanding where the target track EXISTS.
    understanding = Understanding(clip_duration_ms=1500, tracks=("overlay",))
    validated = validate_and_reject(plan, understanding=understanding)
    assert validated.ops[0].status != "dropped"  # NOT dropped by unknown-track

    engines = engines_mod.build_engines()
    result = apply_plan(validated, project_copy=pc, engines=engines)

    assert result.ops_status[0].status == "applied"  # rendered, not a no-op
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) > 0

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_translate_caption_burns_translated_track(sample: Path, tmp_path: Path) -> None:
    translated = [{"index": 1, "start": 0.2, "end": 1.0, "text": "bonjour"}]
    pc = _project_copy(tmp_path, sample, tracks=[{"id": "fr", "lang": "fr", "cues": translated}])
    source_before = pc.data["video"]["path"]
    op = EditOp(id="tc1", kind="translateCaption", params={"track": "fr"})

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) > 0

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
def test_export_renders_valid_delivery_mp4(sample: Path, tmp_path: Path) -> None:
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    op = EditOp(id="ex1", kind="export")

    result, engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "applied"
    rendered = Path(pc.data["video"]["path"])
    assert rendered != Path(source_before)
    assert _ffprobe_ok(rendered) > 0  # ffprobe-valid re-encoded delivery

    undo = apply_plan(result.inverse_plan, project_copy=pc, engines=engines)
    assert undo.ops_status[0].status == "applied"
    assert Path(pc.data["video"]["path"]) == Path(source_before)


@_SKIP
@pytest.mark.parametrize("kind", ["stitchPanorama", "regenScroll", "ocrExtractList", "reorder"])
def test_deferred_kinds_degrade_gracefully(kind: str, sample: Path, tmp_path: Path) -> None:
    # A deferred-kind op has NO engine -> the op is marked failed and the COPY is
    # auto-rolled-back: the source manifest is untouched (graceful degradation,
    # never a crash or a corrupt source).
    pc = _project_copy(tmp_path, sample)
    source_before = pc.data["video"]["path"]
    span = None if kind == "reorder" else (0, 1500)
    op = EditOp(id="d1", kind=kind, span=span, params={"panorama": "p"} if kind == "regenScroll" else {})

    result, _engines = _apply_one(pc, op)

    assert result.ops_status[0].status == "failed"
    assert "no engine for kind" in (result.ops_status[0].status_reason or "")
    # Source untouched + COPY still points at the original (rolled back).
    assert Path(pc.data["video"]["path"]) == Path(source_before)
    assert _ffprobe_ok(Path(source_before)) > 0
