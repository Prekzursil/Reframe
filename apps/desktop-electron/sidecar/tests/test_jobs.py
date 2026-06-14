"""Tests for jobs.py — lifecycle, progress emission, cooperative cancellation.

P2 (A2/A3): also covers the bounded worker pool (queued -> running, gpu
serialization), JobInfo metadata, ``job.list``, and ``job.retry`` re-dispatch
from the stored request (recorded by ``protocol.dispatch``).

No heavy-ML imports; handlers are plain Python callables that exercise the
JobContext seam (progress + cancel flag).
"""
from __future__ import annotations

import threading
import time

import pytest

from media_studio import protocol
from media_studio.jobs import (
    Job,
    JobCancelled,
    JobContext,
    JobRegistry,
    JobStatus,
)
from media_studio.protocol import ErrorCode, RpcContext, RpcError, parse_request


# -- JobStatus enum --------------------------------------------------------


def test_jobstatus_is_str_and_values_are_stable():
    # Inherits from str so it serializes straight into JSON-RPC payloads.
    assert JobStatus.RUNNING == "running"
    assert JobStatus.DONE.value == "done"
    assert {s.value for s in JobStatus} == {
        "pending",
        "running",
        "done",
        "error",
        "cancelled",
    }


# -- synchronous create/lookup --------------------------------------------


def test_create_assigns_incrementing_ids_and_pending_status(registry):
    a = registry.create(lambda ctx: None)
    b = registry.create(lambda ctx: None)
    assert a.id == "job-1"
    assert b.id == "job-2"
    assert a.status is JobStatus.PENDING
    assert registry.get("job-1") is a
    assert registry.get("nope") is None
    assert set(registry.all()) == {"job-1", "job-2"}


def test_custom_id_prefix(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, id_prefix="transcribe")
    job = reg.create(lambda ctx: None)
    assert job.id == "transcribe-1"


# -- happy path: start, progress, done ------------------------------------


def test_start_runs_handler_emits_progress_and_done(registry, collected):
    def handler(ctx: JobContext):
        ctx.progress(10, "starting")
        ctx.progress(50, "halfway")
        return {"transcript": "hello world"}

    job = registry.start(handler)
    assert job.wait(timeout=5) is True
    assert job.status is JobStatus.DONE
    assert job.pct == 100
    assert job.result == {"transcript": "hello world"}

    kinds = [k for k, _ in collected]
    assert kinds == ["progress", "progress", "done"]
    assert collected[0] == ("progress", (job.id, 10, "starting"))
    assert collected[1] == ("progress", (job.id, 50, "halfway"))
    assert collected[-1] == ("done", (job.id, {"transcript": "hello world"}))


def test_done_event_set_and_finished_flag(registry):
    job = registry.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    assert job.finished is True
    assert job.snapshot() == {"status": "done", "pct": 100}


# -- progress clamping ----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [(-5, 0), (0, 0), (33.4, 33), (33.6, 34), (100, 100), (250, 100)],
)
def test_progress_pct_is_clamped_and_rounded(registry, collected, raw, expected):
    registry.start(lambda ctx: ctx.progress(raw, "p")).wait(timeout=5)
    progress_events = [p for k, p in collected if k == "progress"]
    assert progress_events[0][1] == expected


def test_job_pct_mirror_updates_on_progress(registry):
    seen = []

    def handler(ctx: JobContext):
        ctx.progress(25, "")
        seen.append(registry.get(ctx.job_id).pct)
        ctx.progress(75, "")
        seen.append(registry.get(ctx.job_id).pct)

    registry.start(handler).wait(timeout=5)
    assert seen == [25, 75]


# -- error handling --------------------------------------------------------


def test_handler_exception_emits_job_done_with_error(registry, collected):
    # Phase-0 spine finding: a failed job that emits NOTHING looks like an
    # infinite hang to every stdio client (UI panels wait on job.done forever).
    # Contract: failure emits job.done with an {"error": {...}} payload.
    def boom(ctx: JobContext):
        raise RuntimeError("kaboom")

    job = registry.start(boom)
    assert job.wait(timeout=5)
    assert job.status is JobStatus.ERROR
    assert job.error == "kaboom"
    assert job.result is None

    dones = [(jid, payload) for k, (jid, payload) in collected if k == "done"]
    assert len(dones) == 1
    jid, payload = dones[0]
    assert jid == job.id
    assert payload["error"]["message"] == "kaboom"
    assert payload["error"]["type"] == "RuntimeError"


# -- cooperative cancellation ---------------------------------------------


def test_cancel_sets_flag_and_handler_polls_it(registry, collected):
    started = threading.Event()
    release = threading.Event()

    def handler(ctx: JobContext):
        started.set()
        # Cooperative loop: poll the flag until cancelled.
        while not ctx.cancelled:
            if not release.wait(timeout=0.01):
                continue
        return "should-not-reach"

    job = registry.start(handler)
    assert started.wait(timeout=5)
    assert registry.cancel(job.id) is True
    release.set()
    assert job.wait(timeout=5)
    assert job.status is JobStatus.CANCELLED
    # Cancelled jobs do not emit job.done.
    assert all(k != "done" for k, _ in collected)


def test_cancel_via_raise_if_cancelled(registry):
    started = threading.Event()

    def handler(ctx: JobContext):
        started.set()
        while True:
            ctx.raise_if_cancelled()
            time.sleep(0.005)

    job = registry.start(handler)
    assert started.wait(timeout=5)
    registry.cancel(job.id)
    assert job.wait(timeout=5)
    assert job.status is JobStatus.CANCELLED


def test_cancel_before_run_short_circuits(emit_sinks):
    # A job cancelled before its thread observes the flag still ends CANCELLED.
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)
    gate = threading.Event()

    def handler(ctx: JobContext):
        gate.wait(timeout=5)  # hold until we've requested cancel
        ctx.raise_if_cancelled()
        return "nope"

    job = reg.create(handler)
    job.request_cancel()  # cancel while still PENDING
    reg._spawn(job)
    gate.set()
    assert job.wait(timeout=5)
    assert job.status is JobStatus.CANCELLED


def test_cancel_unknown_job_returns_false(registry):
    assert registry.cancel("ghost") is False


def test_cancel_finished_job_is_noop_but_known(registry):
    job = registry.start(lambda ctx: "done")
    assert job.wait(timeout=5)
    # Known id -> True, but status stays DONE (no flag effect after finish).
    assert registry.cancel(job.id) is True
    assert job.status is JobStatus.DONE


def test_handler_returning_after_observing_cancel_marks_cancelled(registry, collected):
    started = threading.Event()

    def handler(ctx: JobContext):
        started.set()
        while not ctx.cancelled:
            time.sleep(0.005)
        return "graceful-exit"  # returns instead of raising

    job = registry.start(handler)
    assert started.wait(timeout=5)
    registry.cancel(job.id)
    assert job.wait(timeout=5)
    # Even though the handler returned normally, the observed cancel wins.
    assert job.status is JobStatus.CANCELLED
    assert all(k != "done" for k, _ in collected)


# -- JobContext direct unit ------------------------------------------------


def test_jobcontext_raise_if_cancelled_raises():
    ev = threading.Event()
    seen = []
    ctx = JobContext(
        job_id="x", _cancel_event=ev, _emit_progress=lambda *a: seen.append(a)
    )
    ctx.progress(42, "hi")
    assert seen == [("x", 42, "hi")]
    ctx.raise_if_cancelled()  # not set -> no raise
    ev.set()
    with pytest.raises(JobCancelled):
        ctx.raise_if_cancelled()


# -- Job dataclass direct unit ---------------------------------------------


def test_job_request_cancel_and_snapshot():
    job = Job(id="j1", handler=lambda ctx: None)
    assert job.cancel_requested is False
    assert job.snapshot() == {"status": "pending", "pct": 0}
    job.request_cancel()
    assert job.cancel_requested is True


def test_registry_join_waits_for_all(registry):
    def slow(ctx: JobContext):
        time.sleep(0.02)
        return "ok"

    jobs = [registry.start(slow) for _ in range(3)]
    registry.join(timeout=5)
    assert all(j.finished for j in jobs)


# ===========================================================================
# P2 (A2/A3) — metadata, JobInfo, worker pool, job.list, job.retry
# ===========================================================================


def _blocker(started: threading.Event, release: threading.Event):
    """A handler that signals it is running, then blocks until released."""

    def handler(ctx: JobContext):
        started.set()
        assert release.wait(timeout=5)
        return "released"

    return handler


def _rpc_ctx(registry: JobRegistry) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=registry)


def _dispatch(method: str, params, ctx: RpcContext):
    req = parse_request(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    return protocol.dispatch(req, ctx)


# -- metadata + JobInfo shape ----------------------------------------------


def test_start_accepts_metadata_and_info_has_jobinfo_shape(registry):
    job = registry.start(
        lambda ctx: "ok",
        feature="transcribe",
        label="Transcribe talk.mp4",
        videoId="vid-1",
    )
    assert job.wait(timeout=5)
    # A3 JobInfo: {jobId, feature, label, videoId?, status, pct}
    assert job.info() == {
        "jobId": job.id,
        "feature": "transcribe",
        "label": "Transcribe talk.mp4",
        "videoId": "vid-1",
        "status": "done",
        "pct": 100,
    }


def test_start_without_metadata_keeps_working_with_defaults(registry):
    # The P1 call shape — no kwargs — must keep working (589 tests ride on it).
    job = registry.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    info = job.info()
    assert info["feature"] == ""
    assert info["label"] == ""
    assert "videoId" not in info  # omitted (not null) when unknown
    # job.status's snapshot shape is unchanged by the metadata upgrade.
    assert job.snapshot() == {"status": "done", "pct": 100}


def test_info_maps_pending_to_queued(registry):
    # A3's wire status set has "queued", not "pending".
    job = registry.create(lambda ctx: None)
    assert job.status is JobStatus.PENDING
    assert job.info()["status"] == "queued"


# -- worker pool: queued -> running under a full pool -----------------------


def test_third_job_queues_when_default_pool_of_two_is_full(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)  # default max_workers=2
    s1, s2 = threading.Event(), threading.Event()
    release = threading.Event()

    a = reg.start(_blocker(s1, release))
    b = reg.start(_blocker(s2, release))
    assert s1.wait(timeout=5) and s2.wait(timeout=5)  # both slots busy

    third_ran = threading.Event()

    def third(ctx: JobContext):
        third_ran.set()
        return "third"

    c = reg.start(third)
    # Slot reservation is synchronous in start(), so this is deterministic:
    # with the pool full, the third job is QUEUED, not running.
    assert c.status is JobStatus.PENDING
    assert c.info()["status"] == "queued"
    assert not third_ran.is_set()

    release.set()  # free the pool -> the queued job transitions to running
    assert c.wait(timeout=5)
    assert third_ran.is_set()
    assert c.status is JobStatus.DONE
    assert a.wait(timeout=5) and b.wait(timeout=5)


def test_pool_runs_two_jobs_concurrently_by_default(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)
    s1, s2 = threading.Event(), threading.Event()
    release = threading.Event()
    reg.start(_blocker(s1, release))
    reg.start(_blocker(s2, release))
    # Both must reach RUNNING while neither has finished -> concurrency >= 2.
    assert s1.wait(timeout=5)
    assert s2.wait(timeout=5)
    release.set()
    reg.join(timeout=5)


def test_gpu_jobs_serialize_to_one_but_dont_block_cpu_jobs(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed)  # 2 general slots, 1 gpu slot
    g1_started = threading.Event()
    release_g1 = threading.Event()

    g1 = reg.start(_blocker(g1_started, release_g1), gpu=True)
    assert g1_started.wait(timeout=5)

    g2 = reg.start(lambda ctx: "gpu-2", gpu=True)
    # A general slot is free, but the single gpu slot is busy -> g2 queues.
    assert g2.status is JobStatus.PENDING
    assert g2.info()["status"] == "queued"

    # A non-gpu job skips ahead into the free general slot.
    cpu = reg.start(lambda ctx: "cpu")
    assert cpu.wait(timeout=5)
    assert cpu.status is JobStatus.DONE
    assert g2.status is JobStatus.PENDING  # still gpu-blocked

    release_g1.set()  # gpu slot frees -> g2 runs
    assert g2.wait(timeout=5)
    assert g2.status is JobStatus.DONE
    assert g1.wait(timeout=5)


def test_cancel_queued_job_finishes_cancelled_without_running(emit_sinks, collected):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, max_workers=1)
    started = threading.Event()
    release = threading.Event()
    blocker = reg.start(_blocker(started, release))
    assert started.wait(timeout=5)

    ran = threading.Event()
    queued = reg.start(lambda ctx: ran.set())
    assert queued.info()["status"] == "queued"
    assert reg.cancel(queued.id) is True
    # Cancelled while queued: terminal immediately, never ran, no job.done.
    assert queued.wait(timeout=5)
    assert queued.status is JobStatus.CANCELLED
    assert not ran.is_set()
    assert all(k != "done" for k, _ in collected)

    release.set()
    assert blocker.wait(timeout=5)
    ran.set()  # avoid dangling event in case of failure ordering


def test_join_covers_jobs_still_waiting_in_the_queue(emit_sinks):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, max_workers=1)

    def slow(ctx: JobContext):
        time.sleep(0.01)
        return "ok"

    jobs = [reg.start(slow) for _ in range(3)]  # 2 of these queue behind job 1
    reg.join(timeout=5)
    assert all(j.finished for j in jobs)


# -- stored request (registry side) -----------------------------------------


def test_record_request_stores_and_backfills_metadata(registry):
    job = registry.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    registry.record_request(job.id, "transcribe.start", {"videoId": "v1"})
    assert registry.get_request(job.id) == {
        "method": "transcribe.start",
        "params": {"videoId": "v1"},
    }
    # Default metadata is backfilled from the originating request.
    info = job.info()
    assert info["feature"] == "transcribe"
    assert info["label"] == "transcribe.start"
    assert info["videoId"] == "v1"


def test_record_request_is_first_write_wins_and_keeps_explicit_metadata(registry):
    job = registry.start(
        lambda ctx: "ok", feature="convert", label="Convert clip", videoId="v7"
    )
    assert job.wait(timeout=5)
    registry.record_request(job.id, "convert.start", {"videoId": "v7"})
    registry.record_request(job.id, "job.retry", {"jobId": job.id})  # ignored
    assert registry.get_request(job.id)["method"] == "convert.start"
    # Explicit metadata is never overwritten by the backfill.
    info = job.info()
    assert info["feature"] == "convert"
    assert info["label"] == "Convert clip"
    assert info["videoId"] == "v7"


def test_get_request_unknown_or_unrecorded_returns_none(registry):
    job = registry.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    assert registry.get_request(job.id) is None
    assert registry.get_request("ghost") is None


def test_list_info_is_most_recent_first_and_bounded_to_100(registry):
    jobs = [registry.create(lambda ctx: None) for _ in range(120)]
    listed = registry.list_info()
    assert len(listed) == 100
    assert listed[0]["jobId"] == jobs[-1].id  # newest first
    assert listed[-1]["jobId"] == jobs[-100].id
    assert [j["status"] for j in listed] == ["queued"] * 100


# -- protocol.dispatch records job-returning requests ------------------------


def test_dispatch_records_method_and_params_for_job_returning_handlers(registry):
    ctx = _rpc_ctx(registry)

    @protocol.method("demo.jobby")
    def _jobby(params, c):
        job = c.jobs.start(lambda jctx: {"echo": params})
        return {"jobId": job.id}

    out = _dispatch("demo.jobby", {"videoId": "v3", "x": 1}, ctx)
    registry.join(timeout=5)
    assert registry.get_request(out["jobId"]) == {
        "method": "demo.jobby",
        "params": {"videoId": "v3", "x": 1},
    }
    # Backfill: the job's JobInfo metadata derives from the recorded request.
    info = registry.get(out["jobId"]).info()
    assert info["feature"] == "demo"
    assert info["label"] == "demo.jobby"
    assert info["videoId"] == "v3"


def test_dispatch_does_not_record_non_job_results(registry):
    ctx = _rpc_ctx(registry)

    @protocol.method("demo.direct")
    def _direct(params, c):
        return {"ok": True}

    _dispatch("demo.direct", {"videoId": "v3"}, ctx)
    assert all(j.request is None for j in registry.all().values())


def test_dispatch_tolerates_registry_without_record_request():
    class BareJobs:
        pass

    ctx = RpcContext(emit_notification=lambda obj: None, jobs=BareJobs())

    @protocol.method("demo.bare")
    def _bare(params, c):
        return {"jobId": "job-1"}

    assert _dispatch("demo.bare", {}, ctx) == {"jobId": "job-1"}  # no crash


# -- job.list built-in -------------------------------------------------------


def test_job_list_builtin_returns_jobinfo_list_newest_first(registry):
    ctx = _rpc_ctx(registry)
    a = registry.start(lambda c: "a", feature="convert", label="A")
    assert a.wait(timeout=5)
    b = registry.start(lambda c: "b", feature="tts", label="B", videoId="v1")
    assert b.wait(timeout=5)

    out = _dispatch("job.list", {}, ctx)
    assert set(out) == {"jobs"}  # A2: job.list() -> {jobs:[JobInfo]}
    assert [j["jobId"] for j in out["jobs"]] == [b.id, a.id]
    assert out["jobs"][0] == {
        "jobId": b.id,
        "feature": "tts",
        "label": "B",
        "videoId": "v1",
        "status": "done",
        "pct": 100,
    }


def test_job_list_requires_registry():
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        _dispatch("job.list", {}, ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


# -- job.retry built-in ------------------------------------------------------


def test_job_retry_redispatches_stored_params_as_new_job(registry):
    ctx = _rpc_ctx(registry)
    calls = []

    @protocol.method("demo.retryable")
    def _retryable(params, c):
        calls.append(dict(params))
        job = c.jobs.start(lambda jctx: {"got": params})
        return {"jobId": job.id}

    first = _dispatch("demo.retryable", {"videoId": "v9", "opt": 2}, ctx)
    registry.join(timeout=5)

    out = _dispatch("job.retry", {"jobId": first["jobId"]}, ctx)
    registry.join(timeout=5)

    assert out["jobId"] != first["jobId"]  # a NEW job (A2)
    assert calls == [{"videoId": "v9", "opt": 2}] * 2  # same stored params
    # The retried job recorded the ORIGINAL request (not "job.retry"), so it is
    # itself retryable.
    assert registry.get_request(out["jobId"]) == {
        "method": "demo.retryable",
        "params": {"videoId": "v9", "opt": 2},
    }
    again = _dispatch("job.retry", {"jobId": out["jobId"]}, ctx)
    registry.join(timeout=5)
    assert len(calls) == 3
    assert again["jobId"] not in {first["jobId"], out["jobId"]}


def test_job_retry_unknown_job_raises_invalid_params(registry):
    ctx = _rpc_ctx(registry)
    with pytest.raises(RpcError) as ei:
        _dispatch("job.retry", {"jobId": "ghost"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_job_retry_without_stored_request_raises_invalid_params(registry):
    ctx = _rpc_ctx(registry)
    job = registry.start(lambda c: "ok")  # direct start: nothing recorded
    assert job.wait(timeout=5)
    with pytest.raises(RpcError) as ei:
        _dispatch("job.retry", {"jobId": job.id}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_job_retry_requires_jobid_and_registry(registry):
    with pytest.raises(RpcError) as ei:
        _dispatch("job.retry", {}, _rpc_ctx(registry))
    assert ei.value.code == ErrorCode.INVALID_PARAMS
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        _dispatch("job.retry", {"jobId": "j"}, ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_job_retry_propagates_handler_without_job_as_internal_error(registry):
    ctx = _rpc_ctx(registry)
    flip = {"first": True}

    @protocol.method("demo.flaky")
    def _flaky(params, c):
        if flip["first"]:
            flip["first"] = False
            job = c.jobs.start(lambda jctx: "ok")
            return {"jobId": job.id}
        return {"ok": True}  # second call no longer returns a job

    first = _dispatch("demo.flaky", {}, ctx)
    registry.join(timeout=5)
    with pytest.raises(RpcError) as ei:
        _dispatch("job.retry", {"jobId": first["jobId"]}, ctx)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR
