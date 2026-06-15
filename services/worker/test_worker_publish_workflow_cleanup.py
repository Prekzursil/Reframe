"""Tests for publish_asset, run_workflow_pipeline, and cleanup_retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models import (  # pylint: disable=import-error
    AutomationRunEvent,
    JobStatus,
    MediaAsset,
    PublishConnection,
    PublishJob,
    Subscription,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowStepStatus,
    WorkflowTemplate,
)
from sqlmodel import select  # pylint: disable=import-error


def _conn_and_asset(worker_env, *, provider="youtube", revoked=False):
    org, user = uuid4(), uuid4()
    asset = worker_env.add_asset(
        uri=f"/media/tmp/{provider}.mp4", mime_type="video/mp4", org_id=org
    )
    conn = PublishConnection(
        org_id=org,
        user_id=user,
        provider=provider,
        account_label=f"{provider} label",
        external_account_id=f"{provider}-acct",
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    with worker_env.session() as session:
        session.add(conn)
        session.commit()
        session.refresh(conn)
    return conn, asset


# --------------------------------------------------------------------------- #
# publish_asset
# --------------------------------------------------------------------------- #


def test_publish_asset_creates_and_completes(worker_env):
    """Publishing with inline args creates a job and completes it."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="youtube")
    result = worker.publish_asset.run(
        None, "youtube", str(conn.id), str(asset.id), None, {"title": "Hi"}
    )
    assert result["status"] == "completed"
    assert result["published_url"].startswith("https://")
    with worker_env.session() as session:
        events = session.exec(select(AutomationRunEvent)).all()
    statuses = {e.status for e in events}
    assert "running" in statuses and "completed" in statuses


def test_publish_asset_missing_required_args(worker_env):
    """Publishing without ids and without a publish_job_id fails validation."""
    worker = worker_env.worker
    result = worker.publish_asset.run(None, None, None, None, None, {})
    assert result["status"] == "failed"


def test_publish_asset_invalid_publish_job_id(worker_env):
    """A non-UUID publish_job_id returns the invalid status."""
    worker = worker_env.worker
    result = worker.publish_asset.run("not-a-uuid")
    assert result["status"] == "invalid_publish_job_id"


def test_publish_asset_missing_publish_job(worker_env):
    """A valid-but-unknown publish_job_id returns the missing status."""
    worker = worker_env.worker
    result = worker.publish_asset.run(str(uuid4()))
    assert result["status"] == "missing"


def test_publish_asset_unsupported_provider(worker_env):
    """An unsupported provider is rejected during validation."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="youtube")
    result = worker.publish_asset.run(
        None, "myspace", str(conn.id), str(asset.id), None, {}
    )
    assert result["status"] == "failed"
    assert "unsupported_provider" in result["error"]


def test_publish_asset_connection_missing(worker_env):
    """A connection id that resolves to nothing fails validation."""
    worker = worker_env.worker
    asset = worker_env.add_asset(uri="/media/tmp/x.mp4", mime_type="video/mp4")
    result = worker.publish_asset.run(
        None, "youtube", str(uuid4()), str(asset.id), None, {}
    )
    assert result["status"] == "failed"
    assert result["error"] == "publish_connection_missing"


def test_publish_asset_asset_missing(worker_env):
    """An asset id that resolves to nothing fails validation."""
    worker = worker_env.worker
    conn, _ = _conn_and_asset(worker_env, provider="youtube")
    result = worker.publish_asset.run(
        None, "youtube", str(conn.id), str(uuid4()), None, {}
    )
    assert result["status"] == "failed"
    assert result["error"] == "asset_missing"


def test_publish_asset_revoked_connection(worker_env):
    """A revoked connection on an existing publish job fails the publish."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="tiktok", revoked=True)
    job = PublishJob(
        org_id=conn.org_id,
        user_id=conn.user_id,
        provider="tiktok",
        connection_id=conn.id,
        asset_id=asset.id,
        status="queued",
    )
    with worker_env.session() as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = str(job.id)
    result = worker.publish_asset.run(job_id)
    assert result["status"] == "failed"
    assert result["error"] == "publish_connection_invalid"


def test_publish_asset_existing_job_asset_missing(worker_env):
    """An existing job whose asset row is gone fails with asset_missing."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="instagram")
    job = PublishJob(
        org_id=conn.org_id,
        user_id=conn.user_id,
        provider="instagram",
        connection_id=conn.id,
        asset_id=asset.id,
        status="queued",
    )
    with worker_env.session() as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = str(job.id)
        # Remove the asset so the lookup misses.
        stored = session.get(MediaAsset, asset.id)
        session.delete(stored)
        session.commit()
    result = worker.publish_asset.run(job_id)
    assert result["status"] == "failed"
    assert result["error"] == "publish_asset_missing"


def test_publish_asset_with_task_id_and_workflow(worker_env):
    """A bound task id and workflow run id are recorded on the publish job."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="facebook")
    # ``apply`` runs the task eagerly and assigns a concrete request id, which
    # exercises the ``job.task_id = task_id`` branch in the task body.
    async_result = worker.publish_asset.apply(
        args=[
            None,
            "facebook",
            str(conn.id),
            str(asset.id),
            str(uuid4()),
            {"title": "FB"},
        ],
        task_id="celery-task-7",
    )
    result = async_result.get()
    assert result["status"] == "completed"
    with worker_env.session() as session:
        job = session.get(PublishJob, uuid_from(result["publish_job_id"]))
    assert job.task_id == "celery-task-7"


def test_publish_asset_invalid_workflow_run_id(worker_env):
    """An invalid workflow run id is tolerated (treated as no workflow)."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="youtube")
    result = worker.publish_asset.run(
        None, "youtube", str(conn.id), str(asset.id), "not-a-uuid", {}
    )
    assert result["status"] == "completed"


def test_publish_asset_execute_failure(worker_env, monkeypatch):
    """A failure inside the provider adapter marks the publish job failed."""
    worker = worker_env.worker
    conn, asset = _conn_and_asset(worker_env, provider="youtube")

    def boom(**_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(worker, "_publish_result_for_provider", boom)
    result = worker.publish_asset.run(
        None, "youtube", str(conn.id), str(asset.id), None, {}
    )
    assert result["status"] == "failed"
    assert "provider exploded" in result["error"]


def uuid_from(value):
    """Small helper to convert a stringified UUID back to a UUID object."""
    from uuid import UUID  # pylint: disable=import-outside-toplevel

    return UUID(str(value))


# --------------------------------------------------------------------------- #
# run_workflow_pipeline
# --------------------------------------------------------------------------- #


def test_workflow_invalid_run_id(worker_env):
    """An invalid run id returns the invalid status."""
    worker = worker_env.worker
    assert worker.run_workflow_pipeline.run("bad")["status"] == "invalid_run_id"


def test_workflow_missing_run(worker_env):
    """An unknown run id returns the missing status."""
    worker = worker_env.worker
    assert worker.run_workflow_pipeline.run(str(uuid4()))["status"] == "missing"


def _make_run(worker_env, *, steps, status=WorkflowRunStatus.queued, with_template=True):
    org, user = uuid4(), uuid4()
    input_asset = worker_env.add_asset(
        uri="/media/tmp/in.mp4", mime_type="video/mp4", org_id=org
    )
    template_id = None
    if with_template:
        template = WorkflowTemplate(
            name="T", steps=steps, org_id=org, owner_user_id=user
        )
        with worker_env.session() as session:
            session.add(template)
            session.commit()
            session.refresh(template)
            template_id = template.id
    else:
        template_id = uuid4()
    run = WorkflowRun(
        template_id=template_id,
        org_id=org,
        owner_user_id=user,
        input_asset_id=input_asset.id,
        status=status,
    )
    with worker_env.session() as session:
        session.add(run)
        session.commit()
        session.refresh(run)
        for idx, step in enumerate(steps):
            session.add(
                WorkflowRunStep(
                    run_id=run.id,
                    order_index=idx,
                    step_type=step["type"],
                    payload=step.get("payload", {}),
                )
            )
        session.commit()
        run_id = str(run.id)
    return run_id


def test_workflow_cancelled_run(worker_env):
    """A run already cancelled returns the cancelled status immediately."""
    worker = worker_env.worker
    run_id = _make_run(
        worker_env,
        steps=[{"type": "captions"}],
        status=WorkflowRunStatus.cancelled,
    )
    assert worker.run_workflow_pipeline.run(run_id)["status"] == "cancelled"


def test_workflow_template_missing(worker_env):
    """A run whose template is gone is failed with template_missing."""
    worker = worker_env.worker
    run_id = _make_run(
        worker_env, steps=[{"type": "captions"}], with_template=False
    )
    result = worker.run_workflow_pipeline.run(run_id)
    assert result["status"] == "failed"
    assert result["error"] == "template_missing"


def test_workflow_dispatch_success(worker_env, monkeypatch):
    """A workflow dispatches each step and completes."""
    worker = worker_env.worker
    run_id = _make_run(
        worker_env,
        steps=[
            {"type": "captions", "payload": {"formats": ["srt"]}},
            {"type": "shorts", "payload": {"max_clips": 1}},
        ],
    )
    sent: list = []
    monkeypatch.setattr(
        worker.celery_app,
        "send_task",
        lambda name, args, queue=None: sent.append(name) or type(
            "R", (), {"id": f"t{len(sent)}"}
        )(),
    )
    result = worker.run_workflow_pipeline.run(run_id)
    assert result["status"] == "completed"
    assert len(result["dispatched_jobs"]) == 2


def test_workflow_step_dispatch_failure(worker_env, monkeypatch):
    """A failing step dispatch fails the run and marks the step failed."""
    worker = worker_env.worker
    run_id = _make_run(worker_env, steps=[{"type": "captions"}])

    def boom(*_a, **_k):
        raise RuntimeError("dispatch boom")

    monkeypatch.setattr(worker.celery_app, "send_task", boom)
    result = worker.run_workflow_pipeline.run(run_id)
    assert result["status"] == "failed"
    assert "dispatch boom" in result["error"]


def test_workflow_step_cancelled_midway(worker_env, monkeypatch):
    """Cancelling the run between steps marks the remaining steps cancelled."""
    worker = worker_env.worker
    from uuid import UUID  # pylint: disable=import-outside-toplevel

    run_id = _make_run(
        worker_env,
        steps=[{"type": "captions"}, {"type": "shorts"}],
    )

    # Dispatching the first step cancels the run on the task's own ``run``
    # object (identity-mapped in its session), so the next iteration's
    # cancellation check at the top of the loop deterministically fires.
    dispatched: list[str] = []

    # pylint: disable-next=unused-argument
    def fake_dispatch(*, job, run, step_type, input_asset_id, step_payload):  # noqa: D401
        dispatched.append(step_type)
        run.status = WorkflowRunStatus.cancelled
        return "task-1"

    monkeypatch.setattr(worker, "_dispatch_pipeline_step", fake_dispatch)
    worker.run_workflow_pipeline.run(run_id)

    with worker_env.session() as session:
        steps = session.exec(
            select(WorkflowRunStep)
            .where(WorkflowRunStep.run_id == UUID(run_id))
            .order_by(WorkflowRunStep.order_index.asc())
        ).all()
    # Only the first step dispatched; the second took the cancellation branch.
    assert dispatched == ["captions"]
    assert steps[0].status == WorkflowStepStatus.completed
    assert steps[1].status == WorkflowStepStatus.cancelled


# --------------------------------------------------------------------------- #
# cleanup_retention
# --------------------------------------------------------------------------- #


def test_cleanup_retention_removes_aged_jobs(worker_env):
    """Cleanup deletes aged terminal jobs and their unreferenced assets."""
    worker = worker_env.worker
    org = uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(days=100)
    out_asset = worker_env.add_asset(
        uri="/media/tmp/old.mp4", mime_type="video/mp4", org_id=org
    )
    worker_env.write_media_file(out_asset, b"old")
    with worker_env.session() as session:
        session.add(Subscription(org_id=org, plan_code="free"))
        session.commit()
    job = worker_env.add_job(
        job_type="shorts",
        org_id=org,
        status=JobStatus.completed,
        output_asset_id=out_asset.id,
        payload={"clip_assets": [{"asset_id": str(out_asset.id)}]},
    )
    with worker_env.session() as session:
        stored = session.get(__import__("app.models", fromlist=["Job"]).Job, job.id)
        stored.updated_at = old_time
        session.add(stored)
        session.commit()
    result = worker.cleanup_retention.run()
    assert result["status"] == "ok"
    assert result["cleaned_jobs"] == 1


def test_cleanup_retention_keeps_recent_jobs(worker_env):
    """Recent jobs and jobs without an org are left untouched."""
    worker = worker_env.worker
    org = uuid4()
    with worker_env.session() as session:
        session.add(Subscription(org_id=org, plan_code="free"))
        session.commit()
    worker_env.add_job(job_type="cut", org_id=org, status=JobStatus.completed)
    worker_env.add_job(job_type="cut", status=JobStatus.failed)  # no org -> skipped
    result = worker.cleanup_retention.run()
    assert result["cleaned_jobs"] == 0
