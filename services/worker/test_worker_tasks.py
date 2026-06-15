"""End-to-end tests for the worker's Celery task bodies."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.models import JobStatus, MediaAsset  # pylint: disable=import-error


def _make_video_job(worker_env, *, job_type="captions"):
    """Create a local video asset (with a file) and a job referencing it."""
    asset = worker_env.add_asset(uri="/media/tmp/video.mp4", mime_type="video/mp4")
    worker_env.write_media_file(asset, b"fake-video-bytes")
    job = worker_env.add_job(job_type=job_type, input_asset_id=asset.id)
    return asset, job


# --------------------------------------------------------------------------- #
# Diagnostic tasks
# --------------------------------------------------------------------------- #


def test_ping_echo(worker_env):
    """``ping`` returns pong and ``echo`` returns its message."""
    worker = worker_env.worker
    assert worker.ping.run() == "pong"
    assert worker.echo.run("hello") == "hello"


def test_system_info(worker_env, monkeypatch):
    """``system_info`` reports python, env, ffmpeg, and feature flags."""
    worker = worker_env.worker
    monkeypatch.setattr(worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        worker.subprocess, "check_output", lambda *a, **k: "ffmpeg version 6.0\n"
    )
    info = worker.system_info.run()
    assert info["ffmpeg"]["present"] is True
    assert info["ffmpeg"]["version"] == "ffmpeg version 6.0"
    assert "transcribe_faster_whisper" in info["features"]


def test_system_info_no_ffmpeg(worker_env, monkeypatch):
    """When ffmpeg is missing the report marks it absent with no version."""
    worker = worker_env.worker
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    info = worker.system_info.run()
    assert info["ffmpeg"]["present"] is False
    assert info["ffmpeg"]["version"] is None


def test_system_info_ffmpeg_version_error(worker_env, monkeypatch):
    """A failing ffmpeg -version call degrades to a null version string."""
    worker = worker_env.worker
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    def boom(*_a, **_k):
        raise OSError("cannot exec")

    monkeypatch.setattr(worker.subprocess, "check_output", boom)
    info = worker.system_info.run()
    assert info["ffmpeg"]["version"] is None


# --------------------------------------------------------------------------- #
# transcribe_video
# --------------------------------------------------------------------------- #


def test_transcribe_video_missing_asset(worker_env):
    """A missing source asset fails the job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="transcribe")
    result = worker.transcribe_video.run(str(job.id), str(uuid4()))
    assert result["status"] == "failed"
    assert worker_env.get_job(job.id).status == JobStatus.failed


def test_transcribe_video_noop_backend(worker_env):
    """The noop backend produces a transcript asset and completes the job."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env, job_type="transcribe")
    result = worker.transcribe_video.run(str(job.id), str(asset.id), {"backend": "noop"})
    assert result["status"] == "transcribed"
    assert result["word_count"] >= 1
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_transcribe_video_empty_words_fallback(worker_env, monkeypatch):
    """An empty transcription triggers the noop fallback path."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env, job_type="transcribe")

    class _Empty:
        words: list = []

    monkeypatch.setattr(worker, "_transcribe_media", lambda *a, **k: _Empty())
    result = worker.transcribe_video.run(str(job.id), str(asset.id), {"backend": "noop"})
    assert result["status"] == "transcribed"
    assert result["word_count"] >= 1


# --------------------------------------------------------------------------- #
# generate_captions
# --------------------------------------------------------------------------- #


def test_generate_captions_missing_asset(worker_env):
    """A missing video asset fails the captions job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="captions")
    result = worker.generate_captions.run(str(job.id), str(uuid4()))
    assert result["status"] == "failed"


def test_generate_captions_noop(worker_env):
    """Noop captions produce an srt subtitle asset and complete the job."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env)
    result = worker.generate_captions.run(
        str(job.id), str(asset.id), {"backend": "noop", "formats": ["srt"]}
    )
    assert result["status"] == "captions_generated"
    assert result["output_asset_id"]
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_generate_captions_unknown_profile_and_diarize(worker_env, monkeypatch):
    """An unknown quality profile warns and diarization is applied when requested."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env)
    # Force diarization to run with a non-noop backend, but stub the heavy work.
    monkeypatch.setattr(
        worker, "_apply_diarization", lambda lines, **k: lines
    )
    result = worker.generate_captions.run(
        str(job.id),
        str(asset.id),
        {
            "backend": "noop",
            "formats": ["vtt"],
            "subtitle_quality_profile": "made-up",
            "speaker_labels": True,
            "diarization_backend": "pyannote",
            "language": "auto",
        },
    )
    assert result["subtitle_quality_profile"] == "balanced"
    assert any("Unknown subtitle_quality_profile" in w for w in result["warnings"])


def test_generate_captions_empty_words_fallback(worker_env, monkeypatch):
    """An empty transcription path falls back to noop words for captions."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env)

    class _Empty:
        words: list = []

    monkeypatch.setattr(worker, "_transcribe_media", lambda *a, **k: _Empty())
    result = worker.generate_captions.run(
        str(job.id), str(asset.id), {"backend": "noop"}
    )
    assert result["status"] == "captions_generated"


# --------------------------------------------------------------------------- #
# translate_subtitles
# --------------------------------------------------------------------------- #


def _make_srt_job(worker_env):
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/subs.srt", mime_type="text/srt"
    )
    worker_env.write_media_file(
        asset, b"1\n00:00:00,000 --> 00:00:01,000\nhello world\n"
    )
    job = worker_env.add_job(job_type="translate_subtitles", input_asset_id=asset.id)
    return asset, job


def test_translate_subtitles_missing_asset(worker_env):
    """A missing subtitle asset fails the translation job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="translate_subtitles")
    result = worker.translate_subtitles.run(str(job.id), str(uuid4()))
    assert result["status"] == "failed"


def test_translate_subtitles_missing_target_language(worker_env):
    """Translation requires a target language."""
    worker = worker_env.worker
    asset, job = _make_srt_job(worker_env)
    result = worker.translate_subtitles.run(str(job.id), str(asset.id), {})
    assert result["status"] == "failed"
    assert "target_language" in result["error"]


def test_translate_subtitles_noop_translator(worker_env):
    """The noop translator round-trips the subtitle and completes the job."""
    worker = worker_env.worker
    asset, job = _make_srt_job(worker_env)
    result = worker.translate_subtitles.run(
        str(job.id),
        str(asset.id),
        {"target_language": "es", "translator_backend": "noop", "source_language": "auto"},
    )
    assert result["status"] == "translated"
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_translate_subtitles_bilingual(worker_env):
    """Bilingual translation uses the bilingual code path."""
    worker = worker_env.worker
    asset, job = _make_srt_job(worker_env)
    result = worker.translate_subtitles.run(
        str(job.id),
        str(asset.id),
        {"target_language": "es", "translator": "noop", "bilingual": True},
    )
    assert result["bilingual"] is True


def test_translate_subtitles_vtt_source(worker_env):
    """A .vtt subtitle source is converted to srt before translation."""
    worker = worker_env.worker
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/subs.vtt", mime_type="text/vtt"
    )
    worker_env.write_media_file(
        asset, b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhola\n"
    )
    job = worker_env.add_job(job_type="translate_subtitles", input_asset_id=asset.id)
    result = worker.translate_subtitles.run(
        str(job.id), str(asset.id), {"target_language": "en", "translator": "noop"}
    )
    assert result["status"] == "translated"


def test_translate_subtitles_unsupported_format(worker_env):
    """A non-srt/vtt subtitle file is rejected."""
    worker = worker_env.worker
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/subs.txt", mime_type="text/plain"
    )
    worker_env.write_media_file(asset, b"not a subtitle")
    job = worker_env.add_job(job_type="translate_subtitles", input_asset_id=asset.id)
    result = worker.translate_subtitles.run(
        str(job.id), str(asset.id), {"target_language": "en", "translator": "noop"}
    )
    assert result["status"] == "failed"
    assert ".srt/.vtt" in result["error"]


def test_translate_subtitles_translation_error(worker_env, monkeypatch):
    """A translator exception is surfaced as a failed job."""
    worker = worker_env.worker
    asset, job = _make_srt_job(worker_env)

    def boom(*_a, **_k):
        raise RuntimeError("translate exploded")

    monkeypatch.setattr(worker, "translate_srt", boom)
    result = worker.translate_subtitles.run(
        str(job.id), str(asset.id), {"target_language": "es", "translator": "noop"}
    )
    assert result["status"] == "failed"
    assert "translation failed" in result["error"]


# --------------------------------------------------------------------------- #
# cut_clip_asset
# --------------------------------------------------------------------------- #


def test_cut_clip_missing_asset(worker_env):
    """A missing source asset fails the cut-clip job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="cut")
    result = worker.cut_clip_asset.run(str(job.id), str(uuid4()), 0.0, 1.0)
    assert result["status"] == "failed"


def test_cut_clip_success(worker_env, monkeypatch):
    """A successful cut creates a clip asset and a thumbnail."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env, job_type="cut")

    def fake_cut(_src, _start, _end, out):
        Path(out).write_bytes(b"clip")

    monkeypatch.setattr(worker, "cut_clip", fake_cut)
    monkeypatch.setattr(
        worker, "create_thumbnail_asset", lambda *a, **k: MediaAsset(
            kind="image", uri="/media/tmp/t.png", mime_type="image/png"
        )
    )
    # end < start exercises the swap branch.
    result = worker.cut_clip_asset.run(
        str(job.id), str(asset.id), 5.0, 2.0, {"label": "x"}
    )
    assert "asset_id" in result
    assert result["start"] == 2.0 and result["end"] == 5.0
    assert result["label"] == "x"
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_cut_clip_ffmpeg_failure(worker_env, monkeypatch):
    """An ffmpeg failure marks the cut-clip job failed."""
    worker = worker_env.worker
    asset, job = _make_video_job(worker_env, job_type="cut")

    def boom(*_a, **_k):
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(worker, "cut_clip", boom)
    result = worker.cut_clip_asset.run(str(job.id), str(asset.id), 0.0, 1.0)
    assert result["status"] == "failed"
    assert "Cut clip failed" in result["error"]


# --------------------------------------------------------------------------- #
# merge_video_audio
# --------------------------------------------------------------------------- #


def test_merge_missing_video(worker_env):
    """A missing video asset fails the merge job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="merge")
    result = worker.merge_video_audio.run(str(job.id), str(uuid4()), str(uuid4()))
    assert result["status"] == "failed"
    assert "Video asset" in result["error"]


def test_merge_missing_audio(worker_env):
    """A missing audio asset fails the merge job."""
    worker = worker_env.worker
    video, job = _make_video_job(worker_env, job_type="merge")
    result = worker.merge_video_audio.run(str(job.id), str(video.id), str(uuid4()))
    assert result["status"] == "failed"
    assert "Audio asset" in result["error"]


def test_merge_success(worker_env, monkeypatch):
    """A successful merge stores a merged video asset."""
    worker = worker_env.worker
    video, job = _make_video_job(worker_env, job_type="merge")
    audio = worker_env.add_asset(
        kind="audio", uri="/media/tmp/audio.m4a", mime_type="audio/mp4"
    )
    worker_env.write_media_file(audio, b"audio")

    def fake_merge(_v, _a, out, **_kwargs):
        Path(out).write_bytes(b"merged")

    monkeypatch.setattr(worker, "ffmpeg_merge_video_audio", fake_merge)
    result = worker.merge_video_audio.run(
        str(job.id), str(video.id), str(audio.id), {"offset": 1.0, "normalize": False}
    )
    assert result["status"] == "merged"
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_merge_ffmpeg_failure(worker_env, monkeypatch):
    """A merge ffmpeg failure marks the job failed."""
    worker = worker_env.worker
    video, job = _make_video_job(worker_env, job_type="merge")
    audio = worker_env.add_asset(
        kind="audio", uri="/media/tmp/audio.m4a", mime_type="audio/mp4"
    )
    worker_env.write_media_file(audio, b"audio")

    def boom(*_a, **_k):
        raise RuntimeError("merge failed")

    monkeypatch.setattr(worker, "ffmpeg_merge_video_audio", boom)
    result = worker.merge_video_audio.run(str(job.id), str(video.id), str(audio.id))
    assert result["status"] == "failed"
    assert "Merge failed" in result["error"]
