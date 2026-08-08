"""Social publish/schedule (C14) — the capability matrix + honest schedule planning.

WHY THESE TESTS EXIST
---------------------
C14 ("direct publish / scheduling to social platforms") was originally SKIPPED in
``docs/plans/v1.5/competitor-research.md:23`` in favour of the substitute that
shipped (platform-ready export presets). The owner overruled that, so the feature
is being built — but the four target platforms differ SHARPLY in what a LOCAL
desktop app with no server is actually allowed to do, and two of the four cannot
publish to a PERSONAL account at all.

The capability matrix under test is where that sourced, per-platform truth lives.
It is deliberately CODE, not prose: the UI reads it, so the app is structurally
unable to offer a publish the platform would refuse, and a doc URL rides with
every row so the claim can be re-checked when a platform changes its rules.
"""

from __future__ import annotations

import pytest
from media_studio.features import social_publish
from media_studio.protocol import ErrorCode, RpcError

# --------------------------------------------------------------------------- #
# the capability matrix (the encoded feasibility finding)
# --------------------------------------------------------------------------- #


def test_matrix_covers_the_four_researched_platforms() -> None:
    """The matrix is exactly the four platforms the C14 ask named."""
    assert set(social_publish.CAPABILITIES) == {
        "youtube",
        "tiktok",
        "instagram_reels",
        "facebook_page",
    }


def test_every_capability_carries_a_source_url() -> None:
    """No row may assert a platform rule without the doc it came from."""
    for cap in social_publish.CAPABILITIES.values():
        assert cap.doc_url.startswith("https://"), cap.id


def test_youtube_is_publishable_with_native_scheduling() -> None:
    """YouTube: personal channel + desktop loopback/PKCE + ``status.publishAt``."""
    cap = social_publish.capability("youtube")
    assert cap.publishable is True
    assert cap.personal_account is True
    assert cap.desktop_loopback_oauth is True
    assert cap.native_scheduling is True
    assert cap.blocked_reason is None


def test_tiktok_is_publishable_but_has_no_native_scheduling() -> None:
    """TikTok: desktop loopback + PKCE IS supported, but the API cannot schedule."""
    cap = social_publish.capability("tiktok")
    assert cap.publishable is True
    assert cap.desktop_loopback_oauth is True
    assert cap.native_scheduling is False


def test_instagram_reels_is_blocked_for_a_personal_account() -> None:
    """Instagram REQUIRES a professional account, so a personal one cannot publish."""
    cap = social_publish.capability("instagram_reels")
    assert cap.personal_account is False
    assert cap.publishable is False
    assert cap.blocked_reason is not None
    assert "professional" in cap.blocked_reason.lower()


def test_facebook_page_is_publishable_and_schedules_natively() -> None:
    """Facebook: only a PAGE (never a personal timeline), and it schedules natively."""
    cap = social_publish.capability("facebook_page")
    assert cap.publishable is True
    assert cap.native_scheduling is True
    assert cap.personal_account is False


def test_facebook_personal_timeline_is_absent_from_the_matrix() -> None:
    """``publish_actions`` was removed in 2018, so there is no personal-timeline row."""
    assert "facebook_timeline" not in social_publish.CAPABILITIES
    assert "facebook_profile" not in social_publish.CAPABILITIES


def test_capability_rejects_an_unknown_platform() -> None:
    """An unknown id is a fail-loud INVALID_PARAMS, never a silent default."""
    with pytest.raises(RpcError) as excinfo:
        social_publish.capability("myspace")
    assert excinfo.value.code == ErrorCode.INVALID_PARAMS


def test_capabilities_wire_payload_is_json_shaped() -> None:
    """``describe_capabilities`` renders the matrix as plain JSON for the renderer."""
    rows = social_publish.describe_capabilities()
    assert isinstance(rows, list)
    ids = [row["id"] for row in rows]
    assert ids == sorted(ids), "rows are id-sorted so the UI order is stable"
    youtube = next(row for row in rows if row["id"] == "youtube")
    assert youtube["nativeScheduling"] is True
    assert youtube["publishable"] is True
    assert youtube["docUrl"].startswith("https://")


# --------------------------------------------------------------------------- #
# honest schedule planning
# --------------------------------------------------------------------------- #
NOW = 1_800_000_000.0


def test_no_publish_at_plans_an_immediate_publish() -> None:
    plan = social_publish.plan_schedule("youtube", None, now=NOW)
    assert plan.kind == "immediate"
    assert plan.publish_at is None
    assert plan.requires_app_running is False


def test_future_publish_at_on_youtube_is_handed_to_the_platform() -> None:
    """Native scheduling wins: the PLATFORM holds it, so the machine may be off."""
    plan = social_publish.plan_schedule("youtube", NOW + 3600, now=NOW)
    assert plan.kind == "platform"
    assert plan.publish_at == NOW + 3600
    assert plan.requires_app_running is False


def test_future_publish_at_on_tiktok_falls_back_to_the_local_queue() -> None:
    """No native scheduling -> a LOCAL queue, and it must say the app must be running."""
    plan = social_publish.plan_schedule("tiktok", NOW + 3600, now=NOW)
    assert plan.kind == "local-queue"
    assert plan.requires_app_running is True
    assert "running" in plan.warning.lower()


def test_a_past_publish_at_is_rejected() -> None:
    with pytest.raises(RpcError) as excinfo:
        social_publish.plan_schedule("youtube", NOW - 1, now=NOW)
    assert excinfo.value.code == ErrorCode.INVALID_PARAMS


def test_scheduling_a_blocked_platform_is_rejected() -> None:
    """A platform that cannot publish at all refuses BEFORE any queue write."""
    with pytest.raises(RpcError) as excinfo:
        social_publish.plan_schedule("instagram_reels", None, now=NOW)
    assert excinfo.value.code == ErrorCode.INVALID_PARAMS
    assert "professional" in str(excinfo.value).lower()


def test_a_non_numeric_publish_at_is_rejected() -> None:
    with pytest.raises(RpcError):
        social_publish.plan_schedule("youtube", "tomorrow", now=NOW)  # type: ignore[arg-type]


def test_a_boolean_publish_at_is_rejected() -> None:
    """``bool`` is an ``int`` subclass; True must not pose as an epoch second."""
    with pytest.raises(RpcError):
        social_publish.plan_schedule("youtube", True, now=NOW)  # type: ignore[arg-type]


def test_platform_plan_beyond_the_native_horizon_falls_back_to_local() -> None:
    """Past a platform's own scheduling horizon the platform cannot hold it.

    Facebook Pages caps ``scheduled_publish_time`` at 30 days out, so a request
    further out than that MUST degrade to the local queue (and disclose it)
    rather than being handed to an API that would reject it.
    """
    cap = social_publish.capability("facebook_page")
    beyond = NOW + cap.native_schedule_max_sec + 1
    plan = social_publish.plan_schedule("facebook_page", beyond, now=NOW)
    assert plan.kind == "local-queue"
    assert plan.requires_app_running is True


def test_plan_at_exactly_the_native_horizon_stays_on_the_platform() -> None:
    """The horizon is inclusive — the boundary belongs to the platform path."""
    cap = social_publish.capability("facebook_page")
    edge = NOW + cap.native_schedule_max_sec
    assert social_publish.plan_schedule("facebook_page", edge, now=NOW).kind == "platform"


def test_immediate_plan_has_no_warning() -> None:
    assert social_publish.plan_schedule("youtube", None, now=NOW).warning == ""


def test_platform_plan_discloses_the_unaudited_visibility_limit() -> None:
    """An unaudited OAuth app has its uploads forced private — say so up front."""
    plan = social_publish.plan_schedule("youtube", None, now=NOW)
    assert plan.unaudited_visibility != ""
