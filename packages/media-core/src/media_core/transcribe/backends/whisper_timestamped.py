"""whisper-timestamped / whisperX transcription backend with graceful fallbacks."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

from media_core.transcribe.config import TranscriptionConfig
from media_core.transcribe.models import TranscriptionResult, Word
from media_core.transcribe.path_guard import validate_media_input_path

logger = logging.getLogger(__name__)


def _coerce_probability(value: Any) -> Optional[float]:
    """Coerce a probability/score payload value to float, or None if unusable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_word(w: dict[str, Any]) -> Optional[Word]:
    """Parse a single word payload into a Word, or None if malformed."""
    try:
        start = float(w["start"])
        end = float(w["end"])
        text = str(w.get("word") or w.get("text") or "").strip()
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("Skipping malformed word payload: %s (%s)", w, exc)
        return None
    prob = w.get("probability") or w.get("score")
    return Word(text=text, start=start, end=end, probability=_coerce_probability(prob))


def _extract_words(segments: Iterable[dict[str, Any]] | None) -> list[Word]:
    """Extract all parseable words from the given segments."""
    words: list[Word] = []
    for seg in segments or []:
        for w in seg.get("words", []) or []:
            parsed = _parse_word(w)
            if parsed is not None:
                words.append(parsed)
    return words


def _resolve_full_text(
    response: dict[str, Any] | Iterable[dict[str, Any]],
    segments: Any,
) -> Optional[str]:
    """Resolve the full transcript text from the response or its segments."""
    if not isinstance(response, dict):
        return None
    full_text = response.get("text") or None
    if full_text or not segments:
        return full_text
    return " ".join((seg.get("text") or "").strip() for seg in segments if seg.get("text"))


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
    words = _extract_words(segments)
    full_text = _resolve_full_text(response, segments)

    return TranscriptionResult(words=words, text=full_text, model=model, language=language)


def transcribe_whisper_timestamped(
    path: str | Path, config: TranscriptionConfig
) -> TranscriptionResult:
    """Placeholder transcription using whisper-timestamped-style payloads if present.

    If the provided path points to a JSON file with `segments`, it will be parsed
    and normalized. Otherwise, returns a stub result so downstream callers don't crash.
    """
    media_path = validate_media_input_path(path)

    if media_path.suffix.lower() == ".json":
        data = json.loads(media_path.read_text(encoding="utf-8"))
        return normalize_whisper_timestamped(data, model=config.model, language=config.language)

    # If whisper_timestamped is installed, attempt a real transcription.
    try:  # pragma: no cover - optional dependency
        # pylint: disable=import-outside-toplevel,import-error
        import whisper_timestamped as wts  # type: ignore

        audio = wts.load_audio(str(media_path))
        model_name = config.model or "base"
        model = wts.load_model(model_name)
        result = wts.transcribe(model, audio, language=config.language)
        return normalize_whisper_timestamped(result, model=model_name, language=config.language)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("whisper_timestamped unavailable or failed (%s); returning stub result", exc)

    # Fallback stub when no structured payload is available.
    return TranscriptionResult.from_iterable(
        [Word(text=media_path.name, start=0.0, end=1.0)],
        model=config.model,
        language=config.language,
    )
