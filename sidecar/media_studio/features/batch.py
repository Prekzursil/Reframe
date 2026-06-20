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
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ..jobs import JobCancelled
from ..protocol import ErrorCode, RpcContext, RpcError
from ..util import clamp, get_logger, now_ms
from . import recipes

log = get_logger("media_studio.features.batch")

BatchItem = dict[str, Any]
BatchState = dict[str, Any]
BatchSummary = dict[str, Any]

#: A template-run seam: ``(video_id, ctx) -> {"jobId": ...}`` — runs one source
#: through the WU5 template path and returns the spawned sub-job id. The runner
#: only awaits + isolates; it never builds the per-source job itself.
TemplateRunner = Callable[[str, RpcContext], dict[str, Any]]
#: Maps a source ``video_id`` to a human title for the progress message.
TitleResolver = Callable[[str], str]
#: The sub-job await/relay seam (defaults to the recipe runner's ``_await_subjob``).
AwaitSubjob = Callable[[str, Any, RpcContext, Callable[[float, str], None]], Any]
#: The parent-job start seam: ``(job_body, **kwargs) -> <job with .id>`` (defaults
#: to ``ctx.jobs.start``). Injected by tests to run the resume body synchronously.
StartJob = Callable[..., Any]

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
        title = resolve_title(video_id)
        base = index / total * 100.0
        span = 100.0 / total
        prefix = f"source {index + 1}/{total} · {title} · "

        def on_sub(pct: float, message: str, _base: float = base, _span: float = span, _prefix: str = prefix) -> None:
            job_ctx.progress(_base + clamp(pct, 0.0, 100.0) / 100.0 * _span, f"{_prefix}{message}")

        final = store.update_item(batch_id, video_id, status="running")
        on_sub(0.0, "")
        try:
            started = template_runner(video_id, ctx)
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


__all__ = [
    "ITEM_STATUSES",
    "TERMINAL_STATUSES",
    "AwaitSubjob",
    "BatchItem",
    "BatchState",
    "BatchStore",
    "BatchSummary",
    "StartJob",
    "TemplateRunner",
    "TitleResolver",
    "derive_status",
    "is_terminal_status",
    "new_item",
    "new_state",
    "resumable_video_ids",
    "resume_batch",
    "run_batch",
]
