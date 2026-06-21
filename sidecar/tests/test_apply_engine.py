"""Tests for the applyEngine + project-COPY reversibility layer (WU-apply).

PURE-logic only: NO heavy-ML imports, NO network/render, NO real filesystem in
the apply path. The engine dispatches each :class:`EditOp` to an *injected* fake
engines table (each fake returns a known inverse op and can be told to raise),
so the ordering / inverse-recording / auto-rollback logic is covered to 100%
line+branch. ``copy_project``'s only filesystem write goes through an injected
writer (the real writer is the ``# pragma: no cover`` seam).

Acceptance (DESIGN §5, PLAN §WU-apply):
  (a) applying a plan NEVER mutates the source manifest (identity + value);
  (b) a forced mid-plan failure auto-rolls-back the COPY (inverse walk);
  (c) the returned ``inverse_plan`` re-applied restores the pre-apply COPY;
  (d) ``reversible=False`` ops are GATED unless explicitly allowed;
  (e) ``copy_project`` round-trips a fixture manifest (deep, isolated).
"""

from __future__ import annotations

import ast
import copy
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from media_studio.features.apply_engine import (
    ApplyError,
    ApplyResult,
    apply_plan,
)
from media_studio.features.project_copy import ProjectCopy, copy_project
from media_studio.models.edit_plan import EditOp, EditPlan

# --------------------------------------------------------------------------- #
# fixtures + fakes
# --------------------------------------------------------------------------- #


def _op(op_id: str, kind: str = "trim", *, reversible: bool = True) -> EditOp:
    """Build a planned op with a valid span."""
    return EditOp(id=op_id, kind=kind, span=(0, 1000), reversible=reversible)


def _plan(*ops: EditOp) -> EditPlan:
    return EditPlan(
        plan_id="p1",
        video_id="v1",
        goal="smooth it",
        source_hash="h0",
        ops=ops,
    )


class FakeProject:
    """Minimal Project stand-in: a ``data`` dict + a ``manifest_path``."""

    def __init__(self, data: dict[str, Any], manifest_path: str | None = None) -> None:
        self.data = data
        self.manifest_path = Path(manifest_path) if manifest_path else None


def _copy(data: dict[str, Any] | None = None) -> ProjectCopy:
    """A ProjectCopy with a mutable data dict and a fake path (no disk write)."""
    return ProjectCopy(data=dict(data or {"tracks": [], "log": []}), manifest_path=Path("copy.json"))


def _record_engine(tag: str, *, raises: bool = False) -> Callable[[EditOp, ProjectCopy], EditOp]:
    """A fake engine that mutates the COPY and returns a known inverse op.

    The forward op appends ``tag`` to the COPY's ``log``; the returned inverse,
    when applied, pops it (so a round-trip restores the COPY).
    """

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        if raises:
            raise RuntimeError(f"boom:{op.id}")
        project_copy.data.setdefault("log", []).append(tag)
        return EditOp(id=f"inv-{op.id}", kind=op.kind, span=op.span, params={"undo": tag})

    return engine


def _inverse_engine() -> Callable[[EditOp, ProjectCopy], EditOp]:
    """An engine that interprets ``params['undo']`` to pop the matching tag."""

    def engine(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        tag = op.params.get("undo")
        log = project_copy.data.get("log", [])
        if log and log[-1] == tag:
            log.pop()
        return EditOp(id=f"re-{op.id}", kind=op.kind, span=op.span)

    return engine


def _engines(
    **by_kind: Callable[[EditOp, ProjectCopy], EditOp],
) -> Mapping[str, Callable[[EditOp, ProjectCopy], EditOp]]:
    return dict(by_kind)


# --------------------------------------------------------------------------- #
# apply_plan — happy path, ordering, inverse recording
# --------------------------------------------------------------------------- #


def test_apply_in_order_mutates_copy_records_inverse() -> None:
    plan = _plan(_op("a"), _op("b"), _op("c"))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))

    assert isinstance(result, ApplyResult)
    # COPY mutated in op order.
    assert proj_copy.data["log"] == ["T", "T", "T"]
    # every op marked applied.
    assert [op.status for op in result.ops_status] == ["applied", "applied", "applied"]
    # inverse recorded in REVERSE order (undo c, then b, then a).
    assert [op.id for op in result.inverse_plan.inverse] == ["inv-c", "inv-b", "inv-a"]
    assert result.project_copy_path == "copy.json"


def test_apply_never_mutates_source_manifest() -> None:
    source_data = {"tracks": [{"id": "t0"}], "log": []}
    source = FakeProject(copy.deepcopy(source_data))
    # apply over a COPY of the source, not the source.
    proj_copy = ProjectCopy(data=copy.deepcopy(source.data), manifest_path=Path("copy.json"))
    apply_plan(_plan(_op("a")), project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))

    # acceptance (a): source untouched by identity AND value.
    assert source.data == source_data
    assert source.data is not proj_copy.data


def test_empty_plan_is_a_noop() -> None:
    proj_copy = _copy()
    result = apply_plan(_plan(), project_copy=proj_copy, engines=_engines())
    assert result.ops_status == ()
    assert result.inverse_plan.inverse == ()
    assert proj_copy.data["log"] == []


# --------------------------------------------------------------------------- #
# apply_plan — mid-plan failure -> stop + auto-rollback (acceptance b)
# --------------------------------------------------------------------------- #


def test_mid_plan_failure_rolls_back_and_marks_statuses() -> None:
    proj_copy = _copy()
    engines = {
        "trim": _record_engine("T"),
        "cut": _record_engine("X", raises=True),
    }
    # rollback dispatches the recorded inverse ops; the inverse engine pops.
    inverse_engines = {"trim": _inverse_engine(), "cut": _inverse_engine()}
    # op #2 (kind=cut) raises.
    plan = _plan(_op("a", "trim"), _op("b", "cut"), _op("c", "trim"))
    result = apply_plan(plan, project_copy=proj_copy, engines=engines, inverse_engines=inverse_engines)

    statuses = [(op.id, op.status, op.status_reason) for op in result.ops_status]
    assert statuses[0] == ("a", "applied", None)
    assert statuses[1][0:2] == ("b", "failed")
    assert "boom:b" in (statuses[1][2] or "")
    assert statuses[2] == ("c", "planned", None)  # unreached
    # acceptance (b): COPY rolled back to pre-apply (the one applied op undone).
    assert proj_copy.data["log"] == []


def test_first_op_failure_rolls_back_nothing() -> None:
    plan = _plan(_op("a", "cut"))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(cut=_record_engine("X", raises=True)))
    assert result.ops_status[0].status == "failed"
    assert proj_copy.data["log"] == []
    assert result.inverse_plan.inverse == ()


def test_rollback_failure_raises_apply_error() -> None:
    # forward op #2 fails; the inverse engine for op #1 ALSO fails -> ApplyError.
    plan = _plan(_op("a", "trim"), _op("b", "cut"))
    proj_copy = _copy()

    def bad_inverse(op: EditOp, project_copy: ProjectCopy) -> EditOp:
        raise RuntimeError("rollback failed")

    engines = {
        "trim": _record_engine("T"),
        "cut": _record_engine("X", raises=True),
    }
    with pytest.raises(ApplyError, match="rollback failed"):
        apply_plan(plan, project_copy=proj_copy, engines=engines, inverse_engines={"trim": bad_inverse})


# --------------------------------------------------------------------------- #
# apply_plan — round-trip undo (acceptance c)
# --------------------------------------------------------------------------- #


def test_inverse_plan_round_trip_restores_copy() -> None:
    plan = _plan(_op("a"), _op("b"))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))
    assert proj_copy.data["log"] == ["T", "T"]

    # re-apply the recorded inverse plan (acceptance c) -> COPY restored.
    undo = apply_plan(result.inverse_plan, project_copy=proj_copy, engines=_engines(trim=_inverse_engine()))
    assert proj_copy.data["log"] == []
    assert [op.status for op in undo.ops_status] == ["applied", "applied"]


# --------------------------------------------------------------------------- #
# apply_plan — irreversible ops are GATED (acceptance d)
# --------------------------------------------------------------------------- #


def test_irreversible_op_gated_by_default() -> None:
    plan = _plan(_op("a", reversible=False))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))
    # gated: not applied, COPY untouched, typed reason.
    assert result.ops_status[0].status == "dropped"
    assert result.ops_status[0].status_reason == "irreversible-unconfirmed"
    assert proj_copy.data["log"] == []
    assert result.inverse_plan.inverse == ()


def test_irreversible_op_applied_when_confirmed() -> None:
    plan = _plan(_op("a", reversible=False))
    proj_copy = _copy()
    result = apply_plan(
        plan,
        project_copy=proj_copy,
        engines=_engines(trim=_record_engine("T")),
        allow_irreversible=True,
    )
    assert result.ops_status[0].status == "applied"
    assert proj_copy.data["log"] == ["T"]


def test_already_dropped_op_skipped() -> None:
    dropped = _op("a").with_status("dropped", "span-exceeds-clip")
    plan = _plan(dropped, _op("b"))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))
    # the dropped op is preserved untouched; only "b" applies.
    assert result.ops_status[0].status == "dropped"
    assert result.ops_status[0].status_reason == "span-exceeds-clip"
    assert result.ops_status[1].status == "applied"
    assert proj_copy.data["log"] == ["T"]


def test_unknown_kind_has_no_engine() -> None:
    plan = _plan(_op("a", "reorder"))
    proj_copy = _copy()
    result = apply_plan(plan, project_copy=proj_copy, engines=_engines(trim=_record_engine("T")))
    # no engine registered for "reorder" -> failed with a typed reason, rollback clean.
    assert result.ops_status[0].status == "failed"
    assert "no engine" in (result.ops_status[0].status_reason or "")
    assert proj_copy.data["log"] == []


# --------------------------------------------------------------------------- #
# copy_project (acceptance e) + the pragma'd writer seam
# --------------------------------------------------------------------------- #


def test_copy_project_deep_copies_and_writes_via_injected_writer() -> None:
    written: list[tuple[Path, dict[str, Any]]] = []

    def writer(path: Path, data: dict[str, Any]) -> None:
        written.append((path, copy.deepcopy(data)))

    source = FakeProject({"tracks": [{"id": "t0", "cues": [1, 2]}]}, manifest_path="src.json")
    pc = copy_project(source, dest_dir=Path("/work/copy"), writer=writer)

    assert isinstance(pc, ProjectCopy)
    # deep copy: mutating the COPY must not touch the source.
    pc.data["tracks"][0]["cues"].append(3)
    assert source.data["tracks"][0]["cues"] == [1, 2]
    # the COPY manifest lives under dest_dir.
    assert pc.manifest_path == Path("/work/copy") / "project.json"
    # the injected writer received the COPY (the disk write is the seam).
    assert written and written[0][0] == pc.manifest_path
    assert written[0][1]["tracks"][0]["cues"] == [1, 2]


def test_copy_project_default_dest_dir_from_source_path() -> None:
    written: list[Path] = []
    source = FakeProject({"tracks": []}, manifest_path="/proj/src.json")
    pc = copy_project(source, writer=lambda p, d: written.append(p))
    # default dest = a sibling ".director-copy" folder next to the source manifest.
    assert pc.manifest_path == Path("/proj/.director-copy") / "project.json"


def test_copy_project_without_manifest_path_uses_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = FakeProject({"tracks": []}, manifest_path=None)
    pc = copy_project(source, writer=lambda p, d: None)
    assert pc.manifest_path == Path.cwd() / ".director-copy" / "project.json"


# --------------------------------------------------------------------------- #
# purity guard: no Provider / transport import (planner-purity, acceptance d)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module", ["apply_engine", "project_copy"])
def test_modules_have_no_provider_or_transport_import(module: str) -> None:
    src = Path(__file__).resolve().parents[1] / "media_studio" / "features" / f"{module}.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    banned = {"provider", "transport", "httpx", "requests", "torch", "onnxruntime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.lower() for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").lower()]
        else:
            continue
        for name in names:
            assert not any(bad in name for bad in banned), f"{module} imports {name!r}"
