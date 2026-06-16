"""Real SpeechBrain VAD + ECAPA backend for diarization (LAZY-imported only).

This module is imported ONLY inside ``diarize._default_backend_factory`` at job
run-time — never at package import, never by the tests (which inject a fake
:class:`~media_studio.features.diarize.DiarizerBackend`). It is therefore the one
place allowed to import ``speechbrain`` / ``torch`` / ``torchaudio``, and those
imports live inside the methods so even importing THIS module stays light.

The :class:`SpeechBrainDiarizer`:
  1. runs SpeechBrain's pretrained ``VAD`` (CRDNN) to get speech boundaries;
  2. loads the audio with torchaudio, slices each speech region, and embeds it
     with the pretrained ``EncoderClassifier`` (ECAPA-TDNN);
  3. returns ``(regions, embeddings)`` for the pure clustering in ``diarize``.

Models resolve from the standard HF cache that ``assets.ensure`` populates, so a
machine that pre-fetched the gated assets runs this fully offline. Coverage of
this module is excluded (it requires the heavy native stack + real audio); the
pure pipeline it feeds is covered exhaustively in ``test_diarize.py``.
"""

from __future__ import annotations

from typing import Any

from ..util import get_logger
from .diarize import CancelProbe, ProgressCb

log = get_logger("media_studio.features.diarize_backend")

#: ECAPA expects 16 kHz mono; VAD is trained at 16 kHz too.
TARGET_SR = 16000


class SpeechBrainDiarizer:  # pragma: no cover - requires the heavy native stack
    """VAD + ECAPA pipeline over the pretrained SpeechBrain models.

    Constructed lazily per job (``settings`` selects the device). Both pretrained
    models are loaded on first :meth:`detect_and_embed` so construction stays
    cheap and an import failure surfaces as the job's error (A6 lesson 3).
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._vad: Any = None
        self._encoder: Any = None

    def _device(self) -> str:
        """Prefer CUDA, fall back to CPU (mirrors transcribe's policy)."""
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path (still works)
            return "cpu"

    def _ensure_models(self) -> None:
        if self._vad is not None and self._encoder is not None:
            return
        from speechbrain.inference.classifiers import EncoderClassifier  # noqa: PLC0415
        from speechbrain.inference.VAD import VAD  # noqa: PLC0415

        device = self._device()
        run_opts = {"device": device}
        self._vad = VAD.from_hparams(source="speechbrain/vad-crdnn-libriparty", run_opts=run_opts)
        self._encoder = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", run_opts=run_opts)
        log.info("speechbrain diarizer ready on %s", device)

    def detect_and_embed(
        self,
        audio_path: str,
        *,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> tuple[list[dict[str, Any]], list[list[float]]]:
        """Run VAD then embed each speech region with ECAPA.

        Returns ``(regions, embeddings)`` 1:1 in time order — exactly what
        ``diarize.diarize_transcript`` consumes. Progress is reported across the
        embedding loop; ``should_cancel`` is polled per region.
        """
        import torch  # noqa: PLC0415
        import torchaudio  # noqa: PLC0415

        self._ensure_models()
        if on_progress is not None:
            on_progress(5.0, "running VAD")

        # VAD -> a tensor of [start, end] (seconds) speech boundaries.
        boundaries = self._vad.get_speech_segments(audio_path)
        waveform, sr = torchaudio.load(audio_path)
        if sr != TARGET_SR:
            waveform = torchaudio.functional.resample(waveform, sr, TARGET_SR)
            sr = TARGET_SR
        if waveform.shape[0] > 1:  # downmix to mono
            waveform = waveform.mean(dim=0, keepdim=True)

        regions: list[dict[str, Any]] = []
        embeddings: list[list[float]] = []
        total = max(len(boundaries), 1)
        for idx, row in enumerate(boundaries):
            if should_cancel is not None and should_cancel():
                break
            start = float(row[0])
            end = float(row[1])
            a = int(start * sr)
            b = int(end * sr)
            chunk = waveform[:, a:b]
            if chunk.shape[1] <= 0:
                continue
            with torch.no_grad():
                emb = self._encoder.encode_batch(chunk)
            vec = emb.squeeze().detach().cpu().tolist()
            if isinstance(vec, float):  # 1-D degenerate guard
                vec = [vec]
            regions.append({"start": start, "end": end})
            embeddings.append([float(x) for x in vec])
            if on_progress is not None:
                on_progress(5.0 + (idx + 1) / total * 75.0, f"embedding region {idx + 1}/{total}")
        return regions, embeddings


__all__ = ["TARGET_SR", "SpeechBrainDiarizer"]
