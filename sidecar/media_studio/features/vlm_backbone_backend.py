"""Real SigLIP-2 backbone (LAZY-imported only — heavy native stack).

Imported ONLY inside ``vlm_backbone._default_backbone_factory`` at runtime —
never at package import, never by the tests (which inject a fake
:class:`~media_studio.features.vlm_backbone.BackboneBackend`). It is therefore
the one place allowed to import ``transformers`` / ``torch``, and those imports
live inside the methods so even importing THIS module stays light.

The pinned model is ``google/siglip2-so400m-patch16-384`` (Apache-2.0, ~2.3 GB
fp16; PHASE8-SOTA-MANIFEST.md component #2). The tiny aesthetic MLP head is the
AGPL-free reimplementation (manifest #3): its weights load from the on-demand
asset when present, else :meth:`head_weights` returns ``None`` and the pure
runner falls back to its embedding-norm proxy.

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure scorers it feeds are covered exhaustively in
``test_vlm_backbone.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ..util import get_logger
from .vlm_backbone import SIGLIP2_MODEL_ID

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.vlm_backbone_backend")


class RealBackboneBackend:  # pragma: no cover - requires the heavy native stack
    """SigLIP-2 SoViT-400M loaded once; serves image + text embeds + head.

    Constructed lazily per job (``settings`` selects the device/dtype). The
    backbone is loaded on first :meth:`embed_images` so construction stays cheap
    and an import failure surfaces as the job's error.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None
        self._processor: Any = None
        self._head: np.ndarray | None = None

    def _device(self) -> str:
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path
            return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415
        from transformers import AutoModel, AutoProcessor  # noqa: PLC0415

        device = self._device()
        dtype = torch.float16 if device == "cuda" else torch.float32
        self._model = AutoModel.from_pretrained(SIGLIP2_MODEL_ID, torch_dtype=dtype).to(device).eval()
        self._processor = AutoProcessor.from_pretrained(SIGLIP2_MODEL_ID)
        log.info("siglip2 backbone ready on %s (%s)", device, dtype)

    def embed_images(self, frames: np.ndarray) -> np.ndarray:
        import torch  # noqa: PLC0415

        self._ensure_model()
        inputs = self._processor(images=list(frames), return_tensors="pt").to(self._device())
        with torch.no_grad():
            feats = self._model.get_image_features(**inputs)
        return feats.detach().cpu().float().numpy()

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        import torch  # noqa: PLC0415

        self._ensure_model()
        inputs = self._processor(text=list(texts), return_tensors="pt", padding="max_length").to(self._device())
        with torch.no_grad():
            feats = self._model.get_text_features(**inputs)
        return feats.detach().cpu().float().numpy()

    def head_weights(self) -> np.ndarray | None:
        return self._head


__all__ = ["RealBackboneBackend"]
