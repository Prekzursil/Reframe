"""Tests for the worker asset-retention helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.worker.worker import (  # pylint: disable=import-error
    _is_older_than_retention,
    _retention_days_for_plan,
)


def test_retention_days_differ_by_plan():
    """Retention windows increase from free to pro to enterprise plans."""
    free_days = _retention_days_for_plan("free")
    pro_days = _retention_days_for_plan("pro")
    enterprise_days = _retention_days_for_plan("enterprise")

    assert free_days < pro_days < enterprise_days


def test_asset_retention_eligibility_uses_plan_window():
    """Retention eligibility respects each plan's retention window."""
    now = datetime.now(timezone.utc)
    old_free = now - timedelta(days=_retention_days_for_plan("free") + 1)
    old_enterprise = now - timedelta(days=_retention_days_for_plan("enterprise") - 1)

    assert _is_older_than_retention(created_at=old_free, plan_code="free", now=now) is True
    assert (
        _is_older_than_retention(created_at=old_enterprise, plan_code="enterprise", now=now)
        is False
    )
