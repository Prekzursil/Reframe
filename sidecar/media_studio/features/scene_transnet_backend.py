"""Real TransNetV2 backend for scene-cut detection (LAZY-imported only).

Imported ONLY inside ``scene_transnet._default_backend_factory`` at run-time —
never at package import, never by the tests (which inject a fake
:class:`~media_studio.features.scene_transnet.TransNetBackend`). It is therefore
the one place allowed to import ``torch`` / the TransNetV2 weights, and those
imports live inside the method so even importing THIS module stays light.

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure cut-extraction it feeds is covered exhaustively in
``test_scene_transnet.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..util import get_logger
from .scene_transnet import CancelProbe, ProgressCb

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.scene_transnet_backend")


class RealTransNetBackend:  # pragma: no cover - requires the heavy native stack
    """TransNetV2 per-frame shot-change predictor over the PyTorch weights.

    Constructed lazily per job (``settings`` selects the device). The model is
    loaded on first :meth:`predict` so construction stays cheap and an import
    failure surfaces as the job's error.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415 - heavy seam, runtime only
        from transnetv2_pytorch import TransNetV2  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = TransNetV2()
        model.eval().to(device)
        self._model = model
        log.info("transnetv2 ready on %s", device)

    def predict(
        self,
        frames: np.ndarray,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> np.ndarray:
        """Return a 1-D per-frame shot-change probability array for ``frames``."""
        import torch  # noqa: PLC0415

        self._ensure_model()
        if on_progress is not None:
            on_progress(10.0, "running TransNetV2")
        tensor = torch.from_numpy(frames).unsqueeze(0)
        with torch.no_grad():
            single, _ = self._model(tensor)
            probs = torch.sigmoid(single).squeeze().cpu().numpy()
        if should_cancel is not None and should_cancel():
            return probs
        if on_progress is not None:
            on_progress(100.0, "done")
        return probs


__all__ = ["RealTransNetBackend"]
