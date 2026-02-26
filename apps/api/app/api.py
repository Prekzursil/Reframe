from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, List, Optional
from uuid import uuid4

try:
    from celery import Celery
except ModuleNotFoundError:  # pragma: no cover - allows API tests without optional celery install
    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def send_task(self, *_args, **_kwargs):
            raise RuntimeError("Celery is not installed in this environment.")
from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile, status, Response
from uuid import UUID

from sqlmodel import Field, Session, SQLModel, select

from app.auth_api import PrincipalDep, ensure_default_plans
from app.billing import get_plan_policy
from app.database import get_session
from app.config import get_settings
from app.errors import ApiError, ErrorCode, ErrorResponse, conflict, not_found, quota_exceeded, server_error
from app.models import Job, JobStatus, MediaAsset, Project, Subscription, SubtitleStylePreset, UsageEvent
from app.rate_limit import enforce_rate_limit
from app.security import AuthPrincipal
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from app.share_links import build_share_token_with_ttl, parse_and_validate_share_token
from app.storage import LocalStorageBackend, get_storage, is_remote_uri

router = APIRouter(prefix="/api/v1")


SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache(maxsize=1)
def get_celery_app() -> Celery:
    settings = get_settings()
    app = Celery("reframe_api", broker=settings.broker_url, backend=settings.result_backend)
    # Fail fast when broker/backend are unavailable so API diagnostics and tests do not hang.
    app.conf.broker_connection_retry_on_startup = False
    app.conf.broker_connection_max_retries = 0
    app.conf.broker_transport_options = {
        "socket_connect_timeout": 1,
        "socket_timeout": 1,
        "max_retries": 0,
    }
    app.conf.result_backend_transport_options = {
        "socket_connect_timeout": 1,
        "socket_timeout": 1,
        "max_retries": 0,
    }
    return app


def _env_truthy(name: str) -> bool:
    raw = (os.getenv(name) or os.getenv(f"REFRAME_{name}") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _celery_queue_name(kind: str) -> str:
    key = kind.strip().upper()
    if key == "GPU":
        return (os.getenv("REFRAME_CELERY_QUEUE_GPU") or "gpu").strip() or "gpu"
    if key == "CPU":
        return (os.getenv("REFRAME_CELERY_QUEUE_CPU") or "cpu").strip() or "cpu"
    return (os.getenv("REFRAME_CELERY_QUEUE_DEFAULT") or "default").strip() or "default"


def _task_prefers_gpu(task_name: str, *args) -> bool:
    if task_name not in {"tasks.generate_captions", "tasks.transcribe_video"}:
        return False
    payload = args[-1] if args and isinstance(args[-1], dict) else {}
    backend = str(payload.get("backend") or "").strip().lower()
    device = str(payload.get("device") or "").strip().lower()
    if device in {"cuda", "gpu"}:
        return True
    if _env_truthy("ASSUME_GPU_FOR_TRANSCRIBE_BACKENDS") and backend in {"faster_whisper", "whisper_cpp", "whisper_timestamped", "whisperx"}:
        return True
    return False


def _resolve_task_queue(task_name: str, *args) -> str:
    gpu_enabled = _env_truthy("ENABLE_GPU_QUEUE")
    if task_name in {"tasks.generate_captions", "tasks.transcribe_video"}:
        if gpu_enabled and _task_prefers_gpu(task_name, *args):
            return _celery_queue_name("GPU")
        return _celery_queue_name("CPU")
    if task_name in {"tasks.generate_shorts", "tasks.render_styled_subtitles", "tasks.merge_video_audio", "tasks.cut_clip", "tasks.translate_subtitles"}:
        return _celery_queue_name("CPU")
    return _celery_queue_name("DEFAULT")


def enqueue_job(job: Job, task_name: str, *args) -> str:
    try:
        queue = _resolve_task_queue(task_name, *args)
        result = get_celery_app().send_task(task_name, args=args, queue=queue)
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


def _scope_query_by_org(query, model, principal: AuthPrincipal):
    if principal.org_id and hasattr(model, "org_id"):
        query = query.where(getattr(model, "org_id") == principal.org_id)
    return query


def _assert_org_access(*, principal: AuthPrincipal, entity_org_id: UUID | None, entity: str, entity_id: str) -> None:
    if not principal.org_id:
        return
    if entity_org_id != principal.org_id:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message=f"Access denied for {entity}",
            details={"entity_id": entity_id, "org_id": str(principal.org_id)},
        )


def _resolve_idempotency_key(payload_value: str | None, header_value: str | None) -> str | None:
    key = (payload_value or header_value or "").strip()
    if not key:
        return None
    if len(key) > 128:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Idempotency key must be at most 128 characters",
            details={"max_length": 128},
        )
    return key


def _find_existing_idempotent_job(
    *,
    session: Session,
    principal: AuthPrincipal,
    job_type: str,
    idempotency_key: str | None,
) -> Job | None:
    if not idempotency_key:
        return None
    query = select(Job).where((Job.job_type == job_type) & (Job.idempotency_key == idempotency_key))
    if principal.org_id:
        query = query.where(Job.org_id == principal.org_id)
    if principal.user_id:
        query = query.where(Job.owner_user_id == principal.user_id)
    query = query.order_by(Job.created_at.desc())
    return session.exec(query).first()


def _resolve_plan_code(session: Session, *, org_id: UUID | None) -> str:
    if not org_id:
        return "free"
    ensure_default_plans(session)
    sub = session.exec(select(Subscription).where(Subscription.org_id == org_id)).first()
    return (sub.plan_code if sub else "free") or "free"


def _enforce_org_quota(session: Session, principal: AuthPrincipal) -> None:
    settings = get_settings()
    org_id = principal.org_id
    if not org_id or not settings.enable_billing:
        return

    plan_code = _resolve_plan_code(session, org_id=org_id)
    policy = get_plan_policy(plan_code)

    running = session.exec(
        select(Job).where((Job.org_id == org_id) & (Job.status == JobStatus.running))
    ).all()
    if len(running) >= policy.max_concurrent_jobs:
        raise quota_exceeded(
            "Concurrent job limit reached",
            details={
                "plan_code": plan_code,
                "max_concurrent_jobs": policy.max_concurrent_jobs,
                "running_jobs": len(running),
            },
        )

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = session.exec(
        select(UsageEvent).where(
            (UsageEvent.org_id == org_id)
            & (UsageEvent.metric == "job_minutes")
            & (UsageEvent.created_at >= month_start)
        )
    ).all()
    used_minutes = sum(float(item.quantity or 0.0) for item in usage)
    if policy.monthly_job_minutes > 0 and used_minutes >= float(policy.monthly_job_minutes):
        raise quota_exceeded(
            "Monthly processing quota reached",
            details={
                "plan_code": plan_code,
                "quota_job_minutes": policy.monthly_job_minutes,
                "used_job_minutes": round(used_minutes, 3),
            },
        )

    storage_usage = session.exec(
        select(UsageEvent).where(
            (UsageEvent.org_id == org_id)
            & (UsageEvent.metric == "storage_bytes")
            & (UsageEvent.created_at >= month_start)
        )
    ).all()
    used_storage_bytes = sum(float(item.quantity or 0.0) for item in storage_usage)
    storage_quota_bytes = float(policy.monthly_storage_gb) * float(1024**3)
    if storage_quota_bytes > 0 and used_storage_bytes >= storage_quota_bytes:
        raise quota_exceeded(
            "Monthly storage quota reached",
            details={
                "plan_code": plan_code,
                "quota_storage_gb": policy.monthly_storage_gb,
                "used_storage_gb": round(used_storage_bytes / float(1024**3), 3),
            },
        )


def _ensure_project_exists(session: Session, project_id: UUID | None, principal: AuthPrincipal | None = None) -> Project | None:
    if not project_id:
        return None
    project = session.get(Project, project_id)
    if not project:
        raise not_found("Project not found", details={"project_id": str(project_id)})
    if principal:
        _assert_org_access(principal=principal, entity_org_id=project.org_id, entity="project", entity_id=str(project.id))
    return project


def _ensure_asset_exists(session: Session, *, asset_id: UUID, principal: AuthPrincipal, kind: str | None = None, field: str = "asset_id") -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={field: str(asset_id)})
    if kind and asset.kind != kind:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Invalid asset kind for {field}",
            details={"expected_kind": kind, "actual_kind": asset.kind, field: str(asset_id)},
        )
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))
    return asset


def _resolve_local_asset_path(asset: MediaAsset, *, media_root: Path) -> Path | None:
    uri = asset.uri or ""
    if not uri or is_remote_uri(uri):
        return None
    return LocalStorageBackend(media_root=media_root).resolve_local_path(uri)


def _coerce_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class WorkerDiagnostics(SQLModel):
    ping_ok: bool = False
    workers: list[str] = []
    system_info: dict | None = None
    error: str | None = None


class SystemStatusResponse(SQLModel):
    api_version: str
    offline_mode: bool
    storage_backend: str
    broker_url: str
    result_backend: str
    worker: WorkerDiagnostics


def _truthy_env(name: str) -> bool:
    raw = (os.getenv(name) or os.getenv(f"REFRAME_{name}") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@router.get("/system/status", response_model=SystemStatusResponse, tags=["System"])
def system_status() -> SystemStatusResponse:
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)

    worker_diag = WorkerDiagnostics()
    try:
        app = get_celery_app()
        try:
            pongs = app.control.ping(timeout=1.0)
            workers = []
            for item in pongs or []:
                if isinstance(item, dict):
                    workers.extend(item.keys())
            worker_diag.workers = sorted(set(workers))
            worker_diag.ping_ok = bool(worker_diag.workers)
        except Exception as exc:
            worker_diag.error = f"Worker ping failed: {exc}"

        if worker_diag.ping_ok:
            try:
                res = app.send_task("tasks.system_info")
                worker_diag.system_info = res.get(timeout=3.0)
            except Exception as exc:
                msg = f"Worker diagnostics task failed: {exc}"
                worker_diag.error = f"{worker_diag.error}; {msg}" if worker_diag.error else msg
    except Exception as exc:  # pragma: no cover - best effort
        worker_diag.error = f"Celery unavailable: {exc}"

    return SystemStatusResponse(
        api_version=settings.api_version,
        offline_mode=_truthy_env("OFFLINE_MODE"),
        storage_backend=type(storage).__name__,
        broker_url=settings.broker_url,
        result_backend=settings.result_backend,
        worker=worker_diag,
    )


class CaptionJobRequest(SQLModel):
    video_asset_id: UUID
    options: Optional[dict] = None
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000001",
                "options": {"language": "en", "backend": "whisper", "subtitle_quality_profile": "balanced"},
            }
        }
    }


class TranslateJobRequest(SQLModel):
    subtitle_asset_id: UUID
    target_language: str
    options: Optional[dict] = None
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

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
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

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
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

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


class DownloadUrlResponse(SQLModel):
    url: str

class MergeAVRequest(SQLModel):
    video_asset_id: UUID
    audio_asset_id: UUID
    offset: float = 0.0
    ducking: bool = False
    normalize: bool = True
    options: Optional[dict] = None
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

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


class CutClipRequest(SQLModel):
    video_asset_id: UUID
    start: float
    end: float
    options: Optional[dict] = None
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "video_asset_id": "00000000-0000-0000-0000-000000000004",
                "start": 12.5,
                "end": 27.0,
                "options": {},
            }
        }
    }


class StyledSubtitleJobRequest(SQLModel):
    video_asset_id: UUID
    subtitle_asset_id: UUID
    style: dict
    preview_seconds: Optional[int] = None
    project_id: Optional[UUID] = None
    idempotency_key: Optional[str] = None

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


class UsageSummary(SQLModel):
    total_jobs: int = 0
    queued_jobs: int = 0
    running_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    cancelled_jobs: int = 0
    job_type_counts: dict[str, int] = Field(default_factory=dict)
    output_assets_count: int = 0
    output_duration_seconds: float = 0.0
    generated_bytes: int = 0
    plan_code: Optional[str] = None
    quota_job_minutes: Optional[int] = None
    used_job_minutes: Optional[float] = None
    overage_job_minutes: Optional[float] = None
    max_concurrent_jobs: Optional[int] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None


class ProjectCreateRequest(SQLModel):
    name: str
    description: Optional[str] = None


class ProjectShareLinksRequest(SQLModel):
    asset_ids: list[UUID]
    expires_in_hours: int = 24


class ProjectShareLink(SQLModel):
    asset_id: UUID
    url: str
    expires_at: datetime


class ProjectShareLinksResponse(SQLModel):
    links: list[ProjectShareLink]


class UploadInitRequest(SQLModel):
    kind: str = "video"
    filename: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    project_id: Optional[UUID] = None


class UploadInitResponse(SQLModel):
    upload_id: str
    asset_id: Optional[UUID] = None
    upload_url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    form_fields: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime
    strategy: str = "single_part"


class UploadCompleteRequest(SQLModel):
    upload_id: str
    asset_id: UUID


class UploadCompleteResponse(SQLModel):
    upload_id: str
    asset_id: UUID
    status: str = "completed"


class MultipartUploadInitRequest(SQLModel):
    kind: str = "video"
    filename: str
    mime_type: Optional[str] = None
    project_id: Optional[UUID] = None


class MultipartUploadInitResponse(SQLModel):
    upload_id: str
    asset_id: UUID
    strategy: str = "multipart_presigned"
    expires_at: datetime
    part_size_bytes: int = 8 * 1024 * 1024


class MultipartUploadPartResponse(SQLModel):
    upload_id: str
    part_number: int
    upload_url: str
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class MultipartPart(SQLModel):
    part_number: int
    etag: str


class MultipartUploadCompleteRequest(SQLModel):
    parts: list[MultipartPart]


class MultipartUploadAbortResponse(SQLModel):
    upload_id: str
    status: str = "aborted"


_pending_uploads: dict[str, dict[str, object]] = {}
_pending_multipart_uploads: dict[str, dict[str, object]] = {}


def _owner_fields(principal: AuthPrincipal) -> dict[str, UUID | None]:
    return {"org_id": principal.org_id, "owner_user_id": principal.user_id}


def _supports_presigned_uploads(storage: Any) -> bool:
    return all(
        hasattr(storage, name)
        for name in ("create_presigned_upload", "create_multipart_upload", "sign_multipart_part", "complete_multipart_upload", "abort_multipart_upload")
    )


def _scoped_tmp_rel_dir(storage: Any, principal: AuthPrincipal) -> str:
    if principal.org_id and not isinstance(storage, LocalStorageBackend):
        return f"{principal.org_id}/tmp"
    return "tmp"


def _dispatch_existing_job(job: Job, session: Session) -> Job:
    payload = job.payload or {}
    if job.job_type == "captions":
        return save_and_dispatch(job, session, "tasks.generate_captions", str(job.id), str(job.input_asset_id), payload)
    if job.job_type == "translate_subtitles":
        return save_and_dispatch(job, session, "tasks.translate_subtitles", str(job.id), str(job.input_asset_id), payload)
    if job.job_type == "shorts":
        return save_and_dispatch(job, session, "tasks.generate_shorts", str(job.id), str(job.input_asset_id), payload)
    if job.job_type == "style_subtitles":
        subtitle_asset_id = str(payload.get("subtitle_asset_id") or "")
        style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
        return save_and_dispatch(
            job,
            session,
            "tasks.render_styled_subtitles",
            str(job.id),
            str(job.input_asset_id),
            subtitle_asset_id,
            style,
            {"preview_seconds": payload.get("preview_seconds")},
        )
    if job.job_type == "merge_av":
        audio_asset_id = str(payload.get("audio_asset_id") or "")
        return save_and_dispatch(
            job,
            session,
            "tasks.merge_video_audio",
            str(job.id),
            str(job.input_asset_id),
            audio_asset_id,
            payload,
        )
    if job.job_type == "cut_clip":
        start = max(0.0, float(payload.get("start") or 0.0))
        end = max(start, float(payload.get("end") or start))
        return save_and_dispatch(
            job,
            session,
            "tasks.cut_clip",
            str(job.id),
            str(job.input_asset_id),
            start,
            end,
            payload,
        )
    raise ApiError(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=ErrorCode.VALIDATION_ERROR,
        message="Job type does not support retry",
        details={"job_type": job.job_type},
    )


@router.post(
    "/captions/jobs",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Captions"],
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def create_caption_job(
    payload: CaptionJobRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.video_asset_id, principal=principal, kind="video", field="video_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(session=session, principal=principal, job_type="captions", idempotency_key=idem)
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="captions",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        payload=payload.options or {},
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
    )
    return save_and_dispatch(job, session, "tasks.generate_captions", str(job.id), str(payload.video_asset_id), payload.options or {})


@router.post(
    "/subtitles/translate",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Translate"],
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def create_translate_job(
    payload: TranslateJobRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.subtitle_asset_id, principal=principal, kind="subtitle", field="subtitle_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(
        session=session,
        principal=principal,
        job_type="translate_subtitles",
        idempotency_key=idem,
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="translate_subtitles",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.subtitle_asset_id,
        payload={"target_language": payload.target_language, **(payload.options or {})},
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
    )
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
def get_job(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    _assert_org_access(principal=principal, entity_org_id=job.org_id, entity="job", entity_id=str(job.id))
    return job


@router.get("/jobs", response_model=List[Job], tags=["Jobs"])
def list_jobs(
    session: SessionDep,
    principal: PrincipalDep,
    status_filter: Optional[JobStatus] = None,
    project_id: Optional[UUID] = None,
) -> List[Job]:
    query = select(Job)
    query = _scope_query_by_org(query, Job, principal)
    if status_filter:
        query = query.where(Job.status == status_filter)
    if project_id:
        _ensure_project_exists(session, project_id, principal)
        query = query.where(Job.project_id == project_id)
    results = session.exec(query).all()
    return results


@router.get("/usage/summary", response_model=UsageSummary, tags=["Usage"])
def get_usage_summary(
    session: SessionDep,
    principal: PrincipalDep,
    from_date: Optional[datetime] = Query(default=None, alias="from"),
    to_date: Optional[datetime] = Query(default=None, alias="to"),
    project_id: Optional[UUID] = None,
) -> UsageSummary:
    from_dt = _coerce_aware_datetime(from_date)
    to_dt = _coerce_aware_datetime(to_date)

    query = select(Job)
    query = _scope_query_by_org(query, Job, principal)
    if project_id:
        _ensure_project_exists(session, project_id, principal)
        query = query.where(Job.project_id == project_id)
    if from_dt:
        query = query.where(Job.created_at >= from_dt)
    if to_dt:
        query = query.where(Job.created_at <= to_dt)

    jobs = session.exec(query).all()
    by_type: dict[str, int] = {}
    output_asset_ids: set[UUID] = set()

    counts_by_status: dict[JobStatus, int] = {
        JobStatus.queued: 0,
        JobStatus.running: 0,
        JobStatus.completed: 0,
        JobStatus.failed: 0,
        JobStatus.cancelled: 0,
    }

    for job in jobs:
        counts_by_status[job.status] = counts_by_status.get(job.status, 0) + 1
        by_type[job.job_type] = by_type.get(job.job_type, 0) + 1
        if job.output_asset_id:
            output_asset_ids.add(job.output_asset_id)

    output_duration_seconds = 0.0
    generated_bytes = 0
    if output_asset_ids:
        assets = session.exec(select(MediaAsset).where(MediaAsset.id.in_(output_asset_ids))).all()
        settings = get_settings()
        media_root = Path(settings.media_root)
        for asset in assets:
            output_duration_seconds += float(asset.duration or 0.0)
            local_path = _resolve_local_asset_path(asset, media_root=media_root)
            if local_path and local_path.exists():
                try:
                    generated_bytes += int(local_path.stat().st_size)
                except OSError:
                    continue

    plan_code: str | None = None
    quota_minutes: int | None = None
    used_minutes: float | None = None
    overage_minutes: float | None = None
    max_concurrent_jobs: int | None = None
    if principal.org_id:
        plan_code = _resolve_plan_code(session, org_id=principal.org_id)
        policy = get_plan_policy(plan_code)
        quota_minutes = policy.monthly_job_minutes
        max_concurrent_jobs = policy.max_concurrent_jobs
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        usage_events = session.exec(
            select(UsageEvent).where(
                (UsageEvent.org_id == principal.org_id)
                & (UsageEvent.metric == "job_minutes")
                & (UsageEvent.created_at >= month_start)
            )
        ).all()
        used_minutes = sum(float(item.quantity or 0.0) for item in usage_events)
        overage_minutes = max(0.0, float(used_minutes) - float(policy.monthly_job_minutes))

    return UsageSummary(
        total_jobs=len(jobs),
        queued_jobs=counts_by_status.get(JobStatus.queued, 0),
        running_jobs=counts_by_status.get(JobStatus.running, 0),
        completed_jobs=counts_by_status.get(JobStatus.completed, 0),
        failed_jobs=counts_by_status.get(JobStatus.failed, 0),
        cancelled_jobs=counts_by_status.get(JobStatus.cancelled, 0),
        job_type_counts=by_type,
        output_assets_count=len(output_asset_ids),
        output_duration_seconds=round(output_duration_seconds, 3),
        generated_bytes=generated_bytes,
        plan_code=plan_code,
        quota_job_minutes=quota_minutes,
        used_job_minutes=round(float(used_minutes), 3) if used_minutes is not None else None,
        overage_job_minutes=round(float(overage_minutes), 3) if overage_minutes is not None else None,
        max_concurrent_jobs=max_concurrent_jobs,
        from_date=from_dt,
        to_date=to_dt,
    )


@router.post(
    "/projects",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={422: {"model": ErrorResponse}},
)
def create_project(payload: ProjectCreateRequest, session: SessionDep, principal: PrincipalDep) -> Project:
    name = (payload.name or "").strip()
    if not name:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Project name is required",
            details={"field": "name"},
        )
    project = Project(
        name=name,
        description=(payload.description or "").strip() or None,
        **_owner_fields(principal),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("/projects", response_model=list[Project], tags=["Projects"])
def list_projects(session: SessionDep, principal: PrincipalDep) -> list[Project]:
    query = select(Project).order_by(Project.created_at.desc())
    query = _scope_query_by_org(query, Project, principal)
    return session.exec(query).all()


@router.get(
    "/projects/{project_id}",
    response_model=Project,
    tags=["Projects"],
    responses={404: {"model": ErrorResponse}},
)
def get_project(project_id: UUID, session: SessionDep, principal: PrincipalDep) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise not_found("Project not found", details={"project_id": str(project_id)})
    _assert_org_access(principal=principal, entity_org_id=project.org_id, entity="project", entity_id=str(project.id))
    return project


@router.get(
    "/projects/{project_id}/jobs",
    response_model=list[Job],
    tags=["Projects"],
    responses={404: {"model": ErrorResponse}},
)
def list_project_jobs(
    project_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    status_filter: Optional[JobStatus] = None,
) -> list[Job]:
    _ensure_project_exists(session, project_id, principal)
    query = select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
    query = _scope_query_by_org(query, Job, principal)
    if status_filter:
        query = query.where(Job.status == status_filter)
    return session.exec(query).all()


@router.get(
    "/projects/{project_id}/assets",
    response_model=list[MediaAsset],
    tags=["Projects"],
    responses={404: {"model": ErrorResponse}},
)
def list_project_assets(
    project_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    kind: Optional[str] = None,
    limit: int = 50,
) -> list[MediaAsset]:
    _ensure_project_exists(session, project_id, principal)
    limit = max(1, min(limit, 200))
    query = select(MediaAsset).where(MediaAsset.project_id == project_id)
    query = _scope_query_by_org(query, MediaAsset, principal)
    if kind:
        query = query.where(MediaAsset.kind == kind)
    query = query.order_by(MediaAsset.created_at.desc()).limit(limit)
    return session.exec(query).all()


@router.post(
    "/projects/{project_id}/share-links",
    response_model=ProjectShareLinksResponse,
    tags=["Projects"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_project_share_links(
    project_id: UUID,
    payload: ProjectShareLinksRequest,
    session: SessionDep,
    request: Request,
    principal: PrincipalDep,
) -> ProjectShareLinksResponse:
    project = _ensure_project_exists(session, project_id, principal)
    assert project is not None  # for typing

    expires_in_hours = max(1, min(int(payload.expires_in_hours or 24), 24 * 30))
    settings = get_settings()
    links: list[ProjectShareLink] = []

    for asset_id in payload.asset_ids:
        asset = session.get(MediaAsset, asset_id)
        if not asset:
            raise not_found("Asset not found", details={"asset_id": str(asset_id)})
        _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))
        if asset.project_id != project.id:
            raise conflict(
                "Asset does not belong to project",
                details={"asset_id": str(asset_id), "project_id": str(project.id)},
            )

        token, expires_at = build_share_token_with_ttl(
            secret=settings.share_link_secret,
            asset_id=asset.id,
            project_id=project.id,
            ttl_hours=expires_in_hours,
        )
        path = request.url_for("download_shared_asset", asset_id=str(asset.id))
        links.append(ProjectShareLink(asset_id=asset.id, url=f"{path}?token={token}", expires_at=expires_at))

    return ProjectShareLinksResponse(links=links)


@router.get(
    "/share/assets/{asset_id}",
    response_class=FileResponse,
    tags=["Projects"],
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    name="download_shared_asset",
)
def download_shared_asset(asset_id: UUID, token: str, session: SessionDep):
    settings = get_settings()
    try:
        token_payload = parse_and_validate_share_token(token, secret=settings.share_link_secret)
    except ValueError as exc:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message="Invalid or expired share token",
            details={"reason": str(exc)},
        ) from exc

    if token_payload.asset_id != asset_id:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message="Invalid share token",
            details={"reason": "asset mismatch"},
        )

    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    if not asset.project_id:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message="Asset is not shareable",
            details={"asset_id": str(asset_id)},
        )
    if token_payload.project_id != asset.project_id:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.PERMISSION_DENIED,
            message="Invalid share token",
            details={"reason": "project mismatch"},
        )

    if asset.uri and is_remote_uri(asset.uri):
        storage = get_storage(media_root=settings.media_root)
        remote_url = storage.get_download_url(asset.uri) or asset.uri
        return RedirectResponse(url=remote_url, status_code=302)

    file_path = LocalStorageBackend(media_root=Path(settings.media_root)).resolve_local_path(asset.uri or "")
    if not file_path.exists():
        raise not_found("Asset file missing", details={"asset_id": str(asset_id), "path": str(file_path)})
    return FileResponse(path=file_path, media_type=asset.mime_type or "application/octet-stream", filename=file_path.name)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=Job,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_job(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> Job:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    _assert_org_access(principal=principal, entity_org_id=job.org_id, entity="job", entity_id=str(job.id))

    if job.status in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
        raise conflict("Job already finished", details={"status": job.status})

    job.status = JobStatus.cancelled
    job.progress = 0.0
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.post(
    "/jobs/{job_id}/retry",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def retry_job(
    job_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    source = session.get(Job, job_id)
    if not source:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    _assert_org_access(principal=principal, entity_org_id=source.org_id, entity="job", entity_id=str(source.id))
    if source.status not in {JobStatus.failed, JobStatus.cancelled}:
        raise conflict("Only failed/cancelled jobs can be retried", details={"status": source.status})
    if not source.input_asset_id:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Retry is only supported for jobs with an input asset",
            details={"job_id": str(source.id), "job_type": source.job_type},
        )

    _enforce_org_quota(session, principal)
    original_payload = source.payload or {}
    retry_attempt = int(original_payload.get("retry_attempt") or 0) + 1 if isinstance(original_payload, dict) else 1
    retry_payload = {**(original_payload if isinstance(original_payload, dict) else {})}
    retry_payload.update({"retry_of": str(source.id), "retry_attempt": retry_attempt})

    idem = _resolve_idempotency_key(None, idempotency_key)
    if idem:
        existing = _find_existing_idempotent_job(session=session, principal=principal, job_type=source.job_type, idempotency_key=idem)
        if existing:
            response.status_code = status.HTTP_200_OK
            return existing

    cloned = Job(
        job_type=source.job_type,
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=source.input_asset_id,
        payload=retry_payload,
        project_id=source.project_id,
        org_id=source.org_id,
        owner_user_id=source.owner_user_id,
        idempotency_key=idem,
    )
    return _dispatch_existing_job(cloned, session)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_job(job_id: UUID, session: SessionDep, principal: PrincipalDep, delete_assets: bool = False) -> Response:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    _assert_org_access(principal=principal, entity_org_id=job.org_id, entity="job", entity_id=str(job.id))

    if job.status not in {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}:
        raise conflict("Job is still active; cancel it before deleting", details={"status": job.status})

    derived_asset_ids = _collect_job_output_asset_ids(job) if delete_assets else set()

    session.delete(job)
    session.commit()

    if delete_assets:
        for asset_id in sorted(derived_asset_ids):
            _delete_asset_if_unreferenced(session, asset_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/jobs/{job_id}/bundle",
    response_class=StreamingResponse,
    tags=["Jobs"],
    responses={404: {"model": ErrorResponse}},
)
def download_job_bundle(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> StreamingResponse:
    job = session.get(Job, job_id)
    if not job:
        raise not_found("Job not found", details={"job_id": str(job_id)})
    _assert_org_access(principal=principal, entity_org_id=job.org_id, entity="job", entity_id=str(job.id))

    settings = get_settings()
    media_root = Path(settings.media_root)
    storage = get_storage(media_root=settings.media_root)

    def resolve_asset_path(asset: MediaAsset) -> Path:
        uri = asset.uri or ""
        if is_remote_uri(uri):
            return Path(uri)
        uri_path = Path(uri.lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == "media":
            uri_path = Path(*uri_path.parts[1:])
        return media_root / uri_path

    def add_asset_to_zip(*, asset: MediaAsset, base_name: str, zf: zipfile.ZipFile) -> Optional[str]:
        """Add an asset's metadata + local file (if available) to the zip.

        Returns the relative file path inside the zip when the local file is included.
        """
        zf.writestr(f"{base_name}_meta.json", json.dumps(asset.model_dump(), default=str, indent=2))
        uri = asset.uri or ""
        if not uri:
            return None

        if is_remote_uri(uri):
            resolved = storage.get_download_url(uri) or uri
            zf.writestr(f"{base_name}_uri.txt", resolved)
            return f"{base_name}_uri.txt"

        path = resolve_asset_path(asset)
        if path.is_file():
            suffix = path.suffix or Path(uri).suffix or ""
            rel_path = f"{base_name}{suffix}"
            zf.write(path, arcname=rel_path)
            return rel_path

        zf.writestr(f"{base_name}_file_missing.txt", f"Asset file missing at {path} (uri={uri})")
        return None

    def add_asset_by_id(*, asset_id: UUID, base_name: str, zf: zipfile.ZipFile) -> Optional[str]:
        asset = session.get(MediaAsset, asset_id)
        if not asset:
            zf.writestr(f"{base_name}_missing.txt", f"Asset {asset_id} missing from database")
            return None
        return add_asset_to_zip(asset=asset, base_name=base_name, zf=zf)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("job.json", json.dumps(job.model_dump(), default=str, indent=2))
        if job.error:
            zf.writestr("error.txt", job.error)

        for label, asset_id in (("input", job.input_asset_id), ("output", job.output_asset_id)):
            if not asset_id:
                continue
            add_asset_by_id(asset_id=asset_id, base_name=f"{label}_asset", zf=zf)

        if job.job_type == "shorts" and isinstance(job.payload, dict):
            raw_clips = job.payload.get("clip_assets")
            if isinstance(raw_clips, list):
                upload_package: dict = {
                    "version": 1,
                    "job_id": str(job.id),
                    "job_type": job.job_type,
                    "note": "Edit the suggested titles/descriptions/tags before uploading.",
                    "prompt": job.payload.get("prompt"),
                    "clips": [],
                }

                for idx, clip in enumerate(raw_clips):
                    if not isinstance(clip, dict):
                        continue
                    clip_dir = f"clips/clip_{idx + 1:02d}"
                    zf.writestr(f"{clip_dir}/clip.json", json.dumps(clip, default=str, indent=2))

                    video_file = None
                    styled_file = None
                    thumb_file = None
                    subs_file = None

                    video_id = clip.get("asset_id")
                    try:
                        if video_id:
                            video_file = add_asset_by_id(asset_id=UUID(str(video_id)), base_name=f"{clip_dir}/video", zf=zf)
                    except Exception:
                        video_file = None

                    thumb_id = clip.get("thumbnail_asset_id")
                    try:
                        if thumb_id:
                            thumb_file = add_asset_by_id(asset_id=UUID(str(thumb_id)), base_name=f"{clip_dir}/thumbnail", zf=zf)
                    except Exception:
                        thumb_file = None

                    subs_id = clip.get("subtitle_asset_id")
                    try:
                        if subs_id:
                            subs_file = add_asset_by_id(asset_id=UUID(str(subs_id)), base_name=f"{clip_dir}/subtitles", zf=zf)
                    except Exception:
                        subs_file = None

                    styled_id = clip.get("styled_asset_id")
                    try:
                        if styled_id:
                            styled_file = add_asset_by_id(asset_id=UUID(str(styled_id)), base_name=f"{clip_dir}/video_styled", zf=zf)
                    except Exception:
                        styled_file = None

                    clip_title = f"Reframe Clip {idx + 1}"
                    if isinstance(job.payload.get("prompt"), str) and job.payload["prompt"].strip():
                        prompt = job.payload["prompt"].strip()
                        clip_title = f"{prompt[:80]} (Clip {idx + 1})"

                    upload_package["clips"].append(
                        {
                            "index": idx + 1,
                            "id": clip.get("id"),
                            "start": clip.get("start"),
                            "end": clip.get("end"),
                            "duration": clip.get("duration"),
                            "score": clip.get("score"),
                            "files": {
                                "video": video_file,
                                "video_styled": styled_file,
                                "thumbnail": thumb_file,
                                "subtitles": subs_file,
                            },
                            "suggested": {
                                "title": clip_title,
                                "description": f"Generated by Reframe from job {job.id}.",
                                "tags": ["reframe", "shorts"],
                            },
                            "source_uris": {
                                "video": clip.get("uri"),
                                "video_styled": clip.get("styled_uri"),
                                "thumbnail": clip.get("thumbnail_uri"),
                                "subtitles": clip.get("subtitle_uri"),
                            },
                        }
                    )

                zf.writestr("upload_package.json", json.dumps(upload_package, default=str, indent=2))

    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename=\"job_{job_id}.zip\"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@router.post(
    "/shorts/jobs",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Shorts"],
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def create_shorts_job(
    payload: ShortsJobRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.video_asset_id, principal=principal, kind="video", field="video_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(session=session, principal=principal, job_type="shorts", idempotency_key=idem)
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="shorts",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
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
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def create_style_job(
    payload: StyledSubtitleJobRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.video_asset_id, principal=principal, kind="video", field="video_asset_id")
    _ensure_asset_exists(session, asset_id=payload.subtitle_asset_id, principal=principal, kind="subtitle", field="subtitle_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(
        session=session,
        principal=principal,
        job_type="style_subtitles",
        idempotency_key=idem,
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="style_subtitles",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
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
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def create_merge_job(
    payload: MergeAVRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.video_asset_id, principal=principal, kind="video", field="video_asset_id")
    _ensure_asset_exists(session, asset_id=payload.audio_asset_id, principal=principal, kind="audio", field="audio_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(session=session, principal=principal, job_type="merge_av", idempotency_key=idem)
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="merge_av",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
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
    "/utilities/cut-clip",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Utilities"],
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def cut_clip_tool(
    payload: CutClipRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.video_asset_id, principal=principal, kind="video", field="video_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    start = max(0.0, float(payload.start or 0.0))
    end = max(start, float(payload.end or start))
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(session=session, principal=principal, job_type="cut_clip", idempotency_key=idem)
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="cut_clip",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.video_asset_id,
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
        payload={
            "start": start,
            "end": end,
            **(payload.options or {}),
        },
    )
    return save_and_dispatch(
        job,
        session,
        "tasks.cut_clip",
        str(job.id),
        str(payload.video_asset_id),
        start,
        end,
        job.payload,
    )


@router.post(
    "/utilities/translate-subtitle",
    response_model=Job,
    status_code=status.HTTP_201_CREATED,
    tags=["Utilities"],
    dependencies=[Depends(enforce_rate_limit("heavy_jobs"))],
)
def translate_subtitle_tool(
    payload: TranslateSubtitleToolRequest,
    session: SessionDep,
    principal: PrincipalDep,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Job:
    _ensure_asset_exists(session, asset_id=payload.subtitle_asset_id, principal=principal, kind="subtitle", field="subtitle_asset_id")
    project = _ensure_project_exists(session, payload.project_id, principal)
    _enforce_org_quota(session, principal)
    idem = _resolve_idempotency_key(payload.idempotency_key, idempotency_key)
    existing = _find_existing_idempotent_job(
        session=session,
        principal=principal,
        job_type="translate_subtitles",
        idempotency_key=idem,
    )
    if existing:
        response.status_code = status.HTTP_200_OK
        return existing

    job = Job(
        job_type="translate_subtitles",
        status=JobStatus.queued,
        progress=0.0,
        input_asset_id=payload.subtitle_asset_id,
        project_id=project.id if project else payload.project_id,
        idempotency_key=idem,
        **_owner_fields(principal),
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


_ALLOWED_UPLOAD_KINDS = {"video", "audio", "subtitle"}
_ALLOWED_SUBTITLE_MIME_TYPES = {
    "text/plain",
    "text/vtt",
    "application/x-subrip",
    "application/octet-stream",
}


def _validate_upload(kind: str, content_type: str | None, filename: str | None) -> None:
    normalized_kind = (kind or "").strip().lower()
    ct = (content_type or "").strip().lower()

    if normalized_kind not in _ALLOWED_UPLOAD_KINDS:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ErrorCode.VALIDATION_ERROR,
            message="Invalid asset kind",
            details={"kind": kind, "allowed_kinds": sorted(_ALLOWED_UPLOAD_KINDS)},
        )

    if normalized_kind == "video":
        if not ct.startswith("video/"):
            raise ApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid content type for video upload",
                details={"content_type": content_type, "filename": filename},
            )

    if normalized_kind == "audio":
        if not ct.startswith("audio/"):
            raise ApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid content type for audio upload",
                details={"content_type": content_type, "filename": filename},
            )

    if normalized_kind == "subtitle":
        if ct and ct not in _ALLOWED_SUBTITLE_MIME_TYPES and not ct.startswith("text/"):
            raise ApiError(
                status_code=status.HTTP_400_BAD_REQUEST,
                code=ErrorCode.VALIDATION_ERROR,
                message="Invalid content type for subtitle upload",
                details={"content_type": content_type, "filename": filename},
            )


def _coerce_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except Exception:
        return None


def _collect_job_output_asset_ids(job: Job) -> set[UUID]:
    """Collect output/derived asset IDs for cleanup; does not include input assets."""
    out: set[UUID] = set()
    if job.output_asset_id:
        out.add(job.output_asset_id)

    payload = job.payload or {}
    if isinstance(payload, dict):
        clip_assets = payload.get("clip_assets")
        if isinstance(clip_assets, list):
            for item in clip_assets:
                if not isinstance(item, dict):
                    continue
                for key in ("asset_id", "thumbnail_asset_id", "subtitle_asset_id", "styled_asset_id"):
                    uid = _coerce_uuid(item.get(key))
                    if uid:
                        out.add(uid)
    return out


def _asset_is_referenced(session: Session, asset_id: UUID) -> bool:
    query = select(Job).where((Job.input_asset_id == asset_id) | (Job.output_asset_id == asset_id)).limit(1)
    return session.exec(query).first() is not None


def _delete_asset_if_unreferenced(session: Session, asset_id: UUID) -> None:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        return
    if _asset_is_referenced(session, asset_id):
        return

    settings = get_settings()
    uri = asset.uri or ""
    if uri:
        storage = get_storage(media_root=settings.media_root)
        try:
            storage.delete_uri(uri)
        except Exception:
            pass

    session.delete(asset)
    session.commit()


@router.post(
    "/assets/upload-init",
    response_model=UploadInitResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def init_asset_upload(
    payload: UploadInitRequest,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
) -> UploadInitResponse:
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    kind = (payload.kind or "").strip().lower() or "video"
    _validate_upload(kind, payload.mime_type, payload.filename)
    project = _ensure_project_exists(session, payload.project_id, principal)

    upload_id = str(uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    pending_entry: dict[str, object] = {
        "kind": kind,
        "project_id": str(project.id) if project else None,
        "org_id": str(principal.org_id) if principal.org_id else None,
        "owner_user_id": str(principal.user_id) if principal.user_id else None,
        "expires_at": expires_at,
        "strategy": "single_part",
    }

    if _supports_presigned_uploads(storage) and not isinstance(storage, LocalStorageBackend):
        rel_dir = _scoped_tmp_rel_dir(storage, principal)
        suffix = Path(payload.filename or "").suffix
        storage_filename = f"{uuid4()}{suffix}"
        presigned = storage.create_presigned_upload(
            rel_dir=rel_dir,
            filename=storage_filename,
            content_type=payload.mime_type,
            expires_seconds=15 * 60,
        )
        uri = str(presigned.get("uri") or "")
        if not uri:
            raise server_error("Storage backend failed to provide upload URI")
        asset = MediaAsset(
            kind=kind,
            uri=uri,
            mime_type=payload.mime_type,
            project_id=project.id if project else payload.project_id,
            **_owner_fields(principal),
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        pending_entry["strategy"] = "single_part_presigned"
        pending_entry["asset_id"] = str(asset.id)
        _pending_uploads[upload_id] = pending_entry
        return UploadInitResponse(
            upload_id=upload_id,
            asset_id=asset.id,
            upload_url=str(presigned.get("upload_url") or ""),
            method=str(presigned.get("method") or "PUT"),
            headers=presigned.get("headers") if isinstance(presigned.get("headers"), dict) else {},
            form_fields=presigned.get("form_fields") if isinstance(presigned.get("form_fields"), dict) else {},
            expires_at=expires_at,
            strategy="single_part_presigned",
        )

    _pending_uploads[upload_id] = pending_entry
    form_fields = {"kind": kind, "upload_id": upload_id}
    if project:
        form_fields["project_id"] = str(project.id)
    upload_url = str(request.url_for("upload_asset"))
    return UploadInitResponse(
        upload_id=upload_id,
        upload_url=upload_url,
        method="POST",
        headers={},
        form_fields=form_fields,
        expires_at=expires_at,
        strategy="single_part",
    )


@router.post(
    "/assets/upload-complete",
    response_model=UploadCompleteResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def complete_asset_upload(
    payload: UploadCompleteRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> UploadCompleteResponse:
    entry = _pending_uploads.get(payload.upload_id)
    if not entry:
        raise not_found("Upload session not found", details={"upload_id": payload.upload_id})

    expires_at = entry.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.now(timezone.utc):
        _pending_uploads.pop(payload.upload_id, None)
        raise conflict("Upload session expired", details={"upload_id": payload.upload_id})

    expected_asset_raw = entry.get("asset_id")
    if expected_asset_raw and str(payload.asset_id) != str(expected_asset_raw):
        raise conflict(
            "Asset mismatch for upload session",
            details={"upload_id": payload.upload_id, "asset_id": str(payload.asset_id)},
        )

    asset = session.get(MediaAsset, payload.asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(payload.asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))

    expected_project_raw = entry.get("project_id")
    expected_project = UUID(str(expected_project_raw)) if expected_project_raw else None
    if expected_project and asset.project_id and asset.project_id != expected_project:
        raise conflict(
            "Asset project mismatch for upload session",
            details={"upload_id": payload.upload_id, "asset_id": str(asset.id)},
        )
    if expected_project and not asset.project_id:
        asset.project_id = expected_project

    if principal.org_id and not asset.org_id:
        asset.org_id = principal.org_id
    if principal.user_id and not asset.owner_user_id:
        asset.owner_user_id = principal.user_id

    session.add(asset)
    session.commit()
    _pending_uploads.pop(payload.upload_id, None)
    return UploadCompleteResponse(upload_id=payload.upload_id, asset_id=asset.id)


@router.post(
    "/assets/upload-multipart/init",
    response_model=MultipartUploadInitResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def init_multipart_asset_upload(
    payload: MultipartUploadInitRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> MultipartUploadInitResponse:
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    if not _supports_presigned_uploads(storage) or isinstance(storage, LocalStorageBackend):
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code=ErrorCode.VALIDATION_ERROR,
            message="Multipart uploads require object storage backend (S3/R2).",
        )

    kind = (payload.kind or "").strip().lower() or "video"
    _validate_upload(kind, payload.mime_type, payload.filename)
    project = _ensure_project_exists(session, payload.project_id, principal)

    rel_dir = _scoped_tmp_rel_dir(storage, principal)
    suffix = Path(payload.filename or "").suffix
    storage_filename = f"{uuid4()}{suffix}"
    provider_session = storage.create_multipart_upload(rel_dir=rel_dir, filename=storage_filename, content_type=payload.mime_type)

    asset = MediaAsset(
        kind=kind,
        uri=str(provider_session["uri"]),
        mime_type=payload.mime_type,
        project_id=project.id if project else payload.project_id,
        **_owner_fields(principal),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    upload_id = str(uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    _pending_multipart_uploads[upload_id] = {
        "provider_upload_id": str(provider_session["upload_id"]),
        "key": str(provider_session["key"]),
        "asset_id": str(asset.id),
        "project_id": str(project.id) if project else None,
        "org_id": str(principal.org_id) if principal.org_id else None,
        "owner_user_id": str(principal.user_id) if principal.user_id else None,
        "expires_at": expires_at,
    }
    return MultipartUploadInitResponse(upload_id=upload_id, asset_id=asset.id, expires_at=expires_at)


@router.post(
    "/assets/upload-multipart/{upload_id}/parts/{part_number}",
    response_model=MultipartUploadPartResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def sign_multipart_upload_part(
    upload_id: str,
    part_number: int,
    session: SessionDep,
    principal: PrincipalDep,
) -> MultipartUploadPartResponse:
    _ = session  # request-scoped dependency keeps db/session lifecycle consistent for auth context
    entry = _pending_multipart_uploads.get(upload_id)
    if not entry:
        raise not_found("Multipart upload session not found", details={"upload_id": upload_id})
    expires_at = entry.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.now(timezone.utc):
        _pending_multipart_uploads.pop(upload_id, None)
        raise conflict("Multipart upload session expired", details={"upload_id": upload_id})

    expected_org_raw = entry.get("org_id")
    expected_org = UUID(str(expected_org_raw)) if expected_org_raw else None
    _assert_org_access(principal=principal, entity_org_id=expected_org, entity="upload", entity_id=upload_id)

    if part_number < 1:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="part_number must be >= 1",
            details={"part_number": part_number},
        )

    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    signed = storage.sign_multipart_part(
        key=str(entry["key"]),
        provider_upload_id=str(entry["provider_upload_id"]),
        part_number=part_number,
        expires_seconds=15 * 60,
    )
    signed_expires = datetime.now(timezone.utc) + timedelta(seconds=int(signed.get("expires_in_seconds") or 15 * 60))
    return MultipartUploadPartResponse(
        upload_id=upload_id,
        part_number=part_number,
        upload_url=str(signed.get("upload_url") or ""),
        method=str(signed.get("method") or "PUT"),
        headers=signed.get("headers") if isinstance(signed.get("headers"), dict) else {},
        expires_at=signed_expires,
    )


@router.post(
    "/assets/upload-multipart/{upload_id}/complete",
    response_model=UploadCompleteResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def complete_multipart_asset_upload(
    upload_id: str,
    payload: MultipartUploadCompleteRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> UploadCompleteResponse:
    entry = _pending_multipart_uploads.get(upload_id)
    if not entry:
        raise not_found("Multipart upload session not found", details={"upload_id": upload_id})
    expires_at = entry.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at < datetime.now(timezone.utc):
        _pending_multipart_uploads.pop(upload_id, None)
        raise conflict("Multipart upload session expired", details={"upload_id": upload_id})

    asset_id = UUID(str(entry["asset_id"]))
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        _pending_multipart_uploads.pop(upload_id, None)
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))

    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    storage.complete_multipart_upload(
        key=str(entry["key"]),
        provider_upload_id=str(entry["provider_upload_id"]),
        parts=[part.model_dump() for part in payload.parts],
    )
    _pending_multipart_uploads.pop(upload_id, None)
    return UploadCompleteResponse(upload_id=upload_id, asset_id=asset.id, status="completed")


@router.post(
    "/assets/upload-multipart/{upload_id}/abort",
    response_model=MultipartUploadAbortResponse,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
def abort_multipart_asset_upload(
    upload_id: str,
    session: SessionDep,
    principal: PrincipalDep,
) -> MultipartUploadAbortResponse:
    entry = _pending_multipart_uploads.get(upload_id)
    if not entry:
        raise not_found("Multipart upload session not found", details={"upload_id": upload_id})

    asset_id = UUID(str(entry["asset_id"]))
    asset = session.get(MediaAsset, asset_id)
    if asset:
        _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))

    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    storage.abort_multipart_upload(
        key=str(entry["key"]),
        provider_upload_id=str(entry["provider_upload_id"]),
    )

    _pending_multipart_uploads.pop(upload_id, None)
    if asset and not _asset_is_referenced(session, asset.id):
        session.delete(asset)
        session.commit()
    return MultipartUploadAbortResponse(upload_id=upload_id, status="aborted")


@router.post(
    "/assets/upload",
    response_model=MediaAsset,
    status_code=status.HTTP_201_CREATED,
    tags=["Assets"],
    dependencies=[Depends(enforce_rate_limit("uploads"))],
)
async def upload_asset(
    session: SessionDep,
    principal: PrincipalDep,
    file: UploadFile = File(...),
    kind: str = Form("video"),
    project_id: Optional[UUID] = Form(default=None),
) -> MediaAsset:
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    kind = (kind or "").strip().lower()
    _validate_upload(kind, file.content_type, file.filename)
    project = _ensure_project_exists(session, project_id, principal)

    suffix = Path(file.filename or "").suffix
    filename = f"{uuid4()}{suffix}"

    max_bytes = max(0, int(settings.max_upload_bytes or 0))
    tmp_dir = Path(settings.media_root) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / filename
    total = 0
    with tmp_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes and total > max_bytes:
                tmp_path.unlink(missing_ok=True)
                raise ApiError(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Upload too large",
                    details={"max_upload_bytes": max_bytes, "uploaded_bytes": total},
                )
            out.write(chunk)

    rel_dir = _scoped_tmp_rel_dir(storage, principal)
    uri = storage.write_file(rel_dir=rel_dir, filename=filename, source_path=tmp_path, content_type=file.content_type)
    if not isinstance(storage, LocalStorageBackend):
        tmp_path.unlink(missing_ok=True)

    asset = MediaAsset(
        kind=kind,
        uri=uri,
        mime_type=file.content_type,
        project_id=project.id if project else project_id,
        **_owner_fields(principal),
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get(
    "/assets",
    response_model=List[MediaAsset],
    tags=["Assets"],
)
def list_assets(
    session: SessionDep,
    principal: PrincipalDep,
    kind: Optional[str] = None,
    limit: int = 25,
    project_id: Optional[UUID] = None,
) -> List[MediaAsset]:
    limit = max(1, min(limit, 200))
    query = select(MediaAsset)
    query = _scope_query_by_org(query, MediaAsset, principal)
    if kind:
        query = query.where(MediaAsset.kind == kind)
    if project_id:
        _ensure_project_exists(session, project_id, principal)
        query = query.where(MediaAsset.project_id == project_id)
    query = query.order_by(MediaAsset.created_at.desc()).limit(limit)
    return session.exec(query).all()


@router.get(
    "/assets/{asset_id}",
    response_model=MediaAsset,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}},
)
def get_asset(asset_id: UUID, session: SessionDep, principal: PrincipalDep) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))
    return asset


@router.delete(
    "/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_asset(asset_id: UUID, session: SessionDep, principal: PrincipalDep) -> Response:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))

    refs_query = select(Job.id).where((Job.input_asset_id == asset_id) | (Job.output_asset_id == asset_id))
    refs_query = _scope_query_by_org(refs_query, Job, principal)
    refs = session.exec(refs_query).all()
    if refs:
        raise conflict(
            "Asset is referenced by jobs; delete the jobs first",
            details={"asset_id": str(asset_id), "job_ids": [str(r) for r in refs]},
        )

    settings = get_settings()
    uri = asset.uri or ""
    if uri:
        storage = get_storage(media_root=settings.media_root)
        try:
            storage.delete_uri(uri)
        except Exception:
            pass

    session.delete(asset)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/assets/{asset_id}/download-url",
    response_model=DownloadUrlResponse,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}},
)
def get_asset_download_url(asset_id: UUID, session: SessionDep, principal: PrincipalDep, presign: bool = True) -> DownloadUrlResponse:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))
    if not asset.uri:
        raise not_found("Asset has no URI", details={"asset_id": str(asset_id)})
    settings = get_settings()
    storage = get_storage(media_root=settings.media_root)
    url = asset.uri
    if presign:
        resolved = storage.get_download_url(asset.uri)
        if resolved:
            url = resolved
    return DownloadUrlResponse(url=url)


@router.get(
    "/assets/{asset_id}/download",
    response_class=FileResponse,
    tags=["Assets"],
    responses={404: {"model": ErrorResponse}},
)
def download_asset(asset_id: UUID, session: SessionDep, principal: PrincipalDep) -> FileResponse:
    asset = session.get(MediaAsset, asset_id)
    if not asset:
        raise not_found("Asset not found", details={"asset_id": str(asset_id)})
    _assert_org_access(principal=principal, entity_org_id=asset.org_id, entity="asset", entity_id=str(asset.id))
    settings = get_settings()
    if asset.uri and is_remote_uri(asset.uri):
        storage = get_storage(media_root=settings.media_root)
        remote_url = storage.get_download_url(asset.uri) or asset.uri
        return RedirectResponse(url=remote_url, status_code=302)
    file_path = LocalStorageBackend(media_root=Path(settings.media_root)).resolve_local_path(asset.uri or "")
    if not file_path.exists():
        raise not_found("Asset file missing", details={"asset_id": str(asset_id), "path": str(file_path)})
    return FileResponse(path=file_path, media_type=asset.mime_type or "application/octet-stream", filename=file_path.name)


@router.get("/presets/styles", response_model=List[SubtitleStylePreset], tags=["Presets"])
def list_style_presets(session: SessionDep, principal: PrincipalDep) -> List[SubtitleStylePreset]:
    presets = session.exec(select(SubtitleStylePreset)).all()
    return presets
