"""BR1 — the B-roll ASSET REGISTRY (``add_broll`` / ``list_broll`` / ``remove_broll``).

Before this unit there was no way to REGISTER a b-roll asset: ``broll.index`` /
``broll.suggest`` / ``broll.apply`` shipped with a working engine whose entire view
of the library was a recursive scan of the ``brollDir`` setting. This module covers
the registry (``role='broll'`` rows in the SAME ``entity`` table as the source
videos), the three ``broll.assets`` / ``broll.addAsset`` / ``broll.removeAsset``
handlers, and the UNION lister that feeds the already-wired engine.

Four things here are correctness claims rather than shape assertions, and each has
its own test because getting any of them wrong is silent:

* **The kind vocabulary is translated on the way out.** The DB stores the PROV
  kinds ``brollImage`` / ``brollClip``; ``broll_compose`` treats anything that is
  not the literal ``"video"`` as a still (``-loop 1``), so a row leaving the
  registry as ``brollClip`` would be composited as a frozen frame.
* **The registry row is index-compatible.** ``broll_index.fingerprint`` hashes
  ``path|sizeBytes|mtime``, so a registered row must carry the same stat fields a
  scanned row does — otherwise every registered asset reads as permanently stale.
* **Dedup is on the REAL path, not the path string.** ``scan_assets`` reports the
  configured folder with the relative parts joined on verbatim while ``add_broll``
  stores resolved text, so the SAME file can reach the two halves of the union
  under two different strings. The spelling exercised below is a ``..`` segment in
  ``brollDir``; letter case, a symlink, a relative folder and an 8.3 short
  component are the other sources. (Measured: ``tempfile.gettempdir()`` on this box
  IS the 8.3 short form, but pytest's ``tmp_path`` is already resolved — so the
  short-name case is real on the box and is NOT what these tests exercise.)
* **A registered asset whose file vanished is excluded from the lister** (it would
  be handed to the image tower) and surfaced as ``missing`` instead.

Stdlib only: the duration prober is injected, and the wired tests register ``.png``
images so no ffprobe subprocess is ever spawned.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from media_studio import library as _library
from media_studio.features import broll_index, broll_ops
from media_studio.handlers import Services, register_all
from media_studio.handlers import library_ops as _library_ops
from media_studio.library import Library
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def lib(tmp_path: Path) -> Library:
    """A Library whose duration prober is a stub (never a real ffprobe)."""
    return Library(tmp_path / "library.json", probe_duration=lambda _p: 4.25)


@pytest.fixture
def still(tmp_path: Path) -> Path:
    p = tmp_path / "assets" / "a dog.PNG"  # upper-case ext + a space, on purpose
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG-not-really")
    return p


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    p = tmp_path / "assets" / "city.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00\x00not-really-a-clip")
    return p


def _ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda _obj: None, jobs=None)


@pytest.fixture
def wired(tmp_path: Path):
    """``(handlers, services)`` from the REAL composition root, tmp-dir backed."""
    collected: dict[str, Any] = {}
    services = Services(data_dir=tmp_path / "data")
    register_all(services, register=lambda name, handler: collected.__setitem__(name, handler))
    return collected, services


# --------------------------------------------------------------------------- #
# Library.add_broll
# --------------------------------------------------------------------------- #
def test_add_broll_returns_the_full_asset_row(lib: Library, still: Path):
    asset = lib.add_broll(str(still))
    assert set(asset) == {
        "assetId",
        "path",
        "kind",
        "entityKind",
        "title",
        "addedAt",
        "durationSec",
        "contentHash",
        "thumbnailPath",
        "sizeBytes",
        "mtime",
        "exists",
        "registered",
    }
    assert asset["entityKind"] == _library.BROLL_IMAGE_KIND
    assert asset["kind"] == "image"
    assert asset["title"] == "a dog"  # stem default
    assert asset["registered"] is True
    assert asset["exists"] is True
    assert asset["contentHash"] is None  # BR1 surfaces the column; BR2 populates it
    assert asset["thumbnailPath"] == ""
    assert Path(asset["path"]).name == "a dog.PNG"


def test_add_broll_classifies_a_clip_and_probes_its_duration(lib: Library, clip: Path):
    asset = lib.add_broll(str(clip))
    assert asset["entityKind"] == _library.BROLL_CLIP_KIND
    assert asset["kind"] == "video"  # the compose vocabulary, NOT the entity kind
    assert asset["durationSec"] == 4.25  # the injected prober ran


def test_add_broll_does_not_probe_a_still(tmp_path: Path, still: Path):
    """An image has no duration; probing one would be a pointless ffprobe spawn."""
    probed: list[str] = []

    def probe(path: str) -> float:
        probed.append(path)
        return 9.0

    asset = Library(tmp_path / "library.json", probe_duration=probe).add_broll(str(still))
    assert probed == []
    assert asset["durationSec"] == 0.0


def test_add_broll_survives_a_failing_duration_probe(tmp_path: Path, clip: Path):
    """A probe failure must not block registration (mirrors Library.add)."""

    def boom(_path: str) -> float:
        raise OSError("ffprobe missing")

    asset = Library(tmp_path / "library.json", probe_duration=boom).add_broll(str(clip))
    assert asset["durationSec"] == 0.0
    assert asset["entityKind"] == _library.BROLL_CLIP_KIND


def test_add_broll_custom_title(lib: Library, still: Path):
    assert lib.add_broll(str(still), title="Hero shot")["title"] == "Hero shot"


def test_add_broll_is_idempotent_by_resolved_path(lib: Library, still: Path):
    first = lib.add_broll(str(still))
    second = lib.add_broll(str(still), title="ignored on re-register")
    assert second == first
    assert len(lib.list_broll()) == 1


def test_add_broll_missing_file_raises(lib: Library, tmp_path: Path):
    with pytest.raises(_library.BrollAssetError, match="not found"):
        lib.add_broll(str(tmp_path / "nope.png"))


def test_add_broll_unsupported_extension_raises(lib: Library, tmp_path: Path):
    notes = tmp_path / "notes.txt"
    notes.write_text("not b-roll", encoding="utf-8")
    with pytest.raises(_library.BrollAssetError, match="not a b-roll"):
        lib.add_broll(str(notes))


def test_add_broll_accepts_exactly_what_the_folder_scan_accepts(lib: Library, tmp_path: Path):
    """The accepted extension set is READ from the scanner, never restated.

    A second copy could drift, and then a file the scan happily indexes would be
    refused by addAsset (or the reverse) — so assert against the scanner's own sets.
    """
    for ext in sorted(broll_ops.IMAGE_EXTS | broll_ops.VIDEO_EXTS):
        f = tmp_path / f"asset{ext}"
        f.write_bytes(b"x")
        registered = lib.add_broll(str(f))
        assert registered["kind"] == ("image" if ext in broll_ops.IMAGE_EXTS else "video")


# --------------------------------------------------------------------------- #
# role isolation — a b-roll asset is NOT a source video and vice versa
# --------------------------------------------------------------------------- #
def test_a_registered_broll_asset_never_appears_in_the_source_video_list(lib: Library, clip: Path):
    lib.add_broll(str(clip))
    assert lib.list() == []
    assert lib.get(_library.broll_asset_id(str(clip.resolve()))) is None


def test_a_source_video_never_appears_in_the_broll_list(lib: Library, clip: Path):
    lib.add(str(clip))
    assert lib.list_broll() == []


def test_remove_broll_cannot_delete_a_source_video_row(lib: Library, clip: Path):
    video = lib.add(str(clip))
    assert lib.remove_broll(video["id"]) is False
    assert len(lib.list()) == 1


# --------------------------------------------------------------------------- #
# Library.list_broll
# --------------------------------------------------------------------------- #
def test_list_broll_is_empty_on_a_fresh_library(lib: Library):
    assert lib.list_broll() == []


def test_list_broll_preserves_registration_order(lib: Library, still: Path, clip: Path):
    lib.add_broll(str(clip))
    lib.add_broll(str(still))
    assert [Path(a["path"]).name for a in lib.list_broll()] == ["city.mp4", "a dog.PNG"]


def test_list_broll_reports_a_vanished_file_without_fabricating_a_size(lib: Library, still: Path):
    lib.add_broll(str(still))
    still.unlink()
    (gone,) = lib.list_broll()
    assert gone["exists"] is False
    assert gone["sizeBytes"] == 0
    assert gone["mtime"] == 0.0


def test_a_registered_row_fingerprints_IDENTICALLY_to_the_scanned_row(tmp_path: Path):
    """The registry row is index-compatible: same file -> same staleness key.

    ``broll_index.fingerprint`` hashes ``path|sizeBytes|mtime``. If a registered row
    omitted (or mis-typed) the stat fields, ``broll.status`` would report every
    registered asset stale forever and ``broll.index`` would re-embed it every run.

    Scoped claim: the two fingerprints coincide when the scanned folder is already
    an absolute RESOLVED path (so the two halves spell the file the same way). The
    union's dedup does NOT rely on that — see the real-path dedup test below.
    """
    folder = (tmp_path / "broll").resolve()
    folder.mkdir(parents=True)
    (folder / "dog.png").write_bytes(b"pixels")

    (scanned,) = broll_ops.scan_assets(str(folder))
    registered = Library(tmp_path / "library.json").add_broll(str(folder / "dog.png"))
    assert broll_index.fingerprint(registered) == broll_index.fingerprint(scanned)
    assert registered["assetId"] == scanned["assetId"]


# --------------------------------------------------------------------------- #
# Library.remove_broll
# --------------------------------------------------------------------------- #
def test_remove_broll_unregisters_the_asset_and_keeps_the_file(lib: Library, still: Path):
    asset = lib.add_broll(str(still))
    assert lib.remove_broll(asset["assetId"]) is True
    assert lib.list_broll() == []
    assert still.exists(), "the USER's file must never be deleted by an unregister"


def test_remove_broll_is_false_for_an_unknown_id(lib: Library):
    assert lib.remove_broll("deadbeefdeadbeef") is False


# --------------------------------------------------------------------------- #
# the UNION lister (what broll.index / status / suggest actually see)
# --------------------------------------------------------------------------- #
def test_the_union_lister_is_the_folder_scan_when_nothing_is_registered(wired, tmp_path: Path):
    _handlers, services = wired
    folder = tmp_path / "scan-only"
    folder.mkdir()
    (folder / "dog.png").write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})
    rows = _library_ops.broll_asset_rows(services)
    assert [Path(r["path"]).name for r in rows] == ["dog.png"]
    assert rows[0]["registered"] is False


def test_the_union_lister_adds_a_registered_asset_from_OUTSIDE_the_folder(wired, tmp_path: Path):
    _handlers, services = wired
    folder = tmp_path / "scanned"
    folder.mkdir()
    (folder / "dog.png").write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})
    elsewhere = tmp_path / "elsewhere" / "city.jpg"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"y")
    services.library.add_broll(str(elsewhere))

    rows = _library_ops.broll_asset_rows(services)
    assert sorted(Path(r["path"]).name for r in rows) == ["city.jpg", "dog.png"]
    assert {r["registered"] for r in rows} == {True, False}


def test_the_union_dedups_on_the_REAL_path_not_the_path_string(wired, tmp_path: Path):
    """One file, two spellings, ONE row — the registered one.

    ``scan_assets`` reports each file as the configured folder with the relative
    parts joined on, verbatim; ``add_broll`` stores ``Path.resolve()``'d text. So a
    ``brollDir`` carrying a ``..`` segment (as used here) makes the SAME file arrive
    at the two halves of the union under two different strings, and a string-keyed
    dedup would count it twice and embed it twice.
    """
    _handlers, services = wired
    folder = tmp_path / "scanned"
    folder.mkdir()
    dog = folder / "dog.png"
    dog.write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder / ".." / "scanned")})
    registered = services.library.add_broll(str(dog), title="Hero dog")
    # Precondition of the test: the two halves really do spell it differently.
    # (Without this assertion the test would still pass on a tree where the two
    # spellings happen to coincide, and would then be measuring nothing.)
    (scanned,) = broll_ops.scan_assets(str(folder / ".." / "scanned"))
    assert scanned["path"] != registered["path"]

    rows = _library_ops.broll_asset_rows(services)
    assert len(rows) == 1
    assert rows[0]["title"] == "Hero dog"  # the REGISTERED row won the collision
    assert rows[0]["registered"] is True


def test_the_union_excludes_a_registered_asset_whose_file_vanished(wired, tmp_path: Path):
    """A vanished path must never reach broll.index (it would fail the job)."""
    _handlers, services = wired
    gone = tmp_path / "gone.png"
    gone.write_bytes(b"x")
    services.library.add_broll(str(gone))
    assert len(_library_ops.broll_asset_rows(services)) == 1
    gone.unlink()
    assert _library_ops.broll_asset_rows(services) == []


# --------------------------------------------------------------------------- #
# the three handlers
# --------------------------------------------------------------------------- #
def test_broll_assets_returns_the_union_plus_a_loud_missing_list(wired, tmp_path: Path):
    handlers, services = wired
    here = tmp_path / "here.png"
    here.write_bytes(b"x")
    gone = tmp_path / "gone.png"
    gone.write_bytes(b"y")
    services.library.add_broll(str(here))
    services.library.add_broll(str(gone))
    gone.unlink()

    out = handlers["broll.assets"]({}, _ctx())
    assert [Path(a["path"]).name for a in out["assets"]] == ["here.png"]
    assert [Path(a["path"]).name for a in out["missing"]] == ["gone.png"]
    assert out["missing"][0]["exists"] is False


def test_broll_assets_partitions_ONE_registry_snapshot(wired, tmp_path: Path):
    """Every registered asset is in exactly one of ``assets`` / ``missing``.

    The two halves must come from a SINGLE ``list_broll()`` read. With two reads an
    asset deleted in between lands in BOTH, and one restored in between lands in
    NEITHER — silently gone from the payload, which is the exact failure ``missing``
    exists to prevent. Pinned by counting the reads: exactly one per call.
    """
    _handlers, services = wired
    reads: list[int] = []
    real_list = services.library.list_broll

    def counted() -> list[dict[str, Any]]:
        reads.append(1)
        return real_list()

    for name in ("a.png", "b.png", "c.png"):
        f = tmp_path / name
        f.write_bytes(b"x")
        services.library.add_broll(str(f))
    (tmp_path / "b.png").unlink()

    services.library.list_broll = counted  # type: ignore[method-assign]
    out = _library_ops.broll_assets(services, {}, _ctx())
    assert sum(reads) == 1, "the registry must be read exactly once per broll.assets"

    registered_ids = {a["assetId"] for a in real_list()}
    present = {a["assetId"] for a in out["assets"] if a["registered"]}
    missing = {a["assetId"] for a in out["missing"]}
    assert present | missing == registered_ids  # nothing lost
    assert present & missing == set()  # nothing double-reported
    assert len(missing) == 1


def test_broll_add_asset_registers_and_returns_the_asset(wired, tmp_path: Path):
    handlers, services = wired
    png = tmp_path / "dog.png"
    png.write_bytes(b"x")
    out = handlers["broll.addAsset"]({"path": str(png), "title": "Dog"}, _ctx())
    assert out["asset"]["title"] == "Dog"
    assert [a["assetId"] for a in services.library.list_broll()] == [out["asset"]["assetId"]]


def test_broll_add_asset_ignores_a_non_string_title(wired, tmp_path: Path):
    handlers, _services = wired
    png = tmp_path / "dog.png"
    png.write_bytes(b"x")
    out = handlers["broll.addAsset"]({"path": str(png), "title": 7}, _ctx())
    assert out["asset"]["title"] == "dog"  # fell back to the stem


def test_broll_add_asset_requires_a_path(wired):
    handlers, _services = wired
    with pytest.raises(RpcError, match="path"):
        handlers["broll.addAsset"]({}, _ctx())


def test_broll_add_asset_turns_a_refusal_into_invalid_params(wired, tmp_path: Path):
    handlers, _services = wired
    with pytest.raises(RpcError, match="not found"):
        handlers["broll.addAsset"]({"path": str(tmp_path / "nope.png")}, _ctx())


def test_broll_remove_asset_unregisters(wired, tmp_path: Path):
    handlers, services = wired
    png = tmp_path / "dog.png"
    png.write_bytes(b"x")
    asset = services.library.add_broll(str(png))
    assert handlers["broll.removeAsset"]({"id": asset["assetId"]}, _ctx()) == {"ok": True}
    assert services.library.list_broll() == []
    assert handlers["broll.removeAsset"]({"id": asset["assetId"]}, _ctx()) == {"ok": False}


def test_broll_remove_asset_requires_an_id(wired):
    handlers, _services = wired
    with pytest.raises(RpcError, match="id"):
        handlers["broll.removeAsset"]({}, _ctx())


# --------------------------------------------------------------------------- #
# composition-root wiring: the registry reaches the ALREADY-WIRED engine
# --------------------------------------------------------------------------- #
def test_a_registered_asset_is_counted_by_the_wired_broll_status(wired, tmp_path: Path):
    """The point of the whole unit: registration feeds the existing engine.

    ``broll.status.libraryCount`` comes from the ``list_assets`` seam handed to
    ``broll_ops.register``. If the registry were a parallel store, this stays 0.
    """
    handlers, services = wired
    assert handlers["broll.status"]({}, _ctx())["libraryCount"] == 0
    png = tmp_path / "outside-any-folder.png"
    png.write_bytes(b"x")
    services.library.add_broll(str(png))
    assert handlers["broll.status"]({}, _ctx())["libraryCount"] == 1


def test_the_registry_methods_never_enter_the_key_injection_allowlist(wired):
    """broll.* is LOCAL-only: no provider, so no key may ever be injected."""
    handlers, _services = wired
    prefixes = ("ai.", "director.", "shortmaker.", "index.")
    exact = {
        "subtitles.translate",
        "providers.usage",
        "providers.openrouterUsage",
        "providers.revealKey",
        "thumbnail.select",
        "phase8.select",
        "recipes.run",
        "templates.apply",
        "batch.start",
        "batch.resume",
    }
    for name in ("broll.assets", "broll.addAsset", "broll.removeAsset"):
        assert name in handlers
        assert not name.startswith(prefixes)
        assert name not in exact


def test_the_real_path_dedup_key_collapses_short_names_and_dot_segments(tmp_path: Path):
    """Control for the dedup key itself: it must see through both spellings."""
    folder = tmp_path / "b"
    folder.mkdir()
    dog = folder / "dog.png"
    dog.write_bytes(b"x")
    weird = str(folder / ".." / "b" / "dog.png")
    assert weird != str(dog)
    assert _library_ops._real_key(weird) == _library_ops._real_key(str(dog.resolve()))
    assert _library_ops._real_key(weird) == os.path.normcase(os.path.realpath(str(dog)))
