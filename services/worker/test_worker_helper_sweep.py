from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from media_core.subtitles.builder import SubtitleLine
from media_core.transcribe.models import Word
from services.worker import worker


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_find_repo_root_and_rel_dir(tmp_path: Path):
    repo = tmp_path / "repo"
    marker = repo / "apps" / "api"
    marker.mkdir(parents=True, exist_ok=True)
    nested = repo / "services" / "worker"
    nested.mkdir(parents=True, exist_ok=True)
    file_path = nested / "worker.py"
    file_path.write_text("x", encoding="utf-8")

    _expect(worker._find_repo_root(file_path) == repo, "Expected repo marker path to resolve")

    fallback = tmp_path / "plain" / "file.py"
    fallback.parent.mkdir(parents=True, exist_ok=True)
    fallback.write_text("x", encoding="utf-8")
    _expect(worker._find_repo_root(fallback) == fallback.parent, "Expected parent fallback path")

    class _RemoteStorage:
        pass

    remote_rel = worker._worker_rel_dir(storage=_RemoteStorage(), org_id=uuid4())
    _expect(remote_rel.split("/")[-1] == "tmp", "Expected remote worker tmp suffix")
    local_rel = worker._worker_rel_dir(storage=worker.LocalStorageBackend(media_root=tmp_path), org_id=uuid4())
    _expect(local_rel == "tmp", "Expected local worker tmp path")


def test_dispatch_task_and_progress_helpers(monkeypatch):
    monkeypatch.setattr(worker, "is_local_queue_mode", lambda: True)
    monkeypatch.setattr(worker, "dispatch_local_task", lambda task_name, *args, queue: f"local-{task_name}-{queue}")
    local = worker._dispatch_task("tasks.echo", ["a"], queue="cpu")
    _expect(local.id.startswith("local-"), "Expected local queue task id")

    monkeypatch.setattr(worker, "is_local_queue_mode", lambda: False)

    class _CeleryResult:
        id = "celery-task-id"

    monkeypatch.setattr(worker.celery_app, "send_task", lambda task_name, args, queue: _CeleryResult())
    remote = worker._dispatch_task("tasks.echo", ["a"], queue="cpu")
    _expect(remote.id == "celery-task-id", "Expected celery task id")

    task = SimpleNamespace(update_state=lambda **_kwargs: None)
    payload = worker._progress(task, "running", 0.5, phase="x")
    _expect(payload["status"] == "running", "Expected running progress payload status")
    _expect(payload["phase"] == "x", "Expected running progress payload phase")

    def _boom(**_kwargs):
        raise RuntimeError("update failed")

    task_bad = SimpleNamespace(update_state=_boom)
    payload_bad = worker._progress(task_bad, "running", 0.75)
    _expect(payload_bad["progress"] == 0.75, "Expected progress fallback payload")


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
            raise worker.subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"], stderr=b"first failure")
        return "ok"

    _expect(worker._run_ffmpeg_with_retries(job_id="j1", step="render", fn=_fn) == "ok", "Expected retry helper success")
    _expect(len(calls) == 2, "Expected exactly one retry before success")
    _expect(bool(updates) and updates[0]["retry_step"] == "render", "Expected retry metadata update")

    monkeypatch.setattr(worker, "get_job_context", lambda _job_id: {"project_id": uuid4(), "org_id": None, "owner_user_id": uuid4()})
    kwargs = worker._job_asset_kwargs("job-1")
    _expect("project_id" in kwargs and "owner_user_id" in kwargs and "org_id" not in kwargs, "Expected scoped job asset kwargs")


def test_publish_and_style_helpers():
    _expect(worker._publish_provider_from_step("publish_youtube", {}) == "youtube", "Expected provider from typed step")
    _expect(worker._publish_provider_from_step("publish", {"provider": "instagram"}) == "instagram", "Expected provider from payload")

    with pytest.raises(ValueError):
        worker._publish_provider_from_step("publish", {"provider": "bad"})
    with pytest.raises(ValueError):
        worker._publish_provider_from_step("unknown", {})

    default_style = worker._resolve_style_from_options(None)
    _expect(bool(default_style["font"]), "Expected default style font")

    preset_style = worker._resolve_style_from_options({"style_preset": "clean white"})
    _expect(bool(preset_style["font"]), "Expected preset style font")

    explicit_style = worker._resolve_style_from_options({"style": {"font": "Inter"}})
    _expect(explicit_style == {"font": "Inter"}, "Expected explicit style override")


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
    _expect(bool(sliced), "Expected sliced subtitle lines")
    _expect(sliced[0].start == 0.0, "Expected clipped start alignment")
    _expect(sliced[0].end <= 4.5, "Expected clipped end bound")

    # Fallback branch: malformed words but text preserved in synthetic word.
    bad_line = SubtitleLine(start=2.0, end=3.0, words=[], speaker="C")
    bad_line.words = [SimpleNamespace(text="bad", start="x", end="y")]
    sliced_bad = worker._slice_subtitle_lines([bad_line], start=1.0, end=4.0)
    _expect(bool(sliced_bad) and bool(sliced_bad[0].words[0].text), "Expected fallback synthetic word text")
