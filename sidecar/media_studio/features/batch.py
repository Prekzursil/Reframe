"""Repurpose BATCH store + model + per-source runner (WU6 substrate + WU7 runner).

A *batch* points one saved :mod:`templates` template at MANY library sources and
runs them as one aggregate job. WU6 ships the durable state layer (model + store +
checkpoint-on-transition); WU7 adds :func:`run_batch`, the parent batch job body
that drives each source through the WU5 template path with NEW per-source
try/except isolation (G-ISO) over the EXISTING recipe sub-job relay. Because the
job registry is in-memory (``jobs.py`` —
``self._jobs: dict``), the ONLY thing that survives a sidecar/app restart is what
the batch checkpoint persists. WU6 therefore ships exactly that checkpoint:

  * **Model** — a ``BatchState`` =
    ``{id, name, templateId, status, createdAt, items:[BatchItem]}`` and a
    ``BatchItem`` = ``{videoId, status, jobId?, error?, skipReason?, results?}``
    where ``status`` is one of
    ``queued | running | done | error | cancelled | skipped`` (DESIGN §5.2). The
    ``skipped`` terminal state + ``skipReason`` carry the visible-skip contract
    (§9.1) so a source dropped by the later consent gate is recorded and
    attributed, never silently absent.
  * **Storage** — :class:`BatchStore` writes ONE file per batch
    (``batches/<batchId>.json``, DESIGN §8) with the proven atomic temp+rename
    write (mirrors :class:`recipes.RecipeStore`). One file per batch makes a
    checkpoint O(1) and means a corrupt batch can never poison another (a corrupt
    file simply loads as ``None``; siblings stay readable).
  * **Checkpoint-on-transition** — :meth:`BatchStore.update_item` rewrites the
    whole batch file on EVERY item transition and recomputes the aggregate
    ``status`` from the item statuses (:func:`derive_status`), so the on-disk
    state is always consistent before the next item runs — the substrate the WU8
    resume reads back.

WU8 adds :func:`resume_batch` (G-DUR): it reads the checkpoint back, treats
``done`` items as complete, re-enqueues the not-yet-done sources (resetting them
to ``queued`` on disk), and starts a FRESH parent job that re-runs ONLY those
sources at SOURCE granularity — finished work is never redone.

No heavy-ML / network / provider imports. The runner reuses the recipe sub-job
relay by import (no new sub-job machinery); consent and the RPC layer are later
WUs.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any, Protocol, cast

from .. import protocol
from ..jobs import JobCancelled
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import clamp, get_logger, now_ms
from . import recipes

log = get_logger("media_studio.features.batch")

BatchItem = dict[str, Any]
BatchState = dict[str, Any]
BatchSummary = dict[str, Any]


#: A template-run seam: ``(video_id, ctx, *, confirm_budget=?) -> {"jobId": ...}``
#: — runs one source through the WU5 template path and returns the spawned sub-job
#: id. The runner only awaits + isolates; it never builds the per-source job
#: itself. ``confirm_budget`` is threaded ONLY for an acknowledged egressing source
#: (WU9); the plain two-arg call is the WU7 default.
class TemplateRunner(Protocol):
    def __call__(self, video_id: str, ctx: RpcContext, *, confirm_budget: str | None = ...) -> dict[str, Any]:
        """Run one source's template path; returns ``{"jobId": ...}``."""
        ...  # pragma: no cover - Protocol method body is never executed


#: Maps a source ``video_id`` to a human title for the progress message.
TitleResolver = Callable[[str], str]
#: The sub-job await/relay seam (defaults to the recipe runner's ``_await_subjob``).
AwaitSubjob = Callable[[str, Any, RpcContext, Callable[[float, str], None]], Any]
#: The parent-job start seam: ``(job_body, **kwargs) -> <job with .id>`` (defaults
#: to ``ctx.jobs.start``). Injected by tests to run the resume body synchronously.
StartJob = Callable[..., Any]
#: Maps a source ``video_id`` to its distinct AI step *shape* key (sources sharing
#: a template+size collapse to ONE shape, so the planner cost is bounded by shape
#: count, not source count — the dedup contract, WU9 / DESIGN §9.1).
ShapeOf = Callable[[str], Hashable]
#: The pure pre-flight planner seam: ``shape_key -> plan`` (the fake ``ai.planJob``
#: in tests). Called ONCE per distinct shape; returns a plan dict with
#: ``{willEgress, cacheHit, costEst, budget, cacheKey}`` (``handlers.py:1696``).
PlanJob = Callable[[Hashable], dict[str, Any]]

#: visible-skip reason tokens (DESIGN §9.1) — never a silent absence.
SKIP_WOULD_EGRESS = "would egress — not acknowledged"
SKIP_NO_HEADROOM = "no budget headroom"

#: every legal :class:`BatchItem` status (DESIGN §5.2).
ITEM_STATUSES: frozenset[str] = frozenset({"queued", "running", "done", "error", "cancelled", "skipped"})
#: the statuses a :class:`BatchItem` can never leave (no further work).
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "error", "cancelled", "skipped"})
#: the optional :class:`BatchItem` fields persisted only when supplied.
_ITEM_OPTIONAL_FIELDS: tuple[str, ...] = ("jobId", "error", "skipReason", "results")


def _invalid(message: str) -> RpcError:
    return RpcError(message, ErrorCode.INVALID_PARAMS)


# --------------------------------------------------------------------------- #
# pure model — item / state shaping + aggregate-status derivation
# --------------------------------------------------------------------------- #
def is_terminal_status(status: str) -> bool:
    """True iff ``status`` is a terminal :class:`BatchItem` status."""
    return status in TERMINAL_STATUSES


def new_item(video_id: str) -> BatchItem:
    """A fresh ``queued`` :class:`BatchItem` for ``video_id`` (fail-loud on empty)."""
    if not isinstance(video_id, str) or not video_id.strip():
        raise _invalid("batch item videoId (non-empty str) is required")
    return {"videoId": video_id, "status": "queued"}


def new_state(
    name: str,
    template_id: str,
    source_video_ids: list[str],
    *,
    batch_id: str | None = None,
) -> BatchState:
    """Validate + shape a brand-new :class:`BatchState` (all items ``queued``).

    Raises ``INVALID_PARAMS`` on any malformed field so a bad create can never
    persist a half-typed record. A missing ``batch_id`` is generated.
    """
    if not isinstance(name, str) or not name.strip():
        raise _invalid("batch.name (non-empty str) is required")
    if not isinstance(template_id, str) or not template_id.strip():
        raise _invalid("batch.templateId (non-empty str) is required")
    if not isinstance(source_video_ids, list) or not source_video_ids:
        raise _invalid("batch.sourceVideoIds (non-empty array) is required")
    items = [new_item(video_id) for video_id in source_video_ids]
    resolved_id = batch_id if isinstance(batch_id, str) and batch_id else uuid.uuid4().hex[:12]
    return {
        "id": resolved_id,
        "name": name.strip(),
        "templateId": template_id.strip(),
        "status": derive_status([item["status"] for item in items]),
        "createdAt": now_ms(),
        "items": items,
    }


def derive_status(item_statuses: list[str]) -> str:
    """Aggregate batch status from the item statuses (DESIGN §5.2 / §10.3).

    * empty / all-``queued``      -> ``queued`` (nothing has started)
    * any ``running`` OR a mix of started + still-``queued`` -> ``running``
    * all ``done``                -> ``done``
    * all terminal, none ``done``, only ``cancelled``        -> ``cancelled``
    * all terminal, none ``done``, no successes (error/skip)  -> ``error``
    * all terminal with at least one ``done`` AND a non-done   -> ``partial``
    """
    if not item_statuses:
        return "queued"
    if all(status == "queued" for status in item_statuses):
        return "queued"
    if any(status == "running" for status in item_statuses):
        return "running"
    if any(status == "queued" for status in item_statuses):
        # Some items finished but others have not started yet -> still mid-flight.
        return "running"
    # Every item is terminal at this point.
    if all(status == "done" for status in item_statuses):
        return "done"
    if all(status == "cancelled" for status in item_statuses):
        return "cancelled"
    if any(status == "done" for status in item_statuses):
        return "partial"
    return "error"


# --------------------------------------------------------------------------- #
# storage — one file per batch (atomic temp+rename), per-batch isolation
# --------------------------------------------------------------------------- #
class BatchStore:
    """One JSON file per batch under ``dir`` (atomic temp+rename writes).

    A per-batch file keeps each checkpoint O(1) and isolates corruption: a bad
    file loads as ``None`` and its siblings stay readable. The write mirrors
    :class:`recipes.RecipeStore` (temp file + ``os.replace``) so a failed write
    never truncates the prior checkpoint.
    """

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.dir = Path(directory)

    def _path(self, batch_id: str) -> Path:
        return self.dir / f"{batch_id}.json"

    def _write(self, state: BatchState) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(state["id"])
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, batch_id: str) -> BatchState | None:
        """Read one batch by id (``None`` if absent / unreadable / wrong shape)."""
        path = self._path(batch_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("batch %s unreadable (%s); treating as missing", batch_id, exc)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def create(self, name: str, template_id: str, source_video_ids: list[str]) -> BatchState:
        """Shape + persist a new all-``queued`` batch; returns the stored state."""
        state = new_state(name, template_id, source_video_ids)
        self._write(state)
        return state

    def update_item(
        self,
        batch_id: str,
        video_id: str,
        *,
        status: str,
        **fields: Any,
    ) -> BatchState:
        """Checkpoint one item transition (rewrites the whole batch file).

        Sets the item's ``status`` (validated against :data:`ITEM_STATUSES`),
        merges any supplied optional fields (``jobId``/``error``/``skipReason``/
        ``results``), recomputes the aggregate ``status``, and atomically rewrites
        the file BEFORE returning — the durability guarantee for resume (WU8).
        """
        if status not in ITEM_STATUSES:
            raise _invalid(f"invalid batch item status: {status!r}")
        state = self.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        target: BatchItem | None = None
        for item in state["items"]:
            if item.get("videoId") == video_id:
                target = item
                break
        if target is None:
            raise _invalid(f"unknown batch item: {video_id}")
        target["status"] = status
        for key in _ITEM_OPTIONAL_FIELDS:
            if key in fields:
                target[key] = fields[key]
        state["status"] = derive_status([item["status"] for item in state["items"]])
        self._write(state)
        return state

    def set_status(self, batch_id: str, status: str) -> BatchState:
        """Override the aggregate batch ``status`` (atomic rewrite).

        The runner uses this when it deliberately STOPS early (``continue_on_error``
        off): the items left ``queued`` would otherwise make :func:`derive_status`
        report ``running`` for a batch that has actually halted, so the runner
        records the terminal ``error`` aggregate explicitly (DESIGN §10.3).
        """
        state = self.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        state["status"] = status
        self._write(state)
        return state

    def delete(self, batch_id: str) -> bool:
        """Drop a batch file; ``True`` if one existed, ``False`` otherwise."""
        path = self._path(batch_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list(self) -> list[BatchSummary]:
        """Lightweight summaries of every readable batch (heavy ``results`` omitted)."""
        if not self.dir.exists():
            return []
        summaries: list[BatchSummary] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                log.warning("batch summary skipped (unreadable): %s", path.name)
                continue
            if not isinstance(data, dict):
                continue
            summaries.append(_summarize(data))
        return summaries


# --------------------------------------------------------------------------- #
# runner — per-source isolation over the WU5 template path (WU7, G-ISO)
# --------------------------------------------------------------------------- #
def _default_await_subjob(
    sub_job_id: str,
    job_ctx: Any,
    ctx: RpcContext,
    on_sub: Callable[[float, str], None],
) -> Any:
    """Await one per-source sub-job via the recipe runner's proven relay.

    ``recipes.Recipes._await_subjob`` references no instance state, so it is
    reused verbatim (no new sub-job-await machinery) by calling it with a ``None``
    ``self`` — the batch runner gains the SAME progress-relay, cancel-propagation,
    error-reraise and timeout behavior the recipe runner already ships and tests.
    """
    # _await_subjob touches no instance state; the cast documents the intentional
    # ``self``-free reuse so basedpyright accepts the stateless call.
    return recipes.Recipes._await_subjob(cast("recipes.Recipes", None), sub_job_id, job_ctx, ctx, on_sub)


def _run_source(
    template_runner: TemplateRunner,
    video_id: str,
    ctx: RpcContext,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Invoke ``template_runner`` for one source, threading any ``confirmBudget``.

    When the WU9 consent supplied a ``confirmBudget`` token (the plan's
    ``cacheKey`` for an acknowledged egressing source), it is passed as the
    ``confirm_budget`` keyword so the underlying AI step satisfies
    ``_enforce_cloud_budget_ack`` (``handlers.py:1672``). With no token (local /
    cache-hit / gate-off / no consent), the runner is called with its plain
    ``(video_id, ctx)`` signature — the WU7 path, unchanged.
    """
    confirm_budget = (decision or {}).get("confirmBudget")
    if confirm_budget:
        return template_runner(video_id, ctx, confirm_budget=confirm_budget)
    return template_runner(video_id, ctx)


def run_batch(
    store: BatchStore,
    batch_id: str,
    template_runner: TemplateRunner,
    job_ctx: Any,
    ctx: RpcContext,
    *,
    continue_on_error: bool = True,
    title_resolver: TitleResolver | None = None,
    await_subjob: AwaitSubjob | None = None,
    consent: dict[str, Any] | None = None,
) -> BatchState:
    """Run a batch's sources through ``template_runner`` with per-source isolation.

    The parent batch job body: iterate the batch's items, run each source through
    the WU5 template path (``template_runner`` → ``{jobId}``), and await that
    sub-job via the EXISTING recipe relay (:func:`_default_await_subjob`). Each
    source's ``[0,100]`` sub-progress is spread into its even slice of the overall
    ``[0,100]`` bar (mirroring ``convert_batch``), and the relayed step message is
    prefixed with ``"source k/N · <title> · "`` (extends the recipe runner's
    ``"step j/M · <label>"``, DESIGN §7).

    The deliberate divergence from ``convert_batch``/``_run_one_step`` (G-ISO):
    each source runs inside a NEW try/except, so one bad source records ``error``
    on its :class:`BatchItem` and the batch CONTINUES when ``continue_on_error``
    (default ``true``); with the toggle off the batch stops at the first error and
    leaves the remaining items ``queued``. A :class:`~media_studio.jobs.JobCancelled`
    is NOT isolated: an in-flight source is recorded ``cancelled`` and the cancel
    re-raised so the parent job unwinds (no new cancel machinery — the relay's
    ``raise_if_cancelled`` path is reused).
    """
    state = store.load(batch_id)
    if state is None:
        raise _invalid(f"unknown batch: {batch_id}")
    resolve_title = title_resolver or (lambda video_id: video_id)
    await_sub = await_subjob or _default_await_subjob
    decisions: dict[str, dict[str, Any]] = {
        decision["videoId"]: decision for decision in (consent or {}).get("decisions", [])
    }

    items: list[BatchItem] = state["items"]
    total = max(len(items), 1)
    final = state  # the latest store-returned state (always non-None for the return).
    for index, item in enumerate(items):
        # A source already in a terminal state (e.g. a ``done`` item preserved by a
        # WU8 resume) is NOT re-run — resume re-enqueues only the incomplete sources
        # by resetting them to ``queued``; finished work stays finished (G-DUR).
        if is_terminal_status(item["status"]):
            continue
        job_ctx.raise_if_cancelled()
        video_id = item["videoId"]
        decision = decisions.get(video_id)
        # WU9 visible skip: a source the consent gate marked ``skip`` is recorded
        # terminal ``skipped`` with its reason BEFORE any work — never run, never a
        # silent absence (§9.1). Its progress slice is still consumed below.
        if decision is not None and decision["action"] == "skip":
            final = store.update_item(batch_id, video_id, status="skipped", skipReason=decision["skipReason"])
            continue
        title = resolve_title(video_id)
        base = index / total * 100.0
        span = 100.0 / total
        prefix = f"source {index + 1}/{total} · {title} · "

        def on_sub(pct: float, message: str, _base: float = base, _span: float = span, _prefix: str = prefix) -> None:
            job_ctx.progress(_base + clamp(pct, 0.0, 100.0) / 100.0 * _span, f"{_prefix}{message}")

        final = store.update_item(batch_id, video_id, status="running")
        on_sub(0.0, "")
        try:
            started = _run_source(template_runner, video_id, ctx, decision)
            result = await_sub(started["jobId"], job_ctx, ctx, on_sub)
        except JobCancelled:
            store.update_item(batch_id, video_id, status="cancelled")
            raise
        except Exception as exc:  # noqa: BLE001 - per-source isolation is the point (G-ISO)
            final = store.update_item(batch_id, video_id, status="error", error=str(exc))
            if not continue_on_error:
                # Halted early: the still-``queued`` tail would read as ``running``,
                # so record the terminal ``error`` aggregate explicitly (§10.3).
                final = store.set_status(batch_id, "error")
                break
            continue
        final = store.update_item(batch_id, video_id, status="done", jobId=started["jobId"], results=result)

    job_ctx.progress(100.0, "done")
    return final


# --------------------------------------------------------------------------- #
# resume — re-enqueue not-yet-done sources as a FRESH job (WU8, G-DUR)
# --------------------------------------------------------------------------- #
#: the statuses a resume re-enqueues unconditionally (work that never finished).
_RESUMABLE_STATUSES: frozenset[str] = frozenset({"queued", "running"})


def resumable_video_ids(state: BatchState, *, retry_errors: bool = False) -> list[str]:
    """Video ids of the sources a resume should re-run, in batch order (§10.1).

    Pure selector over the checkpointed :class:`BatchState`. ``queued`` and
    ``running`` items are always re-enqueued (a ``running`` item is a source the
    crash interrupted mid-flight). ``error`` items are re-enqueued ONLY when
    ``retry_errors`` (default policy leaves an errored source terminal). ``done``
    /``skipped``/``cancelled`` are terminal and never resumed — finished work is
    not redone (the G-DUR durability contract).
    """
    selected: list[str] = []
    for item in state.get("items") or []:
        status = item.get("status")
        if status in _RESUMABLE_STATUSES or (retry_errors and status == "error"):
            selected.append(item["videoId"])
    return selected


def resume_batch(
    store: BatchStore,
    batch_id: str,
    template_runner: TemplateRunner,
    ctx: RpcContext,
    *,
    retry_errors: bool = False,
    continue_on_error: bool = True,
    title_resolver: TitleResolver | None = None,
    await_subjob: AwaitSubjob | None = None,
    start_job: StartJob | None = None,
) -> dict[str, Any]:
    """Resume an incomplete batch as a FRESH parent job (DESIGN §10.1, G-DUR).

    Reads the checkpointed :class:`BatchState`, treats ``done`` items as complete,
    and re-enqueues the not-yet-done sources (:func:`resumable_video_ids`) by
    resetting them to ``queued`` ON DISK before any work starts — the durable
    re-enqueue, not an in-memory one. It then starts a fresh parent job whose body
    runs :func:`run_batch`; because the preserved ``done`` items are terminal,
    ``run_batch`` skips them and runs ONLY the re-enqueued sources. Resume is at
    SOURCE granularity: a re-enqueued source runs its full template path from step
    one (its earlier outputs are idempotent overwrites) — mid-pipeline resume is
    out of scope (§10.1).

    Returns ``{"jobId": <id>}``. When nothing is resumable (every source already
    terminal) it is a NO-OP: no job starts and it returns
    ``{"jobId": None, "status": <terminal aggregate>}``.
    """
    state = store.load(batch_id)
    if state is None:
        raise _invalid(f"unknown batch: {batch_id}")
    pending = resumable_video_ids(state, retry_errors=retry_errors)
    if not pending:
        return {"jobId": None, "status": state.get("status")}
    # Durable re-enqueue: reset each not-yet-done source to ``queued`` on disk so a
    # second crash before the job runs still sees them as pending.
    for video_id in pending:
        state = store.update_item(batch_id, video_id, status="queued")
    starter = start_job or ctx.jobs.start

    def job_body(job_ctx: Any) -> BatchState:
        return run_batch(
            store,
            batch_id,
            template_runner,
            job_ctx,
            ctx,
            continue_on_error=continue_on_error,
            title_resolver=title_resolver,
            await_subjob=await_subjob,
        )

    job = starter(job_body, feature="batch", label=f"resume: {state.get('name', '')}")
    return {"jobId": job.id}


# --------------------------------------------------------------------------- #
# consent — pre-run batch-wide G-ACK surface + visible skip (WU9, DESIGN §9.1)
# --------------------------------------------------------------------------- #
def _has_headroom(plan: dict[str, Any]) -> bool:
    """``True`` iff the plan's budget stays within the free-limit ceiling.

    The pre-flight plan carries a ``budget`` (``handlers.py:1696``) whose
    ``withinFreeLimits`` flag is ``False`` once the run exceeds any involved
    provider's free cap (``budget.py``). A missing flag is treated as headroom
    present (the planner only sets it ``False`` when it KNOWS the cap is busted).
    """
    budget = plan.get("budget") or plan.get("costEst") or {}
    return bool(budget.get("withinFreeLimits", True))


def consent_decision(
    plan: dict[str, Any],
    *,
    confirm_cloud_budget: bool,
    acknowledged: bool,
) -> tuple[str, str | None, str | None]:
    """Decide ONE source's pre-run fate from its pure plan (DESIGN §9.1).

    Returns ``(action, skip_reason, confirm_budget)`` where ``action`` is
    ``"run"`` or ``"skip"``. A local-only or cache-hit plan never egresses, so it
    always runs (``confirm_budget`` ``None``) regardless of the gate. An egressing
    plan runs informationally when ``confirm_cloud_budget`` is OFF. With the gate
    ON: an un-acknowledged egress is ``skip`` (``SKIP_WOULD_EGRESS``); an
    acknowledged egress with NO budget headroom is ``skip`` (``SKIP_NO_HEADROOM``);
    an acknowledged egress with headroom RUNS and threads the plan's ``cacheKey``
    as ``confirm_budget`` (satisfying ``_enforce_cloud_budget_ack``,
    ``handlers.py:1672``, without changing the envelope).
    """
    if not plan.get("willEgress"):
        return ("run", None, None)
    if not confirm_cloud_budget:
        return ("run", None, None)
    if not acknowledged:
        return ("skip", SKIP_WOULD_EGRESS, None)
    if not _has_headroom(plan):
        return ("skip", SKIP_NO_HEADROOM, None)
    return ("run", None, str(plan.get("cacheKey") or ""))


def _sum_egress_cost(egressing_plans: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate ``requests``/``egressBytes`` over the supplied EGRESSING plans.

    The caller (:func:`plan_consent`) passes ONLY the plans whose ``willEgress``
    is true, so local-only and cache-hit sources contribute nothing and the cost
    shown reflects exactly the bytes that would leave the machine (acceptance #4).
    ``withinFreeLimits`` is the AND across those plans — the aggregate has headroom
    only if EVERY egressing source does.
    """
    requests = 0
    egress_bytes = 0
    within = True
    for plan in egressing_plans:
        cost = plan.get("costEst") or {}
        requests += int(cost.get("requests", 0))
        egress_bytes += int(cost.get("egressBytes", 0))
        within = within and _has_headroom(plan)
    return {"requests": requests, "egressBytes": egress_bytes, "withinFreeLimits": within}


def plan_consent(
    source_video_ids: list[str],
    *,
    shape_of: ShapeOf,
    plan_job: PlanJob,
    confirm_cloud_budget: bool,
    acknowledged: bool,
) -> dict[str, Any]:
    """Build the pre-run batch consent surface from pure plans (DESIGN §9.1).

    Computed BEFORE ``batch.start`` from ``ai.planJob`` plans ONLY (zero provider
    calls). One plan is fetched per distinct step *shape* — sources sharing a
    template+size collapse to one plan, so ``plan_job`` is invoked once per shape,
    NOT once per source (acceptance #1). For each source it records the
    :func:`consent_decision` (``action``/``skipReason``/``confirmBudget``) plus the
    surfaced ``willEgress``/``cacheHit`` flags, the N-run/K-skip split, the
    aggregated ``costEst`` over the egressing sources, and the ``budget`` headroom.

    The returned dict is the consent surface the runner consumes (``decisions`` is
    keyed-by-order to mirror the batch items) and the renderer renders as the §9.1
    summary card.
    """
    plans_by_shape: dict[Hashable, dict[str, Any]] = {}
    decisions: list[dict[str, Any]] = []
    egressing_plans: list[dict[str, Any]] = []
    will_run = 0
    will_skip = 0
    for video_id in source_video_ids:
        shape_key = shape_of(video_id)
        plan = plans_by_shape.get(shape_key)
        if plan is None:
            plan = plan_job(shape_key)
            plans_by_shape[shape_key] = plan
        action, skip_reason, confirm_budget = consent_decision(
            plan,
            confirm_cloud_budget=confirm_cloud_budget,
            acknowledged=acknowledged,
        )
        if action == "run":
            will_run += 1
        else:
            will_skip += 1
        if plan.get("willEgress"):
            egressing_plans.append(plan)
        decisions.append(
            {
                "videoId": video_id,
                "action": action,
                "skipReason": skip_reason,
                "confirmBudget": confirm_budget,
                "willEgress": bool(plan.get("willEgress")),
                "cacheHit": bool(plan.get("cacheHit")),
            }
        )
    cost = _sum_egress_cost(egressing_plans)
    return {
        "decisions": decisions,
        "willRun": will_run,
        "willSkip": will_skip,
        "costEst": cost,
        "budget": cost,
    }


def _summarize(state: BatchState) -> BatchSummary:
    """Project a :class:`BatchState` to a :class:`BatchSummary` (no per-item heavy data)."""
    items = state.get("items") or []
    counts = dict.fromkeys(("done", "error", "skipped", "queued", "running", "cancelled"), 0)
    for item in items:
        item_status = item.get("status")
        if item_status in counts:
            counts[item_status] += 1
    return {
        "id": state.get("id"),
        "name": state.get("name"),
        "templateId": state.get("templateId"),
        "status": state.get("status"),
        "createdAt": state.get("createdAt"),
        "counts": {"total": len(items), **counts},
    }


# --------------------------------------------------------------------------- #
# RPC service — the seven ``batch.*`` methods over the WU6-9 substrate (WU10)
# --------------------------------------------------------------------------- #
def _require_id(params: dict[str, Any]) -> str:
    """Read + validate the ``id`` param shared by every id-taking ``batch.*`` method."""
    batch_id = params.get("id")
    if not isinstance(batch_id, str) or not batch_id:
        raise _invalid("id (str) is required")
    return batch_id


def _merge_live_status(state: BatchState, job: Any) -> BatchState:
    """Overlay a live parent job's ``pct`` onto a copy of the stored ``state``.

    ``batch.status`` reads the durable checkpoint (per-item statuses, the source
    of truth incl. ``skipped``) and, while the parent job is still in flight,
    surfaces its live ``pct`` so the UI bar advances between item checkpoints. The
    aggregate ``status`` stays the store's derived value (the checkpoint is
    authoritative for the run/skip split); only the volatile ``pct`` is added. A
    finished/absent job adds nothing — the checkpoint already reflects the outcome.
    """
    if job is None or job.finished:
        return state
    merged = dict(state)
    merged["pct"] = job.pct
    return merged


class Batch:
    """Owns the seven ``batch.*`` methods over the WU6-9 substrate (DESIGN §6).

    ``create``/``list``/``delete`` are direct-return CRUD over the
    :class:`BatchStore`. ``start`` computes the WU9 consent surface (one
    ``ai.planJob`` per distinct step shape, ZERO provider calls) and then starts
    the WU7 :func:`run_batch` parent job, threading each acknowledged source's
    ``confirmBudget`` and skipping un-acked/over-budget egress sources. ``resume``
    re-enqueues the not-yet-done sources as a FRESH job (WU8). ``status`` reads the
    durable checkpoint and overlays the live parent job's ``pct``. ``cancel`` sets
    the parent job's cooperative flag (``jobs.py`` ``cancel`` → the runner's
    ``raise_if_cancelled`` between sources) — NO new cancellation machinery.

    The single per-source seam is :attr:`_template_runner`: it runs ONE source
    through the WU5 template path. The default invokes the live ``templates.apply``
    handler (so a batch rides the SAME recipe runner / sub-job relay a single
    ``templates.apply`` does), binding ``templateId`` from the batch state. No
    provider/key is ever touched here — the AI envelope is reached only by method
    name through that handler.

    Seams (all injectable so tests run with fakes and no media / no real planner):

      * ``template_runner`` — the ``(videoId, ctx, *, confirm_budget=?) -> {jobId}``
        per-source seam (defaults to a ``templates.apply`` call by name).
      * ``shape_of`` / ``plan_job`` — the consent pre-flight seams (default
        ``shape_of`` collapses every source to the batch's ``templateId`` shape;
        default ``plan_job`` calls ``ai.planJob`` by name with that shape's id).
      * ``title_resolver`` — maps a ``videoId`` to a human title for the progress
        message (defaults to the id).
    """

    def __init__(
        self,
        store: BatchStore,
        *,
        methods_provider: Callable[[], dict[str, Any]] | None = None,
        template_runner: TemplateRunner | None = None,
        shape_of: ShapeOf | None = None,
        plan_job: PlanJob | None = None,
        title_resolver: TitleResolver | None = None,
    ) -> None:
        self.store = store
        self._methods_provider = methods_provider or (lambda: protocol.METHODS)
        self._template_runner = template_runner
        self._shape_of = shape_of
        self._plan_job = plan_job
        self._title_resolver = title_resolver
        # parentJobId per running batch -> the cancel/status-merge target. In-memory
        # only (the JobRegistry is in-memory; a restart loses it, which is exactly
        # why resume is a CHECKPOINT read, not a live-job read — §10.1).
        self._parent_jobs: dict[str, str] = {}

    # -- direct-return CRUD -------------------------------------------------
    def create(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.create({name, templateId, sourceVideoIds})`` -> ``{batch}``.

        Validates + persists an all-``queued`` :class:`BatchState` (durable). The
        fields are validated by :func:`new_state`, so a malformed create never
        persists a half-typed record.
        """
        source_ids = params.get("sourceVideoIds")
        return {
            "batch": self.store.create(
                params.get("name"),  # type: ignore[arg-type] - new_state validates
                params.get("templateId"),  # type: ignore[arg-type]
                source_ids,  # type: ignore[arg-type]
            )
        }

    def list(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.list()`` -> ``{batches:[BatchSummary]}`` (incl. finished)."""
        return {"batches": self.store.list()}

    def delete(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.delete({id})`` -> ``{ok}`` (drops a finished/cancelled record)."""
        batch_id = _require_id(params)
        ok = self.store.delete(batch_id)
        self._parent_jobs.pop(batch_id, None)
        return {"ok": ok}

    # -- status (store checkpoint + live job overlay) -----------------------
    def status(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.status({id})`` -> ``{batch}`` (checkpoint + live ``pct`` overlay).

        Reads the durable :class:`BatchState` (the authoritative per-item statuses,
        incl. ``skipped`` with ``skipReason``) and, while the parent job is live,
        overlays its ``pct`` so the aggregate bar advances between item checkpoints.
        """
        batch_id = _require_id(params)
        state = self.store.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        job = self._live_parent_job(batch_id, ctx)
        return {"batch": _merge_live_status(state, job)}

    # -- start (WU9 consent -> WU7 runner) ----------------------------------
    def start(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.start({id, confirmCloudBudget?, acknowledged?})`` -> ``{jobId}``.

        Loads the batch, computes the WU9 consent surface for its still-pending
        sources (one ``ai.planJob`` per distinct step shape; ZERO provider calls),
        then starts the WU7 :func:`run_batch` parent job carrying that consent —
        acknowledged egress sources thread their ``confirmBudget``; un-acked /
        over-budget egress sources end terminal ``skipped`` with their reason
        (never silently absent, §9.1). The parent jobId is held for ``cancel`` /
        ``status``.
        """
        batch_id = _require_id(params)
        state = self.store.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        template_id = str(state.get("templateId") or "")
        runner = self._runner_for(template_id)
        pending = [item["videoId"] for item in state["items"] if not is_terminal_status(item["status"])]
        consent = self._build_consent(
            pending,
            template_id,
            confirm_cloud_budget=bool(params.get("confirmCloudBudget", False)),
            acknowledged=bool(params.get("acknowledged", False)),
        )
        continue_on_error = bool(params.get("continueOnError", True))
        title_resolver = self._title_resolver

        def job_body(job_ctx: Any) -> BatchState:
            return run_batch(
                self.store,
                batch_id,
                runner,
                job_ctx,
                ctx,
                continue_on_error=continue_on_error,
                title_resolver=title_resolver,
                consent=consent,
            )

        job = ctx.jobs.start(job_body, feature="batch", label=f"batch: {state.get('name', '')}")
        self._parent_jobs[batch_id] = job.id
        return {"jobId": job.id}

    # -- plan (WU9 dry-run consent surface; starts NO job) ------------------
    def plan(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.plan({id, confirmCloudBudget?, acknowledged?})`` -> ``{consent}``.

        The pure pre-run consent surface (DESIGN §9.1) for a batch's still-pending
        sources WITHOUT starting a job — one ``ai.planJob`` per distinct step shape,
        ZERO provider calls. Unlike :meth:`start` (whose gate-OFF pass-through
        collapses to ``None``), this ALWAYS returns a fully-populated
        ``decisions``/``willRun``/``willSkip`` surface by calling
        :func:`plan_consent` directly, so the renderer can render the §9.1 card
        before deciding whether to start.
        """
        batch_id = _require_id(params)
        state = self.store.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        template_id = str(state.get("templateId") or "")
        pending = [item["videoId"] for item in state["items"] if not is_terminal_status(item["status"])]
        shape_of = self._shape_of or (lambda _video_id: template_id)
        plan_job = self._plan_job or self._default_plan_job
        consent = plan_consent(
            pending,
            shape_of=shape_of,
            plan_job=plan_job,
            confirm_cloud_budget=bool(params.get("confirmCloudBudget", False)),
            acknowledged=bool(params.get("acknowledged", False)),
        )
        return {"consent": consent}

    # -- resume (WU8 fresh job over the not-yet-done sources) ---------------
    def resume(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.resume({id, retryErrors?})`` -> ``{jobId}`` (re-enqueue pending).

        Re-runs ONLY the not-yet-done sources of an incomplete batch as a fresh
        parent job (:func:`resume_batch`); finished work is never redone (G-DUR).
        A fully-terminal batch is a no-op (``{jobId: None, status}``).
        """
        batch_id = _require_id(params)
        state = self.store.load(batch_id)
        if state is None:
            raise _invalid(f"unknown batch: {batch_id}")
        if ctx.jobs is None:
            raise RpcError("no job registry available", ErrorCode.INTERNAL_ERROR)
        template_id = str(state.get("templateId") or "")
        out = resume_batch(
            self.store,
            batch_id,
            self._runner_for(template_id),
            ctx,
            retry_errors=bool(params.get("retryErrors", False)),
            title_resolver=self._title_resolver,
        )
        job_id = out.get("jobId")
        if job_id is not None:
            self._parent_jobs[batch_id] = job_id
        return out

    # -- cancel (cooperative parent-job flag; jobs.py:447) ------------------
    def cancel(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``batch.cancel({id})`` -> ``{ok}`` (cooperative; ``jobs.py`` cancel).

        Sets the parent job's cancel flag; the runner observes it via
        ``raise_if_cancelled`` between sources and unwinds (the in-flight source is
        recorded ``cancelled``). No new cancellation machinery. ``ok`` is ``False``
        when no live parent job is tracked (nothing to cancel).
        """
        batch_id = _require_id(params)
        parent_job_id = self._parent_jobs.get(batch_id)
        if parent_job_id is None or ctx.jobs is None:
            return {"ok": False}
        return {"ok": bool(ctx.jobs.cancel(parent_job_id))}

    # -- seams --------------------------------------------------------------
    def _live_parent_job(self, batch_id: str, ctx: RpcContext) -> Any:
        """The tracked parent :class:`~media_studio.jobs.Job` (or ``None``)."""
        parent_job_id = self._parent_jobs.get(batch_id)
        if parent_job_id is None or ctx.jobs is None:
            return None
        return ctx.jobs.get(parent_job_id)

    def _runner_for(self, template_id: str) -> TemplateRunner:
        """The per-source template seam for ``template_id`` (injected or default).

        The default invokes the live ``templates.apply`` handler by name — the
        batch rides the EXISTING single-source path; it builds no sub-job itself
        and reaches the AI envelope only through that handler. The seam receives
        its own per-source ``ctx`` at call time (so the same registry/jobs flow).
        """
        if self._template_runner is not None:
            return self._template_runner

        def runner(video_id: str, ctx: RpcContext, *, confirm_budget: str | None = None) -> dict[str, Any]:
            apply_handler = self._methods_provider().get("templates.apply")
            if apply_handler is None:  # pragma: no cover - register order guarantees it
                raise RpcError("templates.apply is not registered", ErrorCode.INTERNAL_ERROR)
            apply_params: dict[str, Any] = {"templateId": template_id, "videoId": video_id}
            if confirm_budget:
                apply_params["confirmBudget"] = confirm_budget
            return apply_handler(apply_params, ctx)

        return runner

    def _build_consent(
        self,
        source_video_ids: list[str],
        template_id: str,
        *,
        confirm_cloud_budget: bool,
        acknowledged: bool,
    ) -> dict[str, Any] | None:
        """The WU9 consent surface for ``source_video_ids`` (``None`` to skip the gate).

        With the gate OFF and no acknowledgement, the consent layer is a pass-through
        (every source runs), so it is omitted entirely — ``run_batch`` then takes its
        unchanged WU7 path. Otherwise one ``ai.planJob`` per distinct step shape
        drives :func:`plan_consent` (ZERO provider calls).
        """
        if not confirm_cloud_budget:
            return None
        shape_of = self._shape_of or (lambda _video_id: template_id)
        plan_job = self._plan_job or self._default_plan_job
        return plan_consent(
            source_video_ids,
            shape_of=shape_of,
            plan_job=plan_job,
            confirm_cloud_budget=confirm_cloud_budget,
            acknowledged=acknowledged,
        )

    def _default_plan_job(self, shape_key: Hashable) -> dict[str, Any]:
        """Default consent planner: the live ``ai.planJob`` handler by name (no keys).

        Passes the step shape as the request ``capability`` discriminator; the
        handler returns the pure pre-flight plan (``willEgress``/``cacheHit``/
        ``budget``/``cacheKey``) with ZERO provider calls.
        """
        plan_handler = self._methods_provider().get("ai.planJob")
        if plan_handler is None:  # pragma: no cover - register order guarantees it
            raise RpcError("ai.planJob is not registered", ErrorCode.INTERNAL_ERROR)
        ctx = RpcContext(emit_notification=lambda *_: None, jobs=None)
        return plan_handler({"capability": str(shape_key)}, ctx)


def register(
    *,
    path: str | os.PathLike[str],
    methods_provider: Callable[[], dict[str, Any]] | None = None,
    template_runner: TemplateRunner | None = None,
    shape_of: ShapeOf | None = None,
    plan_job: PlanJob | None = None,
    title_resolver: TitleResolver | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Batch:
    """Create a :class:`Batch` over ``path`` and register the seven methods.

    ``register_fn`` defaults to :func:`protocol.register`; tests inject a fake
    registrar + a tmp ``path`` + fake seams. Returns the service so the caller can
    hold it (mirrors :func:`templates.register`). The default per-source runner
    invokes ``templates.apply`` by name, so this module MUST be registered AFTER
    the ``templates.*`` group (the composition root in ``handlers.register_all``
    wires it there).
    """
    service = Batch(
        BatchStore(path),
        methods_provider=methods_provider,
        template_runner=template_runner,
        shape_of=shape_of,
        plan_job=plan_job,
        title_resolver=title_resolver,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("batch.create", service.create)
    reg("batch.start", service.start)
    reg("batch.plan", service.plan)
    reg("batch.status", service.status)
    reg("batch.list", service.list)
    reg("batch.cancel", service.cancel)
    reg("batch.resume", service.resume)
    reg("batch.delete", service.delete)
    return service


__all__ = [
    "ITEM_STATUSES",
    "SKIP_NO_HEADROOM",
    "SKIP_WOULD_EGRESS",
    "TERMINAL_STATUSES",
    "AwaitSubjob",
    "Batch",
    "BatchItem",
    "BatchState",
    "BatchStore",
    "BatchSummary",
    "PlanJob",
    "ShapeOf",
    "StartJob",
    "TemplateRunner",
    "TitleResolver",
    "consent_decision",
    "derive_status",
    "is_terminal_status",
    "new_item",
    "new_state",
    "plan_consent",
    "register",
    "resumable_video_ids",
    "resume_batch",
    "run_batch",
]
