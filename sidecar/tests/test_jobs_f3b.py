"""F3b — sidecar reliability guards for jobs.py.

Two foundation hardenings (V1.1 Lane 0, F3b):

* :meth:`JobRegistry.rehydrate` gets a per-record guard so ONE malformed
  persisted record (a non-dict, an unknown status, a non-numeric pct) can never
  crash ALL job resumption — mirroring ``DiskJobStore.load_all``'s skip-and-warn.
* the bounded worker pool gets a per-job wall-clock watchdog that force-finishes
  a wedged handler as ERROR ("job exceeded N min and was stopped") so a stuck
  job can never starve the 2-slot pool. The timer is an injected seam so the
  deadline is exercised deterministically (no real wall-clock wait).

No heavy-ML imports — pure JobRegistry seam exercise.
"""

from __future__ import annotations

import threading

from media_studio.job_store import InMemoryJobStore
from media_studio.jobs import JobRegistry, JobStatus


# --------------------------------------------------------------------------- #
# rehydrate() per-record robustness
# --------------------------------------------------------------------------- #
def test_rehydrate_unknown_status_becomes_interrupted(emit_sinks):
    # An unrecognized stored status must NOT raise (it would crash ALL
    # resumption) — it degrades to INTERRUPTED and is persisted as such.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "frobnicated", "method": "a.x", "params": {}})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get("job-1").status is JobStatus.INTERRUPTED
    rec = next(r for r in store.load_all() if r["jobId"] == "job-1")
    assert rec["status"] == "interrupted"


def test_rehydrate_coerces_bad_pct_to_zero(emit_sinks):
    # A non-numeric pct must not crash the record — it coerces to 0.
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "pct": "not-a-number"})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get("job-1").pct == 0


def test_rehydrate_keeps_valid_pct(emit_sinks):
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "pct": 42})
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert reg.get("job-1").pct == 42


def test_rehydrate_one_bad_record_does_not_crash_the_rest(emit_sinks):
    # A non-dict record raises on ``.get`` — the per-record guard skips it
    # (log.warning + continue) so the well-formed sibling still rehydrates.
    class MixedStore:
        def load_all(self):
            return ["i-am-not-a-dict", {"jobId": "job-2", "status": "done", "method": "a", "params": {}}]

        def write(self, record):  # pragma: no cover - never written during rehydrate
            pass

        def delete(self, job_id):  # pragma: no cover - unused
            pass

    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=MixedStore())
    reg.rehydrate()
    assert reg.get("job-2") is not None
    assert len(reg.all()) == 1


# --------------------------------------------------------------------------- #
# per-job wall-clock watchdog
# --------------------------------------------------------------------------- #
class _FakeTimer:
    """A threading.Timer-shaped stub whose callback is fired by the test."""

    def __init__(self, delay: float, fn):
        self.delay = delay
        self.fn = fn
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class _TimerSpy:
    def __init__(self) -> None:
        self.timers: list[_FakeTimer] = []

    def __call__(self, delay: float, fn) -> _FakeTimer:
        timer = _FakeTimer(delay, fn)
        self.timers.append(timer)
        return timer


def _blocker(started: threading.Event, release: threading.Event):
    def handler(ctx):
        started.set()
        assert release.wait(timeout=5)
        return "released"

    return handler


def test_watchdog_force_errors_a_wedged_job_and_frees_the_slot(emit_sinks, collected):
    ep, ed = emit_sinks
    spy = _TimerSpy()
    reg = JobRegistry(ep, ed, max_workers=1, job_timeout_sec=600.0, timer_factory=spy)
    started, release = threading.Event(), threading.Event()
    reg.start(_blocker(started, release))  # job-1 occupies the only slot
    assert started.wait(5)

    ran2 = threading.Event()
    reg.start(lambda ctx: ran2.set())  # job-2 queues behind the wedged job-1
    assert reg.get("job-2").status is JobStatus.PENDING

    # the watchdog was armed for the running job at its configured deadline
    assert len(spy.timers) == 1
    assert spy.timers[0].delay == 600.0
    assert spy.timers[0].started is True

    spy.timers[0].fn()  # fire the deadline

    j1 = reg.get("job-1")
    assert j1.status is JobStatus.ERROR
    assert "exceeded" in j1.error and "stopped" in j1.error
    # the freed slot lets the queued job-2 run
    assert ran2.wait(5)
    # the wedged job emitted a job.done error payload (no silent hang)
    done_errors = [
        payload
        for kind, payload in collected
        if kind == "done" and isinstance(payload[1], dict) and "error" in payload[1]
    ]
    assert any(p[0] == "job-1" for p in done_errors)
    release.set()  # let the abandoned handler thread unwind cleanly


def test_watchdog_is_cancelled_when_a_job_finishes_in_time(emit_sinks):
    ep, ed = emit_sinks
    spy = _TimerSpy()
    reg = JobRegistry(ep, ed, job_timeout_sec=600.0, timer_factory=spy)
    job = reg.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    assert job.status is JobStatus.DONE
    # the armed timer was cancelled on the normal finish path
    assert len(spy.timers) == 1
    assert spy.timers[0].cancelled is True


def test_no_watchdog_armed_when_timeout_disabled(emit_sinks):
    ep, ed = emit_sinks
    spy = _TimerSpy()
    reg = JobRegistry(ep, ed, timer_factory=spy)  # job_timeout_sec defaults to None
    job = reg.start(lambda ctx: "ok")
    assert job.wait(timeout=5)
    assert spy.timers == []  # no timer ever created


def test_default_timer_factory_builds_a_daemon_threading_timer():
    fired: list[int] = []
    fn = lambda: fired.append(1)  # noqa: E731 - tiny callback for the assertion
    timer = JobRegistry._default_timer_factory(0.05, fn)
    assert isinstance(timer, threading.Timer)
    assert timer.interval == 0.05
    assert timer.function is fn
    assert timer.daemon is True
    timer.cancel()  # never let it fire


# --------------------------------------------------------------------------- #
# terminal-transition idempotency (the watchdog-vs-normal-finish race guard)
# --------------------------------------------------------------------------- #
def test_finish_done_is_idempotent(registry, collected):
    job = registry.create(lambda ctx: None)
    registry._finish_done(job, "first")
    registry._finish_done(job, "second")  # claim already taken -> no-op
    dones = [payload for kind, payload in collected if kind == "done"]
    assert dones == [("job-1", "first")]


def test_finish_error_is_idempotent(registry, collected):
    job = registry.create(lambda ctx: None)
    registry._finish_error(job, RuntimeError("boom"))
    registry._finish_error(job, RuntimeError("again"))  # no-op
    dones = [payload for kind, payload in collected if kind == "done"]
    assert len(dones) == 1
    assert job.status is JobStatus.ERROR


def test_finish_cancelled_is_idempotent(registry, collected):
    job = registry.create(lambda ctx: None)
    registry._finish_cancelled(job)
    registry._finish_cancelled(job)  # no-op
    assert job.status is JobStatus.CANCELLED
