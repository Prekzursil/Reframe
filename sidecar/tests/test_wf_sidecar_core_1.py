"""New-branch tests for the sidecar-core-1 fixer unit (jobs / job_store / keepcopy /
tools_resolver / provider). Kept in a uniquely-named file so it can never collide
with a sibling fixer; coverage is by SOURCE file, so these still count toward the
100% gate for the modules they exercise.

Grouped by the verified finding they cover:

* jobs.py  — cancel emits a terminal JobCancelled job.done (idempotent);
             progress-after-finalize is suppressed; bounded terminal-job retention;
             rehydrate loads in numeric-id (creation) order.
* keepcopy.py — LRU recency is refreshed on re-keep and on touch() (not FIFO).
* tools_resolver.py — version-aware (release-tag marker) detect probes.
* models/provider.py — per-function routing prefers by catalog provider label.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from media_studio import tools_resolver as tr
from media_studio.job_store import InMemoryJobStore
from media_studio.jobs import JobRegistry, JobStatus
from media_studio.keepcopy import KeepCopyError, ManagedStore
from media_studio.library import Library
from media_studio.models import provider as P

_CANCELLED_DONE = {"error": {"message": "cancelled", "type": "JobCancelled"}}


# --------------------------------------------------------------------------- #
# jobs.py — watchdog seam doubles (mirror test_jobs_f3b.py) + helpers
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


class _DeleteRecordingStore(InMemoryJobStore):
    """InMemoryJobStore that records the ids passed to :meth:`delete` (retention probe)."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete(self, job_id: str) -> None:
        self.deleted.append(job_id)
        super().delete(job_id)


class _NonDictFirstStore(InMemoryJobStore):
    """InMemoryJobStore whose ``load_all`` yields a non-dict record first.

    Exercises the resilience of the rehydrate sort key against a store impl that
    returns a non-dict record (real stores never do, but the Protocol allows it).
    """

    def load_all(self):
        return ["not-a-dict", *super().load_all()]


# --------------------------------------------------------------------------- #
# jobs.py finding — cancel emits a terminal JobCancelled job.done (idempotent)
# --------------------------------------------------------------------------- #
def test_cancel_emits_done_once_and_is_idempotent(emit_sinks, collected):
    ep, ed = emit_sinks
    spy = _TimerSpy()
    reg = JobRegistry(ep, ed, max_workers=1, job_timeout_sec=600.0, timer_factory=spy)
    started, release = threading.Event(), threading.Event()

    def handler(ctx):
        started.set()
        while not ctx.cancelled:
            release.wait(timeout=0.01)
        return "unreached"

    job = reg.start(handler)
    assert started.wait(5)
    # Fire the watchdog too: it routes through _finish_error while the handler's
    # observed-cancel routes through _finish_cancelled — _claim_terminal must let
    # exactly ONE terminal transition win, so at most one job.done is emitted.
    assert reg.cancel(job.id) is True
    spy.timers[0].fn()  # watchdog races the cancel; the guard makes this a no-op or the sole finisher
    release.set()
    assert job.wait(timeout=5)
    dones = [(jid, payload) for k, (jid, payload) in collected if k == "done"]
    assert len(dones) == 1  # exactly one terminal notification for this job
    jid, payload = dones[0]
    assert jid == job.id
    # Whoever won, the payload is an error envelope (JobCancelled or the deadline error).
    assert "error" in payload and "type" in payload["error"]


def test_queued_cancel_emits_terminal_done(emit_sinks, collected):
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, max_workers=1)
    started, release = threading.Event(), threading.Event()

    def blocker(ctx):
        started.set()
        assert release.wait(timeout=5)
        return "released"

    reg.start(blocker)  # occupies the only slot
    assert started.wait(5)
    ran = threading.Event()
    queued = reg.start(lambda ctx: ran.set())
    assert queued.info()["status"] == "queued"
    assert reg.cancel(queued.id) is True  # cancelled while still queued
    assert queued.wait(timeout=5)
    assert not ran.is_set()
    dones = {jid: payload for k, (jid, payload) in collected if k == "done"}
    assert dones[queued.id] == _CANCELLED_DONE
    release.set()


# --------------------------------------------------------------------------- #
# jobs.py finding — progress after finalize is suppressed
# --------------------------------------------------------------------------- #
def test_progress_after_finalize_is_suppressed(emit_sinks, collected):
    ep, ed = emit_sinks
    spy = _TimerSpy()
    reg = JobRegistry(ep, ed, max_workers=1, job_timeout_sec=600.0, timer_factory=spy)
    started, release = threading.Event(), threading.Event()
    late_sent = threading.Event()

    def handler(ctx):
        started.set()
        assert release.wait(timeout=5)  # wedged until AFTER the watchdog fires
        ctx.progress(50, "late")  # handler resumes and reports progress post-finalize
        late_sent.set()
        return "released"

    job = reg.start(handler)
    assert started.wait(5)
    spy.timers[0].fn()  # fire the deadline -> _finish_error finalizes ERROR
    assert job.status is JobStatus.ERROR
    release.set()  # let the wedged handler resume + call progress
    assert late_sent.wait(5)
    assert job.wait(timeout=5)
    # No job.progress emitted for this job at pct 50, and job.pct did not regress to 50.
    assert not any(kind == "progress" and payload[0] == job.id and payload[1] == 50 for kind, payload in collected)
    assert job.pct != 50


# --------------------------------------------------------------------------- #
# jobs.py finding — bounded terminal-job retention (registry + store + dead API)
# --------------------------------------------------------------------------- #
def _run_to_done(reg: JobRegistry) -> str:
    job = reg.start(lambda ctx: "x")
    assert job.wait(timeout=5)
    return job.id


def test_terminal_jobs_beyond_cap_are_evicted(emit_sinks):
    ep, ed = emit_sinks
    store = InMemoryJobStore()
    reg = JobRegistry(ep, ed, store=store, max_workers=1, max_terminal_history=2)
    ids = [_run_to_done(reg) for _ in range(3)]
    assert reg.get(ids[0]) is None  # oldest evicted from the registry ...
    assert reg.get(ids[1]) is not None
    assert reg.get(ids[2]) is not None
    assert {i["jobId"] for i in reg.list_info()} == {ids[1], ids[2]}
    stored = {r["jobId"] for r in store.load_all()}  # ... and from the store
    assert stored == {ids[1], ids[2]}


def test_retention_evicts_registry_when_no_store(emit_sinks):
    # store=None -> the eviction still drops the oldest job from the in-memory registry
    # (covers the ``if self._store is not None`` False branch of _prune_terminal_history).
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, max_workers=1, max_terminal_history=1)
    first = _run_to_done(reg)
    second = _run_to_done(reg)
    assert reg.get(first) is None
    assert reg.get(second) is not None


def test_retention_invokes_store_delete(emit_sinks):
    # Proves the previously-dead JobStore.delete API is now wired to eviction.
    ep, ed = emit_sinks
    store = _DeleteRecordingStore()
    reg = JobRegistry(ep, ed, store=store, max_workers=1, max_terminal_history=1)
    first = _run_to_done(reg)
    _run_to_done(reg)
    assert store.deleted == [first]


def test_retention_disabled_when_history_large(emit_sinks):
    ep, ed = emit_sinks
    store = _DeleteRecordingStore()
    reg = JobRegistry(ep, ed, store=store, max_workers=1, max_terminal_history=100)
    ids = [_run_to_done(reg) for _ in range(3)]
    assert store.deleted == []  # nothing evicted under a generous cap
    for i in ids:
        assert reg.get(i) is not None


def test_just_finished_job_is_still_queryable_after_prune(emit_sinks):
    # Regression guard: the newest terminal job is never the eviction victim.
    ep, ed = emit_sinks
    reg = JobRegistry(ep, ed, store=InMemoryJobStore(), max_workers=1, max_terminal_history=1)
    reg.start(lambda ctx: "first").wait(timeout=5)
    last = reg.start(lambda ctx: "second")
    assert last.wait(timeout=5)
    survivor = reg.get(last.id)
    assert survivor is not None
    assert survivor.status is JobStatus.DONE
    assert survivor.result == "second"


def test_non_terminal_interrupted_job_is_never_evicted(emit_sinks):
    ep, ed = emit_sinks
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "running", "method": "a.x", "params": {}})
    reg = JobRegistry(ep, ed, store=store, max_workers=1, max_terminal_history=1)
    reg.rehydrate()  # job-1 -> INTERRUPTED (non-terminal), counter advances to 1
    assert reg.get("job-1").status is JobStatus.INTERRUPTED
    second = _run_to_done(reg)  # job-2 DONE
    third = _run_to_done(reg)  # job-3 DONE -> evicts the oldest TERMINAL (job-2)
    assert reg.get("job-1") is not None  # the interrupted job survives past the cap
    assert reg.get(second) is None
    assert reg.get(third) is not None


def test_rehydrate_caps_terminal_history(emit_sinks):
    ep, ed = emit_sinks
    store = InMemoryJobStore()
    store.write({"jobId": "job-1", "status": "done"})
    store.write({"jobId": "job-2", "status": "done"})
    store.write({"jobId": "job-3", "status": "running"})  # non-terminal -> INTERRUPTED
    store.write({"jobId": "job-4", "status": "done"})
    reg = JobRegistry(ep, ed, store=store, max_terminal_history=2)
    reg.rehydrate()
    # 3 terminal records (1,2,4) > cap 2 -> oldest terminal (job-1) pruned from both
    assert reg.get("job-1") is None
    assert {r["jobId"] for r in store.load_all()} == {"job-2", "job-3", "job-4"}
    assert reg.get("job-2") is not None
    assert reg.get("job-3").status is JobStatus.INTERRUPTED  # interrupted retained
    assert reg.get("job-4") is not None


# --------------------------------------------------------------------------- #
# job_store/jobs finding — rehydrate loads in numeric-id (creation) order
# --------------------------------------------------------------------------- #
def test_rehydrate_orders_list_info_by_numeric_id_not_lexicographic(emit_sinks):
    ep, ed = emit_sinks
    store = InMemoryJobStore()
    # Insertion order != numeric order so this fails under lexicographic/insertion order.
    store.write({"jobId": "job-1", "status": "done"})
    store.write({"jobId": "job-10", "status": "done"})
    store.write({"jobId": "job-2", "status": "done"})
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert [j["jobId"] for j in reg.list_info()] == ["job-10", "job-2", "job-1"]


def test_rehydrate_non_numeric_id_sorts_oldest_without_error(emit_sinks):
    # Covers the (-1, 0) branch of the sort key: a non-numeric id sorts first (oldest)
    # and never raises an int-vs-str TypeError.
    ep, ed = emit_sinks
    store = InMemoryJobStore()
    store.write({"jobId": "job-2", "status": "done"})
    store.write({"jobId": "job-abc", "status": "done"})
    store.write({"jobId": "job-1", "status": "done"})
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert [j["jobId"] for j in reg.list_info()] == ["job-2", "job-1", "job-abc"]


def test_rehydrate_sort_tolerates_a_non_dict_record(emit_sinks):
    # Covers the ``isinstance(record, dict)`` False branch of the sort key: a non-dict
    # record sorts first and is left for the per-record guard to skip (never crashes all).
    ep, ed = emit_sinks
    store = _NonDictFirstStore()
    store.write({"jobId": "job-2", "status": "done"})
    store.write({"jobId": "job-1", "status": "done"})
    reg = JobRegistry(ep, ed, store=store)
    reg.rehydrate()
    assert [j["jobId"] for j in reg.list_info()] == ["job-2", "job-1"]


# --------------------------------------------------------------------------- #
# keepcopy.py finding — LRU recency refreshed on re-keep and touch (not FIFO)
# --------------------------------------------------------------------------- #
def _fresh_library(tmp_path: Path) -> Library:
    return Library(tmp_path / "data" / "library.json", probe_duration=lambda _p: 0.0)


def _add_source(lib: Library, tmp_path: Path, name: str, data: bytes) -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    return lib.add(str(media))["id"], media


def _entity_path(lib: Library, entity_id: str) -> str:
    return lib.get(entity_id)["path"]


def _copier(s: str, d: str) -> None:
    Path(d).write_bytes(Path(s).read_bytes())


def test_touch_bumps_recency_so_older_kept_copy_survives_eviction(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, ma = _add_source(lib, tmp_path, "a.mp4", b"aaaa")
    b, mb = _add_source(lib, tmp_path, "b.mp4", b"bbbb")
    c, _mc = _add_source(lib, tmp_path, "c.mp4", b"cccc")
    stamps = iter(["t0", "t1", "t2", "t3"])
    store = ManagedStore(lib, cap_bytes=8, copier=_copier, now=lambda: next(stamps))
    ka = store.keep_copy(a)  # {A}=4 accessed t0
    store.keep_copy(b)  # {A,B}=8 accessed t1
    store.touch(a)  # A accessed at t2 -> now MORE recent than B(t1)
    store.keep_copy(c)  # 8+4>8 -> evict LRU. FIFO would drop A(t0); LRU drops B(t1).
    kept = {e["entityId"] for e in store.status()["entries"]}
    assert kept == {a, c}  # A survived because touch() made it recently-accessed
    assert Path(ka["managedPath"]).exists()
    assert _entity_path(lib, b) == str(mb.resolve())  # B reverted to its original


def test_re_keep_bumps_last_access(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, _ma = _add_source(lib, tmp_path, "a.mp4", b"aaaa")
    b, mb = _add_source(lib, tmp_path, "b.mp4", b"bbbb")
    c, _mc = _add_source(lib, tmp_path, "c.mp4", b"cccc")
    stamps = iter(["t0", "t1", "t2", "t3"])
    store = ManagedStore(lib, cap_bytes=8, copier=_copier, now=lambda: next(stamps))
    ka0 = store.keep_copy(a)  # {A}=4 accessed t0
    store.keep_copy(b)  # {A,B}=8 accessed t1
    ka1 = store.keep_copy(a)  # idempotent re-keep bumps A's recency -> t2 (no re-copy)
    assert ka1["managedPath"] == ka0["managedPath"]
    assert ka1["keptAt"] == "t0"  # keptAt unchanged ...
    assert ka1["lastAccess"] == "t2"  # ... but last_access advanced past keptAt
    store.keep_copy(c)  # evict LRU = B(t1); A(t2) survives
    kept = {e["entityId"] for e in store.status()["entries"]}
    assert kept == {a, c}
    assert _entity_path(lib, b) == str(mb.resolve())


def test_touch_unknown_entity_is_loud(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    with pytest.raises(KeepCopyError, match="no managed copy to touch"):
        ManagedStore(lib).touch("ghost")


# --------------------------------------------------------------------------- #
# tools_resolver.py finding — version-aware (release-tag marker) detect probes
# --------------------------------------------------------------------------- #
def _mark(dir_path: Path, tag: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / tr.RELEASE_TAG_MARKER).write_text(tag, encoding="utf-8")


def test_detect_cuda_stale_marker_misses(tmp_path, monkeypatch) -> None:
    # exe present but the marker carries an OLD tag -> not the current install -> None
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(tr, "DEV_LLAMA_DIR", str(tmp_path / "empty-dev"))
    cuda_dir = tmp_path / tr.TOOL_DIR_CUDA
    cuda_dir.mkdir(parents=True)
    (cuda_dir / tr.LLAMA_EXE).write_bytes(b"x")
    _mark(cuda_dir, "b0000-old")
    assert tr.detect_llama_cuda({}) is None


def test_detect_cuda_matching_marker_but_missing_exe_falls_through_to_dev(tmp_path, monkeypatch) -> None:
    # marker matches (dir eligible) but no exe -> extracted branch yields None -> dev wins
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
    dev = tmp_path / "dev"
    dev.mkdir()
    dev_exe = dev / tr.LLAMA_EXE
    dev_exe.write_bytes(b"x")
    monkeypatch.setattr(tr, "DEV_LLAMA_DIR", str(dev))
    _mark(tmp_path / tr.TOOL_DIR_CUDA, tr.LLAMA_RELEASE_TAG)
    assert tr.detect_llama_cuda({}) == str(dev_exe)


def test_detect_cpu_matching_marker_but_missing_exe_is_none(tmp_path, monkeypatch) -> None:
    # marker matches -> dir eligible -> _detect_in_tool_dir returns None (no exe)
    monkeypatch.setenv("MEDIA_STUDIO_CONFIG_DIR", str(tmp_path))
    _mark(tmp_path / tr.TOOL_DIR_CPU, tr.LLAMA_RELEASE_TAG)
    assert tr.detect_llama_cpu({}) is None


# --------------------------------------------------------------------------- #
# provider.py finding — per-function routing prefers by catalog provider label
# --------------------------------------------------------------------------- #
def test_prefer_matches_by_catalog_label_for_production_shaped_entry() -> None:
    # Production shape: the UI stores id=slug, provider=label; the routing slot stores a
    # catalog MODEL id. The preference must still hoist the entry (matched by its label).
    groq = {
        "id": "groq",
        "provider": "Groq",
        "baseUrl": "https://groq.example/v1",
        "model": "gpt-oss-120b",
        "apiKeys": ["gk-real"],
        "capabilities": ["text"],
    }
    cerebras = {
        "id": "cerebras",
        "provider": "Cerebras",
        "baseUrl": "https://cerebras.example/v1",
        "model": "qwen3-235b",
        "apiKeys": ["ck-real"],
        "capabilities": ["text"],
    }
    pool = P.build_pool_provider({"providers": [cerebras, groq]}, detect_local=False, prefer="groq-gpt-oss-120b")
    providers = [e.provider for e in pool.entries]
    assert providers[0] == "Groq"  # hoisted via the catalog-resolved label
    assert providers[-1] == "local"


def test_acceptable_provider_idents_known_and_unknown() -> None:
    known = P._acceptable_provider_idents("groq-gpt-oss-120b")
    assert "groq-gpt-oss-120b" in known
    assert "Groq" in known  # the catalog-resolved provider label
    unknown = P._acceptable_provider_idents("not-a-catalog-id")
    assert unknown == frozenset({"not-a-catalog-id"})  # literal-only, no resolution
