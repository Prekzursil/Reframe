from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_retention_days_differ_by_plan():
    from services.worker import worker

    free_days = worker._retention_days_for_plan("free")
    pro_days = worker._retention_days_for_plan("pro")
    enterprise_days = worker._retention_days_for_plan("enterprise")

    assert free_days < pro_days < enterprise_days


def test_asset_retention_eligibility_uses_plan_window():
    from services.worker import worker

    now = datetime.now(timezone.utc)
    old_free = now - timedelta(days=worker._retention_days_for_plan("free") + 1)
    old_enterprise = now - timedelta(days=worker._retention_days_for_plan("enterprise") - 1)

    assert worker._is_older_than_retention(created_at=old_free, plan_code="free", now=now) is True
    assert worker._is_older_than_retention(created_at=old_enterprise, plan_code="enterprise", now=now) is False
