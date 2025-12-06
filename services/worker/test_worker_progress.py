from services.worker.worker import _progress


class DummyTask:
    def __init__(self):
        self.calls = []

    def update_state(self, state, meta):
        self.calls.append((state, meta))


def test_progress_updates_state():
    dummy = DummyTask()
    meta = _progress(dummy, "running", 0.5, job_id="123")
    assert dummy.calls[0][0] == "PROGRESS"
    assert dummy.calls[0][1]["progress"] == 0.5
    assert dummy.calls[0][1]["job_id"] == "123"
    assert meta["status"] == "running"
