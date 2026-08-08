"""Pure validate-and-reject pass over an EditPlan (DESIGN §2.1/§5, WU-dsl).

Before an EditPlan is ever returned by ``director.plan`` (WU-plan-rpc), this pass
hard-checks every op's ``span`` against the real clip duration, track existence,
and per-kind preconditions. Impossible ops are **DROPPED** — but *never silently
discarded*: they are kept in the returned plan with ``status="dropped"`` and a
typed :data:`statusReason` so the storyboard (§7.3) can show the user EXACTLY
what was rejected and why (otherwise they silently get less than they asked for).

This is also the PRIMARY structural defense against prompt-injection from media
(DESIGN §5 #2): an op injected by on-screen/spoken text ("delete all clips") that
references an impossible span cannot survive validation, so it can never reach
apply. The human confirm gate is the BACKSTOP, not the only defense.

PURE: stdlib + the :mod:`edit_plan` model only — NO ``Provider``/transport import.
``validate_and_reject`` NEVER raises; it transforms a plan into a plan, marking
ops. Valid ops keep ``status="planned"``; rejected ops become ``status="dropped"``
with a reason. ORDER is always preserved (the storyboard renders ops in order).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from media_studio.models.edit_plan import EditOp, EditPlan

#: Typed drop reasons (DESIGN §2.1). Surfaced in the storyboard, NEVER trusted
#: as an instruction. FROZEN — the renderer maps these to plain-language copy.
StatusReason = Literal[
    "span-exceeds-clip",
    "span-inverted",
    "span-required",
    "unknown-track",
    "precondition-unmet",
]

#: Op kinds that act on a source range and therefore REQUIRE a valid ``span``.
#: Whole-timeline / artifact ops (``export``) are exempt.
_SPAN_REQUIRED_KINDS: frozenset[str] = frozenset(
    {
        "trim",
        "cut",
        "removeSilence",
        "removeFillers",
        "reorder",
        "retime",
        "reframe",
        "zoomPan",
        "stitchPanorama",
        "regenScroll",
        "ocrExtractList",
    }
)

#: Op kinds that operate on a named track and therefore require the track to
#: exist in the understanding (precondition: ``unknown-track`` otherwise).
_TRACK_KINDS: frozenset[str] = frozenset({"caption", "translateCaption", "overlayText", "lowerThird"})

#: Op kinds that bring OTHER clips to the timeline and therefore require a
#: non-empty ``params['clips']``. ``join`` appends them; ``transition`` overlaps
#: them — both are impossible with nothing to join to.
_CLIPS_REQUIRED_KINDS: frozenset[str] = frozenset({"join", "transition"})


@dataclass(frozen=True)
class Understanding:
    """The validated, machine-known facts an EditPlan is checked against.

    Pure data: the real clip duration (so out-of-range spans are dropped) and
    the set of tracks that actually exist (so unknown-track ops are dropped).
    ``regen_requires_panorama`` mirrors the canonical example precondition
    (DESIGN §3): ``regenScroll`` must reference a stitched panorama in params.
    """

    clip_duration_ms: int
    tracks: Sequence[str] = field(default_factory=tuple)
    require_regen_panorama: bool = True


def _reject(op: EditOp, reason: StatusReason) -> EditOp:
    """Mark an op dropped with a typed reason (immutable copy)."""
    return op.with_status("dropped", reason)


def _span_reason(span: tuple[int, int] | None, duration_ms: int) -> StatusReason | None:
    """Return the span rejection reason, or ``None`` if the span is valid."""
    if span is None:
        return "span-required"
    start, end = span
    if start >= end:
        return "span-inverted"
    if start < 0 or end > duration_ms:
        return "span-exceeds-clip"
    return None


def _params_str(params: Mapping[str, Any], key: str) -> str:
    """Read a string param defensively (missing/non-str -> empty)."""
    value = params.get(key)
    return value if isinstance(value, str) else ""


def _has_clips(params: Mapping[str, Any]) -> bool:
    """True when ``params['clips']`` is a non-empty list with a usable path string."""
    clips = params.get("clips")
    if not isinstance(clips, (list, tuple)) or not clips:
        return False
    return any(isinstance(p, str) and p.strip() for p in clips)


def _is_panorama_mapping(value: Any) -> bool:
    """True when ``value`` is the panorama MAPPING the regen engine can consume.

    Mirrors ``scroll_regen._require_panorama`` exactly: a string ``imagePath``,
    an int (never ``bool``) ``height``, and a list ``frameOffsets``. Keeping the
    two in step is the whole point — see :func:`_has_panorama`.
    """
    if not isinstance(value, Mapping):
        return False
    image_path = value.get("imagePath")
    height = value.get("height")
    offsets = value.get("frameOffsets")
    return (
        isinstance(image_path, str)
        and bool(image_path.strip())
        and isinstance(height, int)
        and not isinstance(height, bool)
        and isinstance(offsets, list)
    )


def _has_panorama(params: Mapping[str, Any]) -> bool:
    """True when ``params['panorama']`` is a usable artifact REFERENCE or MAPPING.

    v1.5 (SCOPE.md O-3) fixes a CONFIRMED contradiction. This precondition used
    to accept ONLY a string (``_params_str`` returns ``""`` for anything else),
    while ``scroll_regen._require_panorama`` accepts ONLY a mapping. Measured on
    the pre-fix tree:

        panorama as STRING -> validator "planned"           / engine REJECTED
        panorama as DICT   -> validator "precondition-unmet" / engine ACCEPTED

    So NO ``regenScroll`` op could be both validator-valid and engine-renderable
    — a declared-but-impossible op. Both shapes are now accepted: a bare string
    is an artifact REFERENCE resolved later, and a mapping is the inline
    artifact the engine consumes directly. A malformed mapping is still dropped,
    so this TIGHTENS the gate on garbage while unblocking the real shape.
    """
    value = params.get("panorama")
    if isinstance(value, str):
        return bool(value.strip())
    return _is_panorama_mapping(value)


def _precondition_reason(op: EditOp, understanding: Understanding) -> StatusReason | None:
    """Per-kind precondition checks beyond span/track, or ``None`` if satisfied.

    Two preconditions today:
      * ``regenScroll`` must reference a stitched panorama (DESIGN §3 canonical
        example) via ``params["panorama"]`` — either a string artifact reference
        or the inline mapping the engine consumes (:func:`_has_panorama`);
      * ``join`` must carry a non-empty ``params["clips"]`` list of paths to
        concatenate (V1 IA §h E2 — a join with nothing to join is impossible);
      * ``transition`` inherits that same precondition — it is a BOUNDARY
        treatment, and with a single clip there is no boundary to treat.

    ``transition`` deliberately does NOT join :data:`_SPAN_REQUIRED_KINDS`: it
    acts on the junction between clips, not on a source range, so demanding a
    span would drop every legitimate transition. The clip-length precondition a
    transition really has (each clip must outlast the transition) needs the
    PROBED duration of the extra clips, which this pure pass does not have — it
    is enforced at render time in ``transitions.xfade_offsets`` and surfaces as a
    per-op ``failed`` with auto-rollback.
    """
    if op.kind == "regenScroll" and understanding.require_regen_panorama and not _has_panorama(op.params):
        return "precondition-unmet"
    if op.kind in _CLIPS_REQUIRED_KINDS and not _has_clips(op.params):
        return "precondition-unmet"
    return None


def _op_reason(op: EditOp, understanding: Understanding) -> StatusReason | None:
    """Compute the single rejection reason for an op, or ``None`` if it is valid."""
    if op.kind in _SPAN_REQUIRED_KINDS:
        span_reason = _span_reason(op.span, understanding.clip_duration_ms)
        if span_reason is not None:
            return span_reason
    if op.kind in _TRACK_KINDS:
        track = _params_str(op.params, "track")
        if track not in set(understanding.tracks):
            return "unknown-track"
    return _precondition_reason(op, understanding)


def validate_and_reject(plan: EditPlan, *, understanding: Understanding) -> EditPlan:
    """Return a copy of ``plan`` with impossible ops marked ``status="dropped"``.

    PURE and total (never raises). For each op, exactly one of:
      * valid -> kept with ``status="planned"`` (untouched ordering);
      * impossible -> ``status="dropped"`` + a typed :data:`StatusReason`.

    Already-``dropped`` ops (e.g. the planner pre-marked one) are left as-is.
    Order is ALWAYS preserved — the storyboard renders ops top-to-bottom.
    """
    validated: list[EditOp] = []
    for op in plan.ops:
        if op.status == "dropped":
            validated.append(op)
            continue
        reason = _op_reason(op, understanding)
        validated.append(op if reason is None else _reject(op, reason))
    return replace(plan, ops=tuple(validated))
