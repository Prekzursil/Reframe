from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word

logger = logging.getLogger(__name__)


class _WordLike(Protocol):
    word: str
    start: float
    end: float
    probability: Optional[float]


class _SegmentLike(Protocol):
    text: str
    start: float
    end: float
    words: list[_WordLike]


def _ensure_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "faster-whisper package is required. Install with `pip install faster-whisper`."
        ) from exc
    return WhisperModel


def normalize_faster_whisper(
    segments: Iterable[_SegmentLike] | Iterable[dict[str, Any]],
    *,
    model: Optional[str],
    language: Optional[str],
) -> TranscriptionResult:
    """Normalize faster-whisper segments into TranscriptionResult."""
    words: list[Word] = []
    for seg in segments:
        seg_words = getattr(seg, "words", None) or getattr(seg, "get", lambda k, d=None: d)("words", None)
        if seg_words is None:
            continue
        for w in seg_words:
            try:
                start = float(getattr(w, "start", w.get("start")))
                end = float(getattr(w, "end", w.get("end")))
                text = str(getattr(w, "word", w.get("word"))).strip()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Skipping malformed word payload: %s (%s)", w, exc)
                continue
            prob = getattr(w, "probability", None)
            try:
                prob_val = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                prob_val = None
            words.append(Word(text=text, start=start, end=end, probability=prob_val))

    text_field = None
    try:
        # If the segments iterable has a first element with text, join them.
        text_field = " ".join(getattr(s, "text", s.get("text", "")).strip() for s in segments) or None
    except Exception:
        text_field = None

    return TranscriptionResult(words=words, text=text_field, model=model, language=language)


def transcribe_faster_whisper(path: str | Path, config: TranscriptionConfig) -> TranscriptionResult:
    """Transcribe a media file using faster-whisper."""
    WhisperModel = _ensure_faster_whisper()
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)

    # Use model from config; device is optional.
    model_kwargs: dict[str, Any] = {}
    if config.device:
        model_kwargs["device"] = config.device

    model = WhisperModel(config.model, **model_kwargs)
    segments, _info = model.transcribe(str(media_path), language=config.language)
    return normalize_faster_whisper(segments, model=config.model, language=config.language)
