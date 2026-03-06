from __future__ import annotations


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_worker_dispatch_task_uses_local_queue(monkeypatch):
    from services.worker import worker

    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")
    monkeypatch.setattr(worker, "is_local_queue_mode", lambda: True)
    monkeypatch.setattr(worker, "dispatch_local_task", lambda task_name, *args, queue=None: "local-step")

    result = worker._dispatch_task("tasks.generate_captions", args=["job", "asset", {}], queue="cpu")

    _expect(result.id == "local-step", "Expected local queue dispatch result id")
