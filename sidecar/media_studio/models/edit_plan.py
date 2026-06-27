"""The typed, ordered, REVERSIBLE EditPlan document (DESIGN §2.1, WU-dsl).

This is the FOUNDATION of the Director agent: the planner is a *pure* function
``prompt + understanding -> EditPlan`` (FEATURE.md:40), so it is testable to 100%
without ever rendering. This module defines the schema deferred to PLAN in
DESIGN §9 ("exact EditPlan JSON schema"):

  * :class:`EditPlan` — ``{planId, videoId, goal, sourceHash, ops, inverse}``,
    a ``@dataclass(frozen=True)`` (immutable, like the existing ``Candidate``
    select result).
  * :class:`EditOp` — the tagged union ``{id, kind, span, params, reversible,
    rationale, status, statusReason}`` whose ``kind`` selects the variant
    (DESIGN §2.2 toolbox).
  * :func:`to_json` / :func:`from_json` — a CANONICAL, deterministic
    (sorted-key) round-trip so ``to_json(from_json(x)) == x`` byte-for-byte,
    which the storyboard/cache correlation relies on.
  * :func:`edit_plan_json_schema` — a plain JSON-schema ``dict`` the renderer
    mirrors as a TS type (``app/renderer/src/lib/directorTypes.ts``, WU-panel).

PURITY (acceptance (d)): this module imports ONLY stdlib — NO ``Provider`` /
transport / heavy-ML import. The planner stays a pure transform; the actual LLM
call is WU-plan-rpc via ``_run_ai_job``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, get_args

# ---------------------------------------------------------------------------
# Typed enumerations (FROZEN — every other WU consumes these). Centralized so
# the dataclasses, the validator, the prompt builder, and the JSON schema all
# read from ONE source of truth.
# ---------------------------------------------------------------------------

#: The v1 operation toolbox (DESIGN §2.2). ``applyEngine`` is the RUNNER
#: (WU-apply), not an op kind — it is intentionally absent here.
OpKind = Literal[
    "trim",
    "cut",
    "join",
    "removeSilence",
    "removeFillers",
    "reorder",
    "retime",
    "reframe",
    "zoomPan",
    "caption",
    "translateCaption",
    "overlayText",
    "lowerThird",
    "export",
    "stitchPanorama",
    "regenScroll",
    "ocrExtractList",
]

#: Per-op lifecycle (DESIGN §2.1/§7.3). The planner emits ``planned``/``dropped``;
#: the apply engine (WU-apply) sets ``applied``/``failed``.
OpStatus = Literal["planned", "applied", "failed", "dropped"]

#: The set of valid op kinds, derived from :data:`OpKind` (single source).
OP_KINDS: tuple[str, ...] = get_args(OpKind)
#: The set of valid statuses, derived from :data:`OpStatus`.
OP_STATUSES: tuple[str, ...] = get_args(OpStatus)


class EditPlanError(ValueError):
    """Typed error for malformed EditPlan JSON / planner output (WU-dsl).

    A :class:`ValueError` subclass so callers may catch either; raised by
    :func:`from_json` and the WU-dsl ``parse_edit_plan`` on structurally
    invalid input (the validate-and-reject pass, by contrast, never raises — it
    DROPS impossible ops with a typed reason).
    """


@dataclass(frozen=True)
class EditOp:
    """A single ordered operation in an EditPlan (DESIGN §2.1).

    ``span`` is the source range the op acts on (``None`` for whole-timeline
    ops). ``params`` is a kind-specific, schema-validated mapping (stored as an
    immutable copy). ``reversible=False`` ops are GATED at apply-time (§5).
    ``rationale``/``statusReason`` are model/engine text shown in the
    storyboard but NEVER trusted as instructions (DESIGN §5 #1).
    """

    id: str
    kind: OpKind
    span: tuple[int, int] | None = None
    params: Mapping[str, Any] = field(default_factory=dict)
    reversible: bool = True
    rationale: str = ""
    status: OpStatus = "planned"
    status_reason: str | None = None

    def with_status(self, status: OpStatus, reason: str | None = None) -> EditOp:
        """Return a copy with ``status``/``status_reason`` replaced (immutable)."""
        return replace(self, status=status, status_reason=reason)


@dataclass(frozen=True)
class EditPlan:
    """The typed, ordered, reversible edit document (DESIGN §2.1).

    ``ops`` is the ORDERED, deterministic operation list; ``inverse`` is the
    undo plan filled at apply-time (WU-apply, §5) — empty until then.
    """

    plan_id: str
    video_id: str
    goal: str
    source_hash: str
    ops: tuple[EditOp, ...] = ()
    inverse: tuple[EditOp, ...] = ()


# ---------------------------------------------------------------------------
# Canonical JSON round-trip (deterministic, sorted-key)
# ---------------------------------------------------------------------------


def _span_to_json(span: tuple[int, int] | None) -> list[int] | None:
    """Render a span tuple as a ``[startMs, endMs]`` list (JSON has no tuples)."""
    if span is None:
        return None
    return [span[0], span[1]]


def _op_to_dict(op: EditOp) -> dict[str, Any]:
    """Render one :class:`EditOp` as a canonical, JSON-ready dict."""
    return {
        "id": op.id,
        "kind": op.kind,
        "span": _span_to_json(op.span),
        "params": dict(op.params),
        "reversible": op.reversible,
        "rationale": op.rationale,
        "status": op.status,
        "statusReason": op.status_reason,
    }


def plan_to_dict(plan: EditPlan) -> dict[str, Any]:
    """Render an :class:`EditPlan` as a canonical, JSON-ready dict."""
    return {
        "planId": plan.plan_id,
        "videoId": plan.video_id,
        "goal": plan.goal,
        "sourceHash": plan.source_hash,
        "ops": [_op_to_dict(op) for op in plan.ops],
        "inverse": [_op_to_dict(op) for op in plan.inverse],
    }


def to_json(plan: EditPlan) -> str:
    """Serialize an :class:`EditPlan` to a CANONICAL JSON string.

    Deterministic: keys sorted, compact separators, no whitespace drift — so
    ``to_json(from_json(x)) == x`` holds byte-for-byte (acceptance (c)) and the
    string is a stable cache/diff anchor.
    """
    return json.dumps(plan_to_dict(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require_str(obj: Mapping[str, Any], key: str) -> str:
    """Read a required string field, raising :class:`EditPlanError` if absent/wrong-type."""
    value = obj.get(key)
    if not isinstance(value, str):
        raise EditPlanError(f"missing or non-string field: {key!r}")
    return value


def _span_from_json(raw: Any) -> tuple[int, int] | None:
    """Parse a ``[startMs, endMs]`` list into a span tuple (or ``None``)."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise EditPlanError(f"span must be a [startMs, endMs] pair, got {raw!r}")
    try:
        return (int(raw[0]), int(raw[1]))
    except (TypeError, ValueError) as exc:
        raise EditPlanError(f"span bounds must be integers, got {raw!r}") from exc


def _op_from_dict(raw: Any) -> EditOp:
    """Parse one op dict into a typed :class:`EditOp` (raises on bad shape)."""
    if not isinstance(raw, Mapping):
        raise EditPlanError(f"op must be an object, got {type(raw).__name__}")
    kind = _require_str(raw, "kind")
    if kind not in OP_KINDS:
        raise EditPlanError(f"unknown op kind: {kind!r}")
    status = raw.get("status", "planned")
    if status not in OP_STATUSES:
        raise EditPlanError(f"unknown op status: {status!r}")
    params = raw.get("params", {})
    if not isinstance(params, Mapping):
        raise EditPlanError("op params must be an object")
    reason = raw.get("statusReason")
    if reason is not None and not isinstance(reason, str):
        raise EditPlanError("statusReason must be a string or null")
    return EditOp(
        id=_require_str(raw, "id"),
        kind=kind,  # type: ignore[arg-type]  # membership checked above
        span=_span_from_json(raw.get("span")),
        params=dict(params),
        reversible=bool(raw.get("reversible", True)),
        rationale=str(raw.get("rationale", "")),
        status=status,  # type: ignore[arg-type]  # membership checked above
        status_reason=reason,
    )


def _ops_from_json(raw: Any, key: str) -> tuple[EditOp, ...]:
    """Parse the ``ops``/``inverse`` array (default empty) into typed ops."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise EditPlanError(f"{key} must be an array")
    return tuple(_op_from_dict(item) for item in raw)


def from_dict(obj: Any) -> EditPlan:
    """Parse a JSON-ready dict into a typed :class:`EditPlan` (raises on bad shape)."""
    if not isinstance(obj, Mapping):
        raise EditPlanError(f"EditPlan must be an object, got {type(obj).__name__}")
    return EditPlan(
        plan_id=_require_str(obj, "planId"),
        video_id=_require_str(obj, "videoId"),
        goal=_require_str(obj, "goal"),
        source_hash=_require_str(obj, "sourceHash"),
        ops=_ops_from_json(obj.get("ops"), "ops"),
        inverse=_ops_from_json(obj.get("inverse"), "inverse"),
    )


def from_json(text: str) -> EditPlan:
    """Parse a JSON string into a typed :class:`EditPlan`.

    Raises :class:`EditPlanError` on invalid JSON or a structurally invalid
    plan (unknown kind/status, malformed span, missing required field).
    """
    try:
        obj = json.loads(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise EditPlanError(f"EditPlan is not valid JSON: {exc}") from exc
    return from_dict(obj)


# ---------------------------------------------------------------------------
# JSON schema export (for the renderer's TS mirror — WU-panel)
# ---------------------------------------------------------------------------


def edit_plan_json_schema() -> dict[str, Any]:
    """Return a JSON-schema ``dict`` describing the EditPlan wire shape.

    The renderer (WU-panel) mirrors this as ``directorTypes.ts`` so the panel is
    typed against ONE source of truth. Spans are ``[startMs, endMs]`` integer
    pairs; ``kind``/``status`` enumerate the frozen vocabularies above.
    """
    span_schema = {
        "type": ["array", "null"],
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
        "description": "Source range [startMs, endMs], or null for whole-timeline ops.",
    }
    op_schema = {
        "type": "object",
        "required": ["id", "kind", "reversible", "status"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": list(OP_KINDS)},
            "span": span_schema,
            "params": {"type": "object"},
            "reversible": {"type": "boolean"},
            "rationale": {"type": "string"},
            "status": {"type": "string", "enum": list(OP_STATUSES)},
            "statusReason": {"type": ["string", "null"]},
        },
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "EditPlan",
        "type": "object",
        "required": ["planId", "videoId", "goal", "sourceHash", "ops", "inverse"],
        "additionalProperties": False,
        "properties": {
            "planId": {"type": "string"},
            "videoId": {"type": "string"},
            "goal": {"type": "string"},
            "sourceHash": {"type": "string"},
            "ops": {"type": "array", "items": op_schema},
            "inverse": {"type": "array", "items": op_schema},
        },
    }
