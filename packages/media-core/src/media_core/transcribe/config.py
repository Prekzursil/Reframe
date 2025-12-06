from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TranscriptionBackend(str, Enum):
    OPENAI_WHISPER = "openai_whisper"
    FASTER_WHISPER = "faster_whisper"
    WHISPER_CPP = "whisper_cpp"


class TranscriptionConfig(BaseModel):
    """Config describing how audio should be transcribed."""

    backend: TranscriptionBackend = Field(
        default=TranscriptionBackend.OPENAI_WHISPER,
        description="Which backend to use for transcription.",
    )
    model: str = Field(
        default="whisper-1",
        description="Model name used by the selected backend.",
    )
    language: Optional[str] = Field(
        default=None,
        description="Optional ISO language code. None means auto-detect.",
    )
    device: Optional[str] = Field(
        default=None,
        description="Device hint for local backends (e.g., 'cpu', 'cuda').",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sampling temperature for stochastic backends that support it.",
    )

    class Config:
        validate_assignment = True
        extra = "forbid"
