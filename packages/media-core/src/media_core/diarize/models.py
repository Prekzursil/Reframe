"""Data models for speaker diarization results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerSegment:
    """A time-bounded segment attributed to a single speaker."""

    start: float
    end: float
    speaker: str
