from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word
from media_core.transcribe.path_guard import validate_media_input_path

logger = logging.getLogger(__name__)


class _TokenLike(Protocol):
    text: str
    t_start: float
    t_end: float


class _SegmentLike(Protocol):
    text: str
    t_start: float
    t_end: float
    tokens: list[_TokenLike]


def _ensure_whispercpp():
    try:
        import whispercpp  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "whispercpp package is required. Install with `pip install whispercpp`."
        ) from exc
    return whispercpp


def _get_tokens(seg: Any) -> Any:
    return getattr(seg, "tokens", None) or getattr(seg, "get", lambda k, d=None: d)("tokens", None)


def _parse_token_word(tok: Any) -> Word | None:
    try:
        start = float(getattr(tok, "t_start", tok.get("t_start")))
        end = float(getattr(tok, "t_end", tok.get("t_end")))
        text = str(getattr(tok, "text", tok.get("text"))).strip()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Skipping malformed token: %s (%s)", tok, exc)
        return None
    return Word(text=text, start=start, end=end, probability=None)


def _parse_segment_word(seg: Any) -> Word | None:
    try:
        start = float(getattr(seg, "t_start", seg.get("t_start")))
        end = float(getattr(seg, "t_end", seg.get("t_end")))
        text = str(getattr(seg, "text", seg.get("text"))).strip()
    except Exception:
        return None
    if not text:
        return None
    return Word(text=text, start=start, end=end, probability=None)


def _segment_words(seg: Any) -> list[Word]:
    tokens = _get_tokens(seg)
    if tokens:
        return [w for tok in tokens if (w := _parse_token_word(tok)) is not None]
    word = _parse_segment_word(seg)
    return [word] if word is not None else []


def _join_segment_text(segments: Iterable[Any]) -> Optional[str]:
    try:
        return " ".join(getattr(s, "text", s.get("text", "")).strip() for s in segments) or None
    except Exception:
        return None


def normalize_whisper_cpp(
    segments: Iterable[_SegmentLike] | Iterable[dict[str, Any]],
    *,
    model: Optional[str],
    language: Optional[str],
) -> TranscriptionResult:
    """Normalize whisper.cpp-style segments into TranscriptionResult."""
    words: list[Word] = []
    for seg in segments:
        words.extend(_segment_words(seg))

    text_field = _join_segment_text(segments)

    return TranscriptionResult(words=words, text=text_field, model=model, language=language)


def transcribe_whisper_cpp(path: str | Path, config: TranscriptionConfig) -> TranscriptionResult:
    """Transcribe using whisper.cpp (pywhispercpp) when available, else graceful fallback."""
    media_path = validate_media_input_path(path)

    try:
        whispercpp = _ensure_whispercpp()
        # Whisper constructor accepts a model name or path. Default to config.model.
        model_name = config.model or "ggml-base.en"
        model = whispercpp.Whisper(model_name)
        segments = list(model.transcribe(media_path))
        return normalize_whisper_cpp(segments, model=model_name, language=config.language)
    except Exception as exc:  # pragma: no cover - optional dependency or runtime failure
        logger.warning("whispercpp unavailable or failed (%s); returning stub result", exc)
        return TranscriptionResult.from_iterable(
            [Word(text=media_path.name, start=0.0, end=1.0)], model="whisper_cpp_stub", language=config.language
        )
