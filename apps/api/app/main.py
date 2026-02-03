import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import create_db_and_tables
from app.api import router as api_router
from app.errors import ApiError, ErrorResponse
from app.cleanup import start_cleanup_loop
from app.logging_config import setup_logging


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
        {"name": "Presets", "description": "Subtitle style presets."},
    ]

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        create_db_and_tables()
        start_cleanup_loop(settings.media_root)
        yield

    app = FastAPI(title=settings.api_title, version=settings.api_version, openapi_tags=tags_metadata, lifespan=lifespan)

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

    @app.get("/health", tags=["Health"])
    @app.get("/healthz", tags=["Health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.api_version}

    return app


app = create_app()
