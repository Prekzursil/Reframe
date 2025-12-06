from fastapi import FastAPI

from app.config import get_settings
from app.database import create_db_and_tables
from app.api import router as api_router


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

    @app.on_event("startup")
    def startup() -> None:
        create_db_and_tables()

    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.api_version}

    return app


app = create_app()
