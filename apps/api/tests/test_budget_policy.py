from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models import OrgBudgetPolicy, UsageLedgerEntry


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _register(client, *, email: str, password: str = "Password123!", organization_name: str = "Budget Org") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "organization_name": organization_name},
    )
    _expect(resp.status_code == 201, f"register failed: {resp.text}")
    return resp.json()


def _upload_video(client, headers: dict[str, str], name: str = "budget-video.mp4") -> dict:
    resp = client.post(
        "/api/v1/assets/upload",
        headers=headers,
        data={"kind": "video"},
        files={"file": (name, b"video-bytes", "video/mp4")},
    )
    _expect(resp.status_code == 201, f"video upload failed: {resp.text}")
    return resp.json()


def _set_billing_enabled(monkeypatch) -> None:
    monkeypatch.setenv("REFRAME_ENABLE_BILLING", "true")
    get_settings.cache_clear()


def _seed_budget_policy_and_usage(*, org_id: str, hard_limit_cents: int, current_cost_cents: int) -> None:
    engine = get_engine()
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        policy = session.exec(select(OrgBudgetPolicy).where(OrgBudgetPolicy.org_id == UUID(org_id))).first()
        if policy is None:
            policy = OrgBudgetPolicy(
                org_id=UUID(org_id),
                monthly_hard_limit_cents=hard_limit_cents,
                monthly_soft_limit_cents=None,
                enforce_hard_limit=True,
            )
        else:
            policy.monthly_hard_limit_cents = hard_limit_cents
            policy.enforce_hard_limit = True
        entry = UsageLedgerEntry(
            org_id=UUID(org_id),
            metric="job_minutes",
            unit="minutes",
            quantity=0.0,
            estimated_cost_cents=current_cost_cents,
            payload={},
            created_at=now,
        )
        session.add(policy)
        session.add(entry)
        session.commit()


def test_budget_policy_get_and_put(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    _set_billing_enabled(monkeypatch)

    owner = _register(client, email="budget-owner@example.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}

    first = client.get("/api/v1/usage/budget-policy", headers=headers)
    _expect(first.status_code == 200, f"budget policy GET failed: {first.text}")
    first_payload = first.json()
    _expect(first_payload["monthly_soft_limit_cents"] is None, "Expected default soft limit to be unset")
    _expect(first_payload["monthly_hard_limit_cents"] is None, "Expected default hard limit to be unset")
    _expect(first_payload["enforce_hard_limit"] is False, "Expected default enforce_hard_limit to be false")

    update = client.put(
        "/api/v1/usage/budget-policy",
        headers=headers,
        json={
            "monthly_soft_limit_cents": 500,
            "monthly_hard_limit_cents": 800,
            "enforce_hard_limit": True,
        },
    )
    _expect(update.status_code == 200, f"budget policy PUT failed: {update.text}")
    update_payload = update.json()
    _expect(update_payload["monthly_soft_limit_cents"] == 500, "Expected updated soft limit")
    _expect(update_payload["monthly_hard_limit_cents"] == 800, "Expected updated hard limit")
    _expect(update_payload["enforce_hard_limit"] is True, "Expected enforce_hard_limit true after update")

    second = client.get("/api/v1/usage/budget-policy", headers=headers)
    _expect(second.status_code == 200, f"budget policy GET after update failed: {second.text}")
    second_payload = second.json()
    _expect(second_payload["monthly_soft_limit_cents"] == 500, "Expected persisted soft limit")
    _expect(second_payload["monthly_hard_limit_cents"] == 800, "Expected persisted hard limit")


def test_budget_policy_hard_limit_blocks_job_submission(test_client, monkeypatch):
    client, _enqueued, _worker, _media_root = test_client
    _set_billing_enabled(monkeypatch)

    owner = _register(client, email="budget-hardlimit@example.com")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}

    _seed_budget_policy_and_usage(
        org_id=owner["org_id"],
        hard_limit_cents=100,
        current_cost_cents=95,
    )

    video = _upload_video(client, headers)
    blocked = client.post(
        "/api/v1/captions/jobs",
        headers=headers,
        json={
            "video_asset_id": video["id"],
            "options": {"formats": ["srt"], "estimated_cost_cents": 10},
        },
    )
    _expect(blocked.status_code == 429, f"Expected budget block on captions job: {blocked.text}")
    payload = blocked.json()
    _expect(payload["code"] == "QUOTA_EXCEEDED", "Expected QUOTA_EXCEEDED error code")
    details = payload.get("details") or {}
    _expect(details.get("monthly_hard_limit_cents") == 100, "Expected hard-limit details in quota response")
    _expect(details.get("projected_month_estimated_cost_cents", 0) > 100, "Expected projected cost to exceed hard limit")
