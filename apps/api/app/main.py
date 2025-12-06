from fastapi import FastAPI

from app.config import get_settings
from app.database import create_db_and_tables


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)

    @app.on_event("startup")
    def startup() -> None:
        create_db_and_tables()

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.api_version}

    return app


app = create_app()
