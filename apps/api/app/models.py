from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class MediaAsset(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    kind: str = Field(description="Type of asset, e.g., video, audio, subtitle")
    uri: Optional[str] = Field(default=None, description="Storage URI or path for the asset")
    mime_type: Optional[str] = Field(default=None)
    duration: Optional[float] = Field(default=None, description="Duration in seconds if known")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class Job(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    job_type: str = Field(description="Pipeline type, e.g., transcribe, translate, shorts")
    status: JobStatus = Field(default=JobStatus.queued, index=True)
    progress: float = Field(default=0.0, description="0-1.0 progress fraction")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON), description="Options or parameters for the job")

    input_asset_id: Optional[UUID] = Field(default=None, foreign_key="mediaasset.id")
    output_asset_id: Optional[UUID] = Field(default=None, foreign_key="mediaasset.id")

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SubtitleStylePreset(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str
    description: Optional[str] = Field(default=None)
    style: dict = Field(default_factory=dict, sa_column=Column(JSON), description="Serialized style payload")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
