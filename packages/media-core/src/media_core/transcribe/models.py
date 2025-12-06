from __future__ import annotations

from typing import Iterable, List, Optional

from pydantic import BaseModel, Field, model_validator


class Word(BaseModel):
    text: str = Field(..., description="The transcribed word text.")
    start: float = Field(..., ge=0.0, description="Start time in seconds.")
    end: float = Field(..., gt=0.0, description="End time in seconds.")
    probability: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence score.",
    )

    @model_validator(mode="after")
    def _validate_order(self) -> "Word":
        if self.end <= self.start:
            msg = f"Word '{self.text}' has non-positive duration: start={self.start}, end={self.end}"
            raise ValueError(msg)
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class TranscriptionResult(BaseModel):
    words: List[Word] = Field(default_factory=list, description="Ordered list of words.")
    text: Optional[str] = Field(default=None, description="Full transcript if provided.")
    model: Optional[str] = Field(default=None, description="Model identifier.")
    language: Optional[str] = Field(default=None, description="Detected or provided language code.")

    @model_validator(mode="after")
    def _validate_monotonic(self) -> "TranscriptionResult":
        if not self.words:
            return self
        sorted_words = sorted(self.words, key=lambda w: w.start)
        for prev, curr in zip(sorted_words, sorted_words[1:]):
            if curr.start < prev.end:
                msg = (
                    f"Words overlap: '{prev.text}' [{prev.start}, {prev.end}) "
                    f"and '{curr.text}' [{curr.start}, {curr.end})"
                )
                raise ValueError(msg)
        # maintain sorted order
        self.words = sorted_words
        return self

    @property
    def duration(self) -> float:
        if not self.words:
            return 0.0
        return self.words[-1].end - self.words[0].start

    @classmethod
    def from_iterable(cls, words: Iterable[Word], **metadata: object) -> "TranscriptionResult":
        """Build a result from an iterable of words, sorting and validating."""
        return cls(words=list(words), **metadata)
