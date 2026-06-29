"""Real OCR backend for the R4 source-chyron safe-zone (LAZY / heavy only).

Imported ONLY at run time by the reframe engines when a real
:class:`~media_studio.features.chyron_safezone.SafeZone` is needed — never at
package import and never by the unit tests (which inject a fake
:class:`~media_studio.features.chyron_safezone.OcrBackend`). It is therefore the
one place allowed to touch ``cv2`` + the RapidOCR/onnxruntime stack, and those
imports live INSIDE the method bodies so importing THIS module stays light
(mirrors ``reframe_multispeaker_backend`` / ``ocr_list_backend``).

DISTINCT from ``ocr_list_backend.RealOcrBackend`` ON PURPOSE: that one returns
only the top-left ANCHOR (``{text, top, left}``) because list-extraction just
needs reading order, whereas chyron detection needs the FULL bounding box
(``x, y, w, h``) — a chyron is defined by being a WIDE strip — so it keeps the
whole RapidOCR polygon and normalises it. It reuses the same manifest-pinned,
version-agnostic detection model SLOT (``ocr_list.ASSET_NAME``).

Coverage of the backend class is excluded (it needs the heavy native stack + the
downloaded ONNX weights); the pure detector it feeds is covered exhaustively in
``test_chyron_safezone.py``, and this module's import surface is covered there.
"""

from __future__ import annotations

from typing import Any

from ..util import get_logger
from .chyron_safezone import DEFAULT_SAMPLE_COUNT, TextBox

log = get_logger("media_studio.features.chyron_safezone_backend")


class RealChyronOcrBackend:  # pragma: no cover - requires cv2 + the RapidOCR stack
    """Sample frames with OpenCV and OCR each into normalised :class:`TextBox`es.

    The detector runs on a handful of evenly spaced frames (chyrons are static),
    so even on a 6 GB box this is cheap; the pure detector then keeps only the
    bands that PERSIST across the samples. The heavy imports are deferred to
    :meth:`detect` so constructing the backend never loads the native stack.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._engine: Any = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        from rapidocr import RapidOCR  # noqa: PLC0415 - heavy seam, runtime only

        self._engine = RapidOCR()
        log.info("rapidocr ready (chyron safe-zone)")

    def detect(self, media_path: str, *, sample_times: tuple[float, ...]) -> tuple[tuple[TextBox, ...], ...]:
        """Return one tuple of normalised text boxes per requested timestamp."""
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        cap = cv2.VideoCapture(media_path)
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1
            frames: list[tuple[TextBox, ...]] = []
            for t in sample_times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    log.debug("detect: no frame at t=%.3f, treating as empty", t)
                    frames.append(())
                    continue
                frames.append(self._ocr_frame(frame, width, height))
            return tuple(frames)
        finally:
            cap.release()

    def _ocr_frame(self, frame: Any, width: int, height: int) -> tuple[TextBox, ...]:
        """OCR one frame, keeping each RapidOCR polygon's FULL extent as a box."""
        self._ensure_engine()
        result = self._engine(frame)
        polys = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if polys is None or texts is None:
            return ()
        boxes: list[TextBox] = []
        for idx, (poly, text) in enumerate(zip(polys, texts, strict=False)):
            xs = [float(pt[0]) for pt in poly]
            ys = [float(pt[1]) for pt in poly]
            left, right = min(xs), max(xs)
            top, bottom = min(ys), max(ys)
            confidence = float(scores[idx]) if scores is not None else 1.0
            boxes.append(
                TextBox.from_pixels(
                    left,
                    top,
                    right - left,
                    bottom - top,
                    frame_width=width,
                    frame_height=height,
                    text=str(text),
                    confidence=confidence,
                )
            )
        return tuple(boxes)


__all__ = ["DEFAULT_SAMPLE_COUNT", "RealChyronOcrBackend"]
