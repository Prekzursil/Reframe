"""Unit tests for the ``reorder`` director op-engine (v1.5 O-3, SCOPE.md).

``reorder`` was the ONE op kind in ``models/edit_plan.OpKind`` with no engine
ANYWHERE in the tree (``stitchPanorama``/``regenScroll``/``ocrExtractList`` each
already ship a real subsystem module — ``panorama_stitch.py``, ``scroll_regen.py``,
``ocr_list.py`` — they were merely unwired). So a prompt asking to reorder clips
surfaced as a per-op ``failed`` + auto-rollback: the named backend gap blocking
transcript-native editing.

Same discipline as ``test_director_op_engines``: the ONE impure thing — the
ffmpeg subprocess — is the injected ``runner``, faked here so the adapter logic
(param validation, permuted keep list, manifest re-point, recorded inverse,
dual-mode undo, every error branch) is exercised deterministically with NO real
ffmpeg.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.features import director_op_engines as engines_mod
from media_studio.features.director_op_engines import (
    DEFERRED_KINDS,
    WIRED_KINDS,
    DirectorEngineError,
    build_engines,
)
from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp

CLIP_SEC = 12.0

#: Three ordered source segments (ms) the reorder permutes.
SEGMENTS = [[0, 2000], [2000, 5000], [5000, 9000]]


def _copy(tmp_path: Path) -> ProjectCopy:
    """A ProjectCopy whose manifest folder is real (so renders land on disk)."""
    src = tmp_path / "src.mp4"
    src.write_bytes(b"\x00source")
    manifest = tmp_path / ".director-copy" / "project.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    return ProjectCopy(data={"video": {"path": str(src)}}, manifest_path=manifest)


class FakeRunner:
    """A fake ffmpeg runner: stubs the output file (last argv element) + records calls."""

    def __init__(self, *, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []

    def __call__(self, argv: Any, total_sec: float = 0.0, **_k: Any) -> int:
        self.calls.append(list(argv))
        if self.code == 0:
            Path(argv[-1]).write_bytes(b"\x00rendered")
        return self.code


@pytest.fixture(autouse=True)
def _probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines_mod._ffmpeg, "ffprobe_duration", lambda *_a, **_k: CLIP_SEC)


def _op(**params: Any) -> EditOp:
    return EditOp(id="r1", kind="reorder", span=(0, 9000), params=params)


def _filtergraph(runner: FakeRunner) -> str:
    """The -filter_complex value of the last render (carries the keep order)."""
    argv = runner.calls[-1]
    return argv[argv.index("-filter_complex") + 1]


# --------------------------------------------------------------------------- #
# wiring: reorder is a REAL engine now, not a deferred kind
# --------------------------------------------------------------------------- #
def test_reorder_is_wired_and_no_longer_deferred() -> None:
    table = build_engines(runner=FakeRunner())
    assert "reorder" in table
    assert "reorder" in WIRED_KINDS
    assert "reorder" not in DEFERRED_KINDS
    assert "reorder" not in engines_mod.DEFERRED_SUBSYSTEMS


# --------------------------------------------------------------------------- #
# forward render: the keeps are emitted in the PERMUTED order
# --------------------------------------------------------------------------- #
def test_reorder_renders_segments_in_the_permuted_order(tmp_path: Path) -> None:
    runner = FakeRunner()
    pc = _copy(tmp_path)
    src_before = pc.data["video"]["path"]

    inverse = build_engines(runner=runner)["reorder"](_op(segments=SEGMENTS, order=[2, 0, 1]), pc)

    graph = _filtergraph(runner)
    # keep #0 is segment[2] (5.0-9.0s), keep #1 is segment[0], keep #2 is segment[1].
    assert "trim=start=5.000:end=9.000,setpts=PTS-STARTPTS[v0]" in graph
    assert "trim=start=0.000:end=2.000,setpts=PTS-STARTPTS[v1]" in graph
    assert "trim=start=2.000:end=5.000,setpts=PTS-STARTPTS[v2]" in graph
    assert "concat=n=3:v=1:a=1" in graph
    # the COPY was RE-POINTED at the render and the inverse restores the old ref.
    assert pc.data["video"]["path"] != src_before
    assert inverse.kind == "reorder"
    assert inverse.params[engines_mod.RESTORE_KEY] == src_before


def test_reorder_defaults_order_to_the_segment_sequence(tmp_path: Path) -> None:
    # ``order`` omitted -> identity: keep the segments as given (compacting gaps).
    runner = FakeRunner()
    pc = _copy(tmp_path)

    build_engines(runner=runner)["reorder"](_op(segments=[[5000, 9000], [0, 2000]]), pc)

    graph = _filtergraph(runner)
    assert "trim=start=5.000:end=9.000,setpts=PTS-STARTPTS[v0]" in graph
    assert "trim=start=0.000:end=2.000,setpts=PTS-STARTPTS[v1]" in graph


def test_reorder_persists_the_repointed_manifest(tmp_path: Path) -> None:
    pc = _copy(tmp_path)
    build_engines(runner=FakeRunner())["reorder"](_op(segments=SEGMENTS, order=[1, 0, 2]), pc)
    # the ON-DISK manifest references the render (not just the in-memory dict).
    assert pc.data["video"]["path"] in pc.manifest_path.read_text(encoding="utf-8")


def test_reorder_surfaces_an_ffmpeg_failure(tmp_path: Path) -> None:
    with pytest.raises(DirectorEngineError, match="ffmpeg exit 1"):
        build_engines(runner=FakeRunner(code=1))["reorder"](_op(segments=SEGMENTS, order=[1, 0, 2]), _copy(tmp_path))


# --------------------------------------------------------------------------- #
# dual-mode: the recorded inverse RESTORES (never re-renders)
# --------------------------------------------------------------------------- #
def test_reorder_inverse_restores_without_re_rendering(tmp_path: Path) -> None:
    runner = FakeRunner()
    pc = _copy(tmp_path)
    original = pc.data["video"]["path"]
    table = build_engines(runner=runner)

    forward = table["reorder"](_op(segments=SEGMENTS, order=[2, 1, 0]), pc)
    renders = len(runner.calls)
    re_inverse = table["reorder"](forward, pc)

    assert pc.data["video"]["path"] == original
    assert len(runner.calls) == renders  # restore-only: no second render
    # the re-inverse re-applies the reordered render reference (double-undo).
    assert re_inverse.params[engines_mod.RESTORE_KEY] != original


# --------------------------------------------------------------------------- #
# validate-and-reject: a malformed reorder is a typed render error, never a
# silent no-op and never silent content loss
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "params",
    [
        {},  # no segments at all (the golden-plan "order only" shape)
        {"order": [1, 0]},  # order without segments
        {"segments": []},  # empty list
        {"segments": "0,2000"},  # not a list
        {"segments": [[0, 2000], "nope"]},  # entry not a pair
        {"segments": [[0, 2000], [1000]]},  # entry not a 2-tuple
        {"segments": [[0, 2000], ["a", "b"]]},  # bounds not integers
        {"segments": [[0, 2000], [5000, 5000]]},  # empty span (end == start)
        {"segments": [[0, 2000], [9000, 5000]]},  # inverted span
        {"segments": [[-1, 2000]]},  # negative start
    ],
)
def test_reorder_rejects_malformed_segments(tmp_path: Path, params: dict[str, Any]) -> None:
    with pytest.raises(DirectorEngineError, match="segments"):
        build_engines(runner=FakeRunner())["reorder"](_op(**params), _copy(tmp_path))


@pytest.mark.parametrize(
    "order",
    [
        [0, 1],  # too short -> would SILENTLY DROP segment 2
        [0, 1, 2, 0],  # too long
        [0, 0, 1],  # duplicate -> repeats a segment
        [0, 1, 3],  # out of range
        [0, 1, "2"],  # not an integer
        [0, 1, True],  # bool is not a valid index
        "012",  # not a list
    ],
)
def test_reorder_rejects_a_non_permutation_order(tmp_path: Path, order: Any) -> None:
    with pytest.raises(DirectorEngineError, match="order"):
        build_engines(runner=FakeRunner())["reorder"](_op(segments=SEGMENTS, order=order), _copy(tmp_path))
