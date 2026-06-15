from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DiarizationBackend(StrEnum):
    NOOP = "noop"
    PYANNOTE = "pyannote"
    SPEECHBRAIN = "speechbrain"


class DiarizationConfig(BaseModel):
    """Config describing how speaker diarization should run."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    backend: DiarizationBackend = Field(
        default=DiarizationBackend.NOOP,
        description="Which backend to use for diarization.",
    )
    model: str = Field(
        default="pyannote/speaker-diarization-3.1",
        description="Model/pipeline id for the selected backend.",
    )
    huggingface_token: str | None = Field(
        default=None,
        description="Optional Hugging Face token for gated/private models (pyannote).",
    )
    min_segment_duration: float = Field(
        default=0.0,
        ge=0.0,
        description="Drop speaker segments shorter than this duration (seconds).",
    )
