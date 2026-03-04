import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from threading import Lock
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger("reframe.local_queue")


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_local_queue_mode() -> bool:
    return _truthy(os.getenv("REFRAME_LOCAL_QUEUE_MODE") or os.getenv("LOCAL_QUEUE_MODE"))


@lru_cache(maxsize=1)
def _executor() -> ThreadPoolExecutor:
    workers_raw = (os.getenv("REFRAME_LOCAL_QUEUE_WORKERS") or "4").strip()
    try:
        workers = max(1, int(workers_raw))
    except ValueError:
        workers = 4
    return ThreadPoolExecutor(max_workers=workers, thread_name_prefix="reframe-local-queue")


@lru_cache(maxsize=1)
def _worker_tasks() -> Dict[str, Any]:
    from services.worker import worker as worker_module

    # Celery task registry gives us the same task names that send_task dispatches.
    return dict(worker_module.celery_app.tasks)


_pending_lock = Lock()
_pending: Dict[str, Future] = {}


def _run_task(task_name: str, args: Tuple[Any, ...]) -> Any:
    tasks = _worker_tasks()
    task = tasks.get(task_name)
    if task is None:
        raise RuntimeError(f"Local queue task not found: {task_name}")
    return task.run(*args)


def dispatch_task(task_name: str, *args: Any, queue: Optional[str] = None) -> str:
    if not is_local_queue_mode():
        raise RuntimeError("Local queue mode is not enabled")

    task_id = f"local-{uuid4()}"

    def _wrapped() -> None:
        try:
            _run_task(task_name, args)
        except Exception:
            logger.exception("Local queue task failed", extra={"task": task_name, "task_id": task_id, "queue": queue})
            raise

    future = _executor().submit(_wrapped)
    with _pending_lock:
        _pending[task_id] = future

    def _cleanup(_fut: Future) -> None:
        with _pending_lock:
            _pending.pop(task_id, None)

    future.add_done_callback(_cleanup)
    return task_id


def revoke_task(task_id: str) -> bool:
    with _pending_lock:
        future = _pending.get(task_id)
    if future is None:
        return False
    return future.cancel()


def diagnostics() -> Dict[str, Any]:
    if not is_local_queue_mode():
        return {
            "ping_ok": False,
            "workers": [],
            "system_info": None,
            "error": "Local queue mode is disabled",
        }

    info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        task = _worker_tasks().get("tasks.system_info")
        if task is None:
            raise RuntimeError("tasks.system_info is unavailable")
        info = task.run()
    except Exception as exc:  # pragma: no cover - defensive
        error = f"Local diagnostics failed: {exc}"

    with _pending_lock:
        queued = len(_pending)

    workers = ["local-queue"]
    if queued > 0:
        workers.append(f"pending:{queued}")

    return {
        "ping_ok": True,
        "workers": workers,
        "system_info": info,
        "error": error,
    }
