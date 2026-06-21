"""The ``regenScroll`` constant-speed scroll renderer (DESIGN §3 step #3, WU-regen GAP-3b).

After a scrolling span has been reconstructed into one tall panorama
(:func:`~media_studio.features.panorama_stitch.stitch_panorama`, WU-stitch), the
Director re-renders a FRESH, CONSTANT-SPEED glide down that panorama to replace
the erratic original pan. This module owns the *pure* part of that render:

  * the **frame-time/position curve** — given a ``durationMs``, ``fps`` and the
    panorama's scrollable extent (``height`` minus the viewport), the absolute Y
    scroll position of every output frame is a deterministic LINEAR ramp. Its
    first difference (per-frame delta) is CONSTANT — that is the falsifiable
    proof this is a constant-speed glide and explicitly NOT a speed-ramp
    (DESIGN §2.2/§3); and
  * the **artifact assembly** — the read-only :class:`ClipArtifact`
    ``{clip_path, frame_count, duration_ms, fps}`` (the engine never mutates a
    source manifest, it only RETURNS an artifact + a durable INVERSE that
    restores the original span, recorded by WU-apply).

The single heavy, non-deterministic part is a SEAM injected as a callable so the
curve math above is testable to 100% line+branch without ever encoding a clip:

  * ``renderer(panorama, positions, fps) -> clip_path`` — pan the viewport over
    the panorama at each computed Y ``position`` and encode (real impl =
    render-cli, behind ``# pragma: no cover``).

Only ``easing="linear"`` is accepted in v1 (DESIGN §3); any other easing is
rejected, since a non-linear curve would re-introduce the very acceleration this
step exists to remove.

PURITY: this module imports ONLY stdlib + the :mod:`panorama_stitch` /
:mod:`edit_plan` models at module scope — NO ``Provider``/transport/render
import. A default render-cli renderer is provided behind ``# pragma: no cover``
(the prod seam), wiring its import *inside* the function so the module stays
import-light for the gate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from media_studio.features.panorama_stitch import PanoramaArtifact
from media_studio.models.edit_plan import EditOp

#: A render seam: pan the viewport over ``panorama`` at each absolute Y
#: ``positions`` value (constant-speed curve) and encode at ``fps``, returning
#: the written clip path. Injected so the curve math is pure; the real impl is
#: render-cli (behind ``# pragma: no cover``).
Renderer = Callable[[PanoramaArtifact, Sequence[float], int], str]

#: The only easing accepted in v1: a fresh CONSTANT-SPEED glide (DESIGN §3).
LINEAR_EASING = "linear"

#: Defaults applied by the op-adapter when the optional curve params are absent.
DEFAULT_FPS = 30
DEFAULT_VIEWPORT_HEIGHT = 1


class RegenError(ValueError):
    """Typed error for an impossible / failed constant-speed regen (WU-regen).

    A :class:`ValueError` subclass (consistent with
    :class:`~media_studio.features.panorama_stitch.StitchError` and
    :class:`~media_studio.models.edit_plan.EditPlanError`). Raised on bad input
    (non-positive duration/fps/viewport, non-linear easing, missing span/params)
    and as a wrapper around a renderer seam failure so callers never see a raw
    render/IO exception leak across the engine boundary.
    """


@dataclass(frozen=True)
class ClipArtifact:
    """A read-only regenerated-clip artifact (WU-regen).

    ``clip_path`` is the encoded constant-speed glide; ``frame_count`` is how
    many frames it holds; ``duration_ms``/``fps`` echo the render parameters.
    Frozen: the artifact is never mutated and is NEVER written back into the
    source manifest — WU-apply swaps the original span for this clip and records
    the inverse (restore the original span) for a durable undo.
    """

    clip_path: str
    frame_count: int
    duration_ms: int
    fps: int


def _linear_positions(frame_count: int, travel: float) -> list[float]:
    """Return the per-frame absolute Y positions for a LINEAR glide.

    The first frame anchors at ``0.0`` and the last lands exactly at ``travel``
    (the scrollable extent). The per-frame delta is constant — zero
    acceleration — which is the product claim for ``regenScroll``. A single
    frame is a degenerate glide pinned at the top (no travel).
    """
    if frame_count == 1:
        return [0.0]
    step = travel / (frame_count - 1)
    return [step * index for index in range(frame_count)]


def regen_scroll(
    panorama: PanoramaArtifact,
    *,
    duration_ms: int,
    easing: str,
    fps: int,
    viewport_height: int,
    renderer: Renderer,
) -> ClipArtifact:
    """Render a constant-speed glide over ``panorama`` into a :class:`ClipArtifact`.

    The output holds ``round(duration_ms / 1000 * fps)`` frames (at least one).
    Each frame's Y position is a LINEAR ramp from ``0`` to the scrollable extent
    (``panorama.height - viewport_height``, clamped at ``0`` when the panorama
    already fits the viewport), giving a constant per-frame delta. The
    ``renderer`` performs the actual pan/encode (the seam).

    Raises :class:`RegenError` if ``easing`` is not ``"linear"`` (v1 is
    linear-only), ``duration_ms``/``fps``/``viewport_height`` are non-positive,
    or the renderer fails. Never mutates a source manifest — returns a read-only
    artifact.
    """
    if easing != LINEAR_EASING:
        raise RegenError(f"regenScroll v1 supports only easing={LINEAR_EASING!r}, got {easing!r}")
    if duration_ms <= 0:
        raise RegenError(f"duration_ms must be positive, got {duration_ms}")
    if fps <= 0:
        raise RegenError(f"fps must be positive, got {fps}")
    if viewport_height <= 0:
        raise RegenError(f"viewport_height must be positive, got {viewport_height}")

    frame_count = max(1, round(duration_ms / 1000 * fps))
    travel = max(0, panorama.height - viewport_height)
    positions = _linear_positions(frame_count, float(travel))

    try:
        clip_path = renderer(panorama, positions, fps)
    except Exception as exc:  # noqa: BLE001 - any renderer failure -> typed engine error
        raise RegenError(f"scroll render failed: {exc}") from exc

    return ClipArtifact(clip_path=clip_path, frame_count=frame_count, duration_ms=duration_ms, fps=fps)


def _require_span(op: EditOp) -> tuple[int, int]:
    """Read the op ``span`` (required — the original range the glide replaces)."""
    if op.span is None:
        raise RegenError("regenScroll op requires a span (the original range to replace)")
    return op.span


def _require_panorama(params: dict[str, Any]) -> PanoramaArtifact:
    """Rebuild the :class:`PanoramaArtifact` from the op's ``panorama`` param."""
    raw = params.get("panorama")
    if not isinstance(raw, dict):
        raise RegenError("regenScroll op requires a 'panorama' mapping")
    image_path = raw.get("imagePath")
    height = raw.get("height")
    offsets = raw.get("frameOffsets")
    if (
        not isinstance(image_path, str)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or not isinstance(offsets, list)
    ):
        raise RegenError("regenScroll 'panorama' must have a string imagePath, int height, list frameOffsets")
    return PanoramaArtifact(image_path=image_path, height=height, frame_offsets=tuple(offsets))


def _require_duration(params: dict[str, Any]) -> int:
    """Read the required ``durationMs`` op-param (must be an int)."""
    raw = params.get("durationMs")
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise RegenError("regenScroll 'durationMs' must be an integer")
    return raw


def _require_easing(params: dict[str, Any]) -> str:
    """Read the optional ``easing`` op-param (defaulted to linear, must be str)."""
    raw = params.get("easing", LINEAR_EASING)
    if not isinstance(raw, str):
        raise RegenError("regenScroll 'easing' must be a string")
    return raw


def _require_fps(params: dict[str, Any]) -> int:
    """Read the optional ``fps`` op-param (defaulted, must be an int)."""
    raw = params.get("fps", DEFAULT_FPS)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise RegenError("regenScroll 'fps' must be an integer")
    return raw


def _require_viewport(params: dict[str, Any]) -> int:
    """Read the optional ``viewportHeight`` op-param (defaulted, must be an int)."""
    raw = params.get("viewportHeight", DEFAULT_VIEWPORT_HEIGHT)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise RegenError("regenScroll 'viewportHeight' must be an integer")
    return raw


def regen_scroll_op(op: EditOp, *, renderer: Renderer) -> tuple[ClipArtifact, dict[str, Any]]:
    """Op-adapter: run :func:`regen_scroll` from a ``regenScroll`` EditOp.

    Validates the op kind, its required ``span`` (the original range this glide
    replaces) and its ``params`` (``panorama``, ``durationMs``, optional
    ``easing``/``fps``/``viewportHeight``), then dispatches. Returns the
    :class:`ClipArtifact` plus the durable INVERSE — a ``restoreSpan`` directive
    naming the original span — which WU-apply records so the edit can be undone.
    Raises :class:`RegenError` for a wrong kind or malformed params (the engine
    boundary stays typed).
    """
    if op.kind != "regenScroll":
        raise RegenError(f"regen_scroll_op called with non-regenScroll op: {op.kind!r}")
    span = _require_span(op)
    params = dict(op.params)
    panorama = _require_panorama(params)
    duration_ms = _require_duration(params)
    easing = _require_easing(params)
    fps = _require_fps(params)
    viewport_height = _require_viewport(params)

    artifact = regen_scroll(
        panorama,
        duration_ms=duration_ms,
        easing=easing,
        fps=fps,
        viewport_height=viewport_height,
        renderer=renderer,
    )
    inverse: dict[str, Any] = {"kind": "restoreSpan", "span": [span[0], span[1]]}
    return artifact, inverse


# ---------------------------------------------------------------------------
# Default production seam (render-cli) — exercised only at runtime, never tests.
# The render import lives INSIDE the function so module import stays light and
# the purity guard (no module-scope render/transport import) holds.
# ---------------------------------------------------------------------------


def default_renderer(
    panorama: PanoramaArtifact, positions: Sequence[float], fps: int
) -> str:  # pragma: no cover - needs OpenCV + a real panorama image
    """Real renderer: crop the viewport over the panorama at each Y position and encode.

    Behind ``# pragma: no cover`` — it decodes a real panorama image, writes one
    cropped frame per computed Y ``position`` (the constant-speed curve), and
    encodes them to a clip via ``cv2.VideoWriter``. Replaced by a fake in tests;
    the geometry it receives is fully tested upstream. The ``cv2`` import lives
    inside the function so the module stays import-light and the purity guard
    (no module-scope ``cv2``) holds.
    """
    import cv2  # noqa: PLC0415 - lazy seam import keeps module import-light

    canvas = cv2.imread(panorama.image_path)
    if canvas is None:
        raise RegenError(f"could not read panorama image: {panorama.image_path}")
    full_h, width = canvas.shape[0], canvas.shape[1]
    view_h = max(1, full_h - int(round(positions[-1]))) if len(positions) > 1 else full_h
    out_path = f"{panorama.image_path}.scroll.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # type: ignore[attr-defined]
    writer = cv2.VideoWriter(out_path, fourcc, float(fps), (width, view_h))
    try:
        for position in positions:
            top = int(round(position))
            writer.write(canvas[top : top + view_h, :])
    finally:
        writer.release()
    return out_path
