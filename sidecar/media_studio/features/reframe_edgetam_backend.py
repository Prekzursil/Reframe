"""Real heavy-ML backend for the OPT-IN EdgeTAM reframe tracker (LAZY only).

Imported ONLY inside
``reframe_claudeshorts._default_edgetam_tracker_factory`` at run-time — never at
package import, never by the unit tests (which inject a fake tracker via the
``edgetam_tracker_factory`` seam). It is therefore the one place allowed to import
torch + the vendored EdgeTAM (``sam2``) package and load the sha256-pinned
checkpoint, and those imports live INSIDE the method bodies so even importing THIS
module stays light (mirrors ``reframe_multispeaker_backend`` / ``scene_transnet_backend``).

Coverage of this module is excluded (it requires torch + the EdgeTAM package +
real weights); the pure tracker-wiring it feeds is covered exhaustively in
``test_reframe_claudeshorts.py`` (with a fake tracker), and this module's import
surface is covered by ``test_phase8_backend_surfaces.py``.

WHY EdgeTAM (WU2): the DEFAULT claudeshorts backend re-detects a face every
sampled frame (YuNet), so a speaker who is briefly occluded or turns fully away is
lost and the crop snaps back to a center/motion fallback. EdgeTAM
(facebookresearch/EdgeTAM, Apache-2.0) is an edge-optimized SAM2 successor that
PROPAGATES a single subject mask through occlusions, so the crop keeps tracking
the same person. It is OPT-IN (``settings["reframeTracker"]="edgetam"``); the
YuNet default is untouched.

6 GB VRAM CONTRACT (design note): the tracker holds ONE model. :meth:`release`
frees it + the CUDA cache BETWEEN the detect stage and the ffmpeg encode stage, so
the encode never competes with a resident tracker for the 6 GB budget (mirrors the
R1 multi-speaker engine's release-between-stages pattern).
"""

from __future__ import annotations

from typing import Any

from ..util import get_logger
from .reframe_claudeshorts import EdgeTamBackendUnavailableError, resolve_edgetam_model_path

log = get_logger("media_studio.features.reframe_edgetam_backend")

# The EdgeTAM (sam2 fork) model config that pairs with the edgetam.pt checkpoint.
EDGETAM_CONFIG = "configs/edgetam.yaml"
# Detection confidence floor: a low-confidence propagated mask (subject fully gone)
# is treated as "lost" so the finder falls through to the motion last resort
# instead of steering the crop with a phantom mask.
MIN_MASK_AREA_FRAC = 0.0005


class RealEdgeTamTracker:  # pragma: no cover - requires torch + the EdgeTAM package + weights
    """Stateful EdgeTAM subject tracker over the sampled reframe frames.

    Constructed lazily per job (``settings`` selects the device). The heavy torch +
    EdgeTAM imports and the checkpoint load happen in :meth:`_ensure_model` on the
    FIRST :meth:`track` call, so a missing stack surfaces as the typed
    :class:`EdgeTamBackendUnavailableError` (never a silent fall back to YuNet —
    WU2 req 2). Each :meth:`track` returns the tracked subject's normalized
    horizontal center (0..1) or ``None`` when the subject is not confidently
    located (occluded / left frame), letting the caller's motion last resort take
    over for that one frame.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._predictor: Any = None
        self._device: Any = None
        # The previous frame's mask centroid (px), used as the next frame's point
        # prompt so the mask propagates temporally through brief occlusions.
        self._prev_point: tuple[float, float] | None = None

    def _ensure_model(self) -> None:
        """Import torch + EdgeTAM and load the pinned checkpoint (first call only).

        A missing torch / EdgeTAM package / checkpoint is a PROVISIONING failure —
        raised as the typed :class:`EdgeTamBackendUnavailableError` so the opt-in
        request fails loud rather than silently reverting to the YuNet default.
        """
        if self._predictor is not None:
            return
        try:
            import torch  # noqa: PLC0415 - heavy seam
            from sam2.build_sam import build_sam2  # noqa: PLC0415 - EdgeTAM (sam2 fork)
            from sam2.sam2_image_predictor import SAM2ImagePredictor  # noqa: PLC0415 - EdgeTAM
        except Exception as exc:  # noqa: BLE001 - any import failure -> loud opt-in error
            raise EdgeTamBackendUnavailableError(
                "the opt-in EdgeTAM tracker needs torch + the EdgeTAM (sam2) package, "
                "but importing them failed; install the EdgeTAM runtime or clear "
                "reframeTracker to use the YuNet default"
            ) from exc

        model_path = resolve_edgetam_model_path(self._settings)
        if model_path is None:
            raise EdgeTamBackendUnavailableError(
                "the opt-in EdgeTAM checkpoint is not provisioned — run first-run setup "
                "(assets.ensure) to download the sha256-pinned edgetam.pt"
            )
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = build_sam2(EDGETAM_CONFIG, model_path, device=str(self._device))
        self._predictor = SAM2ImagePredictor(model)

    def track(self, img: Any) -> float | None:
        """Locate the tracked subject in ``img`` (BGR); return its cx_norm or None.

        FIRST frame: seed with a center point prompt (the subject is framed near
        center in a talking-head clip) and remember its mask centroid. LATER frames:
        prompt with the PREVIOUS centroid so the mask propagates temporally — the
        subject stays tracked through a brief occlusion / head turn. Returns the
        mask centroid's normalized horizontal position, or ``None`` when the mask is
        empty/tiny (subject gone), so the caller's motion last resort covers the gap.
        """
        import numpy as np  # noqa: PLC0415 - job-time native (numpy ships with cv2)

        self._ensure_model()
        h, w = int(img.shape[0]), int(img.shape[1])
        # sam2 expects RGB; the sampled frames are BGR (cv2.imread).
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        point = self._prev_point or (w / 2.0, h / 2.0)
        self._predictor.set_image(rgb)
        masks, scores, _logits = self._predictor.predict(
            point_coords=np.array([[point[0], point[1]]], dtype="float32"),
            point_labels=np.array([1], dtype="int64"),
            multimask_output=True,
        )
        mask = self._best_mask(masks, scores, area=float(h * w))
        if mask is None:
            # Lost this frame: forget the stale point so the next frame re-seeds from
            # center rather than chasing a phantom off-frame location.
            self._prev_point = None
            return None
        ys, xs = np.nonzero(mask)
        cx_px = float(xs.mean())
        self._prev_point = (cx_px, float(ys.mean()))
        return cx_px / float(w)

    @staticmethod
    def _best_mask(masks: Any, scores: Any, area: float) -> Any | None:
        """Pick the highest-score mask; return it only if it covers enough area."""
        import numpy as np  # noqa: PLC0415 - job-time native

        if masks is None or len(masks) == 0:
            return None
        best = int(np.argmax(scores))
        mask = np.asarray(masks[best]) > 0.0
        if float(mask.sum()) < area * MIN_MASK_AREA_FRAC:
            return None
        return mask

    def release(self) -> None:
        """Drop the model + free the CUDA cache (called between stages, 6 GB ceiling)."""
        self._predictor = None
        self._prev_point = None
        try:
            import torch  # noqa: PLC0415 - heavy seam

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - no torch/CUDA -> nothing to free
            log.debug("release: no CUDA cache to free")


__all__ = ["RealEdgeTamTracker"]
