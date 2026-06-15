"""Shared fixtures for the worker test-suite.

Every fixture wires a throw-away SQLite database and media root, resets the
worker's lazily-built singletons, and creates the schema so the Celery task
bodies can be exercised end-to-end without a real broker or ffmpeg binary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest


@dataclass
class WorkerEnv:
    """Bundle of the loaded worker module and helpers for a test."""

    worker: Any
    engine: Any
    media_root: Path
    Session: Any  # noqa: N815 - mirrors sqlmodel.Session import name

    def session(self):
        """Open a new SQLModel session bound to the test engine."""
        return self.Session(self.engine)

    def add_asset(self, *, kind: str = "video", uri: str, mime_type: str, **kwargs):
        """Persist and return a MediaAsset row."""
        from app.models import MediaAsset  # pylint: disable=import-outside-toplevel

        asset = MediaAsset(kind=kind, uri=uri, mime_type=mime_type, **kwargs)
        with self.session() as session:
            session.add(asset)
            session.commit()
            session.refresh(asset)
            return asset

    def add_job(self, **kwargs):
        """Persist and return a Job row."""
        from app.models import Job, JobStatus  # pylint: disable=import-outside-toplevel

        kwargs.setdefault("job_type", "generic")
        kwargs.setdefault("status", JobStatus.queued)
        job = Job(**kwargs)
        with self.session() as session:
            session.add(job)
            session.commit()
            session.refresh(job)
            return job

    def get_job(self, job_id):
        """Reload a Job row by id."""
        from app.models import Job  # pylint: disable=import-outside-toplevel

        with self.session() as session:
            return session.get(Job, UUID(str(job_id)))

    def write_media_file(self, asset, contents: bytes = b"data") -> Path:
        """Write a file to the local media root matching ``asset.uri``.

        Mirrors :func:`worker._resolve_local_asset_path` so ``fetch_asset`` can
        resolve the asset to a real on-disk file.
        """
        uri_path = Path(str(asset.uri).lstrip("/"))
        if uri_path.parts and uri_path.parts[0] == "media":  # pragma: no branch
            uri_path = Path(*uri_path.parts[1:])
        target = self.media_root / uri_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        return target


@pytest.fixture()
def worker_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WorkerEnv:
    """Provision an isolated worker runtime backed by SQLite and a tmp media root."""
    # Imports are function-local so monkeypatched env vars are visible before the
    # settings-reading modules are (re)loaded.
    # pylint: disable=import-outside-toplevel,import-error
    from app.config import get_settings
    from app.database import create_db_and_tables, get_engine
    from services.worker import worker
    from sqlmodel import Session

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = "sqlite:///" + db_path.as_posix()
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))
    # Keep behavioural tests deterministic: never sleep on retry backoff.
    monkeypatch.setattr(worker.time, "sleep", lambda _s: None)

    get_settings.cache_clear()
    get_engine.cache_clear()
    worker._engine = None  # pylint: disable=protected-access
    worker._media_tmp = None  # pylint: disable=protected-access
    create_db_and_tables()

    return WorkerEnv(
        worker=worker,
        engine=get_engine(),
        media_root=media_root,
        Session=Session,
    )
