"""L2 — record provenance (W3C-PROV) on a successful Job (DESIGN §3.3).

On ``Job`` success an op may *opt in* to a lineage append: one ``activity`` row
(what ran) + its ``agent`` (which app/route/preset ran it) + ``entity`` rows for
the OUTPUTS produced + ``edge`` rows wiring them together::

    output  --generated_by-->  activity        (PROV ``wasGeneratedBy``)
    output  --derived_from-->  input source    (PROV ``wasDerivedFrom``)
    activity --used-->         input source    (PROV ``used``)
    activity --associated_with--> agent        (PROV ``wasAssociatedWith``)

The whole append is ONE transaction (``BEGIN``/``COMMIT`` over the L1 SQLite
store; any failure ``ROLLBACK``s so a half-written derivation never persists).
The agent records the **resolved RoutingPolicy from M3** (the route the job
actually took) so "regenerate this short" (L5) can replay the real route.

Security keystone (GATE-2 / §WU-keys): both the activity ``params_json`` and the
``agent`` (incl. its ``route``) are run through :func:`redact_secrets` — a deep,
recursive scrub that reuses ``models.secrets.redact`` / :func:`redact_keys` — so
NO raw API key ever lands in a lineage row. ``redact_secrets`` reveals at most a
key's last 4 chars (never the full secret), exactly like the RPC-facing redactor.

PURE builders (``redact_secrets`` / ``job_*`` / ``normalize_*`` / ``build_edges``)
take no I/O and are unit-tested in isolation; only :func:`record_lineage` touches
the DB (through the injected :class:`~media_studio.library.Library` façade), so it
is never coupled to :mod:`media_studio.jobs` — a ``job`` is read structurally
(:class:`LineageJob`).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from .library import _ENTITY_COLUMNS, _new_id, _now_iso
from .models.secrets import redact, redact_keys

#: Lower-cased dict-key names whose VALUE is treated as a secret and redacted to
#: its last-4 form before any lineage write. ``apiKeys`` is also handled directly;
#: a ``providers`` list reuses the provider-shaped :func:`redact_keys`.
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "apikey",
        "apikeys",
        "api_key",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "authorization",
        "bearer",
    }
)

#: PROV relation labels written to the ``edge`` table.
REL_GENERATED_BY = "generated_by"
REL_DERIVED_FROM = "derived_from"
REL_USED = "used"
REL_ASSOCIATED_WITH = "associated_with"

#: Default ``entity.kind`` / ``role`` for a produced output that names no kind.
DEFAULT_OUTPUT_KIND = "output"
OUTPUT_ROLE = "output"


class LineageJob(Protocol):
    """The structural shape :func:`record_lineage` reads from a completed job.

    A :class:`media_studio.jobs.Job` satisfies this (``id`` / ``status`` /
    ``request``) so lineage never imports the jobs module; tests pass any object
    with these attributes.
    """

    id: str
    status: Any
    request: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# deep secret redaction (reuses models.secrets.redact / redact_keys)
# --------------------------------------------------------------------------- #
def _redact_value(value: Any) -> Any:
    """Redact the value found under a secret-named key.

    A list (e.g. ``apiKeys``) is redacted element-wise; a bare string to its
    last-4 form; anything else recurses (a nested object under a secret key is
    still scrubbed, never passed through raw).
    """
    if isinstance(value, list):
        return [redact(str(item)) for item in value]
    if isinstance(value, str):
        return redact(value)
    return redact_secrets(value)


def redact_secrets(value: Any) -> Any:
    """Return a deep copy of ``value`` with every secret scrubbed (PURE).

    Recurses through dicts/lists. For a dict, a ``providers`` list is redacted
    with the provider-shaped :func:`redact_keys`; any key whose lower-cased name
    is in :data:`SECRET_KEYS` has its value redacted via :func:`_redact_value`;
    every other value recurses. Non-container scalars pass through unchanged.
    Never mutates the input.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, val in value.items():
            if isinstance(key, str) and key.lower() == "providers" and isinstance(val, list):
                out[key] = redact_keys(val)
            elif isinstance(key, str) and key.lower() in SECRET_KEYS:
                out[key] = _redact_value(val)
            else:
                out[key] = redact_secrets(val)
        return out
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def _dump(value: Any) -> str | None:
    """JSON-encode an already-redacted value (stable key order), or ``None``."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------------- #
# job field extractors (structural — no jobs.py import)
# --------------------------------------------------------------------------- #
def job_op(job: LineageJob) -> str:
    """The activity ``op`` = the job's originating RPC method (or ``""``)."""
    request = job.request
    if isinstance(request, dict):
        method = request.get("method")
        if isinstance(method, str):
            return method
    return ""


def job_status(job: LineageJob) -> str:
    """The activity ``status`` = the job's wire status value (e.g. ``"done"``)."""
    value = getattr(job.status, "value", None)
    return value if isinstance(value, str) else str(job.status)


def job_params(job: LineageJob) -> Any:
    """The job's request ``params`` (pre-redaction), or ``None``."""
    request = job.request
    if isinstance(request, dict):
        return request.get("params")
    return None


# --------------------------------------------------------------------------- #
# entity / agent normalization
# --------------------------------------------------------------------------- #
def entity_id(entity: Any) -> str:
    """The id of an input/output entity dict, or a fresh id when absent."""
    eid = entity.get("id") if isinstance(entity, dict) else None
    if isinstance(eid, str) and eid:
        return eid
    return _new_id()


def normalize_output_entity(out: Any) -> dict[str, Any]:
    """Normalize a produced-output dict to a full ``role='output'`` entity row.

    Mirrors :meth:`Library._normalize` column-for-column (so an output reads back
    through the same ``entity`` shape as a source), defaulting every field so a
    sparse / non-dict output never raises on insert. ``contentHash`` stays
    nullable (unpopulated until L6).
    """
    src = out if isinstance(out, dict) else {}
    return {
        "id": entity_id(src),
        "kind": str(src.get("kind") or DEFAULT_OUTPUT_KIND),
        "path": str(src.get("path") or ""),
        "role": OUTPUT_ROLE,
        "title": str(src.get("title") or ""),
        "addedAt": str(src.get("addedAt") or _now_iso()),
        "durationSec": float(src.get("durationSec") or 0.0),
        "contentHash": src.get("contentHash"),
        "hasTranscript": bool(src.get("hasTranscript", False)),
        "thumbnailPath": str(src.get("thumbnailPath") or ""),
    }


def normalize_agent(agent: Any) -> tuple[str, str, str | None, str]:
    """Return ``(agent_id, app_version, route_json, preset)`` from an agent dict.

    The agent records the resolved RoutingPolicy from M3 as ``route`` — scrubbed
    through :func:`redact_secrets` (a defensive cloud route could carry a key) and
    serialized to ``route_json``. A non-dict agent degrades to empty fields with a
    fresh id (never raises).
    """
    safe = redact_secrets(agent) if isinstance(agent, dict) else {}
    app_version = str(safe.get("appVersion") or "")
    route_json = _dump(safe.get("route"))
    preset = str(safe.get("preset") or "")
    return _new_id(), app_version, route_json, preset


# --------------------------------------------------------------------------- #
# edges (PROV relations)
# --------------------------------------------------------------------------- #
def build_edges(
    activity_id: str,
    agent_id: str,
    output_ids: list[str],
    input_ids: list[str],
) -> list[tuple[str, str, str]]:
    """Build the ``(src, dst, rel)`` PROV edges for one lineage append (PURE)."""
    edges: list[tuple[str, str, str]] = [(activity_id, agent_id, REL_ASSOCIATED_WITH)]
    for iid in input_ids:
        edges.append((activity_id, iid, REL_USED))
    for oid in output_ids:
        edges.append((oid, activity_id, REL_GENERATED_BY))
        for iid in input_ids:
            edges.append((oid, iid, REL_DERIVED_FROM))
    return edges


# --------------------------------------------------------------------------- #
# the write (single transaction over the L1 SQLite store)
# --------------------------------------------------------------------------- #
def _insert_entity_row(conn: sqlite3.Connection, entity: dict[str, Any]) -> None:
    """Insert one normalized output ``entity`` row (parameterized ``?`` SQL only)."""
    conn.execute(
        f"INSERT OR REPLACE INTO entity ({_ENTITY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            entity["id"],
            entity["kind"],
            entity["path"],
            entity["role"],
            entity["title"],
            entity["addedAt"],
            float(entity["durationSec"]),
            entity["contentHash"],
            int(bool(entity["hasTranscript"])),
            entity["thumbnailPath"],
        ),
    )


def record_lineage(
    library: Any,
    job: LineageJob,
    inputs: list[Any],
    outputs: list[Any],
    agent: Any,
) -> str:
    """Append one lineage record for a successful ``job`` and return the activity id.

    Writes the ``agent`` + ``activity`` + output ``entity`` rows + PROV ``edge``
    rows in ONE transaction over the L1 SQLite store (``library._open()``); any
    error ``ROLLBACK``s the whole append. ``params_json`` and the ``agent`` are
    redacted (:func:`redact_secrets`) before the write so no raw key persists.
    This is the opt-in helper from §3.3 — an op that does not want lineage simply
    never calls it (zero behaviour change).
    """
    agent_id, app_version, route_json, preset = normalize_agent(agent)
    activity_id = _new_id()
    params_json = _dump(redact_secrets(job_params(job)))
    timestamp = _now_iso()
    output_entities = [normalize_output_entity(o) for o in outputs]
    input_ids = [entity_id(i) for i in inputs]
    output_ids = [e["id"] for e in output_entities]
    edges = build_edges(activity_id, agent_id, output_ids, input_ids)

    with library._open() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                "INSERT INTO agent (id, app_version, route_json, preset) VALUES (?, ?, ?, ?)",
                (agent_id, app_version, route_json, preset),
            )
            conn.execute(
                "INSERT INTO activity"
                " (id, op, started_at, ended_at, status, params_json, agent_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (activity_id, job_op(job), timestamp, timestamp, job_status(job), params_json, agent_id),
            )
            for entity in output_entities:
                _insert_entity_row(conn, entity)
            for src, dst, rel in edges:
                conn.execute("INSERT INTO edge (src, dst, rel) VALUES (?, ?, ?)", (src, dst, rel))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return activity_id


# --------------------------------------------------------------------------- #
# L3 — lineage_of(): ancestors / descendants query (recursive edge walk)
# --------------------------------------------------------------------------- #
def _row_to_entity(row: sqlite3.Row) -> dict[str, Any]:
    """Reconstruct a full entity dict from an ``entity`` row (all columns).

    Richer than :meth:`Library._row_to_video` (carries ``kind``/``role``/
    ``contentHash``) because a lineage node can be a source, a derived output,
    or an export. ``duration_sec`` is always written as a float (never NULL),
    ``content_hash`` is the only nullable column.
    """
    return {
        "id": row["id"],
        "kind": row["kind"],
        "path": row["path"],
        "role": row["role"],
        "title": row["title"],
        "addedAt": row["added_at"],
        "durationSec": float(row["duration_sec"]),
        "contentHash": row["content_hash"],
        "hasTranscript": bool(row["has_transcript"]),
        "thumbnailPath": row["thumbnail_path"],
    }


def _load_entity(conn: sqlite3.Connection, eid: str) -> dict[str, Any] | None:
    """Return the full entity dict for ``eid`` (any role), or ``None`` if absent."""
    row = conn.execute("SELECT * FROM entity WHERE id = ?", (eid,)).fetchone()
    return _row_to_entity(row) if row is not None else None


def _resolve_entity(conn: sqlite3.Connection, eid: str) -> dict[str, Any]:
    """Resolve ``eid`` to its entity dict, or a loud ``{id, missing}`` stub.

    A ``derived_from`` edge can point at an id with no ``entity`` row (e.g. an
    input that was referenced by id but never added as a library source). Such a
    node is surfaced as a ``missing`` stub — never silently dropped from the
    derivation — so the UI can show "source no longer in library".
    """
    entity = _load_entity(conn, eid)
    if entity is None:
        return {"id": eid, "missing": True}
    return entity


def _step(conn: sqlite3.Connection, eid: str, *, ancestors: bool) -> list[str]:
    """One hop along ``derived_from`` edges (deterministic ``rowid`` order).

    ancestors (where it came from): follow ``src=eid -> dst`` (the parents an
    output was derived from). descendants (what was made from it): follow
    ``dst=eid -> src`` (the children derived from this node).
    """
    if ancestors:
        rows = conn.execute(
            "SELECT dst FROM edge WHERE src = ? AND rel = ? ORDER BY rowid",
            (eid, REL_DERIVED_FROM),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT src FROM edge WHERE dst = ? AND rel = ? ORDER BY rowid",
            (eid, REL_DERIVED_FROM),
        ).fetchall()
    return [r[0] for r in rows]


def _related_ids(conn: sqlite3.Connection, start_id: str, *, ancestors: bool) -> list[str]:
    """BFS the ``derived_from`` graph from ``start_id`` (cycle-/diamond-safe).

    Returns the related ids in breadth-first order, each appearing exactly once
    (a ``seen`` set — pre-seeded with ``start_id`` — collapses shared ancestors,
    re-convergence and any cycle back to the root).
    """
    seen: set[str] = {start_id}
    order: list[str] = []
    frontier: list[str] = [start_id]
    while frontier:
        nxt: list[str] = []
        for eid in frontier:
            for nid in _step(conn, eid, ancestors=ancestors):
                if nid in seen:
                    continue
                seen.add(nid)
                order.append(nid)
                nxt.append(nid)
        frontier = nxt
    return order


def _parse_json(text: Any) -> Any:
    """Decode a stored JSON column back to a value; empty/``NULL`` -> ``None``.

    Mirrors :func:`_dump` (the write side): an absent ``params_json`` /
    ``route_json`` was stored as SQL ``NULL`` (``None``), which round-trips to
    ``None`` here rather than raising.
    """
    if not text:
        return None
    return json.loads(text)


def _load_provenance(conn: sqlite3.Connection, eid: str) -> dict[str, Any] | None:
    """Resolve the producing activity + agent of ``eid`` for the L4 detail card.

    Follows the ``output --generated_by--> activity --(agent_id)--> agent`` chain
    (one ``generated_by`` edge per produced entity; earliest ``rowid`` wins if an
    id were ever regenerated). Returns the activity's ``op``/``status``/timestamps
    + its redacted ``params`` and the agent's ``appVersion``/``preset``/``route``
    (the resolved M3 RoutingPolicy) — exactly what the provenance card maps to
    FRIENDLY op/model labels. ``None`` when ``eid`` was never produced by an
    activity (a raw imported source, an unknown id, or a dangling edge whose
    activity row is absent — the INNER JOIN drops it rather than guessing).
    """
    row = conn.execute(
        "SELECT a.op AS op, a.status AS status, a.started_at AS started_at,"
        " a.ended_at AS ended_at, a.params_json AS params_json,"
        " g.app_version AS app_version, g.route_json AS route_json, g.preset AS preset"
        " FROM edge e"
        " JOIN activity a ON a.id = e.dst"
        " LEFT JOIN agent g ON g.id = a.agent_id"
        " WHERE e.src = ? AND e.rel = ? ORDER BY e.rowid LIMIT 1",
        (eid, REL_GENERATED_BY),
    ).fetchone()
    if row is None:
        return None
    return {
        "op": row["op"],
        "status": row["status"],
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"],
        "params": _parse_json(row["params_json"]),
        "appVersion": row["app_version"],
        "preset": row["preset"],
        "route": _parse_json(row["route_json"]),
    }


def lineage_of(library: Any, entity_id: str) -> dict[str, Any]:
    """Return the provenance of ``entity_id`` — ancestors + descendants (DESIGN §3.2).

    ``ancestors`` = where it came from (the transitive ``derived_from`` chain
    upward); ``descendants`` = what was made from it (the chain downward). Each is
    a list of full entity dicts (or a ``missing`` stub for a referenced-but-absent
    node), in breadth-first order. ``entity`` is the queried node itself
    (``None`` when the id is unknown). ``provenance`` is the producing activity +
    agent of the queried node (``None`` for a raw source) — the L4 detail card's
    data source. One read transaction over the L1 store.
    """
    with library._open() as conn:
        entity = _load_entity(conn, entity_id)
        ancestors = [_resolve_entity(conn, i) for i in _related_ids(conn, entity_id, ancestors=True)]
        descendants = [_resolve_entity(conn, i) for i in _related_ids(conn, entity_id, ancestors=False)]
        provenance = _load_provenance(conn, entity_id)
    return {
        "id": entity_id,
        "entity": entity,
        "ancestors": ancestors,
        "descendants": descendants,
        "provenance": provenance,
    }


__all__ = [
    "SECRET_KEYS",
    "LineageJob",
    "build_edges",
    "entity_id",
    "job_op",
    "job_params",
    "job_status",
    "lineage_of",
    "normalize_agent",
    "normalize_output_entity",
    "record_lineage",
    "redact_secrets",
]
