"""Unit tests for media_studio.models.key_pool_status (M4 per-key cooldown).

PURE classification: HTTP 402/429 park a key, the free-tier <10-credit cap parks
a free key, and everything else stays active. No transport, no socket — the rule
is provable in isolation.
"""

from __future__ import annotations

import pytest
from media_studio.models import key_pool_status as kps


# --------------------------------------------------------------------------- #
# cooldown_reason_for_code — only 402/429 park a key
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", [402, 429])
def test_cooldown_reason_for_code_parks_402_429(code: int) -> None:
    reason = kps.cooldown_reason_for_code(code)
    assert reason is not None
    assert str(code) in reason


@pytest.mark.parametrize("code", [None, 401, 403, 500])
def test_cooldown_reason_for_code_other_codes_are_none(code: int | None) -> None:
    assert kps.cooldown_reason_for_code(code) is None


# --------------------------------------------------------------------------- #
# free_cap_reason — free-tier key under the 10-credit floor only
# --------------------------------------------------------------------------- #
def test_free_cap_reason_free_tier_under_floor() -> None:
    assert kps.free_cap_reason(is_free_tier=True, remaining_usd=4.0) == kps.FREE_CAP_REASON


def test_free_cap_reason_free_tier_at_floor_is_active() -> None:
    # Exactly at the floor is NOT below it (strict ``<``) -> not parked.
    assert kps.free_cap_reason(is_free_tier=True, remaining_usd=kps.FREE_TIER_CREDIT_FLOOR) is None


def test_free_cap_reason_free_tier_above_floor_is_active() -> None:
    assert kps.free_cap_reason(is_free_tier=True, remaining_usd=25.0) is None


def test_free_cap_reason_free_tier_unknown_remaining_is_active() -> None:
    assert kps.free_cap_reason(is_free_tier=True, remaining_usd=None) is None


def test_free_cap_reason_paid_tier_is_active() -> None:
    assert kps.free_cap_reason(is_free_tier=False, remaining_usd=1.0) is None


# --------------------------------------------------------------------------- #
# classify_success — (status, reason) for a successful probe
# --------------------------------------------------------------------------- #
def test_classify_success_free_cap_is_cooldown() -> None:
    status, reason = kps.classify_success({"costUsd": 0.0, "limitUsd": 10.0, "remainingUsd": 2.0, "isFreeTier": True})
    assert status == kps.STATUS_COOLDOWN
    assert reason == kps.FREE_CAP_REASON


def test_classify_success_paid_is_active_no_reason() -> None:
    status, reason = kps.classify_success({"costUsd": 1.0, "limitUsd": 50.0, "remainingUsd": 49.0, "isFreeTier": False})
    assert status == kps.STATUS_ACTIVE
    assert reason is None


def test_classify_success_empty_parsed_defaults_active() -> None:
    assert kps.classify_success({}) == (kps.STATUS_ACTIVE, None)


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
