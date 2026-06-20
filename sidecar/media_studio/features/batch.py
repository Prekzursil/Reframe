"""Repurpose BATCH store + model (the repurpose bundle's WU6 durability substrate).

A *batch* points one saved :mod:`templates` template at MANY library sources and
runs them as one aggregate job (the runner is WU7; this module is the durable
state layer only). Because the job registry is in-memory (``jobs.py`` —
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

Pure logic + filesystem only — no heavy-ML / network / provider / runner imports.
The runner, resume, consent and RPC layers are later WUs.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..protocol import ErrorCode, RpcError
from ..util import get_logger, now_ms

log = get_logger("media_studio.features.batch")

BatchItem = dict[str, Any]
BatchState = dict[str, Any]
BatchSummary = dict[str, Any]

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
    "BatchItem",
    "BatchState",
    "BatchStore",
    "BatchSummary",
    "derive_status",
    "is_terminal_status",
    "new_item",
    "new_state",
]
