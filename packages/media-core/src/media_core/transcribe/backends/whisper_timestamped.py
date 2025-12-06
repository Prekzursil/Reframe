from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word

logger = logging.getLogger(__name__)


def normalize_whisper_timestamped(
    response: dict[str, Any] | Iterable[dict[str, Any]],
    *,
    model: Optional[str],
    language: Optional[str],
) -> TranscriptionResult:
    """Normalize whisper-timestamped / whisperX-like output into TranscriptionResult.

    Expected shape (common between whisper-timestamped and whisperX):
    {
        "segments": [
            {
                "text": "...",
                "start": float,
                "end": float,
                "words": [{"word": str, "start": float, "end": float, "probability": float}, ...]
            },
            ...
        ],
        "text": "full transcript"
    }
    """

    segments = response.get("segments", []) if isinstance(response, dict) else response
    words: list[Word] = []
    for seg in segments or []:
        for w in seg.get("words", []) or []:
            try:
                start = float(w["start"])
                end = float(w["end"])
                text = str(w.get("word") or w.get("text") or "").strip()
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug("Skipping malformed word payload: %s (%s)", w, exc)
                continue
            prob = w.get("probability") or w.get("score")
            try:
                prob_val = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                prob_val = None
            words.append(Word(text=text, start=start, end=end, probability=prob_val))

    full_text = None
    if isinstance(response, dict):
        full_text = response.get("text") or None
        if not full_text and segments:
            full_text = " ".join((seg.get("text") or "").strip() for seg in segments if seg.get("text"))

    return TranscriptionResult(words=words, text=full_text, model=model, language=language)


def transcribe_whisper_timestamped(path: str | Path, config: TranscriptionConfig) -> TranscriptionResult:
    """Placeholder: integrate with whisper-timestamped/whisperX at runtime."""
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    raise NotImplementedError(
        "whisper-timestamped/whisperX integration requires runtime model loading; not executed in scaffold."
    )
