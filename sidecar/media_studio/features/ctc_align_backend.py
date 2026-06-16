"""Real ctc-forced-aligner backend for word timing (LAZY-imported only).

Imported ONLY inside ``ctc_align._default_backend_factory`` at job run-time —
never at package import, never by the tests (which inject a fake
:class:`~media_studio.features.ctc_align.CtcAlignBackend`). It is therefore the
one place allowed to import ``ctc_forced_aligner`` / ``torch``, and those imports
live inside the methods so even importing THIS module stays light.

The :class:`RealCtcAlignBackend` drives the standard ctc-forced-aligner pipeline
(``load_alignment_model`` -> ``generate_emissions`` -> ``get_alignments`` ->
``get_spans`` -> ``postprocess_results``) and adapts its word segments into the
pure layer's :class:`~media_studio.features.ctc_align.WordSpan` list.

The model id is injected (Decision #1): the CC-BY-NC MMS default for the local
tool, or an MIT wav2vec2 id for the commercial build. Models resolve from the
standard HF cache that ``assets.ensure`` populates, so a machine that pre-fetched
the asset runs this fully offline.

Coverage of this module is excluded (it requires the heavy native stack + real
audio); the pure pipeline it feeds is covered exhaustively in ``test_ctc_align.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..util import get_logger
from .ctc_align import CancelProbe, ProgressCb, WordSpan

if TYPE_CHECKING:
    import numpy as np

log = get_logger("media_studio.features.ctc_align_backend")

#: ctc-forced-aligner operates at 16 kHz mono (the CTC models' training rate).
TARGET_SR = 16000


class RealCtcAlignBackend:  # pragma: no cover - requires the heavy native stack
    """Force-align word tokens against audio with the ctc-forced-aligner stack.

    Constructed lazily per job with the resolved ``model_id`` (Decision #1). The
    alignment model + tokenizer are loaded on first :meth:`align` so construction
    stays cheap and an import failure surfaces as the job's error.
    """

    def __init__(self, settings: dict[str, Any] | None = None, model_id: str = "") -> None:
        self._settings = dict(settings or {})
        self._model_id = model_id
        self._model: Any = None
        self._tokenizer: Any = None

    def _device(self) -> str:
        """Prefer CUDA, fall back to CPU (mirrors transcribe's policy)."""
        try:
            import torch  # noqa: PLC0415 - heavy seam, runtime only

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:  # noqa: BLE001 - no torch -> CPU path (still works)
            return "cpu"

    def _ensure_model(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return
        import torch  # noqa: PLC0415
        from ctc_forced_aligner import load_alignment_model  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        device = self._device()
        dtype = torch.float16 if device == "cuda" else torch.float32
        self._model, self._tokenizer = load_alignment_model(
            device,
            self._model_id,
            dtype=dtype,
        )
        log.info("ctc-forced-aligner ready on %s (model=%s)", device, self._model_id)

    def align(
        self,
        samples: np.ndarray,
        sr: int,
        tokens: Any,
        *,
        language: str | None = None,
        on_progress: ProgressCb | None = None,
        should_cancel: CancelProbe | None = None,
    ) -> list[WordSpan]:
        """Force-align ``tokens`` to ``samples`` and return one span per token."""
        import numpy as np  # noqa: PLC0415
        import torch  # noqa: PLC0415
        from ctc_forced_aligner import (  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
            generate_emissions,
            get_alignments,
            get_spans,
            postprocess_results,
            preprocess_text,
        )

        self._ensure_model()
        if on_progress is not None:
            on_progress(10.0, "generating emissions")

        device = self._device()
        waveform = torch.from_numpy(np.asarray(samples, dtype=np.float32)).to(device)
        if sr != TARGET_SR:
            import torchaudio  # noqa: PLC0415

            waveform = torchaudio.functional.resample(waveform, sr, TARGET_SR)

        emissions, stride = generate_emissions(self._model, waveform, batch_size=1)
        if should_cancel is not None and should_cancel():
            return []

        text = " ".join(str(t) for t in tokens)
        tokens_starred, text_starred = preprocess_text(
            text,
            romanize=True,
            language=language or "eng",
        )
        if on_progress is not None:
            on_progress(60.0, "aligning")

        segments, scores, blank_token = get_alignments(
            emissions,
            tokens_starred,
            self._tokenizer,
        )
        spans = get_spans(tokens_starred, segments, blank_token)
        word_timestamps = postprocess_results(text_starred, spans, stride, scores)

        out: list[WordSpan] = []
        for item in word_timestamps:
            out.append(
                WordSpan(
                    text=str(item.get("text", "")),
                    start=float(item.get("start", 0.0)),
                    end=float(item.get("end", 0.0)),
                    score=float(item.get("score", 1.0)),
                )
            )
        if on_progress is not None:
            on_progress(100.0, "done")
        return out


__all__ = ["TARGET_SR", "RealCtcAlignBackend"]
