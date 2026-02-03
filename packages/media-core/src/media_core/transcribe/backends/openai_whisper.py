from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word

logger = logging.getLogger(__name__)


def _ensure_openai():
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "openai package is required for the OpenAI Whisper backend. "
            "Install with `pip install openai`."
        ) from exc
    return openai


def normalize_verbose_json(
    verbose_json: dict[str, Any],
    *,
    model: Optional[str],
    language: Optional[str],
) -> TranscriptionResult:
    """Normalize OpenAI verbose_json response to TranscriptionResult."""
    segments: Iterable[dict[str, Any]] = verbose_json.get("segments", []) or []
    words: list[Word] = []
    for segment in segments:
        for w in segment.get("words", []) or []:
            try:
                start = float(w["start"])
                end = float(w["end"])
                text = str(w["word"]).strip()
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug("Skipping malformed word payload: %s (%s)", w, exc)
                continue
            prob = w.get("probability")
            try:
                prob_val = float(prob) if prob is not None else None
            except (TypeError, ValueError):
                prob_val = None
            words.append(Word(text=text, start=start, end=end, probability=prob_val))

    text_field = verbose_json.get("text") or None
    return TranscriptionResult(words=words, text=text_field, model=model, language=language)


def transcribe_openai_file(path: str | Path, config: TranscriptionConfig) -> TranscriptionResult:
    """Transcribe a media file using OpenAI Whisper."""
    if os.getenv("REFRAME_OFFLINE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("REFRAME_OFFLINE_MODE is enabled; refusing to call OpenAI transcription API.")
    openai = _ensure_openai()
    client = openai.OpenAI()
    media_path = Path(path)
    if not media_path.is_file():
        raise FileNotFoundError(media_path)

    with media_path.open("rb") as f:
        # OpenAI SDK expects a file-like object; also send a filename hint.
        file_obj = io.BufferedReader(f)
        response = client.audio.transcriptions.create(
            model=config.model,
            file=file_obj,
            language=config.language,
            temperature=config.temperature,
            response_format="verbose_json",
        )

    return normalize_verbose_json(response, model=config.model, language=config.language)
