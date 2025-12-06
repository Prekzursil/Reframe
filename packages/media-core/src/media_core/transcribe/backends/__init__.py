"""Transcription backends."""

from .faster_whisper import normalize_faster_whisper, transcribe_faster_whisper
from .openai_whisper import transcribe_openai_file

__all__ = [
    "transcribe_openai_file",
    "transcribe_faster_whisper",
    "normalize_faster_whisper",
]
