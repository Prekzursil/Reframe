from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[3]
_tools_bin = REPO_ROOT / ".tools" / "bin"
if _tools_bin.is_dir():
    os.environ["PATH"] = f"{_tools_bin}{os.pathsep}{os.environ.get('PATH', '')}"

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

def _derived_test_secret(label: str) -> str:
    return hashlib.sha256(f"reframe-test::{label}".encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _set_test_security_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REFRAME_JWT_SECRET", _derived_test_secret("jwt"))
    monkeypatch.setenv("REFRAME_JWT_REFRESH_SECRET", _derived_test_secret("jwt-refresh"))
    monkeypatch.setenv("REFRAME_OAUTH_STATE_SECRET", _derived_test_secret("oauth-state"))

    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = f"sqlite:////{str(db_path).lstrip('/')}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))

    from app.api import get_celery_app
    from app.config import get_settings
    from app.database import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_celery_app.cache_clear()

    import app.api as api_module

    enqueued: list[dict] = []

    def fake_enqueue_job(job, task_name: str, *args) -> str:
        enqueued.append({"task": task_name, "args": args, "job_id": str(job.id)})
        return f"test-task-{len(enqueued)}"

    monkeypatch.setattr(api_module, "enqueue_job", fake_enqueue_job)

    from app.main import create_app

    app = create_app()

    from services.worker import worker

    worker._engine = None
    worker._media_tmp = None

    with TestClient(app) as client:
        yield client, enqueued, worker, media_root
