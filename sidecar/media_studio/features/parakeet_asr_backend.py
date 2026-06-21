"""Real NeMo Parakeet-TDT-0.6b-v3 loader (LAZY-imported only).

Imported ONLY inside ``parakeet_asr._default_loader`` at run-time — never at
package import, never by the tests (which inject a fake
:class:`~media_studio.features.parakeet_asr.ParakeetLoader`). It is therefore
the one place allowed to import ``nemo_toolkit`` / ``torch`` and pull the model
weights, and those imports live inside the methods so even importing THIS module
stays light.

Coverage of this module is excluded (it requires the heavy native stack + real
model weights); the pure ASR plumbing it feeds — chunking, merge, normalizers,
CPU fallback, the offline degrade — is covered exhaustively in
``test_parakeet_asr.py`` via an injected fake loader.
"""

from __future__ import annotations

from typing import Any

from ..util import get_logger

log = get_logger("media_studio.features.parakeet_asr_backend")


class _RealParakeetModel:  # pragma: no cover - requires the heavy native stack
    """Adapts NeMo's ``EncDecRNNTBPEModel`` to the ``ParakeetModel`` Protocol.

    Wraps NeMo's ``transcribe`` output (a hypotheses list carrying
    word-level timestamps when ``timestamps=True``) into the segment-like shape
    the pure normalizers in ``parakeet_asr`` expect.
    """

    def __init__(self, model: Any) -> None:
        self._model = model

    def transcribe(self, audio: str, **kwargs: Any) -> Any:
        language = kwargs.get("language")
        # NeMo decodes the whole file; the chunking caller passes offset/duration
        # for bookkeeping but NeMo's CLI-level path transcribes per-file. A real
        # 6 GB build would pre-slice the audio to ``[offset, offset+duration)``
        # before calling this; here we forward the path + request timestamps.
        hyps = self._model.transcribe([audio], timestamps=True)
        hyp = hyps[0] if hyps else None
        segments = _hyp_to_segments(hyp)
        return {
            "segments": segments,
            "info": {"language": language or ""},
        }


def _hyp_to_segments(hyp: Any) -> list[dict[str, Any]]:  # pragma: no cover - heavy seam
    """Convert a NeMo hypothesis with word timestamps into segment dicts."""
    if hyp is None:
        return []
    timestamp = getattr(hyp, "timestamp", None) or {}
    seg_stamps = timestamp.get("segment") if isinstance(timestamp, dict) else None
    word_stamps = timestamp.get("word") if isinstance(timestamp, dict) else None
    words = [
        {"text": w.get("word", ""), "start": w.get("start", 0.0), "end": w.get("end", 0.0)} for w in (word_stamps or [])
    ]
    if seg_stamps:
        return [
            {
                "start": s.get("start", 0.0),
                "end": s.get("end", 0.0),
                "text": s.get("segment", ""),
                "words": [w for w in words if s.get("start", 0.0) <= w["start"] < s.get("end", 0.0)],
            }
            for s in seg_stamps
        ]
    text = getattr(hyp, "text", "") or ""
    end = words[-1]["end"] if words else 0.0
    return [{"start": 0.0, "end": end, "text": text, "words": words}]


class RealParakeetLoader:  # pragma: no cover - requires the heavy native stack
    """Default loader: lazily imports ``nemo_toolkit`` and builds a model.

    The import lives inside :meth:`load` (not at module scope) so importing this
    module never pulls in NeMo / its native deps. Models are cached per
    (model, device, compute_type) so a job that transcribes after a device
    fallback does not rebuild needlessly (mirrors ``FasterWhisperLoader``).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], _RealParakeetModel] = {}

    def load(self, model: str, device: str, compute_type: str) -> _RealParakeetModel:
        key = (model, device, compute_type)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        import torch  # noqa: PLC0415 - heavy seam, runtime only
        from nemo.collections.asr.models import ASRModel  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        asr = ASRModel.from_pretrained(model_name=model)
        target = device if (device != "cuda" or torch.cuda.is_available()) else "cpu"
        asr = asr.to(target)
        asr.eval()
        built = _RealParakeetModel(asr)
        self._cache[key] = built
        log.info("parakeet ready on %s (%s)", target, compute_type)
        return built

    def release(self) -> None:
        """Drop cached models so the single-heavy-model budget is freed (§7)."""
        self._cache.clear()


__all__ = ["RealParakeetLoader"]
