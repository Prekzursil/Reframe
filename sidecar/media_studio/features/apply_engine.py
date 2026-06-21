"""The applyEngine: walk an EditPlan over a project COPY, recording an inverse
(DESIGN §5, GAP-1, PLAN.md §WU-apply — build FIRST, "unretrofittable").

This is the reversibility layer the in-place handlers lack. Today every handler
mutates ``project.data`` in place and ``project.save()``s with **no undo**
(``subtitles_edit`` walks tracks then saves, ``handlers.py:234/743``).
:func:`apply_plan` instead:

  * applies ``plan.ops`` **in order** over a project COPY (never the source);
  * dispatches each op to its engine via an **injected dispatch table**
    ``{kind: callable}`` (the seam — real impls are the shipped engines; tests
    inject fakes), and **records the inverse op** the engine returns;
  * gates ``reversible=False`` ops behind an explicit ``allow_irreversible``
    second-confirm (DESIGN §5);
  * on the FIRST op that throws → **stops** (no further ops run), marks that op
    ``failed`` + a typed reason, leaves unreached ops ``planned``, then
    **auto-rolls-back the COPY** by walking the recorded inverse in reverse
    (DESIGN §5 — the source manifest was never touched, so rollback is just
    inverting the COPY). v1 is all-or-nothing stop-on-first-failure.

The returned ``inverse_plan`` (an :class:`EditPlan` whose ``inverse`` holds the
recorded undo ops, newest-first) re-applied to the post-apply COPY restores the
pre-apply COPY — the one-shot undo (acceptance c; WU-undo reuses this).

PURITY: stdlib + the ``edit_plan``/``project_copy`` models only — NO
``Provider``/transport/heavy-ML import. The heavy engine calls live BEHIND the
injected table, so the dispatch + ordering + rollback logic is fully testable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from media_studio.features.project_copy import ProjectCopy
from media_studio.models.edit_plan import EditOp, EditPlan

#: An op-engine: applies the op to the COPY and returns the INVERSE op to undo it.
#: Real impls are the shipped engines (silencetrim/fillers/reframe/...); tests
#: inject fakes. Registered per ``kind`` in the dispatch table.
OpEngine = Callable[[EditOp, ProjectCopy], EditOp]
#: A kind -> engine dispatch table (the injected seam).
EngineTable = Mapping[str, OpEngine]


class ApplyError(RuntimeError):
    """Raised only when AUTO-ROLLBACK itself fails (DESIGN §5).

    A forward-op failure is NOT an :class:`ApplyError` — it is captured as the
    op's ``status="failed"`` and the COPY is rolled back. An ``ApplyError`` means
    even the inverse walk threw, so the COPY may be in an indeterminate state;
    the source manifest (untouched) is the durable fallback.
    """


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of :func:`apply_plan` (DESIGN §5, PLAN §WU-apply).

    ``ops_status`` is the per-op lifecycle after apply (``applied``/``failed``/
    ``planned``/``dropped``), in plan order. ``inverse_plan`` carries the recorded
    inverse ops (in ``inverse``, newest-first) for one-shot undo. ``project_copy_path``
    is the COPY manifest path the engine wrote to (never the source).
    """

    ops_status: tuple[EditOp, ...]
    inverse_plan: EditPlan
    project_copy_path: str


def _rollback(
    applied_inverse: list[EditOp],
    project_copy: ProjectCopy,
    inverse_engines: EngineTable,
) -> None:
    """Walk the recorded inverse ops (newest-first) to restore the COPY.

    Raises :class:`ApplyError` if an inverse engine throws — the COPY is then
    indeterminate and the (untouched) source is the fallback (DESIGN §5).
    """
    for inv in applied_inverse:
        engine = inverse_engines.get(inv.kind)
        if engine is None:  # pragma: no cover - inverse kind always matches a forward kind
            continue
        try:
            engine(inv, project_copy)
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed ApplyError
            raise ApplyError(f"rollback failed at {inv.id!r}: {exc}") from exc


def apply_plan(
    plan: EditPlan,
    *,
    project_copy: ProjectCopy,
    engines: EngineTable,
    inverse_engines: EngineTable | None = None,
    allow_irreversible: bool = False,
) -> ApplyResult:
    """Apply ``plan.ops`` over ``project_copy`` in order, recording the inverse.

    Stop-on-first-failure with auto-rollback (DESIGN §5). ``engines`` maps each
    ``kind`` to its op-engine; ``inverse_engines`` (default = ``engines``) runs
    the recorded inverse during rollback. ``allow_irreversible`` is the
    second-confirm gate for ``reversible=False`` ops.

    Never mutates the source manifest. Returns the per-op statuses + the recorded
    ``inverse_plan`` (newest-first) for one-shot undo.
    """
    undo = inverse_engines if inverse_engines is not None else engines
    statuses: list[EditOp] = []
    recorded: list[EditOp] = []  # inverse ops, newest-first (prepended)
    failed = False

    for op in plan.ops:
        if failed:
            statuses.append(op)  # unreached: left as-is (planner emitted "planned")
            continue
        if op.status == "dropped":
            statuses.append(op)  # already rejected by validate_and_reject (WU-dsl)
            continue
        if not op.reversible and not allow_irreversible:
            statuses.append(op.with_status("dropped", "irreversible-unconfirmed"))
            continue
        engine = engines.get(op.kind)
        if engine is None:
            statuses.append(op.with_status("failed", f"no engine for kind {op.kind!r}"))
            failed = True
            _rollback(recorded, project_copy, undo)
            continue
        try:
            inverse_op = engine(op, project_copy)
        except Exception as exc:  # noqa: BLE001 - captured as op status, then rollback
            statuses.append(op.with_status("failed", str(exc)))
            failed = True
            _rollback(recorded, project_copy, undo)
            continue
        statuses.append(op.with_status("applied"))
        recorded.insert(0, inverse_op)  # newest-first: rollback/undo walks in reverse

    # The inverse plan is RUNNABLE: its ``ops`` are the recorded inverse ops
    # (newest-first), so feeding ``inverse_plan`` straight back into
    # :func:`apply_plan` performs the one-shot undo (WU-undo reuses this). The
    # same ops are mirrored in ``inverse`` for symmetry with the forward plan.
    inverse_plan = replace(plan, ops=tuple(recorded), inverse=tuple(recorded))
    return ApplyResult(
        ops_status=tuple(statuses),
        inverse_plan=inverse_plan,
        project_copy_path=str(project_copy.manifest_path),
    )
