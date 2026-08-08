"""Social publish QUEUE + the ``social.*`` RPC group (C14).

The queue is the durable record of what Reframe has been asked to publish. Two
properties are load-bearing and each has a test that fails if it regresses:

1. **A queue entry NEVER holds credential material.** OAuth tokens for these
   platforms live only in the Electron main-process keystore and are injected
   per-request over the stdio frame. The queue is a JSON file under the data root,
   so a token landing in an entry would be a plaintext credential at rest — the
   exact defect ``app/main/keystore.ts`` exists to prevent. ``test_*_no_token_*``
   asserts the persisted bytes structurally, not by inspecting one happy path.
2. **A blocked platform is refused BEFORE any write.** ``instagram_reels`` cannot
   be published to from a personal account at all, so enqueueing it must raise and
   leave the file untouched rather than accumulating entries that can never run.
"""

from __future__ import annotations

import json

import pytest
from media_studio import protocol
from media_studio.features import social_publish, social_queue
from media_studio.protocol import ErrorCode, RpcContext, RpcError

NOW = 1_800_000_000.0
LATER = NOW + 3600


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda _payload: None, jobs=None)


@pytest.fixture()
def store(tmp_path) -> social_queue.PublishQueueStore:
    return social_queue.PublishQueueStore(tmp_path / "social-queue.json")


def _job(**over) -> dict:
    base = {
        "platform": "youtube",
        "clipPath": "exports/clip-1.mp4",
        "title": "My clip",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# store: absent / corrupt / round-trip
# --------------------------------------------------------------------------- #
def test_absent_file_reads_as_an_empty_queue(store) -> None:
    assert store.list() == []


def test_corrupt_file_reads_as_an_empty_queue(store) -> None:
    """A poisoned file must not crash the panel; it degrades to empty."""
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.list() == []


def test_non_list_document_reads_as_an_empty_queue(store) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"entries": []}', encoding="utf-8")
    assert store.list() == []


def test_non_dict_rows_are_dropped(store) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('["junk", 7]', encoding="utf-8")
    assert store.list() == []


def test_enqueue_round_trips_through_disk(store) -> None:
    entry = store.enqueue(_job(), now=NOW)
    assert entry["status"] == social_queue.STATUS_PENDING
    assert entry["id"]
    reread = social_queue.PublishQueueStore(store.path).list()
    assert [e["id"] for e in reread] == [entry["id"]]


# --------------------------------------------------------------------------- #
# the NO-TOKEN-AT-REST invariant
# --------------------------------------------------------------------------- #
def test_a_token_field_is_stripped_from_an_enqueued_job(store) -> None:
    """A caller that passes a token gets it DROPPED, not persisted."""
    entry = store.enqueue(
        _job(accessToken="ya29.super-secret", refreshToken="1//refresh", _injectedSocialTokens={"youtube": "t"}),
        now=NOW,
    )
    assert "accessToken" not in entry
    assert "refreshToken" not in entry
    assert social_queue.INJECTED_TOKENS_FIELD not in entry


def test_no_token_shaped_key_reaches_the_queue_file(store) -> None:
    """Structural: scan the PERSISTED BYTES, not just the returned entry."""
    store.enqueue(
        _job(accessToken="ya29.super-secret", clientSecret="GOCSPX-nope"),
        now=NOW,
    )
    raw = store.path.read_text(encoding="utf-8")
    assert "ya29.super-secret" not in raw
    assert "GOCSPX-nope" not in raw
    for row in json.loads(raw):
        for key in row:
            assert not social_queue.is_secret_field(key), key


def test_the_entry_wire_shape_is_exactly_the_allowlist(store) -> None:
    """An entry carries ONLY the documented non-secret fields.

    An allowlist (not a denylist) is what makes the no-token invariant hold for a
    field nobody has thought of yet: an unknown key cannot ride along at all.
    """
    entry = store.enqueue(_job(surpriseField="x"), now=NOW)
    assert set(entry) == set(social_queue.ENTRY_FIELDS)


# --------------------------------------------------------------------------- #
# normalization + refusals
# --------------------------------------------------------------------------- #
def test_a_blocked_platform_is_refused_and_writes_nothing(store) -> None:
    with pytest.raises(RpcError) as excinfo:
        store.enqueue(_job(platform="instagram_reels"), now=NOW)
    assert excinfo.value.code == ErrorCode.INVALID_PARAMS
    assert not store.path.exists(), "a refused enqueue must leave no file behind"


def test_an_unknown_platform_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue(_job(platform="myspace"), now=NOW)


def test_a_missing_clip_path_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue({"platform": "youtube", "title": "t"}, now=NOW)


def test_a_missing_title_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue({"platform": "youtube", "clipPath": "a.mp4"}, now=NOW)


def test_a_non_object_job_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue("nope", now=NOW)


def test_optional_fields_default_to_empty(store) -> None:
    entry = store.enqueue(_job(), now=NOW)
    assert entry["description"] == ""
    assert entry["videoId"] == ""
    assert entry["error"] == ""
    assert entry["publishAt"] is None
    assert entry["createdAt"] == NOW


def test_optional_fields_are_carried_when_supplied(store) -> None:
    entry = store.enqueue(_job(description="  hello  ", videoId="vid-7"), now=NOW)
    assert entry["description"] == "hello"
    assert entry["videoId"] == "vid-7"


def test_a_non_string_description_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue(_job(description=7), now=NOW)


def test_a_non_string_video_id_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue(_job(videoId=7), now=NOW)


# --------------------------------------------------------------------------- #
# the schedule plan is recorded ON the entry (honesty travels with the row)
# --------------------------------------------------------------------------- #
def test_an_immediate_entry_records_the_immediate_kind(store) -> None:
    entry = store.enqueue(_job(), now=NOW)
    assert entry["kind"] == social_publish.KIND_IMMEDIATE
    assert entry["requiresAppRunning"] is False


def test_a_scheduled_youtube_entry_is_held_by_the_platform(store) -> None:
    entry = store.enqueue(_job(publishAt=LATER), now=NOW)
    assert entry["kind"] == social_publish.KIND_PLATFORM
    assert entry["requiresAppRunning"] is False
    assert entry["publishAt"] == LATER


def test_a_scheduled_tiktok_entry_lands_on_the_local_queue(store) -> None:
    entry = store.enqueue(_job(platform="tiktok", publishAt=LATER), now=NOW)
    assert entry["kind"] == social_publish.KIND_LOCAL_QUEUE
    assert entry["requiresAppRunning"] is True


def test_a_past_publish_at_is_refused(store) -> None:
    with pytest.raises(RpcError):
        store.enqueue(_job(publishAt=NOW - 1), now=NOW)


# --------------------------------------------------------------------------- #
# cancel + due
# --------------------------------------------------------------------------- #
def test_cancel_marks_a_pending_entry_cancelled(store) -> None:
    entry = store.enqueue(_job(), now=NOW)
    assert store.cancel(entry["id"]) is True
    assert store.list()[0]["status"] == social_queue.STATUS_CANCELLED


def test_cancel_is_false_for_an_unknown_id(store) -> None:
    assert store.cancel("nope") is False


def test_cancel_is_false_for_an_already_cancelled_entry(store) -> None:
    """Cancel is idempotent-safe: a second call reports "nothing to do"."""
    entry = store.enqueue(_job(), now=NOW)
    store.cancel(entry["id"])
    assert store.cancel(entry["id"]) is False


def test_due_returns_only_pending_local_queue_entries_whose_time_has_come(store) -> None:
    soon = store.enqueue(_job(platform="tiktok", publishAt=NOW + 10), now=NOW)
    store.enqueue(_job(platform="tiktok", publishAt=NOW + 9999), now=NOW)
    # A platform-held schedule is the PLATFORM's job, never the local runner's.
    store.enqueue(_job(platform="youtube", publishAt=NOW + 10), now=NOW)
    due = store.due(now=NOW + 20)
    assert [e["id"] for e in due] == [soon["id"]]


def test_due_skips_a_cancelled_entry(store) -> None:
    entry = store.enqueue(_job(platform="tiktok", publishAt=NOW + 10), now=NOW)
    store.cancel(entry["id"])
    assert store.due(now=NOW + 20) == []


def test_an_immediate_entry_is_due_at_once(store) -> None:
    """No publishAt means "now", so the runner picks it up on its next sweep."""
    entry = store.enqueue(_job(platform="tiktok"), now=NOW)
    assert [e["id"] for e in store.due(now=NOW)] == [entry["id"]]


# --------------------------------------------------------------------------- #
# RPC group
# --------------------------------------------------------------------------- #
def test_register_binds_exactly_the_documented_methods(tmp_path) -> None:
    registered: dict[str, object] = {}
    social_queue.register(
        path=tmp_path / "social-queue.json",
        clock=lambda: NOW,
        register_fn=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert set(registered) == {
        "social.capabilities",
        "social.plan",
        "social.enqueue",
        "social.queue",
        "social.cancel",
    }


def test_register_defaults_to_the_real_registrar_and_clock(tmp_path) -> None:
    """The production path (no injected registrar/clock) wires the same group."""
    protocol.clear_methods()
    svc = social_queue.register(path=tmp_path / "social-queue.json")
    assert "social.capabilities" in protocol.METHODS
    # The default clock is the wall clock, so it must produce a real timestamp.
    assert svc.now() > 0


def test_capabilities_rpc_returns_the_matrix(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    out = svc.capabilities({}, _ctx())
    assert [row["id"] for row in out["platforms"]] == sorted(social_publish.CAPABILITIES)


def test_plan_rpc_previews_the_honest_plan(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    out = svc.plan({"platform": "tiktok", "publishAt": LATER}, _ctx())
    assert out["plan"]["kind"] == social_publish.KIND_LOCAL_QUEUE
    assert out["plan"]["requiresAppRunning"] is True
    assert "running" in out["plan"]["warning"].lower()


def test_plan_rpc_defaults_to_an_immediate_preview(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    out = svc.plan({"platform": "youtube"}, _ctx())
    assert out["plan"]["kind"] == social_publish.KIND_IMMEDIATE


def test_enqueue_queue_and_cancel_rpcs_round_trip(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    entry = svc.enqueue({"job": _job()}, _ctx())["entry"]
    assert [e["id"] for e in svc.queue({}, _ctx())["entries"]] == [entry["id"]]
    assert svc.cancel({"id": entry["id"]}, _ctx())["ok"] is True


def test_enqueue_rpc_requires_a_job_object(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    with pytest.raises(RpcError):
        svc.enqueue({}, _ctx())


def test_cancel_rpc_requires_an_id(tmp_path) -> None:
    svc = social_queue.register(path=tmp_path / "q.json", clock=lambda: NOW, register_fn=lambda _n, _f: None)
    with pytest.raises(RpcError):
        svc.cancel({}, _ctx())
