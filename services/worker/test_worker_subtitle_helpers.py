"""Tests for subtitle slicing, serialization, and transcriber-resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from media_core.subtitles.builder import SubtitleLine  # pylint: disable=import-error
from media_core.transcribe import TranscriptionBackend, TranscriptionConfig  # noqa: E501  pylint: disable=import-error
from media_core.transcribe.models import Word  # pylint: disable=import-error
from media_core.diarize import DiarizationBackend  # pylint: disable=import-error
from services.worker import worker  # pylint: disable=import-error


def _line(start, end, text="hi"):
    return SubtitleLine(
        start=start, end=end, words=[Word(text=text, start=start, end=end)]
    )


def test_shift_subtitle_words_clips_and_skips():
    """Words are shifted to clip-relative timing and out-of-range ones dropped."""
    words = [
        Word(text="a", start=10.0, end=11.0),
        Word(text="b", start=0.0, end=1.0),  # before clip window -> dropped
    ]
    shifted = worker._shift_subtitle_words(words, start=10.0, clip_duration=5.0)
    assert len(shifted) == 1
    assert shifted[0].start == 0.0
    assert worker._shift_subtitle_words(None, start=0.0, clip_duration=5.0) == []


def test_shift_subtitle_line_outside_window_returns_none():
    """A line entirely outside the requested window is dropped."""
    assert worker._shift_subtitle_line(
        _line(0.0, 1.0), start=10.0, end=20.0, clip_duration=10.0
    ) is None


def test_shift_subtitle_line_preserves_text_when_words_unshiftable():
    """When word timings fall outside the clip, line text is preserved."""
    line = SubtitleLine(
        start=10.0,
        end=15.0,
        words=[Word(text="keepme", start=0.0, end=1.0)],
    )
    shifted = worker._shift_subtitle_line(
        line, start=10.0, end=15.0, clip_duration=5.0
    )
    assert shifted is not None
    assert shifted.text() == "keepme"


def test_slice_subtitle_lines():
    """``_slice_subtitle_lines`` keeps overlapping lines and time-shifts them."""
    lines = [_line(10.0, 12.0, "in"), _line(100.0, 101.0, "out")]
    out = worker._slice_subtitle_lines(lines, start=10.0, end=20.0)
    assert len(out) == 1
    assert out[0].start == 0.0


def test_serialize_subtitles_formats():
    """``_serialize_subtitles`` emits ass/vtt/srt content and metadata."""
    lines = [_line(0.0, 1.0, "hello")]
    ass = worker._serialize_subtitles(lines, "ass")
    assert ass[1] == "text/ass" and ass[2] == ".ass"
    vtt = worker._serialize_subtitles(lines, "vtt")
    assert vtt[1] == "text/vtt"
    srt = worker._serialize_subtitles(lines, "unknown")
    assert srt[1] == "text/srt"


def test_parse_subtitle_lines_by_suffix(worker_env):
    """Subtitle parsing dispatches by file suffix and returns None otherwise."""
    worker = worker_env.worker
    vtt = worker.new_tmp_file(".vtt")
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi\n", encoding="utf-8")
    assert worker._parse_subtitle_lines_by_suffix(vtt)
    srt = worker.new_tmp_file(".srt")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    assert worker._parse_subtitle_lines_by_suffix(srt)
    txt = worker.new_tmp_file(".txt")
    txt.write_text("plain", encoding="utf-8")
    assert worker._parse_subtitle_lines_by_suffix(txt) is None


def test_prepare_ass_subtitle_path_passthrough_and_convert(worker_env):
    """ASS files pass through; srt/vtt are converted to karaoke ASS."""
    worker = worker_env.worker
    ass = worker.new_tmp_file(".ass")
    ass.write_text("[Script Info]\n", encoding="utf-8")
    assert worker._prepare_ass_subtitle_path(ass) == ass
    srt = worker.new_tmp_file(".srt")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    converted = worker._prepare_ass_subtitle_path(srt)
    assert converted.suffix == ".ass"
    assert converted.exists()


def test_prepare_ass_subtitle_path_rejects_unknown(worker_env):
    """Unsupported subtitle suffixes raise ValueError."""
    worker = worker_env.worker
    bad = worker.new_tmp_file(".txt")
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        worker._prepare_ass_subtitle_path(bad)


def test_resolve_transcriber_openai_offline(monkeypatch):
    """OpenAI whisper falls back to noop when offline mode is enabled."""
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    warnings: list[str] = []
    cfg = TranscriptionConfig(backend=TranscriptionBackend.OPENAI_WHISPER, model="m")
    fn = worker._resolve_transcriber(Path("x.mp4"), cfg, warnings=warnings)
    result = fn()
    assert result.words
    assert warnings


def test_resolve_transcriber_openai_online(monkeypatch):
    """OpenAI whisper online routes to the openai file transcriber."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    called: dict = {}
    monkeypatch.setattr(
        worker, "transcribe_openai_file", lambda p, c: called.setdefault("p", p)
    )
    cfg = TranscriptionConfig(backend=TranscriptionBackend.OPENAI_WHISPER, model="m")
    fn = worker._resolve_transcriber(Path("clip.mp4"), cfg, warnings=[])
    fn()
    assert called["p"] == "clip.mp4"


def test_resolve_transcriber_known_backend(monkeypatch):
    """Known non-OpenAI backends map to their transcriber callables."""
    monkeypatch.setattr(worker, "transcribe_faster_whisper", lambda p, c: "fw")
    cfg = TranscriptionConfig(backend=TranscriptionBackend.FASTER_WHISPER, model="m")
    fn = worker._resolve_transcriber(Path("x.mp4"), cfg, warnings=[])
    assert fn() == "fw"


def test_resolve_transcriber_unknown_backend_uses_noop():
    """An unmapped backend falls back to the noop transcriber."""
    cfg = TranscriptionConfig(backend=TranscriptionBackend.NOOP, model="m")
    fn = worker._resolve_transcriber(Path("x.mp4"), cfg, warnings=[])
    assert fn().words


def test_transcribe_media_falls_back_on_error(monkeypatch):
    """A failing transcriber falls back to noop and records a warning."""
    def boom(_p, _c):
        raise RuntimeError("backend down")

    monkeypatch.setattr(worker, "transcribe_faster_whisper", boom)
    cfg = TranscriptionConfig(backend=TranscriptionBackend.FASTER_WHISPER, model="m")
    warnings: list[str] = []
    result = worker._transcribe_media(Path("x.mp4"), cfg, warnings=warnings)
    assert result.words
    assert any("falling back to noop" in w for w in warnings)


def test_resolve_transcribe_video_backend_paths(monkeypatch):
    """whisper alias, unknown backend, and offline OpenAI are normalised."""
    warnings: list[str] = []
    assert worker._resolve_transcribe_video_backend(
        "whisper", warnings=warnings
    ) == TranscriptionBackend.FASTER_WHISPER
    assert worker._resolve_transcribe_video_backend(
        "totally-unknown", warnings=warnings
    ) == TranscriptionBackend.NOOP
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    assert worker._resolve_transcribe_video_backend(
        "openai_whisper", warnings=warnings
    ) == TranscriptionBackend.NOOP


def test_resolve_captions_backend_paths(monkeypatch):
    """The captions backend resolver handles whisper, unknown, and offline."""
    warnings: list[str] = []
    assert worker._resolve_captions_backend(
        "whisper", warnings=warnings
    ) == TranscriptionBackend.NOOP
    assert worker._resolve_captions_backend(
        "bogus", warnings=warnings
    ) == TranscriptionBackend.NOOP
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    assert worker._resolve_captions_backend(
        "openai_whisper", warnings=warnings
    ) == TranscriptionBackend.NOOP


def test_build_caption_grouping_uses_profile_and_opts():
    """Grouping config layers explicit opts over profile defaults."""
    grouping = worker._build_caption_grouping(
        {"max_chars_per_line": 20}, {"max_words_per_line": 5}
    )
    assert grouping.max_chars_per_line == 20
    assert grouping.max_words_per_line == 5


def test_build_diarization_config_paths(monkeypatch):
    """Diarization config resolves backends and default models."""
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    warnings: list[str] = []
    cfg = worker._build_diarization_config(
        {"diarization_backend": "speechbrain"}, warnings=warnings
    )
    assert cfg.backend == DiarizationBackend.SPEECHBRAIN
    assert "speechbrain" in cfg.model
    unknown = worker._build_diarization_config(
        {"diarization_backend": "made-up"}, warnings=warnings
    )
    assert unknown.backend == DiarizationBackend.NOOP
    assert warnings


def test_apply_diarization_offline_pyannote(monkeypatch):
    """Offline mode refuses pyannote diarization and keeps lines unchanged."""
    from media_core.diarize import DiarizationConfig  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    lines = [_line(0.0, 1.0)]
    warnings: list[str] = []
    out = worker._apply_diarization(
        lines,
        src_path=Path("x.mp4"),
        diarization_config=DiarizationConfig(backend=DiarizationBackend.PYANNOTE),
        warnings=warnings,
    )
    assert out is lines
    assert warnings


def test_apply_diarization_offline_speechbrain(monkeypatch):
    """Offline mode refuses speechbrain diarization too."""
    from media_core.diarize import DiarizationConfig  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    lines = [_line(0.0, 1.0)]
    warnings: list[str] = []
    out = worker._apply_diarization(
        lines,
        src_path=Path("x.mp4"),
        diarization_config=DiarizationConfig(backend=DiarizationBackend.SPEECHBRAIN),
        warnings=warnings,
    )
    assert out is lines


def test_apply_diarization_failure_keeps_lines(monkeypatch, worker_env):
    """A diarization failure is swallowed and the original lines are returned."""
    from media_core.diarize import DiarizationConfig  # pylint: disable=import-outside-toplevel

    worker = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    def boom(*_a, **_k):
        raise RuntimeError("no ffmpeg")

    monkeypatch.setattr(worker, "_extract_audio_wav_for_diarization", boom)
    lines = [_line(0.0, 1.0)]
    warnings: list[str] = []
    out = worker._apply_diarization(
        lines,
        src_path=Path("x.mp4"),
        diarization_config=DiarizationConfig(backend=DiarizationBackend.NOOP),
        warnings=warnings,
    )
    assert out is lines
    assert any("diarization failed" in w.lower() for w in warnings)


def test_apply_diarization_success(monkeypatch, worker_env):
    """A successful diarization assigns speaker segments to the lines."""
    from media_core.diarize import DiarizationConfig  # pylint: disable=import-outside-toplevel

    worker = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(
        worker, "_extract_audio_wav_for_diarization", lambda *a, **k: None
    )
    monkeypatch.setattr(worker, "diarize_audio", lambda *a, **k: ["seg"])
    monkeypatch.setattr(
        worker, "assign_speakers_to_lines", lambda lines, segs: ["assigned"]
    )
    out = worker._apply_diarization(
        [_line(0.0, 1.0)],
        src_path=Path("x.mp4"),
        diarization_config=DiarizationConfig(backend=DiarizationBackend.NOOP),
        warnings=[],
    )
    assert out == ["assigned"]
