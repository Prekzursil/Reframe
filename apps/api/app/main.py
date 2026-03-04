import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.auth_api import router as auth_router
from app.billing_api import router as billing_router
from app.cleanup import start_cleanup_loop
from app.collaboration_api import router as collaboration_router
from app.config import get_settings
from app.database import create_db_and_tables
from app.errors import ApiError, ErrorResponse
from app.identity_api import router as identity_router
from app.logging_config import setup_logging
from app.publish_api import router as publish_router


_RESERVED_DESKTOP_PREFIXES = (
    "api/",
    "docs",
    "openapi.json",
    "redoc",
    "media/",
    "health",
    "healthz",
)


def _mount_desktop_web(app: FastAPI, desktop_web_dist: str) -> None:
    raw = (desktop_web_dist or "").strip()
    if not raw:
        return

    web_dist = Path(raw).resolve()
    index_path = web_dist / "index.html"
    if not index_path.is_file():
        return

    @app.get("/", include_in_schema=False)
    def desktop_index() -> FileResponse:
        return FileResponse(index_path)

    @app.get("/{full_path:path}", include_in_schema=False)
    def desktop_spa(full_path: str) -> FileResponse:
        normalized = (full_path or "").lstrip("/")
        if any(
            normalized == reserved or normalized.startswith(f"{reserved}/")
            for reserved in _RESERVED_DESKTOP_PREFIXES
        ):
            raise HTTPException(status_code=404)

        candidate = (web_dist / normalized).resolve(strict=False)
        try:
            candidate.relative_to(web_dist)
        except ValueError as exc:
            raise HTTPException(status_code=404) from exc

        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(log_format=settings.log_format, log_level=settings.log_level)
    request_logger = logging.getLogger("reframe.request")
    tags_metadata = [
        {"name": "Health", "description": "Health and readiness checks."},
        {"name": "Captions", "description": "Create captioning jobs."},
        {"name": "Translate", "description": "Translate subtitle assets."},
        {"name": "Shorts", "description": "Create shorts generation jobs."},
        {"name": "Utilities", "description": "Utility processing like merge A/V."},
        {"name": "Jobs", "description": "Job retrieval and listings."},
        {"name": "Assets", "description": "Manage media assets."},
        {"name": "Projects", "description": "Project containers and share-link flows."},
        {"name": "Usage", "description": "Aggregated usage and processing metrics."},
        {"name": "Auth", "description": "Authentication, OAuth, and organization context."},
        {"name": "Billing", "description": "Subscription, checkout, and usage quota endpoints."},
        {"name": "Presets", "description": "Subtitle style presets."},
        {"name": "System", "description": "Diagnostics for local setup."},
    ]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        create_db_and_tables()
        start_cleanup_loop(
            settings.media_root,
            interval_seconds=int(settings.cleanup_interval_seconds),
            ttl_hours=int(settings.cleanup_ttl_hours),
        )
        yield

    app = FastAPI(title=settings.api_title, version=settings.api_version, openapi_tags=tags_metadata, lifespan=lifespan)

    Path(settings.media_root).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        request_id = request.headers.get("x-request-id") or str(uuid4())
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000.0
            request_logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query,
                    "duration_ms": round(duration_ms, 2),
                    "client": request.client.host if request.client else None,
                },
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        request_logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client": request.client.host if request.client else None,
            },
        )
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_, exc: ApiError):
        payload = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    app.include_router(api_router)
    app.include_router(auth_router)
    app.include_router(identity_router)
    app.include_router(collaboration_router)
    app.include_router(publish_router)
    app.include_router(billing_router)

    @app.get("/health", tags=["Health"])
    @app.get("/healthz", tags=["Health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.api_version}

    _mount_desktop_web(app, settings.desktop_web_dist)

    return app


app = create_app()
