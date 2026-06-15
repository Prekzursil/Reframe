"""Database engine, schema creation, and session helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    """Create (and cache) the SQLModel engine from application settings."""
    settings = get_settings()
    url = settings.database_url
    # `database_url` is a runtime ``str``; pylint sees the pydantic FieldInfo default.
    connect_args = (
        {"check_same_thread": False}
        if url.startswith("sqlite")  # pylint: disable=no-member
        else {}
    )
    return create_engine(url, echo=False, connect_args=connect_args)


def create_db_and_tables() -> None:
    """Create all database tables, ensuring model metadata is registered first."""
    # Import models so SQLModel sees the metadata before creating tables.
    from app import models  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import

    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a SQLModel session bound to the cached engine."""
    engine = get_engine()
    with Session(engine) as session:
        yield session
