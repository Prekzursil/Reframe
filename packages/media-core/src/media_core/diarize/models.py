from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: str

