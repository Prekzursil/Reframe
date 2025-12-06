from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, List, Optional
from uuid import uuid4

from celery import Celery
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from uuid import UUID

from sqlmodel import Session, SQLModel, select

from app.database import get_session
from app.config import get_settings
from app.errors import ErrorResponse, conflict, not_found, server_error
from app.models import Job, JobStatus, MediaAsset, SubtitleStylePreset
from app.rate_limit import enforce_rate_limit
from fastapi.responses import FileResponse


router = APIRouter(prefix="/api/v1")


SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache(maxsize=1)
def get_celery_app() -> Celery:
    settings = get_settings()
    return Celery("reframe_api", broker=settings.broker.broker_url, backend=settings.broker.result_backend)


def enqueue_job(job: Job, task_name: str, *args) -> str:
    try:
        result = get_celery_app().send_task(task_name, args=args)
        return result.id
    except Exception as exc:  # pragma: no cover - defensive
        raise server_error("Failed to enqueue job", details={"job_id": str(job.id), "task": task_name, "error": str(exc)})


def save_and_dispatch(job: Job, session: Session, task_name: str, *args) -> Job:
    session.add(job)
    session.commit()
    session.refresh(job)
    task_id = enqueue_job(job, task_name, *args)
    job.task_id = task_id
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


class CaptionJobRequest(SQLModel):
    video_asset_id: UUID
    options: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000001",
                "options": {"language": "en", "backend": "whisper"},
            }
        }
    }


class TranslateJobRequest(SQLModel):
    subtitle_asset_id: UUID
    target_language: str
    options: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "subtitle_asset_id": "00000000-0000-0000-0000-000000000002",
                "target_language": "es",
                "options": {"formality": "informal"},
            }
        }
    }


class TranslateSubtitleToolRequest(SQLModel):
    subtitle_asset_id: UUID
    target_language: str
    bilingual: bool = False
    options: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "subtitle_asset_id": "00000000-0000-0000-0000-000000000002",
                "target_language": "es",
                "bilingual": True,
                "options": {"preserve_timing": True},
            }
        }
    }


class ShortsJobRequest(SQLModel):
    video_asset_id: UUID
    max_clips: int = 3
    min_duration: float = 10.0
    max_duration: float = 60.0
    aspect_ratio: str = "9:16"
    options: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000003",
                "max_clips": 3,
                "min_duration": 10,
                "max_duration": 45,
                "aspect_ratio": "9:16",
                "options": {"prompt": "Highlight the key moments"},
            }
        }
    }


class MergeAVRequest(SQLModel):
    video_asset_id: UUID
    audio_asset_id: UUID
    offset: float = 0.0
    ducking: bool = False
    normalize: bool = True
    options: Optional[dict] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000004",
                "audio_asset_id": "00000000-0000-0000-0000-000000000005",
                "offset": 0.5,
                "ducking": True,
                "normalize": True,
                "options": {"target_lufs": -14},
            }
        }
    }


class StyledSubtitleJobRequest(SQLModel):
    video_asset_id: UUID
    subtitle_asset_id: UUID
    style: dict
    preview_seconds: Optional[int] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000001",
                "subtitle_asset_id": "00000000-0000-0000-0000-000000000002",
                "style": {"font": "Inter", "text_color": "#ffffff"},
                "preview_seconds": 5,
            }
        }
    }


@router.post(
    "/captions/jobs",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Captions"],
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_rate_limit)],
)
def create_caption_job(payload: CaptionJobRequest, session: SessionDep) -> Job:
    job = Job(job_type="captions", status=JobStatus.queued, progress=0.0, input_asset_id=payload.video_asset_id, payload=payload.options or {})
    return save_and_dispatch(job, session, "tasks.generate_captions", str(job.id), str(payload.video_asset_id), payload.options or {})


@router.post(
    "/subtitles/translate",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Translate"],
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_rate_limit)],
)
def create_translate_job(payload: TranslateJobRequest, session: SessionDep) -> Job:
    job = Job(job_type="translate_subtitles", status=JobStatus.queued, progress=0.0, input_asset_id=payload.subtitle_asset_id, payload={"target_language": payload.target_language, **(payload.options or {})})
    return save_and_dispatch(
        job,
        session,
        "tasks.translate_subtitles",
        str(job.id),
        str(payload.subtitle_asset_id),
        {"target_language": payload.target_language, **(payload.options or {})},
    )


@router.get(
    "/jobs/{job_id}",
    response_model=Job,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}},
)
def get_job(job_id: UUID, session: SessionDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    return job


@router.get("/jobs", response_model=List[Job], tags=["Jobs"])
def list_jobs(status_filter: Optional[JobStatus] = None, session: SessionDep = Depends(get_session)) -> List[Job]:
    query = select(Job)
    if status_filter:
        query = query.where(Job.status == status_filter)
    results = session.exec(query).all()
    return results


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=Job,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_job(job_id: UUID, session: SessionDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})

    if job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
        raise conflict("Job already finished", details={"status": job.status})

    job.status = JobStatus.cancelled
    job.progress = 0.0
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/shorts/jobs",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Shorts"],
    dependencies=[Depends(enforce_rate_limit)],
)
def create_shorts_job(payload: ShortsJobRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="shorts",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        payload={
            "max_clips": payload.max_clips,
            "min_duration": payload.min_duration,
            "max_duration": payload.max_duration,
            "aspect_ratio": payload.aspect_ratio,
            **(payload.options or {}),
        },
    )
    return save_and_dispatch(
        job,
        session,
        "tasks.generate_shorts",
        str(job.id),
        str(payload.video_asset_id),
        job.payload,
    )


@router.post(
    "/subtitles/style",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Subtitles"],
    dependencies=[Depends(enforce_rate_limit)],
)
def create_style_job(payload: StyledSubtitleJobRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="style_subtitles",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        payload={
            "subtitle_asset_id": str(payload.subtitle_asset_id),
            "style": payload.style,
            "preview_seconds": payload.preview_seconds,
        },
    )
    return save_and_dispatch(
        job,
        session,
        "tasks.render_styled_subtitles",
        str(job.id),
        str(payload.video_asset_id),
        str(payload.subtitle_asset_id),
        payload.style,
        {"preview_seconds": payload.preview_seconds},
    )


@router.post(
    "/utilities/merge-av",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Utilities"],
    dependencies=[Depends(enforce_rate_limit)],
)
def create_merge_job(payload: MergeAVRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="merge_av",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        payload={
            "audio_asset_id": str(payload.audio_asset_id),
            "offset": payload.offset,
            "ducking": payload.ducking,
            "normalize": payload.normalize,
            **(payload.options or {}),
        },
    )
    return save_and_dispatch(
        job,
        session,
        "tasks.merge_video_audio",
        str(job.id),
        str(payload.video_asset_id),
        str(payload.audio_asset_id),
        job.payload,
    )


@router.post(
    "/utilities/translate-subtitle",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Utilities"],
    dependencies=[Depends(enforce_rate_limit)],
)
def translate_subtitle_tool(payload: TranslateSubtitleToolRequest, session: SessionDep) -> Job:
    job = Job(
        job_type="translate_subtitles",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.subtitle_asset_id,
        payload={
            "target_language": payload.target_language,
            "bilingual": payload.bilingual,
            **(payload.options or {}),
        },
    )
    return save_and_dispatch(
        job,
        session,
        "tasks.translate_subtitles",
        str(job.id),
        str(payload.subtitle_asset_id),
        job.payload,
    )


@router.post(
    "/assets/upload",
    response_model=MediaAsset,
    status_code=status.HTTP_201_CREATED,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit)],
)
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form("video"),
    session: SessionDep = Depends(get_session),
) -> MediaAsset:
    settings = get_settings()
    media_root = Path(settings.media_root)
    media_root.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix
    filename = f"{uuid4()}{suffix}"
    target_dir = media_root / "tmp"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    data = await file.read()
    target_path.write_bytes(data)

    asset = MediaAsset(kind=kind, uri=f"/media/tmp/{filename}", mime_type=file.content_type)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get(
    "/assets/{asset_id}",
    response_model=MediaAsset,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}},
)
def get_asset(asset_id: UUID, session: SessionDep) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    return asset


@router.get(
    "/assets/{asset_id}/download",
    response_class=FileResponse,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}},
)
def download_asset(asset_id: UUID, session: SessionDep) -> FileResponse:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    settings = get_settings()
    uri_path = Path(asset.uri.lstrip("/"))
    if uri_path.parts and uri_path.parts[0] == "media":
        uri_path = Path(*uri_path.parts[1:])
    file_path = Path(settings.media_root) / uri_path
    if not file_path.exists():
        raise not_found("Asset file missing", details={"asset_id": str(asset_id), "path": str(file_path)})
    return FileResponse(path=file_path, media_type=asset.mime_type or "application/octet-stream", filename=file_path.name)


@router.get("/presets/styles", response_model=List[SubtitleStylePreset], tags=["Presets"])
def list_style_presets(session: SessionDep) -> List[SubtitleStylePreset]:
    presets = session.exec(select(SubtitleStylePreset)).all()
    return presets
