"""Social publish QUEUE + the ``social.*`` RPC group (C14).

The durable record of what Reframe has been asked to publish, stored as one JSON
document under the data root and written atomically (temp + ``os.replace``), so a
crash mid-write can never truncate the queue. Storage + pure logic only: no
network, no provider imports, and — deliberately — no credential handling at all.

THE NO-TOKEN-AT-REST INVARIANT (why the entry shape is an ALLOWLIST)
-------------------------------------------------------------------
OAuth tokens for these platforms live ONLY in the Electron main-process keystore
(``app/main/keystore.ts``, DPAPI/Keychain-wrapped) and are injected per-request
over the existing stdio JSON-RPC frame, exactly as provider API keys already are.
This queue file is plain JSON on disk, so a token reaching an entry would be a
plaintext credential at rest — the precise defect that keystore exists to prevent.

:func:`normalize_job` therefore builds each entry from a fixed field ALLOWLIST
(:data:`ENTRY_FIELDS`) rather than copying the caller's dict and deleting known
secret names. A denylist only protects against the secret field names someone
thought of; an allowlist protects against the one nobody has invented yet, because
an unrecognised key cannot ride along at all. :func:`is_secret_field` exists for
the regression that scans the persisted BYTES, so the invariant is asserted
structurally rather than on one happy path.

REFUSE BEFORE WRITE
-------------------
Every guard runs before any filesystem touch, so a rejected enqueue leaves no file
and no partial row. That matters most for ``instagram_reels``, which
:mod:`social_publish` marks unpublishable: without the pre-write refusal the queue
would silently accumulate entries that can never run.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import protocol
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import get_logger
from . import social_publish

log = get_logger("media_studio.features.social_queue")

QueueEntry = dict[str, Any]

#: The per-request field name main uses to inject decrypted social tokens
#: (mirrors ``settings_store.INJECTED_KEYS_FIELD`` for provider keys). Named here
#: so the strip is enforced at the store boundary as well as at the RPC boundary.
INJECTED_TOKENS_FIELD = "_injectedSocialTokens"

#: Entry lifecycle. ``publishing`` / ``done`` / ``failed`` are written by the
#: runner that performs the upload; the store only ever creates ``pending`` and
#: transitions to ``cancelled``.
STATUS_PENDING = "pending"
STATUS_PUBLISHING = "publishing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

#: The COMPLETE set of keys a persisted entry may carry. See the module docstring:
#: this is an allowlist precisely so an unknown (possibly secret-bearing) field
#: cannot be persisted by accident.
ENTRY_FIELDS: tuple[str, ...] = (
    "id",
    "platform",
    "videoId",
    "clipPath",
    "title",
    "description",
    "publishAt",
    "kind",
    "requiresAppRunning",
    "status",
    "createdAt",
    "error",
)

#: Substrings that mark a field name as credential-bearing. Used ONLY by the
#: structural regression (:func:`is_secret_field`) — the production path relies on
#: :data:`ENTRY_FIELDS` instead, because a substring denylist is not a security
#: boundary. Lowercased comparison so ``accessToken`` / ``access_token`` both hit.
_SECRET_NAME_MARKERS: tuple[str, ...] = ("token", "secret", "password", "credential", "apikey")


def is_secret_field(name: str) -> bool:
    """Whether ``name`` looks credential-bearing (regression helper, not a guard).

    Deliberately generous: it exists so a test can scan the persisted bytes and
    fail loudly if ANY token-shaped key ever appears, without having to enumerate
    the field names a future platform might introduce.
    """
    lowered = name.replace("_", "").lower()
    return any(marker in lowered for marker in _SECRET_NAME_MARKERS)


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"job.{key} (non-empty str) is required")
    return value.strip()


def _optional_str(raw: dict[str, Any], key: str) -> str:
    """A trimmed optional string; a non-string value is a fail-loud refusal.

    Coercing (``str(value)``) would quietly persist ``"7"`` for a numeric title,
    so a wrong type is reported instead of normalised away.
    """
    value = raw.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(f"job.{key} must be a str when present")
    return value.strip()


def normalize_job(raw: Any, *, now: float) -> QueueEntry:
    """Validate a publish request into the frozen :data:`ENTRY_FIELDS` wire shape.

    Runs the platform guard and the schedule plan FIRST, so an unpublishable
    platform or a past ``publishAt`` raises before the caller ever reaches a write.
    The resulting entry is assembled key-by-key from the allowlist — the caller's
    dict is never copied wholesale, so no unexpected (or secret) field survives.
    """
    if not isinstance(raw, dict):
        raise _invalid("job must be an object")

    # capability() + plan_schedule() own the platform/time refusals, including the
    # blocked-platform reason and the local-vs-platform scheduling decision.
    plan = social_publish.plan_schedule(raw.get("platform"), raw.get("publishAt"), now=now)

    return {
        "id": uuid.uuid4().hex[:12],
        "platform": plan.platform,
        "videoId": _optional_str(raw, "videoId"),
        "clipPath": _require_str(raw, "clipPath"),
        "title": _require_str(raw, "title"),
        "description": _optional_str(raw, "description"),
        "publishAt": plan.publish_at,
        "kind": plan.kind,
        "requiresAppRunning": plan.requires_app_running,
        "status": STATUS_PENDING,
        "createdAt": now,
        "error": "",
    }


class PublishQueueStore:
    """A JSON-backed publish queue (atomic temp+rename writes).

    An absent, corrupt, or wrongly-shaped document reads as an EMPTY queue rather
    than raising: a poisoned file must not brick the Publish panel. Unlike the
    export-preset catalog there is no reseed — an empty publish queue is a
    perfectly valid state, so recovering silently loses nothing.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def _read(self) -> list[QueueEntry]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("social queue unreadable (%s); treating as empty", exc)
            return []
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def _write(self, entries: list[QueueEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[QueueEntry]:
        """Every entry, oldest first (insertion order)."""
        return self._read()

    def enqueue(self, job: Any, *, now: float) -> QueueEntry:
        """Append a normalized entry and return it.

        Normalization (and every refusal it raises) happens BEFORE the read/write,
        so a rejected job leaves the queue file exactly as it was — including not
        creating it at all on a first-ever rejected call.
        """
        entry = normalize_job(job, now=now)
        self._write([*self._read(), entry])
        return entry

    def cancel(self, entry_id: str) -> bool:
        """Mark a PENDING entry cancelled. ``False`` when there was nothing to do.

        The row is kept (not deleted) so the panel can still show what was asked
        for and what became of it. Only ``pending`` is cancellable: an entry the
        runner already took, finished, failed, or a second cancel of the same row
        all answer ``False`` rather than rewriting a terminal state.
        """
        entries = self._read()
        changed = False
        out: list[QueueEntry] = []
        for entry in entries:
            if entry.get("id") == entry_id and entry.get("status") == STATUS_PENDING:
                out.append({**entry, "status": STATUS_CANCELLED})
                changed = True
            else:
                out.append(entry)
        if changed:
            self._write(out)
        return changed

    def due(self, *, now: float) -> list[QueueEntry]:
        """Pending LOCAL-QUEUE entries whose time has come.

        Deliberately excludes ``kind == "platform"`` rows: those were handed to the
        platform's own scheduler, so publishing them locally as well would
        double-post. A row with no ``publishAt`` means "as soon as possible" and is
        due immediately.
        """
        out: list[QueueEntry] = []
        for entry in self._read():
            if entry.get("status") != STATUS_PENDING:
                continue
            if entry.get("kind") == social_publish.KIND_PLATFORM:
                continue
            moment = entry.get("publishAt")
            if moment is None or float(moment) <= now:
                out.append(entry)
        return out


def _plan_row(plan: social_publish.SchedulePlan) -> dict[str, Any]:
    """Render a :class:`~.social_publish.SchedulePlan` as the camelCase wire row."""
    return {
        "platform": plan.platform,
        "kind": plan.kind,
        "publishAt": plan.publish_at,
        "requiresAppRunning": plan.requires_app_running,
        "warning": plan.warning,
        "unauditedVisibility": plan.unaudited_visibility,
    }


class SocialPublish:
    """The ``social.*`` handler group — direct-return CRUD over the queue.

    No jobs and no notifications: enqueueing is a storage operation. Performing the
    upload is a separate concern that needs an injected token, so it deliberately
    does not live here.
    """

    def __init__(self, store: PublishQueueStore, clock: Callable[[], float]) -> None:
        self.store = store
        self.now = clock

    def capabilities(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``social.capabilities()`` -> ``{platforms:[row]}`` (the honest matrix)."""
        return {"platforms": social_publish.describe_capabilities()}

    def plan(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``social.plan({platform, publishAt?})`` -> ``{plan}``.

        A PREVIEW seam: the UI calls this while the user is still picking a time so
        the local-queue disclosure ("Reframe must be running then") can be shown
        BEFORE anything is committed, not after.
        """
        plan = social_publish.plan_schedule(params.get("platform"), params.get("publishAt"), now=self.now())
        return {"plan": _plan_row(plan)}

    def enqueue(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``social.enqueue({job})`` -> ``{entry}``."""
        job = params.get("job")
        if not isinstance(job, dict):
            raise _invalid("job (object) is required")
        return {"entry": self.store.enqueue(job, now=self.now())}

    def queue(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``social.queue()`` -> ``{entries:[entry]}``."""
        return {"entries": self.store.list()}

    def cancel(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``social.cancel({id})`` -> ``{ok}``."""
        return {"ok": self.store.cancel(_require_str(params, "id"))}


def register(
    *,
    path: str | os.PathLike[str],
    clock: Callable[[], float] | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> SocialPublish:
    """Create a :class:`SocialPublish` over ``path`` and register its five methods.

    ``clock`` and ``register_fn`` default to the wall clock and
    :func:`protocol.register`; tests inject a frozen clock + a fake registrar so
    every scheduling boundary is deterministic.
    """
    service = SocialPublish(PublishQueueStore(path), clock if clock is not None else time.time)
    reg = register_fn if register_fn is not None else protocol.register
    reg("social.capabilities", service.capabilities)
    reg("social.plan", service.plan)
    reg("social.enqueue", service.enqueue)
    reg("social.queue", service.queue)
    reg("social.cancel", service.cancel)
    return service
