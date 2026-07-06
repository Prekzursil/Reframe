"""L5 tests — reveal source / regenerate-from-source / hash-verified relink.

The pure digest helpers and the source-resolution walk are unit-tested in
isolation; the four DB operations run end-to-end against a REAL temp-file SQLite
store (never an in-memory shim). The whole-file hash is exercised BOTH through an
injected ``hash_file`` seam (deterministic, no bytes read) AND through the default
:func:`media_studio.relink.blake3_file` against tiny temp files, so the default
reader (and its loud missing-package branch) are covered without reading large
media. GATE L5: a relink re-points ONLY on an exact whole-file BLAKE3 match —
``(size, mtime)`` is never accepted, and an unverifiable/mismatched relink fails
loud.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
from media_studio import relink
from media_studio.library import Library


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fresh_library(tmp_path: Path) -> Library:
    return Library(tmp_path / "library.json", probe_duration=lambda _p: 0.0)


def _add_source(lib: Library, tmp_path: Path, name: str, data: bytes = b"\x00") -> tuple[str, Path]:
    media = tmp_path / name
    media.write_bytes(data)
    vid = lib.add(str(media))["id"]
    return vid, media


def _record_short(lib: Library, *, src_id: str, clip_id: str) -> None:
    lib.record_lineage(
        type(
            "J",
            (),
            {
                "id": "j1",
                "status": type("S", (), {"value": "done"})(),
                "request": {"method": "shorts.select", "params": {"preset": "punchy"}},
            },
        )(),
        inputs=[{"id": src_id}],
        outputs=[{"id": clip_id, "kind": "short", "path": "/exports/clip.mp4"}],
        agent={"appVersion": "1.1.0", "route": {"mode": "local"}},
    )


# --------------------------------------------------------------------------- #
# pure digest helpers
# --------------------------------------------------------------------------- #
def test_format_digest_prefixes_and_lowercases():
    assert relink.format_digest("ABCD1234") == "blake3:abcd1234"


def test_format_digest_strips_whitespace():
    assert relink.format_digest("  ABCD  ") == "blake3:abcd"


def test_digests_match_equal():
    assert relink.digests_match("blake3:abc", "blake3:ABC") is True


def test_digests_match_whitespace_insensitive():
    assert relink.digests_match(" blake3:abc ", "blake3:abc") is True


def test_digests_match_unequal():
    assert relink.digests_match("blake3:abc", "blake3:def") is False


# --------------------------------------------------------------------------- #
# blake3_file + content_hash_of (default reader + injected seam)
# --------------------------------------------------------------------------- #
def test_blake3_file_streams_real_bytes_deterministically(tmp_path: Path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"identical-bytes")
    b.write_bytes(b"identical-bytes")
    assert relink.blake3_file(str(a)) == relink.blake3_file(str(b))
    c = tmp_path / "c.bin"
    c.write_bytes(b"different")
    assert relink.blake3_file(str(c)) != relink.blake3_file(str(a))


def test_blake3_file_large_input_multi_chunk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Force the streaming loop to iterate >1 chunk (tiny chunk size).
    monkeypatch.setattr(relink, "_HASH_CHUNK", 4)
    big = tmp_path / "big.bin"
    big.write_bytes(b"0123456789abcdef")  # 16 bytes -> 4 chunks of 4
    assert relink.blake3_file(str(big)).startswith("")  # hex string, non-empty
    assert len(relink.blake3_file(str(big))) == 64  # blake3 default = 32 bytes = 64 hex


def test_blake3_file_missing_package_fails_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    f = tmp_path / "f.bin"
    f.write_bytes(b"x")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "blake3":
            raise ImportError("no blake3")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(relink.RelinkError, match="blake3.*not installed"):
        relink.blake3_file(str(f))


def test_content_hash_of_uses_injected_seam_and_prefixes(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"x")
    digest = relink.content_hash_of(str(f), hash_file=lambda _p: "DEADBEEF")
    assert digest == "blake3:deadbeef"


def test_content_hash_of_missing_file_is_loud(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        relink.content_hash_of(str(tmp_path / "nope.bin"), hash_file=lambda _p: "x")


def test_content_hash_of_default_reader(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello")
    assert relink.content_hash_of(str(f)).startswith("blake3:")


# --------------------------------------------------------------------------- #
# reveal_source
# --------------------------------------------------------------------------- #
def test_reveal_source_for_a_present_source_itself(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    out = relink.reveal_source(lib, src)
    assert out["id"] == src
    assert len(out["sources"]) == 1
    assert out["sources"][0]["id"] == src
    assert out["sources"][0]["path"] == str(media.resolve())
    assert out["sources"][0]["exists"] is True
    # A freshly-added source has NULL content_hash (pinned lazily on view).
    assert out["sources"][0]["relinkable"] is False
    assert out["missing"] == []


def test_reveal_source_relinkable_true_after_pin(tmp_path: Path):
    # Once a whole-file hash is pinned, reveal reports the source as relinkable
    # (a hash-verified relink now has a baseline to match against).
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    relink.pin_source_hash(lib, src)
    out = relink.reveal_source(lib, src)
    assert out["sources"][0]["relinkable"] is True


def test_reveal_source_for_a_derived_short_resolves_its_source(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    _record_short(lib, src_id=src, clip_id="clip1")
    out = relink.reveal_source(lib, "clip1")
    assert [s["id"] for s in out["sources"]] == [src]
    assert out["missing"] == []


def test_reveal_source_flags_a_missing_source_loudly(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    media.unlink()  # the source file moved/deleted on disk
    out = relink.reveal_source(lib, src)
    assert out["sources"][0]["exists"] is False
    assert out["missing"] == [str(media.resolve())]


def test_reveal_source_unknown_id_raises(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    with pytest.raises(relink.RelinkError, match="unknown asset"):
        relink.reveal_source(lib, "ghost")


def test_reveal_source_excludes_non_source_and_stub_ancestors(tmp_path: Path):
    # A derived clip whose ONLY recorded input is an id with no entity row
    # (a stub) -> no on-disk source resolves; sources is empty (loud-missing
    # handled by the lineage stub view, not reveal).
    lib = _fresh_library(tmp_path)
    _record_short(lib, src_id="never-added", clip_id="clip1")
    out = relink.reveal_source(lib, "clip1")
    assert out["sources"] == []
    assert out["missing"] == []


# --------------------------------------------------------------------------- #
# regenerate
# --------------------------------------------------------------------------- #
def test_regenerate_ready_when_source_present(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    _record_short(lib, src_id=src, clip_id="clip1")
    out = relink.regenerate(lib, "clip1")
    assert out["id"] == "clip1"
    assert out["op"] == "shorts.select"
    assert out["params"] == {"preset": "punchy"}
    assert out["missing"] == []
    assert out["ready"] is True


def test_regenerate_not_ready_when_source_missing(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    _record_short(lib, src_id=src, clip_id="clip1")
    media.unlink()
    out = relink.regenerate(lib, "clip1")
    assert out["ready"] is False
    assert out["missing"] == [str(media.resolve())]


def test_regenerate_raw_source_has_nothing_to_regenerate(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    with pytest.raises(relink.RelinkError, match="nothing to regenerate"):
        relink.regenerate(lib, src)


def test_regenerate_unknown_id_raises(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    with pytest.raises(relink.RelinkError, match="unknown asset"):
        relink.regenerate(lib, "ghost")


# --------------------------------------------------------------------------- #
# pin_source_hash
# --------------------------------------------------------------------------- #
def test_pin_source_hash_records_the_digest(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    updated = relink.pin_source_hash(lib, src, hash_file=lambda _p: "CAFE")
    assert updated["contentHash"] == "blake3:cafe"
    # persisted: lineage_of reads it back from the row.
    assert lib.lineage(src)["entity"]["contentHash"] == "blake3:cafe"


def test_pin_source_hash_unknown_id_raises(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    with pytest.raises(relink.RelinkError, match="unknown asset"):
        relink.pin_source_hash(lib, "ghost")


def test_pin_source_hash_missing_file_is_loud(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    media.unlink()
    with pytest.raises(FileNotFoundError, match="cannot pin a content hash"):
        relink.pin_source_hash(lib, src, hash_file=lambda _p: "x")


# --------------------------------------------------------------------------- #
# relink — hash-verified re-point
# --------------------------------------------------------------------------- #
def test_relink_repoints_on_matching_hash(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"same-content")
    relink.pin_source_hash(lib, src)  # real blake3 baseline
    # The same content moved to a new location.
    moved = tmp_path / "moved" / "talk.mp4"
    moved.parent.mkdir()
    moved.write_bytes(b"same-content")
    updated = relink.relink(lib, src, str(moved))
    assert updated["path"] == str(moved.resolve())
    assert lib.get(src)["path"] == str(moved.resolve())


def test_relink_refuses_on_hash_mismatch(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"original")
    relink.pin_source_hash(lib, src)
    wrong = tmp_path / "wrong.mp4"
    wrong.write_bytes(b"a totally different file")
    with pytest.raises(relink.RelinkVerificationError, match="does not match"):
        relink.relink(lib, src, str(wrong))
    # path is unchanged after a refused relink.
    assert lib.get(src)["path"] == str(media.resolve())


def test_relink_requires_a_recorded_hash(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")  # no pin -> content_hash NULL
    other = tmp_path / "other.mp4"
    other.write_bytes(b"x")
    with pytest.raises(relink.RelinkVerificationError, match="no recorded content hash"):
        relink.relink(lib, src, str(other))


def test_relink_new_path_missing_is_loud(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4")
    relink.pin_source_hash(lib, src)
    with pytest.raises(FileNotFoundError, match="cannot relink to a file"):
        relink.relink(lib, src, str(tmp_path / "ghost.mp4"))


def test_relink_unknown_id_raises(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    target = tmp_path / "t.mp4"
    target.write_bytes(b"x")
    with pytest.raises(relink.RelinkError, match="unknown asset"):
        relink.relink(lib, "ghost", str(target))


# --------------------------------------------------------------------------- #
# Library façade delegation (lazy-import seam)
# --------------------------------------------------------------------------- #
def test_library_facade_reveal_regenerate_relink(tmp_path: Path):
    lib = _fresh_library(tmp_path)
    src, media = _add_source(lib, tmp_path, "talk.mp4", data=b"facade")
    _record_short(lib, src_id=src, clip_id="clip1")
    assert lib.reveal_source(src)["sources"][0]["id"] == src
    assert lib.regenerate("clip1")["op"] == "shorts.select"
    pinned = lib.pin_source_hash(src)
    assert pinned["contentHash"].startswith("blake3:")
    moved = tmp_path / "moved.mp4"
    moved.write_bytes(b"facade")
    assert lib.relink(src, str(moved))["path"] == str(moved.resolve())
