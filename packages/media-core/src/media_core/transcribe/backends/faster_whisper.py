from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word

logger = logging.getLogger(__name__)


_MODEL_ALIASES: dict[str, str] = {
    # UI / config-friendly names -> faster-whisper model ids
    "whisper-large-v3": "large-v3",
    "openai/whisper-large-v3": "large-v3",
    "whisper-large-v2": "large-v2",
    "openai/whisper-large-v2": "large-v2",
    "whisper-large": "large",
    "openai/whisper-large": "large",
    "whisper-medium": "medium",
    "openai/whisper-medium": "medium",
    "whisper-small": "small",
    "openai/whisper-small": "small",
    "whisper-base": "base",
    "openai/whisper-base": "base",
    "whisper-tiny": "tiny",
    "openai/whisper-tiny": "tiny",
}


def _normalize_model_name(model: str) -> str:
    raw = (model or "").strip()
    if not raw:
        return raw
    lowered = raw.lower()
    return _MODEL_ALIASES.get(lowered, raw)


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
    segment_texts: list[str] = []
    for seg in segments:
        if isinstance(seg, dict):
            seg_text = str(seg.get("text", "")).strip()
            seg_words = seg.get("words")
        else:
            seg_text = str(getattr(seg, "text", "")).strip()
            seg_words = getattr(seg, "words", None)

        if seg_text:
            segment_texts.append(seg_text)
        if not seg_words:
            continue
        for w in seg_words:
            try:
                if isinstance(w, dict):
                    start = float(w.get("start"))
                    end = float(w.get("end"))
                    text = str(w.get("word", "")).strip()
                    prob = w.get("probability")
                else:
                    start = float(getattr(w, "start"))
                    end = float(getattr(w, "end"))
                    text = str(getattr(w, "word", "")).strip()
                    prob = getattr(w, "probability", None)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Skipping malformed word payload: %s (%s)", w, exc)
                continue
            try:
                prob_val = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                prob_val = None
            words.append(Word(text=text, start=start, end=end, probability=prob_val))

    text_field = " ".join(segment_texts) or None

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

    model_name = _normalize_model_name(config.model)
    model = WhisperModel(model_name, **model_kwargs)
    segments, _info = model.transcribe(str(media_path), language=config.language)
    return normalize_faster_whisper(segments, model=model_name, language=config.language)
