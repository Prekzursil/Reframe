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
from .scene_transnet import ASSET_NAME, CancelProbe, ProgressCb

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.scene_transnet_backend")


class RealTransNetBackend:  # pragma: no cover - requires the heavy native stack
    """TransNetV2 per-frame shot-change predictor over the re-hosted safetensors weight.

    Constructed lazily per job (``settings`` selects the device). The model +
    weight are loaded on first :meth:`predict` so construction stays cheap and a
    load failure surfaces as the job's error (which the runner degrades to the
    PySceneDetect fallback — never a silent break).

    VERIFY-BEFORE-LOAD (I2): the weight loads via
    :func:`_safetensors_loader.load_into_model` — safetensors ONLY (a ``.pth`` /
    pickle is refused LOUD, torch.load is never called), the manifest sha256 is
    re-verified on disk, and ``load_state_dict`` is strict (a key/shape mismatch
    raises rather than half-loading).
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None

    def _resolve_weight_path(self) -> str:
        """Resolve the on-disk ``transnetv2.safetensors`` path (override or asset).

        Order: an explicit operator override ``settings['sceneTransnetWeightPath']``
        wins; otherwise the sha256-pinned asset-manager install path. Raises if the
        weight cannot be located (never silently loads a missing file).
        """
        override = self._settings.get("sceneTransnetWeightPath")
        if override:
            import os  # noqa: PLC0415

            return os.path.expanduser(str(override))

        from ..assets import manifest  # noqa: PLC0415
        from ..assets.manager import AssetManager  # noqa: PLC0415

        entry = manifest.get_asset(ASSET_NAME)
        mgr = AssetManager(settings_provider=lambda: self._settings)
        path = mgr.installed_path(entry) if entry is not None else None
        if path is None:
            raise RuntimeError(f"TransNetV2 weight asset {ASSET_NAME!r} is not installed")
        return path

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import torch  # noqa: PLC0415 - heavy seam, runtime only

        from ..assets import manifest  # noqa: PLC0415
        from ._safetensors_loader import load_into_model  # noqa: PLC0415
        from ._transnetv2.transnetv2_pytorch import TransNetV2  # noqa: PLC0415 - vendored torch arch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = TransNetV2()
        weight_path = self._resolve_weight_path()
        entry = manifest.get_asset(ASSET_NAME)
        expected = entry.sha256 if entry is not None else None
        load_into_model(
            model,
            weight_path,
            expected_sha256=expected,
            load_file=lambda p: _load_file_to(p, device),
        )
        model.eval().to(device)
        self._model = model
        log.info("transnetv2 ready on %s (%s)", device, weight_path)

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


def _load_file_to(path: str, device: str) -> dict[str, Any]:  # pragma: no cover - torch/safetensors native seam
    """safetensors.torch.load_file onto ``device`` (the injected reader seam)."""
    from safetensors.torch import load_file  # noqa: PLC0415

    return load_file(path, device=device)


__all__ = ["RealTransNetBackend"]
