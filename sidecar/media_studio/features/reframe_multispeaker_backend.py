"""Real heavy-ML backend for the R1 multi-speaker reframe engine (LAZY only).

Imported ONLY inside ``reframe_multispeaker._default_backend_factory`` at
run-time — never at package import, never by the unit tests (which inject a fake
:class:`~media_studio.features.reframe_multispeaker.MultiSpeakerBackend`). It is
therefore the one place allowed to import torch / cv2 / the Light-ASD +
TransNetV2 weights, and those imports live INSIDE the method bodies so even
importing THIS module stays light (mirrors ``scene_transnet_backend`` /
``diarize_backend``).

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure director it feeds is covered exhaustively in
``test_reframe_multispeaker.py``, and this module's import surface is covered by
``test_phase8_backend_surfaces.py``.

6 GB VRAM CONTRACT (design note): the stages run SEQUENTIALLY — shot detection
(TransNetV2), then diarization, then visual active-speaker (Light-ASD) — and
:meth:`RealMultiSpeakerBackend.release` frees the previous stage's model before
the next loads, so two models are never resident at once.
"""

from __future__ import annotations

import contextlib
import os
import subprocess  # noqa: S404 - argv lists only, no shell=True
import tempfile
from typing import Any

from ..util import get_logger
from .reframe_multispeaker import ShotAnalysis

log = get_logger("media_studio.features.reframe_multispeaker_backend")


class RealMultiSpeakerBackend:  # pragma: no cover - requires the heavy native stack
    """Staged TransNetV2 + diarize + Light-ASD pipeline over real frames.

    Constructed lazily per job (``settings`` selects the device). Each model is
    loaded on demand inside its stage and dropped via :meth:`release` before the
    next stage loads, so a 6 GB GPU holds at most one model at a time.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._stage_model: Any = None

    def release(self) -> None:
        """Drop the current stage's model + free CUDA cache (between stages)."""
        self._stage_model = None
        try:
            import torch  # noqa: PLC0415 - heavy seam

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - no torch/CUDA -> nothing to free
            log.debug("release: no CUDA cache to free")

    def analyze(
        self,
        media_path: str,
        *,
        on_progress: Any | None = None,
        should_cancel: Any | None = None,
    ) -> ShotAnalysis:
        """Run the staged pipeline and return the analysis bundle.

        STAGE 1 shots -> release -> STAGE 2 diarize -> release -> STAGE 3 faces +
        Light-ASD + VAD -> release. The heavy imports live inside the helpers so
        an OOM/model-load failure surfaces as the job's typed error (the engine
        wraps it + cleans up the partial output).
        """
        import cv2  # noqa: PLC0415 - job-time native (pre-imported by __main__)

        cap = cv2.VideoCapture(media_path)
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()

        shot_boundaries = self._stage_shots(media_path, fps)
        self.release()
        diarize_per_frame = self._stage_diarize(media_path, total, fps)
        self.release()
        boxes, scores, vad = self._stage_visual(media_path, total, fps)
        self.release()

        return ShotAnalysis(
            width=width,
            height=height,
            fps=fps,
            total_frames=total,
            shot_boundaries=shot_boundaries,
            boxes_per_frame=boxes,
            visual_scores_per_frame=scores,
            diarize_per_frame=diarize_per_frame,
            vad_per_frame=vad,
        )

    def _stage_shots(self, media_path: str, fps: float) -> tuple[int, ...]:
        """STAGE 1 — TransNetV2 (+PySceneDetect) cut frames."""
        from .scene_transnet import compute_scene_cuts  # noqa: PLC0415 - heavy seam

        cuts_sec = compute_scene_cuts(media_path, fps_hint=fps, settings=self._settings)
        return tuple(int(round(c * fps)) for c in cuts_sec)

    def _stage_diarize(self, media_path: str, total: int, fps: float) -> tuple[str, ...]:
        """STAGE 2 — speaker diarization -> per-frame active id.

        The SpeechBrain VAD reads audio through libsndfile, which has no video
        demuxer, so a raw ``media_path`` (.mp4) raises "Format not recognised".
        The video's audio is therefore first extracted to a 16 kHz mono WAV (same
        timeline, so region seconds map straight onto the source-fps frame grid),
        mirroring ``_lightasd_infer``'s audio extraction.
        """
        from . import diarize  # noqa: PLC0415 - heavy seam

        fd, wav_path = tempfile.mkstemp(prefix="msreframe_diar_", suffix=".wav")
        os.close(fd)
        try:
            subprocess.run(  # noqa: S603
                ["ffmpeg", "-y", "-i", media_path, "-vn", "-ac", "1", "-ar", "16000", wav_path],  # noqa: S607
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Real diarize API: detect_and_embed -> (regions[{start,end}], embeddings)
            # 1:1 in time order; greedy_cluster -> a cluster id per region;
            # speaker_label -> "SPEAKER_NN". (There is no top-level diarize.diarize();
            # this is the raw-media -> per-frame-speaker path, no transcript needed.)
            backend = diarize._default_backend_factory(self._settings)
            regions, embeddings = backend.detect_and_embed(wav_path)
        finally:
            with contextlib.suppress(OSError):
                os.remove(wav_path)
        labels = diarize.greedy_cluster(embeddings, threshold=diarize.DEFAULT_THRESHOLD)
        per_frame = [""] * total
        for region, label in zip(regions, labels, strict=False):
            start = max(0, int(round(float(region.get("start", 0.0)) * fps)))
            end = min(total, int(round(float(region.get("end", 0.0)) * fps)))
            speaker = diarize.speaker_label(label)
            for f in range(start, end):
                per_frame[f] = speaker
        return tuple(per_frame)

    def _stage_visual(self, media_path: str, total: int, fps: float) -> tuple[Any, Any, Any]:
        """STAGE 3 — face boxes + Light-ASD visual scores + audio VAD per frame.

        Real S3FD + Light-ASD inference (GPU-validated on razvan_gandu): returns
        ``(boxes_per_frame, visual_scores_per_frame, vad_per_frame)``, each of
        length ``total``, boxes as ``(x, y, w, h)`` source-pixels and per-box ASD
        scores index-aligned to the boxes. Delegates to the seam helper so the
        heavy imports stay inside the call.
        """
        from ._lightasd_infer import analyze_visual  # noqa: PLC0415 - heavy seam

        return analyze_visual(media_path, total, fps, settings=self._settings)


__all__ = ["RealMultiSpeakerBackend"]
