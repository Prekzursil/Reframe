"""Unit tests for the ``stitchPanorama`` frame-stitch engine (WU-stitch, GAP-3a).

PURE-logic only: NO OpenCV / image decode / network. The real pixel-align and
encode are SEAMS injected as callables, so the offset-accumulation math and the
artifact assembly are tested to 100% line+branch without ever touching a real
image. Covers (DESIGN §3 step #2, PLAN §WU-stitch):

  * (a) ordered frames -> expected cumulative ``frame_offsets`` + total ``height``
    (the golden offset math — deterministic);
  * (b) a single frame -> a degenerate panorama (no raise);
  * (c) an aligner that fails -> :class:`StitchError` (typed, never leaks raw);
  * the artifact is READ-ONLY (frozen dataclass; the engine never mutates a
    source manifest — it only returns an artifact);
  * the ``stitchPanorama`` op-adapter parses an :class:`EditOp` and dispatches;
  * module PURITY: no Provider/transport/OpenCV import at module scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from media_studio.features.panorama_stitch import (
    PanoramaArtifact,
    StitchError,
    stitch_panorama,
    stitch_panorama_op,
)
from media_studio.models.edit_plan import EditOp

# ---------------------------------------------------------------------------
# Test doubles: a fake aligner (canned per-frame vertical advance) + a fake
# image writer (records the call, returns a path — no real pixels).
# ---------------------------------------------------------------------------


def _aligner_from(advances: list[int]):
    """Return an aligner yielding canned vertical advances for each frame pair.

    ``advances[i]`` is how far frame ``i`` advances past the previous frame's
    origin (the non-overlapping part). The first frame's advance is its own
    starting offset (always 0 for the engine; the aligner is asked per pair).
    """
    calls: list[tuple[str, str]] = []

    def aligner(prev_frame: str, frame: str) -> int:
        calls.append((prev_frame, frame))
        return advances[len(calls) - 1]

    aligner.calls = calls  # type: ignore[attr-defined]
    return aligner


def _writer():
    """Return a fake image writer recording its args and yielding a fixed path."""
    seen: dict[str, object] = {}

    def write(frames, offsets, height):
        seen["frames"] = list(frames)
        seen["offsets"] = list(offsets)
        seen["height"] = height
        return "/artifacts/panorama_abc.png"

    write.seen = seen  # type: ignore[attr-defined]
    return write


# ---------------------------------------------------------------------------
# (a) ordered frames -> cumulative offsets + total height (golden math)
# ---------------------------------------------------------------------------


def test_ordered_frames_accumulate_offsets_and_height():
    frames = ["f0.png", "f1.png", "f2.png"]
    # First frame sits at 0; the aligner returns the advance for each *pair*.
    aligner = _aligner_from([120, 95])
    writer = _writer()

    art = stitch_panorama(frames, frame_height=160, aligner=aligner, writer=writer)

    # Offsets are cumulative: frame0 @ 0, frame1 @ 120, frame2 @ 215.
    assert art.frame_offsets == (0, 120, 215)
    # Total height = last offset + the last frame's full height.
    assert art.height == 215 + 160
    assert art.image_path == "/artifacts/panorama_abc.png"
    # The aligner was asked once per *pair* (n-1 times), in order.
    assert aligner.calls == [("f0.png", "f1.png"), ("f1.png", "f2.png")]
    # The writer received the assembled geometry.
    assert writer.seen["offsets"] == [0, 120, 215]
    assert writer.seen["height"] == art.height


def test_zero_advance_frames_stack_at_same_offset():
    # A degenerate-but-valid run: identical frames advance 0 -> same offset.
    frames = ["a.png", "b.png"]
    art = stitch_panorama(frames, frame_height=100, aligner=_aligner_from([0]), writer=_writer())
    assert art.frame_offsets == (0, 0)
    assert art.height == 100  # 0 + frame_height


# ---------------------------------------------------------------------------
# (b) single frame -> degenerate panorama (no raise)
# ---------------------------------------------------------------------------


def test_single_frame_is_a_degenerate_panorama():
    writer = _writer()
    art = stitch_panorama(["only.png"], frame_height=160, aligner=_aligner_from([]), writer=writer)
    assert art.frame_offsets == (0,)
    assert art.height == 160
    assert art.image_path == "/artifacts/panorama_abc.png"
    # The aligner is never called for a single frame (no pairs).
    assert writer.seen["offsets"] == [0]


# ---------------------------------------------------------------------------
# (c) failure modes -> typed StitchError
# ---------------------------------------------------------------------------


def test_empty_frames_raises_stitch_error():
    with pytest.raises(StitchError, match="at least one frame"):
        stitch_panorama([], frame_height=160, aligner=_aligner_from([]), writer=_writer())


def test_non_positive_frame_height_raises_stitch_error():
    with pytest.raises(StitchError, match="frame_height"):
        stitch_panorama(["f.png"], frame_height=0, aligner=_aligner_from([]), writer=_writer())


def test_aligner_failure_is_wrapped_in_stitch_error():
    def boom(prev_frame: str, frame: str) -> int:
        raise RuntimeError("opencv exploded")

    with pytest.raises(StitchError, match="align"):
        stitch_panorama(["a.png", "b.png"], frame_height=160, aligner=boom, writer=_writer())


def test_negative_advance_from_aligner_raises_stitch_error():
    # A pan can only move forward; a negative advance is a bad align result.
    with pytest.raises(StitchError, match="advance"):
        stitch_panorama(["a.png", "b.png"], frame_height=160, aligner=_aligner_from([-5]), writer=_writer())


def test_writer_failure_is_wrapped_in_stitch_error():
    def boom(frames, offsets, height):
        raise OSError("disk full")

    with pytest.raises(StitchError, match="write"):
        stitch_panorama(["a.png"], frame_height=160, aligner=_aligner_from([]), writer=boom)


# ---------------------------------------------------------------------------
# Artifact is READ-ONLY (frozen) — the engine returns, never mutates a manifest
# ---------------------------------------------------------------------------


def test_artifact_is_frozen_read_only():
    art = stitch_panorama(["a.png"], frame_height=10, aligner=_aligner_from([]), writer=_writer())
    assert isinstance(art, PanoramaArtifact)
    with pytest.raises(AttributeError):
        art.height = 999  # type: ignore[misc]  # frozen dataclass


# ---------------------------------------------------------------------------
# The stitchPanorama op-adapter: parses an EditOp's params and dispatches.
# ---------------------------------------------------------------------------


def test_op_adapter_dispatches_with_params():
    op = EditOp(
        id="op1",
        kind="stitchPanorama",
        span=(0, 4000),
        params={"frames": ["f0.png", "f1.png"], "frameHeight": 160},
    )
    art = stitch_panorama_op(op, aligner=_aligner_from([120]), writer=_writer())
    assert art.frame_offsets == (0, 120)
    assert art.height == 120 + 160


def test_op_adapter_rejects_non_stitch_kind():
    op = EditOp(id="op1", kind="trim", span=(0, 1000))
    with pytest.raises(StitchError, match="stitchPanorama"):
        stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())


def test_op_adapter_rejects_missing_frames():
    op = EditOp(id="op1", kind="stitchPanorama", params={"frameHeight": 160})
    with pytest.raises(StitchError, match="frames"):
        stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())


def test_op_adapter_rejects_non_list_frames():
    op = EditOp(id="op1", kind="stitchPanorama", params={"frames": "nope", "frameHeight": 160})
    with pytest.raises(StitchError, match="frames"):
        stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())


def test_op_adapter_rejects_non_string_frame_entries():
    op = EditOp(id="op1", kind="stitchPanorama", params={"frames": ["ok.png", 5], "frameHeight": 160})
    with pytest.raises(StitchError, match="frames"):
        stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())


def test_op_adapter_rejects_bad_frame_height():
    op = EditOp(id="op1", kind="stitchPanorama", params={"frames": ["a.png"], "frameHeight": "tall"})
    with pytest.raises(StitchError, match="frameHeight"):
        stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())


def test_op_adapter_defaults_frame_height_when_absent():
    op = EditOp(id="op1", kind="stitchPanorama", params={"frames": ["a.png"]})
    art = stitch_panorama_op(op, aligner=_aligner_from([]), writer=_writer())
    # The default frame height is applied; a degenerate single-frame panorama.
    assert art.frame_offsets == (0,)
    assert art.height > 0


# ---------------------------------------------------------------------------
# Purity guard: no Provider/transport/OpenCV import at module scope.
# ---------------------------------------------------------------------------

_BANNED_IMPORT_SUBSTRINGS = ("provider", "httpx", "runner", "ai_job", "ai_cache", "requests", "cv2")


def _module_level_imports(source: str) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(source)
    for node in tree.body:  # module scope only — function-local seam imports are OK
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def test_module_has_no_transport_or_opencv_import_at_module_scope():
    root = Path(__file__).resolve().parents[1]  # sidecar/
    source = (root / "media_studio/features/panorama_stitch.py").read_text(encoding="utf-8")
    for name in _module_level_imports(source):
        lowered = name.lower()
        assert not any(banned in lowered for banned in _BANNED_IMPORT_SUBSTRINGS), (
            f"panorama_stitch.py imports forbidden module at module scope: {name}"
        )
