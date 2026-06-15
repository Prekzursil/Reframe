"""Unit tests for pure/DB helper functions in :mod:`app.api`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import Session

from app import api as api_module
from app.config import get_settings
from app.database import get_engine
from app.errors import ApiError
from app.security import AuthPrincipal


# ---------------------------------------------------------------------------
# env / queue helpers
# ---------------------------------------------------------------------------


def test_env_truthy(monkeypatch):
    monkeypatch.delenv("MY_FLAG", raising=False)
    monkeypatch.delenv("REFRAME_MY_FLAG", raising=False)
    assert api_module._env_truthy("MY_FLAG") is False
    monkeypatch.setenv("MY_FLAG", "ON")
    assert api_module._env_truthy("MY_FLAG") is True
    monkeypatch.delenv("MY_FLAG", raising=False)
    monkeypatch.setenv("REFRAME_MY_FLAG", "yes")
    assert api_module._env_truthy("MY_FLAG") is True


def test_celery_queue_name(monkeypatch):
    for key in ("REFRAME_CELERY_QUEUE_GPU", "REFRAME_CELERY_QUEUE_CPU", "REFRAME_CELERY_QUEUE_DEFAULT"):
        monkeypatch.delenv(key, raising=False)
    assert api_module._celery_queue_name("gpu") == "gpu"
    assert api_module._celery_queue_name("cpu") == "cpu"
    assert api_module._celery_queue_name("anything") == "default"
    monkeypatch.setenv("REFRAME_CELERY_QUEUE_GPU", "custom-gpu")
    assert api_module._celery_queue_name("GPU") == "custom-gpu"


def test_task_prefers_gpu(monkeypatch):
    monkeypatch.delenv("REFRAME_ASSUME_GPU_FOR_TRANSCRIBE_BACKENDS", raising=False)
    # Non-transcribe task never prefers GPU.
    assert api_module._task_prefers_gpu("tasks.cut_clip") is False
    # Explicit device cuda -> True.
    assert (
        api_module._task_prefers_gpu(api_module.TASK_GENERATE_CAPTIONS, {"device": "cuda"}) is True
    )
    # No device, assume-flag off -> False.
    assert (
        api_module._task_prefers_gpu(
            api_module.TASK_TRANSCRIBE_VIDEO, {"backend": "faster_whisper"}
        )
        is False
    )
    # assume-flag on + known backend -> True.
    monkeypatch.setenv("REFRAME_ASSUME_GPU_FOR_TRANSCRIBE_BACKENDS", "1")
    assert (
        api_module._task_prefers_gpu(
            api_module.TASK_TRANSCRIBE_VIDEO, {"backend": "whisper_cpp"}
        )
        is True
    )
    # assume-flag on but unknown backend -> False.
    assert (
        api_module._task_prefers_gpu(api_module.TASK_TRANSCRIBE_VIDEO, {"backend": "tiny"}) is False
    )


def test_resolve_task_queue(monkeypatch):
    for key in ("REFRAME_CELERY_QUEUE_GPU", "REFRAME_CELERY_QUEUE_CPU", "REFRAME_CELERY_QUEUE_DEFAULT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("REFRAME_ENABLE_GPU_QUEUE", raising=False)
    # transcribe with GPU disabled -> CPU.
    assert api_module._resolve_task_queue(api_module.TASK_GENERATE_CAPTIONS) == "cpu"
    # GPU enabled + prefers GPU -> GPU.
    monkeypatch.setenv("REFRAME_ENABLE_GPU_QUEUE", "1")
    assert (
        api_module._resolve_task_queue(api_module.TASK_GENERATE_CAPTIONS, {"device": "gpu"})
        == "gpu"
    )
    # CPU-class task -> CPU.
    assert api_module._resolve_task_queue(api_module.TASK_CUT_CLIP) == "cpu"
    # Unknown task -> default.
    assert api_module._resolve_task_queue("tasks.unknown") == "default"


# ---------------------------------------------------------------------------
# org access helpers
# ---------------------------------------------------------------------------


def test_assert_org_access_allows_when_no_principal_org():
    principal = AuthPrincipal(org_id=None)
    # No org on principal -> no enforcement.
    api_module._assert_org_access(
        principal=principal, entity_org_id=uuid4(), entity="project", entity_id="x"
    )


def test_assert_org_access_allows_matching_org():
    org = uuid4()
    principal = AuthPrincipal(org_id=org)
    api_module._assert_org_access(
        principal=principal, entity_org_id=org, entity="project", entity_id="x"
    )


def test_assert_org_access_denies_mismatched_org():
    principal = AuthPrincipal(org_id=uuid4())
    with pytest.raises(ApiError) as exc:
        api_module._assert_org_access(
            principal=principal, entity_org_id=uuid4(), entity="project", entity_id="x"
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# idempotency key
# ---------------------------------------------------------------------------


def test_resolve_idempotency_key():
    assert api_module._resolve_idempotency_key(None, None) is None
    assert api_module._resolve_idempotency_key("  ", "") is None
    assert api_module._resolve_idempotency_key("abc", None) == "abc"
    assert api_module._resolve_idempotency_key(None, "from-header") == "from-header"


def test_resolve_idempotency_key_too_long():
    with pytest.raises(ApiError) as exc:
        api_module._resolve_idempotency_key("x" * 129, None)
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# safe redirect / download URL validation
# ---------------------------------------------------------------------------


def test_is_forbidden_ip_host():
    assert api_module._is_forbidden_ip_host("127.0.0.1") is True
    assert api_module._is_forbidden_ip_host("10.0.0.1") is True
    assert api_module._is_forbidden_ip_host("169.254.0.1") is True
    assert api_module._is_forbidden_ip_host("8.8.8.8") is False
    # Not an IP at all -> False.
    assert api_module._is_forbidden_ip_host("example.com") is False


def test_safe_redirect_url_accepts_https():
    out = api_module._safe_redirect_url("https://example.com/file#frag")
    assert out == "https://example.com/file"


def test_safe_redirect_url_rejects_non_https():
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("http://example.com/x")
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("not a url")


def test_safe_redirect_url_rejects_credentials():
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("https://user:pass@example.com/x")


def test_safe_redirect_url_rejects_localhost():
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("https://localhost/x")


def test_safe_redirect_url_rejects_private_ip():
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("https://10.0.0.5/x")


def test_safe_redirect_url_missing_hostname():
    # A URL with scheme https but blank netloc fails the scheme/netloc check first.
    with pytest.raises(ApiError):
        api_module._safe_redirect_url("https://")


# ---------------------------------------------------------------------------
# local asset path safety
# ---------------------------------------------------------------------------


def test_safe_local_asset_path_ok(tmp_path: Path):
    out = api_module._safe_local_asset_path(media_root=str(tmp_path), uri="/media/sub/file.mp4")
    assert out == (tmp_path / "sub" / "file.mp4").resolve()


def test_safe_local_asset_path_escape(tmp_path: Path):
    # An escaping uri is rejected by LocalStorageBackend.resolve_local_path with ValueError
    # before _safe_local_asset_path's own relative_to guard runs.
    with pytest.raises(ValueError, match="escapes media root"):
        api_module._safe_local_asset_path(media_root=str(tmp_path), uri="/media/../../etc/passwd")


# ---------------------------------------------------------------------------
# stream local file
# ---------------------------------------------------------------------------


def test_stream_local_file_missing(tmp_path: Path):
    from app.errors import ApiError as _ApiError

    with pytest.raises(_ApiError) as exc:
        api_module._stream_local_file(file_path=tmp_path / "nope.bin", mime_type=None)
    assert exc.value.status_code == 404


def test_stream_local_file_streams_content(tmp_path: Path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"abc" * 100)
    resp = api_module._stream_local_file(file_path=target, mime_type="video/mp4")
    assert resp.media_type == "video/mp4"
    assert "attachment" in resp.headers["content-disposition"]
    # body_iterator may be sync or async depending on Starlette; consume both forms.
    iterator = resp.body_iterator
    if hasattr(iterator, "__anext__"):
        import asyncio

        async def _collect():
            chunks = []
            async for chunk in iterator:
                chunks.append(chunk)
            return chunks

        collected = asyncio.run(_collect())
    else:
        collected = list(iterator)
    body = b"".join(
        c if isinstance(c, bytes) else c.encode() for c in collected
    )
    assert body == b"abc" * 100


# ---------------------------------------------------------------------------
# cost / estimate helpers
# ---------------------------------------------------------------------------


def test_coerce_non_negative_float():
    assert api_module._coerce_non_negative_float("3.5") == 3.5
    assert api_module._coerce_non_negative_float(None) == 0.0
    assert api_module._coerce_non_negative_float("bad") == 0.0
    assert api_module._coerce_non_negative_float(-5) == 0.0
    assert api_module._coerce_non_negative_float(120, scale=1.0 / 60.0) == 2.0


def test_extract_estimated_minutes():
    assert api_module._extract_estimated_minutes({"expected_minutes": 4}) == 4.0
    assert api_module._extract_estimated_minutes({"duration_seconds": 120}) == 2.0
    assert api_module._extract_estimated_minutes({}) == 0.0


def test_estimate_job_submission_cost_cents():
    # explicit override wins.
    assert (
        api_module._estimate_job_submission_cost_cents(
            job_type="captions", payload={"estimated_cost_cents": 99}
        )
        == 99
    )
    # base cost + minutes*2.
    assert (
        api_module._estimate_job_submission_cost_cents(
            job_type="captions", payload={"expected_minutes": 3}
        )
        == 25 + 6
    )
    # unknown job type -> base 10.
    assert (
        api_module._estimate_job_submission_cost_cents(job_type="weird", payload=None) == 10
    )


def test_optional_int():
    assert api_module._optional_int(None) is None
    assert api_module._optional_int("5") == 5


def test_budget_projected_status():
    f = api_module._budget_projected_status
    assert f(current_month_estimated_cost_cents=50, soft_limit=None, hard_limit=None) == "ok"
    assert (
        f(current_month_estimated_cost_cents=200, soft_limit=100, hard_limit=300)
        == "soft_limit_exceeded"
    )
    assert (
        f(current_month_estimated_cost_cents=400, soft_limit=100, hard_limit=300)
        == "hard_limit_exceeded"
    )
    # zero hard limit is treated as unlimited.
    assert f(current_month_estimated_cost_cents=400, soft_limit=None, hard_limit=0) == "ok"


def test_require_org_manager_role():
    api_module._require_org_manager_role(AuthPrincipal(role="owner"))
    api_module._require_org_manager_role(AuthPrincipal(role="admin"))
    with pytest.raises(ApiError) as exc:
        api_module._require_org_manager_role(AuthPrincipal(role="member"))
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# subscription / quota enforcement (pure parts)
# ---------------------------------------------------------------------------


def test_enforce_subscription_active_for_plan():
    from app.models import Subscription

    # No sub or free plan -> no-op.
    api_module._enforce_subscription_active_for_plan(None, plan_code="pro")
    sub = Subscription(org_id=uuid4(), plan_code="pro", status="active")
    api_module._enforce_subscription_active_for_plan(sub, plan_code="free")
    api_module._enforce_subscription_active_for_plan(sub, plan_code="pro")
    sub.status = "past_due"
    with pytest.raises(ApiError) as exc:
        api_module._enforce_subscription_active_for_plan(sub, plan_code="pro")
    assert exc.value.status_code == 429


def test_enforce_monthly_minutes_limit():
    # unlimited.
    api_module._enforce_monthly_minutes_limit(plan_code="free", monthly_limit=0, used_minutes=1000)
    # under limit.
    api_module._enforce_monthly_minutes_limit(plan_code="pro", monthly_limit=100, used_minutes=50)
    with pytest.raises(ApiError):
        api_module._enforce_monthly_minutes_limit(
            plan_code="pro", monthly_limit=100, used_minutes=100
        )


def test_enforce_storage_limit():
    api_module._enforce_storage_limit(plan_code="free", monthly_storage_gb=0, used_storage_bytes=1)
    api_module._enforce_storage_limit(
        plan_code="pro", monthly_storage_gb=1, used_storage_bytes=10
    )
    with pytest.raises(ApiError):
        api_module._enforce_storage_limit(
            plan_code="pro", monthly_storage_gb=1, used_storage_bytes=float(1024**3) + 1
        )


def test_coerce_aware_datetime():
    assert api_module._coerce_aware_datetime(None) is None
    naive = datetime(2030, 1, 1, 12, 0, 0)
    aware = api_module._coerce_aware_datetime(naive)
    assert aware.tzinfo is timezone.utc
    already = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert api_module._coerce_aware_datetime(already) == already


def test_month_start_utc():
    start = api_module._month_start_utc()
    assert start.day == 1
    assert start.hour == 0
    assert start.tzinfo is timezone.utc


def test_truthy_env(monkeypatch):
    monkeypatch.delenv("TE_FLAG", raising=False)
    monkeypatch.delenv("REFRAME_TE_FLAG", raising=False)
    assert api_module._truthy_env("TE_FLAG") is False
    monkeypatch.setenv("TE_FLAG", "true")
    assert api_module._truthy_env("TE_FLAG") is True


# ---------------------------------------------------------------------------
# DB-backed helpers (use the configured engine from test_client)
# ---------------------------------------------------------------------------


def test_resolve_plan_code_no_org(test_client):
    engine = get_engine()
    with Session(engine) as session:
        assert api_module._resolve_plan_code(session, org_id=None) == "free"


def test_ensure_project_exists_none(test_client):
    engine = get_engine()
    with Session(engine) as session:
        assert api_module._ensure_project_exists(session, None) is None


def test_ensure_project_exists_missing(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError) as exc:
            api_module._ensure_project_exists(session, uuid4())
        assert exc.value.status_code == 404


def test_ensure_asset_exists_missing(test_client):
    engine = get_engine()
    with Session(engine) as session:
        with pytest.raises(ApiError) as exc:
            api_module._ensure_asset_exists(
                session, asset_id=uuid4(), principal=AuthPrincipal()
            )
        assert exc.value.status_code == 404


def test_enforce_org_quota_no_op_without_billing(test_client, monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "false")
    get_settings.cache_clear()
    engine = get_engine()
    with Session(engine) as session:
        # org_id None -> early return; billing disabled -> early return.
        api_module._enforce_org_quota(session, AuthPrincipal(org_id=None))
        api_module._enforce_org_quota(session, AuthPrincipal(org_id=uuid4()))
    get_settings.cache_clear()


def test_enforce_org_budget_policy_no_op_without_billing(test_client, monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "false")
    get_settings.cache_clear()
    engine = get_engine()
    with Session(engine) as session:
        api_module._enforce_org_budget_policy(
            session, AuthPrincipal(org_id=None), job_type="captions", job_payload=None
        )
    get_settings.cache_clear()
