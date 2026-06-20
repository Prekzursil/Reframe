"""Unit tests for the ``regenScroll`` constant-speed scroll renderer (WU-regen, GAP-3b).

PURE-logic only: NO render-cli / encode / network. The real frame encode is a
SEAM injected as a callable, so the frame-time/position curve computation is
tested to 100% line+branch without ever encoding a clip. Covers (DESIGN §3
step #3, PLAN §WU-regen):

  * (a) ``easing="linear"`` -> UNIFORM per-frame position deltas, i.e. a curve
    whose FIRST DIFFERENCE is constant (zero acceleration) — the falsifiable
    proof this is a fresh constant-speed glide, NOT a speed-ramp (DESIGN §2.2);
  * (b) ``durationMs`` + panorama ``height`` + ``fps`` -> the expected frame
    count and the curve's full travel (last position) lands at the scrollable
    extent (``height`` minus the viewport, never past the end);
  * (c) a non-linear easing is REJECTED in v1 (linear-only, DESIGN §3);
  * (d) a renderer that fails -> :class:`RegenError` (typed, never leaks raw);
  * the durable inverse RESTORES the original span (recorded for WU-apply);
  * the ``regenScroll`` op-adapter parses an :class:`EditOp` and dispatches;
  * the :class:`ClipArtifact` is READ-ONLY (frozen dataclass);
  * module PURITY: no Provider/transport/render import at module scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from media_studio.features.panorama_stitch import PanoramaArtifact
from media_studio.features.scroll_regen import (
    ClipArtifact,
    RegenError,
    regen_scroll,
    regen_scroll_op,
)
from media_studio.models.edit_plan import EditOp

# ---------------------------------------------------------------------------
# Test doubles: a fake renderer that records its call (frame positions, fps,
# clip path) and returns a fixed path — no real pixels are ever encoded.
# ---------------------------------------------------------------------------


def _renderer(path: str = "/artifacts/scroll_xyz.mp4"):
    """Return a fake renderer recording its args and yielding a fixed path."""
    seen: dict[str, object] = {}

    def render(panorama, positions, fps):
        seen["panorama"] = panorama
        seen["positions"] = list(positions)
        seen["fps"] = fps
        return path

    render.seen = seen  # type: ignore[attr-defined]
    return render


def _panorama(height: int = 1000, image_path: str = "/artifacts/pano.png") -> PanoramaArtifact:
    """Build a minimal stitched panorama artifact for the regen to glide over."""
    return PanoramaArtifact(image_path=image_path, height=height, frame_offsets=(0,))


# ---------------------------------------------------------------------------
# (a) linear easing -> constant first-difference (the constant-speed claim)
# ---------------------------------------------------------------------------


def test_linear_easing_has_constant_first_difference():
    # A glide over a 1000px panorama with a 400px viewport => 600px of travel.
    renderer = _renderer()
    art = regen_scroll(
        _panorama(height=1000),
        duration_ms=1000,
        easing="linear",
        fps=5,
        viewport_height=400,
        renderer=renderer,
    )
    positions = list(renderer.seen["positions"])  # type: ignore[arg-type]
    # The first difference (per-frame delta) must be CONSTANT -> zero accel.
    deltas = [b - a for a, b in zip(positions, positions[1:])]  # noqa: B905 - offset-by-one pairing is intentional
    assert len(set(deltas)) == 1, f"non-uniform deltas prove a ramp, not constant speed: {deltas}"
    # Curve starts at the top and ends at the scrollable extent (height-viewport).
    assert positions[0] == pytest.approx(0.0)
    assert positions[-1] == pytest.approx(600.0)
    assert isinstance(art, ClipArtifact)


def test_single_frame_glide_is_degenerate_no_delta():
    # fps*durationSec rounds to a single frame -> one position, no deltas, no raise.
    renderer = _renderer()
    regen_scroll(
        _panorama(height=1000),
        duration_ms=1,  # 0.001s * 5fps -> rounds to 1 frame
        easing="linear",
        fps=5,
        viewport_height=400,
        renderer=renderer,
    )
    positions = list(renderer.seen["positions"])  # type: ignore[arg-type]
    assert positions == [pytest.approx(0.0)]


# ---------------------------------------------------------------------------
# (b) duration + height + fps -> expected frame count + full travel
# ---------------------------------------------------------------------------


def test_frame_count_is_duration_times_fps():
    renderer = _renderer()
    art = regen_scroll(
        _panorama(height=2000),
        duration_ms=2000,  # 2.0s
        easing="linear",
        fps=30,
        viewport_height=500,
        renderer=renderer,
    )
    # 2.0s * 30fps = 60 frames.
    assert art.frame_count == 60
    assert len(renderer.seen["positions"]) == 60  # type: ignore[arg-type]
    assert renderer.seen["fps"] == 30
    # Travel never goes past the scrollable extent (2000 - 500).
    assert list(renderer.seen["positions"])[-1] == pytest.approx(1500.0)  # type: ignore[index]


def test_viewport_taller_than_panorama_pins_at_top():
    # Nothing to scroll: the whole panorama already fits -> all positions at 0.
    renderer = _renderer()
    art = regen_scroll(
        _panorama(height=300),
        duration_ms=1000,
        easing="linear",
        fps=4,
        viewport_height=400,  # taller than the 300px panorama
        renderer=renderer,
    )
    positions = list(renderer.seen["positions"])  # type: ignore[arg-type]
    assert all(p == pytest.approx(0.0) for p in positions)
    assert art.frame_count == 4


def test_artifact_records_clip_metadata():
    renderer = _renderer("/artifacts/clip_42.mp4")
    art = regen_scroll(
        _panorama(height=1000),
        duration_ms=1000,
        easing="linear",
        fps=10,
        viewport_height=400,
        renderer=renderer,
    )
    assert art.clip_path == "/artifacts/clip_42.mp4"
    assert art.duration_ms == 1000
    assert art.fps == 10


# ---------------------------------------------------------------------------
# (c) non-linear easing rejected (linear-only in v1)
# ---------------------------------------------------------------------------


def test_non_linear_easing_is_rejected():
    with pytest.raises(RegenError, match="linear"):
        regen_scroll(
            _panorama(),
            duration_ms=1000,
            easing="easeInOut",
            fps=5,
            viewport_height=400,
            renderer=_renderer(),
        )


# ---------------------------------------------------------------------------
# (d) failure modes -> typed RegenError
# ---------------------------------------------------------------------------


def test_non_positive_duration_raises_regen_error():
    with pytest.raises(RegenError, match="duration"):
        regen_scroll(
            _panorama(),
            duration_ms=0,
            easing="linear",
            fps=5,
            viewport_height=400,
            renderer=_renderer(),
        )


def test_non_positive_fps_raises_regen_error():
    with pytest.raises(RegenError, match="fps"):
        regen_scroll(
            _panorama(),
            duration_ms=1000,
            easing="linear",
            fps=0,
            viewport_height=400,
            renderer=_renderer(),
        )


def test_non_positive_viewport_raises_regen_error():
    with pytest.raises(RegenError, match="viewport"):
        regen_scroll(
            _panorama(),
            duration_ms=1000,
            easing="linear",
            fps=5,
            viewport_height=0,
            renderer=_renderer(),
        )


def test_renderer_failure_is_wrapped_in_regen_error():
    def boom(panorama, positions, fps):
        raise OSError("encode died")

    with pytest.raises(RegenError, match="render"):
        regen_scroll(
            _panorama(),
            duration_ms=1000,
            easing="linear",
            fps=5,
            viewport_height=400,
            renderer=boom,
        )


# ---------------------------------------------------------------------------
# Durable inverse: restores the original span (recorded for WU-apply).
# ---------------------------------------------------------------------------


def test_op_adapter_inverse_restores_original_span():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(1000, 5000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
            "easing": "linear",
            "fps": 5,
            "viewportHeight": 400,
        },
    )
    art, inverse = regen_scroll_op(op, renderer=_renderer())
    assert isinstance(art, ClipArtifact)
    # The recorded inverse restores the ORIGINAL span (durable undo, DESIGN §3).
    assert inverse["kind"] == "restoreSpan"
    assert inverse["span"] == [1000, 5000]


def test_op_adapter_dispatches_curve_params():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
            "easing": "linear",
            "fps": 10,
            "viewportHeight": 400,
        },
    )
    art, _inverse = regen_scroll_op(op, renderer=_renderer())
    assert art.frame_count == 10


# ---------------------------------------------------------------------------
# Op-adapter validation -> typed RegenError.
# ---------------------------------------------------------------------------


def test_op_adapter_rejects_non_regen_kind():
    op = EditOp(id="op1", kind="trim", span=(0, 1000))
    with pytest.raises(RegenError, match="regenScroll"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_missing_span():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=None,
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
        },
    )
    with pytest.raises(RegenError, match="span"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_missing_panorama():
    op = EditOp(id="op1", kind="regenScroll", span=(0, 1000), params={"durationMs": 1000})
    with pytest.raises(RegenError, match="panorama"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_non_mapping_panorama():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={"panorama": "nope", "durationMs": 1000},
    )
    with pytest.raises(RegenError, match="panorama"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_malformed_panorama_fields():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={"panorama": {"imagePath": 5, "height": 1000, "frameOffsets": [0]}, "durationMs": 1000},
    )
    with pytest.raises(RegenError, match="panorama"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_bad_duration_param():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={"panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]}, "durationMs": "long"},
    )
    with pytest.raises(RegenError, match="durationMs"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_defaults_optional_params():
    # easing/fps/viewportHeight default when absent; durationMs is required.
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
        },
    )
    art, _inverse = regen_scroll_op(op, renderer=_renderer())
    assert art.frame_count > 0
    assert art.fps > 0


def test_op_adapter_rejects_bad_easing_param_type():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
            "easing": 5,
        },
    )
    with pytest.raises(RegenError, match="easing"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_bad_fps_param_type():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
            "fps": "fast",
        },
    )
    with pytest.raises(RegenError, match="fps"):
        regen_scroll_op(op, renderer=_renderer())


def test_op_adapter_rejects_bad_viewport_param_type():
    op = EditOp(
        id="op1",
        kind="regenScroll",
        span=(0, 1000),
        params={
            "panorama": {"imagePath": "/p.png", "height": 1000, "frameOffsets": [0]},
            "durationMs": 1000,
            "viewportHeight": "tall",
        },
    )
    with pytest.raises(RegenError, match="viewport"):
        regen_scroll_op(op, renderer=_renderer())


# ---------------------------------------------------------------------------
# ClipArtifact is READ-ONLY (frozen) — the engine returns, never mutates.
# ---------------------------------------------------------------------------


def test_artifact_is_frozen_read_only():
    art = regen_scroll(
        _panorama(),
        duration_ms=1000,
        easing="linear",
        fps=5,
        viewport_height=400,
        renderer=_renderer(),
    )
    assert isinstance(art, ClipArtifact)
    with pytest.raises(AttributeError):
        art.frame_count = 999  # type: ignore[misc]  # frozen dataclass


# ---------------------------------------------------------------------------
# Purity guard: no Provider/transport/render import at module scope.
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


def test_module_has_no_transport_or_render_import_at_module_scope():
    root = Path(__file__).resolve().parents[1]  # sidecar/
    source = (root / "media_studio/features/scroll_regen.py").read_text(encoding="utf-8")
    for name in _module_level_imports(source):
        lowered = name.lower()
        assert not any(banned in lowered for banned in _BANNED_IMPORT_SUBSTRINGS), (
            f"scroll_regen.py imports forbidden module at module scope: {name}"
        )
