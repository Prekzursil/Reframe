"""WU-3b1 — managed keep-a-copy store + the shared atomic byte-copy machinery.

Two units under test:

* :func:`media_studio.features.project_copy.copy_file_atomic` — the SINGLE shared
  byte-copy primitive (temp file + ``os.replace``, rollback on any failure) the
  managed store reuses (no parallel copy code).
* :class:`media_studio.keepcopy.ManagedStore` — the opt-in managed byte-copy store:
  free-space preflight, cumulative cap + LRU eviction, content-hash dedup, and the
  lineage re-point (managed copy becomes authoritative; original recorded as
  provenance; eviction reverts to the original).

Every heavy/host-only step runs behind an injected seam (``hash_file`` / ``copier`` /
``disk_usage`` / ``now``) against a REAL temp-file SQLite store, so preflight-fail,
atomic-rollback, cap-eviction, dedup-hit, and already-missing-source branches are all
proven without moving real gigabytes. The default (real) byte copier + real BLAKE3 are
also exercised against tiny temp files so the default reader is covered.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from media_studio.features import project_copy
from media_studio.keepcopy import KeepCopyError, ManagedStore
from media_studio.library import Library


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fresh_library(tmp_path: Path) -> Library:
    return Library(tmp_path / "data" / "library.json", probe_duration=lambda _p: 0.0)


def _add_source(lib: Library, tmp_path: Path, name: str, data: bytes) -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    return lib.add(str(media))["id"], media


def _free(n: int) -> SimpleNamespace:
    """A fake disk_usage result exposing only ``.free``."""
    return SimpleNamespace(free=n)


def _entity_path(lib: Library, entity_id: str) -> str:
    return lib.get(entity_id)["path"]


# --------------------------------------------------------------------------- #
# copy_file_atomic — the shared atomic byte-copy machinery
# --------------------------------------------------------------------------- #
def test_copy_file_atomic_default_copier_copies_real_bytes(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"real-payload")
    dest = tmp_path / "store" / "dest.bin"
    out = project_copy.copy_file_atomic(str(src), str(dest))
    assert out == dest
    assert dest.read_bytes() == b"real-payload"
    # the temp part file must not linger after a successful replace.
    assert not (dest.parent / (dest.name + project_copy.COPY_PART_SUFFIX)).exists()


def test_copy_file_atomic_injected_copier_success(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    dest = tmp_path / "dest.bin"

    def copier(s: str, d: str) -> None:
        Path(d).write_bytes(b"copied-via-seam")

    project_copy.copy_file_atomic(str(src), str(dest), copier=copier)
    assert dest.read_bytes() == b"copied-via-seam"


def test_copy_file_atomic_missing_source_is_loud(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="does not exist"):
        project_copy.copy_file_atomic(str(tmp_path / "ghost.bin"), str(tmp_path / "d.bin"))


def test_copy_file_atomic_rolls_back_partial_temp_on_failure(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    dest = tmp_path / "dest.bin"

    def failing_copier(s: str, d: str) -> None:
        Path(d).write_bytes(b"half-written")  # a partial temp is created ...
        raise RuntimeError("disk exploded mid-write")  # ... then the write fails

    with pytest.raises(RuntimeError, match="disk exploded"):
        project_copy.copy_file_atomic(str(src), str(dest), copier=failing_copier)
    # ROLLBACK: neither a corrupt dest nor the partial temp survive.
    assert not dest.exists()
    assert not (dest.parent / (dest.name + project_copy.COPY_PART_SUFFIX)).exists()


def test_copy_file_atomic_rollback_when_temp_never_created(tmp_path: Path) -> None:
    src = tmp_path / "src.bin"
    src.write_bytes(b"x")
    dest = tmp_path / "dest.bin"

    def failing_copier(s: str, d: str) -> None:
        raise RuntimeError("failed before writing anything")

    with pytest.raises(RuntimeError, match="before writing"):
        project_copy.copy_file_atomic(str(src), str(dest), copier=failing_copier)
    assert not dest.exists()


# --------------------------------------------------------------------------- #
# ManagedStore.keep_copy — happy path + lineage re-point
# --------------------------------------------------------------------------- #
def test_keep_copy_copies_bytes_and_repoints_lineage(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"original-bytes")
    store = ManagedStore(lib)  # real copier + real blake3 + real disk_usage

    managed = store.keep_copy(src)

    # the managed copy exists under the data-root managed-copies folder ...
    managed_path = Path(managed["managedPath"])
    assert managed_path.parent == store.store_dir
    assert managed_path.read_bytes() == b"original-bytes"
    assert managed["originalPath"] == str(media.resolve())  # provenance recorded
    assert managed["contentHash"].startswith("blake3:")
    assert managed["sizeBytes"] == len(b"original-bytes")
    # lineage re-point: the entity is now authoritative-on the managed copy, and the
    # content hash is pinned (so a later hash-verified relink has a baseline).
    entity = lib.get(src)
    assert entity["path"] == str(managed_path)
    assert lib.lineage(src)["entity"]["contentHash"] == managed["contentHash"]


def test_keep_copy_is_idempotent_no_second_copy(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, _media = _add_source(lib, tmp_path, "talk.mp4", data=b"abc")
    calls: list[str] = []

    def counting_copier(s: str, d: str) -> None:
        calls.append(d)
        Path(d).write_bytes(Path(s).read_bytes())

    store = ManagedStore(lib, copier=counting_copier)
    first = store.keep_copy(src)
    second = store.keep_copy(src)  # idempotent: returns the existing row, no re-copy
    assert first == second
    assert len(calls) == 1


def test_keep_copy_unknown_video_is_loud(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    with pytest.raises(KeepCopyError, match="unknown video"):
        ManagedStore(lib).keep_copy("ghost")


def test_keep_copy_missing_source_file_is_loud(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"x")
    media.unlink()  # the source vanished before the opt-in copy
    with pytest.raises(KeepCopyError, match="source file .* is missing"):
        ManagedStore(lib).keep_copy(src)


def test_keep_copy_empty_source_path_is_loud(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, _media = _add_source(lib, tmp_path, "talk.mp4", data=b"x")
    with lib._open() as conn:  # force an empty by-path source (never resolvable)
        conn.execute("UPDATE entity SET path = '' WHERE id = ?", (src,))
    with pytest.raises(KeepCopyError, match="source file .* is missing"):
        ManagedStore(lib).keep_copy(src)


# --------------------------------------------------------------------------- #
# free-space preflight
# --------------------------------------------------------------------------- #
def test_keep_copy_preflight_fails_when_not_enough_space(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"four")  # 4 bytes
    copied: list[str] = []
    store = ManagedStore(
        lib,
        disk_usage=lambda _p: _free(1),  # only 1 free byte, need 4
        copier=lambda s, d: copied.append(d),
    )
    with pytest.raises(KeepCopyError, match="not enough free space"):
        store.keep_copy(src)
    # loud + no side effects: nothing copied, entity still points at the original.
    assert copied == []
    assert _entity_path(lib, src) == str(media.resolve())
    assert store.status()["count"] == 0


# --------------------------------------------------------------------------- #
# cumulative cap + LRU eviction
# --------------------------------------------------------------------------- #
def test_keep_copy_file_larger_than_cap_is_refused(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, _media = _add_source(lib, tmp_path, "big.mp4", data=b"0123456789")  # 10 bytes
    store = ManagedStore(lib, cap_bytes=4, copier=lambda s, d: None)
    with pytest.raises(KeepCopyError, match="exceeds the .*cap"):
        store.keep_copy(src)


def test_cap_evicts_least_recently_used_to_make_room(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, ma = _add_source(lib, tmp_path, "a.mp4", data=b"aaaa")  # 4 bytes, distinct
    b, mb = _add_source(lib, tmp_path, "b.mp4", data=b"bbbb")
    c, mc = _add_source(lib, tmp_path, "c.mp4", data=b"cccc")
    stamps = iter(["t0", "t1", "t2", "t3"])
    store = ManagedStore(
        lib,
        cap_bytes=10,  # holds two 4-byte copies, not three
        copier=lambda s, d: Path(d).write_bytes(Path(s).read_bytes()),
        now=lambda: next(stamps),
    )
    ka = store.keep_copy(a)  # store: {A}=4
    store.keep_copy(b)  # store: {A,B}=8
    store.keep_copy(c)  # 8+4>10 -> evict LRU (A) -> store: {B,C}=8

    status = store.status()
    kept = {e["entityId"] for e in status["entries"]}
    assert kept == {b, c}
    assert status["sizeBytes"] == 8
    # A was evicted: its managed file is gone and its entity reverts to the original.
    assert not Path(ka["managedPath"]).exists()
    assert _entity_path(lib, a) == str(ma.resolve())
    # B / C remain authoritative on their managed copies.
    assert _entity_path(lib, b) != str(mb.resolve())


# --------------------------------------------------------------------------- #
# content-hash dedup + shared-file eviction
# --------------------------------------------------------------------------- #
def test_dedup_reuses_the_one_managed_file_for_identical_content(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, _ma = _add_source(lib, tmp_path, "a.mp4", data=b"same-content")
    b, _mb = _add_source(lib, tmp_path, "b.mp4", data=b"same-content")  # byte-identical
    copies: list[str] = []
    store = ManagedStore(lib, copier=lambda s, d: (copies.append(d), Path(d).write_bytes(Path(s).read_bytes())))

    ka = store.keep_copy(a)
    kb = store.keep_copy(b)  # dedup hit: shares A's managed file, copies nothing new
    assert kb["managedPath"] == ka["managedPath"]
    assert len(copies) == 1  # only ONE physical copy for two entities
    status = store.status()
    assert status["count"] == 2
    assert status["sizeBytes"] == len(b"same-content")  # counted once


def test_evicting_a_shared_copy_keeps_bytes_until_last_referrer(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, ma = _add_source(lib, tmp_path, "a.mp4", data=b"shared")
    b, _mb = _add_source(lib, tmp_path, "b.mp4", data=b"shared")
    store = ManagedStore(lib, copier=lambda s, d: Path(d).write_bytes(Path(s).read_bytes()))
    ka = store.keep_copy(a)
    store.keep_copy(b)
    shared = Path(ka["managedPath"])

    store.evict(a)  # B still references the shared bytes -> file survives
    assert shared.exists()
    assert _entity_path(lib, a) == str(ma.resolve())  # A reverts to original

    store.evict(b)  # last referrer gone -> the bytes are freed
    assert not shared.exists()


# --------------------------------------------------------------------------- #
# atomic rollback through keep_copy (no corrupt managed file / no lineage change)
# --------------------------------------------------------------------------- #
def test_keep_copy_mid_write_failure_leaves_no_corrupt_state(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"payload")

    def failing_copier(s: str, d: str) -> None:
        Path(d).write_bytes(b"corrupt-partial")
        raise RuntimeError("write failed")

    store = ManagedStore(lib, copier=failing_copier)
    with pytest.raises(RuntimeError, match="write failed"):
        store.keep_copy(src)
    # no managed file, no managed row, no lineage re-point survived the failure.
    assert list(store.store_dir.glob("*")) == []
    assert store.status()["count"] == 0
    assert _entity_path(lib, src) == str(media.resolve())


# --------------------------------------------------------------------------- #
# status / evict / clear
# --------------------------------------------------------------------------- #
def test_status_exposes_size_cap_and_count(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    src, _media = _add_source(lib, tmp_path, "talk.mp4", data=b"abcd")
    store = ManagedStore(lib, cap_bytes=999, copier=lambda s, d: Path(d).write_bytes(Path(s).read_bytes()))
    assert store.status() == {"sizeBytes": 0, "capBytes": 999, "count": 0, "entries": []}
    store.keep_copy(src)
    after = store.status()
    assert after["sizeBytes"] == 4
    assert after["capBytes"] == 999
    assert after["count"] == 1


def test_evict_unknown_entity_is_loud(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    with pytest.raises(KeepCopyError, match="no managed copy to evict"):
        ManagedStore(lib).evict("ghost")


def test_clear_removes_every_managed_copy(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    a, ma = _add_source(lib, tmp_path, "a.mp4", data=b"aaa")
    b, mb = _add_source(lib, tmp_path, "b.mp4", data=b"bbb")
    store = ManagedStore(lib, copier=lambda s, d: Path(d).write_bytes(Path(s).read_bytes()))
    ka = store.keep_copy(a)
    kb = store.keep_copy(b)

    out = store.clear()
    assert out == {"ok": True, "cleared": 2}
    assert store.status()["count"] == 0
    assert not Path(ka["managedPath"]).exists()
    assert not Path(kb["managedPath"]).exists()
    assert _entity_path(lib, a) == str(ma.resolve())
    assert _entity_path(lib, b) == str(mb.resolve())


def test_clear_on_empty_store_is_a_noop(tmp_path: Path) -> None:
    lib = _fresh_library(tmp_path)
    assert ManagedStore(lib).clear() == {"ok": True, "cleared": 0}
