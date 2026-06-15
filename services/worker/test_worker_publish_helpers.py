"""Tests for publish-result formatting, id parsing, and step dispatch helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.worker import worker  # pylint: disable=import-error


def _connection(**kwargs):
    return SimpleNamespace(
        account_label=kwargs.get("account_label", "My Creator"),
        external_account_id=kwargs.get("external_account_id", "page-1"),
        org_id=kwargs.get("org_id"),
        user_id=kwargs.get("user_id"),
        id=kwargs.get("id", uuid4()),
        revoked_at=kwargs.get("revoked_at"),
    )


def _asset(asset_id=None):
    return SimpleNamespace(id=asset_id or uuid4(), mime_type="video/mp4")


@pytest.mark.parametrize(
    "provider,host",
    [
        ("youtube", "youtube.com/watch"),
        ("tiktok", "tiktok.com/@mycreator"),
        ("instagram", "instagram.com/p/"),
        ("facebook", "facebook.com/page-1"),
    ],
)
def test_publish_result_for_provider_urls(provider, host):
    """Each provider produces a published_url on its own domain."""
    result = worker._publish_result_for_provider(
        provider=provider,
        connection=_connection(),
        asset=_asset(),
        payload={"title": "Hello"},
    )
    assert host in result["published_url"]
    assert result["status"] == "published"
    assert result["title"] == "Hello"


def test_publish_result_for_provider_default_titles():
    """Missing title falls back to a per-provider default label."""
    yt = worker._publish_result_for_provider(
        provider="youtube", connection=_connection(), asset=_asset(), payload={}
    )
    assert yt["title"] == "Untitled upload"
    # caption is used when title is absent.
    tk = worker._publish_result_for_provider(
        provider="tiktok",
        connection=_connection(),
        asset=_asset(),
        payload={"caption": "Cap"},
    )
    assert tk["title"] == "Cap"


def test_publish_result_for_provider_rejects_unknown():
    """An unsupported provider raises ValueError."""
    with pytest.raises(ValueError):
        worker._publish_result_for_provider(
            provider="myspace", connection=_connection(), asset=_asset(), payload={}
        )


def test_parse_publish_ids_missing_fields():
    """Missing required fields yields a validation error result."""
    conn, asset, error = worker._parse_publish_ids(
        provider=None, connection_id="x", asset_id="y"
    )
    assert conn is None and asset is None
    assert error["status"] == "failed"


def test_parse_publish_ids_invalid_uuid():
    """Non-UUID connection/asset ids return a UUID validation error."""
    conn, asset, error = worker._parse_publish_ids(
        provider="youtube", connection_id="not-uuid", asset_id="also-bad"
    )
    assert conn is None and asset is None
    assert "valid UUIDs" in error["error"]


def test_parse_publish_ids_valid():
    """Valid ids parse into UUIDs with no error."""
    cid, aid = uuid4(), uuid4()
    conn, asset, error = worker._parse_publish_ids(
        provider="youtube", connection_id=str(cid), asset_id=str(aid)
    )
    assert conn == cid and asset == aid and error is None


def test_publish_run_event_builds_event():
    """``_publish_run_event`` returns an AutomationRunEvent with derived fields."""
    job = SimpleNamespace(org_id=uuid4(), id=uuid4(), provider="youtube")
    event = worker._publish_run_event(
        job=job,
        workflow_uuid=None,
        status="completed",
        message="ok",
        payload={"a": 1},
    )
    assert event.step_name == "publish.job.youtube"
    assert event.status == "completed"
    assert event.message == "ok"
    assert isinstance(event.created_at, datetime)


def _job(**kwargs):
    return SimpleNamespace(id=kwargs.get("id", uuid4()))


def _run(**kwargs):
    return SimpleNamespace(
        id=kwargs.get("id", uuid4()),
        input_asset_id=kwargs.get("input_asset_id"),
    )


def test_dispatch_style_subtitles_step(monkeypatch):
    """Style-subtitles dispatch sends the render task with resolved ids."""
    sent: dict = {}

    def fake_send_task(name, args, queue=None):
        sent.update({"name": name, "args": args, "queue": queue})
        return SimpleNamespace(id="task-1")

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)
    input_asset = uuid4()
    task_id = worker._dispatch_style_subtitles_step(
        job=_job(),
        run=_run(input_asset_id=uuid4()),
        input_asset_id=input_asset,
        step_payload={"style": {"font": "X"}, "preview_seconds": 3},
    )
    assert task_id == "task-1"
    assert sent["name"] == "tasks.render_styled_subtitles"
    assert sent["args"][2] == str(input_asset)


def test_dispatch_publish_step_requires_connection(monkeypatch):
    """Publish dispatch fails without a connection id."""
    monkeypatch.setattr(
        worker.celery_app, "send_task", lambda *a, **k: SimpleNamespace(id="t")
    )
    with pytest.raises(ValueError, match="connection_id"):
        worker._dispatch_publish_step(
            job=_job(),
            run=_run(),
            step_type="publish_youtube",
            input_asset_id=uuid4(),
            step_payload={},
        )


def test_dispatch_publish_step_requires_asset(monkeypatch):
    """Publish dispatch fails without an asset id or workflow input asset."""
    monkeypatch.setattr(
        worker.celery_app, "send_task", lambda *a, **k: SimpleNamespace(id="t")
    )
    with pytest.raises(ValueError, match="asset_id"):
        worker._dispatch_publish_step(
            job=_job(),
            run=_run(),
            step_type="publish_youtube",
            input_asset_id=None,
            step_payload={"connection_id": str(uuid4())},
        )


def test_dispatch_publish_step_sends_task(monkeypatch):
    """A complete publish step dispatches the publish task."""
    sent: dict = {}

    def fake_send_task(name, args, queue=None):  # pylint: disable=unused-argument
        sent.update({"name": name, "args": args})
        return SimpleNamespace(id="pub-task")

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)
    cid = str(uuid4())
    task_id = worker._dispatch_publish_step(
        job=_job(),
        run=_run(),
        step_type="publish_youtube",
        input_asset_id=uuid4(),
        step_payload={"connection_id": cid},
    )
    assert task_id == "pub-task"
    assert sent["name"] == "tasks.publish_asset"
    assert sent["args"][2] == cid


@pytest.mark.parametrize(
    "step_type,expected_task",
    [
        ("captions", "tasks.generate_captions"),
        ("translate_subtitles", "tasks.translate_subtitles"),
        ("shorts", "tasks.generate_shorts"),
    ],
)
def test_dispatch_pipeline_step_routes(monkeypatch, step_type, expected_task):
    """Pipeline step dispatch routes each step type to the right task."""
    sent: dict = {}

    def fake_send_task(name, args, queue=None):  # pylint: disable=unused-argument
        sent["name"] = name
        return SimpleNamespace(id="t")

    monkeypatch.setattr(worker.celery_app, "send_task", fake_send_task)
    worker._dispatch_pipeline_step(
        job=_job(),
        run=_run(),
        step_type=step_type,
        input_asset_id=uuid4(),
        step_payload={},
    )
    assert sent["name"] == expected_task


def test_dispatch_pipeline_step_missing_input_asset():
    """Steps requiring an input asset fail fast when it is absent."""
    with pytest.raises(ValueError, match="missing input asset"):
        worker._dispatch_pipeline_step(
            job=_job(),
            run=_run(),
            step_type="captions",
            input_asset_id=None,
            step_payload={},
        )


def test_dispatch_pipeline_step_style_and_publish(monkeypatch):
    """Style and publish step types delegate to their helpers."""
    monkeypatch.setattr(
        worker.celery_app, "send_task", lambda *a, **k: SimpleNamespace(id="t")
    )
    style_id = worker._dispatch_pipeline_step(
        job=_job(),
        run=_run(input_asset_id=uuid4()),
        step_type="style_subtitles",
        input_asset_id=uuid4(),
        step_payload={},
    )
    assert style_id == "t"
    pub_id = worker._dispatch_pipeline_step(
        job=_job(),
        run=_run(),
        step_type="publish_tiktok",
        input_asset_id=uuid4(),
        step_payload={"connection_id": str(uuid4())},
    )
    assert pub_id == "t"


def test_dispatch_pipeline_step_unknown_type():
    """An unknown step type raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported workflow step"):
        worker._dispatch_pipeline_step(
            job=_job(),
            run=_run(),
            step_type="unknown_step",
            input_asset_id=uuid4(),
            step_payload={},
        )
