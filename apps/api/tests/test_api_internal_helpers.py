from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import select

from app import api
from app.errors import ApiError
from app.models import Job, OrgBudgetPolicy


def test_queue_and_gpu_helpers(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_GPU_QUEUE", "true")
    monkeypatch.setenv("REFRAME_ASSUME_GPU_FOR_TRANSCRIBE_BACKENDS", "true")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_GPU", "gpuq")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_CPU", "cpuq")
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_DEFAULT", "defq")

    assert api._env_truthy("ENABLE_GPU_QUEUE") is True
    assert api._celery_queue_name("GPU") == "gpuq"
    assert api._celery_queue_name("CPU") == "cpuq"
    assert api._celery_queue_name("DEFAULT") == "defq"

    assert api._task_prefers_gpu("tasks.generate_captions", {"backend": "faster_whisper"}) is True
    assert api._task_prefers_gpu("tasks.transcribe_video", {"device": "cuda"}) is True
    assert api._task_prefers_gpu("tasks.merge_video_audio", {}) is False

    assert api._resolve_task_queue("tasks.generate_captions", {"backend": "faster_whisper"}) == "gpuq"
    assert api._resolve_task_queue("tasks.generate_shorts", {}) == "cpuq"
    assert api._resolve_task_queue("tasks.unknown", {}) == "defq"


def test_scope_and_org_access_helpers():
    org_id = uuid4()
    principal = SimpleNamespace(org_id=org_id)
    query = select(Job)
    scoped = api._scope_query_by_org(query, Job, principal)
    assert "org_id" in str(scoped)

    api._assert_org_access(principal=principal, entity_org_id=org_id, entity="job", entity_id="1")

    with pytest.raises(ApiError):
        api._assert_org_access(principal=principal, entity_org_id=uuid4(), entity="job", entity_id="2")


def test_idempotency_and_redirect_helpers(monkeypatch):
    assert api._resolve_idempotency_key("  abc ", None) == "abc"
    assert api._resolve_idempotency_key(None, "hdr") == "hdr"
    assert api._resolve_idempotency_key("", "") is None

    with pytest.raises(ApiError):
        api._resolve_idempotency_key("x" * 129, None)

    assert api._is_forbidden_ip_host("127.0.0.1") is True
    assert api._is_forbidden_ip_host("8.8.8.8") is False

    assert api._safe_redirect_url("https://example.com/file.txt#frag") == "https://example.com/file.txt"

    with pytest.raises(ApiError):
        api._safe_redirect_url("http://example.com/file.txt")
    with pytest.raises(ApiError):
        api._safe_redirect_url("https://user:pass@example.com/file.txt")
    with pytest.raises(ApiError):
        api._safe_redirect_url("https://localhost/file.txt")
    with pytest.raises(ApiError):
        api._safe_redirect_url("https://127.0.0.1/file.txt")


def test_local_asset_stream_and_path_helpers(tmp_path: Path):
    media_root = tmp_path / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    file_path = media_root / "a.bin"
    file_path.write_bytes(b"hello")

    resolved = api._safe_local_asset_path(media_root=str(media_root), uri="a.bin")
    assert resolved == file_path

    with pytest.raises(ApiError):
        api._safe_local_asset_path(media_root=str(media_root), uri="../escape.bin")

    response = api._stream_local_file(file_path=file_path, mime_type="application/octet-stream")
    assert response.headers["Content-Disposition"].startswith("attachment;")

    async def _collect() -> bytes:
        data = bytearray()
        async for chunk in response.body_iterator:
            data.extend(chunk)
        return bytes(data)

    assert asyncio.run(_collect()) == b"hello"


def test_cost_budget_and_datetime_helpers(monkeypatch):
    assert api._coerce_non_negative_float("12.5") == 12.5
    assert api._coerce_non_negative_float("-1") == 0.0
    assert api._coerce_non_negative_float("2", scale=0.5) == 1.0

    assert api._extract_estimated_minutes({"expected_minutes": 7}) == 7.0
    assert api._extract_estimated_minutes({"duration_seconds": 180}) == 3.0
    assert api._extract_estimated_minutes({}) == 0.0

    assert api._estimate_job_submission_cost_cents(job_type="captions", payload={"duration_seconds": 120}) == 29
    assert api._estimate_job_submission_cost_cents(job_type="unknown", payload={"estimated_cost_cents": 17}) == 17

    assert api._optional_int(None) is None
    assert api._optional_int("8") == 8

    assert api._budget_projected_status(current_month_estimated_cost_cents=15, soft_limit=20, hard_limit=30) == "ok"
    assert api._budget_projected_status(current_month_estimated_cost_cents=25, soft_limit=20, hard_limit=30) == "soft_limit_exceeded"
    assert api._budget_projected_status(current_month_estimated_cost_cents=35, soft_limit=20, hard_limit=30) == "hard_limit_exceeded"

    dt_naive = datetime(2026, 3, 1, 1, 2, 3)
    aware = api._coerce_aware_datetime(dt_naive)
    assert aware is not None and aware.tzinfo is not None

    dt_aware = datetime(2026, 3, 1, 1, 2, 3, tzinfo=timezone.utc)
    assert api._coerce_aware_datetime(dt_aware) == dt_aware

    assert api._coerce_aware_datetime(None) is None

    principal_admin = SimpleNamespace(role="admin")
    principal_owner = SimpleNamespace(role="owner")
    principal_member = SimpleNamespace(role="member")
    api._require_org_manager_role(principal_admin)
    api._require_org_manager_role(principal_owner)
    with pytest.raises(ApiError):
        api._require_org_manager_role(principal_member)

    policy = OrgBudgetPolicy(
        org_id=uuid4(),
        monthly_soft_limit_cents=100,
        monthly_hard_limit_cents=150,
        enforce_hard_limit=True,
    )
    view = api._serialize_budget_policy(
        policy=policy,
        org_id=policy.org_id,
        current_month_estimated_cost_cents=120,
    )
    assert view.projected_status == "soft_limit_exceeded"

    assert api._month_start_utc().day == 1

