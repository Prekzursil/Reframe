"""L1 migration tests — SQLite façade + library.json -> DB migration.

These exercise the data-safety guarantees of the L1 storage migration against a
REAL temp-file SQLite DB (never an in-memory shim): WAL journal mode, the
``PRAGMA user_version`` gate, idempotency, partial/corrupt JSON handling,
transaction rollback, the post-commit ``.bak`` backup, parameterized-SQL
injection safety, and the full-Video-dict shape regression (GATE-2).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from media_studio import library
from media_studio.library import Library, LibraryMigrationError


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _user_version(db: Path) -> int:
    conn = sqlite3.connect(str(db))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def _journal_mode(db: Path) -> str:
    conn = sqlite3.connect(str(db))
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    finally:
        conn.close()


def _table_names(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _write_index(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _db_for(index: Path) -> Path:
    return index.with_suffix(".db")


# --------------------------------------------------------------------------- #
# db path derivation + fresh (no library.json) open
# --------------------------------------------------------------------------- #
def test_db_path_derived_from_index_path(tmp_path: Path):
    lib = Library(tmp_path / "library.json")
    assert lib._db_path == tmp_path / "library.db"  # noqa: SLF001 (white-box)


def test_fresh_open_creates_wal_db_stamped_user_version_1(tmp_path: Path):
    idx = tmp_path / "library.json"
    lib = Library(idx, probe_duration=lambda _p: 0.0)
    assert lib.list() == []  # triggers migration on first op
    db = _db_for(idx)
    assert db.exists()
    assert _user_version(db) == 1
    assert _journal_mode(db) == "wal"
    # No library.json existed, so no backup is written.
    assert not (tmp_path / "library.json.bak").exists()


def test_fresh_open_creates_full_prov_schema(tmp_path: Path):
    idx = tmp_path / "library.json"
    Library(idx, probe_duration=lambda _p: 0.0).list()
    assert {"entity", "activity", "agent", "edge"} <= _table_names(_db_for(idx))


# --------------------------------------------------------------------------- #
# migration of an existing library.json
# --------------------------------------------------------------------------- #
def test_migration_imports_full_video_dict_shape(tmp_path: Path):
    # GATE-2: the FULL Video dict (incl. thumbnailPath) survives migrate -> list.
    idx = tmp_path / "library.json"
    full = {
        "id": "vid-1",
        "path": "/media/talk.mp4",
        "title": "My Talk",
        "addedAt": "2026-01-02T03:04:05Z",
        "durationSec": 12.5,
        "hasTranscript": True,
        "thumbnailPath": "/posters/talk.jpg",
    }
    _write_index(idx, {"version": 1, "videos": [full]})
    lib = Library(idx, probe_duration=lambda _p: 0.0)
    got = lib.list()
    assert got == [full]
    assert set(got[0].keys()) == {
        "id",
        "path",
        "title",
        "addedAt",
        "durationSec",
        "hasTranscript",
        "thumbnailPath",
    }


def test_migration_partial_json_backfills_defaults(tmp_path: Path):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": [{"path": "/x.mp4"}]})
    v = Library(idx, probe_duration=lambda _p: 0.0).list()[0]
    assert v["id"]  # generated
    assert v["addedAt"]  # generated
    assert v["title"] == ""
    assert v["durationSec"] == 0.0
    assert v["hasTranscript"] is False
    assert v["thumbnailPath"] == ""


def test_migration_renames_library_json_to_bak(tmp_path: Path):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": [{"id": "a", "path": "/x.mp4"}]})
    original = idx.read_text(encoding="utf-8")
    Library(idx, probe_duration=lambda _p: 0.0).list()
    bak = tmp_path / "library.json.bak"
    assert not idx.exists()  # demoted
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == original  # point-in-time copy


def test_migration_idempotent_no_op_when_already_migrated(tmp_path: Path):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": [{"id": "keep", "path": "/x.mp4"}]})
    Library(idx, probe_duration=lambda _p: 0.0).list()  # first migrate
    # A re-created EMPTY library.json must NOT re-trigger a downgrade (gate is
    # user_version, never file existence).
    _write_index(idx, {"version": 1, "videos": []})
    again = Library(idx, probe_duration=lambda _p: 0.0)
    listed = again.list()
    assert [v["id"] for v in listed] == ["keep"]  # data intact, not wiped
    assert _user_version(_db_for(idx)) == 1
    # The re-created library.json is left untouched (not consumed, not re-baked).
    assert idx.exists()


def test_migration_preexisting_bak_does_not_crash(tmp_path: Path):
    idx = tmp_path / "library.json"
    bak = tmp_path / "library.json.bak"
    _write_index(idx, {"version": 1, "videos": [{"id": "z", "path": "/z.mp4"}]})
    bak.write_text("stale-previous-backup", encoding="utf-8")
    listed = Library(idx, probe_duration=lambda _p: 0.0).list()
    assert [v["id"] for v in listed] == ["z"]
    assert _user_version(_db_for(idx)) == 1
    # os.replace overwrites the stale .bak with the point-in-time source.
    assert bak.read_text(encoding="utf-8") == json.dumps({"version": 1, "videos": [{"id": "z", "path": "/z.mp4"}]})


# --------------------------------------------------------------------------- #
# corrupt library.json -> abort BEFORE stamp/.bak (preserve source authoritative)
# --------------------------------------------------------------------------- #
def test_migration_corrupt_unparseable_json_aborts_before_stamp(tmp_path: Path):
    idx = tmp_path / "library.json"
    idx.write_text("{ this is : not json", encoding="utf-8")
    with pytest.raises(LibraryMigrationError):
        Library(idx, probe_duration=lambda _p: 0.0).list()
    # No stamped empty DB; corrupt source preserved; no .bak written.
    assert _user_version(_db_for(idx)) == 0
    assert idx.read_text(encoding="utf-8") == "{ this is : not json"
    assert not (tmp_path / "library.json.bak").exists()


def test_migration_non_object_json_is_corrupt(tmp_path: Path):
    idx = tmp_path / "library.json"
    _write_index(idx, [1, 2, 3])  # valid JSON, wrong shape
    with pytest.raises(LibraryMigrationError):
        Library(idx, probe_duration=lambda _p: 0.0).list()
    assert _user_version(_db_for(idx)) == 0


def test_migration_videos_not_a_list_is_corrupt(tmp_path: Path):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": "not-a-list"})
    with pytest.raises(LibraryMigrationError):
        Library(idx, probe_duration=lambda _p: 0.0).list()
    assert _user_version(_db_for(idx)) == 0


# --------------------------------------------------------------------------- #
# transaction rollback -> source stays authoritative, next open retries
# --------------------------------------------------------------------------- #
def test_migration_rollback_on_insert_failure_then_retry_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": [{"id": "r", "path": "/r.mp4"}]})

    def boom(self, conn, video):  # noqa: ANN001, ARG001
        raise RuntimeError("insert exploded mid-migration")

    monkeypatch.setattr(Library, "_insert_entity", boom)
    with pytest.raises(RuntimeError, match="insert exploded"):
        Library(idx, probe_duration=lambda _p: 0.0).list()

    db = _db_for(idx)
    # The whole migration rolled back: no stamp, no entity table, source intact.
    assert _user_version(db) == 0
    assert "entity" not in _table_names(db)
    assert idx.exists()  # NOT renamed to .bak
    assert not (tmp_path / "library.json.bak").exists()

    # Removing the fault, the next open retries from the still-authoritative JSON.
    monkeypatch.undo()
    listed = Library(idx, probe_duration=lambda _p: 0.0).list()
    assert [v["id"] for v in listed] == ["r"]
    assert _user_version(db) == 1


def test_backup_rename_failure_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    idx = tmp_path / "library.json"
    _write_index(idx, {"version": 1, "videos": [{"id": "b", "path": "/b.mp4"}]})

    real_replace = library.os.replace

    def flaky_replace(src, dst, *args, **kwargs):  # noqa: ANN001
        if str(dst).endswith(".bak"):
            raise OSError("backup rename denied")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(library.os, "replace", flaky_replace)
    # Migration already committed before the (failed) backup, so it must not raise.
    listed = Library(idx, probe_duration=lambda _p: 0.0).list()
    assert [v["id"] for v in listed] == ["b"]
    assert _user_version(_db_for(idx)) == 1


# --------------------------------------------------------------------------- #
# parameterized SQL only — injection round-trip
# --------------------------------------------------------------------------- #
def test_parameterized_sql_injection_roundtrip(tmp_path: Path):
    idx = tmp_path / "library.json"
    media = tmp_path / "evil.mp4"
    media.write_bytes(b"x")
    lib = Library(idx, probe_duration=lambda _p: 1.0)
    nasty = "Robert'); DROP TABLE entity;--"
    v = lib.add(str(media), title=nasty)
    # The payload is stored/retrieved verbatim and the table is NOT dropped.
    assert v["title"] == nasty
    assert lib.get(v["id"])["title"] == nasty
    assert "entity" in _table_names(_db_for(idx))
    assert len(lib.list()) == 1


def test_content_hash_column_nullable_and_unpopulated(tmp_path: Path):
    idx = tmp_path / "library.json"
    media = tmp_path / "v.mp4"
    media.write_bytes(b"x")
    lib = Library(idx, probe_duration=lambda _p: 1.0)
    v = lib.add(str(media))
    conn = sqlite3.connect(str(_db_for(idx)))
    try:
        row = conn.execute("SELECT content_hash FROM entity WHERE id=?", (v["id"],)).fetchone()
    finally:
        conn.close()
    assert row[0] is None  # nullable + unpopulated in L1 (no BLAKE3 dep)
