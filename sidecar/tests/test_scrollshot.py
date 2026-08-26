from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from media_studio.features import scrollshot as ss


class FakeJob:
    def __init__(self, cancelled: bool = False, cancel_after: int | None = None) -> None:
        self.cancelled = cancelled
        self.cancel_after = cancel_after
        self.calls = 0
        self.progress_updates: list[tuple[float, str]] = []

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("cancelled")

    def progress(self, pct: float, message: str = "") -> None:
        self.calls += 1
        self.progress_updates.append((pct, message))
        if self.cancel_after is not None and self.calls >= self.cancel_after:
            self.cancelled = True


def frame(index: int, path: Path | str, image: Any = None, *, width: int = 100, height: int = 60) -> ss.SampledFrame:
    return ss.SampledFrame(
        index=index,
        source_index=index * 10,
        path=str(path),
        image=image if image is not None else f"img-{index}",
        width=width,
        height=height,
    )


def obs(frame_index: int, text: str, top: int, confidence: float = 90.0) -> ss.OcrObservation:
    return ss.OcrObservation(
        frame_index=frame_index,
        text=text,
        top=top,
        left=0,
        width=10,
        height=10,
        confidence=confidence,
    )


def test_escape_markdown_text_neutralizes_html_and_markdown_tokens() -> None:
    escaped = ss.escape_markdown_text("<script>alert(1)</script> [x]")
    assert "&lt;script&gt;alert\\(1\\)&lt;/script&gt;" in escaped
    assert "\\[x\\]" in escaped
    assert ss.escape_code_value("a`b") == "a\\`b"
    assert ss.normalize_text("  Alpha   Beta ") == "alpha beta"


def test_load_config_defaults_and_invalid_modes() -> None:
    cfg = ss.load_config(source_path="C:/tmp/demo.mp4", title=None, language="", assurance=None)
    assert cfg.title == "demo"
    assert cfg.language == "eng"
    assert cfg.assurance == "strict"
    with pytest.raises(ss.ScrollshotError, match="unsupported assurance"):
        ss.load_config(source_path="C:/tmp/demo.mp4", title="x", language="eng", assurance="loud")
    assert str(ss.ScrollshotDependencyError("ocr", "missing")).startswith("scrollshot ocr dependency:")


def test_apply_masks_handles_chrome_and_cursor_paths() -> None:
    calls: list[tuple[tuple[int, int], tuple[int, int]]] = []

    class Cv2:
        @staticmethod
        def rectangle(image: Any, pt1: tuple[int, int], pt2: tuple[int, int], color: Any, thickness: int) -> Any:
            calls.append((pt1, pt2))
            return image

    assert ss.apply_masks("image", 8, ((1, 2, 3, 4),), Cv2) == "image"
    assert calls == [((0, 0), (99999, 8)), ((1, 2), (4, 6))]
    calls.clear()
    ss.apply_masks("image", 0, (), Cv2)
    assert calls == []


def test_compose_markdown_lines_records_conflicts_and_preserves_order() -> None:
    lines, conflicts = ss.compose_markdown_lines(
        [
            obs(0, "Alpha", 10, 50.0),
            obs(1, "Alpha", 11, 80.0),
            obs(1, "Alpba", 12, 60.0),
            obs(2, "Beta", 55, 70.0),
        ],
        positions=(0, 10, 20),
    )
    assert [item.text for item in lines] == ["Alpha", "Beta"]
    assert conflicts[0].chosen_text == "Alpha"
    assert conflicts[0].alternate_texts == ("Alpba",)
    assert obs(0, "Alpha", 10).absolute_top == 10


def test_render_markdown_includes_issues_and_conflicts() -> None:
    rendered = ss.render_markdown(
        config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
        source_path=r"C:\clips\demo.mp4",
        bundle_id="demo-1",
        coverage_verdict="incomplete",
        issues=["gap after frame 0"],
        lines=[ss.MarkdownLine(text="Alpha", absolute_top=10, source_frames=(0,), confidence=50.0)],
        conflicts=[ss.ConflictRecord(absolute_top=10, chosen_text="Alpha", alternate_texts=("Alpba",), source_frames=(0, 1))],
    )
    assert "- Coverage notes: gap after frame 0" in rendered
    assert "- Alpha" in rendered
    assert "OCR Conflicts" in rendered
    empty_render = ss.render_markdown(
        config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
        source_path="x.mp4",
        bundle_id="demo-2",
        coverage_verdict="complete",
        issues=[],
        lines=[],
        conflicts=[],
    )
    assert "No OCR text extracted." in empty_render


def test_solve_pose_graph_accepts_neighbor_skip_and_revisit_edges() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", max_skip=1)
    pose = ss.solve_pose_graph(
        4,
        100,
        [
            ss.EdgeProposal(0, 1, 40, 2.0, (ss.EdgeCue("template", 39, 1.0), ss.EdgeCue("phase", 41, 1.0))),
            ss.EdgeProposal(0, 1, 99, 1.4, (ss.EdgeCue("template", 99, 0.7), ss.EdgeCue("phase", 99, 0.7))),
            ss.EdgeProposal(1, 2, 35, 2.0, (ss.EdgeCue("template", 35, 1.0), ss.EdgeCue("phase", 35, 1.0))),
            ss.EdgeProposal(2, 3, 30, 2.0, (ss.EdgeCue("template", 29, 1.0), ss.EdgeCue("phase", 31, 1.0))),
            ss.EdgeProposal(0, 2, 75, 2.0, (ss.EdgeCue("template", 74, 1.0), ss.EdgeCue("phase", 76, 1.0))),
            ss.EdgeProposal(0, 3, 105, 2.0, (ss.EdgeCue("ocr", 105, 2.0), ss.EdgeCue("phase", 106, 1.0))),
        ],
        config,
    )
    assert pose.coverage_verdict == "complete"
    assert pose.positions == (0, 40, 75, 105)
    assert len(pose.accepted_edges) == 3


def test_solve_pose_graph_detects_gaps_reverse_cycles_invalid_and_weak_edges() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", coverage_gap_px=0)
    pose = ss.solve_pose_graph(
        3,
        40,
        [
            ss.EdgeProposal(0, 1, 100, 2.0, (ss.EdgeCue("template", 100, 1.0), ss.EdgeCue("phase", 100, 1.0))),
            ss.EdgeProposal(1, 2, 10, 1.0, (ss.EdgeCue("template", 10, 1.0),)),
        ],
        config,
    )
    assert pose.coverage_verdict == "incomplete"
    assert "coverage gap from 40 to 100" in pose.issues
    assert "coverage gap: missing frames 2" in pose.issues
    assert len(pose.rejected_edges) == 1
    weak_skip = ss.solve_pose_graph(
        3,
        240,
        [
            ss.EdgeProposal(0, 1, 80, 3.0, (ss.EdgeCue("template", 80, 1.0), ss.EdgeCue("phase", 80, 1.0), ss.EdgeCue("ocr", 80, 1.0))),
            ss.EdgeProposal(0, 2, 120, 3.4, (ss.EdgeCue("template", 120, 1.0), ss.EdgeCue("phase", 40, 0.4), ss.EdgeCue("ocr", 120, 2.0))),
        ],
        ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
    )
    assert weak_skip.coverage_verdict == "incomplete"
    assert any("coverage missing frames 2" in issue for issue in weak_skip.issues)
    assert any(edge.src == 0 and edge.dst == 2 for edge in weak_skip.rejected_edges)
    cycle = ss.solve_pose_graph(
        3,
        40,
        [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(1, 2, 100, 2.0, (ss.EdgeCue("template", 100, 1.0), ss.EdgeCue("phase", 100, 1.0))),
            ss.EdgeProposal(
                0,
                2,
                80,
                5.0,
                (ss.EdgeCue("template", 80, 1.0), ss.EdgeCue("phase", 80, 1.0), ss.EdgeCue("ocr", 80, 3.0)),
            ),
            ss.EdgeProposal(-1, 2, 5, 2.0, (ss.EdgeCue("template", 5, 1.0), ss.EdgeCue("phase", 5, 1.0))),
        ],
        config,
    )
    assert not any("cycle mismatch" in issue for issue in cycle.issues)
    assert any(edge.src == 1 and edge.dst == 2 for edge in cycle.rejected_edges)
    with pytest.raises(ss.ScrollshotError, match="frame_count"):
        ss.solve_pose_graph(0, 10, [], config)
    with pytest.raises(ss.ScrollshotError, match="frame_height"):
        ss.solve_pose_graph(1, 0, [], config)


def test_text_overlap_delta_covers_none_and_counted_paths() -> None:
    assert ss._text_overlap_delta([], [obs(0, "Alpha", 1)]) is None
    assert ss._text_overlap_delta([obs(0, "I", 10)], [obs(1, "I", 2)]) is None
    assert ss._text_overlap_delta([obs(0, "Alpha", 10, 39.9)], [obs(1, "Alpha", 2, 80.0)]) is None
    assert ss._text_overlap_delta([obs(0, "Alpha", 10, 80.0)], [obs(1, "Alpha", 2, 39.9)]) is None
    cue = ss._text_overlap_delta(
        [obs(0, "Alpha", 10, 80.0), obs(0, "Beta", 20, 80.0)],
        [obs(1, "Alpha", 2, 80.0), obs(1, "Beta", 12, 80.0)],
    )
    assert cue == ss.EdgeCue(name="ocr", delta=8, confidence=2.0)
    assert ss._text_overlap_delta([obs(0, "Alpha", 10, 80.0)], [obs(1, "Alpha", 2, 80.0), obs(1, "Alpha", 2, 80.0)]) is None
    assert (
        ss._text_overlap_delta(
        [obs(0, "Alpha", 20, 50), obs(0, "Alpha", 10, 90), obs(0, "Alpha", 30, 80)],
        [obs(1, "Alpha", 2, 90)],
        )
        is None
    )
    assert ss._text_overlap_delta([obs(0, "Alpha", 10)], [obs(1, "Beta", 2)]) is None
    reverse = ss._text_overlap_delta([obs(0, "Alpha", 2)], [obs(1, "Alpha", 10)])
    assert reverse == ss.EdgeCue(name="ocr", delta=-8, confidence=1.0)


def test_cluster_cues_and_gray_coercion_cover_empty_and_passthrough_paths() -> None:
    delta, group = ss._cluster_cues((), 4)
    assert delta == 0
    assert group == ()
    delta, group = ss._cluster_cues((ss.EdgeCue("template", 10, 0.0),), 3)
    assert delta == 10
    assert group == ()
    delta, group = ss._cluster_cues(
        (
            ss.EdgeCue("template", 10, 0.7),
            ss.EdgeCue("phase", 12, 0.5),
            ss.EdgeCue("ocr", -20, 2.0),
        ),
        3,
    )
    assert delta == 11
    assert tuple(item.name for item in group) == ("template", "phase")
    namespace_image = SimpleNamespace(shape=(40, 30, 3))
    assert ss._coerce_gray_float32(namespace_image, object()) is namespace_image
    rgb = np.zeros((4, 3, 3), dtype=np.uint8)
    gray = ss._coerce_gray_float32(rgb, object())
    assert gray.shape == (4, 3)
    assert gray.dtype == np.float32
    mono = np.zeros((4, 3), dtype=np.uint8)
    mono_out = ss._coerce_gray_float32(mono, object())
    assert mono_out.shape == (4, 3)
    assert mono_out.dtype == np.float32


def test_detect_fixed_top_has_both_state_and_dependency_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ss._detect_fixed_top([frame(0, "one.png")], configured=3) == 3
    mismatched = [
        frame(0, "a.png", image=np.zeros((30, 10, 3), dtype=np.uint8), width=10, height=30),
        frame(1, "b.png", image=np.zeros((29, 10, 3), dtype=np.uint8), width=10, height=29),
    ]
    assert ss._detect_fixed_top(mismatched, configured=2) == 2
    faint = [
        frame(0, "a.png", image=np.zeros((30, 10, 3), dtype=np.float32), width=10, height=30),
        frame(1, "b.png", image=np.full((30, 10, 3), 0.5, dtype=np.float32), width=10, height=30),
    ]
    assert ss._detect_fixed_top(faint) == 0
    moving = np.zeros((30, 10, 3), dtype=np.uint8)
    moving[6:] = 30
    detected = [
        frame(0, "a.png", image=np.zeros_like(moving), width=10, height=30),
        frame(1, "b.png", image=moving, width=10, height=30),
        frame(2, "c.png", image=moving.copy(), width=10, height=30),
    ]
    assert ss._detect_fixed_top(detected) == 6
    compressed = np.zeros((30, 10, 3), dtype=np.float32)
    compressed[4] = 2.0
    compressed[5] = 5.0
    compressed[6:] = 30.0
    compressed_detected = [
        frame(0, "compressed-a.png", image=np.zeros_like(compressed), width=10, height=30),
        frame(1, "compressed-b.png", image=compressed, width=10, height=30),
    ]
    assert ss._detect_fixed_top(compressed_detected) == 5
    short = np.zeros((30, 10, 3), dtype=np.uint8)
    short[2:] = 30
    assert ss._detect_fixed_top([detected[0], frame(1, "short.png", image=short, width=10, height=30)]) == 0
    tall = np.zeros((90, 10, 3), dtype=np.uint8)
    tall[30:] = 30
    assert (
        ss._detect_fixed_top(
            [
                frame(0, "tall-a.png", image=np.zeros_like(tall), width=10, height=90),
                frame(1, "tall-b.png", image=tall, width=10, height=90),
            ]
        )
        == 30
    )

    import builtins

    real_import = builtins.__import__

    def no_numpy(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if name.startswith("numpy"):
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "numpy", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_numpy)
    assert ss._detect_fixed_top(detected, configured=4) == 4


def test_bottom_strip_delta_handles_zero_height_and_empty_templates() -> None:
    class FakeCv2:
        TM_CCOEFF_NORMED = 1

        @staticmethod
        def matchTemplate(left: Any, right: Any, mode: int) -> Any:
            return np.zeros((1, 1), dtype=np.float32)

        @staticmethod
        def minMaxLoc(result: Any) -> tuple[float, float, tuple[int, int], tuple[int, int]]:
            return 0.0, 1.0, (0, 0), (0, 0)

    assert ss._bottom_strip_delta(np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32), FakeCv2) is None
    assert ss._bottom_strip_delta(np.zeros((10, 0), dtype=np.float32), np.zeros((10, 0), dtype=np.float32), FakeCv2) is None


def test_solve_pose_graph_prefers_stronger_duplicate_pair() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    pose = ss.solve_pose_graph(
        2,
        40,
        [
            ss.EdgeProposal(0, 1, 5, 1.0, (ss.EdgeCue("template", 5, 1.0), ss.EdgeCue("phase", 5, 0.1))),
            ss.EdgeProposal(0, 1, 15, 5.0, (ss.EdgeCue("template", 15, 2.0), ss.EdgeCue("phase", 15, 3.0))),
        ],
        config,
    )
    assert pose.positions == (0, 15)
    assert len(pose.accepted_edges) == 1
    weaker_second = ss.solve_pose_graph(
        2,
        40,
        [
            ss.EdgeProposal(0, 1, 15, 5.0, (ss.EdgeCue("template", 15, 2.0), ss.EdgeCue("phase", 15, 3.0))),
            ss.EdgeProposal(0, 1, 5, 1.0, (ss.EdgeCue("template", 5, 1.0), ss.EdgeCue("phase", 5, 0.1))),
        ],
        config,
    )
    assert weaker_second.positions == (0, 15)


def test_solve_pose_graph_skips_cycle_checks_for_unplaced_components() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    pose = ss.solve_pose_graph(
        4,
        40,
        [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(2, 3, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
        ],
        config,
    )
    assert pose.coverage_verdict == "incomplete"
    assert "coverage gap: missing frames 2, 3" in pose.issues


def test_solve_pose_graph_ignores_long_revisit_cycle_checks() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    pose = ss.solve_pose_graph(
        5,
        40,
        [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(1, 2, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(2, 3, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(3, 4, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(0, 4, 999, 0.2, (ss.EdgeCue("template", 999, 0.1), ss.EdgeCue("phase", 999, 0.1))),
        ],
        config,
    )
    assert pose.coverage_verdict == "complete"
    assert not any("cycle mismatch" in issue for issue in pose.issues)


def test_solve_pose_graph_keeps_consistent_long_revisit_edges() -> None:
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", max_skip=1)
    pose = ss.solve_pose_graph(
        5,
        40,
        [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(1, 2, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(2, 3, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(3, 4, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(0, 4, 40, 2.0, (ss.EdgeCue("template", 40, 1.0), ss.EdgeCue("phase", 40, 1.0))),
        ],
        config,
    )
    assert pose.coverage_verdict == "complete"
    assert not any(edge.src == 0 and edge.dst == 4 for edge in pose.rejected_edges)


def test_verify_manifest_detects_mutated_output(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "scrollshot.md").write_text("hello", encoding="utf-8")
    (out / "long-screenshot.png").write_bytes(b"png")
    (out / "observations.json").write_text("[]", encoding="utf-8")
    (out / "conflicts.json").write_text("[]", encoding="utf-8")
    manifest_path = out / "manifest.json"
    manifest = {
        "source": {"path": str(source)},
        "files": {
            "markdown": "scrollshot.md",
            "image": "long-screenshot.png",
            "observations": "observations.json",
            "conflicts": "conflicts.json",
            "manifest": "manifest.json",
        },
        "hashes": {
            "source": ss.sha256_file(source),
            "markdown": ss.sha256_file(out / "scrollshot.md"),
            "image": ss.sha256_file(out / "long-screenshot.png"),
            "observations": ss.sha256_file(out / "observations.json"),
            "conflicts": ss.sha256_file(out / "conflicts.json"),
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (out / "scrollshot.md").write_text("tampered", encoding="utf-8")
    assert ss.verify_manifest(manifest_path) == ["markdown"]
    source.write_bytes(b"changed")
    assert ss.verify_manifest(manifest_path) == ["markdown", "source"]


def test_exporter_success_writes_atomic_bundle_and_verifies_hashes(tmp_path: Path) -> None:
    source = tmp_path / "scroll.mp4"
    source.write_bytes(b"source")

    def sampler(video_path: str, frames_dir: str, config: ss.ScrollshotConfig) -> list[ss.SampledFrame]:
        frame_dir = Path(frames_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(3):
            path = frame_dir / f"frame_{index}.png"
            path.write_bytes(f"frame-{index}".encode())
            frames.append(frame(index, path))
        return frames

    def ocr_reader(frames: list[ss.SampledFrame], config: ss.ScrollshotConfig) -> list[ss.OcrObservation]:
        return [obs(0, "Alpha", 0), obs(1, "Alpha", 1), obs(2, "Beta", 40)]

    def edge_finder(frames: list[ss.SampledFrame], observations: list[ss.OcrObservation], config: ss.ScrollshotConfig) -> list[ss.EdgeProposal]:
        return [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0))),
            ss.EdgeProposal(1, 2, 20, 2.0, (ss.EdgeCue("template", 20, 1.0), ss.EdgeCue("phase", 20, 1.0))),
        ]

    def composer(frames: list[ss.SampledFrame], positions: tuple[int, ...], out_path: str) -> str:
        Path(out_path).write_bytes(b"png")
        return out_path

    exporter = ss.ScrollshotExporter(
        out_root=tmp_path / "exports",
        sampler=sampler,
        ocr_reader=ocr_reader,
        edge_finder=edge_finder,
        composer=composer,
        token_factory=lambda: "bundle-1",
    )
    stale_stage = tmp_path / "exports" / ".scroll-bundle-1.tmp"
    stale_stage.mkdir(parents=True, exist_ok=True)
    (stale_stage / "stale.txt").write_text("stale", encoding="utf-8")
    bundle = exporter.export(
        source_path=str(source),
        config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="strict"),
        job_ctx=FakeJob(),
    )
    manifest = json.loads(Path(bundle.manifest_path).read_text(encoding="utf-8"))
    assert Path(bundle.bundle_dir).is_dir()
    assert manifest["coverage"]["verdict"] == "complete"
    assert bundle.markdown_sha256 == manifest["hashes"]["markdown"]
    assert bundle.image_sha256 == manifest["hashes"]["image"]
    assert bundle.source_sha256 == manifest["hashes"]["source"]
    assert bundle.image_path.endswith("long-screenshot.png")


def test_exporter_respects_assurance_precancel_midcancel_and_rollback(tmp_path: Path) -> None:
    source = tmp_path / "scroll.mp4"
    source.write_bytes(b"source")

    def sampler(video_path: str, frames_dir: str, config: ss.ScrollshotConfig) -> list[ss.SampledFrame]:
        frame_dir = Path(frames_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        path = frame_dir / "frame.png"
        path.write_bytes(b"frame")
        return [frame(0, path), frame(1, path)]

    weak_edges = [ss.EdgeProposal(0, 1, 120, 1.0, (ss.EdgeCue("template", 120, 1.0),))]

    exporter = ss.ScrollshotExporter(
        out_root=tmp_path / "exports",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: weak_edges,
        composer=lambda frames, positions, out_path: (Path(out_path).write_bytes(b"png"), str(out_path))[1],
        token_factory=lambda: "bundle-2",
    )
    with pytest.raises(ss.ScrollshotError, match="coverage"):
        exporter.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="strict"),
            job_ctx=FakeJob(),
        )
    balanced = exporter.export(
        source_path=str(source),
        config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
        job_ctx=FakeJob(),
    )
    assert balanced.coverage_verdict == "incomplete"
    cancel_exporter = ss.ScrollshotExporter(
        out_root=tmp_path / "cancel",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: weak_edges,
        composer=lambda frames, positions, out_path: (Path(out_path).write_bytes(b"png"), str(out_path))[1],
        token_factory=lambda: "bundle-4",
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        cancel_exporter.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(cancelled=True),
        )
    with pytest.raises(RuntimeError, match="cancelled"):
        cancel_exporter.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(cancel_after=2),
        )
    rollback = ss.ScrollshotExporter(
        out_root=tmp_path / "rollback",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: [
            ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0)))
        ],
        composer=lambda frames, positions, out_path: (Path(out_path).write_bytes(b"png"), str(out_path))[1],
        token_factory=lambda: "bundle-3",
        replace_dir=lambda src, dst: (_ for _ in ()).throw(OSError("rename failed")),
    )
    with pytest.raises(OSError, match="rename failed"):
        rollback.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )
    assert not (tmp_path / "rollback" / ".bundle-3.tmp").exists()
    assert not (tmp_path / "rollback" / "bundle-3").exists()


def test_exporter_missing_source_existing_bundle_empty_sampler_and_hash_failures(tmp_path: Path) -> None:
    exporter = ss.ScrollshotExporter(out_root=tmp_path / "exports")
    with pytest.raises(ss.ScrollshotError, match="video not found"):
        exporter.export(
            source_path=str(tmp_path / "missing.mp4"),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )

    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    existing = tmp_path / "exports-existing" / "source-bundle"
    existing.mkdir(parents=True)
    exists_exporter = ss.ScrollshotExporter(out_root=existing.parent, token_factory=lambda: "bundle")
    with pytest.raises(ss.ScrollshotError, match="already exists"):
        exists_exporter.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )

    empty_exporter = ss.ScrollshotExporter(
        out_root=tmp_path / "empty",
        sampler=lambda video_path, frames_dir, config: [],
        token_factory=lambda: "bundle",
    )
    with pytest.raises(ss.ScrollshotError, match="no sampled frames"):
        empty_exporter.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )

    ok_edge = [ss.EdgeProposal(0, 1, 10, 2.0, (ss.EdgeCue("template", 10, 1.0), ss.EdgeCue("phase", 10, 1.0)))]

    def sampler(video_path: str, frames_dir: str, config: ss.ScrollshotConfig) -> list[ss.SampledFrame]:
        frame_dir = Path(frames_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)
        image = frame_dir / "frame.png"
        image.write_bytes(b"frame")
        return [frame(0, image), frame(1, image)]

    hash_fail = ss.ScrollshotExporter(
        out_root=tmp_path / "hash-fail",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: ok_edge,
        composer=lambda frames, positions, out_path: (Path(out_path).write_bytes(b"png"), str(out_path))[1],
        token_factory=lambda: "bundle",
        hasher=lambda path: "same",
    )
    with pytest.raises(ss.ScrollshotError, match="hash mismatch for"):
        hash_fail.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )

    bad_composer = ss.ScrollshotExporter(
        out_root=tmp_path / "bad-composer",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: ok_edge,
        composer=lambda frames, positions, out_path: 5,
        token_factory=lambda: "bundle",
    )
    with pytest.raises(ss.ScrollshotError, match="non-path"):
        bad_composer.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )

    def mutate_after_publish(src: str, dst: str) -> None:
        os.replace(src, dst)
        Path(dst, "scrollshot.md").write_text("mutated", encoding="utf-8")

    drift = ss.ScrollshotExporter(
        out_root=tmp_path / "drift",
        sampler=sampler,
        ocr_reader=lambda frames, config: [],
        edge_finder=lambda frames, observations, config: ok_edge,
        composer=lambda frames, positions, out_path: (Path(out_path).write_bytes(b"png"), str(out_path))[1],
        token_factory=lambda: "bundle",
        replace_dir=mutate_after_publish,
    )
    with pytest.raises(ss.ScrollshotError, match="after publish"):
        drift.export(
            source_path=str(source),
            config=ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced"),
            job_ctx=FakeJob(),
        )


def test_default_frame_sampler_and_ocr_reader_and_edge_finder_and_composer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_capture_frames = [
        np.zeros((40, 30, 3), dtype=np.uint8),
        np.zeros((40, 30, 3), dtype=np.uint8),
        np.zeros((40, 30, 3), dtype=np.uint8),
        np.zeros((40, 30, 3), dtype=np.uint8),
        np.zeros((40, 30, 3), dtype=np.uint8),
    ]
    written: list[str] = []

    class FakeCapture:
        def __init__(self, path: str) -> None:
            self.path = path
            self.items = iter(fake_capture_frames)

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            try:
                return True, next(self.items)
            except StopIteration:
                return False, None

        def release(self) -> None:
            return None

    class FakeCv2:
        TM_CCOEFF_NORMED = 1
        COLOR_BGR2GRAY = 2

        @staticmethod
        def VideoCapture(path: str) -> FakeCapture:
            return FakeCapture(path)

        @staticmethod
        def imwrite(path: str, image: Any) -> bool:
            Path(path).write_bytes(b"frame")
            written.append(path)
            return True

        @staticmethod
        def rectangle(image: Any, pt1: Any, pt2: Any, color: Any, thickness: int) -> Any:
            return image

        @staticmethod
        def cvtColor(image: Any, code: int) -> Any:
            return image[:, :, 0]

        @staticmethod
        def matchTemplate(left: Any, right: Any, mode: int) -> Any:
            return np.zeros((3, 3), dtype=np.float32)

        @staticmethod
        def minMaxLoc(result: Any) -> tuple[float, float, tuple[int, int], tuple[int, int]]:
            return 0.0, 0.9, (0, 0), (0, 10)

        @staticmethod
        def phaseCorrelate(left: Any, right: Any) -> tuple[tuple[float, float], float]:
            return (0.0, -12.0), 0.8

    def fake_run(argv: list[str], capture_output: bool, text: bool, check: bool, timeout: int) -> Any:
        assert argv[-1] == "tsv"
        assert timeout == 60
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(
                [
                    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                    "5\t1\t1\t1\t1\t1\t1\t1\t4\t7\t90\tAlpha",
                    "5\t1\t1\t1\t1\t2\t2\t2\t5\t8\t-1\t",
                    "5\t1\t1\t1\t2\t1\t3\t30\t6\t9\t88\tBeta",
                    "5\t1\t1\t1\t2\t2\t4\t40\t7\t10\tbad\tGamma",
                ]
            ),
            stderr="",
        )

    class FakeImage:
        def __init__(self, path: str) -> None:
            self.path = path
            self.width = 30
            self.height = 40
            self.mode = "RGB"

        def crop(self, box: tuple[int, int, int, int]) -> "FakeImage":
            cropped = FakeImage(f"{self.path}:{box[1]}-{box[3]}")
            cropped.height = box[3] - box[1]
            return cropped

    pasted: list[int] = []

    class FakeCanvas(FakeImage):
        def __init__(self) -> None:
            super().__init__("canvas")

        def paste(self, image: FakeImage, offset: tuple[int, int]) -> None:
            pasted.append(offset[1])

        def save(self, path: str) -> None:
            Path(path).write_bytes(b"png")

    class FakePILImage:
        @staticmethod
        def open(path: str) -> FakeImage:
            return FakeImage(path)

        @staticmethod
        def new(mode: str, size: tuple[int, int]) -> FakeCanvas:
            return FakeCanvas()

    monkeypatch.setitem(sys.modules, "cv2", FakeCv2)
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=FakePILImage))
    monkeypatch.setitem(sys.modules, "PIL.Image", FakePILImage)
    monkeypatch.setattr(ss, "_resolve_tesseract_executable", lambda: "tesseract.exe")
    monkeypatch.setattr(ss.subprocess, "run", fake_run)

    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", sample_every=3, chrome_top_px=4)
    frames = list(ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), config))
    assert [item.index for item in frames] == [0, 1, 2]
    assert frames[-1].source_index == 4
    observations = list(ss.default_ocr_reader(frames, config))
    assert [item.text for item in observations] == ["Beta", "Beta", "Beta"]
    proposals = list(ss.default_edge_finder(frames, observations, config))
    assert proposals[0].cues[0].name == "template"
    assert any(cue.name == "ocr" for cue in proposals[0].cues)
    no_text = ss.default_edge_finder(frames[:2], [], config)
    assert all(all(cue.name != "ocr" for cue in edge.cues) for edge in no_text)
    revisit = ss.default_edge_finder(
        frames,
        [obs(0, "SharedA", 20), obs(0, "SharedB", 40), obs(1, "Middle", 15), obs(2, "SharedA", 5), obs(2, "SharedB", 25)],
        ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", max_skip=0, revisit_min_gap=2),
    )
    assert any(edge.src == 0 and edge.dst == 2 for edge in revisit)
    weak_revisit = ss.default_edge_finder(
        frames,
        [obs(0, "OnlyOnce", 20), obs(2, "OnlyOnce", 5)],
        ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", revisit_min_gap=2),
    )
    assert not any(edge.src == 0 and edge.dst == 2 and len(edge.cues) == 2 for edge in weak_revisit)
    out = ss.default_composer(frames, [0, 10, 20], str(tmp_path / "out.png"))
    assert Path(out).is_file()
    assert pasted == [0, 25, 35]


def test_default_edge_finder_covers_reverse_template_and_phase_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCv2:
        COLOR_BGR2GRAY = 1

        @staticmethod
        def cvtColor(image: Any, code: int) -> Any:
            return image[:, :, 0]

    monkeypatch.setitem(sys.modules, "cv2", FakeCv2)
    frames = [
        frame(0, "a.png", image=np.zeros((20, 20, 3), dtype=np.uint8), width=20, height=20),
        frame(1, "b.png", image=np.zeros((20, 20, 3), dtype=np.uint8), width=20, height=20),
    ]
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    cues = iter(
        [
            None,
            ss.EdgeCue("template", 5, 0.9),
            None,
            None,
        ]
    )
    monkeypatch.setattr(ss, "_bottom_strip_delta", lambda *args: next(cues))
    monkeypatch.setattr(ss, "_phase_delta", lambda *args: ss.EdgeCue("phase", -5, 0.8))
    reverse = ss.default_edge_finder(frames, [], config)
    assert reverse[0].delta == -5
    assert reverse[0].cues[0] == ss.EdgeCue("template", -5, 0.9)
    phase_only = ss.default_edge_finder(frames, [], config)
    assert phase_only[0].cues == (ss.EdgeCue("phase", -5, 0.8),)


def test_default_composer_covers_gap_boundary_and_zero_height_skip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pasted: list[int] = []

    class FakeImage:
        def __init__(self, path: str) -> None:
            self.path = path
            self.width = 30
            self.height = 40
            self.mode = "RGB"

        def crop(self, box: tuple[int, int, int, int]) -> "FakeImage":
            cropped = FakeImage(f"{self.path}:{box[1]}-{box[3]}")
            cropped.height = box[3] - box[1]
            return cropped

    class FakeCanvas(FakeImage):
        def __init__(self) -> None:
            super().__init__("canvas")

        def paste(self, image: FakeImage, offset: tuple[int, int]) -> None:
            pasted.append(offset[1])

        def save(self, path: str) -> None:
            Path(path).write_bytes(b"png")

    class FakePILImage:
        @staticmethod
        def open(path: str) -> FakeImage:
            return FakeImage(path)

        @staticmethod
        def new(mode: str, size: tuple[int, int]) -> FakeCanvas:
            return FakeCanvas()

    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=FakePILImage))
    monkeypatch.setitem(sys.modules, "PIL.Image", FakePILImage)
    frames = [frame(index, tmp_path / f"frame-{index}.png") for index in range(3)]
    for item in frames:
        Path(item.path).write_bytes(b"png")
    ss.default_composer(frames[:2], [0, 50], str(tmp_path / "gap.png"))
    assert pasted == [0, 50]
    pasted.clear()
    ss.default_composer(frames, [0, 0, 0], str(tmp_path / "triple.png"))
    assert pasted == [0, 20]
    pasted.clear()
    monkeypatch.setattr(ss, "_detect_fixed_top", lambda _frames: 4)
    ss.default_composer(frames[:2], [0, 10], str(tmp_path / "header.png"))
    assert pasted == [0, 4, 27]


def test_default_dependency_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if name in {"cv2", "PIL", "PIL.Image"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    with pytest.raises(ss.ScrollshotDependencyError, match="opencv-python"):
        ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), config)
    monkeypatch.setattr(ss, "_resolve_tesseract_executable", lambda: None)
    with pytest.raises(ss.ScrollshotDependencyError, match="Tesseract executable"):
        ss.default_ocr_reader([], config)
    with pytest.raises(ss.ScrollshotDependencyError, match="opencv-python"):
        ss.default_edge_finder([], [], config)
    with pytest.raises(ss.ScrollshotDependencyError, match="Pillow"):
        ss.default_composer([], [], str(tmp_path / "x.png"))


def test_default_ocr_reader_raises_when_tesseract_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    image_path = tmp_path / "frame.png"
    image_path.write_bytes(b"png")
    monkeypatch.setattr(ss, "_resolve_tesseract_executable", lambda: "tesseract.exe")
    monkeypatch.setattr(
        ss.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    with pytest.raises(ss.ScrollshotError, match="tesseract failed"):
        ss.default_ocr_reader([frame(0, image_path)], config)
    monkeypatch.setattr(
        ss.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(ss.subprocess.TimeoutExpired("tesseract", 60)),
    )
    with pytest.raises(ss.ScrollshotError, match="timed out"):
        ss.default_ocr_reader([frame(0, image_path)], config)


def test_resolve_tesseract_executable_prefers_existing_candidate_and_can_fail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"exe")
    monkeypatch.setattr(ss.shutil, "which", lambda name: str(executable) if name == "tesseract" else None)
    assert ss._resolve_tesseract_executable() == str(executable)
    monkeypatch.setattr(ss.shutil, "which", lambda name: None)
    monkeypatch.setattr(ss, "Path", lambda _value: SimpleNamespace(is_file=lambda: False))
    assert ss._resolve_tesseract_executable() is None


def test_default_frame_sampler_open_empty_and_write_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class ClosedCapture:
        def isOpened(self) -> bool:
            return False

        def release(self) -> None:
            return None

    class EmptyCapture(ClosedCapture):
        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            return False, None

    class OneFrameCapture(ClosedCapture):
        def __init__(self) -> None:
            self.used = False

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            if self.used:
                return False, None
            self.used = True
            return True, SimpleNamespace(shape=(20, 20, 3))

    class FailingCv2:
        @staticmethod
        def VideoCapture(path: str) -> Any:
            return ClosedCapture()

        @staticmethod
        def rectangle(image: Any, pt1: Any, pt2: Any, color: Any, thickness: int) -> Any:
            return image

    monkeypatch.setitem(sys.modules, "cv2", FailingCv2)
    config = ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced")
    with pytest.raises(ss.ScrollshotError, match="could not open video"):
        ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), config)

    class EmptyCv2(FailingCv2):
        @staticmethod
        def VideoCapture(path: str) -> Any:
            return EmptyCapture()

    monkeypatch.setitem(sys.modules, "cv2", EmptyCv2)
    with pytest.raises(ss.ScrollshotError, match="non-empty video"):
        ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), config)

    class WriteFailCv2(FailingCv2):
        @staticmethod
        def VideoCapture(path: str) -> Any:
            return OneFrameCapture()

        @staticmethod
        def imwrite(path: str, image: Any) -> bool:
            return False

    monkeypatch.setitem(sys.modules, "cv2", WriteFailCv2)
    with pytest.raises(ss.ScrollshotError, match="could not write frame"):
        ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), config)

    class LastWriteFailCapture:
        def __init__(self) -> None:
            self.items = iter([SimpleNamespace(shape=(20, 20, 3)), SimpleNamespace(shape=(20, 20, 3))])

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            try:
                return True, next(self.items)
            except StopIteration:
                return False, None

        def release(self) -> None:
            return None

    class LastWriteFailCv2(FailingCv2):
        writes = 0

        @staticmethod
        def VideoCapture(path: str) -> Any:
            return LastWriteFailCapture()

        @staticmethod
        def imwrite(path: str, image: Any) -> bool:
            LastWriteFailCv2.writes += 1
            return LastWriteFailCv2.writes == 1

    monkeypatch.setitem(sys.modules, "cv2", LastWriteFailCv2)
    with pytest.raises(ss.ScrollshotError, match="could not write frame"):
        ss.default_frame_sampler("video.mp4", str(tmp_path / "frames"), ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", sample_every=3))


def test_default_frame_sampler_skips_last_append_when_last_frame_was_sampled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Capture:
        def __init__(self) -> None:
            self.items = iter(
                [
                    SimpleNamespace(shape=(20, 20, 3)),
                    SimpleNamespace(shape=(20, 20, 3)),
                    SimpleNamespace(shape=(20, 20, 3)),
                    SimpleNamespace(shape=(20, 20, 3)),
                ]
            )

        def isOpened(self) -> bool:
            return True

        def read(self) -> tuple[bool, Any]:
            try:
                return True, next(self.items)
            except StopIteration:
                return False, None

        def release(self) -> None:
            return None

    class Cv2:
        writes = 0

        @staticmethod
        def VideoCapture(path: str) -> Any:
            return Capture()

        @staticmethod
        def rectangle(image: Any, pt1: Any, pt2: Any, color: Any, thickness: int) -> Any:
            return image

        @staticmethod
        def imwrite(path: str, image: Any) -> bool:
            Cv2.writes += 1
            Path(path).write_bytes(b"frame")
            return True

    monkeypatch.setitem(sys.modules, "cv2", Cv2)
    frames = list(
        ss.default_frame_sampler(
            "video.mp4",
            str(tmp_path / "frames"),
            ss.ScrollshotConfig(title="Demo", language="eng", assurance="balanced", sample_every=3),
        )
    )
    assert [item.source_index for item in frames] == [0, 3]
    assert Cv2.writes == 2
