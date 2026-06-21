"""Job lifecycle: Job, JobStatus, progress emit, cooperative cancellation, JobRegistry.

Pure-logic, dependency-free (only stdlib + util). Long-running handlers run on
worker threads; this module gives each handler a cooperative cancel flag it must
poll, plus a progress-emit callback that fans out ``job.progress`` notifications.

P2 (ADDENDUM A2/A3) additions — all additive, the P1 surface is unchanged:

* jobs carry metadata (``feature`` / ``label`` / ``videoId``) surfaced as a
  JobInfo dict via :meth:`Job.info` (the ``job.list`` payload);
* the registry is a **bounded worker pool** (default 2 concurrent; gpu-tagged
  jobs serialized to 1). Jobs wait QUEUED in FIFO order and start the moment a
  slot frees — ``start()`` with a free slot spawns immediately, so direct
  ``registry.start(handler)`` usage behaves exactly as before;
* the dispatch layer records each job's originating request (method + params)
  via :meth:`JobRegistry.record_request`, enabling ``job.retry`` to re-dispatch
  the stored request as a NEW job.

See CONTRACTS.md §2 (job.progress / job.done notifications), §3 (Job) and the
P2 ADDENDUM A2 (job.list / job.retry) + A3 (JobInfo).
"""

from __future__ import annotations

import copy
import enum
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .job_store import JobRecord, JobStore
from .util import clamp_pct, get_logger

log = get_logger("media_studio.jobs")

# Stored statuses that are NOT terminal — a job left in one of these when the
# process exited was mid-flight and is rehydrated as INTERRUPTED (WU-6).
_NON_TERMINAL_WIRE_STATUSES = frozenset({"pending", "running", "queued"})

# A progress sink: receives the jobId, an integer pct (0..100), and a message.
ProgressEmit = Callable[[str, int, str], None]
# A "job done" sink: receives the jobId and the handler's result payload.
DoneEmit = Callable[[str, Any], None]
# A job handler: given a JobContext, does the work and returns a result payload.
JobHandler = Callable[["JobContext"], Any]


class JobStatus(enum.StrEnum):
    """Lifecycle states for a job.

    Inherits from ``str`` so the value serializes directly into JSON-RPC
    payloads (``job.status`` returns ``{"status", "pct"}``) without a custom
    encoder.

    CONTRACT-NOTE (A3): JobInfo's wire status set is "queued"|"running"|"done"|
    "error"|"cancelled" plus (WU-6) "interrupted". A pool-waiting job is
    internally PENDING ("pending") and is *mapped* to "queued" in
    :meth:`Job.info`; we do not add a QUEUED member because the P1
    ``job.status`` surface (and its tests) pin "pending" as the pre-run value.

    WU-6 widens the value set to SIX by adding INTERRUPTED ("interrupted") —
    the status given on startup to a job that was ``pending``/``running`` when
    the process last exited (persisted via the injected JobStore and rehydrated
    here). Unlike PENDING, INTERRUPTED is a REAL wire value: :meth:`Job.info`
    emits it unchanged (no mapping), and resumable-job UI keys off it.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class JobCancelled(Exception):
    """Raised by ``JobContext.raise_if_cancelled`` to unwind a cancelled handler.

    Handlers may either poll ``ctx.cancelled`` and return early, or call
    ``ctx.raise_if_cancelled()`` at checkpoints to bail out via this exception.
    """


@dataclass
class JobContext:
    """Handed to a running handler: report progress + observe cancellation.

    The handler is expected to poll ``cancelled`` (or call ``raise_if_cancelled``)
    at safe checkpoints and to call ``progress(pct, message)`` as it advances.
    """

    job_id: str
    _cancel_event: threading.Event
    _emit_progress: ProgressEmit

    @property
    def cancelled(self) -> bool:
        """True once cancellation has been requested for this job."""
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        """Raise :class:`JobCancelled` if cancellation has been requested."""
        if self._cancel_event.is_set():
            raise JobCancelled(self.job_id)

    def progress(self, pct: float, message: str = "") -> None:
        """Emit a ``job.progress`` notification (pct clamped to 0..100)."""
        self._emit_progress(self.job_id, clamp_pct(pct), message)


@dataclass
class Job:
    """A unit of long-running work tracked by the registry.

    Fields mirror what the IPC surface exposes: ``job.status`` returns
    ``status`` + ``pct``; ``job.list`` returns :meth:`info` (JobInfo, A3); the
    terminal result/error are kept for ``job.done`` relay and for synchronous
    callers that wait on the job. ``request`` holds the originating RPC request
    (``{"method", "params"}``) once the dispatch layer records it (the
    ``job.retry`` source).
    """

    id: str
    handler: JobHandler
    status: JobStatus = JobStatus.PENDING
    pct: int = 0
    result: Any = None
    error: str | None = None
    # -- P2 metadata (A3 JobInfo) -------------------------------------------
    feature: str = ""
    label: str = ""
    video_id: str | None = None
    # CONTRACT-NOTE: "gpu-tagged jobs serialized to 1" needs a tag; A2/A3 name
    # none, so the tag is a start()/create() kwarg + this internal field (it is
    # NOT part of the JobInfo wire shape).
    gpu: bool = False
    request: dict[str, Any] | None = field(default=None, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _done_event: threading.Event = field(default_factory=threading.Event, repr=False)
    # Pool bookkeeping: _scheduled = handed to the pool (queued or spawned);
    # _slot_held = currently counted against the pool's concurrency limits.
    _scheduled: bool = field(default=False, repr=False)
    _slot_held: bool = field(default=False, repr=False)

    @property
    def cancel_requested(self) -> bool:
        """True once cancellation has been requested (flag set)."""
        return self._cancel_event.is_set()

    @property
    def finished(self) -> bool:
        """True once the job reached a terminal state (done/error/cancelled)."""
        return self.status in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED)

    def request_cancel(self) -> None:
        """Set the cooperative cancel flag. The handler must observe it."""
        self._cancel_event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the job finishes (or ``timeout`` elapses). Returns finished?"""
        return self._done_event.wait(timeout)

    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable view for ``job.status`` (``{status, pct}``)."""
        return {"status": self.status.value, "pct": self.pct}

    def info(self) -> dict[str, Any]:
        """JSON-serializable **JobInfo** (A3) for ``job.list``.

        Shape: ``{jobId, feature, label, videoId?, status, pct}`` — ``videoId``
        is omitted (not null) when unknown; a not-yet-running job reads
        ``"queued"`` (the A3 wire name for the internal PENDING state).
        """
        status = "queued" if self.status is JobStatus.PENDING else self.status.value
        info: dict[str, Any] = {
            "jobId": self.id,
            "feature": self.feature,
            "label": self.label,
            "status": status,
            "pct": self.pct,
        }
        if self.video_id is not None:
            info["videoId"] = self.video_id
        return info


class JobRegistry:
    """Creates, queues, runs, tracks, retries, and cancels jobs.

    Jobs run on daemon worker threads drawn from a bounded pool: at most
    ``max_workers`` (default 2) jobs run concurrently, and at most
    ``max_gpu_workers`` (default 1) of those may be gpu-tagged — gpu jobs
    serialize among themselves while still counting against the general pool.
    Excess jobs wait QUEUED (FIFO; a gpu job blocked on the gpu slot does not
    starve later non-gpu jobs). Progress + completion are pushed through the
    ``emit_progress`` / ``emit_done`` sinks supplied at construction (the RPC
    server wires these to stdout notifications). Thread-safe.
    """

    def __init__(
        self,
        emit_progress: ProgressEmit,
        emit_done: DoneEmit,
        *,
        id_prefix: str = "job",
        max_workers: int = 2,
        max_gpu_workers: int = 1,
        store: JobStore | None = None,
    ) -> None:
        self._emit_progress = emit_progress
        self._emit_done = emit_done
        self._id_prefix = id_prefix
        # WU-6: optional persistence seam. When ``None`` the registry is purely
        # in-memory (P1/P2 behavior) so every existing caller keeps working;
        # when supplied, every create / record_request / status transition is
        # written through, and :meth:`rehydrate` reloads it at startup.
        self._store = store
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._lock = threading.RLock()
        # -- worker pool state ----------------------------------------------
        self._max_workers = max(1, int(max_workers))
        self._max_gpu_workers = max(1, int(max_gpu_workers))
        self._queue: list[Job] = []
        self._running_count = 0
        self._gpu_running = 0

    # -- creation / lookup -------------------------------------------------

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self._id_prefix}-{self._counter}"

    # -- persistence write-through (WU-6) -----------------------------------

    @staticmethod
    def _record_for(job: Job) -> JobRecord:
        """Build the persisted record for ``job`` (its JobInfo + stored request).

        Superset of JobInfo: adds the originating ``method``/``params`` (the
        ``job.retry`` source) so a rehydrated shell can re-dispatch. ``videoId``
        is always present (``None`` when unknown) so the record shape is stable.
        """
        record: JobRecord = {
            "jobId": job.id,
            "feature": job.feature,
            "label": job.label,
            "videoId": job.video_id,
            "status": job.info()["status"],
            "pct": job.pct,
        }
        if job.request is not None:
            record["method"] = job.request.get("method")
            record["params"] = job.request.get("params")
        return record

    def _persist(self, job: Job) -> None:
        """Write ``job``'s current record through the store (no-op when absent)."""
        if self._store is not None:
            self._store.write(self._record_for(job))

    def create(
        self,
        handler: JobHandler,
        *,
        feature: str = "",
        label: str = "",
        videoId: str | None = None,  # noqa: N803 - wire-name kwarg per the A2/A3 spec
        gpu: bool = False,
    ) -> Job:
        """Register a job for ``handler`` (PENDING). Does not start it.

        Metadata kwargs are optional so all existing ``create(handler)`` /
        ``start(handler)`` callers keep working; the dispatch layer backfills
        feature/label/videoId from the originating request when left default.
        """
        with self._lock:
            job = Job(
                id=self._next_id(),
                handler=handler,
                feature=feature,
                label=label,
                video_id=videoId,
                gpu=bool(gpu),
            )
            self._jobs[job.id] = job
            self._persist(job)
            return job

    def get(self, job_id: str) -> Job | None:
        """Return the job by id, or ``None`` if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> dict[str, Job]:
        """Return a shallow copy of the id -> job map."""
        with self._lock:
            return dict(self._jobs)

    def list_info(self, limit: int = 100) -> list[dict[str, Any]]:
        """JobInfo dicts, most-recent-first, bounded (A2: ``job.list``).

        "Most recent" = creation order descending (ids are monotonic), capped
        at ``limit`` (default 100 per the unit contract).
        """
        with self._lock:
            jobs = list(self._jobs.values())
        newest_first = list(reversed(jobs))
        return [job.info() for job in newest_first[: max(0, int(limit))]]

    # -- stored request (job.retry source) ----------------------------------

    def record_request(self, job_id: str, method: str, params: dict[str, Any]) -> None:
        """Store the originating request for ``job_id`` (dispatch-layer hook).

        First write wins: a later ``job.retry`` dispatch (whose result also
        carries a jobId) cannot overwrite the REAL method+params the inner
        re-dispatch already recorded for the new job. Also backfills the job's
        feature/label/videoId metadata when the job was started with defaults,
        so every job started through the RPC dispatch gets meaningful JobInfo
        even before call sites pass explicit metadata.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            # First-write-wins guard (P2): a later job.retry dispatch — and a
            # rehydrated job whose request is already populated (WU-6) — must
            # not overwrite the real method+params, nor re-write the store.
            if job is None or job.request is not None:
                return
            job.request = {"method": method, "params": copy.deepcopy(dict(params))}
            if not job.feature:
                job.feature = method.split(".", 1)[0]
            if not job.label:
                job.label = method
            if job.video_id is None:
                video_id = params.get("videoId") if isinstance(params, dict) else None
                if isinstance(video_id, str) and video_id:
                    job.video_id = video_id
            self._persist(job)

    def get_request(self, job_id: str) -> dict[str, Any] | None:
        """Return a copy of the stored ``{"method", "params"}`` (or ``None``)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.request is None:
                return None
            return copy.deepcopy(job.request)

    # -- rehydrate (WU-6 startup) -------------------------------------------

    @staticmethod
    def _rehydrated_noop(ctx: JobContext) -> None:  # pragma: no cover - never run
        """Placeholder handler for a rehydrated shell.

        A rehydrated job is NEVER auto-spawned (§5 no-silent-spend), so this
        body never executes; ``job.retry`` re-dispatches from the stored
        ``request`` via a FRESH handler instead.
        """

    def rehydrate(self, *, handler: JobHandler | None = None) -> None:
        """Reload persisted jobs at startup; mark mid-flight jobs INTERRUPTED.

        Recreates a :class:`Job` shell per stored record with its metadata +
        stored ``{method, params}`` (so the built-in ``job.retry`` can
        re-dispatch it), maps any non-terminal stored status
        (``pending``/``running``/``queued``) to :data:`JobStatus.INTERRUPTED`
        and persists that re-mark, and keeps terminal statuses verbatim. NO job
        is started here — the pool is untouched (assert run-count 0). A no-op
        when no store was injected; a record without a ``jobId`` is skipped.
        ``handler`` overrides the shell handler (tests use it as a tripwire).
        """
        if self._store is None:
            return
        shell_handler = handler if handler is not None else self._rehydrated_noop
        max_seen = 0
        for record in self._store.load_all():
            job_id = record.get("jobId")
            if not isinstance(job_id, str) or not job_id:
                log.warning("rehydrate: skipping record without jobId")
                continue
            stored_status = str(record.get("status", ""))
            interrupted = stored_status in _NON_TERMINAL_WIRE_STATUSES
            status = JobStatus.INTERRUPTED if interrupted else JobStatus(stored_status)
            method = record.get("method")
            params = record.get("params")
            request = None
            if isinstance(method, str):
                request = {"method": method, "params": copy.deepcopy(params) if params is not None else {}}
            job = Job(
                id=job_id,
                handler=shell_handler,
                status=status,
                pct=int(record.get("pct", 0) or 0),
                feature=str(record.get("feature", "") or ""),
                label=str(record.get("label", "") or ""),
                video_id=record.get("videoId"),
                request=request,
            )
            with self._lock:
                self._jobs[job_id] = job
            if interrupted:
                # Persist the re-mark so a SECOND restart stays consistent.
                self._persist(job)
            suffix = job_id.rsplit("-", 1)[-1]
            if suffix.isdigit():
                max_seen = max(max_seen, int(suffix))
        # New ids must not collide with rehydrated ones.
        with self._lock:
            self._counter = max(self._counter, max_seen)

    # -- execution ---------------------------------------------------------

    def start(
        self,
        handler: JobHandler,
        *,
        feature: str = "",
        label: str = "",
        videoId: str | None = None,  # noqa: N803 - wire-name kwarg per the A2/A3 spec
        gpu: bool = False,
    ) -> Job:
        """Create a job and run it as soon as a pool slot is free. Returns the Job.

        Backwards compatible: ``start(handler)`` works unchanged. When the pool
        has a free slot the job spawns immediately (synchronously, on this
        call), so single-job/direct-registry usage behaves exactly like P1;
        otherwise the job waits QUEUED (JobInfo status "queued") in FIFO order
        and is spawned by the thread that frees a slot.
        """
        job = self.create(handler, feature=feature, label=label, videoId=videoId, gpu=gpu)
        with self._lock:
            job._scheduled = True
            self._queue.append(job)
        self._pump()
        return job

    def _pump(self) -> None:
        """Start queued jobs while pool slots are free (FIFO + gpu serialization).

        A job whose cancel flag was set while still queued finishes CANCELLED
        without ever running. A gpu job blocked only on the gpu slot does not
        block a later non-gpu job (skip-ahead keeps the general pool busy);
        relative order among eligible jobs is preserved.
        """
        to_spawn: list[Job] = []
        cancelled: list[Job] = []
        with self._lock:
            remaining: list[Job] = []
            for job in self._queue:
                if job.cancel_requested:
                    cancelled.append(job)
                    continue
                general_free = self._running_count < self._max_workers
                gpu_free = (not job.gpu) or self._gpu_running < self._max_gpu_workers
                if general_free and gpu_free:
                    self._running_count += 1
                    if job.gpu:
                        self._gpu_running += 1
                    job._slot_held = True
                    to_spawn.append(job)
                else:
                    remaining.append(job)
            self._queue = remaining
        for job in cancelled:
            self._finish_cancelled(job)
        for job in to_spawn:
            self._spawn(job)

    def _release_slot(self, job: Job) -> None:
        """Return ``job``'s pool slot (if it held one) and start the next job."""
        with self._lock:
            if not job._slot_held:
                return
            job._slot_held = False
            self._running_count -= 1
            if job.gpu:
                self._gpu_running -= 1
        self._pump()

    def _spawn(self, job: Job) -> None:
        thread = threading.Thread(target=self._run, args=(job,), name=f"job-{job.id}", daemon=True)
        job._scheduled = True
        job._thread = thread
        thread.start()

    def _on_progress(self, job: Job) -> ProgressEmit:
        """Wrap the progress sink so the job's own ``pct`` mirror stays current."""

        def emit(job_id: str, pct: int, message: str) -> None:
            with self._lock:
                job.pct = pct
            self._emit_progress(job_id, pct, message)

        return emit

    def _set_status(self, job: Job, new_status: JobStatus) -> None:
        """The SINGLE status-transition choke-point (WU-6 write-through seam).

        Every status change goes through here so no transition is silently
        missed by persistence: mutate under the lock, then write the job's
        record through the store. The four lifecycle sinks (running / done /
        cancelled / error) all route through this method.
        """
        with self._lock:
            job.status = new_status
        self._persist(job)

    def _run(self, job: Job) -> None:
        try:
            self._set_status(job, JobStatus.RUNNING)
            ctx = JobContext(
                job_id=job.id,
                _cancel_event=job._cancel_event,
                _emit_progress=self._on_progress(job),
            )
            try:
                if ctx.cancelled:
                    raise JobCancelled(job.id)
                result = job.handler(ctx)
                # A handler may also cooperatively exit by returning after observing
                # cancellation; honor the flag so status reflects the user's intent.
                if ctx.cancelled:
                    self._finish_cancelled(job)
                else:
                    self._finish_done(job, result)
            except JobCancelled:
                self._finish_cancelled(job)
            except Exception as exc:  # noqa: BLE001 - report any handler failure as job error
                log.error("job %s failed: %s\n%s", job.id, exc, traceback.format_exc())
                self._finish_error(job, exc)
        finally:
            # Always return the pool slot — even if a finish/emit path raised —
            # so a bad job can never shrink the pool permanently.
            self._release_slot(job)

    def _finish_done(self, job: Job, result: Any) -> None:
        with self._lock:
            job.pct = 100
            job.result = result
        self._set_status(job, JobStatus.DONE)  # one write-through, final pct included
        job._done_event.set()
        self._emit_done(job.id, result)

    def _finish_cancelled(self, job: Job) -> None:
        self._set_status(job, JobStatus.CANCELLED)
        job._done_event.set()
        # CONTRACT-NOTE: §2 only specifies job.done for *completed* long jobs.
        # We do NOT emit job.done on cancel; the caller learns the outcome via
        # job.cancel's {ok:true} and/or job.status -> "cancelled".

    def _finish_error(self, job: Job, exc: Exception) -> None:
        with self._lock:
            job.error = str(exc)
        self._set_status(job, JobStatus.ERROR)  # one write-through, error set
        job._done_event.set()
        # Phase-0 spine finding: a failed job MUST notify, or every stdio client
        # (UI panels included) waits on job.done forever and the failure reads
        # as a hang. Failure emits job.done with an error payload.
        self._emit_done(
            job.id,
            {"error": {"message": str(exc), "type": exc.__class__.__name__}},
        )

    # -- cancellation ------------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        """Request cooperative cancellation. Returns True if the job exists.

        Sets the cancel flag; a running handler observes it at its next
        checkpoint. A job still waiting in the queue is finished CANCELLED
        immediately (it never ran, so there is nothing to interrupt).
        Cancelling an unknown or already-finished job is a no-op (returns
        whether the job id was known).
        """
        finish_queued: Job | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if not job.finished:
                job.request_cancel()
                if job in self._queue:
                    self._queue.remove(job)
                    finish_queued = job
        if finish_queued is not None:
            self._finish_cancelled(finish_queued)
        return True

    def join(self, timeout: float | None = None) -> None:
        """Wait until every scheduled job has finished (test/shutdown convenience).

        ``timeout`` is a TOTAL deadline across all jobs. Covers queued jobs
        whose worker threads do not exist yet (they spawn when a slot frees):
        we first wait on each scheduled job's done event, then drain the worker
        threads so the final ``job.done`` emissions have flushed before this
        returns. Jobs created but never started are not waited on.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        def remaining() -> float | None:
            if deadline is None:
                return None
            return deadline - time.monotonic()

        while True:
            with self._lock:
                waiting = [j for j in self._jobs.values() if j._scheduled and not j._done_event.is_set()]
            if not waiting:
                break
            rem = remaining()
            if rem is not None and rem <= 0:
                break
            waiting[0]._done_event.wait(rem)
            if not waiting[0]._done_event.is_set():
                break  # timed out waiting on this job — give up (deadline hit)
        with self._lock:
            threads = [j._thread for j in self._jobs.values() if j._thread is not None]
        for thread in threads:
            thread.join(remaining())
