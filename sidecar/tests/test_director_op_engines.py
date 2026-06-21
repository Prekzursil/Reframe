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
    assert "reframe" in DEFERRED_KINDS  # the host->WSL-bridge op stays deferred


def test_log_deferred_announces_unwired_kinds() -> None:
    seen: list[tuple[Any, ...]] = []

    class _Log:
        def info(self, *args: Any) -> None:
            seen.append(args)

    engines_mod.log_deferred(_Log())
    assert seen and "deferred" in seen[0][0]


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
    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float]:
        Path(out_path).write_bytes(b"\x00trimmed")
        return out_path, 3.0

    monkeypatch.setattr(engines_mod._silencetrim, "trim_clip", fake_trim_clip)
    inverse = build_engines(runner=FakeRunner())["removeSilence"](op, pc)
    assert pc.data["video"]["path"] != src_before
    assert Path(pc.data["video"]["path"]).exists()
    assert inverse.params[RESTORE_KEY] == src_before


def test_remove_silence_passthrough_repoints_to_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]

    # Nothing to remove: trim_clip returns the INPUT unchanged (removedSec 0).
    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float]:
        return in_path, 0.0

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

    def fake_trim_clip(in_path: str, out_path: str, **_k: Any) -> tuple[str, float]:
        Path(out_path).write_bytes(b"\x00trimmed")
        return out_path, 1.0

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
