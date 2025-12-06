from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import create_db_and_tables
from app.api import router as api_router
from app.errors import ApiError, ErrorResponse
from app.cleanup import start_cleanup_loop


def create_app() -> FastAPI:
    settings = get_settings()
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

    app = FastAPI(title=settings.api_title, version=settings.api_version, openapi_tags=tags_metadata)

    app.mount("/media", StaticFiles(directory=settings.media_root), name="media")

    @app.on_event("startup")
    def startup() -> None:
        create_db_and_tables()
        start_cleanup_loop(settings.media_root)

    @app.exception_handler(ApiError)
    async def api_error_handler(_, exc: ApiError):
        payload = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.api_version}

    return app


app = create_app()
