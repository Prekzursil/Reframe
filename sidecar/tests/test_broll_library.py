"""BR1 — the B-roll ASSET REGISTRY (``add_broll`` / ``list_broll`` / ``remove_broll``).

Before this unit there was no way to REGISTER a b-roll asset: ``broll.index`` /
``broll.suggest`` / ``broll.apply`` shipped with a working engine whose entire view
of the library was a recursive scan of the ``brollDir`` setting. This module covers
the registry (``role='broll'`` rows in the SAME ``entity`` table as the source
videos), the three ``broll.assets`` / ``broll.addAsset`` / ``broll.removeAsset``
handlers, and the UNION lister that feeds the already-wired engine.

Six things here are correctness claims rather than shape assertions, and each has
its own test because getting any of them wrong is silent:

* **The registry door admits exactly what the folder scan admits** — BOTH of the
  scanner's gates, not just the extension set. ``add_broll`` originally checked only
  ``src.exists()``, which is TRUE for a directory, so ``mkdir album.png`` registered as
  a b-roll IMAGE and reached ``broll.index``' embed plan, where the batched image tower
  fails the WHOLE job on one unopenable path.
* **The dedup survives an EMPTY registry.** A junction inside ``brollDir`` makes the
  SCAN itself emit one file twice (measured: ``os.path.islink`` is False for a junction
  and ``rglob`` descends into it), so the union may not short-circuit when nothing is
  registered — only memoise the ``realpath`` per directory.

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
import re
from pathlib import Path
from typing import Any

import pytest
from media_studio import library as _library
from media_studio.features import broll_index, broll_ops
from media_studio.handlers import Services, register_all
from media_studio.handlers import library_ops as _library_ops
from media_studio.library import Library
from media_studio.protocol import RpcContext, RpcError

#: sidecar/tests/<this file> -> sidecar/tests -> sidecar -> <repo root>. The
#: key-injection allowlist is READ from here rather than transcribed (see
#: :func:`test_the_registry_methods_are_absent_from_the_REAL_key_injection_allowlist`);
#: ``test_director_op_kind_parity.py`` establishes this cross-language-read pattern.
_KEY_BRIDGE_TS = Path(__file__).resolve().parents[2] / "app" / "main" / "keyBridge.ts"


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


def test_add_broll_accepts_the_same_extension_sets_as_the_folder_scan(lib: Library, tmp_path: Path):
    """The accepted extension SET is READ from the scanner, never restated.

    A second copy could drift, and then a file the scan happily indexes would be
    refused by addAsset (or the reverse) — so assert against the scanner's own sets.

    Scoped deliberately: this covers the extension sets ONLY, which is all it ever
    measured. The scanner's OTHER gate — ``path.is_file()`` — is asserted by
    :func:`test_add_broll_refuses_a_DIRECTORY_named_like_an_image` and
    :func:`test_the_registry_door_and_the_folder_scan_refuse_THE_SAME_directory`.
    (The earlier name, ``..._accepts_exactly_what_the_folder_scan_accepts``, was
    REFUTED: it claimed full acceptance parity while the is_file half was missing.)
    """
    for ext in sorted(broll_ops.IMAGE_EXTS | broll_ops.VIDEO_EXTS):
        f = tmp_path / f"asset{ext}"
        f.write_bytes(b"x")
        registered = lib.add_broll(str(f))
        assert registered["kind"] == ("image" if ext in broll_ops.IMAGE_EXTS else "video")


def test_add_broll_refuses_a_DIRECTORY_named_like_an_image(lib: Library, tmp_path: Path):
    """The scanner's ``is_file()`` gate, reproduced at the registry door.

    ``scan_assets`` skips anything that is not ``path.is_file()``
    (``features/broll_ops.py``); ``add_broll`` used to gate only on ``src.exists()``,
    which is TRUE for a directory. Measured before the fix, end to end against the
    real composition root: ``broll.addAsset(<dir album.png>)`` -> ACCEPTED
    ``kind='image' exists=True sizeBytes=0``; it then passed the union lister's
    ``exists`` filter (``os.stat`` of a directory succeeds), and ``broll.status``
    reported ``libraryCount=3 staleCount=3`` — and ``staleCount`` IS
    ``len(refresh_plan()['embed'])``, verbatim the list ``broll.index`` hands to the
    image tower, where ``open()`` on that path raises ``PermissionError``. One bad row
    fails the WHOLE index job because the tower stacks the batch, so this is a
    library-wide failure, not a per-asset one.
    """
    bogus = tmp_path / "album.png"
    bogus.mkdir()
    with pytest.raises(_library.BrollAssetError, match="not a file"):
        lib.add_broll(str(bogus))
    assert lib.list_broll() == []


def test_the_registry_door_and_the_folder_scan_refuse_THE_SAME_directory(wired, tmp_path: Path):
    """Acceptance parity asserted by RUNNING both gates over one tree, not by prose.

    The control is in the same run: both gates ACCEPT ``real.png``, so a zero from
    either of them is a refusal and not a broken probe.
    """
    handlers, services = wired
    folder = tmp_path / "scanned"
    folder.mkdir()
    (folder / "real.png").write_bytes(b"x")
    bogus = folder / "album.png"
    bogus.mkdir()
    # control: the scanner takes the real file and skips the directory
    assert [Path(a["path"]).name for a in broll_ops.scan_assets(str(folder))] == ["real.png"]
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})
    # control: the SAME door takes the real file
    assert handlers["broll.addAsset"]({"path": str(folder / "real.png")}, _ctx())["asset"]["kind"] == "image"
    with pytest.raises(RpcError, match="not a file"):
        handlers["broll.addAsset"]({"path": str(bogus)}, _ctx())
    assert [Path(r["path"]).name for r in _library_ops.broll_asset_rows(services)] == ["real.png"]


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


def test_a_registered_asset_lands_in_the_index_EMBED_PLAN(wired, tmp_path: Path):
    """Stronger than a count: the registry participates in INCREMENTAL indexing.

    Build a real index sidecar covering ONLY the scanned file, so ``broll.status``
    honestly reports ``stale=False, staleCount=0``. Registering an asset from OUTSIDE
    ``brollDir`` must then raise ``staleCount`` to 1 — and ``staleCount`` is
    ``len(refresh_plan()['embed'])``, which is verbatim the list ``broll.index`` hands
    to the image tower. A registry that were a parallel store would leave it at 0.

    No weights are involved: the vector is a hand-written 2-D literal, so this runs in
    the gate env. UNVERIFIED (out of scope here): whether the real SigLIP-2 tower then
    produces a useful vector for that asset — the settling experiment is design BR8's
    real-model tier.
    """
    handlers, services = wired
    folder = tmp_path / "scanned"
    folder.mkdir()
    (folder / "dog.png").write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})

    scanned = broll_ops.scan_assets(str(folder))
    broll_ops.save_index_file(
        services.data_dir / broll_ops.INDEX_FILENAME,
        broll_index.build(scanned, [[0.0, 1.0]], model=broll_ops.DEFAULT_MODEL_ID, built_at="t"),
    )
    before = handlers["broll.status"]({}, _ctx())
    assert (before["stale"], before["staleCount"], before["libraryCount"]) == (False, 0, 1)

    city = tmp_path / "outside" / "city.jpg"
    city.parent.mkdir()
    city.write_bytes(b"y")
    services.library.add_broll(str(city))

    after = handlers["broll.status"]({}, _ctx())
    assert (after["stale"], after["staleCount"], after["libraryCount"]) == (True, 1, 2)


def test_the_registry_methods_are_absent_from_the_REAL_key_injection_allowlist(wired):
    """broll.* is LOCAL-only: no provider, so no key may ever be injected.

    This reads the ACTUAL allowlist out of ``app/main/keyBridge.ts`` — the file whose
    ``INJECT_PREFIXES`` / ``INJECT_METHODS`` literals ``needsKeyInjection()`` consults
    — instead of comparing against a second copy transcribed here. The previous
    version of this test hardcoded both literals, so two of its three assertions were
    constant-true over its own constants and adding ``broll.assets`` to the real
    allowlist could never have turned it red: it was REFUTED as a gate that cannot
    fail, and this is the replacement.

    Detector control (asserted below before the real claim): the parse must find the
    four known prefix families and the known-present ``subtitles.translate`` entry. A
    regex that silently matched nothing would otherwise yield empty sets that every
    method trivially passes.

    Scope: this pins the DECLARED literals. It does not EXECUTE
    ``needsKeyInjection()`` — that is ``app/main/keyBridge.test.ts``' job, and
    measured on this branch that suite's "is false for non-provider methods" list
    contains no ``broll.*`` case (UNVERIFIED whether a later lane adds one; the
    settling experiment is a grep of ``keyBridge.test.ts`` for ``broll.``).
    """
    handlers, _services = wired
    source = _KEY_BRIDGE_TS.read_text(encoding="utf-8")
    prefix_match = re.search(r"const INJECT_PREFIXES[^=]*=\s*\[(.*?)\];", source, re.DOTALL)
    methods_match = re.search(r"const INJECT_METHODS[^=]*=\s*new Set\(\[(.*?)\]\);", source, re.DOTALL)
    assert prefix_match is not None, f"INJECT_PREFIXES not found in {_KEY_BRIDGE_TS} — update this gate, don't drop it"
    assert methods_match is not None, f"INJECT_METHODS not found in {_KEY_BRIDGE_TS} — update this gate, don't drop it"
    prefixes = tuple(re.findall(r"'([^']+)'", prefix_match.group(1)))
    exact = set(re.findall(r"'([^']+)'", methods_match.group(1)))
    # --- detector control: the parse really did read the live allowlist ---------
    assert prefixes == ("ai.", "director.", "shortmaker.", "index.")
    assert "subtitles.translate" in exact and "providers.revealKey" in exact
    # --- the claim -------------------------------------------------------------
    for name in ("broll.assets", "broll.addAsset", "broll.removeAsset"):
        assert name in handlers
        assert not name.startswith(prefixes), f"{name} is prefix-matched by keyBridge.ts INJECT_PREFIXES"
        assert name not in exact, f"{name} was added to keyBridge.ts INJECT_METHODS — broll.* takes no provider key"


def test_the_real_path_dedup_key_collapses_dot_segments(tmp_path: Path):
    """Control for the dedup key itself: it must see through both spellings.

    Scoped to the ``..`` dot-segment spelling, which is the only one this test
    constructs. (The earlier name claimed 8.3 short names too; the module docstring
    already admitted that case is NOT exercised here, so the name was REFUTED.)
    """
    folder = tmp_path / "b"
    folder.mkdir()
    dog = folder / "dog.png"
    dog.write_bytes(b"x")
    weird = str(folder / ".." / "b" / "dog.png")
    assert weird != str(dog)
    assert _library_ops._real_key(weird) == _library_ops._real_key(str(dog.resolve()))
    assert _library_ops._real_key(weird) == os.path.normcase(os.path.realpath(str(dog)))


def test_the_dedup_key_is_IDENTICAL_with_and_without_the_directory_cache(tmp_path: Path):
    """The per-call directory memo must not change the key for ANY spelling.

    ``_real_key`` resolves the DIRECTORY and normcases the basename onto it, memoising
    the directory, because ``realpath`` is a per-path syscall and the union lister
    calls it once per scanned asset. Equivalence is the whole safety argument for that
    optimisation, so it is asserted rather than reasoned about.
    """
    folder = tmp_path / "b"
    folder.mkdir()
    dog = folder / "dog.png"
    dog.write_bytes(b"x")
    cache: dict[str, str] = {}
    for spelling in (str(dog), str(folder / ".." / "b" / "dog.png"), str(dog).upper(), str(folder / "DOG.PNG")):
        assert _library_ops._real_key(spelling, cache) == _library_ops._real_key(spelling)
    # One entry per distinct directory spelling, and the uncached call is unaffected.
    #
    # CASE-FOLDING IS A FILESYSTEM PROPERTY, NOT A CONSTANT. `_real_key` normcases the
    # basename, and `os.path.normcase` is identity on POSIX. So an ALL-CAPS respelling of
    # the same path is the SAME file on Windows/NTFS and a genuinely DIFFERENT (absent)
    # file on Linux — 1 key there, 2 keys here, and BOTH are correct.
    #
    # This assertion originally hardcoded `== 1`. It passed on the Windows box it was
    # written on (7440 tests green) and FAILED the Linux CI gate with `assert 2 == 1`,
    # which also cost the 100% coverage bar because the abort skipped the trailing-
    # separator assertion below. Detecting the filesystem instead of the platform keeps
    # this a real assertion on BOTH: it now pins the case-SENSITIVE behaviour too, rather
    # than being relaxed to accommodate it.
    case_insensitive_fs = os.path.normcase("A") != "A"
    expected_keys = 1 if case_insensitive_fs else 2
    assert len({_library_ops._real_key(s, cache) for s in (str(dog), str(dog).upper())}) == expected_keys
    # a trailing-separator spelling has no basename to join: it resolves whole
    assert _library_ops._real_key(str(folder) + os.sep, cache) == _library_ops._real_key(str(folder) + os.sep)


def test_the_union_lister_resolves_each_DIRECTORY_once_not_each_file(wired, tmp_path: Path, monkeypatch):
    """PERF pin: N scanned assets in one folder cost ONE ``realpath``, not N.

    Measured on this box before the memo, 2000 one-folder assets with an EMPTY
    registry: ``scan_assets`` alone 94 ms vs ``broll_asset_rows`` 479 ms (x5.1), and
    ``broll.status`` is a direct-return handler, so that delta is paid synchronously on
    the RPC loop on every status/index/suggest call. Counting the syscall is a stabler
    pin than a wall-clock threshold.
    """
    _handlers, services = wired
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(12):
        (folder / f"a{i}.png").write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})
    outside = tmp_path / "elsewhere" / "city.jpg"
    outside.parent.mkdir()
    outside.write_bytes(b"y")
    services.library.add_broll(str(outside))

    real_realpath = os.path.realpath
    calls: list[str] = []

    def counting(path):
        calls.append(str(path))
        return real_realpath(path)

    monkeypatch.setattr(_library_ops.os.path, "realpath", counting)
    rows = _library_ops.broll_asset_rows(services)
    assert len(rows) == 13  # 12 scanned + 1 registered — the memo changed no output
    # 2 distinct directories (the scanned folder + the registered asset's folder).
    assert len(calls) == 2, f"expected one realpath per DIRECTORY, got {len(calls)}: {calls}"


def test_the_union_still_dedups_two_SCANNED_spellings_of_one_file(wired, tmp_path: Path, monkeypatch):
    """Scanned-vs-scanned dedup must survive even with an EMPTY registry.

    This is why the union CANNOT short-circuit to ``[{**row, 'registered': False} ...]``
    when nothing is registered. Measured with ``mklink /J``: ``os.path.islink`` returns
    **False** for a Windows junction and ``Path.rglob`` DOES descend into it, so a
    junction inside ``brollDir`` makes ``scan_assets`` emit ``mirror\\dog.png`` AND
    ``real\\dog.png`` — two spellings of ONE file, collapsing to one ``_real_key``.
    Skipping the dedup on an empty registry would embed that file twice.

    The two spellings are injected through the scanner seam rather than by creating a
    junction, so this runs on every platform the gate runs on.
    """
    _handlers, services = wired
    folder = tmp_path / "scanned"
    folder.mkdir()
    dog = folder / "dog.png"
    dog.write_bytes(b"x")
    services.settings.set({broll_ops.BROLL_DIR_KEY: str(folder)})
    (row,) = broll_ops.scan_assets(str(folder))
    twin = {**row, "path": str(folder / ".." / "scanned" / "dog.png")}
    monkeypatch.setattr(_library_ops._broll_ops, "scan_assets", lambda _root: [row, twin])

    assert services.library.list_broll() == []  # the registry really is empty
    rows = _library_ops.broll_asset_rows(services)
    assert len(rows) == 1, "one file spelled twice by the SCAN must still yield one row"
    assert rows[0]["registered"] is False
