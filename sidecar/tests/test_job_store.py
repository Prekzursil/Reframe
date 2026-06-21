"""Tests for the WU-5 JobStore substrate (atomic per-job disk persistence).

The store is the only genuinely new substrate in the UX/QoL bundle (jobs.py is
100% in-memory today). These tests pin the falsifiable acceptance from
docs/plans/ux-qol/PLAN.md WU-5:

* ``write(r)`` then ``load_all()`` round-trips field-for-field;
* a second ``write`` with the same ``jobId`` UPDATES (one file, not a duplicate);
* a corrupt JSON file in the root is SKIPPED (a partial-write crash never bricks
  startup) — the falsifiable resilience claim;
* ``load_all()`` on a non-existent root returns ``[]`` (no crash on first run);
* the write is atomic (temp file + rename, no partial file left behind);
* ``InMemoryJobStore`` is parity-tested against the same contract.

Using a REAL tmp dir for ``DiskJobStore`` is legitimate here: the filesystem IS
the unit under test (no ffmpeg / network / provider is touched).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest
from media_studio import job_store
from media_studio.job_store import DiskJobStore, InMemoryJobStore, JobStore


def _record(job_id: str = "job-1", **overrides: Any) -> dict[str, Any]:
    """A full WU-5 job record (the persisted shape)."""
    rec: dict[str, Any] = {
        "jobId": job_id,
        "feature": "transcribe",
        "label": "Transcribe clip",
        "videoId": "vid-42",
        "method": "ai.transcribe",
        "params": {"videoId": "vid-42", "lang": "en"},
        "status": "running",
        "pct": 37,
        "startedAt": "2026-06-20T04:00:00Z",
        "finishedAt": None,
    }
    rec.update(overrides)
    return rec


# --------------------------------------------------------------------------- #
# Parametrize across both implementations so the CONTRACT is enforced on both. #
# --------------------------------------------------------------------------- #
def _make_disk(tmp_path: Path) -> JobStore:
    return DiskJobStore(tmp_path / "jobs")


def _make_mem(tmp_path: Path) -> JobStore:  # tmp_path unused; signature parity
    return InMemoryJobStore()


@pytest.fixture(params=[_make_disk, _make_mem], ids=["disk", "memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> JobStore:
    return request.param(tmp_path)


def test_write_then_load_all_round_trips_field_for_field(store: JobStore) -> None:
    rec = _record()
    store.write(rec)
    loaded = store.load_all()
    assert loaded == [rec]


def test_second_write_same_job_id_updates_not_duplicates(store: JobStore) -> None:
    store.write(_record(status="running", pct=10))
    store.write(_record(status="done", pct=100, finishedAt="2026-06-20T04:05:00Z"))
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0]["status"] == "done"
    assert loaded[0]["pct"] == 100
    assert loaded[0]["finishedAt"] == "2026-06-20T04:05:00Z"


def test_load_all_returns_all_distinct_jobs(store: JobStore) -> None:
    store.write(_record("job-a"))
    store.write(_record("job-b"))
    ids = sorted(r["jobId"] for r in store.load_all())
    assert ids == ["job-a", "job-b"]


def test_load_all_on_empty_store_returns_empty_list(store: JobStore) -> None:
    assert store.load_all() == []


def test_delete_removes_the_record(store: JobStore) -> None:
    store.write(_record("job-a"))
    store.write(_record("job-b"))
    store.delete("job-a")
    ids = [r["jobId"] for r in store.load_all()]
    assert ids == ["job-b"]


def test_delete_missing_job_is_a_no_op(store: JobStore) -> None:
    store.write(_record("job-a"))
    store.delete("does-not-exist")  # must not raise
    assert [r["jobId"] for r in store.load_all()] == ["job-a"]


# --------------------------------------------------------------------------- #
# DiskJobStore-specific behaviour (atomicity, corruption resilience, layout).  #
# --------------------------------------------------------------------------- #
def test_disk_load_all_on_nonexistent_root_returns_empty(tmp_path: Path) -> None:
    store = DiskJobStore(tmp_path / "never-created")
    assert store.load_all() == []


def test_disk_write_creates_the_root_dir(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    assert not root.exists()
    DiskJobStore(root).write(_record())
    assert root.is_dir()


def test_disk_write_leaves_no_temp_file(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = DiskJobStore(root)
    store.write(_record("job-a"))
    # Only the final per-job JSON file remains; no .tmp residue (atomic rename).
    names = sorted(p.name for p in root.iterdir())
    assert names == ["job-a.json"]


def test_disk_corrupt_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = DiskJobStore(root)
    store.write(_record("good"))
    # Simulate a partial-write / garbage file crash artifact.
    (root / "broken.json").write_text("{ this is not json", encoding="utf-8")
    loaded = store.load_all()
    assert [r["jobId"] for r in loaded] == ["good"]


def test_disk_non_json_files_in_root_are_ignored(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = DiskJobStore(root)
    store.write(_record("good"))
    # A stray temp/other file must not be parsed as a record.
    (root / "good.json.tmp").write_text("garbage", encoding="utf-8")
    (root / "README.txt").write_text("notes", encoding="utf-8")
    assert [r["jobId"] for r in store.load_all()] == ["good"]


def test_disk_non_dict_json_record_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    store = DiskJobStore(root)
    store.write(_record("good"))
    # A syntactically-valid JSON file whose top level is not an object.
    (root / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert [r["jobId"] for r in store.load_all()] == ["good"]


def test_disk_record_is_persisted_as_indented_json(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    DiskJobStore(root).write(_record("job-a"))
    text = (root / "job-a.json").read_text(encoding="utf-8")
    assert '"jobId": "job-a"' in text  # pretty, key-spaced (indent=2)


def test_disk_root_accepts_str_path(tmp_path: Path) -> None:
    # The constructor coerces str | PathLike to Path.
    store = DiskJobStore(str(tmp_path / "jobs"))
    store.write(_record("job-a"))
    assert [r["jobId"] for r in store.load_all()] == ["job-a"]


def test_in_memory_returns_independent_copies(tmp_path: Path) -> None:
    # Mutating a returned record must not corrupt the store's state (parity with
    # the disk store, which always re-reads from JSON).
    store = InMemoryJobStore()
    store.write(_record("job-a", pct=10))
    loaded = store.load_all()
    loaded[0]["pct"] = 999
    assert store.load_all()[0]["pct"] == 10


def test_in_memory_write_copies_input_record(tmp_path: Path) -> None:
    # Mutating the caller's record after write must not change stored state.
    store = InMemoryJobStore()
    rec = _record("job-a", pct=10)
    store.write(rec)
    rec["pct"] = 999
    assert store.load_all()[0]["pct"] == 10


# --------------------------------------------------------------------------- #
# Concurrency: two threads writing the SAME job must not clobber each other.   #
# --------------------------------------------------------------------------- #
def test_disk_concurrent_writes_same_job_do_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two threads writing the same ``jobId`` must both succeed (no race).

    Reproduces the production DiskJobStore race: the RPC thread (record_request)
    and the worker thread (_set_status) write the SAME job concurrently. With a
    fixed ``<job>.json.tmp`` temp name both threads target one temp file, so the
    first ``os.replace`` consumes it and the second raises ``FileNotFoundError``,
    breaking the job. A unique temp per write makes both writes independent.

    The interleaving is forced deterministically (not thread-spawn-and-hope): a
    :class:`threading.Barrier` holds BOTH workers at the ``os.replace`` seam
    until both have created their temp file, then the replaces are serialized.
    Pre-fix this guarantees the collision; post-fix both replaces succeed.
    """
    store = DiskJobStore(tmp_path / "jobs")
    store.write(_record("job-x"))  # create the root dir up front

    barrier = threading.Barrier(2)
    serialize = threading.Lock()
    real_replace = os.replace

    def coordinated_replace(src: Any, dst: Any) -> None:
        # Both threads have written their temp file before ANY replace happens.
        barrier.wait()
        with serialize:
            real_replace(src, dst)

    monkeypatch.setattr(job_store.os, "replace", coordinated_replace)

    errors: list[BaseException] = []

    def worker(status: str) -> None:
        try:
            store.write(_record("job-x", status=status))
        except BaseException as exc:  # noqa: BLE001 - capture for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(status,)) for status in ("running", "done")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    # Exactly one record survives (last writer wins), root has no .tmp residue.
    loaded = store.load_all()
    assert [r["jobId"] for r in loaded] == ["job-x"]
    assert sorted(p.name for p in (tmp_path / "jobs").iterdir()) == ["job-x.json"]
