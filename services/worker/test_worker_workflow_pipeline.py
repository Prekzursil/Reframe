from __future__ import annotations

from pathlib import Path


class _Result:
    def __init__(self, task_id: str):
        self.id = task_id


def test_run_workflow_pipeline_dispatches_child_jobs(monkeypatch, tmp_path: Path):
    from app.config import get_settings
    from app.database import create_db_and_tables, get_engine
    from app.models import MediaAsset, Organization, User, WorkflowRun, WorkflowRunStep, WorkflowTemplate
    from services.worker import worker
    from sqlmodel import Session

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "reframe-test.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))

    get_settings.cache_clear()
    get_engine.cache_clear()
    worker._engine = None
    worker._media_tmp = None
    create_db_and_tables()

    calls: list[dict] = []

    def fake_send_task(task_name: str, args: list, queue: str | None = None):
        calls.append({"task_name": task_name, "args": args, "queue": queue})
        return _Result(f"task-{len(calls)}")

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)

    with Session(get_engine()) as session:
        user = User(email="pipeline-owner@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)

        org = Organization(name="Pipeline Org", slug="pipeline-org")
        session.add(org)
        session.commit()
        session.refresh(org)

        template = WorkflowTemplate(
            name="Pipeline",
            steps=[
                {"type": "captions", "payload": {"formats": ["srt"]}},
                {"type": "shorts", "payload": {"max_clips": 2}},
            ],
            org_id=org.id,
            owner_user_id=user.id,
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        input_asset = MediaAsset(
            kind="video",
            uri="tmp://workflow-input.mp4",
            mime_type="video/mp4",
            org_id=org.id,
            owner_user_id=user.id,
        )
        session.add(input_asset)
        session.commit()
        session.refresh(input_asset)

        run = WorkflowRun(
            template_id=template.id,
            org_id=org.id,
            owner_user_id=user.id,
            input_asset_id=input_asset.id,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        session.add(WorkflowRunStep(run_id=run.id, order_index=0, step_type="captions", payload={"formats": ["srt"]}))
        session.add(WorkflowRunStep(run_id=run.id, order_index=1, step_type="shorts", payload={"max_clips": 2}))
        session.commit()

        run_id = str(run.id)

    result = worker.run_workflow_pipeline.run(run_id)

    assert result["status"] == "completed"
    assert len(calls) == 2
    assert calls[0]["task_name"] == "tasks.generate_captions"
    assert calls[1]["task_name"] == "tasks.generate_shorts"
