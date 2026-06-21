"""The ``stitchPanorama`` frame-stitch engine (DESIGN §3 step #2, WU-stitch GAP-3a).

A scrolling clip (e.g. a phone slowly panning down a long list) is reconstructed
into ONE tall panorama image so the Director can later re-glide over it at a
constant speed (``regenScroll``, WU-regen). This module owns the *pure* part of
that reconstruction:

  * the **frame-offset accumulation** — given a per-pair vertical "advance"
    (how far each frame moved past the previous one), the absolute Y offset of
    every frame in the final panorama is a deterministic running sum; and
  * the **artifact assembly** — the read-only :class:`PanoramaArtifact`
    ``{image_path, height, frame_offsets}`` (DESIGN §2.2, reversible="artifact
    only": the engine never mutates a source manifest, it only RETURNS an
    artifact, so it is structurally non-destructive).

The two heavy, non-deterministic parts are SEAMS injected as callables so the
math above is testable to 100% line+branch without ever decoding an image:

  * ``aligner(prev_frame, frame) -> int`` — the pixel align that measures the
    vertical advance between two adjacent frames (real impl = OpenCV
    feature-match or vertical-overlap correlation); and
  * ``writer(frames, offsets, height) -> image_path`` — the pixel write that
    composites the frames onto a tall canvas and encodes it.

PURITY: this module imports ONLY stdlib + the :mod:`edit_plan` model at module
scope — NO ``Provider``/transport/OpenCV import. A default OpenCV aligner/writer
is provided behind ``# pragma: no cover`` (the prod seam), wiring its ``cv2``
import *inside* the function so the module stays import-light for the gate.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from media_studio.models.edit_plan import EditOp

#: A pixel-align seam: measure how far ``frame`` advanced past ``prev_frame``
#: (the non-overlapping vertical extent, in pixels). Injected so the offset math
#: is pure; the real impl is OpenCV (behind ``# pragma: no cover``).
Aligner = Callable[[str, str], int]

#: A pixel-write seam: composite the ordered ``frames`` at their absolute Y
#: ``offsets`` onto a canvas of total ``height`` and return the written path.
Writer = Callable[[Sequence[str], Sequence[int], int], str]

#: The default per-frame height used by the op-adapter when ``frameHeight`` is
#: absent from the op params (a sane non-zero placeholder; the prod writer
#: re-derives true heights from the decoded frames).
DEFAULT_FRAME_HEIGHT = 1


class StitchError(ValueError):
    """Typed error for an impossible / failed panorama stitch (WU-stitch).

    A :class:`ValueError` subclass (consistent with :class:`EditPlanError`).
    Raised on bad input (no frames, non-positive height, bad align result) and
    as a wrapper around an aligner/writer seam failure so callers never see a
    raw OpenCV/IO exception leak across the engine boundary.
    """


@dataclass(frozen=True)
class PanoramaArtifact:
    """A read-only stitched-panorama artifact (DESIGN §2.2).

    ``image_path`` is the written panorama image; ``height`` is its total pixel
    height; ``frame_offsets`` is the absolute Y offset of each input frame in
    the panorama, in input order. Frozen: the artifact is never mutated and is
    NEVER written back into the source manifest (reversible="artifact only").
    """

    image_path: str
    height: int
    frame_offsets: tuple[int, ...]


def _accumulate_offsets(frames: Sequence[str], aligner: Aligner) -> list[int]:
    """Return the absolute Y offset of each frame (running sum of advances).

    The first frame anchors at 0. Each subsequent frame's offset is the prior
    offset plus the aligner-measured forward ``advance``. A negative advance is
    physically impossible for a forward pan, so it is rejected; an aligner that
    raises is wrapped as a :class:`StitchError`.
    """
    offsets = [0]
    for index in range(1, len(frames)):
        try:
            advance = aligner(frames[index - 1], frames[index])
        except Exception as exc:  # noqa: BLE001 - any seam failure -> typed engine error
            raise StitchError(f"frame align failed at index {index}: {exc}") from exc
        if advance < 0:
            raise StitchError(f"aligner returned a negative advance ({advance}) at index {index}")
        offsets.append(offsets[-1] + advance)
    return offsets


def stitch_panorama(
    frames: Sequence[str],
    *,
    frame_height: int,
    aligner: Aligner,
    writer: Writer,
) -> PanoramaArtifact:
    """Stitch ordered ``frames`` into one tall :class:`PanoramaArtifact`.

    ``frame_height`` is the (uniform) pixel height of an input frame; the total
    panorama ``height`` is the last frame's offset plus ``frame_height``. The
    ``aligner`` measures the per-pair forward advance (pure offset math); the
    ``writer`` performs the actual pixel composite/encode (the seam).

    Raises :class:`StitchError` if ``frames`` is empty, ``frame_height`` is
    non-positive, the aligner fails / returns a negative advance, or the writer
    fails. Never mutates a source manifest — returns a read-only artifact.
    """
    if not frames:
        raise StitchError("a panorama needs at least one frame")
    if frame_height <= 0:
        raise StitchError(f"frame_height must be positive, got {frame_height}")

    offsets = _accumulate_offsets(frames, aligner)
    height = offsets[-1] + frame_height

    try:
        image_path = writer(frames, offsets, height)
    except Exception as exc:  # noqa: BLE001 - any writer failure -> typed engine error
        raise StitchError(f"panorama write failed: {exc}") from exc

    return PanoramaArtifact(image_path=image_path, height=height, frame_offsets=tuple(offsets))


def _require_frames(params: dict[str, Any]) -> list[str]:
    """Read + validate the ``frames`` op-param (a non-empty list of paths)."""
    raw = params.get("frames")
    if not isinstance(raw, list) or not raw:
        raise StitchError("stitchPanorama op requires a non-empty 'frames' list")
    if not all(isinstance(item, str) for item in raw):
        raise StitchError("stitchPanorama 'frames' entries must all be strings")
    return raw


def _require_frame_height(params: dict[str, Any]) -> int:
    """Read the ``frameHeight`` op-param (defaulted, must be an int)."""
    raw = params.get("frameHeight", DEFAULT_FRAME_HEIGHT)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise StitchError("stitchPanorama 'frameHeight' must be an integer")
    return raw


def stitch_panorama_op(op: EditOp, *, aligner: Aligner, writer: Writer) -> PanoramaArtifact:
    """Op-adapter: run :func:`stitch_panorama` from a ``stitchPanorama`` EditOp.

    Validates the op kind and its ``params`` (``frames``, optional
    ``frameHeight``) before dispatching. Raises :class:`StitchError` for a
    wrong kind or malformed params (the engine boundary stays typed).
    """
    if op.kind != "stitchPanorama":
        raise StitchError(f"stitch_panorama_op called with non-stitchPanorama op: {op.kind!r}")
    params = dict(op.params)
    frames = _require_frames(params)
    frame_height = _require_frame_height(params)
    return stitch_panorama(frames, frame_height=frame_height, aligner=aligner, writer=writer)


# ---------------------------------------------------------------------------
# Default production seams (OpenCV) — exercised only at runtime, never in tests.
# The ``cv2`` import lives INSIDE the functions so module import stays light and
# the purity guard (no module-scope cv2) holds.
# ---------------------------------------------------------------------------


def _imread(path: str, flags: int | None = None):  # pragma: no cover - real cv2 decode; needs a real image file
    """Decode ``path`` via ``cv2.imread`` or raise :class:`StitchError`.

    ``cv2.imread`` returns ``None`` for an unreadable file; the guard both keeps
    the engine boundary typed (no raw ``None`` leaks) and narrows the type for
    basedpyright. Behind ``# pragma: no cover`` — it needs a real image file.
    """
    import cv2  # noqa: PLC0415 - lazy seam import keeps module import-light

    img = cv2.imread(path) if flags is None else cv2.imread(path, flags)
    if img is None:
        raise StitchError(f"could not read frame image: {path}")
    return img


def default_aligner(prev_frame: str, frame: str) -> int:  # pragma: no cover - needs OpenCV + real images
    """Real vertical-overlap aligner: measure how far ``frame`` panned down.

    Uses OpenCV template matching of ``frame``'s top strip against ``prev_frame``
    to find the vertical advance. Behind ``# pragma: no cover`` — it requires
    real decoded images and is replaced by a fake in tests.
    """
    import cv2  # noqa: PLC0415 - lazy seam import keeps module import-light

    prev = _imread(prev_frame, cv2.IMREAD_GRAYSCALE)
    cur = _imread(frame, cv2.IMREAD_GRAYSCALE)
    strip = cur[: cur.shape[0] // 4, :]
    result = cv2.matchTemplate(prev, strip, cv2.TM_CCOEFF_NORMED)
    _min_v, _max_v, _min_loc, max_loc = cv2.minMaxLoc(result)
    return int(max_loc[1])


def default_writer(
    frames: Sequence[str], offsets: Sequence[int], height: int
) -> str:  # pragma: no cover - needs OpenCV + real images
    """Real panorama writer: composite frames onto a tall canvas and encode.

    Behind ``# pragma: no cover`` — it decodes/encodes real images. Replaced by
    a fake in tests; the geometry it receives is fully tested upstream.
    """
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    first = _imread(frames[0])
    canvas = np.zeros((height, first.shape[1], first.shape[2]), dtype=first.dtype)
    for path, top in zip(frames, offsets, strict=True):
        img = _imread(path)
        canvas[top : top + img.shape[0], :] = img
    out_path = f"{frames[0]}.panorama.png"
    cv2.imwrite(out_path, canvas)
    return out_path
