"""Tests for the worker's database-backed helpers (assets, jobs, usage)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import select  # pylint: disable=import-error

from app.models import (  # pylint: disable=import-error
    Job,
    JobStatus,
    MediaAsset,
    Subscription,
    UsageEvent,
    UsageLedgerEntry,
)


def test_get_engine_and_media_tmp_are_cached(worker_env):
    """The engine and media tmp dir are built lazily and cached."""
    worker = worker_env.worker
    assert worker.get_engine() is worker.get_engine()
    tmp = worker.get_media_tmp()
    assert tmp.exists()
    assert worker.get_media_tmp() is tmp


def test_new_tmp_file_normalizes_suffix(worker_env):
    """``new_tmp_file`` prefixes a dot when the suffix lacks one."""
    worker = worker_env.worker
    assert worker.new_tmp_file("mp4").suffix == ".mp4"
    assert worker.new_tmp_file(".srt").suffix == ".srt"


def test_create_asset_from_contents(worker_env):
    """``create_asset`` writes inline contents and persists a MediaAsset."""
    worker = worker_env.worker
    asset = worker.create_asset(
        kind="subtitle", mime_type="text/srt", suffix=".srt", contents="hello"
    )
    assert asset.id is not None
    path = worker_env.media_root / Path(asset.uri.lstrip("/")).relative_to("media")
    assert path.read_text(encoding="utf-8") == "hello"


def test_create_asset_from_source_path(worker_env, tmp_path):
    """``create_asset`` copies a source file when one is supplied."""
    worker = worker_env.worker
    src = tmp_path / "src.png"
    src.write_bytes(b"img-bytes")
    asset = worker.create_asset(
        kind="image", mime_type="image/png", suffix=".png", source_path=src
    )
    path = worker_env.media_root / Path(asset.uri.lstrip("/")).relative_to("media")
    assert path.read_bytes() == b"img-bytes"


def test_create_asset_for_existing_file_rejects_outside_tmp(worker_env, tmp_path):
    """Registering a file outside the worker tmp dir is rejected."""
    worker = worker_env.worker
    stray = tmp_path / "stray.mp4"
    stray.write_bytes(b"x")
    with pytest.raises(ValueError, match="must be under"):
        worker.create_asset_for_existing_file(
            kind="video", mime_type="video/mp4", file_path=stray
        )


def test_create_asset_for_existing_file_under_tmp(worker_env):
    """A file inside the tmp dir is registered as an asset."""
    worker = worker_env.worker
    tmp_file = worker.new_tmp_file(".mp4")
    tmp_file.write_bytes(b"video")
    asset = worker.create_asset_for_existing_file(
        kind="video", mime_type="video/mp4", file_path=tmp_file
    )
    assert asset.kind == "video"


def test_fetch_asset_invalid_id_returns_none(worker_env):
    """A non-UUID asset id returns ``(None, None)``."""
    worker = worker_env.worker
    assert worker.fetch_asset("not-a-uuid") == (None, None)


def test_fetch_asset_missing_returns_none(worker_env):
    """An unknown but valid UUID returns ``(None, None)``."""
    worker = worker_env.worker
    assert worker.fetch_asset(str(uuid4())) == (None, None)


def test_fetch_asset_local_path(worker_env):
    """A local asset resolves to its on-disk media path."""
    worker = worker_env.worker
    asset = worker_env.add_asset(uri="/media/tmp/clip.mp4", mime_type="video/mp4")
    worker_env.write_media_file(asset, b"clip")
    fetched, path = worker.fetch_asset(str(asset.id))
    assert fetched.id == asset.id
    assert path.read_bytes() == b"clip"


def test_asset_size_bytes_local_and_remote(worker_env):
    """Asset size is read from disk for local URIs and zero for remote URIs."""
    worker = worker_env.worker
    local = worker_env.add_asset(uri="/media/tmp/a.bin", mime_type="application/octet-stream")
    worker_env.write_media_file(local, b"12345")
    assert worker._asset_size_bytes(local) == 5
    remote = worker_env.add_asset(uri="https://cdn/x.mp4", mime_type="video/mp4")
    assert worker._asset_size_bytes(remote) == 0
    missing = worker_env.add_asset(uri="/media/tmp/none.bin", mime_type="x")
    assert worker._asset_size_bytes(missing) == 0
    empty = MediaAsset(kind="video", uri=None, mime_type="video/mp4")
    assert worker._asset_size_bytes(empty) == 0


def test_get_job_context_and_project_id(worker_env):
    """Job context returns the project/org/owner ids of an existing job."""
    worker = worker_env.worker
    org, owner, project = uuid4(), uuid4(), uuid4()
    job = worker_env.add_job(
        job_type="captions", org_id=org, owner_user_id=owner, project_id=project
    )
    ctx = worker.get_job_context(str(job.id))
    assert ctx["org_id"] == org
    assert worker.get_job_project_id(str(job.id)) == project
    assert worker._job_asset_kwargs(str(job.id))["owner_user_id"] == owner


def test_get_job_context_missing_and_invalid(worker_env):
    """Missing or invalid job ids return empty context dicts."""
    worker = worker_env.worker
    assert worker.get_job_context(str(uuid4()))["org_id"] is None
    assert worker.get_job_context("bad-id")["project_id"] is None


def test_update_job_records_completion_usage(worker_env):
    """Transitioning a job to completed records usage events and a ledger entry."""
    worker = worker_env.worker
    org, owner = uuid4(), uuid4()
    out_asset = worker_env.add_asset(uri="/media/tmp/out.mp4", mime_type="video/mp4")
    worker_env.write_media_file(out_asset, b"0123456789")
    with worker_env.session() as session:
        out = session.get(MediaAsset, out_asset.id)
        out.duration = 120.0
        session.add(out)
        session.add(Subscription(org_id=org, plan_code="pro"))
        session.commit()
    job = worker_env.add_job(
        job_type="shorts", org_id=org, owner_user_id=owner, output_asset_id=out_asset.id
    )
    worker.update_job(
        str(job.id), status=JobStatus.completed, progress=1.0, payload={"k": "v"}
    )
    reloaded = worker_env.get_job(job.id)
    assert reloaded.status == JobStatus.completed
    assert reloaded.payload["k"] == "v"
    with worker_env.session() as session:
        events = session.exec(select(UsageEvent)).all()
        ledger = session.exec(select(UsageLedgerEntry)).all()
    metrics = {e.metric for e in events}
    assert "jobs_completed" in metrics
    assert "job_minutes" in metrics
    assert "storage_bytes" in metrics
    assert any(item.estimated_cost_cents > 0 for item in ledger)


def test_update_job_missing_job_is_noop(worker_env):
    """Updating a non-existent job logs and returns without raising."""
    worker = worker_env.worker
    worker.update_job(str(uuid4()), status=JobStatus.completed)


def test_update_job_sets_output_asset_id(worker_env):
    """``output_asset_id`` is stored when supplied."""
    worker = worker_env.worker
    out = worker_env.add_asset(uri="/media/tmp/o.mp4", mime_type="video/mp4")
    job = worker_env.add_job(job_type="cut")
    worker.update_job(str(job.id), error="boom", output_asset_id=str(out.id))
    reloaded = worker_env.get_job(job.id)
    assert reloaded.output_asset_id == out.id
    assert reloaded.error == "boom"


def test_record_usage_event_without_org_is_noop(worker_env):
    """Usage recording is skipped entirely when there is no org id."""
    worker = worker_env.worker
    with worker_env.session() as session:
        worker._record_usage_event(
            session,
            org_id=None,
            user_id=None,
            job_id=uuid4(),
            metric="jobs_completed",
            quantity=1.0,
        )
        session.commit()
        events = session.exec(select(UsageEvent)).all()
    assert events == []


def test_record_usage_event_uses_subscription_plan(worker_env):
    """A storage_bytes metric records the ``byte`` unit with the org plan."""
    worker = worker_env.worker
    org = uuid4()
    with worker_env.session() as session:
        session.add(Subscription(org_id=org, plan_code="enterprise"))
        session.commit()
        worker._record_usage_event(
            session,
            org_id=org,
            user_id=None,
            job_id=uuid4(),
            metric="storage_bytes",
            quantity=2048.0,
        )
        session.commit()
        ledger = session.exec(select(UsageLedgerEntry)).all()
    assert ledger[0].unit == "byte"
    assert ledger[0].payload["plan_code"] == "enterprise"


def test_clip_asset_ids_parsing():
    """``_clip_asset_ids`` extracts valid UUIDs and skips invalid ones."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    good = uuid4()
    ids = worker._clip_asset_ids(
        {"asset_id": str(good), "thumbnail_asset_id": "bad", "styled_asset_id": None}
    )
    assert ids == {good}
    assert worker._clip_asset_ids("not-a-dict") == set()


def test_job_related_asset_ids():
    """``_job_related_asset_ids`` merges the output asset and clip asset ids."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    out = uuid4()
    clip = uuid4()
    job = Job(
        job_type="shorts",
        output_asset_id=out,
        payload={"clip_assets": [{"asset_id": str(clip)}]},
    )
    assert worker._job_related_asset_ids(job) == {out, clip}
    # Non-dict payload short-circuits to just the output asset id.
    job2 = Job(job_type="shorts", output_asset_id=out, payload={})
    job2.payload = ["not-a-dict"]
    assert worker._job_related_asset_ids(job2) == {out}


def test_asset_referenced_by_jobs(worker_env):
    """An asset referenced as a job input is detected as referenced."""
    worker = worker_env.worker
    asset = worker_env.add_asset(uri="/media/tmp/in.mp4", mime_type="video/mp4")
    worker_env.add_job(job_type="cut", input_asset_id=asset.id)
    with worker_env.session() as session:
        assert worker._asset_referenced_by_jobs(session, asset.id) is True
        assert worker._asset_referenced_by_jobs(session, uuid4()) is False


def test_retention_days_env_override(monkeypatch):
    """An env override changes the retention window; bad values fall back."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("REFRAME_RETENTION_PRO_DAYS", "45")
    assert worker._retention_days_for_plan("pro") == 45
    monkeypatch.setenv("REFRAME_RETENTION_PRO_DAYS", "bad")
    assert worker._retention_days_for_plan("pro") == 30


def test_retention_days_blank_plan(monkeypatch):
    """A blank plan code uses the free-plan retention env key and default."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    monkeypatch.delenv("REFRAME_RETENTION_FREE_DAYS", raising=False)
    assert worker._retention_days_for_plan("") == 14


def test_is_older_than_retention_none_and_naive():
    """``None`` created_at is never expired; naive datetimes assume UTC."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    assert worker._is_older_than_retention(created_at=None, plan_code="free") is False
    now = datetime.now(timezone.utc)
    naive_old = (now - timedelta(days=100)).replace(tzinfo=None)
    assert worker._is_older_than_retention(
        created_at=naive_old, plan_code="free", now=now
    ) is True
