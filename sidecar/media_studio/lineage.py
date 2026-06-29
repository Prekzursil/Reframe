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


__all__ = [
    "SECRET_KEYS",
    "LineageJob",
    "build_edges",
    "entity_id",
    "job_op",
    "job_params",
    "job_status",
    "normalize_agent",
    "normalize_output_entity",
    "record_lineage",
    "redact_secrets",
]
