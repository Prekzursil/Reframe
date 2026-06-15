"""Tests for the worker ``_progress`` task-state helper."""

from services.worker.worker import _progress


class DummyTask:  # pylint: disable=too-few-public-methods
    """Minimal Celery task stub that records ``update_state`` calls."""

    def __init__(self):
        self.calls = []

    def update_state(self, state, meta):
        """Record a single ``(state, meta)`` state update."""
        self.calls.append((state, meta))


def test_progress_updates_state():
    """``_progress`` should emit a PROGRESS state with the supplied metadata."""
    dummy = DummyTask()
    meta = _progress(dummy, "running", 0.5, job_id="123")
    assert dummy.calls[0][0] == "PROGRESS"
    assert dummy.calls[0][1]["progress"] == 0.5
    assert dummy.calls[0][1]["job_id"] == "123"
    assert meta["status"] == "running"
