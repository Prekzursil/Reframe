from __future__ import annotations

from uuid import uuid4


def test_enqueue_job_uses_local_queue_when_enabled(monkeypatch):
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")

    import app.api as api_module

    monkeypatch.setattr(api_module, "dispatch_local_task", lambda task_name, *args, queue=None: "local-123")

    class _Job:
        id = uuid4()

    task_id = api_module.enqueue_job(_Job(), "tasks.generate_captions", "job-id", "asset-id", {"backend": "noop"})
    assert task_id == "local-123"


def test_system_status_prefers_local_queue_diagnostics(monkeypatch):
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")

    import app.api as api_module

    monkeypatch.setattr(
        api_module,
        "local_queue_diagnostics",
        lambda: {
            "ping_ok": True,
            "workers": ["local-queue", "pending:2"],
            "system_info": {"ffmpeg": {"present": True, "version": "6.1"}},
            "error": None,
        },
    )

    status = api_module.system_status()
    assert status.worker.ping_ok is True
    assert status.worker.workers == ["local-queue", "pending:2"]
    assert status.worker.system_info == {"ffmpeg": {"present": True, "version": "6.1"}}


def test_publish_dispatch_uses_local_queue_when_enabled(monkeypatch):
    monkeypatch.setenv("REFRAME_LOCAL_QUEUE_MODE", "true")

    import app.publish_api as publish_api

    monkeypatch.setattr(publish_api, "dispatch_local_task", lambda task_name, *args: "local-publish")

    class _Job:
        id = uuid4()

    task_id = publish_api._dispatch_publish_task(_Job())
    assert task_id == "local-publish"
