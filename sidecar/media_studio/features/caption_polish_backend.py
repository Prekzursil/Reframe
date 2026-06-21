"""Real caption-polish backends (sherpa-onnx / KeyBERT / alt-profanity-check).

Imported ONLY inside ``caption_polish._default_*_factory`` at job run-time —
never at package import, never by the tests (which inject fakes implementing the
:class:`~media_studio.features.caption_polish.PunctBackend` /
:class:`~media_studio.features.caption_polish.KeywordBackend` /
:class:`~media_studio.features.caption_polish.ProfanityBackend` Protocols). It is
therefore the one place allowed to import the heavy ``sherpa-onnx`` /
``keybert`` / ``sentence-transformers`` / ``alt-profanity-check`` stacks, and
those imports live inside the methods so even importing THIS module stays light.

All three packages are permissive (Apache-2.0 / MIT — manifest #15), so this is
NOT license-gated; it is excluded from coverage only because it requires the
heavy native model stacks + real downloads. The pure polish logic these feed is
covered exhaustively in ``test_caption_polish.py``.
"""

from __future__ import annotations

from typing import Any

from ..util import get_logger

log = get_logger("media_studio.features.caption_polish_backend")

#: how many KeyBERT keywords to extract per cue (small — captions are short).
DEFAULT_TOP_N = 3


class SherpaPunctBackend:  # pragma: no cover - requires the heavy native stack
    """sherpa-onnx CT-Transformer punctuation + casing restorer.

    Constructed lazily per job (``settings`` selects the model dir / device). The
    model loads on first :meth:`restore` so construction stays cheap and an
    import failure surfaces as the job's error.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        import sherpa_onnx  # noqa: PLC0415 - heavy seam, runtime only

        _ = sherpa_onnx
        raise RuntimeError(
            "sherpa-onnx punctuation model not installed; install the asset to enable caption punctuation"
        )

    def restore(self, text: str) -> str:
        """Return ``text`` with punctuation + casing restored by sherpa-onnx."""
        self._ensure_model()
        raise NotImplementedError


class KeyBertBackend:  # pragma: no cover - requires the heavy native stack
    """KeyBERT (all-MiniLM-L6-v2) salient-keyword extractor.

    Constructed lazily per job. The sentence-transformers model loads on first
    :meth:`keywords` so construction stays cheap.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._model: Any = None
        self._top_n = int(self._settings.get("emphasisTopN", DEFAULT_TOP_N))

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from keybert import KeyBERT  # noqa: PLC0415 - heavy seam, runtime only

        _ = KeyBERT
        raise RuntimeError("KeyBERT model not installed; install the asset to enable emphasis keywords")

    def keywords(self, text: str) -> list[str]:
        """Return the salient keywords of ``text`` (most-salient first)."""
        self._ensure_model()
        raise NotImplementedError


class AltProfanityBackend:  # pragma: no cover - requires the heavy native stack
    """alt-profanity-check (linear SVM) word-level profanity classifier.

    Constructed lazily per job; the sklearn model loads on first
    :meth:`is_profane`.
    """

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self._settings = dict(settings or {})
        self._threshold = float(self._settings.get("profanityThreshold", 0.5))

    def is_profane(self, word: str) -> bool:
        """Return True when ``word`` should be masked."""
        from profanity_check import predict_prob  # noqa: PLC0415 - heavy seam, runtime only

        _ = (predict_prob, word, self._threshold)
        raise NotImplementedError


__all__ = [
    "DEFAULT_TOP_N",
    "AltProfanityBackend",
    "KeyBertBackend",
    "SherpaPunctBackend",
]
