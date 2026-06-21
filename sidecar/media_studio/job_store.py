"""WU-5: an injectable store that persists job records to disk atomically.

This is the only genuinely new substrate in the UX/QoL bundle: ``jobs.py`` is
100% in-memory (no file I/O), so resumed-after-restart jobs need a place to
survive a process exit. WU-6 wires this store into ``JobRegistry`` (write-through
on every status transition) and rehydrates from it at startup; WU-5 ships the
store alone, fully covered, with no coupling to the registry.

Design:

* :class:`JobStore` is a structural ``Protocol`` (duck-typed seam) so the
  registry can take any implementation — the real :class:`DiskJobStore` or the
  test/in-memory :class:`InMemoryJobStore`.
* :class:`DiskJobStore` writes ONE pretty-JSON file per job under ``root/<jobId>.json``
  using the project's atomic write pattern (temp file + :func:`os.replace`,
  mirroring ``library.py``). A crash mid-write leaves either the old file or the
  new one — never a half-written record — and a stray garbage file is skipped on
  load rather than bricking startup.

Record shape (the persisted JobInfo+request superset)::

    {jobId, feature, label, videoId, method, params, status, pct,
     startedAt, finishedAt}

The store treats records as opaque JSON dicts: it requires only a ``jobId`` key
(the file/identity key) and otherwise round-trips whatever the caller stored.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .util import get_logger

log = get_logger("media_studio.job_store")

# A persisted job record. Opaque JSON dict keyed by ``jobId`` (see module docstring).
JobRecord = dict[str, Any]


@runtime_checkable
class JobStore(Protocol):
    """The persistence seam the registry depends on (structural / duck-typed).

    Any object exposing these three methods is a valid store; the registry never
    imports a concrete class, so tests inject :class:`InMemoryJobStore` and the
    real process injects :class:`DiskJobStore`.
    """

    def write(self, record: JobRecord) -> None:
        """Persist ``record`` (keyed by ``record["jobId"]``); a repeat id updates."""
        ...  # pragma: no cover - Protocol method body is never executed

    def load_all(self) -> list[JobRecord]:
        """Return every persisted record (order unspecified). ``[]`` when empty."""
        ...  # pragma: no cover - Protocol method body is never executed

    def delete(self, job_id: str) -> None:
        """Remove the record for ``job_id`` if present (a no-op when absent)."""
        ...  # pragma: no cover - Protocol method body is never executed


class DiskJobStore:
    """Persists each job as an atomically-written JSON file under ``root``.

    One file per job (``root/<jobId>.json``) so a single job's update never
    rewrites the whole index and a corrupt file isolates blast radius to that
    one job. ``load_all`` skips anything that is not a readable JSON object, so a
    partial-write crash artifact never prevents the rest from loading.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)

    def _path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def write(self, record: JobRecord) -> None:
        """Atomically persist ``record`` to ``root/<jobId>.json`` (temp + rename).

        The temp file gets a UNIQUE name (:func:`tempfile.mkstemp` in the target
        directory) rather than a fixed ``<jobId>.json.tmp``. Two threads writing
        the same job — e.g. the RPC thread (record_request) and the worker thread
        (_set_status) — would otherwise share one temp path: the first
        ``os.replace`` consumes it and the second raises ``FileNotFoundError``,
        breaking the job on the production store. A per-write temp makes the two
        replaces independent (last writer wins), preserving atomicity.
        """
        path = self._path(str(record["jobId"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, indent=2, ensure_ascii=False))
        os.replace(tmp, path)

    def load_all(self) -> list[JobRecord]:
        """Load every well-formed ``*.json`` record under ``root``.

        A non-existent root, a non-JSON / non-object file, or a partial-write
        artifact is skipped — never fatal — so a crashed write can never brick
        startup (the WU-5 resilience invariant).
        """
        if not self.root.is_dir():
            return []
        records: list[JobRecord] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                log.warning("skipping unreadable job record: %s", path.name)
                continue
            if isinstance(data, dict):
                records.append(data)
            else:
                log.warning("skipping non-object job record: %s", path.name)
        return records

    def delete(self, job_id: str) -> None:
        """Remove ``root/<jobId>.json`` if it exists (missing id is a no-op)."""
        self._path(job_id).unlink(missing_ok=True)


class InMemoryJobStore:
    """A dependency-free :class:`JobStore` for tests (parity with the disk store).

    Stores deep copies on both ``write`` and ``load_all`` so callers cannot
    mutate persisted state through a returned record — matching the disk store,
    which always re-reads fresh dicts from JSON.
    """

    def __init__(self) -> None:
        self._records: dict[str, JobRecord] = {}

    def write(self, record: JobRecord) -> None:
        self._records[str(record["jobId"])] = copy.deepcopy(record)

    def load_all(self) -> list[JobRecord]:
        return [copy.deepcopy(r) for r in self._records.values()]

    def delete(self, job_id: str) -> None:
        self._records.pop(job_id, None)
