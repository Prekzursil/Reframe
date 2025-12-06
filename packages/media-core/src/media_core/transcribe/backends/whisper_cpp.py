from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word

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


def normalize_whisper_cpp(
    segments: Iterable[_SegmentLike] | Iterable[dict[str, Any]],
    *,
    model: Optional[str],
    language: Optional[str],
) -> TranscriptionResult:
    """Normalize whisper.cpp-style segments into TranscriptionResult."""
    words: list[Word] = []
    for seg in segments:
        tokens = getattr(seg, "tokens", None) or getattr(seg, "get", lambda k, d=None: d)("tokens", None)
        if tokens:
            for tok in tokens:
                try:
                    start = float(getattr(tok, "t_start", tok.get("t_start")))
                    end = float(getattr(tok, "t_end", tok.get("t_end")))
                    text = str(getattr(tok, "text", tok.get("text"))).strip()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("Skipping malformed token: %s (%s)", tok, exc)
                    continue
                words.append(Word(text=text, start=start, end=end, probability=None))
        else:
            try:
                start = float(getattr(seg, "t_start", seg.get("t_start")))
                end = float(getattr(seg, "t_end", seg.get("t_end")))
                text = str(getattr(seg, "text", seg.get("text"))).strip()
            except Exception:
                continue
            if text:
                words.append(Word(text=text, start=start, end=end, probability=None))

    text_field = None
    try:
        text_field = " ".join(getattr(s, "text", s.get("text", "")).strip() for s in segments) or None
    except Exception:
        text_field = None

    return TranscriptionResult(words=words, text=text_field, model=model, language=language)


def transcribe_whisper_cpp(path: str | Path, config: TranscriptionConfig) -> TranscriptionResult:
    """Transcribe using whisper.cpp (pywhispercpp), if installed."""
    _ensure_whispercpp()
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    raise NotImplementedError(
        "whisper.cpp integration requires runtime model loading; not executed in this scaffold."
    )
