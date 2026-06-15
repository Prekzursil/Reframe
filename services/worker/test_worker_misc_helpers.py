"""Tests for the remaining worker helpers (translators, audio, clip assets)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from media_core.subtitles.builder import SubtitleLine  # pylint: disable=import-error
from media_core.transcribe.models import Word  # pylint: disable=import-error
from media_core.translate.translator import NoOpTranslator  # pylint: disable=import-error
from services.worker import worker  # pylint: disable=import-error


def _line(start, end, text="hi"):
    return SubtitleLine(
        start=start, end=end, words=[Word(text=text, start=start, end=end)]
    )


# --------------------------------------------------------------------------- #
# translator selection
# --------------------------------------------------------------------------- #


def test_select_translator_noop():
    """An explicit noop backend yields the NoOpTranslator."""
    translator = worker._select_translator(
        {"translator_backend": "noop"},
        src_language="en",
        target_language="es",
        warnings=[],
    )
    assert isinstance(translator, NoOpTranslator)


def test_select_translator_groq_unavailable(monkeypatch):
    """A groq backend without a client falls back to NoOpTranslator."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(worker, "get_groq_chat_client_from_env", lambda: None)
    translator = worker._select_translator(
        {"translator": "groq"},
        src_language="en",
        target_language="es",
        warnings=[],
    )
    assert isinstance(translator, NoOpTranslator)


def test_select_translator_local_falls_back(monkeypatch):
    """A LocalTranslator failure falls back to the groq/noop path."""
    def boom(*_a, **_k):
        raise RuntimeError("no argos models")

    monkeypatch.setattr(worker, "LocalTranslator", boom)
    monkeypatch.setattr(worker, "get_groq_chat_client_from_env", lambda: None)
    warnings: list[str] = []
    translator = worker._select_translator(
        {}, src_language="en", target_language="es", warnings=warnings
    )
    assert isinstance(translator, NoOpTranslator)
    assert warnings


def test_select_translator_local_success(monkeypatch):
    """A working LocalTranslator is returned directly."""
    sentinel = object()
    monkeypatch.setattr(worker, "LocalTranslator", lambda s, t: sentinel)
    translator = worker._select_translator(
        {}, src_language="en", target_language="es", warnings=[]
    )
    assert translator is sentinel


def test_build_groq_translator_offline(monkeypatch):
    """Groq translator is refused in offline mode."""
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    warnings: list[str] = []
    assert worker._build_groq_translator({}, warnings=warnings) is None
    assert warnings


def test_build_groq_translator_no_client(monkeypatch):
    """Groq translator is unavailable when no client can be built."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.setattr(worker, "get_groq_chat_client_from_env", lambda: None)
    warnings: list[str] = []
    assert worker._build_groq_translator({}, warnings=warnings) is None
    assert any("GROQ_API_KEY" in w for w in warnings)


def test_build_groq_translator_success(monkeypatch):
    """A configured client yields a CloudTranslator with the resolved model."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setattr(
        worker, "get_groq_chat_client_from_env", lambda: SimpleNamespace()
    )
    warnings: list[str] = []
    translator = worker._build_groq_translator(
        {"groq_model": "  "}, warnings=warnings
    )
    assert translator is not None
    assert translator.model == "llama3-8b-8192"
    assert any("Groq cloud translator" in w for w in warnings)


# --------------------------------------------------------------------------- #
# _load_translatable_srt
# --------------------------------------------------------------------------- #


def test_load_translatable_srt_missing_target(worker_env):
    """A missing target language returns the fail() error."""
    worker = worker_env.worker
    path = worker.new_tmp_file(".srt")
    path.write_text("x", encoding="utf-8")
    text, error = worker._load_translatable_srt(
        path, target_language="", fail=lambda e: {"err": e}
    )
    assert text is None and error == {"err": "Missing target_language"}


def test_load_translatable_srt_vtt(worker_env):
    """A .vtt source is converted to srt text."""
    worker = worker_env.worker
    path = worker.new_tmp_file(".vtt")
    path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi\n", encoding="utf-8"
    )
    text, error = worker._load_translatable_srt(
        path, target_language="es", fail=lambda e: {"err": e}
    )
    assert error is None
    assert "hi" in text


def test_load_translatable_srt_unsupported(worker_env):
    """A non-srt/vtt source returns a fail() error."""
    worker = worker_env.worker
    path = worker.new_tmp_file(".txt")
    path.write_text("x", encoding="utf-8")
    text, error = worker._load_translatable_srt(
        path, target_language="es", fail=lambda e: {"err": e}
    )
    assert text is None
    assert ".srt/.vtt" in error["err"]


def test_load_translatable_srt_vtt_parse_error(worker_env, monkeypatch):
    """A VTT parse failure is surfaced through fail()."""
    worker = worker_env.worker
    path = worker.new_tmp_file(".vtt")
    path.write_text("WEBVTT\n", encoding="utf-8")

    def boom(_text):
        raise RuntimeError("bad vtt")

    monkeypatch.setattr(worker, "parse_vtt", boom)
    text, error = worker._load_translatable_srt(
        path, target_language="es", fail=lambda e: {"err": e}
    )
    assert text is None
    assert "Failed to parse VTT" in error["err"]


# --------------------------------------------------------------------------- #
# audio extraction
# --------------------------------------------------------------------------- #


def test_extract_audio_wav_no_ffmpeg(monkeypatch):
    """Audio extraction requires ffmpeg on PATH."""
    monkeypatch.setattr(worker.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        worker._extract_audio_wav_for_diarization(Path("v.mp4"), Path("a.wav"))


def test_extract_audio_wav_runs_ffmpeg(monkeypatch):
    """Audio extraction invokes the runner with the expected ffmpeg args."""
    monkeypatch.setattr(worker.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    captured: dict = {}

    def runner(cmd, check=True, capture_output=True):  # pylint: disable=unused-argument
        captured["cmd"] = cmd

    worker._extract_audio_wav_for_diarization(
        Path("v.mp4"), Path("a.wav"), runner=runner
    )
    assert "pcm_s16le" in captured["cmd"]


# --------------------------------------------------------------------------- #
# remote asset fetch
# --------------------------------------------------------------------------- #


def test_fetch_remote_asset_path_resolves_storage(worker_env, monkeypatch):
    """A non-http URI is resolved via storage then downloaded."""
    worker = worker_env.worker
    monkeypatch.setattr(
        worker, "_download_remote_uri_to_tmp", lambda **k: Path("/tmp/x.bin")
    )
    storage = SimpleNamespace(get_download_url=lambda uri: "https://cdn/x.bin")
    asset = SimpleNamespace(uri="s3://bucket/x.bin", mime_type="x", id=uuid4())
    assert worker._fetch_remote_asset_path(asset, storage) == Path("/tmp/x.bin")


def test_fetch_remote_asset_path_unresolvable(worker_env):
    """A storage URI that resolves to nothing returns None."""
    worker = worker_env.worker
    storage = SimpleNamespace(get_download_url=lambda uri: None)
    asset = SimpleNamespace(uri="s3://bucket/x.bin", mime_type="x", id=uuid4())
    assert worker._fetch_remote_asset_path(asset, storage) is None


def test_fetch_remote_asset_path_download_error(worker_env, monkeypatch):
    """A download error is swallowed and returns None."""
    worker = worker_env.worker

    def boom(**_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(worker, "_download_remote_uri_to_tmp", boom)
    storage = SimpleNamespace(get_download_url=lambda uri: "https://cdn/x")
    asset = SimpleNamespace(uri="http://direct/x.bin", mime_type="x", id=uuid4())
    assert worker._fetch_remote_asset_path(asset, storage) is None


def test_download_remote_uri_offline(monkeypatch):
    """Downloading is refused entirely in offline mode."""
    monkeypatch.setenv("REFRAME_OFFLINE_MODE", "1")
    with pytest.raises(RuntimeError, match="OFFLINE_MODE"):
        worker._download_remote_uri_to_tmp(uri="https://x/y.bin")


def test_download_remote_uri_not_http(monkeypatch):
    """A non-http URI is rejected before any network call."""
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)
    with pytest.raises(ValueError, match="Not a remote"):
        worker._download_remote_uri_to_tmp(uri="ftp://x/y")


def test_download_remote_uri_empty_download(worker_env, monkeypatch):
    """An empty downloaded file raises a descriptive error."""
    worker = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(*_a, **_k):
        return _Resp()

    monkeypatch.setattr(worker.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(worker.shutil, "copyfileobj", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="empty"):
        worker._download_remote_uri_to_tmp(
            uri="https://cdn/file.srt", mime_type="text/srt"
        )


def test_download_remote_uri_success(worker_env, monkeypatch):
    """A successful download writes a non-empty tmp file."""
    worker = worker_env.worker
    monkeypatch.delenv("REFRAME_OFFLINE_MODE", raising=False)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(*_a, **_k):
        return _Resp()

    def fake_copy(_resp, fileobj):
        fileobj.write(b"payload")

    monkeypatch.setattr(worker.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(worker.shutil, "copyfileobj", fake_copy)
    # URI without an extension uses the mime-type suffix guess.
    dest = worker._download_remote_uri_to_tmp(
        uri="https://cdn/download", mime_type="text/plain"
    )
    assert dest.exists()
    assert dest.read_bytes() == b"payload"


# --------------------------------------------------------------------------- #
# clip subtitle/styled asset helpers
# --------------------------------------------------------------------------- #


def _clip_ctx(worker, *, source_lines=None):
    return worker.ShortsClipContext(
        job_id="job-1",
        src_path=Path("src.mp4"),
        mime_type="video/mp4",
        asset_kwargs={},
        use_subtitles=True,
        style_preset="tiktok bold",
        subtitles=worker.ShortsSubtitleContext(
            style_for_clip={"font": "X"},
            subtitle_source_lines=source_lines,
            warnings=[],
        ),
    )


def test_build_clip_subtitle_file_placeholder(worker_env):
    """Without source lines a placeholder VTT is written."""
    worker = worker_env.worker
    ctx = _clip_ctx(worker, source_lines=None)
    seg = SimpleNamespace(start=0.0, end=2.0)
    path = worker._build_clip_subtitle_file(ctx, idx=0, seg=seg)
    assert "placeholder" in path.read_text(encoding="utf-8")


def test_build_clip_subtitle_file_sliced(worker_env):
    """With source lines a sliced VTT is written."""
    worker = worker_env.worker
    ctx = _clip_ctx(worker, source_lines=[_line(0.0, 1.0, "hello")])
    seg = SimpleNamespace(start=0.0, end=2.0)
    path = worker._build_clip_subtitle_file(ctx, idx=0, seg=seg)
    assert "WEBVTT" in path.read_text(encoding="utf-8")


def test_build_clip_styled_asset_failure(worker_env, monkeypatch):
    """A styled render failure is caught and returns None with a warning."""
    worker = worker_env.worker
    ctx = _clip_ctx(worker)

    def boom(**_k):
        raise RuntimeError("render failed")

    monkeypatch.setattr(worker, "_render_styled_subtitles_to_file", boom)
    asset = worker._build_clip_styled_asset(
        ctx, idx=0, clip_path=Path("c.mp4"), subtitle_file=Path("s.vtt")
    )
    assert asset is None
    assert ctx.subtitles.warnings


def test_build_clip_subtitle_assets_build_failure(worker_env, monkeypatch):
    """A subtitle build failure returns (None, None) with a warning."""
    worker = worker_env.worker
    ctx = _clip_ctx(worker)

    def boom(*_a, **_k):
        raise RuntimeError("write failed")

    monkeypatch.setattr(worker, "_build_clip_subtitle_file", boom)
    seg = SimpleNamespace(start=0.0, end=2.0)
    result = worker._build_clip_subtitle_assets(
        ctx, idx=0, seg=seg, clip_path=Path("c.mp4")
    )
    assert result == (None, None)
    assert ctx.subtitles.warnings


def test_build_clip_subtitle_assets_success(worker_env, monkeypatch):
    """A successful subtitle build returns subtitle and styled assets."""
    worker = worker_env.worker
    ctx = _clip_ctx(worker, source_lines=[_line(0.0, 1.0)])
    styled = SimpleNamespace(id=uuid4(), uri="/media/tmp/styled.mp4")
    monkeypatch.setattr(worker, "_build_clip_styled_asset", lambda *a, **k: styled)
    seg = SimpleNamespace(start=0.0, end=2.0)
    subtitle_asset, styled_asset = worker._build_clip_subtitle_assets(
        ctx, idx=0, seg=seg, clip_path=Path("c.mp4")
    )
    assert subtitle_asset is not None
    assert styled_asset is styled
