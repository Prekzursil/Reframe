from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


@pytest.fixture()
def test_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = f"sqlite:////{str(db_path).lstrip('/')}"
    monkeypatch.setenv("REFRAME_DATABASE", json.dumps({"url": db_url}))
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

