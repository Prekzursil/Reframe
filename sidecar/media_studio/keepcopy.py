"""WU-3b1 — OPT-IN "keep a managed copy" of a source video (DESIGN §3.3 sidecar store).

The library references its videos **by path** (never by copied bytes), so a source
that is moved, renamed, or deleted breaks playback. This module adds an *opt-in*
safety copy: on demand it copies a video's ORIGINAL bytes into an app-managed store
under the data-root (``<dataRoot>/managed-copies/``) and makes that managed copy the
AUTHORITATIVE source for playback/relink, recording the original path as provenance.

Guarantees (GATE WU-3b1):

* **Atomic copy** — the byte copy is delegated to the SINGLE shared copy machinery
  :func:`media_studio.features.project_copy.copy_file_atomic` (temp file + ``os.replace``,
  rollback on any failure) — there is NO parallel copy code here.
* **Free-space preflight** — before copying, the store's free disk space is checked
  against the source size; an insufficient-space store fails LOUD (never a silent
  partial copy).
* **Cumulative cap + LRU eviction** — the managed store has a max-byte ceiling
  (:data:`DEFAULT_CAP_BYTES`); keeping a copy that would breach it first evicts the
  least-recently-accessed managed copies until it fits, so the store can never
  silently fill a small data-root SSD. A single file larger than the whole cap is
  refused LOUD.
* **Content-hash dedup** — the whole-file BLAKE3 ``content_hash`` (reused from
  :mod:`media_studio.relink`) keys the store, so identical bytes are never copied
  twice; a second entity with the same content shares the one managed file at zero
  extra cost.
* **Lineage re-point** — a kept copy re-points the library entity's ``path`` to the
  managed file (authoritative) and records the ORIGINAL path in the managed row
  (provenance); an eviction re-points the entity BACK to its original path so
  playback falls back to the original rather than a deleted managed file.

State lives in a ``managed_copy`` table on the SAME SQLite store as the L1 provenance
DB, created lazily (``CREATE TABLE IF NOT EXISTS``) so it is independent of the gated
library migration. DB access goes through the injected :class:`~media_studio.library.Library`
façade (``library._open`` / ``library.get``) with parameterized (``?``) SQL only.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import relink as _relink
from .features import project_copy as _project_copy
from .library import _now_iso

#: Sub-folder of the data-root (beside ``library.db``) the managed byte-copies live in.
STORE_DIRNAME = "managed-copies"

#: Default cumulative ceiling for the managed store (20 GiB). Exposed via
#: :meth:`ManagedStore.status` so the UI can show "used / cap".
DEFAULT_CAP_BYTES = 20 * 1024**3

#: The managed-store table (created lazily; NOT part of the gated library migration).
_MANAGED_TABLE = "managed_copy"

_CREATE_MANAGED = (
    f"CREATE TABLE IF NOT EXISTS {_MANAGED_TABLE} ("
    " entity_id TEXT PRIMARY KEY, original_path TEXT, managed_path TEXT,"
    " content_hash TEXT, size_bytes INTEGER, kept_at TEXT, last_access TEXT)"
)

#: A free-space probe: ``(path) -> object with a ``.free`` byte count`` (default
#: :func:`shutil.disk_usage`). Injected so the preflight is testable without a real
#: full disk.
DiskUsage = Callable[[str], Any]

#: A wall-clock stamp seam ``() -> iso-string`` (default :func:`media_studio.library._now_iso`).
Clock = Callable[[], str]


class KeepCopyError(RuntimeError):
    """A keep-a-copy / managed-store operation could not proceed (loud, no silent skip)."""


def _row_to_managed(row: sqlite3.Row) -> dict[str, Any]:
    """Reconstruct a managed-copy dict from a ``managed_copy`` row (wire shape)."""
    return {
        "entityId": row["entity_id"],
        "originalPath": row["original_path"],
        "managedPath": row["managed_path"],
        "contentHash": row["content_hash"],
        "sizeBytes": int(row["size_bytes"]),
        "keptAt": row["kept_at"],
        "lastAccess": row["last_access"],
    }


class ManagedStore:
    """The opt-in managed byte-copy store over the injected L1 :class:`Library` façade.

    All heavy/host-only steps are behind injected seams (``hash_file`` for the
    whole-file BLAKE3, ``copier`` for the byte copy, ``disk_usage`` for the free-space
    preflight, ``now`` for the LRU timestamp) so the store logic — preflight, cap,
    eviction, dedup, lineage re-point — is unit-tested without moving gigabytes.
    """

    def __init__(
        self,
        library: Any,
        *,
        cap_bytes: int = DEFAULT_CAP_BYTES,
        hash_file: _relink.HashFile | None = None,
        copier: _project_copy.FileCopier | None = None,
        disk_usage: DiskUsage | None = None,
        now: Clock | None = None,
    ) -> None:
        self._library = library
        self.cap_bytes = int(cap_bytes)
        self._hash_file = hash_file
        self._copier = copier
        self._disk_usage: DiskUsage = disk_usage or shutil.disk_usage
        self._now: Clock = now or _now_iso
        #: The managed-copy folder under the data-root (sibling of the library DB).
        self.store_dir = Path(library.index_path).parent / STORE_DIRNAME

    # ---- store helpers ----------------------------------------------------
    def _ensure_store_dir(self) -> Path:
        """Create (idempotently) and return the managed-copy folder."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        return self.store_dir

    def _store_path(self, digest: str, ext: str) -> Path:
        """The content-addressed managed path for ``digest`` (dedup: identical bytes -> one file)."""
        hex_part = digest.split(":")[-1]
        return self._ensure_store_dir() / f"{hex_part}{ext}"

    @staticmethod
    def _store_size(conn: sqlite3.Connection) -> int:
        """Total managed bytes on disk — summed over DISTINCT content (shared files count once)."""
        rows = conn.execute(f"SELECT content_hash, size_bytes FROM {_MANAGED_TABLE}").fetchall()
        per_hash: dict[str, int] = {r["content_hash"]: int(r["size_bytes"]) for r in rows}
        return sum(per_hash.values())

    # ---- eviction ---------------------------------------------------------
    @staticmethod
    def _original_exists(row: sqlite3.Row) -> bool:
        """Whether a managed copy's ORIGINAL source still exists on disk.

        A copy whose original is gone is IRREPLACEABLE — the managed bytes are the
        only surviving copy of the video — so eviction must never destroy it silently
        (the exact loss keep-a-copy exists to prevent).
        """
        original = row["original_path"]
        return bool(original) and Path(original).exists()

    def _evict_row_db(self, conn: sqlite3.Connection, row: sqlite3.Row) -> list[Path]:
        """Do the DB half of evicting one copy; return the managed file(s) to unlink.

        The entity's ``path`` is re-pointed BACK to the recorded original source
        (provenance) so playback/relink falls back to the original, and the managed row
        is dropped. The managed FILE is NOT deleted here — it is RETURNED (as a 0/1-item
        list) for the caller to unlink, so a rolled-back transaction never leaves a
        re-pointed row beside a deleted file. An empty list is returned when a surviving
        row still references that content (a deduped file shared by another entity stays).
        """
        entity_id = row["entity_id"]
        content_hash = row["content_hash"]
        conn.execute("UPDATE entity SET path = ? WHERE id = ?", (row["original_path"], entity_id))
        conn.execute(f"DELETE FROM {_MANAGED_TABLE} WHERE entity_id = ?", (entity_id,))
        others = conn.execute(
            f"SELECT 1 FROM {_MANAGED_TABLE} WHERE content_hash = ? LIMIT 1", (content_hash,)
        ).fetchone()
        return [Path(row["managed_path"])] if others is None else []

    def _lru_evictable_victim(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        """The least-recently-accessed copy that is SAFE to evict (its original still exists).

        Returns ``None`` when EVERY remaining copy is irreplaceable (original gone) — the
        caller then refuses LOUD rather than destroying the only surviving copy.
        """
        rows = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} ORDER BY last_access ASC, rowid ASC").fetchall()
        for row in rows:
            if self._original_exists(row):
                return row
        return None

    def _evict_to_fit(self, conn: sqlite3.Connection, incoming: int) -> list[Path]:
        """Evict least-recently-used REPLACEABLE copies until ``incoming`` new bytes fit.

        Returns the managed files to unlink AFTER the transaction commits (deferred). A
        dedup hit (``incoming == 0``) grows nothing, so nothing is evicted. A single file
        larger than the WHOLE cap can never fit and is refused LOUD. Only copies whose
        ORIGINAL still exists are evicted (safe to revert to the original); if freeing
        space would require evicting an IRREPLACEABLE copy (original gone), the keep is
        refused LOUD rather than destroying the only surviving copy of that video.
        """
        to_delete: list[Path] = []
        if incoming <= 0:
            return to_delete
        if incoming > self.cap_bytes:
            raise KeepCopyError(
                f"cannot keep a copy: the file ({incoming} bytes) exceeds the "
                f"managed-store cap ({self.cap_bytes} bytes)"
            )
        while self._store_size(conn) + incoming > self.cap_bytes:
            victim = self._lru_evictable_victim(conn)
            if victim is None:
                raise KeepCopyError(
                    "cannot keep a copy: freeing store space would require evicting a "
                    "managed copy whose original source is gone (that managed copy is the "
                    "only surviving copy of the video) — refusing rather than destroying it"
                )
            to_delete.extend(self._evict_row_db(conn, victim))
        return to_delete

    # ---- public API -------------------------------------------------------
    def keep_copy(self, entity_id: str) -> dict[str, Any]:
        """Keep a managed byte-copy of ``entity_id``'s source and re-point lineage to it.

        Idempotent: a video that already has a managed copy returns the existing row
        unchanged (no re-copy). Raises :class:`KeepCopyError` for an unknown video, a
        missing source file, a failed free-space preflight, or a file larger than the
        whole store cap.
        """
        video = self._library.get(entity_id)
        if video is None:
            raise KeepCopyError(f"unknown video: {entity_id}")

        with self._library._open() as conn:
            conn.execute(_CREATE_MANAGED)
            existing = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} WHERE entity_id = ?", (entity_id,)).fetchone()
            if existing is not None:
                return _row_to_managed(existing)  # idempotent: already kept

            src = video.get("path") or ""
            if not src or not Path(src).exists():
                raise KeepCopyError(f"cannot keep a copy: the source file for {entity_id} is missing: {src!r}")

            digest = _relink.content_hash_of(src, hash_file=self._hash_file)
            size = Path(src).stat().st_size
            dup = conn.execute(
                f"SELECT managed_path FROM {_MANAGED_TABLE} WHERE content_hash = ? LIMIT 1",
                (digest,),
            ).fetchone()

            # PREFLIGHT BEFORE eviction: check free space up-front so eviction victims are
            # never destroyed for a keep that then fails the space check. A dedup hit copies
            # no new bytes, so it needs neither free space nor eviction.
            if dup is None:
                usage = self._disk_usage(str(self._ensure_store_dir()))
                if usage.free < size:
                    raise KeepCopyError(
                        f"cannot keep a copy: not enough free space in the managed store "
                        f"({usage.free} bytes free, need {size})"
                    )

            # ATOMIC mutation sequence: eviction + INSERT managed_copy + UPDATE entity
            # re-point run in ONE explicit transaction (the connection is autocommit, so
            # BEGIN/COMMIT is explicit) — a crash mid-sequence rolls the WHOLE sequence
            # back, never leaving evicted victims beside a row without its lineage re-point.
            conn.execute("BEGIN")
            try:
                if dup is not None:
                    # Dedup hit: identical bytes already managed — reuse the file, copy nothing.
                    managed_path = dup["managed_path"]
                    to_delete = self._evict_to_fit(conn, 0)
                else:
                    managed_path = str(self._store_path(digest, Path(src).suffix))
                    to_delete = self._evict_to_fit(conn, size)
                stamp = self._now()
                conn.execute(
                    f"INSERT INTO {_MANAGED_TABLE}"
                    " (entity_id, original_path, managed_path, content_hash, size_bytes, kept_at, last_access)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (entity_id, src, managed_path, digest, size, stamp, stamp),
                )
                # LINEAGE re-point: the managed copy is now AUTHORITATIVE for playback/relink;
                # its content hash is pinned so a later hash-verified relink has a baseline.
                conn.execute(
                    "UPDATE entity SET path = ?, content_hash = ? WHERE id = ?",
                    (managed_path, digest, entity_id),
                )
                if dup is None:
                    # The byte copy is the LAST step before COMMIT: any copy failure rolls
                    # back the eviction + INSERT + re-point above (and the copier rolls back
                    # its own temp), so no partial state survives a mid-write crash.
                    _project_copy.copy_file_atomic(src, managed_path, copier=self._copier)
                row = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} WHERE entity_id = ?", (entity_id,)).fetchone()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            # DEFERRED: only AFTER the transaction commits do we unlink evicted victims' bytes,
            # so a rolled-back keep never destroys a victim's file.
            for victim_file in to_delete:
                with suppress(FileNotFoundError):
                    victim_file.unlink()
        return _row_to_managed(row)

    def status(self) -> dict[str, Any]:
        """Return the managed store's ``{sizeBytes, capBytes, count, entries}`` snapshot."""
        with self._library._open() as conn:
            conn.execute(_CREATE_MANAGED)
            rows = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} ORDER BY rowid").fetchall()
            size = self._store_size(conn)
        entries = [_row_to_managed(r) for r in rows]
        return {"sizeBytes": size, "capBytes": self.cap_bytes, "count": len(entries), "entries": entries}

    def evict(self, entity_id: str, *, force: bool = False) -> dict[str, Any]:
        """Evict a single video's managed copy (re-point to original, free the bytes).

        LOUD SAFETY: when the copy's ORIGINAL source is gone the managed copy is the ONLY
        surviving copy of the video, so evicting it would destroy it. This refuses LOUD
        (raises :class:`KeepCopyError`) in that case UNLESS ``force=True`` is passed to
        destroy it anyway — never a silent destruction of the only copy.
        """
        with self._library._open() as conn:
            conn.execute(_CREATE_MANAGED)
            row = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} WHERE entity_id = ?", (entity_id,)).fetchone()
            if row is None:
                raise KeepCopyError(f"no managed copy to evict for {entity_id}")
            if not force and not self._original_exists(row):
                raise KeepCopyError(
                    f"refusing to evict the managed copy for {entity_id}: its original source "
                    f"{row['original_path']!r} is gone, so the managed copy is the only "
                    f"surviving copy of the video (pass force=True to destroy it anyway)"
                )
            to_delete = self._evict_row_db(conn, row)
        for victim_file in to_delete:
            with suppress(FileNotFoundError):
                victim_file.unlink()
        return {"ok": True, "entityId": entity_id}

    def clear(self, *, force: bool = False) -> dict[str, Any]:
        """Evict EVERY managed copy (re-point each entity to its original, free all bytes).

        LOUD SAFETY: refuses (raises :class:`KeepCopyError`) — destroying NOTHING — when any
        managed copy's ORIGINAL source is gone (it would be the only surviving copy of its
        video), UNLESS ``force=True`` is passed to destroy those irreplaceable copies too.
        """
        with self._library._open() as conn:
            conn.execute(_CREATE_MANAGED)
            rows = conn.execute(f"SELECT * FROM {_MANAGED_TABLE} ORDER BY rowid").fetchall()
            if not force:
                irreplaceable = [r for r in rows if not self._original_exists(r)]
                if irreplaceable:
                    raise KeepCopyError(
                        f"refusing to clear the managed store: {len(irreplaceable)} managed "
                        f"copy(ies) have a missing original source and would be the only "
                        f"surviving copy of their video (pass force=True to destroy them anyway)"
                    )
            to_delete: list[Path] = []
            for row in rows:
                to_delete.extend(self._evict_row_db(conn, row))
        for victim_file in to_delete:
            with suppress(FileNotFoundError):
                victim_file.unlink()
        return {"ok": True, "cleared": len(rows)}


__all__ = [
    "DEFAULT_CAP_BYTES",
    "STORE_DIRNAME",
    "KeepCopyError",
    "ManagedStore",
]
