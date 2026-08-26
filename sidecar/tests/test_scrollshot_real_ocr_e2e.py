"""Offline real-Tesseract smoke for the production scrollshot OCR adapter.

The workstation ships ``tesseract.exe`` but intentionally has no pytesseract or
RapidOCR package in the sidecar environment.  This acceptance test therefore
pins the production adapter to a local executable-backed implementation rather
than allowing an undeclared Python wrapper or a network OCR fallback.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from media_studio.features import scrollshot

pytestmark = pytest.mark.e2e

_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def _deny_network(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("scrollshot OCR attempted network access")


def test_production_ocr_adapter_uses_local_tesseract_with_text_boxes_and_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recognize real pixels offline and preserve word-level evidence geometry."""
    assert _TESSERACT.is_file(), f"required local OCR executable is missing: {_TESSERACT}"
    cv2 = pytest.importorskip("cv2", reason="OpenCV is required to construct the OCR fixture")
    image = np.full((260, 1000, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "REFRAME OCR 2026",
        (40, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        2.4,
        (0, 0, 0),
        5,
        cv2.LINE_AA,
    )
    image_path = tmp_path / "real-tesseract-input.png"
    assert cv2.imwrite(str(image_path), image)
    monkeypatch.setattr(socket.socket, "connect", _deny_network)

    frame = scrollshot.SampledFrame(
        index=0,
        source_index=0,
        path=str(image_path),
        image=image,
        width=image.shape[1],
        height=image.shape[0],
    )
    config = scrollshot.ScrollshotConfig(title="OCR smoke", language="eng", assurance="strict")
    observations = list(scrollshot.default_ocr_reader([frame], config))

    compact_text = re.sub(r"[^A-Z0-9]", "", " ".join(item.text for item in observations).upper())
    assert "REFRAMEOCR2026" in compact_text, compact_text
    assert observations, "production OCR returned no word observations"
    assert all(item.frame_index == 0 for item in observations)
    assert all(item.left >= 0 and item.top >= 0 for item in observations)
    assert all(item.width > 0 and item.height > 0 for item in observations)
    assert all(0.0 <= item.confidence <= 100.0 for item in observations)
    assert any(item.confidence >= 70.0 for item in observations), observations


# UNIT-COMPLETE: scrollshot-real-ocr-smoke-20260819
