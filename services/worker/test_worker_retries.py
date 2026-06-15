"""Tests for the worker's ffmpeg retry helper."""

from __future__ import annotations

import subprocess


def test_run_ffmpeg_with_retries_updates_job_payload(monkeypatch):
    """A transient ffmpeg failure is retried and recorded on the job payload."""
    # Imported lazily so monkeypatching can target the loaded module.
    from services.worker import worker  # pylint: disable=import-error,import-outside-toplevel

    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "0")

    updates: list[dict] = []

    def fake_update(_job_id: str, **kwargs):
        payload = kwargs.get("payload") or {}
        if payload:  # pragma: no branch - retry helper always sends a payload
            updates.append(payload)

    monkeypatch.setattr(worker, "update_job", fake_update)
    monkeypatch.setattr(worker.time, "sleep", lambda _s: None)

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"boom")
        return "ok"

    result = worker._run_ffmpeg_with_retries(  # pylint: disable=protected-access
        job_id="job-123", step="cut_clip:1", fn=flaky
    )
    assert result == "ok"
    assert updates
    assert updates[0]["retry_step"] == "cut_clip:1"
    assert updates[0]["retry_attempt"] == 1
    assert updates[0]["retry_max_attempts"] == 2
