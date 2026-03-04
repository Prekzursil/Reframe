from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import Job, MediaAsset, PublishConnection
from services.worker import worker


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_truthy_and_bool_coercion_helpers(monkeypatch):
    monkeypatch.setenv("SAMPLE_FLAG", "true")
    _expect(worker._env_truthy("SAMPLE_FLAG"), "Expected env truthy for true")

    monkeypatch.delenv("SAMPLE_FLAG", raising=False)
    monkeypatch.setenv("REFRAME_SAMPLE_FLAG", "1")
    _expect(worker._env_truthy("SAMPLE_FLAG"), "Expected REFRAME_ fallback env lookup")

    _expect(worker._coerce_bool(True), "Expected bool true coercion")
    _expect(worker._coerce_bool(1), "Expected numeric true coercion")
    _expect(not worker._coerce_bool("no"), "Expected string false coercion")
    _expect(worker._coerce_bool_with_default(None, True), "Expected default bool fallback")


def test_retry_parsers_and_retention_helpers(monkeypatch):
    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "bad")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "bad")
    _expect(worker._retry_max_attempts() == 2, "Expected retry attempts default for invalid value")
    _expect(worker._retry_base_delay_seconds() == 1.0, "Expected retry base delay default for invalid value")

    monkeypatch.setenv("REFRAME_RETENTION_ENTERPRISE_DAYS", "120")
    _expect(worker._retention_days_for_plan("enterprise") == 120, "Expected env override for retention days")
    monkeypatch.setenv("REFRAME_RETENTION_ENTERPRISE_DAYS", "oops")
    _expect(worker._retention_days_for_plan("enterprise") == 90, "Expected fallback retention for invalid override")

    now = datetime(2026, 3, 4, tzinfo=timezone.utc)
    old = now - timedelta(days=200)
    fresh = now - timedelta(days=1)
    _expect(worker._is_older_than_retention(created_at=old, plan_code="free", now=now), "Expected old asset retention match")
    _expect(not worker._is_older_than_retention(created_at=fresh, plan_code="free", now=now), "Expected fresh asset retention mismatch")


def test_color_http_and_publish_helpers():
    _expect(worker._hex_to_ass_color("#abc", default="x") == "&H00CCBBAA", "Expected 3-char hex conversion")
    _expect(worker._hex_to_ass_color("zzzzzz", default="x") == "x", "Expected invalid hex default fallback")
    _expect(worker._is_http_uri("https://example.com"), "Expected https URI detection")
    _expect(not worker._is_http_uri("file:///tmp/x"), "Expected non-http URI rejection")

    connection = PublishConnection(provider="youtube", external_account_id="acct-1", account_label="Creator Name")
    asset = MediaAsset(id=uuid4(), kind="video", uri="/media/x.mp4", mime_type="video/mp4")

    for provider in ("youtube", "tiktok", "instagram", "facebook"):
        result = worker._publish_result_for_provider(
            provider=provider,
            connection=connection,
            asset=asset,
            payload={"title": "Demo"},
        )
        _expect(result["status"] == "published", f"Expected published status for {provider}")
        _expect(bool(result["published_url"]), f"Expected published URL for {provider}")

    with pytest.raises(ValueError):
        worker._publish_result_for_provider(provider="x", connection=connection, asset=asset, payload={})


def test_job_related_asset_and_size_helpers(monkeypatch, tmp_path: Path):
    output_id = uuid4()
    clip_id = uuid4()
    thumb_id = uuid4()
    subtitle_id = uuid4()
    styled_id = uuid4()

    job = Job(
        id=uuid4(),
        job_type="shorts",
        status="completed",
        output_asset_id=output_id,
        payload={
            "clip_assets": [
                {
                    "asset_id": str(clip_id),
                    "thumbnail_asset_id": str(thumb_id),
                    "subtitle_asset_id": str(subtitle_id),
                    "styled_asset_id": str(styled_id),
                    "garbage": "x",
                },
                "not-a-dict",
            ]
        },
    )
    ids = worker._job_related_asset_ids(job)
    _expect(output_id in ids and clip_id in ids and thumb_id in ids and subtitle_id in ids and styled_id in ids, "Expected related asset id extraction")

    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    file_rel = Path("tmp") / "out.bin"
    full = media_root / file_rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"abcdef")

    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(media_root=str(media_root)))
    local_asset = MediaAsset(id=uuid4(), kind="binary", uri=f"/media/{file_rel.as_posix()}", mime_type="application/octet-stream")
    _expect(worker._asset_size_bytes(local_asset) == 6, "Expected local asset size bytes")

    remote_asset = MediaAsset(id=uuid4(), kind="binary", uri="https://cdn.example.com/a.bin", mime_type="application/octet-stream")
    _expect(worker._asset_size_bytes(remote_asset) == 0, "Expected remote URI size fallback")


def test_dispatch_pipeline_step_branches(monkeypatch):
    calls: list[dict] = []

    def fake_dispatch(task_name: str, args, queue: str):
        calls.append({"task_name": task_name, "args": args, "queue": queue})
        return SimpleNamespace(id=f"id-{task_name}")

    monkeypatch.setattr(worker, "_dispatch_task", fake_dispatch)

    run = SimpleNamespace(id=uuid4(), input_asset_id=uuid4())
    job = SimpleNamespace(id=uuid4())

    captions_id = worker._dispatch_pipeline_step(
        job=job,
        run=run,
        step_type="captions",
        input_asset_id=uuid4(),
        step_payload={"backend": "noop"},
    )
    _expect(captions_id.startswith("id-"), "Expected captions dispatch id")

    publish_id = worker._dispatch_pipeline_step(
        job=job,
        run=run,
        step_type="publish_youtube",
        input_asset_id=uuid4(),
        step_payload={"connection_id": str(uuid4()), "asset_id": str(uuid4())},
    )
    _expect(publish_id.startswith("id-"), "Expected publish dispatch id")

    _expect(any(call["task_name"] == "tasks.generate_captions" for call in calls), "Expected captions task dispatch")
    _expect(any(call["task_name"] == "tasks.publish_asset" for call in calls), "Expected publish task dispatch")

    with pytest.raises(ValueError):
        worker._dispatch_pipeline_step(
            job=job,
            run=run,
            step_type="captions",
            input_asset_id=None,
            step_payload={},
        )

    with pytest.raises(ValueError):
        worker._dispatch_pipeline_step(
            job=job,
            run=run,
            step_type="publish",
            input_asset_id=uuid4(),
            step_payload={"provider": "youtube"},
        )


def test_download_remote_uri_to_tmp_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(worker, "new_tmp_file", lambda _suffix: tmp_path / "download.bin")

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: True)
    with pytest.raises(RuntimeError):
        worker._download_remote_uri_to_tmp(uri="https://example.com/file.bin")

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: False)
    with pytest.raises(ValueError):
        worker._download_remote_uri_to_tmp(uri="file:///tmp/file.bin")