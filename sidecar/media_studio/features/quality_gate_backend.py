"""Real DOVER-Mobile VQA backend for the quality gate (LAZY-imported only).

Imported ONLY inside ``quality_gate._default_backend_factory`` /
``quality_gate._default_frame_loader`` at job run-time — never at package import,
never by the tests (which inject a fake :class:`~media_studio.features.quality_gate.DoverBackend`
and a fake frame loader). It is therefore the one place allowed to import the
heavy ``torch`` / ``decord`` / ``opencv`` DOVER stack, and those imports live
inside the methods/functions so even importing THIS module stays light.

The DOVER-Mobile checkpoint is **S-Lab License 1.0 — non-commercial**; this stays
local-only. Coverage of this module is excluded (it requires the heavy native
stack + real video); the pure gate it feeds is covered exhaustively in
``test_quality_gate.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..util import get_logger

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.quality_gate_backend")

#: DOVER samples a fixed-size clip frame stream; the exact size is a backend knob.
TARGET_FRAMES = 32


class DoverMobileBackend:  # pragma: no cover - requires the heavy native stack
    """DOVER-Mobile (convnext_v2_femto) technical+aesthetic VQA.

    Constructed lazily per job (``settings`` selects the device). The model loads
    on first :meth:`assess` so construction stays cheap and an import failure
    surfaces as the job's error.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None

    def _device(self) -> str:
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path
            return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        # The real DOVER-Mobile load (torch + the DOVER package) goes here at
        # runtime; omitted in this Wave-1 stub (excluded from coverage).
        raise RuntimeError("DOVER-Mobile model not installed; install the asset to enable the quality gate")

    def assess(self, frames: np.ndarray) -> tuple[float, float]:
        """Return a ``(technical, aesthetic)`` quality pair for one clip's frames."""
        self._ensure_model()
        raise NotImplementedError


def load_clip_frames(
    media_path: str, candidates: Sequence[dict[str, Any]]
) -> list[np.ndarray]:  # pragma: no cover - requires native video decode
    """Extract a DOVER frame stack per candidate clip (cv2/decord, runtime only)."""
    import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

    _ = (cv2, media_path, candidates, TARGET_FRAMES)
    raise NotImplementedError


__all__ = ["TARGET_FRAMES", "DoverMobileBackend", "load_clip_frames"]
