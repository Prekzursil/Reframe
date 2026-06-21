"""Unit tests for the real director op-engine adapters (FIX #7).

PURE-logic only: the ONE impure thing — the ffmpeg subprocess — is the injected
``runner``, replaced here by a fake that STUBS the output file (writes a few
bytes) and records the argv. So these tests exercise the full adapter logic —
source resolution, argv build, manifest re-point, recorded inverse, dual-mode
undo, and every error branch — with NO real ffmpeg, deterministically, carrying
the 100% line+branch gate. A separate ``@pytest.mark.integration`` test
(``test_director_render_integration``) proves a real ffprobe-valid mp4 + undo
round-trip with the DEFAULT runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from media_studio.features import director_op_engines as engines_mod
from media_studio.features.director_op_engines import (
    DEFERRED_KINDS,
    RESTORE_KEY,
    WIRED_KINDS,
    DirectorEngineError,
    build_engines,
)
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp

CLIP_SEC = 12.0


def _copy(tmp_path: Path, *, video: Any = "__src__", tracks: Any = None) -> ProjectCopy:
    """A ProjectCopy whose manifest folder is real (so renders land on disk)."""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00source")
    data: dict[str, Any] = {"video": {"path": str(src)} if video == "__src__" else video}
    if tracks is not None:
        data["tracks"] = tracks
    manifest = tmp_path / ".director-copy" / "project.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    return ProjectCopy(data=data, manifest_path=manifest)


class FakeRunner:
    """A fake ffmpeg runner: stubs the output file (last argv element) + records calls."""

    def __init__(self, *, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv: Any, total_sec: float = 0.0, **_k: Any) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00rendered")  # the stubbed render output
        return self.code


def _fake_probe(monkeypatch: pytest.MonkeyPatch, value: float = CLIP_SEC) -> None:
    monkeypatch.setattr(engines_mod._ffmpeg, "ffprobe_duration", lambda *_a, **_k: value)


# --------------------------------------------------------------------------- #
# build_engines / log_deferred
# --------------------------------------------------------------------------- #
def test_build_engines_covers_wired_kinds() -> None:
    table = build_engines(runner=FakeRunner())
    assert set(table) == set(WIRED_KINDS)
    assert "trim" in table and "caption" in table and "removeSilence" in table


def test_build_engines_defaults_runner_to_ffmpeg_run() -> None:
    # No runner -> closes over the real ffmpeg.run (just assert the table builds).
    table = build_engines()
    assert set(table) == set(WIRED_KINDS)


def test_deferred_kinds_have_no_engine() -> None:
    table = build_engines(runner=FakeRunner())
    assert not (set(DEFERRED_KINDS) & set(table))
    # The honestly-deferred subsystem ops stay out of the table; reorder too.
    assert {"stitchPanorama", "regenScroll", "ocrExtractList", "reorder"} <= set(DEFERRED_KINDS)
    # The ffmpeg-achievable ops moved INTO the wired table.
    assert {
        "reframe",
        "zoomPan",
        "retime",
        "overlayText",
        "lowerThird",
        "removeFillers",
        "translateCaption",
        "export",
    } <= set(WIRED_KINDS)


def test_deferred_subsystems_cover_every_deferred_kind() -> None:
    # Every deferred kind names the subsystem it requires (no bare deferrals).
    assert set(engines_mod.DEFERRED_SUBSYSTEMS) == set(DEFERRED_KINDS)
    assert "panorama" in engines_mod.DEFERRED_SUBSYSTEMS["stitchPanorama"]
    assert "OCR" in engines_mod.DEFERRED_SUBSYSTEMS["ocrExtractList"]


def test_log_deferred_announces_unwired_kinds_with_subsystems() -> None:
    seen: list[tuple[Any, ...]] = []

    class _Log:
        def info(self, *args: Any) -> None:
            seen.append(args)

    engines_mod.log_deferred(_Log())
    assert seen and "deferred" in seen[0][0]
    notice = seen[0][-1]  # the "kind (requires <subsystem>)" string
    assert "stitchPanorama (requires" in notice and "OCR" in notice


# --------------------------------------------------------------------------- #
# trim
# --------------------------------------------------------------------------- #
def test_trim_renders_and_records_inverse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    op = EditOp(id="t1", kind="trim", span=(2000, 5000))

    inverse = build_engines(runner=runner)["trim"](op, pc)

    out = pc.data["video"]["path"]
    assert out != src_before  # the COPY was RE-POINTED at the render
    assert Path(out).exists() and Path(out).read_bytes()  # a real (stubbed) file
    assert inverse.kind == "trim" and inverse.params[RESTORE_KEY] == src_before
    # The PERSISTED COPY manifest references the render (not the orphaned source) —
    # this is what a real client reads back via ApplyResult.project_copy_path.
    persisted = json.loads(pc.manifest_path.read_text(encoding="utf-8"))
    assert persisted["video"]["path"] == out
    # head [0,2.0] + tail [5.0,12.0] kept -> two trim/atrim pairs in the filtergraph.
    fc = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "trim=start=0.000:end=2.000" in fc and "trim=start=5.000:end=12.000" in fc


def test_trim_head_only_when_span_reaches_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["trim"](EditOp(id="t", kind="trim", span=(3000, 12000)), pc)
    fc = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "concat=n=1" in fc  # only the head [0,3.0] kept


def test_trim_tail_only_when_span_starts_at_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["trim"](EditOp(id="t", kind="trim", span=(0, 4000)), pc)
    fc = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "trim=start=4.000:end=12.000" in fc


def test_trim_full_span_is_a_render_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="nothing left to keep"):
        build_engines(runner=FakeRunner())["trim"](EditOp(id="t", kind="trim", span=(0, 12000)), pc)


def test_trim_ffmpeg_failure_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="ffmpeg exit 1"):
        build_engines(runner=FakeRunner(code=1))["trim"](EditOp(id="t", kind="trim", span=(2000, 5000)), pc)


# --------------------------------------------------------------------------- #
# cut
# --------------------------------------------------------------------------- #
def test_cut_keeps_only_the_span(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["cut"](EditOp(id="c1", kind="cut", span=(1000, 6000)), pc)
    fc = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "trim=start=1.000:end=6.000" in fc and "concat=n=1" in fc
    assert inverse.params[RESTORE_KEY] == src_before


# --------------------------------------------------------------------------- #
# removeSilence
# --------------------------------------------------------------------------- #
def test_remove_silence_repoints_when_trim_cuts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    op = EditOp(id="s1", kind="removeSilence", span=(0, 12000))

    # Stub trim_clip to "render" a real output file and report a removal.
    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float, list[tuple[float, float]]]:
        Path(out_path).write_bytes(b"\x00trimmed")
        return out_path, 3.0, [(0.0, 6.0), (9.0, 12.0)]

    monkeypatch.setattr(engines_mod._silencetrim, "trim_clip", fake_trim_clip)
    inverse = build_engines(runner=FakeRunner())["removeSilence"](op, pc)
    assert pc.data["video"]["path"] != src_before
    assert Path(pc.data["video"]["path"]).exists()
    assert inverse.params[RESTORE_KEY] == src_before


def test_remove_silence_passthrough_repoints_to_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]

    # Nothing to remove: trim_clip returns the INPUT unchanged (removedSec 0).
    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float, list[tuple[float, float]]]:
        return in_path, 0.0, [(0.0, 12.0)]

    monkeypatch.setattr(engines_mod._silencetrim, "trim_clip", fake_trim_clip)
    inverse = build_engines(runner=FakeRunner())["removeSilence"](
        EditOp(id="s", kind="removeSilence", span=(0, 12000)), pc
    )
    # Re-points to the input (a stable concrete ref) so undo restores it identically.
    assert pc.data["video"]["path"] == src_before
    assert inverse.params[RESTORE_KEY] == src_before


# --------------------------------------------------------------------------- #
# caption (burn the target track's cues)
# --------------------------------------------------------------------------- #
_CUES = [{"index": 1, "start": 1.0, "end": 3.0, "text": "hello"}]


def test_caption_burns_track_cues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path, tracks=[{"id": "cap1", "kind": "hard", "cues": _CUES}])
    src_before = pc.data["video"]["path"]
    op = EditOp(id="cap-op", kind="caption", params={"track": "cap1"})

    inverse = build_engines(runner=runner)["caption"](op, pc)

    # An ASS file was written and burned via the subtitles filter.
    ass = next(pc.manifest_path.parent.glob("*.ass"))
    assert "hello" in ass.read_text(encoding="utf-8")
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert vf.startswith("subtitles=")
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_caption_missing_track_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path, tracks=[{"id": "other", "cues": _CUES}])
    with pytest.raises(DirectorEngineError, match="not found"):
        build_engines(runner=FakeRunner())["caption"](EditOp(id="c", kind="caption", params={"track": "cap1"}), pc)


def test_caption_no_tracks_block_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)  # no "tracks" key at all
    with pytest.raises(DirectorEngineError, match="not found"):
        build_engines(runner=FakeRunner())["caption"](EditOp(id="c", kind="caption", params={"track": "cap1"}), pc)


def test_caption_non_mapping_track_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    # A junk (non-mapping) track entry is skipped; the real track is still found.
    pc = _copy(tmp_path, tracks=["junk", {"id": "cap1", "cues": _CUES}])
    inverse = build_engines(runner=FakeRunner())["caption"](
        EditOp(id="c", kind="caption", params={"track": "cap1"}), pc
    )
    assert inverse.params[RESTORE_KEY]


def test_caption_empty_cues_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path, tracks=[{"id": "cap1", "cues": []}])
    with pytest.raises(DirectorEngineError, match="no cues"):
        build_engines(runner=FakeRunner())["caption"](EditOp(id="c", kind="caption", params={"track": "cap1"}), pc)


# --------------------------------------------------------------------------- #
# dual-mode inverse (undo direction restores, never re-renders)
# --------------------------------------------------------------------------- #
def test_inverse_op_restores_without_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)

    forward_inverse = table["trim"](EditOp(id="t", kind="trim", span=(2000, 5000)), pc)
    rendered = pc.data["video"]["path"]
    assert rendered != original
    calls_after_forward = len(runner.calls)

    # Re-feed the recorded inverse through the SAME-kind engine (rollback/undo).
    re_inverse = table["trim"](forward_inverse, pc)

    assert pc.data["video"]["path"] == original  # restored
    assert len(runner.calls) == calls_after_forward  # NO new render (pure restore)
    assert re_inverse.params[RESTORE_KEY] == rendered  # double-undo is reversible


@pytest.mark.parametrize(
    ("kind", "op_params", "tracks"),
    [
        ("cut", {}, None),
        ("removeSilence", {}, None),
        ("caption", {"track": "cap1"}, [{"id": "cap1", "cues": _CUES}]),
    ],
)
def test_inverse_restores_for_every_wired_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    op_params: dict[str, Any],
    tracks: Any,
) -> None:
    # Each wired adapter's UNDO direction restores the recorded ref WITHOUT a render.
    _fake_probe(monkeypatch)
    runner = FakeRunner()

    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float, list[tuple[float, float]]]:
        Path(out_path).write_bytes(b"\x00trimmed")
        return out_path, 1.0, [(0.0, 6.0), (8.0, 12.0)]

    monkeypatch.setattr(engines_mod._silencetrim, "trim_clip", fake_trim_clip)
    pc = _copy(tmp_path, tracks=tracks)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)
    span = None if kind == "caption" else (1000, 6000)
    forward_inverse = table[kind](EditOp(id="op", kind=kind, span=span, params=op_params), pc)  # type: ignore[arg-type]
    calls_after_forward = len(runner.calls)

    table[kind](forward_inverse, pc)  # the recorded inverse: restore-only

    assert pc.data["video"]["path"] == original
    assert len(runner.calls) == calls_after_forward  # no new render on undo


# --------------------------------------------------------------------------- #
# manifest guards
# --------------------------------------------------------------------------- #
def test_missing_video_block_is_error(tmp_path: Path) -> None:
    pc = _copy(tmp_path, video=None)
    with pytest.raises(DirectorEngineError, match="no 'video' block"):
        build_engines(runner=FakeRunner())["trim"](EditOp(id="t", kind="trim", span=(1000, 2000)), pc)


def test_missing_source_path_is_error(tmp_path: Path) -> None:
    pc = _copy(tmp_path, video={"path": ""})
    with pytest.raises(DirectorEngineError, match="no source path"):
        build_engines(runner=FakeRunner())["trim"](EditOp(id="t", kind="trim", span=(1000, 2000)), pc)


# --------------------------------------------------------------------------- #
# removeFillers (drop the filler span — like trim)
# --------------------------------------------------------------------------- #
def test_remove_fillers_cuts_span_and_records_inverse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    op = EditOp(id="rf1", kind="removeFillers", span=(2000, 4000))

    inverse = build_engines(runner=runner)["removeFillers"](op, pc)

    fc = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    # head [0,2.0] + tail [4.0,12.0] kept -> the filler span [2,4] is excised.
    assert "trim=start=0.000:end=2.000" in fc and "trim=start=4.000:end=12.000" in fc
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_remove_fillers_inverse_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)
    fwd = table["removeFillers"](EditOp(id="rf", kind="removeFillers", span=(1000, 3000)), pc)
    calls = len(runner.calls)
    table["removeFillers"](fwd, pc)
    assert pc.data["video"]["path"] == original
    assert len(runner.calls) == calls  # restore-only, no re-render


# --------------------------------------------------------------------------- #
# reframe (center-crop + scale to aspect)
# --------------------------------------------------------------------------- #
def test_reframe_default_aspect_crops_and_scales(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["reframe"](EditOp(id="r1", kind="reframe", span=(0, 12000)), pc)
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert vf.startswith("crop=ih*9/16:ih,scale=1080:1920")  # default 9:16 -> 1080x1920
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_reframe_custom_aspect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["reframe"](
        EditOp(id="r", kind="reframe", span=(0, 12000), params={"aspect": "1:1"}), pc
    )
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert "crop=ih*1/1:ih" in vf


def test_reframe_blank_aspect_falls_back_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    # A non-str / blank aspect param falls back to the 9:16 default.
    build_engines(runner=runner)["reframe"](
        EditOp(id="r", kind="reframe", span=(0, 12000), params={"aspect": "   "}), pc
    )
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert "crop=ih*9/16:ih" in vf


def test_reframe_non_string_aspect_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["reframe"](EditOp(id="r", kind="reframe", span=(0, 12000), params={"aspect": 169}), pc)
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert "crop=ih*9/16:ih" in vf


@pytest.mark.parametrize(
    ("aspect", "match"),
    [
        ("9", "must be 'W:H'"),
        ("a:b", "two integers"),
        ("0:16", "must be positive"),
    ],
)
def test_reframe_bad_aspect_is_error(aspect: str, match: str) -> None:
    with pytest.raises(DirectorEngineError, match=match):
        engines_mod.build_reframe_argv("in.mp4", "out.mp4", aspect)


# --------------------------------------------------------------------------- #
# zoomPan (Ken-Burns push-in)
# --------------------------------------------------------------------------- #
def _fake_dims(monkeypatch: pytest.MonkeyPatch, value: tuple[int, int] = (320, 240)) -> None:
    monkeypatch.setattr(engines_mod._shorts, "probe_dims", lambda *_a, **_k: value)


def test_zoom_pan_renders_zoompan_filter_preserving_dims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    _fake_dims(monkeypatch, (1080, 1920))
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["zoomPan"](EditOp(id="z1", kind="zoomPan", span=(0, 12000)), pc)
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert vf.startswith("zoompan=z=min(1.0+0.5*on/")
    assert ":s=1080x1920" in vf  # source dims PINNED (no silent 1280x720 rescale)
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_zoom_pan_omits_size_when_probe_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A failed dims probe ((0, 0)) omits s= rather than emitting s=0x0.
    _fake_probe(monkeypatch)
    _fake_dims(monkeypatch, (0, 0))
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["zoomPan"](EditOp(id="z", kind="zoomPan", span=(0, 12000)), pc)
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert ":s=" not in vf


def test_zoom_pan_zero_duration_clamps_frames() -> None:
    # total_sec 0 -> frames clamps to >=1 so the expression never divides by zero.
    argv = engines_mod.build_zoompan_argv("in.mp4", "out.mp4", total_sec=0.0)
    vf = argv[argv.index("-vf") + 1]
    assert "on/1\\,1.5" in vf
    assert ":s=" not in vf  # default dims (0, 0) -> no s=


# --------------------------------------------------------------------------- #
# retime (setpts + atempo)
# --------------------------------------------------------------------------- #
def test_retime_speeds_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["retime"](
        EditOp(id="rt1", kind="retime", span=(0, 12000), params={"factor": 2.0}), pc
    )
    fg = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
    assert "setpts=0.500000*PTS" in fg and "atempo=2.0" in fg
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_retime_no_op_factor_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="no-op"):
        build_engines(runner=FakeRunner())["retime"](
            EditOp(id="rt", kind="retime", span=(0, 12000), params={"factor": 1.0}), pc
        )


def test_retime_non_positive_factor_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="no-op"):
        build_engines(runner=FakeRunner())["retime"](
            EditOp(id="rt", kind="retime", span=(0, 12000), params={"factor": 0.0}), pc
        )


def test_retime_non_numeric_factor_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="numeric"):
        build_engines(runner=FakeRunner())["retime"](
            EditOp(id="rt", kind="retime", span=(0, 12000), params={"factor": "fast"}), pc
        )


def test_atempo_chain_speed_up_beyond_two() -> None:
    # 5x -> 2.0, 2.0, then the 1.25 remainder.
    stages = engines_mod._atempo_chain(5.0)
    assert stages[:2] == ["2.0", "2.0"]
    assert abs(float(stages[-1]) - 1.25) < 1e-6


def test_atempo_chain_slow_down_below_half() -> None:
    # 0.25x -> 0.5, then a 0.5 remainder.
    stages = engines_mod._atempo_chain(0.25)
    assert stages[0] == "0.5"
    assert abs(float(stages[-1]) - 0.5) < 1e-6


# --------------------------------------------------------------------------- #
# overlayText / lowerThird (drawtext)
# --------------------------------------------------------------------------- #
def test_overlay_text_draws_centered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["overlayText"](
        EditOp(id="o1", kind="overlayText", span=(0, 12000), params={"text": "Hi"}), pc
    )
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert vf.startswith("drawtext=text='Hi'") and "box=1" not in vf  # centered, no box
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_lower_third_draws_boxed_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    build_engines(runner=runner)["lowerThird"](
        EditOp(id="l1", kind="lowerThird", span=(0, 12000), params={"text": "Jane Doe"}), pc
    )
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert "box=1" in vf and "y=h-h/6" in vf  # lower band over a box


@pytest.mark.parametrize("kind", ["overlayText", "lowerThird"])
def test_drawtext_missing_text_is_error(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="non-empty"):
        build_engines(runner=FakeRunner())[kind](EditOp(id="x", kind=kind, span=(0, 12000)), pc)  # type: ignore[arg-type]


def test_drawtext_blank_text_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path)
    with pytest.raises(DirectorEngineError, match="non-empty"):
        build_engines(runner=FakeRunner())["overlayText"](
            EditOp(id="x", kind="overlayText", span=(0, 12000), params={"text": "   "}), pc
        )


def test_escape_drawtext_handles_special_chars() -> None:
    # backslash, colon, percent, quote, and newline are all neutralised.
    out = engines_mod._escape_drawtext("a\\b:c 50%'q\nx")
    assert out == "a\\\\b\\:c 50\\%\\'q x"


# --------------------------------------------------------------------------- #
# translateCaption (re-burn the translated track's cues)
# --------------------------------------------------------------------------- #
def test_translate_caption_burns_translated_cues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    translated = [{"index": 1, "start": 1.0, "end": 3.0, "text": "bonjour"}]
    pc = _copy(tmp_path, tracks=[{"id": "fr", "lang": "fr", "cues": translated}])
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["translateCaption"](
        EditOp(id="tc1", kind="translateCaption", params={"track": "fr"}), pc
    )
    ass = next(pc.manifest_path.parent.glob("*.ass"))
    assert "bonjour" in ass.read_text(encoding="utf-8")  # the TRANSLATED text is burned
    vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
    assert vf.startswith("subtitles=")
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_translate_caption_missing_track_is_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    pc = _copy(tmp_path, tracks=[{"id": "other", "cues": _CUES}])
    with pytest.raises(DirectorEngineError, match="not found"):
        build_engines(runner=FakeRunner())["translateCaption"](
            EditOp(id="tc", kind="translateCaption", params={"track": "fr"}), pc
        )


# --------------------------------------------------------------------------- #
# export (re-encode/mux passthrough)
# --------------------------------------------------------------------------- #
def test_export_re_encodes_and_records_inverse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]
    inverse = build_engines(runner=runner)["export"](EditOp(id="ex1", kind="export"), pc)
    argv = runner.calls[0]
    assert "libx264" in argv and "aac" in argv  # a real re-encode
    assert pc.data["video"]["path"] != src_before
    assert inverse.params[RESTORE_KEY] == src_before


def test_export_inverse_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_probe(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)
    fwd = table["export"](EditOp(id="ex", kind="export"), pc)
    calls = len(runner.calls)
    table["export"](fwd, pc)
    assert pc.data["video"]["path"] == original
    assert len(runner.calls) == calls


# --------------------------------------------------------------------------- #
# dual-mode inverse for the new geometry/timing/overlay ops
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("kind", "op_params"),
    [
        ("reframe", {"aspect": "9:16"}),
        ("zoomPan", {}),
        ("retime", {"factor": 2.0}),
        ("overlayText", {"text": "hi"}),
        ("lowerThird", {"text": "hi"}),
    ],
)
def test_inverse_restores_for_new_render_ops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, op_params: dict[str, Any]
) -> None:
    _fake_probe(monkeypatch)
    _fake_dims(monkeypatch)
    runner = FakeRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)
    fwd = table[kind](EditOp(id="op", kind=kind, span=(0, 12000), params=op_params), pc)  # type: ignore[arg-type]
    calls = len(runner.calls)
    table[kind](fwd, pc)
    assert pc.data["video"]["path"] == original
    assert len(runner.calls) == calls  # restore-only on undo
