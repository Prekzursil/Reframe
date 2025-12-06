"""Transcription utilities and models for Reframe."""

from .backends import transcribe_openai_file
from .config import TranscriptionBackend, TranscriptionConfig
from .models import TranscriptionResult, Word

__all__ = [
    "TranscriptionBackend",
    "TranscriptionConfig",
    "TranscriptionResult",
    "Word",
    "transcribe_openai_file",
]
