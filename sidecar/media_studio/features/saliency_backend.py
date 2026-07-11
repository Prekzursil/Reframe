"""Real ViNet-S saliency backend for the Phase-8 saliency runner (LAZY-imported only).

Imported ONLY inside ``saliency._default_backend_factory`` at run-time — never at
package import, never by the unit tests (which inject a fake
:class:`~media_studio.features.saliency.SaliencyBackend` whose ``infer`` returns
hand-built numpy stacks). It is therefore the one place allowed to import torch /
the vendored ViNet-S network, and those imports live INSIDE the method bodies so
even importing THIS module stays light (mirrors ``scene_transnet_backend`` /
``reframe_edgetam_backend``).

Coverage of the heavy class is excluded (it needs torch + the vendored arch + the
real weight); the pure saliency math it feeds is covered exhaustively in
``test_saliency.py`` (with a fake backend), the verify-before-load gate in
``test_safetensors_loader.py``, and this module's import surface in
``test_phase8_backend_surfaces.py``.

VERIFY-BEFORE-LOAD (I2): the weight is loaded via
:func:`_safetensors_loader.load_into_model` — safetensors ONLY (a ``.pth`` /
pickle is refused LOUD, torch.load is never called), with the manifest sha256
re-verified on disk and ``load_state_dict`` strict (a key/shape mismatch raises).

C2 INVARIANT: ViNet-S ENHANCES the always-on YuNet crop-track (it supplies the
no-face saliency crop-centre); it is NEVER a prerequisite. A missing / unloadable
weight degrades the ``saliency`` channel to ``present=False`` upstream (the F1
"download to enable" path), never blocking a reframe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..pathsafe import clean_for_log
from ..util import get_logger
from .saliency import ASSET_NAME

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.saliency_backend")

#: ViNet-S DHF1K input geometry (mirrors the upstream ViNet_S_dataloader transform:
#: Resize((224, 384)) -> ToTensor -> ImageNet Normalize) + the 32-frame clip length.
_INPUT_H = 224
_INPUT_W = 384
_CLIP_LEN = 32
_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)


class ViNetSaliencyBackend:  # pragma: no cover - requires torch + the vendored arch + the real weight
    """ViNet-S per-frame saliency-map predictor over the re-hosted safetensors weight.

    Constructed lazily per job (``settings`` selects the device). The model +
    weight are loaded on the FIRST :meth:`infer` so construction stays cheap and a
    load failure surfaces as the job's error (which the runner degrades to
    ``present=False`` — never a silent zero map).
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None
        self._device: str = "cpu"

    def _resolve_weight_path(self) -> str:
        """Resolve the on-disk ``vinet-s-saliency.safetensors`` path (override or asset).

        Order: an explicit operator override ``settings['saliencyWeightPath']``
        wins; otherwise the sha256-pinned asset-manager install path. Raises if the
        weight cannot be located (never silently loads a missing file).
        """
        override = self._settings.get("saliencyWeightPath")
        if override:
            import os  # noqa: PLC0415

            return os.path.expanduser(str(override))

        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        mgr = AssetManager(settings_provider=lambda: self._settings)
        path = mgr.installed_path(entry) if entry is not None else None
        if path is None:
            raise RuntimeError(f"ViNet-S saliency weight asset {ASSET_NAME!r} is not installed")
        return path

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415 - heavy seam, runtime only

        from ..assets import manifest  # noqa: PLC0415
        from ._safetensors_loader import load_into_model  # noqa: PLC0415
        from ._vinet_s.model import VideoSaliencyModel  # noqa: PLC0415 - vendored torch arch

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        # The exact config the DHF1K / root-grouped visual-only weight was trained
        # with (dossier §1.6); its 470 backbone.*/decoder.* keys match the weight.
        model = VideoSaliencyModel(
            use_upsample=True,
            num_hier=3,
            num_clips=_CLIP_LEN,
            grouped_conv=True,
            root_grouping=True,
            depth=False,
            efficientnet=False,
            BiCubic=False,
            maxpool3d=True,
        )
        weight_path = self._resolve_weight_path()
        entry = manifest.get_asset(ASSET_NAME)
        expected = entry.sha256 if entry is not None else None
        # Verify-before-load: safetensors ONLY + sha re-verify + strict load_state_dict.
        load_into_model(
            model,
            weight_path,
            expected_sha256=expected,
            load_file=lambda p: _load_file_to(p, self._device),
        )
        model.eval().to(self._device)
        self._model = model
        log.info("ViNet-S saliency ready on %s (%s)", self._device, clean_for_log(weight_path))

    def infer(self, frames: np.ndarray) -> np.ndarray:
        """Return an ``NxHxW`` per-frame saliency stack for the ``NxHxWx3`` ``frames``.

        Each input frame gets a 32-frame clip ending at it (edge-padded at the
        start), run through ViNet-S; the clip's saliency map is resized back to the
        input frame's H×W so the crop-centre argmax lands in original coordinates.
        """
        import cv2  # noqa: PLC0415 - job-time native
        import numpy as np  # noqa: PLC0415
        import torch  # noqa: PLC0415

        self._ensure_model()
        arr = np.asarray(frames)
        if arr.size == 0 or arr.shape[0] == 0:
            return np.empty((0, 0, 0), dtype=np.float64)
        n, src_h, src_w = arr.shape[0], arr.shape[1], arr.shape[2]

        # Preprocess every frame once: BGR->RGB, Resize(224,384), /255, ImageNet norm.
        mean = np.asarray(_IMAGENET_MEAN, dtype=np.float32).reshape(3, 1, 1)
        std = np.asarray(_IMAGENET_STD, dtype=np.float32).reshape(3, 1, 1)
        pre: list[np.ndarray] = []
        for i in range(n):
            rgb = cv2.cvtColor(arr[i], cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (_INPUT_W, _INPUT_H))
            chw = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
            pre.append((chw - mean) / std)
        stack = np.stack(pre, axis=0)  # [N, C, H, W]

        maps: list[np.ndarray] = []
        with torch.no_grad():
            for i in range(n):
                lo = i - _CLIP_LEN + 1
                idx = [max(0, j) for j in range(lo, i + 1)]  # edge-pad the clip start
                clip = stack[idx]  # [T, C, H, W]
                tensor = torch.from_numpy(clip).permute(1, 0, 2, 3).unsqueeze(0).to(self._device)  # [1,C,T,H,W]
                out = self._model(tensor)
                sal = out.squeeze().detach().cpu().numpy().astype(np.float64)
                maps.append(cv2.resize(sal, (src_w, src_h)))
        return np.asarray(maps, dtype=np.float64)


def _load_file_to(path: str, device: str) -> dict[str, Any]:  # pragma: no cover - torch/safetensors native seam
    """safetensors.torch.load_file onto ``device`` (the injected reader seam)."""
    from safetensors.torch import load_file  # noqa: PLC0415

    return load_file(path, device=device)


__all__ = ["ViNetSaliencyBackend"]
