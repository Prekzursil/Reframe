from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session

from app.models import (
    Job,
    JobStatus,
    MediaAsset,
    Organization,
    PublishConnection,
    PublishJob,
    User,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowTemplate,
)
from media_core.segment.shorts import SegmentCandidate
from services.worker import worker


class _TaskSelf:
    def __init__(self, request_id: str | None = "task-1"):
        self.request = SimpleNamespace(id=request_id)
        self.states: list[dict] = []

    def update_state(self, **kwargs):
        self.states.append(kwargs)


@pytest.fixture()
def worker_db(monkeypatch, tmp_path: Path):
    from app.config import get_settings
    from app.database import create_db_and_tables, get_engine

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "worker-test.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("REFRAME_MEDIA_ROOT", str(media_root))

    get_settings.cache_clear()
    get_engine.cache_clear()
    worker._engine = None
    worker._media_tmp = None
    create_db_and_tables()

    return get_engine


def test_run_workflow_pipeline_invalid_missing_cancelled(worker_db):
    assert worker.run_workflow_pipeline.run("not-a-uuid")["status"] == "invalid_run_id"

    missing = worker.run_workflow_pipeline.run(str(uuid4()))
    assert missing["status"] == "missing"

    get_engine = worker_db
    with Session(get_engine()) as session:
        user = User(email="wf-owner@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)

        org = Organization(name="WF Org", slug="wf-org")
        session.add(org)
        session.commit()
        session.refresh(org)

        template = WorkflowTemplate(
            name="wf",
            steps=[{"type": "captions", "payload": {}}],
            org_id=org.id,
            owner_user_id=user.id,
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        run = WorkflowRun(
            template_id=template.id,
            org_id=org.id,
            owner_user_id=user.id,
            input_asset_id=None,
            status=WorkflowRunStatus.cancelled,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        cancelled = worker.run_workflow_pipeline.run(str(run.id))
        assert cancelled["status"] == "cancelled"


def test_run_workflow_pipeline_template_missing_and_dispatch_failure(worker_db, monkeypatch):
    get_engine = worker_db
    with Session(get_engine()) as session:
        user = User(email="wf2-owner@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)

        org = Organization(name="WF2 Org", slug="wf2-org")
        session.add(org)
        session.commit()
        session.refresh(org)

        missing_template_run = WorkflowRun(
            template_id=uuid4(),
            org_id=org.id,
            owner_user_id=user.id,
            input_asset_id=None,
        )
        session.add(missing_template_run)
        session.commit()
        session.refresh(missing_template_run)

        failed = worker.run_workflow_pipeline.run(str(missing_template_run.id))
        assert failed["status"] == "failed"
        assert failed["error"] == "template_missing"

        template = WorkflowTemplate(
            name="wf-dispatch",
            steps=[{"type": "captions", "payload": {}}],
            org_id=org.id,
            owner_user_id=user.id,
        )
        session.add(template)
        session.commit()
        session.refresh(template)

        run = WorkflowRun(
            template_id=template.id,
            org_id=org.id,
            owner_user_id=user.id,
            input_asset_id=None,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        step = WorkflowRunStep(run_id=run.id, order_index=0, step_type="captions", payload={})
        session.add(step)
        session.commit()
        run_id = str(run.id)

    monkeypatch.setattr(worker, "_dispatch_pipeline_step", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("dispatch boom")))

    dispatched = worker.run_workflow_pipeline.run(run_id)
    assert dispatched["status"] == "failed"
    assert "dispatch boom" in dispatched["error"]


def test_publish_asset_invalid_inputs_and_missing_records(worker_db):
    assert worker.publish_asset.run(None, None, None, None, None, {})["status"] == "failed"

    invalid = worker.publish_asset.run(None, "youtube", "not-uuid", "bad", None, {})
    assert invalid["error"] == "connection_id and asset_id must be valid UUIDs"

    missing_connection = worker.publish_asset.run(None, "youtube", str(uuid4()), str(uuid4()), None, {})
    assert missing_connection["error"] == "publish_connection_missing"


def test_publish_asset_connection_revoked_and_asset_missing(worker_db):
    get_engine = worker_db
    with Session(get_engine()) as session:
        user = User(email="publish-owner@test.dev")
        session.add(user)
        session.commit()
        session.refresh(user)

        org = Organization(name="Publish Org", slug="publish-org")
        session.add(org)
        session.commit()
        session.refresh(org)

        connection = PublishConnection(
            org_id=org.id,
            user_id=user.id,
            provider="youtube",
            account_label="acct",
            external_account_id="acct-1",
            revoked_at=datetime.now(timezone.utc),
        )
        session.add(connection)
        session.commit()
        session.refresh(connection)

        asset = MediaAsset(kind="video", uri="/media/tmp/a.mp4", mime_type="video/mp4", org_id=org.id, owner_user_id=user.id)
        session.add(asset)
        session.commit()
        session.refresh(asset)

        revoked_result = worker.publish_asset.run(None, "youtube", str(connection.id), str(asset.id), None, {})
        assert revoked_result["status"] == "failed"
        assert revoked_result["error"] == "publish_connection_invalid"

        job = PublishJob(
            org_id=org.id,
            user_id=user.id,
            provider="youtube",
            connection_id=connection.id,
            asset_id=uuid4(),
            status="queued",
            payload={},
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        missing_asset = worker.publish_asset.run(str(job.id), None, None, None, None, {})
        assert missing_asset["status"] == "failed"
        assert missing_asset["error"] == "publish_connection_invalid"


def test_render_styled_subtitles_failure_and_success_paths(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    sub = tmp_path / "sub.srt"
    output = tmp_path / "styled.mp4"
    video.write_bytes(b"video")
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    output.write_bytes(b"styled")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})

    # Missing video
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (None, None))
    missing_video = worker.render_styled_subtitles.run(str(uuid4()), str(uuid4()), str(uuid4()), {}, {})
    assert missing_video["status"] == "failed"

    # Missing subtitle
    calls = {"count": 0}

    def _fetch(asset_id: str):
        calls["count"] += 1
        return (SimpleNamespace(id=UUID(asset_id), mime_type="video/mp4"), video if calls["count"] == 1 else None)

    monkeypatch.setattr(worker, "fetch_asset", _fetch)
    missing_sub = worker.render_styled_subtitles.run(str(uuid4()), str(uuid4()), str(uuid4()), {}, {})
    assert missing_sub["status"] == "failed"

    # ffmpeg failure
    vid_id = str(uuid4())
    sub_id = str(uuid4())

    def _fetch_by_id(asset_id: str):
        return (SimpleNamespace(id=UUID(asset_id), mime_type="video/mp4" if asset_id == vid_id else "text/plain"), video if asset_id == vid_id else sub)

    monkeypatch.setattr(worker, "fetch_asset", _fetch_by_id)
    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("render boom")))
    failed_render = worker.render_styled_subtitles.run(str(uuid4()), vid_id, sub_id, {}, {})
    assert failed_render["status"] == "failed"

    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", lambda **_kwargs: output)
    monkeypatch.setattr(worker, "create_asset_for_existing_file", lambda **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/styled.mp4"))
    success = worker.render_styled_subtitles.run(str(uuid4()), vid_id, sub_id, {}, {"preview_seconds": "7"})
    assert success["status"] == "styled_render"


def test_generate_shorts_failure_and_success_paths(monkeypatch, tmp_path: Path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})

    # Missing source path
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (None, None))
    missing = worker.generate_shorts.run(str(uuid4()), str(uuid4()), {})
    assert missing["status"] == "failed"

    # Probe failure
    monkeypatch.setattr(worker, "fetch_asset", lambda asset_id: (SimpleNamespace(id=UUID(asset_id), mime_type="video/mp4", uri="/media/tmp/video.mp4"), video))
    monkeypatch.setattr(worker, "probe_media", lambda _path: (_ for _ in ()).throw(RuntimeError("probe boom")))
    probe_failed = worker.generate_shorts.run(str(uuid4()), str(uuid4()), {})
    assert probe_failed["status"] == "failed"

    # Success path with mocked media operations
    monkeypatch.setattr(worker, "probe_media", lambda _path: {"duration": 20.0})
    monkeypatch.setattr(
        worker,
        "equal_splits",
        lambda _duration, clip_length=60.0: [
            SegmentCandidate(start=0.0, end=8.0, score=0.9, reason="a", snippet="a"),
            SegmentCandidate(start=8.0, end=16.0, score=0.8, reason="b", snippet="b"),
        ],
    )
    monkeypatch.setattr(worker, "score_segments_heuristic", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "select_top", lambda candidates, **_kwargs: candidates)
    monkeypatch.setattr(worker, "_run_ffmpeg_with_retries", lambda **_kwargs: None)
    monkeypatch.setattr(worker, "new_tmp_file", lambda suffix: tmp_path / f"out{suffix}")
    monkeypatch.setattr(worker, "cut_clip", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "create_asset_for_existing_file", lambda **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/clip.mp4"))
    monkeypatch.setattr(worker, "create_thumbnail_asset", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/thumb.jpg"))
    monkeypatch.setattr(worker, "create_asset", lambda **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/manifest.json"))

    done = worker.generate_shorts.run(str(uuid4()), str(uuid4()), {"max_clips": 2})
    assert done["status"] == "shorts_generated"
    assert len(done["clip_assets"]) == 2


def test_cut_merge_and_cleanup_paths(monkeypatch, tmp_path: Path, worker_db):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})

    # cut clip: missing source then success
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (None, None))
    cut_missing = worker.cut_clip_asset.run(str(uuid4()), str(uuid4()), 5, 1, {})
    assert cut_missing["status"] == "failed"

    monkeypatch.setattr(worker, "fetch_asset", lambda asset_id: (SimpleNamespace(id=UUID(asset_id), mime_type="video/mp4", uri="/media/tmp/video.mp4"), video))
    monkeypatch.setattr(worker, "_run_ffmpeg_with_retries", lambda **_kwargs: None)
    monkeypatch.setattr(worker, "new_tmp_file", lambda suffix: tmp_path / f"cut{suffix}")
    monkeypatch.setattr(worker, "cut_clip", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "create_asset_for_existing_file", lambda **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/cut.mp4"))
    monkeypatch.setattr(worker, "create_thumbnail_asset", lambda *_args, **_kwargs: SimpleNamespace(id=uuid4(), uri="/media/tmp/cut-thumb.jpg"))
    cut_done = worker.cut_clip_asset.run(str(uuid4()), str(uuid4()), 8, 2, {})
    assert cut_done["duration"] == 6.0

    # merge: missing audio then success
    video_id = str(uuid4())
    audio_id = str(uuid4())

    def _fetch_merge(asset_id: str):
        if asset_id == video_id:
            return (SimpleNamespace(id=UUID(asset_id), mime_type="video/mp4", uri="/media/tmp/video.mp4"), video)
        return (SimpleNamespace(id=UUID(asset_id), mime_type="audio/wav", uri="/media/tmp/audio.wav"), audio)

    monkeypatch.setattr(worker, "fetch_asset", _fetch_merge)
    monkeypatch.setattr(worker, "ffmpeg_merge_video_audio", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "new_tmp_file", lambda suffix: tmp_path / f"merge{suffix}")
    merge_done = worker.merge_video_audio.run(str(uuid4()), video_id, audio_id, {"offset": 1.5})
    assert merge_done["status"] == "merged"

    # cleanup retention early path
    get_engine = worker_db
    with Session(get_engine()) as session:
        org = Organization(name="cleanup-org", slug="cleanup-org")
        user = User(email="cleanup@test.dev")
        session.add(org)
        session.add(user)
        session.commit()
        session.refresh(org)
        session.refresh(user)
        job = Job(job_type="captions", status=JobStatus.running, org_id=org.id, owner_user_id=user.id)
        session.add(job)
        session.commit()

    result = worker.cleanup_retention.run()
    assert result["status"] == "ok"
