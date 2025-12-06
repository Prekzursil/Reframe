"""Transcription utilities and models for Reframe."""

from pathlib import Path

from .backends import (
    normalize_faster_whisper,
    transcribe_faster_whisper,
    transcribe_openai_file,
    normalize_whisper_cpp,
    transcribe_whisper_cpp,
    transcribe_whisper_timestamped,
)
from .config import TranscriptionBackend, TranscriptionConfig
from .models import TranscriptionResult, Word

__all__ = [
    "TranscriptionBackend",
    "TranscriptionConfig",
    "TranscriptionResult",
    "Word",
    "transcribe_openai_file",
    "transcribe_faster_whisper",
    "normalize_faster_whisper",
    "transcribe_whisper_cpp",
    "normalize_whisper_cpp",
    "transcribe_whisper_timestamped",
    "transcribe_noop",
]


def transcribe_noop(path: str | Path, config: TranscriptionConfig | None = None) -> TranscriptionResult:
    """Lightweight fallback used by CLI when no backend is available."""
    name = Path(path).name
    word = Word(text=name or "noop", start=0.0, end=1.0)
    return TranscriptionResult(words=[word], text=name, model=(config.model if config else "noop"), language=getattr(config, "language", None))
