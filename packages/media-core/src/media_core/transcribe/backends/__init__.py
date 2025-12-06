"""Transcription backends."""

from .openai_whisper import transcribe_openai_file

__all__ = ["transcribe_openai_file"]
