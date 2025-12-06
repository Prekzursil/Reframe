from __future__ import annotations

from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, SQLModel, select

from app.database import get_session
from app.models import Job

router = APIRouter(prefix="/api/v1")


SessionDep = Annotated[Session, Depends(get_session)]


class CaptionJobRequest(SQLModel):
    video_asset_id: UUID
    options: Optional[dict] = None


class TranslateJobRequest(SQLModel):
    subtitle_asset_id: UUID
    target_language: str
    options: Optional[dict] = None


@router.post("/captions/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_caption_job(payload: CaptionJobRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="captions",
        status="queued",
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        payload=payload.options or {},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post("/subtitles/translate", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_translate_job(payload: TranslateJobRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="translate_subtitles",
        status="queued",
        progress=0.0,
        input_asset_id=payload.subtitle_asset_id,
        payload={"target_language": payload.target_language, **(payload.options or {})},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: UUID, session: SessionDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/jobs", response_model=List[Job])
def list_jobs(status_filter: Optional[str] = None, session: SessionDep = Depends(get_session)) -> List[Job]:
    query = select(Job)
    if status_filter:
        query = query.where(Job.status == status_filter)
    results = session.exec(query).all()
    return results
