"""Second batch of direct helper unit tests for :mod:`app.api` (quota, retry, workflow)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlmodel import Session

from app import api as api_module
from app.config import get_settings
from app.database import get_engine
from app.errors import ApiError
from app.models import (
    Job,
    JobStatus,
    MediaAsset,
    OrgBudgetPolicy,
    Subscription,
    UsageEvent,
    UsageLedgerEntry,
)
from app.security import AuthPrincipal


# ---------------------------------------------------------------------------
# _dispatch_existing_job unsupported type
# ---------------------------------------------------------------------------


def test_dispatch_existing_job_unsupported_type(test_client):
    engine = get_engine()
    with Session(engine) as session:
        job = Job(job_type="unknown_type", status=JobStatus.failed)
        with pytest.raises(ApiError) as exc:
            api_module._dispatch_existing_job(job, session)
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# _normalize_workflow_steps validation
# ---------------------------------------------------------------------------


def test_normalize_workflow_steps_errors():
    with pytest.raises(ApiError):
        api_module._normalize_workflow_steps(["not-a-dict"])
    with pytest.raises(ApiError):
        api_module._normalize_workflow_steps([{"type": "bogus"}])
    # publish step without connection_id -> error
    with pytest.raises(ApiError):
        api_module._normalize_workflow_steps([{"type": "publish_youtube", "payload": {}}])
    # empty -> error
    with pytest.raises(ApiError):
        api_module._normalize_workflow_steps([])


def test_normalize_workflow_steps_ok():
    out = api_module._normalize_workflow_steps(
        [
            {"type": "captions", "payload": {"x": 1}},
            {"step_type": "publish_tiktok", "payload": {"connection_id": "c1"}},
        ]
    )
    assert out[0] == {"type": "captions", "payload": {"x": 1}}
    assert out[1]["type"] == "publish_tiktok"


# ---------------------------------------------------------------------------
# _ensure_asset_exists kind mismatch
# ---------------------------------------------------------------------------


def test_ensure_asset_exists_kind_mismatch(test_client):
    engine = get_engine()
    with Session(engine) as session:
        asset = MediaAsset(kind="audio", uri="/media/a.aac")
        session.add(asset)
        session.commit()
        session.refresh(asset)
        with pytest.raises(ApiError) as exc:
            api_module._ensure_asset_exists(
                session,
                asset_id=asset.id,
                principal=AuthPrincipal(),
                kind="video",
                field="video_asset_id",
            )
        assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# budget / quota enforcement (billing enabled)
# ---------------------------------------------------------------------------


def _enable_billing(monkeypatch):
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    get_settings.cache_clear()


def test_enforce_org_budget_policy_hard_limit_exceeded(test_client, monkeypatch):
    _enable_billing(monkeypatch)
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        session.add(
            OrgBudgetPolicy(
                org_id=org_id, monthly_hard_limit_cents=10, enforce_hard_limit=True
            )
        )
        # existing spend already over the tiny hard limit.
        session.add(
            UsageLedgerEntry(
                org_id=org_id,
                metric="job_minutes",
                quantity=1.0,
                estimated_cost_cents=100,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        with pytest.raises(ApiError) as exc:
            api_module._enforce_org_budget_policy(
                session,
                AuthPrincipal(org_id=org_id),
                job_type="captions",
                job_payload={},
            )
        assert exc.value.status_code == 429
    get_settings.cache_clear()


def test_enforce_org_budget_policy_no_policy(test_client, monkeypatch):
    _enable_billing(monkeypatch)
    engine = get_engine()
    with Session(engine) as session:
        # No policy row -> early return, no raise.
        api_module._enforce_org_budget_policy(
            session, AuthPrincipal(org_id=uuid4()), job_type="captions", job_payload={}
        )
    get_settings.cache_clear()


def test_enforce_org_quota_concurrent_limit(test_client, monkeypatch):
    _enable_billing(monkeypatch)
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        # free plan: max_concurrent_jobs == 1; create one running job to hit the limit.
        session.add(Subscription(org_id=org_id, plan_code="free", status="active"))
        session.add(Job(job_type="captions", status=JobStatus.running, org_id=org_id))
        session.commit()
        with pytest.raises(ApiError) as exc:
            api_module._enforce_org_quota(session, AuthPrincipal(org_id=org_id))
        assert exc.value.status_code == 429
    get_settings.cache_clear()


def test_enforce_org_quota_monthly_minutes_limit(test_client, monkeypatch):
    _enable_billing(monkeypatch)
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        session.add(Subscription(org_id=org_id, plan_code="free", status="active"))
        # free plan monthly_job_minutes == 120; record usage at/over it.
        session.add(
            UsageEvent(
                org_id=org_id,
                metric="job_minutes",
                quantity=200.0,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        with pytest.raises(ApiError) as exc:
            api_module._enforce_org_quota(session, AuthPrincipal(org_id=org_id))
        assert exc.value.status_code == 429
    get_settings.cache_clear()


def test_enforce_subscription_inactive_blocks_paid_plan(test_client, monkeypatch):
    _enable_billing(monkeypatch)
    engine = get_engine()
    org_id = uuid4()
    with Session(engine) as session:
        session.add(Subscription(org_id=org_id, plan_code="pro", status="past_due"))
        session.commit()
        with pytest.raises(ApiError) as exc:
            api_module._enforce_org_quota(session, AuthPrincipal(org_id=org_id))
        assert exc.value.status_code == 429
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _summarize_output_assets with a real local asset
# ---------------------------------------------------------------------------


def test_summarize_output_assets(test_client, monkeypatch, tmp_path):
    engine = get_engine()
    settings = get_settings()
    media_root = settings.media_root
    # Write a real file under the media root so the size branch runs.
    from pathlib import Path

    target_dir = Path(media_root) / "out"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "o.mp4").write_bytes(b"x" * 50)
    with Session(engine) as session:
        asset = MediaAsset(kind="video", uri="/media/out/o.mp4", duration=12.5)
        session.add(asset)
        session.commit()
        session.refresh(asset)
        duration, generated = api_module._summarize_output_assets(session, {asset.id})
        assert duration == 12.5
        assert generated == 50
        # empty set short-circuits.
        assert api_module._summarize_output_assets(session, set()) == (0.0, 0)
