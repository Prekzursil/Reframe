from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from media_core.transcribe.models import TranscriptionResult, Word


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _words() -> list[Word]:
    return [
        Word(text="hello", start=0.0, end=0.5),
        Word(text="world", start=0.6, end=1.1),
    ]


def test_transcribe_video_missing_asset_path_marks_failed(monkeypatch):
    from services.worker import worker

    updates: list[dict] = []
    monkeypatch.setattr(worker, "update_job", lambda _job_id, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (None, None))

    result = worker.transcribe_video.run(str(uuid4()), str(uuid4()), {"backend": "noop"})

    _expect(result["status"] == "failed", "Expected missing source asset to fail task")
    _expect(any(item.get("status") == worker.JobStatus.failed for item in updates), "Expected failed job update")


def test_transcribe_video_success_with_backend_alias(monkeypatch, tmp_path: Path):
    from services.worker import worker

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (SimpleNamespace(id=uuid4()), video))
    monkeypatch.setattr(worker, "_transcribe_media", lambda *_args, **_kwargs: TranscriptionResult(words=_words()))
    monkeypatch.setattr(worker, "create_asset", lambda **_kwargs: SimpleNamespace(id=uuid4()))

    result = worker.transcribe_video.run(str(uuid4()), str(uuid4()), {"backend": "whisper", "language": "en"})

    _expect(result["status"] == "transcribed", "Expected transcribe task success")
    _expect(result["backend"] == "faster_whisper", "Expected whisper alias to map to faster_whisper")
    _expect(result["word_count"] == 2, "Expected generated word count")


def test_generate_captions_handles_invalid_profile_and_backend(monkeypatch, tmp_path: Path):
    from services.worker import worker

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (SimpleNamespace(id=uuid4()), video))
    # Force fallback path from empty transcription -> noop words.
    monkeypatch.setattr(worker, "_transcribe_media", lambda *_args, **_kwargs: TranscriptionResult(words=[]))
    monkeypatch.setattr(worker, "transcribe_noop", lambda *_args, **_kwargs: TranscriptionResult(words=_words()))
    monkeypatch.setattr(worker, "create_asset", lambda **_kwargs: SimpleNamespace(id=uuid4()))

    result = worker.generate_captions.run(str(uuid4()),
        str(uuid4()),
        {
            "backend": "unknown-backend",
            "formats": ["ass"],
            "subtitle_quality_profile": "nonexistent-profile",
            "diarize": True,
            "diarization_backend": "unknown-backend",
        },
    )

    _expect(result["status"] == "captions_generated", "Expected caption task success")
    _expect(result["transcription_backend"] == "noop", "Expected unknown backend fallback to noop")
    _expect(result["subtitle_quality_profile"] == "balanced", "Expected unknown quality profile fallback")
    _expect(any("Unknown backend" in item for item in result["warnings"]), "Expected backend warning")
    _expect(any("Unknown subtitle_quality_profile" in item for item in result["warnings"]), "Expected profile warning")


def test_generate_captions_missing_asset_fails(monkeypatch):
    from services.worker import worker

    updates: list[dict] = []
    monkeypatch.setattr(worker, "update_job", lambda _job_id, **kwargs: updates.append(kwargs))
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (None, None))

    result = worker.generate_captions.run(str(uuid4()), str(uuid4()), {"backend": "noop"})

    _expect(result["status"] == "failed", "Expected missing video failure")
    _expect(any(item.get("status") == worker.JobStatus.failed for item in updates), "Expected failed job update")


def test_translate_subtitles_fails_on_missing_target_language(monkeypatch, tmp_path: Path):
    from services.worker import worker

    subtitle = tmp_path / "captions.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello world\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (SimpleNamespace(id=uuid4()), subtitle))

    result = worker.translate_subtitles.run(str(uuid4()), str(uuid4()), {"source_language": "en"})

    _expect(result["status"] == "failed", "Expected missing target_language failure")
    _expect("target_language" in result["error"], "Expected missing target_language error message")


def test_translate_subtitles_success_with_noop_translator(monkeypatch, tmp_path: Path):
    from services.worker import worker

    subtitle = tmp_path / "captions.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello world\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (SimpleNamespace(id=uuid4()), subtitle))
    monkeypatch.setattr(worker, "create_asset", lambda **_kwargs: SimpleNamespace(id=uuid4()))

    result = worker.translate_subtitles.run(str(uuid4()),
        str(uuid4()),
        {"target_language": "es", "source_language": "en", "translator_backend": "noop", "bilingual": True},
    )

    _expect(result["status"] == "translated", "Expected subtitle translation success")
    _expect(result["target_language"] == "es", "Expected target language in payload")
    _expect(result["bilingual"] is True, "Expected bilingual output flag")


def test_translate_subtitles_rejects_unsupported_extension(monkeypatch, tmp_path: Path):
    from services.worker import worker

    subtitle = tmp_path / "captions.txt"
    subtitle.write_text("not-srt", encoding="utf-8")

    monkeypatch.setattr(worker, "update_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "_job_asset_kwargs", lambda _job_id: {})
    monkeypatch.setattr(worker, "fetch_asset", lambda _asset_id: (SimpleNamespace(id=uuid4()), subtitle))

    result = worker.translate_subtitles.run(str(uuid4()), str(uuid4()), {"target_language": "es"})

    _expect(result["status"] == "failed", "Expected unsupported extension failure")
    _expect("Only .srt/.vtt subtitles are supported" in result["error"], "Expected unsupported extension message")


def test_dispatch_pipeline_step_publish_paths_and_validation(monkeypatch):
    from services.worker import worker

    run = SimpleNamespace(id=uuid4(), input_asset_id=uuid4())
    job = SimpleNamespace(id=uuid4())
    calls: list[dict] = []
    monkeypatch.setattr(
        worker,
        "_dispatch_task",
        lambda task_name, args, queue: calls.append({"task_name": task_name, "args": args, "queue": queue}) or SimpleNamespace(id="task-1"),
    )

    task_id = worker._dispatch_pipeline_step(
        job=job,
        run=run,
        step_type="publish_youtube",
        input_asset_id=uuid4(),
        step_payload={"connection_id": str(uuid4()), "asset_id": str(uuid4())},
    )
    _expect(task_id == "task-1", "Expected publish step to dispatch task")
    _expect(calls[-1]["task_name"] == "tasks.publish_asset", "Expected publish task dispatch")

    try:
        worker._dispatch_pipeline_step(
            job=job,
            run=run,
            step_type="publish",
            input_asset_id=uuid4(),
            step_payload={"provider": "youtube"},
        )
        raise AssertionError("Expected validation error when connection_id is missing")
    except ValueError:
        pass

