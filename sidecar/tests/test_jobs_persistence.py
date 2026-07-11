"""WU-6: JobRegistry write-through + rehydrate + INTERRUPTED status.

These tests pin the persistence seam introduced in WU-6: the registry
writes a job record through an injected :class:`JobStore` on create, on the
chosen ``record_request`` path, and on each of the four status transitions
(routed through one ``_set_status`` choke-point); and on startup ``rehydrate``
re-reads the store, marking non-terminal stored jobs ``INTERRUPTED`` while
keeping terminal statuses verbatim — never auto-spawning anything.

Heavy-ML-free: handlers are plain callables; the store is the WU-5
:class:`InMemoryJobStore`.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from media_studio.job_store import InMemoryJobStore
from media_studio.jobs import Job, JobRegistry, JobStatus


@pytest.fixture()
def store() -> InMemoryJobStore:
    return InMemoryJobStore()


@pytest.fixture()
def reg(emit_sinks, store) -> JobRegistry:
    ep, ed = emit_sinks
    return JobRegistry(emit_progress=ep, emit_done=ed, store=store)


# -- INTERRUPTED status / contract -----------------------------------------


def test_jobstatus_value_set_is_exactly_six_with_interrupted():
    # WU-6 widens the wire status set from five to six (adds "interrupted").
    assert {s.value for s in JobStatus} == {
        "pending",
        "running",
        "done",
        "error",
        "cancelled",
        "interrupted",
    }
    assert JobStatus.INTERRUPTED.value == "interrupted"


def test_interrupted_is_a_real_wire_value_in_info():
    # Unlike PENDING (mapped to "queued"), INTERRUPTED emits unchanged.
    job = Job(id="job-1", handler=lambda ctx: None, status=JobStatus.INTERRUPTED)
    assert job.info()["status"] == "interrupted"
    assert job.snapshot()["status"] == "interrupted"


# -- write-through ----------------------------------------------------------


def test_create_writes_through_to_store(reg, store):
    job = reg.create(lambda ctx: None, feature="transcribe", label="t", videoId="v1")
    records = store.load_all()
    assert len(records) == 1
    rec = records[0]
    assert rec["jobId"] == job.id
    assert rec["status"] == "queued"  # PENDING maps to the wire "queued"
    assert rec["feature"] == "transcribe"
    assert rec["videoId"] == "v1"


def test_record_request_writes_through_method_and_params(reg, store):
    job = reg.create(lambda ctx: None)
    reg.record_request(job.id, "transcribe.start", {"videoId": "v9"})
    rec = next(r for r in store.load_all() if r["jobId"] == job.id)
    assert rec["method"] == "transcribe.start"
    assert rec["params"] == {"videoId": "v9"}


def test_each_status_transition_writes_through_exactly_once(emit_sinks):
    # One store.write per transition (the choke-point routes all four sinks).
    writes: list[tuple[str, str]] = []

    class CountingStore:
        def write(self, record):
            writes.append((record["jobId"], record["status"]))

        def load_all(self):
            return []

        def delete(self, job_id):
            pass

    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=CountingStore())

    # DONE transition.
    done = reg.start(lambda ctx: "ok")
    done.wait(2.0)
    # ERROR transition.
    err = reg.start(lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
    err.wait(2.0)
    reg.join(2.0)

    done_writes = [s for (jid, s) in writes if jid == done.id]
    err_writes = [s for (jid, s) in writes if jid == err.id]
    # create -> running -> done  (3 writes, exactly one "running" + one "done")
    assert done_writes.count("running") == 1
    assert done_writes.count("done") == 1
    # create -> running -> error
    assert err_writes.count("running") == 1
    assert err_writes.count("error") == 1


def test_cancelled_transition_writes_through(emit_sinks, store):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store, max_workers=1)
    started = threading.Event()
    release = threading.Event()

    def slow(ctx):
        started.set()
        release.wait(2.0)
        ctx.raise_if_cancelled()

    job = reg.start(slow)
    started.wait(2.0)
    reg.cancel(job.id)
    release.set()
    reg.join(2.0)
    rec = next(r for r in store.load_all() if r["jobId"] == job.id)
    assert rec["status"] == "cancelled"


def test_no_store_is_in_memory_noop(emit_sinks):
    # Back-compat: default store=None means zero persistence side effects.
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)  # no store
    job = reg.start(lambda ctx: "ok")
    job.wait(2.0)
    reg.join(2.0)
    assert job.status is JobStatus.DONE  # ran fine without a store


# -- rehydrate --------------------------------------------------------------


def test_rehydrate_marks_non_terminal_interrupted_and_keeps_terminal(emit_sinks):
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x", "params": {}})
    store.write({"jobId": "job-2", "status": "pending", "method": "b.y", "params": {}})
    store.write({"jobId": "job-3", "status": "done", "method": "c.z", "params": {}})
    store.write({"jobId": "job-4", "status": "error", "method": "d.w", "params": {}})
    store.write({"jobId": "job-5", "status": "cancelled", "method": "e.v", "params": {}})

    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()

    assert reg.get("job-1").status is JobStatus.INTERRUPTED
    assert reg.get("job-2").status is JobStatus.INTERRUPTED
    assert reg.get("job-3").status is JobStatus.DONE
    assert reg.get("job-4").status is JobStatus.ERROR
    assert reg.get("job-5").status is JobStatus.CANCELLED


def test_rehydrate_restores_request_for_retry(emit_sinks):
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "transcribe.start", "params": {"videoId": "v3"}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get_request("job-1") == {"method": "transcribe.start", "params": {"videoId": "v3"}}


def test_rehydrate_restores_metadata(emit_sinks):
    store = InMemoryJobStore()
    store.write(
        {
            "jobId": "job-7",
            "status": "running",
            "feature": "convert",
            "label": "Convert clip",
            "videoId": "v8",
            "method": "convert.start",
            "params": {"videoId": "v8"},
        }
    )
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    info = reg.get("job-7").info()
    assert info["feature"] == "convert"
    assert info["label"] == "Convert clip"
    assert info["videoId"] == "v8"


def test_rehydrate_does_not_autospawn(emit_sinks):
    # §5 no-silent-spend: a rehydrated interrupted job NEVER runs on rehydrate.
    ran = threading.Event()
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    # Replace the handler the shell would run with a tripwire — it must NOT fire.
    reg.rehydrate(handler=lambda ctx: ran.set())
    reg.join(0.2)
    assert not ran.is_set()
    assert reg._running_count == 0  # pool never spun up


def test_rehydrate_writes_back_interrupted_status(emit_sinks):
    # The interrupted re-mark is persisted so a second restart stays consistent.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    rec = next(r for r in store.load_all() if r["jobId"] == "job-1")
    assert rec["status"] == "interrupted"


def _done_emits(collected) -> list[tuple[str, Any]]:
    """Filter the recording sink down to ``(job_id, result)`` for done emits."""
    return [payload for (kind, payload) in collected if kind == "done"]


def test_rehydrate_emits_terminal_job_done_for_interrupted(collected, emit_sinks):
    # A job left mid-flight (running/pending/queued) when the process exited is
    # rehydrated INTERRUPTED — and MUST also emit a terminal job.done carrying a
    # JobInterrupted error, or a renderer still holding its {jobId} (a long-job
    # panel spinning on job.progress after a sidecar crash+restart) waits on
    # job.done forever. Terminal records emit nothing.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x", "params": {}})
    store.write({"jobId": "job-2", "status": "pending", "method": "b.y", "params": {}})
    store.write({"jobId": "job-3", "status": "done", "method": "c.z", "params": {}})
    store.write({"jobId": "job-4", "status": "error", "method": "d.w", "params": {}})
    store.write({"jobId": "job-5", "status": "cancelled", "method": "e.v", "params": {}})

    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()

    emits = _done_emits(collected)
    # Exactly the two non-terminal jobs notified (id-ascending order), each with
    # the frozen A3 error shape {error:{message,type}} and type "JobInterrupted".
    assert [job_id for (job_id, _result) in emits] == ["job-1", "job-2"]
    for _job_id, result in emits:
        assert result == {"error": {"message": "job interrupted by restart", "type": "JobInterrupted"}}
    # The status re-mark is unchanged: still INTERRUPTED (resumable via job.retry),
    # NOT flipped to a terminal ERROR by the notification.
    assert reg.get("job-1").status is JobStatus.INTERRUPTED
    assert reg.get("job-2").status is JobStatus.INTERRUPTED


def test_rehydrate_emits_nothing_when_all_terminal(collected, emit_sinks):
    # No mid-flight jobs -> no synthetic job.done notifications at all.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "done", "method": "a.x", "params": {}})
    store.write({"jobId": "job-2", "status": "cancelled", "method": "b.y", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert _done_emits(collected) == []


def test_rehydrate_emits_job_done_for_unknown_status(collected, emit_sinks):
    # An out-of-vocabulary status degrades to INTERRUPTED (F3b) and is notified
    # too, so a client tracking such a job never hangs either.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "garbage", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert _done_emits(collected) == [
        ("job-1", {"error": {"message": "job interrupted by restart", "type": "JobInterrupted"}})
    ]


def test_rehydrate_terminal_not_rewritten(emit_sinks):
    # Terminal records keep their status and are not needlessly re-written.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "done", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    rec = next(r for r in store.load_all() if r["jobId"] == "job-1")
    assert rec["status"] == "done"


def test_rehydrate_skips_records_without_jobid(emit_sinks):
    # A malformed record (no jobId) is skipped, not fatal.
    class BadStore:
        def load_all(self):
            return [{"status": "running"}, {"jobId": "job-9", "status": "done", "method": "a", "params": {}}]

        def write(self, record):
            pass

        def delete(self, job_id):
            pass

    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=BadStore())
    reg.rehydrate()
    assert reg.get("job-9") is not None
    assert len(reg.all()) == 1


def test_rehydrate_record_without_method_has_no_request(emit_sinks):
    # A record missing "method" rehydrates a shell with no stored request
    # (job.retry has nothing to re-dispatch — get_request returns None).
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running"})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get("job-1").status is JobStatus.INTERRUPTED
    assert reg.get_request("job-1") is None


def test_rehydrate_method_without_params_defaults_to_empty(emit_sinks):
    # A record with a method but no params rehydrates with params == {}.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x"})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get_request("job-1") == {"method": "a.x", "params": {}}


def test_rehydrate_non_numeric_id_does_not_advance_counter(emit_sinks):
    # An id whose suffix is not a number is tolerated; the counter is unmoved.
    store = InMemoryJobStore()
    store.write({"jobId": "custom-job", "status": "done", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get("custom-job") is not None
    fresh = reg.create(lambda ctx: None)
    assert fresh.id == "job-1"  # counter never advanced past the non-numeric id


def test_rehydrate_without_store_is_noop(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)  # no store
    reg.rehydrate()  # must not raise
    assert reg.all() == {}


def test_rehydrate_counter_skips_past_existing_ids(emit_sinks):
    # New jobs created after rehydrate must not collide with rehydrated ids.
    store = InMemoryJobStore()
    store.write({"jobId": "job-5", "status": "done", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    fresh = reg.create(lambda ctx: None)
    assert fresh.id != "job-5"
    assert int(fresh.id.split("-")[1]) > 5


# -- record_request x rehydrate guard interaction --------------------------


def test_record_request_after_rehydrate_does_not_clobber_or_rewrite(emit_sinks):
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "transcribe.start", "params": {"videoId": "v3"}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    # First-write-wins guard: a rehydrated job already has request set, so a
    # later record_request must NOT overwrite the stored {method, params}.
    reg.record_request("job-1", "job.retry", {"jobId": "job-1"})
    assert reg.get_request("job-1") == {"method": "transcribe.start", "params": {"videoId": "v3"}}
    # A genuinely new job still records fine through the same path.
    new = reg.create(lambda ctx: None)
    reg.record_request(new.id, "convert.start", {"videoId": "v2"})
    assert reg.get_request(new.id) == {"method": "convert.start", "params": {"videoId": "v2"}}
