from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from media_core.subtitles.builder import SubtitleLine
from media_core.transcribe.models import Word
from services.worker import worker


def test_find_repo_root_and_rel_dir(tmp_path: Path):
    repo = tmp_path / "repo"
    marker = repo / "apps" / "api"
    marker.mkdir(parents=True, exist_ok=True)
    nested = repo / "services" / "worker"
    nested.mkdir(parents=True, exist_ok=True)
    file_path = nested / "worker.py"
    file_path.write_text("x", encoding="utf-8")

    assert worker._find_repo_root(file_path) == repo

    fallback = tmp_path / "plain" / "file.py"
    fallback.parent.mkdir(parents=True, exist_ok=True)
    fallback.write_text("x", encoding="utf-8")
    assert worker._find_repo_root(fallback) == fallback.parent

    class _RemoteStorage:
        pass

    assert worker._worker_rel_dir(storage=_RemoteStorage(), org_id=uuid4()).endswith("/tmp")
    assert worker._worker_rel_dir(storage=worker.LocalStorageBackend(media_root=tmp_path), org_id=uuid4()) == "tmp"


def test_dispatch_task_and_progress_helpers(monkeypatch):
    monkeypatch.setattr(worker, "is_local_queue_mode", lambda: True)
    monkeypatch.setattr(worker, "dispatch_local_task", lambda task_name, *args, queue: f"local-{task_name}-{queue}")
    local = worker._dispatch_task("tasks.echo", ["a"], queue="cpu")
    assert local.id.startswith("local-")

    monkeypatch.setattr(worker, "is_local_queue_mode", lambda: False)

    class _CeleryResult:
        id = "celery-task-id"

    monkeypatch.setattr(worker.celery_app, "send_task", lambda task_name, args, queue: _CeleryResult())
    remote = worker._dispatch_task("tasks.echo", ["a"], queue="cpu")
    assert remote.id == "celery-task-id"

    task = SimpleNamespace(update_state=lambda **_kwargs: None)
    payload = worker._progress(task, "running", 0.5, phase="x")
    assert payload["status"] == "running"
    assert payload["phase"] == "x"

    def _boom(**_kwargs):
        raise RuntimeError("update failed")

    task_bad = SimpleNamespace(update_state=_boom)
    payload_bad = worker._progress(task_bad, "running", 0.75)
    assert payload_bad["progress"] == 0.75


def test_retry_loop_and_job_asset_kwargs(monkeypatch):
    calls: list[int] = []
    updates: list[dict] = []

    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "0")
    monkeypatch.setattr(worker, "update_job", lambda job_id, payload: updates.append({"job_id": job_id, **payload}))
    monkeypatch.setattr(worker.time, "sleep", lambda _delay: None)

    def _fn():
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"first failure")
        return "ok"

    assert worker._run_ffmpeg_with_retries(job_id="j1", step="render", fn=_fn) == "ok"
    assert len(calls) == 2
    assert updates and updates[0]["retry_step"] == "render"

    monkeypatch.setattr(worker, "get_job_context", lambda _job_id: {"project_id": uuid4(), "org_id": None, "owner_user_id": uuid4()})
    kwargs = worker._job_asset_kwargs("job-1")
    assert "project_id" in kwargs and "owner_user_id" in kwargs and "org_id" not in kwargs


def test_publish_and_style_helpers():
    assert worker._publish_provider_from_step("publish_youtube", {}) == "youtube"
    assert worker._publish_provider_from_step("publish", {"provider": "instagram"}) == "instagram"

    with pytest.raises(ValueError):
        worker._publish_provider_from_step("publish", {"provider": "bad"})
    with pytest.raises(ValueError):
        worker._publish_provider_from_step("unknown", {})

    default_style = worker._resolve_style_from_options(None)
    assert default_style["font"]

    preset_style = worker._resolve_style_from_options({"style_preset": "clean white"})
    assert preset_style["font"]

    explicit_style = worker._resolve_style_from_options({"style": {"font": "Inter"}})
    assert explicit_style == {"font": "Inter"}


def test_slice_subtitle_lines_handles_overlap_and_fallback_words():
    lines = [
        SubtitleLine(
            start=0.0,
            end=4.0,
            words=[Word(text="hello", start=0.0, end=1.0), Word(text="world", start=1.0, end=2.0)],
            speaker="A",
        ),
        SubtitleLine(
            start=4.0,
            end=7.0,
            words=[Word(text="clip", start=4.0, end=5.0)],
            speaker="B",
        ),
    ]

    sliced = worker._slice_subtitle_lines(lines, start=1.0, end=5.5)
    assert sliced
    assert sliced[0].start == 0.0
    assert sliced[0].end <= 4.5

    # Fallback branch: malformed words but text preserved in synthetic word.
    bad_line = SubtitleLine(start=2.0, end=3.0, words=[], speaker="C")
    bad_line.words = [SimpleNamespace(text="bad", start="x", end="y")]
    sliced_bad = worker._slice_subtitle_lines([bad_line], start=1.0, end=4.0)
    assert sliced_bad and sliced_bad[0].words[0].text
