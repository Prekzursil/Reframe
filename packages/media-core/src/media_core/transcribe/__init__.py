"""Transcription utilities and models for Reframe."""

from .backends import (
    normalize_faster_whisper,
    transcribe_faster_whisper,
    transcribe_openai_file,
    normalize_whisper_cpp,
    transcribe_whisper_cpp,
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
]
