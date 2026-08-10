"""Library + Project persistence for the media-studio sidecar.

Library: add/list/remove videos in a JSON index on disk. Each added video is
probed for its ``durationSec`` via ``ffprobe`` (resolved through ``ffmpeg.py``).

Project: open/save a *versioned* JSON manifest that references its source video
**by path** (never by copied bytes). ``consolidate`` copies referenced assets
into the project folder and rewrites the refs to be *relative* to that folder,
and ``find_missing_sources`` reports refs whose files no longer exist.

Schema field names are frozen by CONTRACTS.md section 3:
  Video   = {id, path, title, addedAt, durationSec, hasTranscript}
  Project = {id, video, transcript?, tracks, clips, settings}

This module is pure logic + filesystem I/O. The only external dependency is the
ffprobe duration probe, which is injected (``probe_duration``) so tests can mock
the subprocess seam without importing ffmpeg/ffprobe.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

# CONTRACT-NOTE: the manifest schema version is local to this unit (the contract
# only mandates "versioned"); bump on any breaking field change. open() tolerates
# missing/older versions by filling defaults rather than failing hard.
MANIFEST_VERSION = 1

# Type aliases for clarity (matching CONTRACTS.md section 3 field names).
# NOTE: the manifest *payload* alias is ``ProjectData`` (a plain dict), kept
# distinct from the ``Project`` *class* below so the alias is not shadowed by
# the class (that shadowing was the root of the basedpyright `Project` cascade).
Video = dict[str, Any]
ProjectData = dict[str, Any]

# A duration prober: (path) -> seconds. Injected so the ffprobe subprocess can be
# mocked at the seam in tests (no ffmpeg import required for library tests).
DurationProber = Callable[[str], float]


def _now_iso() -> str:
    """UTC timestamp, e.g. ``2026-06-11T19:30:00Z`` (stable, sortable, tz-aware)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    """A short, collision-free id for a library entry / project."""
    return uuid.uuid4().hex[:12]


def _default_probe(path: str) -> float:
    """Default duration prober delegating to ffmpeg.ffprobe_duration.

    Imported lazily so that importing :mod:`library` (and its tests) never pulls
    in the ffmpeg module at import time.
    """
    from . import ffmpeg  # local import keeps the seam mockable / import-light

    return ffmpeg.ffprobe_duration(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    """Atomically write ``data`` as pretty JSON (temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# L1 — SQLite provenance store (replaces the flat library.json index)
# --------------------------------------------------------------------------- #
# The W3C-PROV schema (§3.2). L1 only populates `entity` rows (role='source');
# the activity/agent/edge tables are created now so L2/L3 build on a stable DB.
# `content_hash` is a nullable, unpopulated column in L1 (no BLAKE3 dep here).
# Executed as INDIVIDUAL statements inside ONE explicit transaction so the
# schema-create + import + user_version stamp are atomic (executescript would
# implicitly COMMIT and break that atomicity).
_SCHEMA: tuple[str, ...] = (
    "CREATE TABLE entity ("
    " id TEXT PRIMARY KEY, kind TEXT, path TEXT, role TEXT,"
    " title TEXT, added_at TEXT, duration_sec REAL, content_hash TEXT,"
    " has_transcript INTEGER, thumbnail_path TEXT)",
    "CREATE TABLE activity ("
    " id TEXT PRIMARY KEY, op TEXT, started_at TEXT, ended_at TEXT,"
    " status TEXT, params_json TEXT, agent_id TEXT)",
    "CREATE TABLE agent ( id TEXT PRIMARY KEY, app_version TEXT, route_json TEXT, preset TEXT)",
    "CREATE TABLE edge (src TEXT, dst TEXT, rel TEXT)",
    "CREATE INDEX ix_edge_src ON edge(src)",
    "CREATE INDEX ix_edge_dst ON edge(dst)",
)

# The schema version stamped into ``PRAGMA user_version`` once migration commits.
# (An int literal — PRAGMAs cannot be ``?``-bound — so it is inlined at the call
# site; this constant documents the value.)
SCHEMA_USER_VERSION = 1

# All Video columns, in INSERT order, mapping the Video dict -> the entity row.
_ENTITY_COLUMNS = "id, kind, path, role, title, added_at, duration_sec, content_hash, has_transcript, thumbnail_path"


class LibraryMigrationError(RuntimeError):
    """Raised when an existing ``library.json`` cannot be safely migrated.

    A corrupt / wrong-shape index aborts the migration BEFORE the
    ``user_version`` stamp and BEFORE the ``.bak`` rename, so the corrupt source
    stays authoritative (never a silently-stamped empty DB = total data loss).
    """


# --------------------------------------------------------------------------- #
# BR1 — the B-roll asset REGISTRY (``role='broll'`` rows in the SAME entity table)
# --------------------------------------------------------------------------- #
#: ``entity.role`` of a registered b-roll asset. Distinct from ``'source'`` so the
#: two libraries cannot leak into each other: every b-roll query below is
#: role-scoped exactly like the source-video ones, so a b-roll still can never
#: surface in ``library.list`` and a source video can never be unregistered here.
BROLL_ROLE = "broll"

#: The two ``entity.kind`` values a b-roll asset may take (design BR1).
BROLL_IMAGE_KIND = "brollImage"
BROLL_CLIP_KIND = "brollClip"

#: PROV entity kind -> the asset ``kind`` the planner/compositor speak. This
#: translation is load-bearing, not cosmetic: ``features/broll_compose.py`` treats
#: anything that is not the literal ``"video"`` as a still (``-loop 1``), so handing
#: it a ``brollClip`` would composite a clip as one frozen frame. The lookup is
#: strict on purpose — :meth:`Library.add_broll` is the ONLY writer of a
#: ``role='broll'`` row and only ever writes these two constants, so a third value
#: is a programming error that must be loud rather than silently read as a still.
_BROLL_ASSET_KIND: dict[str, str] = {BROLL_IMAGE_KIND: "image", BROLL_CLIP_KIND: "video"}


class BrollAssetError(RuntimeError):
    """A b-roll asset cannot be registered: the file is missing, or is not b-roll."""


def broll_asset_id(path: str) -> str:
    """The stable asset id for ``path`` — ``sha256(path)[:16]``.

    Deliberately the SAME derivation ``broll_ops.scan_assets`` uses for its
    ``assetId``, so when the configured ``brollDir`` is already an absolute,
    resolved path a file that is BOTH scanned and registered carries ONE id and
    registering it does not churn its vector in the index. Where the two spellings
    of one file differ (an 8.3 short component, a ``..`` segment, letter case) the
    ids differ too — which is why the union lister dedups on the REAL path rather
    than on this id, and a divergent spelling can never double-count an asset.

    ``entity.id`` is a GLOBAL primary key shared with the source videos, so the two
    id spaces must not overlap: this returns 16 hex chars where :func:`_new_id`
    returns 12, which makes a b-roll id length-disjoint from every
    ``_new_id``-derived source id and therefore incapable of replacing one through
    the ``INSERT OR REPLACE`` in :meth:`Library.add_broll`.
    """
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def _broll_entity_kind(path: Path) -> str | None:
    """``path``'s b-roll ``entity.kind``, or ``None`` when it is not b-roll at all.

    The accepted extension sets are READ from ``features.broll_ops`` (lazily, so
    importing this module stays stdlib-only and feature-free) rather than restated
    here: a second copy would drift, and then a file the folder scan happily
    indexes could be refused by ``add_broll`` — or, worse, the reverse.
    """
    from .features import broll_ops  # local import keeps this module import-light

    suffix = path.suffix.lower()
    if suffix in broll_ops.IMAGE_EXTS:
        return BROLL_IMAGE_KIND
    if suffix in broll_ops.VIDEO_EXTS:
        return BROLL_CLIP_KIND
    return None


def _stat_or_zero(path: str) -> tuple[int, float, bool]:
    """``(sizeBytes, mtime, exists)`` for ``path`` — zeros when the file is gone.

    Those two stat fields are exactly what ``broll_index.fingerprint`` hashes, so a
    registered row must carry them the way a scanned row does or every registered
    asset would read as permanently stale and be re-embedded on every index run. A
    vanished file reports ``exists=False`` rather than a fabricated size, and the
    caller surfaces it LOUDLY instead of silently dropping it — the same discipline
    as :meth:`Project.find_missing_sources`.
    """
    try:
        stat = os.stat(path)
    except OSError:
        return 0, 0.0, False
    return stat.st_size, stat.st_mtime, True


class Library:
    """A SQLite-backed (W3C-PROV) collection of source videos.

    The public surface (``add/list/remove/get/set_has_transcript/set_thumbnail``
    + the static ``_normalize``) is preserved verbatim from the legacy JSON
    implementation — it is now a *façade* over a SQLite DB whose path is derived
    from ``index_path`` (``library.json`` -> ``library.db``), so it lives under
    the SAME ``dataRoot`` (DB + its ``-wal``/``-shm`` sidecars relocate with the
    folder). On first open an existing ``library.json`` is migrated into the DB
    (idempotent, gated on ``PRAGMA user_version``) and demoted to
    ``library.json.bak``. Methods return / accept plain dicts whose keys match
    CONTRACTS.md section 3.
    """

    def __init__(self, index_path: str | os.PathLike, probe_duration: DurationProber | None = None):
        self.index_path = Path(index_path)
        # DB sibling of the index (same dataRoot). Pinned by the `.db` suffix
        # convention so the ~20 caller/test sites that pass `…/library.json`
        # keep working unchanged.
        self._db_path = self.index_path.with_suffix(".db")
        self._probe = probe_duration or _default_probe

    @property
    def db_path(self) -> Path:
        """The REAL store: the SQLite DB (``-wal``/``-shm`` are its siblings).

        ``index_path`` is the legacy JSON index — only ever read, then demoted to
        ``library.json.bak``; it is never written. Callers that want to NAME the
        store (e.g. ``paths.describe``) must use this, not ``index_path``, and must
        not re-derive the ``.db`` suffix convention themselves.
        """
        return self._db_path

    # ---- connection + migration -------------------------------------------
    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        """Open the DB (WAL), run the one-shot migration, yield the connection.

        ``isolation_level=None`` puts the driver in autocommit mode so the
        migration owns its transaction EXPLICITLY (``BEGIN``/``COMMIT``); the
        ``journal_mode=WAL`` PRAGMA runs at open OUTSIDE that transaction (it
        commits implicitly), per SQLite practice.
        """
        # The dataRoot may not exist yet on first open (the legacy JSON store
        # created it lazily in `_write_json`); sqlite3.connect will NOT, so
        # ensure the parent dir before connecting.
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._migrate(conn)
            yield conn
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= SCHEMA_USER_VERSION:
            return  # idempotent: never re-runs once stamped (gate is user_version)
        # Parse the legacy index BEFORE opening the transaction so a corrupt
        # source aborts with NOTHING stamped and the source left authoritative.
        legacy = self._read_legacy_videos()
        conn.execute("BEGIN")
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            for raw in legacy:
                self._insert_entity(conn, self._normalize(raw))
            # Stamp LAST, inside the txn, as an int literal (PRAGMA can't bind ?).
            conn.execute(f"PRAGMA user_version = {SCHEMA_USER_VERSION}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        # Post-commit, best-effort: demote the now-migrated source to a backup.
        self._backup_library_json()

    def _read_legacy_videos(self) -> builtins.list[dict[str, Any]]:
        """Return the raw video dicts from ``library.json`` (or ``[]`` if absent).

        Raises :class:`LibraryMigrationError` on an unparseable or wrong-shape
        index so migration aborts loudly rather than stamping an empty DB.
        """
        if not self.index_path.exists():
            return []
        try:
            data = _read_json(self.index_path)
        except ValueError as exc:  # JSONDecodeError is a ValueError subclass
            raise LibraryMigrationError(f"corrupt library index {self.index_path}: {exc}") from exc
        if not isinstance(data, dict):
            raise LibraryMigrationError(f"corrupt library index (not an object): {self.index_path}")
        videos = data.get("videos", [])
        if not isinstance(videos, builtins.list):
            raise LibraryMigrationError(f"corrupt library index (videos not a list): {self.index_path}")
        return videos

    def _backup_library_json(self) -> None:
        """Rename ``library.json`` -> ``library.json.bak`` (point-in-time backup).

        Best-effort and idempotent: runs only AFTER the migration committed, uses
        ``os.replace`` (atomic; overwrites any stale ``.bak``), and swallows a
        rename failure — a backup miss must never crash, roll back, or
        re-trigger migration (the ``user_version`` stamp already guards that).
        """
        if not self.index_path.exists():
            return
        bak = self.index_path.with_name(self.index_path.name + ".bak")
        # Best-effort: a backup miss must never crash/roll back (no `await` here,
        # so contextlib.suppress is safe — satisfies ruff SIM105 without the
        # CodeQL py/ineffectual-statement gotcha that bites `await` in suppress).
        with suppress(OSError):
            os.replace(self.index_path, bak)

    @staticmethod
    def _insert_entity(conn: sqlite3.Connection, video: Video) -> None:
        """Insert (or replace) a fully-normalized Video as a ``role='source'`` row.

        Parameterized (``?``) SQL only — values never touch the SQL text.
        ``content_hash`` is stored as ``NULL`` (unpopulated in L1).
        """
        conn.execute(
            f"INSERT OR REPLACE INTO entity ({_ENTITY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                video["id"],
                "video",
                video["path"],
                "source",
                video["title"],
                video["addedAt"],
                float(video["durationSec"]),
                None,  # content_hash: nullable, unpopulated in L1 (no BLAKE3 dep)
                int(bool(video["hasTranscript"])),
                video["thumbnailPath"],
            ),
        )

    @staticmethod
    def _row_to_video(row: sqlite3.Row) -> Video:
        """Reconstruct a full Video dict from an ``entity`` row.

        Columns are always written fully-normalized (strings/float/int, never
        NULL except ``content_hash``), so no defaulting/branching is needed.
        """
        return {
            "id": row["id"],
            "path": row["path"],
            "title": row["title"],
            "addedAt": row["added_at"],
            "durationSec": float(row["duration_sec"]),
            "hasTranscript": bool(row["has_transcript"]),
            "thumbnailPath": row["thumbnail_path"],
        }

    @staticmethod
    def _normalize(v: dict[str, Any]) -> Video:
        return {
            "id": v.get("id") or _new_id(),
            "path": v.get("path", ""),
            "title": v.get("title", ""),
            "addedAt": v.get("addedAt") or _now_iso(),
            "durationSec": float(v.get("durationSec") or 0.0),
            "hasTranscript": bool(v.get("hasTranscript", False)),
            # WU-2: additive source-video poster path; "" until library.thumbnail
            # extracts one. Backfilled here so legacy records load without KeyError.
            "thumbnailPath": str(v.get("thumbnailPath") or ""),
        }

    # ---- public surface (matches library.* methods) ------------------------
    def list(self) -> builtins.list[Video]:
        """Return all source videos (insertion order preserved)."""
        with self._open() as conn:
            rows = conn.execute("SELECT * FROM entity WHERE role = ? ORDER BY rowid", ("source",)).fetchall()
        return [self._row_to_video(r) for r in rows]

    def add(self, path: str, title: str | None = None) -> Video:
        """Add ``path`` to the library, probing its duration, and return the Video.

        Re-adding an existing path is idempotent: the existing entry is returned
        rather than creating a duplicate row.
        """
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"video not found: {path}")

        abspath = str(src.resolve())
        with self._open() as conn:
            existing = conn.execute("SELECT * FROM entity WHERE role = ? AND path = ?", ("source", abspath)).fetchone()
            if existing is not None:
                return self._row_to_video(existing)  # idempotent re-add

            try:
                duration = float(self._probe(abspath))
            except Exception:
                # CONTRACT-NOTE: a probe failure must not block adding the video;
                # we store 0.0 and let a later re-probe / transcribe fill it in.
                duration = 0.0

            video: Video = {
                "id": _new_id(),
                "path": abspath,
                "title": title or src.stem,
                "addedAt": _now_iso(),
                "durationSec": duration,
                "hasTranscript": False,
                "thumbnailPath": "",  # WU-2: poster filled in by library.thumbnail
            }
            self._insert_entity(conn, video)
        return video

    def get(self, video_id: str) -> Video | None:
        """Return the Video with ``id == video_id`` or ``None``."""
        with self._open() as conn:
            row = conn.execute("SELECT * FROM entity WHERE role = ? AND id = ?", ("source", video_id)).fetchone()
        return self._row_to_video(row) if row is not None else None

    def remove(self, video_id: str, *, destroy_managed_copy: bool = False) -> bool:
        """Remove the video with ``id == video_id``. Returns True if removed.

        The USER's source file on disk is never deleted (refs are by path;
        deletion is out of scope for a library remove). An app-managed byte-copy
        (opt-in keep-a-copy), however, IS reclaimed here — otherwise its row +
        content-addressed file would be orphaned, counting forever against the
        managed-store cap with no entity to evict them.

        FAILS CLOSED on the irreplaceable case. This used to pass ``force=True``
        unconditionally, justified as "the user is deleting the video, so evicting even
        an irreplaceable copy is intended, not an accidental destruction". That premise
        was never true in the shipped UI: the Library card's "Remove" calls this with NO
        confirm and NO undo, and "Remove selected" loops it over a whole selection — so
        the force flag turned :meth:`ManagedStore.evict`'s explicit contract ("never a
        silent destruction of the only copy") into exactly that.

        ``destroy_managed_copy`` therefore defaults to False, which lets that LOUD
        refusal reach the caller whenever the managed copy is the ONLY surviving copy
        (i.e. keep-a-copy was opted into AND the original source has since moved or been
        deleted). The refusal happens BEFORE the entity DELETE, so nothing is destroyed
        and the video remains actionable. A caller that has genuinely confirmed the
        user's intent passes ``destroy_managed_copy=True``.

        Mirrors ``library.managedEvict``, whose ``force`` already defaults to False —
        this reuses that default-safe shape rather than inventing a second one.
        """
        # Explicit membership check (not exception-as-control-flow) so both the
        # has-managed and no-managed branches stay coverage-clean.
        has_managed = any(e["entityId"] == video_id for e in self.managed_status()["entries"])
        if has_managed:
            self.managed_evict(video_id, force=destroy_managed_copy)
        with self._open() as conn:
            cur = conn.execute("DELETE FROM entity WHERE role = ? AND id = ?", ("source", video_id))
            return cur.rowcount > 0

    def set_has_transcript(self, video_id: str, value: bool = True) -> Video | None:
        """Mark a video's ``hasTranscript`` flag and persist; returns the Video."""
        with self._open() as conn:
            cur = conn.execute(
                "UPDATE entity SET has_transcript = ? WHERE role = ? AND id = ?",
                (int(bool(value)), "source", video_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM entity WHERE role = ? AND id = ?", ("source", video_id)).fetchone()
        return self._row_to_video(row)

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> Video | None:
        """WU-2: set a video's ``thumbnailPath`` and persist; returns the Video.

        Mirrors :meth:`set_has_transcript`. Returns ``None`` for an unknown id.
        """
        with self._open() as conn:
            cur = conn.execute(
                "UPDATE entity SET thumbnail_path = ? WHERE role = ? AND id = ?",
                (str(thumbnail_path), "source", video_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM entity WHERE role = ? AND id = ?", ("source", video_id)).fetchone()
        return self._row_to_video(row)

    # ---- BR1 b-roll asset registry ----------------------------------------- #
    def list_broll(self) -> builtins.list[dict[str, Any]]:
        """Every registered b-roll asset, in registration order (BR1).

        Rows are shaped like ``broll_ops.scan_assets``' rows — ``assetId``, ``path``,
        ``kind``, ``durationSec``, ``sizeBytes``, ``mtime`` — so the index and the
        planner consume a scanned and a registered asset without branching, PLUS the
        registry-only fields: the PROV ``entityKind``, the ``title`` /
        ``thumbnailPath`` the UI shows, ``contentHash``, ``registered=True``, and
        ``exists``. A row whose file has since moved or been deleted is RETURNED
        (marked absent), never hidden — the caller decides what to do about it.
        """
        with self._open() as conn:
            rows = conn.execute("SELECT * FROM entity WHERE role = ? ORDER BY rowid", (BROLL_ROLE,)).fetchall()
        return [self._row_to_broll_asset(r) for r in rows]

    def add_broll(self, path: str, title: str | None = None) -> dict[str, Any]:
        """Register ``path`` as a b-roll asset and return its asset row (BR1).

        Reuses the SAME ``entity`` table as the source videos with ``role='broll'``
        and ``kind`` in {``brollImage``, ``brollClip``} — a b-roll asset is a
        first-class PROV entity, not a second store, so lineage/relink keep ONE
        graph. Idempotent by RESOLVED path: re-registering an already-registered
        file returns the existing row rather than creating a duplicate (mirroring
        :meth:`add`). The bytes are never copied and the file is never moved; the
        registry holds a path.

        Raises :class:`BrollAssetError` for a file that does not exist, or whose
        extension the b-roll folder scan would not pick up either.
        """
        src = Path(path)
        if not src.exists():
            raise BrollAssetError(f"b-roll asset not found: {path}")
        kind = _broll_entity_kind(src)
        if kind is None:
            raise BrollAssetError(f"not a b-roll image or clip: {path}")
        abspath = str(src.resolve())
        with self._open() as conn:
            existing = conn.execute(
                "SELECT * FROM entity WHERE role = ? AND path = ?", (BROLL_ROLE, abspath)
            ).fetchone()
            if existing is not None:
                return self._row_to_broll_asset(existing)  # idempotent re-register
            asset_id = broll_asset_id(abspath)
            conn.execute(
                f"INSERT OR REPLACE INTO entity ({_ENTITY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset_id,
                    kind,
                    abspath,
                    BROLL_ROLE,
                    title or src.stem,
                    _now_iso(),
                    self._broll_duration(abspath, kind),
                    # content_hash: the column is SURFACED by the asset row but left
                    # NULL here. Populating it means a whole-file BLAKE3 of a
                    # possibly multi-GB asset inside a synchronous RPC; the stronger
                    # staleness key is BR2's job (broll_index's docstring already
                    # names it as the upgrade path from the size+mtime fingerprint).
                    None,
                    0,  # has_transcript: meaningless for a b-roll asset
                    "",  # thumbnail_path: "" until a poster is extracted for it
                ),
            )
            row = conn.execute("SELECT * FROM entity WHERE role = ? AND id = ?", (BROLL_ROLE, asset_id)).fetchone()
        # Read the row BACK rather than assembling the return value by hand: what a
        # caller gets from add_broll is then the SAME shape list_broll yields BY
        # CONSTRUCTION, instead of via two literals someone has to keep in step.
        return self._row_to_broll_asset(row)

    def remove_broll(self, asset_id: str) -> bool:
        """Unregister the b-roll asset with ``id == asset_id``. True if removed.

        The USER's file on disk is NEVER deleted — the registry holds a path, not
        bytes (the same rule :meth:`remove` follows for a source video). Role-scoped,
        so a source-video id can never be removed through this door.
        """
        with self._open() as conn:
            cur = conn.execute("DELETE FROM entity WHERE role = ? AND id = ?", (BROLL_ROLE, asset_id))
            return cur.rowcount > 0

    def _broll_duration(self, path: str, kind: str) -> float:
        """The probed duration of a b-roll CLIP; ``0.0`` for a still.

        A still has no duration, so probing one would be a pointless ffprobe spawn.
        CONTRACT-NOTE: a probe failure degrades to ``0.0`` rather than blocking the
        registration — the same rule :meth:`add` applies to a source video.
        """
        if kind != BROLL_CLIP_KIND:
            return 0.0
        try:
            return float(self._probe(path))
        except Exception:
            return 0.0

    @staticmethod
    def _row_to_broll_asset(row: sqlite3.Row) -> dict[str, Any]:
        """An ``entity`` row -> the planner/index-shaped b-roll asset dict (BR1)."""
        size, mtime, exists = _stat_or_zero(row["path"])
        return {
            "assetId": row["id"],
            "path": row["path"],
            # The compose/planner vocabulary ("image"/"video"), NOT the entity kind.
            "kind": _BROLL_ASSET_KIND[row["kind"]],
            "entityKind": row["kind"],
            "title": row["title"],
            "addedAt": row["added_at"],
            "durationSec": float(row["duration_sec"]),
            "contentHash": row["content_hash"],
            "thumbnailPath": row["thumbnail_path"],
            "sizeBytes": size,
            "mtime": mtime,
            "exists": exists,
            "registered": True,
        }

    # ---- L2 lineage (PROV append on Job success) ---------------------------
    def record_lineage(
        self,
        job: Any,
        inputs: builtins.list[Any],
        outputs: builtins.list[Any],
        agent: Any,
    ) -> str:
        """Append one PROV lineage record for a successful ``job`` (DESIGN §3.3).

        Thin façade over :func:`media_studio.lineage.record_lineage` (imported
        lazily so :mod:`lineage` — which reuses this module's id/timestamp/schema
        helpers — can import :mod:`library` without an import cycle). Returns the
        new activity id. Opt-in: an op that does not want lineage never calls it.
        """
        from . import lineage  # lazy import breaks the library<->lineage cycle

        return lineage.record_lineage(self, job, inputs, outputs, agent)

    def lineage(self, entity_id: str) -> dict[str, Any]:
        """Return ``entity_id``'s provenance — ancestors + descendants (L3, §3.2).

        Thin façade over :func:`media_studio.lineage.lineage_of` (lazy import, as
        for :meth:`record_lineage`). ``{id, entity, ancestors, descendants,
        provenance}`` where each relation is a list of full entity dicts (or a
        ``missing`` stub) and ``provenance`` is the producing activity + agent of
        the queried node (``None`` for a raw source) — the L4 detail card source.
        """
        from . import lineage  # lazy import breaks the library<->lineage cycle

        return lineage.lineage_of(self, entity_id)

    # ---- L5 reveal / regenerate / hash-verified relink ---------------------
    def reveal_source(self, entity_id: str) -> dict[str, Any]:
        """L5: resolve ``entity_id`` to its by-path source file(s) for OS-reveal.

        Thin façade over :func:`media_studio.relink.reveal_source` (lazy import, as
        for :meth:`lineage`). ``{id, sources:[{id,path,title,exists}], missing}`` —
        ``missing`` lists sources no longer on disk (loud, never silently skipped).
        """
        from . import relink  # lazy import keeps relink (which imports library) cycle-free

        return relink.reveal_source(self, entity_id)

    def regenerate(self, entity_id: str) -> dict[str, Any]:
        """L5: build the replay descriptor for ``entity_id`` (``{id, op, params, missing, ready}``).

        Thin façade over :func:`media_studio.relink.regenerate` (lazy import).
        ``ready`` is ``False`` when any source file is missing — the caller relinks
        first rather than regenerating from a vanished source.
        """
        from . import relink  # lazy import keeps relink (which imports library) cycle-free

        return relink.regenerate(self, entity_id)

    def pin_source_hash(self, entity_id: str, hash_file: Callable[[str], str] | None = None) -> dict[str, Any]:
        """L5: record ``entity_id``'s whole-file BLAKE3 ``content_hash`` (relink baseline).

        Thin façade over :func:`media_studio.relink.pin_source_hash` (lazy import).
        Returns the updated entity dict; raises if the source file is missing.
        """
        from . import relink  # lazy import keeps relink (which imports library) cycle-free

        return relink.pin_source_hash(self, entity_id, hash_file=hash_file)

    def relink(self, entity_id: str, new_path: str, hash_file: Callable[[str], str] | None = None) -> dict[str, Any]:
        """L5: HASH-VERIFIED re-point of ``entity_id`` to ``new_path`` (whole-file BLAKE3).

        Thin façade over :func:`media_studio.relink.relink` (lazy import). Re-points
        only when the new file's BLAKE3 matches the recorded ``content_hash``; a
        mismatch or an unverifiable asset (no recorded hash) raises loudly.
        """
        from . import relink  # lazy import keeps relink (which imports library) cycle-free

        return relink.relink(self, entity_id, new_path, hash_file=hash_file)

    # ---- WU-3b1 managed-copy store (opt-in keep-a-copy) --------------------
    def keep_copy(self, entity_id: str) -> dict[str, Any]:
        """WU-3b1: keep an app-managed byte-copy of ``entity_id``'s source (lineage re-point).

        Thin façade over :class:`media_studio.keepcopy.ManagedStore` (lazy import, as
        for :meth:`relink`). Copies the original bytes into the managed store under the
        data-root, makes the copy AUTHORITATIVE for playback/relink, and records the
        original path as provenance. Raises :class:`~media_studio.keepcopy.KeepCopyError`
        for an unknown/missing source, a failed free-space preflight, or an over-cap file.
        """
        from . import keepcopy  # lazy import keeps keepcopy (which imports library) cycle-free

        return keepcopy.ManagedStore(self).keep_copy(entity_id)

    def managed_status(self) -> dict[str, Any]:
        """WU-3b1: the managed store's ``{sizeBytes, capBytes, count, entries}`` snapshot."""
        from . import keepcopy  # lazy import keeps keepcopy (which imports library) cycle-free

        return keepcopy.ManagedStore(self).status()

    def managed_evict(self, entity_id: str, *, force: bool = False) -> dict[str, Any]:
        """WU-3b1: evict ``entity_id``'s managed copy (re-point to original, free the bytes).

        Refuses LOUD when the original source is gone (the managed copy is the only
        surviving copy) unless ``force=True`` — never silently destroys the only copy.
        """
        from . import keepcopy  # lazy import keeps keepcopy (which imports library) cycle-free

        return keepcopy.ManagedStore(self).evict(entity_id, force=force)

    def managed_clear(self, *, force: bool = False) -> dict[str, Any]:
        """WU-3b1: evict EVERY managed copy (re-point each entity to its original).

        Refuses LOUD (destroying nothing) when any managed copy's original source is gone
        unless ``force=True`` — never silently destroys the only surviving copy of a video.
        """
        from . import keepcopy  # lazy import keeps keepcopy (which imports library) cycle-free

        return keepcopy.ManagedStore(self).clear(force=force)


class Project:
    """A versioned JSON project manifest referencing its source video by path.

    Manifest on disk::

        {"version": 1, "id", "video", "transcript"?, "tracks": [...],
         "clips": [{"candidate", "path"}], "audioTracks": [...],
         "videoTracks": [{"id", "name", "index", "clips": [...]}], "settings": {...}}

    ``clips`` are ALTERNATIVE OUTPUTS (candidate renders), NOT timeline lanes.
    The stacked video lanes of the editor live in ``videoTracks`` — see
    ``features/video_tracks.py``.

    Refs (the video path and each clip/track ``path``) are stored as written by
    the caller. ``consolidate`` copies those assets *into* the project folder and
    rewrites the refs to be **relative** to the folder, so the project becomes
    self-contained and portable.
    """

    def __init__(self, data: ProjectData, manifest_path: str | os.PathLike | None = None):
        self.data = data
        self.manifest_path = Path(manifest_path) if manifest_path else None

    # ---- construction ------------------------------------------------------
    @classmethod
    def new(cls, video: Video, settings: dict[str, Any] | None = None) -> Project:
        """Create a fresh project around ``video`` with empty tracks/clips."""
        data: ProjectData = {
            "id": _new_id(),
            "video": dict(video),
            "tracks": [],
            "clips": [],
            "settings": dict(settings or {}),
        }
        return cls(data)

    @classmethod
    def open(cls, manifest_path: str | os.PathLike) -> Project:
        """Open a manifest from disk, backfilling any missing schema fields."""
        path = Path(manifest_path)
        raw = _read_json(path)
        if not isinstance(raw, dict):
            raise ValueError(f"invalid project manifest: {manifest_path}")
        data: ProjectData = {
            "id": raw.get("id") or _new_id(),
            "video": raw.get("video") or {},
            "tracks": raw.get("tracks") or [],
            "clips": raw.get("clips") or [],
            "audioTracks": raw.get("audioTracks") or [],  # A3 (T2)
            # The multi-lane VIDEO timeline (features/video_tracks.py). Backfilled
            # empty so a manifest written before the editor existed still opens.
            "videoTracks": raw.get("videoTracks") or [],
            "settings": raw.get("settings") or {},
        }
        # transcript is optional (only present once transcribed).
        if raw.get("transcript") is not None:
            data["transcript"] = raw["transcript"]
        # transcriptEdits is the OPTIONAL reversible transcript-edit ledger
        # (features/transcript_edit.py). Backfilled exactly like `transcript`:
        # absent on an old project, and NEVER synthesised — a manifest that has
        # never been transcript-edited must round-trip byte-identical. Without
        # this passthrough the ledger written by `applyEdit` would be silently
        # dropped on the next `open()`, and undo would lose its history.
        if raw.get("transcriptEdits") is not None:
            data["transcriptEdits"] = raw["transcriptEdits"]
        return cls(data, manifest_path=path)

    # ---- persistence -------------------------------------------------------
    def save(self, manifest_path: str | os.PathLike | None = None) -> Path:
        """Write the manifest (versioned) to disk and return its path."""
        path = Path(manifest_path) if manifest_path else self.manifest_path
        if path is None:
            raise ValueError("no manifest_path given to save()")
        out: dict[str, Any] = {"version": MANIFEST_VERSION}
        out.update(self.data)
        _write_json(path, out)
        self.manifest_path = path
        return path

    # ---- refs --------------------------------------------------------------
    def _ref_paths(self) -> list[str]:
        """Every external file path the manifest references (video + clips + tracks + audioTracks)."""
        refs: list[str] = []
        video = self.data.get("video") or {}
        if video.get("path"):
            refs.append(video["path"])
        for clip in self.data.get("clips") or []:
            if isinstance(clip, dict) and clip.get("path"):
                refs.append(clip["path"])
        for track in self.data.get("tracks") or []:
            if isinstance(track, dict) and track.get("path"):
                refs.append(track["path"])
        # Bug-sweep: dub AudioTracks carry a 'path' too — include them so a deleted
        # dub is reported missing and consolidate can rebase it (portability).
        for atrack in self.data.get("audioTracks") or []:
            if isinstance(atrack, dict) and atrack.get("path"):
                refs.append(atrack["path"])
        # Same reasoning for the VIDEO timeline: every lane clip references a source
        # file by path (its own, which may be B-roll rather than the project video),
        # so a deleted clip source must be reported missing and consolidate must be
        # able to rebase it. Omitting these would leave a "portable" folder whose
        # timeline still points at absolute paths outside it.
        for vtrack in self.data.get("videoTracks") or []:
            if not isinstance(vtrack, dict):
                continue
            for clip in vtrack.get("clips") or []:
                if isinstance(clip, dict) and clip.get("path"):
                    refs.append(clip["path"])
        return refs

    def find_missing_sources(self) -> list[str]:
        """Return referenced paths that do not currently exist on disk.

        Relative refs are resolved against the manifest's folder when known.
        """
        base = self.manifest_path.parent if self.manifest_path else Path.cwd()
        missing: list[str] = []
        for ref in self._ref_paths():
            p = Path(ref)
            resolved = p if p.is_absolute() else base / p
            if not resolved.exists():
                missing.append(ref)
        return missing

    def consolidate(self, folder: str | os.PathLike) -> str:
        """Copy every referenced asset into ``folder/assets`` and rebase refs.

        After consolidation the manifest's video/clip/track paths are *relative*
        (``assets/<name>``) to ``folder``, the manifest is saved into ``folder``,
        and the absolute folder path is returned. Missing sources are skipped
        (their refs are left untouched) rather than raising, so a partially
        recoverable project can still be consolidated.
        """
        dest = Path(folder)
        assets = dest / "assets"
        assets.mkdir(parents=True, exist_ok=True)

        base = self.manifest_path.parent if self.manifest_path else Path.cwd()
        used: set[str] = set()
        # Dedup memo keyed by the RESOLVED ABSOLUTE path: two refs to the SAME file
        # (e.g. the same clip on two tracks) are copied ONCE and both rebased to the
        # one ``assets/<name>``. DIFFERENT files sharing a basename have distinct abs
        # keys, so ``_unique_name`` still disambiguates them into separate copies.
        copied: dict[str, str] = {}

        def _copy_in(ref: str) -> str:
            src = Path(ref)
            resolved = src if src.is_absolute() else base / src
            if not resolved.exists():
                return ref  # missing source: leave ref as-is
            abskey = str(resolved.resolve())
            cached = copied.get(abskey)
            if cached is not None:
                return cached  # dedup: identical file already copied under this name
            name = self._unique_name(resolved.name, used)
            used.add(name)
            shutil.copy2(resolved, assets / name)
            # POSIX-style relative ref keeps manifests portable across OSes.
            rebased = f"assets/{name}"
            copied[abskey] = rebased
            return rebased

        video = self.data.get("video") or {}
        if video.get("path"):
            video["path"] = _copy_in(video["path"])
        for clip in self.data.get("clips") or []:
            if isinstance(clip, dict) and clip.get("path"):
                clip["path"] = _copy_in(clip["path"])
        for track in self.data.get("tracks") or []:
            if isinstance(track, dict) and track.get("path"):
                track["path"] = _copy_in(track["path"])
        # Bug-sweep: copy + rebase dub AudioTracks too, else the portable folder
        # still points at the dub audio by its original absolute path.
        for atrack in self.data.get("audioTracks") or []:
            if isinstance(atrack, dict) and atrack.get("path"):
                atrack["path"] = _copy_in(atrack["path"])
        # ... and every VIDEO-timeline lane clip (the _copy_in memo dedups a clip that
        # references the same file as the project video, so one copy serves both refs).
        for vtrack in self.data.get("videoTracks") or []:
            if not isinstance(vtrack, dict):
                continue
            for clip in vtrack.get("clips") or []:
                if isinstance(clip, dict) and clip.get("path"):
                    clip["path"] = _copy_in(clip["path"])
        # Rebase the source-video poster too so a MOVED portable folder still finds
        # its thumbnail relative. Kept OUT of _ref_paths/find_missing_sources on
        # purpose: the poster is a REGENERABLE derived artifact, not a relinkable
        # source, so its absence must not be reported as a missing source.
        if video.get("thumbnailPath"):
            video["thumbnailPath"] = _copy_in(video["thumbnailPath"])

        self.save(dest / "project.json")
        return str(dest.resolve())

    @staticmethod
    def _unique_name(name: str, used: set[str]) -> str:
        """Disambiguate ``name`` against ``used`` (appends -1, -2, ... before ext)."""
        if name not in used:
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        i = 1
        while f"{stem}-{i}{suffix}" in used:
            i += 1
        return f"{stem}-{i}{suffix}"
