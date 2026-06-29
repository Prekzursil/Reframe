"""L5 — Reveal source / Regenerate-from-source / hash-verified relink (DESIGN §3.3.3 + GATE L5).

Three asset-detail actions over the L1 SQLite provenance store, plus the hash
baseline they need:

* :func:`reveal_source` — resolve an asset to its by-path SOURCE file(s) so the UI
  can reveal them in the OS file explorer. LOUD about a source whose file no longer
  exists (the ``find_missing_sources`` contract — never a silent skip).
* :func:`regenerate` — replay the producing activity (op + redacted params + the
  resolved M3 route) against the still-by-path source. Refuses (loud) when any
  source is missing, surfacing exactly which paths to relink.
* :func:`relink` — HASH-VERIFIED re-point of a moved source: the whole-file BLAKE3
  digest of the new path MUST match the recorded ``content_hash`` (a ``(size,
  mtime)`` stat is NOT content verification, GATE L5). A mismatch — or an
  unverifiable asset with no recorded hash — raises loudly; only an exact match
  re-points the row. Piece-hash recheck stays V2 (L6).
* :func:`pin_source_hash` — record an asset's whole-file BLAKE3 ``content_hash``
  while its file is present, so a later relink has a baseline to verify against.
  This is the whole-file path; cross-library dedup + piece-hash are L6/V2.

The actual file hashing is the ONLY heavy/host-only step and lives behind an
injected ``hash_file`` seam (default :func:`blake3_file`, lazily imported) so the
pure logic is unit-tested without reading multi-GB media. Digests are stored
**algorithm-prefixed** (``blake3:<hex>``) so a future SHA-256/C2PA path can coexist
without a migration. NO silent fallback to a weaker hash: a missing ``blake3``
package fails LOUD.

DB reads/writes go through the injected L1 :class:`~media_studio.library.Library`
façade (``library._open``) using parameterized (``?``) SQL only; the entity/edge
walking helpers are reused from :mod:`media_studio.lineage` so there is one source
of truth for the PROV graph shape.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .lineage import _load_entity, _load_provenance, _related_ids

#: Algorithm tag stored in front of every digest (``blake3:<hex>``). Self-describing
#: so the column is not baked to one algorithm (DESIGN §3.2).
DIGEST_ALGO = "blake3"

#: Streaming read size for the whole-file hash (1 MiB) — bounded memory on multi-GB sources.
_HASH_CHUNK = 1 << 20

#: ``entity.role`` of a by-path source video (the only role a relink/reveal targets on disk).
SOURCE_ROLE = "source"


class RelinkError(RuntimeError):
    """A reveal/regenerate/relink operation could not proceed (loud, no silent skip)."""


class RelinkVerificationError(RelinkError):
    """A hash-verified relink was refused — the new file does not match (or cannot be verified)."""


#: A whole-file hasher: ``(path) -> hex digest`` (no algorithm prefix). Injected so
#: the heavy byte-read is mockable at the seam in tests (DESIGN: heavy half behind a seam).
HashFile = Callable[[str], str]


# --------------------------------------------------------------------------- #
# digest helpers (PURE) + the heavy hash seam
# --------------------------------------------------------------------------- #
def format_digest(hex_digest: str) -> str:
    """Return the algorithm-prefixed, lower-cased digest (``blake3:<hex>``)."""
    return f"{DIGEST_ALGO}:{hex_digest.strip().lower()}"


def digests_match(a: str, b: str) -> bool:
    """Whether two algorithm-prefixed digests are equal (case-/whitespace-insensitive)."""
    return a.strip().lower() == b.strip().lower()


def blake3_file(path: str) -> str:
    """Whole-file BLAKE3 hex digest, streamed in bounded chunks.

    ``blake3`` is imported lazily so importing this module never pulls the native
    extension. A missing package raises a LOUD :class:`RelinkError` (no silent
    fallback to a weaker hash — GATE: fail loud).
    """
    try:
        import blake3 as _blake3
    except ImportError as exc:  # the package is a declared dep; a missing one is loud
        raise RelinkError("the 'blake3' package is required for hash-verified relink but is not installed") from exc
    hasher = _blake3.blake3()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def content_hash_of(path: str, *, hash_file: HashFile | None = None) -> str:
    """Return the algorithm-prefixed whole-file digest of ``path`` (loud if absent).

    The byte-read goes through the injected ``hash_file`` seam (default
    :func:`blake3_file`); the existence check is here so a relink/pin against a
    vanished file fails loudly BEFORE any hashing attempt.
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"cannot hash a file that does not exist: {path}")
    reader = hash_file or blake3_file
    return format_digest(reader(path))


# --------------------------------------------------------------------------- #
# source resolution (reuses the lineage derived_from walk)
# --------------------------------------------------------------------------- #
def _source_status(entity: dict[str, Any]) -> dict[str, Any]:
    """A reveal row for one source entity: id/path/title + whether the file exists."""
    path = entity["path"]
    exists = bool(path) and Path(path).exists()
    return {"id": entity["id"], "path": path, "title": entity["title"], "exists": exists}


def _source_entities(conn: sqlite3.Connection, entity_id: str) -> list[dict[str, Any]]:
    """The ``role='source'`` entities ``entity_id`` derives from (itself if it IS a source).

    A source asset reveals/regenerates against its own file; a derived asset
    against the source-role ancestors it was ``derived_from`` (breadth-first,
    de-duplicated by the lineage walk). Non-source ancestors (intermediate derived
    rows) and id-only stubs with no entity row are excluded — only on-disk sources
    can be revealed or relinked.
    """
    sources: list[dict[str, Any]] = []
    own = _load_entity(conn, entity_id)
    if own is not None and own["role"] == SOURCE_ROLE:
        sources.append(own)
    for ancestor_id in _related_ids(conn, entity_id, ancestors=True):
        ancestor = _load_entity(conn, ancestor_id)
        if ancestor is not None and ancestor["role"] == SOURCE_ROLE:
            sources.append(ancestor)
    return sources


# --------------------------------------------------------------------------- #
# L5 operations (over the injected L1 Library façade)
# --------------------------------------------------------------------------- #
def reveal_source(library: Any, entity_id: str) -> dict[str, Any]:
    """Resolve ``entity_id`` to its by-path source file(s) for OS-reveal (DESIGN §3.4).

    Returns ``{id, sources:[{id,path,title,exists}], missing:[path,…]}``. ``missing``
    lists every source whose file is no longer on disk (the ``find_missing_sources``
    contract — surfaced loudly so the UI can offer a relink, never silently
    skipped). An unknown id raises :class:`RelinkError`.
    """
    with library._open() as conn:
        if _load_entity(conn, entity_id) is None:
            raise RelinkError(f"unknown asset: {entity_id}")
        sources = [_source_status(s) for s in _source_entities(conn, entity_id)]
    missing = [s["path"] for s in sources if not s["exists"]]
    return {"id": entity_id, "sources": sources, "missing": missing}


def regenerate(library: Any, entity_id: str) -> dict[str, Any]:
    """Build the replay descriptor for ``entity_id`` (DESIGN §3.3.3).

    Replays the producing activity (its ``op`` + redacted ``params``) against the
    still-by-path source. Returns ``{id, op, params, missing, ready}``; ``ready`` is
    ``False`` (and ``missing`` is populated) when any source file is gone — the
    caller must relink first, never silently regenerate from a missing source.
    Raises :class:`RelinkError` for an unknown id or a raw asset that Reframe never
    produced (nothing to regenerate).
    """
    with library._open() as conn:
        if _load_entity(conn, entity_id) is None:
            raise RelinkError(f"unknown asset: {entity_id}")
        provenance = _load_provenance(conn, entity_id)
        sources = [_source_status(s) for s in _source_entities(conn, entity_id)]
    if provenance is None:
        raise RelinkError(f"nothing to regenerate: {entity_id} was not produced by Reframe")
    missing = [s["path"] for s in sources if not s["exists"]]
    return {
        "id": entity_id,
        "op": provenance["op"],
        "params": provenance["params"],
        "missing": missing,
        "ready": not missing,
    }


def pin_source_hash(library: Any, entity_id: str, *, hash_file: HashFile | None = None) -> dict[str, Any]:
    """Record ``entity_id``'s whole-file BLAKE3 ``content_hash`` while its file exists.

    The baseline a later :func:`relink` verifies against. Raises :class:`RelinkError`
    for an unknown id and :class:`FileNotFoundError` when the file is already gone
    (you can only pin a hash while the original is present). Returns the updated
    entity dict (``contentHash`` now populated).
    """
    with library._open() as conn:
        entity = _load_entity(conn, entity_id)
        if entity is None:
            raise RelinkError(f"unknown asset: {entity_id}")
        path = entity["path"]
        if not path or not Path(path).exists():
            raise FileNotFoundError(f"cannot pin a content hash: the file for {entity_id} is missing: {path!r}")
        digest = content_hash_of(path, hash_file=hash_file)
        conn.execute("UPDATE entity SET content_hash = ? WHERE id = ?", (digest, entity_id))
    # Return the just-persisted state without a second read (the only changed
    # field is content_hash) — immutable copy, no unreachable re-load branch.
    return {**entity, "contentHash": digest}


def relink(library: Any, entity_id: str, new_path: str, *, hash_file: HashFile | None = None) -> dict[str, Any]:
    """HASH-VERIFIED re-point of ``entity_id`` to ``new_path`` (GATE L5, explicit ask).

    The whole-file BLAKE3 digest of ``new_path`` MUST equal the recorded
    ``content_hash``; only then is the entity's ``path`` re-pointed. A ``(size,
    mtime)`` stat is NOT accepted as content verification. Raises:

    * :class:`FileNotFoundError` — ``new_path`` does not exist.
    * :class:`RelinkError` — unknown id.
    * :class:`RelinkVerificationError` — no recorded hash to verify against (pin one
      first), or the new file's hash does not match the recorded digest.

    Returns the updated entity dict on success.
    """
    if not Path(new_path).exists():
        raise FileNotFoundError(f"cannot relink to a file that does not exist: {new_path}")
    with library._open() as conn:
        entity = _load_entity(conn, entity_id)
        if entity is None:
            raise RelinkError(f"unknown asset: {entity_id}")
        recorded = entity["contentHash"]
        if not recorded:
            raise RelinkVerificationError(
                f"cannot verify relink for {entity_id}: no recorded content hash. "
                "Pin the source hash while the original file is available, then relink."
            )
        new_digest = content_hash_of(new_path, hash_file=hash_file)
        if not digests_match(recorded, new_digest):
            raise RelinkVerificationError(
                f"relink refused for {entity_id}: {new_path} does not match the recorded "
                f"content hash (recorded {recorded}, got {new_digest})."
            )
        abspath = str(Path(new_path).resolve())
        conn.execute("UPDATE entity SET path = ? WHERE id = ?", (abspath, entity_id))
    # Return the just-persisted state without a second read (the only changed
    # field is path) — immutable copy, no unreachable re-load branch.
    return {**entity, "path": abspath}


__all__ = [
    "DIGEST_ALGO",
    "HashFile",
    "RelinkError",
    "RelinkVerificationError",
    "SOURCE_ROLE",
    "blake3_file",
    "content_hash_of",
    "digests_match",
    "format_digest",
    "pin_source_hash",
    "regenerate",
    "relink",
    "reveal_source",
]
