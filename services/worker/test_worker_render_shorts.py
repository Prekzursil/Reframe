"""Tests for render_styled_subtitles, generate_shorts, and their helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models import JobStatus, MediaAsset  # pylint: disable=import-error
from media_core.segment.shorts import SegmentCandidate  # pylint: disable=import-error
from media_core.subtitles.builder import SubtitleLine  # pylint: disable=import-error
from media_core.transcribe.models import Word  # pylint: disable=import-error


def _video_asset(worker_env):
    asset = worker_env.add_asset(uri="/media/tmp/video.mp4", mime_type="video/mp4")
    worker_env.write_media_file(asset, b"fake-video")
    return asset


def _srt_asset(worker_env):
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/subs.srt", mime_type="text/srt"
    )
    worker_env.write_media_file(
        asset, b"1\n00:00:00,000 --> 00:00:02,000\nhello there\n"
    )
    return asset


def _line(start, end, text="hi"):
    return SubtitleLine(
        start=start, end=end, words=[Word(text=text, start=start, end=end)]
    )


# --------------------------------------------------------------------------- #
# render_styled_subtitles
# --------------------------------------------------------------------------- #


def test_render_styled_missing_video(worker_env):
    """Missing video asset fails the render job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="render")
    result = worker.render_styled_subtitles.run(
        str(job.id), str(uuid4()), str(uuid4())
    )
    assert result["status"] == "failed"
    assert "Video asset" in result["error"]


def test_render_styled_missing_subtitle(worker_env):
    """Missing subtitle asset fails the render job."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    job = worker_env.add_job(job_type="render")
    result = worker.render_styled_subtitles.run(
        str(job.id), str(video.id), str(uuid4())
    )
    assert result["status"] == "failed"
    assert "Subtitle asset" in result["error"]


def test_render_styled_success(worker_env, monkeypatch):
    """A successful render stores the output as a video asset."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    subs = _srt_asset(worker_env)
    job = worker_env.add_job(job_type="render")

    def fake_render(**_kwargs):
        out = worker.new_tmp_file(".mp4")
        out.write_bytes(b"rendered")
        return out

    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", fake_render)
    result = worker.render_styled_subtitles.run(
        str(job.id), str(video.id), str(subs.id), {"font": "X"}, {"preview_seconds": 5}
    )
    assert result["status"] == "styled_render"
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_render_styled_failure(worker_env, monkeypatch):
    """A render exception is reported as a failed job."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    subs = _srt_asset(worker_env)
    job = worker_env.add_job(job_type="render")

    def boom(**_kwargs):
        raise RuntimeError("render blew up")

    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", boom)
    result = worker.render_styled_subtitles.run(
        str(job.id), str(video.id), str(subs.id)
    )
    assert result["status"] == "failed"
    assert "Styled render failed" in result["error"]


def test_render_styled_subtitles_to_file_no_ffmpeg(worker_env, monkeypatch):
    """The render helper requires ffmpeg on PATH."""
    worker = worker_env.worker
    subs = worker.new_tmp_file(".srt")
    subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg is required"):
        worker._render_styled_subtitles_to_file(
            job_id="j",
            step="s",
            video_path=Path("v.mp4"),
            subtitle_path=subs,
            style={},
        )


def test_render_styled_subtitles_to_file_success(worker_env, monkeypatch):
    """The render helper builds the ffmpeg command and verifies output exists."""
    worker = worker_env.worker
    subs = worker.new_tmp_file(".srt")
    subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    captured: dict = {}

    def fake_run(cmd, check=True, capture_output=True):  # pylint: disable=unused-argument
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"out")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    out = worker._render_styled_subtitles_to_file(
        job_id="j",
        step="s",
        video_path=Path("v.mp4"),
        subtitle_path=subs,
        style={"font": "Arial"},
        preview_seconds=3,
    )
    assert out.exists()
    assert "-t" in captured["cmd"]


def test_render_styled_subtitles_to_file_empty_output(worker_env, monkeypatch):
    """An empty render output raises a descriptive error."""
    worker = worker_env.worker
    subs = worker.new_tmp_file(".srt")
    subs.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        worker, "_run_ffmpeg_with_retries", lambda **k: None
    )
    with pytest.raises(RuntimeError, match="output file was not created"):
        worker._render_styled_subtitles_to_file(
            job_id="j",
            step="s",
            video_path=Path("v.mp4"),
            subtitle_path=subs,
            style={},
        )


# --------------------------------------------------------------------------- #
# shorts helper functions
# --------------------------------------------------------------------------- #


def test_load_shorts_subtitle_source_disabled():
    """Subtitle loading returns None when subtitles are disabled."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    assert worker._load_shorts_subtitle_source(
        use_subtitles=False, subtitle_asset_id="x", warnings=[]
    ) is None


def test_load_shorts_subtitle_source_no_id():
    """A missing subtitle id warns and returns None."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    warnings: list[str] = []
    assert worker._load_shorts_subtitle_source(
        use_subtitles=True, subtitle_asset_id="", warnings=warnings
    ) is None
    assert warnings


def test_load_shorts_subtitle_source_missing_file(worker_env):
    """A subtitle id that doesn't resolve on disk warns and returns None."""
    worker = worker_env.worker
    warnings: list[str] = []
    assert worker._load_shorts_subtitle_source(
        use_subtitles=True, subtitle_asset_id=str(uuid4()), warnings=warnings
    ) is None
    assert warnings


def test_load_shorts_subtitle_source_unsupported(worker_env):
    """A non-srt/vtt subtitle file warns and returns None."""
    worker = worker_env.worker
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/notes.txt", mime_type="text/plain"
    )
    worker_env.write_media_file(asset, b"plain")
    warnings: list[str] = []
    result = worker._load_shorts_subtitle_source(
        use_subtitles=True, subtitle_asset_id=str(asset.id), warnings=warnings
    )
    assert result is None
    assert any(".srt/.vtt" in w for w in warnings)


def test_load_shorts_subtitle_source_success(worker_env):
    """A valid srt subtitle yields parsed lines."""
    worker = worker_env.worker
    asset = _srt_asset(worker_env)
    lines = worker._load_shorts_subtitle_source(
        use_subtitles=True, subtitle_asset_id=str(asset.id), warnings=[]
    )
    assert lines


def test_load_shorts_subtitle_source_fetch_error(worker_env, monkeypatch):
    """An exception while loading subtitles is swallowed with a warning."""
    worker = worker_env.worker

    def boom(_id):
        raise RuntimeError("disk error")

    monkeypatch.setattr(worker, "fetch_asset", boom)
    warnings: list[str] = []
    assert worker._load_shorts_subtitle_source(
        use_subtitles=True, subtitle_asset_id=str(uuid4()), warnings=warnings
    ) is None
    assert any("Failed to load" in w for w in warnings)


def test_score_candidates_by_silence_no_trim():
    """Without silence trimming candidates get descending placeholder scores."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    cands = [SegmentCandidate(0.0, 10.0), SegmentCandidate(10.0, 20.0)]
    worker._score_candidates_by_silence(
        cands, src_path=Path("x"), opts={}, trim_silence=False
    )
    assert cands[0].score > cands[1].score


def test_score_candidates_by_silence_with_overlap(monkeypatch):
    """Silence overlap reduces a candidate's score."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(worker, "detect_silence", lambda *a, **k: [(0.0, 5.0)])
    cands = [SegmentCandidate(0.0, 10.0), SegmentCandidate(0.0, 0.0)]
    worker._score_candidates_by_silence(
        cands, src_path=Path("x"), opts={}, trim_silence=True
    )
    assert cands[0].reason.startswith("silence_ratio=")
    assert cands[1].score == 0.0  # zero-duration candidate


def test_score_candidates_by_silence_error(monkeypatch):
    """A silence-detection error falls back to placeholder scoring."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    def boom(*_a, **_k):
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(worker, "detect_silence", boom)
    cands = [SegmentCandidate(0.0, 10.0)]
    worker._score_candidates_by_silence(
        cands, src_path=Path("x"), opts={}, trim_silence=True
    )
    assert cands[0].score == 1.0


def test_apply_candidate_snippets():
    """Snippets are assembled from overlapping subtitle lines."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    cands = [SegmentCandidate(0.0, 5.0)]
    worker._apply_candidate_snippets(cands, [_line(0.0, 2.0, "hello")])
    assert cands[0].snippet == "hello"


# --------------------------------------------------------------------------- #
# Groq segment scoring
# --------------------------------------------------------------------------- #


def test_apply_groq_segment_scoring_prerequisite():
    """An unmet prerequisite appends a warning and returns early."""
    from services.worker import worker  # pylint: disable=import-outside-toplevel

    warnings: list[str] = []
    worker._apply_groq_segment_scoring(
        [SegmentCandidate(0.0, 5.0)],
        opts={},
        prompt="",
        subtitle_asset_id="x",
        warnings=warnings,
    )
    assert warnings


def test_apply_groq_segment_scoring_no_client(worker_env, monkeypatch):
    """Groq scoring warns and skips when no client is configured."""
    worker = worker_env.worker
    asset = _srt_asset(worker_env)
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(worker, "get_groq_chat_client_from_env", lambda: None)
    warnings: list[str] = []
    worker._apply_groq_segment_scoring(
        [SegmentCandidate(0.0, 5.0)],
        opts={},
        prompt="make it pop",
        subtitle_asset_id=str(asset.id),
        warnings=warnings,
    )
    assert any("GROQ_API_KEY is not set" in w for w in warnings)


def test_apply_groq_segment_scoring_success(worker_env, monkeypatch):
    """A configured Groq client blends LLM scores into the candidates."""
    worker = worker_env.worker
    asset = _srt_asset(worker_env)
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(
        worker, "get_groq_chat_client_from_env", lambda: SimpleNamespace()
    )

    # pylint: disable-next=unused-argument
    def fake_llm(*, transcript, candidates, prompt, model, client):  # noqa: D401
        for cand in candidates:
            cand.score = 0.9

    monkeypatch.setattr(worker, "score_segments_llm", fake_llm)
    cands = [SegmentCandidate(0.0, 2.0, score=0.5)]
    warnings: list[str] = []
    worker._apply_groq_segment_scoring(
        cands,
        opts={"groq_model": "m"},
        prompt="make it pop",
        subtitle_asset_id=str(asset.id),
        warnings=warnings,
    )
    assert any("Applied Groq segment scoring" in w for w in warnings)
    assert cands[0].score == (0.2 * 0.5) + (0.8 * 0.9)


def test_apply_groq_segment_scoring_exception(worker_env, monkeypatch):
    """A Groq scoring error is swallowed with a fallback warning."""
    worker = worker_env.worker
    asset = _srt_asset(worker_env)
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    def boom():
        raise RuntimeError("groq down")

    monkeypatch.setattr(worker, "get_groq_chat_client_from_env", boom)
    warnings: list[str] = []
    worker._apply_groq_segment_scoring(
        [SegmentCandidate(0.0, 2.0)],
        opts={},
        prompt="p",
        subtitle_asset_id=str(asset.id),
        warnings=warnings,
    )
    assert any("Groq scoring failed" in w for w in warnings)


def test_groq_load_subtitle_lines_missing(worker_env):
    """Missing subtitle file warns and returns None."""
    worker = worker_env.worker
    warnings: list[str] = []
    assert worker._groq_load_subtitle_lines(str(uuid4()), warnings=warnings) is None
    assert warnings


def test_groq_load_subtitle_lines_unsupported(worker_env):
    """An unsupported subtitle format raises ValueError inside the loader."""
    worker = worker_env.worker
    asset = worker_env.add_asset(
        kind="subtitle", uri="/media/tmp/sub.txt", mime_type="text/plain"
    )
    worker_env.write_media_file(asset, b"plain")
    with pytest.raises(ValueError):
        worker._groq_load_subtitle_lines(str(asset.id), warnings=[])


# --------------------------------------------------------------------------- #
# generate_shorts
# --------------------------------------------------------------------------- #


def _stub_clip_assets(worker, monkeypatch):
    """Stub ffmpeg-driven helpers so generate_shorts runs without ffmpeg."""
    def fake_cut(_src, _start, _end, out):
        Path(out).write_bytes(b"clip")

    monkeypatch.setattr(worker, "cut_clip", fake_cut)
    monkeypatch.setattr(
        worker,
        "create_thumbnail_asset",
        lambda *a, **k: MediaAsset(
            kind="image", uri="/media/tmp/t.png", mime_type="image/png"
        ),
    )


def test_generate_shorts_missing_asset(worker_env):
    """A missing source asset fails the shorts job."""
    worker = worker_env.worker
    job = worker_env.add_job(job_type="shorts")
    result = worker.generate_shorts.run(str(job.id), str(uuid4()))
    assert result["status"] == "failed"


def test_generate_shorts_probe_failure(worker_env, monkeypatch):
    """A media-probe failure fails the shorts job."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    job = worker_env.add_job(job_type="shorts")

    def boom(_p):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(worker, "probe_media", boom)
    result = worker.generate_shorts.run(str(job.id), str(video.id))
    assert result["status"] == "failed"
    assert "Failed to probe media" in result["error"]


def test_generate_shorts_success_no_subtitles(worker_env, monkeypatch):
    """Shorts generation produces clips and a manifest without subtitles."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    job = worker_env.add_job(job_type="shorts")
    monkeypatch.setattr(worker, "probe_media", lambda _p: {"duration": 120.0})
    _stub_clip_assets(worker, monkeypatch)
    result = worker.generate_shorts.run(
        str(job.id), str(video.id), {"max_clips": 2, "max_duration": 60.0}
    )
    assert result["status"] == "shorts_generated"
    assert len(result["clip_assets"]) >= 1
    assert worker_env.get_job(job.id).status == JobStatus.completed


def test_generate_shorts_with_subtitles(worker_env, monkeypatch):
    """Shorts generation burns subtitles when use_subtitles is enabled."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    subs = _srt_asset(worker_env)
    job = worker_env.add_job(job_type="shorts")
    monkeypatch.setattr(worker, "probe_media", lambda _p: {"duration": 90.0})
    _stub_clip_assets(worker, monkeypatch)

    def fake_render(**_kwargs):
        out = worker.new_tmp_file(".mp4")
        out.write_bytes(b"styled")
        return out

    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", fake_render)
    result = worker.generate_shorts.run(
        str(job.id),
        str(video.id),
        {
            "max_clips": 1,
            "max_duration": 60.0,
            "use_subtitles": True,
            "subtitle_asset_id": str(subs.id),
            "style_preset": "tiktok bold",
        },
    )
    assert result["status"] == "shorts_generated"
    clip = result["clip_assets"][0]
    assert clip["subtitle_asset_id"] is not None
    assert clip["styled_asset_id"] is not None


def test_generate_shorts_cut_failure(worker_env, monkeypatch):
    """A clip-cut failure aborts the shorts job."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    job = worker_env.add_job(job_type="shorts")
    monkeypatch.setattr(worker, "probe_media", lambda _p: {"duration": 120.0})

    def boom(*_a, **_k):
        raise RuntimeError("cut failed")

    monkeypatch.setattr(worker, "cut_clip", boom)
    result = worker.generate_shorts.run(
        str(job.id), str(video.id), {"max_clips": 1}
    )
    assert result["status"] == "failed"
    assert "Failed to cut clip" in result["error"]


def test_generate_shorts_groq_scoring(worker_env, monkeypatch):
    """Shorts can route candidate scoring through the Groq backend."""
    worker = worker_env.worker
    video = _video_asset(worker_env)
    subs = _srt_asset(worker_env)
    job = worker_env.add_job(job_type="shorts")
    monkeypatch.setattr(worker, "probe_media", lambda _p: {"duration": 120.0})
    _stub_clip_assets(worker, monkeypatch)
    applied: dict = {}
    monkeypatch.setattr(
        worker,
        "_apply_groq_segment_scoring",
        lambda *a, **k: applied.setdefault("called", True),
    )
    result = worker.generate_shorts.run(
        str(job.id),
        str(video.id),
        {
            "max_clips": 1,
            "segment_scoring_backend": "groq",
            "prompt": "best moments",
            "subtitle_asset_id": str(subs.id),
            "trim_silence": True,
        },
    )
    assert result["status"] == "shorts_generated"
    assert applied.get("called") is True
