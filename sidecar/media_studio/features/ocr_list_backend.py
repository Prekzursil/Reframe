"""Real RapidOCR backend (LAZY-imported only — heavy native stack) (WU-ocr).

Imported ONLY inside ``ocr_list._default_backend_factory`` at runtime — never at
package import, never by the tests (which inject a fake
:class:`~media_studio.features.ocr_list.OcrBackend`). It is therefore the one
place allowed to import ``rapidocr`` / ``onnxruntime`` / ``cv2``, and those imports
live inside the methods so even importing THIS module stays light.

VERSION-AGNOSTIC (DESIGN §9 F7): the detection model path is resolved from the
manifest SLOT (``ocr_list.ASSET_NAME`` -> ``assets/manifest.RAPIDOCR_ASSET_NAME``)
via the asset manager — never a hardcoded PP-OCR version string. The manifest's
URL/label discrepancy (``ch_PP-OCRv4`` file vs "PP-OCRv5" label) therefore cannot
leak into the engine: whatever the slot resolves to is what loads.

Coverage of this module is excluded (it requires the heavy native OCR stack +
the downloaded ONNX weights); the pure box-ordering / dedup / poster logic it
feeds is covered exhaustively in ``test_ocr_list.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..util import get_logger
from .ocr_list import ASSET_NAME

log = get_logger("media_studio.features.ocr_list_backend")


class RealOcrBackend:  # pragma: no cover - requires the heavy native OCR stack
    """RapidOCR loaded lazily; OCRs one frame into ``{text, top, left}`` boxes.

    Constructed lazily per job (``settings`` selects the device). The engine is
    loaded on first :meth:`read_text` so construction stays cheap and an import /
    load failure surfaces as the job's error (wrapped by the pure
    :func:`~media_studio.features.ocr_list.extract_list` into a typed ``OcrError``).
    The detection model path is resolved from the manifest SLOT — never a hardcoded
    version (DESIGN §9 F7).
    """

    def __init__(self, settings: Mapping[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._engine: Any = None

    def _model_path(self) -> str | None:
        """Resolve the detection model path from the manifest SLOT (version-agnostic).

        Looks the asset up by :data:`ocr_list.ASSET_NAME` and returns the installed
        path, or ``None`` when the asset is not registered / not installed (RapidOCR
        then falls back to its packaged default model). NO hardcoded PP-OCR version.
        """
        try:
            from ..assets import manifest  # noqa: PLC0415 - lazy: avoids an import cycle
            from ..assets.manager import AssetManager  # noqa: PLC0415

            entry = manifest.get_asset(ASSET_NAME)
            if entry is None:
                return None
            mgr = AssetManager(settings_provider=lambda: dict(self._settings))
            return mgr.installed_path(entry)
        except Exception:  # noqa: BLE001 - missing asset machinery -> packaged default
            return None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        from rapidocr import RapidOCR  # noqa: PLC0415 - heavy seam, runtime only

        path = self._model_path()
        params = {"Det.model_path": path} if path else {}
        self._engine = RapidOCR(params=params) if params else RapidOCR()
        log.info("rapidocr ready (det=%s)", path or "packaged-default")

    def read_text(self, frame: Any) -> list[dict[str, Any]]:
        """OCR one RGB frame into ``{text, top, left}`` boxes (top-left anchored).

        RapidOCR returns ``(boxes, txts, scores)`` where each box is a 4-point
        polygon ``[[x,y], ...]``; the top-left point (min y, then min x) is the
        anchor the pure ordering uses. Any frame with no detected text yields ``[]``.
        """
        self._ensure_engine()
        result = self._engine(frame)
        boxes: list[dict[str, Any]] = []
        polys = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        if polys is None or texts is None:
            return boxes
        for poly, text in zip(polys, texts, strict=False):
            ys = [float(pt[1]) for pt in poly]
            xs = [float(pt[0]) for pt in poly]
            boxes.append({"text": str(text), "top": min(ys), "left": min(xs)})
        return boxes


__all__ = ["RealOcrBackend"]
