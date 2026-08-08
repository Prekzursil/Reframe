"""Social publish / schedule (C14) — the per-platform capability matrix.

WHY THIS MODULE IS A MATRIX AND NOT FOUR UPLOADERS
--------------------------------------------------
C14 asks for "direct publish / scheduling to social platforms" from Reframe — a
LOCAL desktop app with no server and no public domain. The four target platforms
differ sharply in what that actually permits, and **two of the four cannot publish
to a PERSONAL account at all**. Encoding that as data (rather than discovering it
at runtime as a 400) is what keeps the UI from offering a publish the platform
would refuse.

Every row was read off the platform's own current documentation on 2026-08-08; the
``doc_url`` rides with the row so a future reader can re-check it rather than trust
this comment. The four findings, each with the fact that decided it:

* **YouTube — PUBLISHABLE, schedules natively.** ``videos.insert`` uploads to a
  personal channel, Google's installed-app flow accepts a ``http://127.0.0.1:<port>``
  loopback redirect with PKCE S256 (the copy/paste "OOB" flow is retired), and
  ``status.publishAt`` lets the PLATFORM hold a future publish. Caveat that ships
  in the row: uploads from an **unverified** API project created after 2020-07-28
  are forced to private until the project passes an audit.
* **TikTok — PUBLISHABLE, cannot schedule.** Contrary to the obvious assumption,
  TikTok DOES document a desktop flow whose redirect host may only be ``localhost``
  or ``127.0.0.1`` and for which PKCE S256 is REQUIRED (it is the *web* config that
  demands an ``https`` URI). But the Content Posting API has no scheduling
  parameter at all, and an **unaudited** client is restricted to private
  (``SELF_ONLY``) visibility.
* **Instagram Reels — NOT PUBLISHABLE from a personal account.** The Instagram
  Platform API states plainly that an app user must have an Instagram
  *professional* account (Business or Creator); a personal/consumer account is not
  served by the API at all. This is a property of the ACCOUNT, not of our app, so
  no amount of local engineering unblocks it — hence a ``blocked_reason`` rather
  than a stub uploader.
* **Facebook — a PAGE only, never a personal timeline.** The ``publish_actions``
  permission that allowed posting to a user's own profile was removed on
  2018-04-24 and is not granted to new apps, so there is deliberately NO
  ``facebook_timeline`` row. Publishing to a Page the user administers IS
  supported and schedules natively (``published=false`` +
  ``scheduled_publish_time``), bounded to 30 days out.

HONESTY ABOUT SCHEDULING (the part a desktop app usually lies about)
--------------------------------------------------------------------
A local app is OFF when the machine is off, so a purely local scheduler cannot
honour "post at 09:00 tomorrow" if the laptop is shut. :func:`plan_schedule`
therefore always prefers handing the future time to the PLATFORM when the platform
can hold it, and only falls back to a local queue when it cannot — and that
fallback carries an explicit ``requires_app_running`` flag plus a warning string
the UI is expected to show verbatim. The flag is the mechanism: a caller cannot
render a local-queue plan without also receiving the disclosure.

Pure logic only — no network, no provider imports, no token handling. Tokens for
these platforms live exclusively in the Electron main process keystore
(``app/main/keystore.ts``) and are injected per-request; nothing here reads,
writes, or logs credential material.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..protocol import ErrorCode, RpcError

#: Seconds in 30 days — the documented outer bound on a Facebook Page's
#: ``scheduled_publish_time`` ("between 10 minutes and 30 days from the time of
#: the API request").
_FACEBOOK_SCHEDULE_MAX_SEC = 30 * 24 * 60 * 60

#: The plan kinds :func:`plan_schedule` can return.
KIND_IMMEDIATE = "immediate"
KIND_PLATFORM = "platform"
KIND_LOCAL_QUEUE = "local-queue"

#: The verbatim disclosure a local-queue plan carries. A desktop app is not a
#: server: this text is the whole reason :class:`SchedulePlan` has a warning field.
LOCAL_QUEUE_WARNING = (
    "This platform's API cannot hold a scheduled post, so Reframe will publish it "
    "from this computer at the chosen time. Reframe must be running then — if the "
    "computer is asleep, shut down, or offline, the post is sent when Reframe next "
    "runs, not at the time you picked."
)


@dataclass(frozen=True)
class PlatformCapability:
    """What ONE platform actually permits a local desktop app to do.

    Every boolean here is a documented platform rule, not a Reframe policy, so a
    ``False`` cannot be engineered away on our side — it can only change when the
    platform changes (which is what ``doc_url`` is for).
    """

    #: Stable wire id (also the settings/queue key).
    id: str
    #: Human label for the UI.
    label: str
    #: Whether this app can publish here AT ALL. ``False`` iff ``blocked_reason``.
    publishable: bool
    #: Whether a PERSONAL (non-professional, non-Page) account can be published to.
    personal_account: bool
    #: Whether the platform's OAuth accepts a loopback redirect for a desktop app.
    desktop_loopback_oauth: bool
    #: Whether the PLATFORM can hold a future publish time (survives a powered-off
    #: machine). When ``False`` a future time can only ride the local queue.
    native_scheduling: bool
    #: How far out the platform will accept a scheduled time, in seconds; ``None``
    #: when the platform documents no cap.
    #:
    #: UNVERIFIED (youtube): YouTube's ``status.publishAt`` reference states no
    #: maximum horizon, so this is ``None`` rather than a number invented here. A
    #: future publishAt further out than YouTube silently tolerates would surface
    #: as an API error, not as a wrong local decision. SETTLING EXPERIMENT: submit
    #: a ``publishAt`` several years out against a real audited project and record
    #: the accepted bound.
    native_schedule_max_sec: int | None
    #: Whether the token exchange requires a client secret. ``True`` everywhere
    #: here, which is precisely why Reframe uses a bring-your-own-OAuth-app model
    #: (see the module note in ``docs/wiring/WIRING-social-publish.md``): a
    #: DISTRIBUTED desktop binary cannot embed a confidential client secret.
    requires_client_secret: bool
    #: What an app that has NOT passed the platform's review/audit is limited to.
    #: Surfaced before the first publish so the restriction is never a surprise.
    unaudited_visibility: str
    #: The documentation page this row was read from.
    doc_url: str
    #: WHY publishing is impossible, or ``None`` when it is possible.
    blocked_reason: str | None


CAPABILITIES: dict[str, PlatformCapability] = {
    "youtube": PlatformCapability(
        id="youtube",
        label="YouTube",
        publishable=True,
        personal_account=True,
        desktop_loopback_oauth=True,
        native_scheduling=True,
        native_schedule_max_sec=None,
        requires_client_secret=True,
        unaudited_visibility=(
            "Until your Google Cloud project passes YouTube's API audit, every video "
            "uploaded through it is forced to PRIVATE. Uploads still succeed; only "
            "the visibility is capped."
        ),
        doc_url="https://developers.google.com/youtube/v3/docs/videos/insert",
        blocked_reason=None,
    ),
    "tiktok": PlatformCapability(
        id="tiktok",
        label="TikTok",
        publishable=True,
        personal_account=True,
        desktop_loopback_oauth=True,
        native_scheduling=False,
        native_schedule_max_sec=None,
        requires_client_secret=True,
        unaudited_visibility=(
            "Until your TikTok app passes TikTok's audit, all content it posts is "
            "restricted to private (SELF_ONLY) viewing."
        ),
        doc_url="https://developers.tiktok.com/doc/content-posting-api-get-started",
        blocked_reason=None,
    ),
    "instagram_reels": PlatformCapability(
        id="instagram_reels",
        label="Instagram Reels",
        publishable=False,
        personal_account=False,
        desktop_loopback_oauth=False,
        native_scheduling=False,
        native_schedule_max_sec=None,
        requires_client_secret=True,
        unaudited_visibility=(
            "Publishing needs Advanced Access to instagram_content_publish, which requires Meta App Review."
        ),
        doc_url="https://developers.facebook.com/docs/instagram-platform/overview",
        blocked_reason=(
            "Instagram's API only serves an Instagram PROFESSIONAL account (Business "
            "or Creator). A personal Instagram account cannot be published to through "
            "any API, so Reframe cannot post Reels for you. Converting the account to "
            "a professional one in the Instagram app is what unblocks this — it is an "
            "account setting, not something Reframe can work around."
        ),
    ),
    "facebook_page": PlatformCapability(
        id="facebook_page",
        label="Facebook Page",
        publishable=True,
        # A Page is administered BY a personal account but is not itself one; the
        # personal TIMELINE has been unpublishable since publish_actions was removed
        # on 2018-04-24, which is why there is no facebook_timeline row at all.
        personal_account=False,
        desktop_loopback_oauth=False,
        native_scheduling=True,
        native_schedule_max_sec=_FACEBOOK_SCHEDULE_MAX_SEC,
        requires_client_secret=True,
        unaudited_visibility=(
            "Publishing needs Advanced Access to pages_manage_posts, which requires "
            "Meta App Review. Before review, only accounts with a role on the app "
            "(admin / developer / tester) can publish."
        ),
        doc_url="https://developers.facebook.com/docs/pages-api/posts",
        blocked_reason=None,
    ),
}


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def capability(platform_id: Any) -> PlatformCapability:
    """The :class:`PlatformCapability` for ``platform_id``.

    Fails loud on anything unknown rather than defaulting: a typo'd platform must
    never silently resolve to a row whose rules do not apply to it.
    """
    if not isinstance(platform_id, str) or platform_id not in CAPABILITIES:
        known = ", ".join(sorted(CAPABILITIES))
        raise _invalid(f"unknown social platform: {platform_id!r} (known: {known})")
    return CAPABILITIES[platform_id]


def _as_row(cap: PlatformCapability) -> dict[str, Any]:
    """Render one capability as the frozen camelCase wire row."""
    return {
        "id": cap.id,
        "label": cap.label,
        "publishable": cap.publishable,
        "personalAccount": cap.personal_account,
        "desktopLoopbackOauth": cap.desktop_loopback_oauth,
        "nativeScheduling": cap.native_scheduling,
        "nativeScheduleMaxSec": cap.native_schedule_max_sec,
        "requiresClientSecret": cap.requires_client_secret,
        "unauditedVisibility": cap.unaudited_visibility,
        "docUrl": cap.doc_url,
        "blockedReason": cap.blocked_reason,
    }


def describe_capabilities() -> list[dict[str, Any]]:
    """The whole matrix as id-sorted JSON rows (stable UI order)."""
    return [_as_row(CAPABILITIES[key]) for key in sorted(CAPABILITIES)]


@dataclass(frozen=True)
class SchedulePlan:
    """WHERE a publish time will be held, and what the user must be told.

    ``requires_app_running`` exists so the disclosure is structural: a caller
    cannot obtain a local-queue plan without also receiving the flag and the
    ``warning`` text that explains a desktop app cannot publish while off.
    """

    platform: str
    #: One of :data:`KIND_IMMEDIATE` / :data:`KIND_PLATFORM` / :data:`KIND_LOCAL_QUEUE`.
    kind: str
    #: The requested epoch-seconds publish time, or ``None`` for an immediate post.
    publish_at: float | None
    #: True only when Reframe itself must be running at ``publish_at``.
    requires_app_running: bool
    #: Verbatim user-facing disclosure; ``""`` when there is nothing to disclose.
    warning: str
    #: The platform's pre-audit visibility cap, echoed so the UI can show it once.
    unaudited_visibility: str


def _validated_publish_at(publish_at: Any, now: float) -> float:
    """Coerce + guard a requested publish time into future epoch seconds."""
    # bool is an int subclass; reject it explicitly so True cannot pose as a time.
    if isinstance(publish_at, bool) or not isinstance(publish_at, (int, float)):
        raise _invalid("publishAt must be epoch seconds (a number) or null")
    moment = float(publish_at)
    if moment <= now:
        raise _invalid("publishAt is in the past; pick a future time or publish now")
    return moment


def _holds_natively(cap: PlatformCapability, publish_at: float, now: float) -> bool:
    """Whether the PLATFORM can hold ``publish_at`` itself.

    False when the platform has no scheduling API at all, and also when the
    requested time is past the horizon the platform documents — handing an API a
    time it will reject is worse than queueing locally and saying so.
    """
    if not cap.native_scheduling:
        return False
    horizon = cap.native_schedule_max_sec
    return horizon is None or publish_at <= now + horizon


def plan_schedule(platform_id: Any, publish_at: Any, *, now: float) -> SchedulePlan:
    """Decide where a publish time is held, refusing what the platform cannot do.

    ``publish_at`` is epoch seconds, or ``None`` for "publish now". ``now`` is
    injected (never read from the clock here) so the decision is a pure function
    and the boundary cases are unit-pinnable.

    Raises :class:`RpcError` (INVALID_PARAMS) for an unknown platform, a platform
    that cannot be published to at all, or a non-numeric / past time — always
    BEFORE any queue write, so a refused request leaves no partial state.
    """
    cap = capability(platform_id)
    if not cap.publishable:
        # blocked_reason is non-None whenever publishable is False (both are set
        # together per row), so this surfaces the platform's own reason verbatim.
        raise _invalid(cap.blocked_reason or f"{cap.label} cannot be published to")

    if publish_at is None:
        return SchedulePlan(
            platform=cap.id,
            kind=KIND_IMMEDIATE,
            publish_at=None,
            requires_app_running=False,
            warning="",
            unaudited_visibility=cap.unaudited_visibility,
        )

    moment = _validated_publish_at(publish_at, now)
    if _holds_natively(cap, moment, now):
        return SchedulePlan(
            platform=cap.id,
            kind=KIND_PLATFORM,
            publish_at=moment,
            requires_app_running=False,
            warning="",
            unaudited_visibility=cap.unaudited_visibility,
        )
    return SchedulePlan(
        platform=cap.id,
        kind=KIND_LOCAL_QUEUE,
        publish_at=moment,
        requires_app_running=True,
        warning=LOCAL_QUEUE_WARNING,
        unaudited_visibility=cap.unaudited_visibility,
    )
