from __future__ import annotations

from functools import lru_cache
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    return create_engine(settings.database.url, echo=False)


def create_db_and_tables() -> None:
    # Import models so SQLModel sees the metadata before creating tables.
    from app import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
