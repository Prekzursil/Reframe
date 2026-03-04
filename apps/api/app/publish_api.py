from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, Any, Optional
from uuid import UUID

try:
    from celery import Celery
except ModuleNotFoundError:  # pragma: no cover
    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def send_task(self, *_args, **_kwargs):
            raise RuntimeError("Celery is not installed in this environment.")

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session, SQLModel, select

from app.auth_api import PrincipalDep
from app.config import get_settings
from app.local_queue import dispatch_task as dispatch_local_task, is_local_queue_mode
from app.database import get_session
from app.errors import ApiError, ErrorCode, ErrorResponse, conflict, not_found, unauthorized
from app.models import AutomationRunEvent, MediaAsset, PublishConnection, PublishJob
from app.security import create_oauth_state, parse_oauth_state

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]

SUPPORTED_PUBLISH_PROVIDERS = ("youtube", "tiktok", "instagram", "facebook")
PUBLISH_JOB_TERMINAL = {"completed", "failed", "cancelled"}


class PublishProviderView(SQLModel):
    provider: str
    display_name: str
    connected_count: int


class PublishConnectionView(SQLModel):
    id: UUID
    provider: str
    account_label: Optional[str] = None
    external_account_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None


class PublishConnectStartResponse(SQLModel):
    provider: str
    authorize_url: str
    state: str
    redirect_uri: str


class PublishJobCreateRequest(SQLModel):
    provider: str
    connection_id: UUID
    asset_id: UUID
    title: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = []
    schedule_at: Optional[datetime] = None
    workflow_run_id: Optional[UUID] = None


class PublishJobView(SQLModel):
    id: UUID
    provider: str
    connection_id: UUID
    asset_id: UUID
    status: str
    retry_count: int
    payload: dict
    error: Optional[str] = None
    external_post_id: Optional[str] = None
    published_url: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_display(provider: str) -> str:
    return {
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "facebook": "Facebook",
    }.get(provider, provider.title())


def _validate_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized not in SUPPORTED_PUBLISH_PROVIDERS:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code=ErrorCode.VALIDATION_ERROR,
            message="Unsupported publish provider",
            details={"provider": provider},
        )
    return normalized


def _hash_secret(raw: str | None) -> str | None:
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _serialize_connection(connection: PublishConnection) -> PublishConnectionView:
    return PublishConnectionView(
        id=connection.id,
        provider=connection.provider,
        account_label=connection.account_label,
        external_account_id=connection.external_account_id,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
        revoked_at=connection.revoked_at,
    )


def _serialize_publish_job(job: PublishJob) -> PublishJobView:
    return PublishJobView(
        id=job.id,
        provider=job.provider,
        connection_id=job.connection_id,
        asset_id=job.asset_id,
        status=job.status,
        retry_count=job.retry_count,
        payload=dict(job.payload or {}),
        error=job.error,
        external_post_id=job.external_post_id,
        published_url=job.published_url,
        task_id=job.task_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _emit_automation_event(
    session: Session,
    *,
    org_id: UUID | None,
    workflow_run_id: UUID | None,
    publish_job_id: UUID | None,
    step_name: str,
    status_value: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        AutomationRunEvent(
            org_id=org_id,
            workflow_run_id=workflow_run_id,
            publish_job_id=publish_job_id,
            step_name=step_name,
            status=status_value,
            message=message,
            payload=payload or {},
            created_at=_now(),
        )
    )


@lru_cache(maxsize=1)
def _celery_app() -> Celery:
    settings = get_settings()
    app = Celery("reframe_publish_api", broker=settings.broker_url, backend=settings.result_backend)
    app.conf.broker_connection_retry_on_startup = False
    app.conf.broker_connection_max_retries = 0
    return app


def _dispatch_publish_task(job: PublishJob) -> str:
    if is_local_queue_mode():
        return dispatch_local_task("tasks.publish_asset", str(job.id))
    result = _celery_app().send_task("tasks.publish_asset", args=[str(job.id)])
    return result.id


def _require_hosted_principal(principal) -> None:
    if not principal.org_id or not principal.user_id:
        raise unauthorized("Authentication required")


@router.get(
    "/publish/providers",
    response_model=list[PublishProviderView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}},
)
def list_publish_providers(session: SessionDep, principal: PrincipalDep) -> list[PublishProviderView]:
    _require_hosted_principal(principal)
    rows = []
    for provider in SUPPORTED_PUBLISH_PROVIDERS:
        count = len(
            session.exec(
                select(PublishConnection).where(
                    (PublishConnection.org_id == principal.org_id)
                    & (PublishConnection.provider == provider)
                    & (PublishConnection.revoked_at == None)  # noqa: E711
                )
            ).all()
        )
        rows.append(PublishProviderView(provider=provider, display_name=_provider_display(provider), connected_count=count))
    return rows


@router.get(
    "/publish/{provider}/connections",
    response_model=list[PublishConnectionView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}},
)
def list_publish_connections(provider: str, session: SessionDep, principal: PrincipalDep) -> list[PublishConnectionView]:
    _require_hosted_principal(principal)
    normalized = _validate_provider(provider)
    rows = session.exec(
        select(PublishConnection).where(
            (PublishConnection.org_id == principal.org_id)
            & (PublishConnection.provider == normalized)
            & (PublishConnection.revoked_at == None)  # noqa: E711
        )
    ).all()
    return [_serialize_connection(item) for item in rows]


@router.get(
    "/publish/{provider}/connect/start",
    response_model=PublishConnectStartResponse,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}},
)
def start_publish_connection(
    provider: str,
    session: SessionDep,
    principal: PrincipalDep,
    redirect_to: str | None = Query(default=None),
) -> PublishConnectStartResponse:
    _require_hosted_principal(principal)
    normalized = _validate_provider(provider)
    state = create_oauth_state(provider=f"publish:{normalized}:{principal.org_id}", redirect_to=redirect_to)
    settings = get_settings()
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/api/v1/publish/{normalized}/connect/callback"
    authorize_url = (
        f"{settings.app_base_url.rstrip('/')}/mock-oauth/{normalized}"
        f"?state={state}"
        f"&redirect_uri={redirect_uri}"
    )
    return PublishConnectStartResponse(
        provider=normalized,
        authorize_url=authorize_url,
        state=state,
        redirect_uri=redirect_uri,
    )


@router.get(
    "/publish/{provider}/connect/callback",
    response_model=PublishConnectionView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def complete_publish_connection(
    provider: str,
    state: str,
    session: SessionDep,
    principal: PrincipalDep,
    code: str | None = Query(default=None),
    refresh_token: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    account_label: str | None = Query(default=None),
) -> PublishConnectionView:
    _require_hosted_principal(principal)
    normalized = _validate_provider(provider)
    state_provider, _ = parse_oauth_state(state)
    expected_prefix = f"publish:{normalized}:{principal.org_id}"
    if state_provider != expected_prefix:
        raise unauthorized("Invalid publish OAuth state")

    if not code and not refresh_token:
        raise unauthorized("Provider callback is missing OAuth code")

    connection = PublishConnection(
        org_id=principal.org_id,
        user_id=principal.user_id,
        provider=normalized,
        account_label=(account_label or f"{_provider_display(normalized)} account").strip(),
        external_account_id=(account_id or "").strip() or None,
        token_ref=_hash_secret(code),
        refresh_token_ref=_hash_secret(refresh_token or code),
        connection_meta={"connected_via": "oauth_callback"},
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(connection)
    _emit_automation_event(
        session,
        org_id=principal.org_id,
        workflow_run_id=None,
        publish_job_id=None,
        step_name=f"publish.connect.{normalized}",
        status_value="connected",
        payload={"connection_id": str(connection.id)},
    )
    session.commit()
    session.refresh(connection)
    return _serialize_connection(connection)


@router.delete(
    "/publish/{provider}/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def revoke_publish_connection(
    provider: str,
    connection_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> Response:
    _require_hosted_principal(principal)
    normalized = _validate_provider(provider)
    connection = session.get(PublishConnection, connection_id)
    if not connection or connection.provider != normalized or connection.org_id != principal.org_id:
        raise not_found("Publish connection not found", {"connection_id": str(connection_id)})
    connection.revoked_at = _now()
    connection.updated_at = _now()
    session.add(connection)
    _emit_automation_event(
        session,
        org_id=principal.org_id,
        workflow_run_id=None,
        publish_job_id=None,
        step_name=f"publish.connect.{normalized}",
        status_value="revoked",
        payload={"connection_id": str(connection.id)},
    )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/publish/jobs",
    response_model=PublishJobView,
    status_code=status.HTTP_201_CREATED,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_publish_job(payload: PublishJobCreateRequest, session: SessionDep, principal: PrincipalDep) -> PublishJobView:
    _require_hosted_principal(principal)
    provider = _validate_provider(payload.provider)
    connection = session.get(PublishConnection, payload.connection_id)
    if not connection or connection.org_id != principal.org_id or connection.provider != provider or connection.revoked_at is not None:
        raise not_found("Publish connection not found", {"connection_id": str(payload.connection_id)})
    asset = session.get(MediaAsset, payload.asset_id)
    if not asset or asset.org_id != principal.org_id:
        raise not_found("Media asset not found", {"asset_id": str(payload.asset_id)})

    job = PublishJob(
        org_id=principal.org_id,
        user_id=principal.user_id,
        provider=provider,
        connection_id=connection.id,
        asset_id=asset.id,
        status="queued",
        payload={
            "title": (payload.title or "").strip() or None,
            "description": (payload.description or "").strip() or None,
            "tags": [item.strip() for item in payload.tags if item.strip()],
            "schedule_at": payload.schedule_at.isoformat() if payload.schedule_at else None,
            "workflow_run_id": str(payload.workflow_run_id) if payload.workflow_run_id else None,
        },
        retry_count=0,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        job.task_id = _dispatch_publish_task(job)
    except Exception as exc:  # pragma: no cover
        job.status = "failed"
        job.error = str(exc)
    job.updated_at = _now()
    session.add(job)
    _emit_automation_event(
        session,
        org_id=principal.org_id,
        workflow_run_id=payload.workflow_run_id,
        publish_job_id=job.id,
        step_name=f"publish.job.{provider}",
        status_value=job.status,
        payload={"task_id": job.task_id},
    )
    session.commit()
    session.refresh(job)
    return _serialize_publish_job(job)


@router.get(
    "/publish/jobs",
    response_model=list[PublishJobView],
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}},
)
def list_publish_jobs(
    session: SessionDep,
    principal: PrincipalDep,
    provider: Optional[str] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> list[PublishJobView]:
    _require_hosted_principal(principal)
    query = select(PublishJob).where(PublishJob.org_id == principal.org_id).order_by(PublishJob.created_at.desc())
    if provider:
        query = query.where(PublishJob.provider == _validate_provider(provider))
    if status_filter:
        query = query.where(PublishJob.status == status_filter.strip().lower())
    jobs = session.exec(query).all()
    return [_serialize_publish_job(job) for job in jobs]


@router.get(
    "/publish/jobs/{job_id}",
    response_model=PublishJobView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_publish_job(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> PublishJobView:
    _require_hosted_principal(principal)
    job = session.get(PublishJob, job_id)
    if not job or job.org_id != principal.org_id:
        raise not_found("Publish job not found", {"job_id": str(job_id)})
    return _serialize_publish_job(job)


@router.post(
    "/publish/jobs/{job_id}/retry",
    response_model=PublishJobView,
    tags=["Projects"],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def retry_publish_job(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> PublishJobView:
    _require_hosted_principal(principal)
    job = session.get(PublishJob, job_id)
    if not job or job.org_id != principal.org_id:
        raise not_found("Publish job not found", {"job_id": str(job_id)})
    if job.status not in {"failed", "cancelled"}:
        raise conflict("Publish job is not retryable", details={"status": job.status})
    job.status = "queued"
    job.error = None
    job.retry_count = int(job.retry_count or 0) + 1
    try:
        job.task_id = _dispatch_publish_task(job)
    except Exception as exc:  # pragma: no cover
        job.status = "failed"
        job.error = str(exc)
    job.updated_at = _now()
    session.add(job)
    workflow_run_id = None
    raw_workflow_id = (job.payload or {}).get("workflow_run_id")
    if raw_workflow_id:
        try:
            workflow_run_id = UUID(str(raw_workflow_id))
        except ValueError:
            workflow_run_id = None
    _emit_automation_event(
        session,
        org_id=principal.org_id,
        workflow_run_id=workflow_run_id,
        publish_job_id=job.id,
        step_name=f"publish.job.{job.provider}",
        status_value=job.status,
        message="retry",
        payload={"task_id": job.task_id, "retry_count": job.retry_count},
    )
    session.commit()
    session.refresh(job)
    return _serialize_publish_job(job)
