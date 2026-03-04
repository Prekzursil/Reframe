from __future__ import annotations

import io
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_worker_bool_and_color_helpers(monkeypatch):
    from services.worker import worker

    monkeypatch.setenv("REFRAME_TEST_FLAG", "true")
    _expect(worker._env_truthy("TEST_FLAG") is True, "Expected _env_truthy to read prefixed env")
    _expect(worker._truthy_env("TEST_FLAG") is True, "Expected _truthy_env wrapper behavior")

    _expect(worker._coerce_bool(True) is True, "Expected bool True")
    _expect(worker._coerce_bool(0) is False, "Expected numeric false")
    _expect(worker._coerce_bool("YES") is True, "Expected yes string to coerce true")
    _expect(worker._coerce_bool({}) is False, "Expected unknown type false")
    _expect(worker._coerce_bool_with_default(None, True) is True, "Expected default when None")

    _expect(worker._hex_to_ass_color("#ffcc00", default="x") == "&H0000CCFF", "Expected ASS BGR conversion")
    _expect(worker._hex_to_ass_color("abc", default="x") == "&H00CCBBAA", "Expected 3-char hex expansion")
    _expect(worker._hex_to_ass_color("bad*value", default="fallback") == "fallback", "Expected default on invalid")


def test_worker_retry_env_parsing(monkeypatch):
    from services.worker import worker

    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "not-int")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "not-float")
    _expect(worker._retry_max_attempts() == 2, "Expected fallback max attempts")
    _expect(worker._retry_base_delay_seconds() == 1.0, "Expected fallback base delay")

    monkeypatch.setenv("REFRAME_JOB_RETRY_MAX_ATTEMPTS", "0")
    monkeypatch.setenv("REFRAME_JOB_RETRY_BASE_DELAY_SECONDS", "-2")
    _expect(worker._retry_max_attempts() == 1, "Expected lower-bound max attempts")
    _expect(worker._retry_base_delay_seconds() == 0.0, "Expected lower-bound delay")


def test_worker_download_remote_uri_to_tmp_paths(monkeypatch, tmp_path: Path):
    from services.worker import worker

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: True)
    try:
        worker._download_remote_uri_to_tmp(uri="https://example.com/file.txt")
        raise AssertionError("Expected offline mode guard failure")
    except RuntimeError:
        pass

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: False)
    try:
        worker._download_remote_uri_to_tmp(uri="file:///tmp/x")
        raise AssertionError("Expected non-http URI failure")
    except ValueError:
        pass

    target = tmp_path / "downloaded.bin"
    monkeypatch.setattr(worker, "new_tmp_file", lambda _suffix: target)

    class _Resp:
        def __enter__(self):
            self.buf = io.BytesIO(b"hello")
            return self.buf

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: _Resp())

    out = worker._download_remote_uri_to_tmp(uri="https://example.com/file.bin")
    _expect(out == target, "Expected downloaded file path")
    _expect(out.read_bytes() == b"hello", "Expected downloaded bytes")

    empty_target = tmp_path / "empty.bin"
    monkeypatch.setattr(worker, "new_tmp_file", lambda _suffix: empty_target)

    class _EmptyResp:
        def __enter__(self):
            self.buf = io.BytesIO(b"")
            return self.buf

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *_args, **_kwargs: _EmptyResp())
    try:
        worker._download_remote_uri_to_tmp(uri="https://example.com/empty.bin")
        raise AssertionError("Expected empty download to fail")
    except RuntimeError:
        pass


def test_worker_transcribe_media_routing(monkeypatch, tmp_path: Path):
    from media_core.transcribe import TranscriptionBackend, TranscriptionConfig
    from services.worker import worker

    media = tmp_path / "audio.wav"
    media.write_bytes(b"data")

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: False)
    monkeypatch.setattr(worker, "transcribe_openai_file", lambda *_args, **_kwargs: "openai")
    monkeypatch.setattr(worker, "transcribe_faster_whisper", lambda *_args, **_kwargs: "faster")
    monkeypatch.setattr(worker, "transcribe_whisper_cpp", lambda *_args, **_kwargs: "cpp")
    monkeypatch.setattr(worker, "transcribe_whisper_timestamped", lambda *_args, **_kwargs: "ts")
    monkeypatch.setattr(worker, "transcribe_noop", lambda *_args, **_kwargs: "noop")

    warnings: list[str] = []

    _expect(
        worker._transcribe_media(
            media,
            TranscriptionConfig(backend=TranscriptionBackend.FASTER_WHISPER),
            warnings=warnings,
        )
        == "faster",
        "Expected faster route",
    )
    _expect(
        worker._transcribe_media(
            media,
            TranscriptionConfig(backend=TranscriptionBackend.WHISPER_CPP),
            warnings=warnings,
        )
        == "cpp",
        "Expected whisper.cpp route",
    )
    _expect(
        worker._transcribe_media(
            media,
            TranscriptionConfig(backend=TranscriptionBackend.WHISPER_TIMESTAMPED),
            warnings=warnings,
        )
        == "ts",
        "Expected timestamped route",
    )
    _expect(
        worker._transcribe_media(
            media,
            TranscriptionConfig(backend=TranscriptionBackend.NOOP),
            warnings=warnings,
        )
        == "noop",
        "Expected noop route",
    )
    _expect(
        worker._transcribe_media(
            media,
            TranscriptionConfig(backend=TranscriptionBackend.OPENAI_WHISPER),
            warnings=warnings,
        )
        == "openai",
        "Expected openai route",
    )

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: True)
    _expect(worker._transcribe_media(media, TranscriptionConfig(backend=TranscriptionBackend.OPENAI_WHISPER), warnings=warnings) == "noop", "Expected offline openai fallback")

    monkeypatch.setattr(worker, "offline_mode_enabled", lambda: False)
    monkeypatch.setattr(worker, "transcribe_faster_whisper", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    _expect(worker._transcribe_media(media, TranscriptionConfig(backend=TranscriptionBackend.FASTER_WHISPER), warnings=warnings) == "noop", "Expected exception fallback to noop")
    _expect(any("failed; falling back" in item for item in warnings), "Expected fallback warning")


def test_worker_extract_audio_and_thumbnail_paths(monkeypatch, tmp_path: Path):
    from services.worker import worker

    video = tmp_path / "in.mp4"
    video.write_bytes(b"video")
    audio = tmp_path / "out.wav"

    monkeypatch.setattr(worker.shutil, "which", lambda _name: None)
    try:
        worker._extract_audio_wav_for_diarization(video, audio)
        raise AssertionError("Expected missing ffmpeg error")
    except FileNotFoundError:
        pass

    calls: list[list[str]] = []
    monkeypatch.setattr(worker.shutil, "which", lambda _name: "ffmpeg")
    worker._extract_audio_wav_for_diarization(video, audio, runner=lambda cmd, **_kwargs: calls.append(cmd))
    _expect(calls and calls[0][-1] == str(audio), "Expected extraction command invocation")

    fallback_calls: list[dict] = []
    monkeypatch.setattr(worker, "create_asset", lambda **kwargs: fallback_calls.append(kwargs) or kwargs)
    fallback = worker.create_thumbnail_asset(None)
    _expect(fallback["kind"] == "image", "Expected fallback thumbnail asset for missing input")

    monkeypatch.setattr(worker.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(worker, "get_media_tmp", lambda: tmp_path)
    monkeypatch.setattr(worker, "uuid4", lambda: "test-thumb")

    def _runner_success(cmd, **_kwargs):
        out = Path(cmd[-1])
        out.write_bytes(b"png")

    success = worker.create_thumbnail_asset(video, runner=_runner_success)
    _expect(success.get("source_path") is not None, "Expected source-path thumbnail success")

    def _runner_fail(_cmd, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["ffmpeg"])

    failed = worker.create_thumbnail_asset(video, runner=_runner_fail)
    _expect(failed.get("contents") is not None, "Expected fallback thumbnail on ffmpeg error")


def test_worker_retention_publish_and_asset_helpers(monkeypatch, tmp_path: Path):
    from services.worker import worker

    monkeypatch.setenv("REFRAME_RETENTION_FREE_DAYS", "21")
    _expect(worker._retention_days_for_plan("free") == 21, "Expected env override for retention")
    monkeypatch.setenv("REFRAME_RETENTION_FREE_DAYS", "bad")
    _expect(worker._retention_days_for_plan("free") == 14, "Expected fallback on invalid retention env")

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=45)
    _expect(worker._is_older_than_retention(created_at=old, plan_code="pro", now=now) is True, "Expected old asset beyond retention")
    _expect(worker._is_older_than_retention(created_at=None, plan_code="pro", now=now) is False, "Expected None timestamp to be retained")

    clip_asset = str(uuid4())
    thumb_asset = str(uuid4())
    payload = {"clip_assets": [{"asset_id": clip_asset, "thumbnail_asset_id": thumb_asset, "subtitle_asset_id": "bad-id"}]}
    job = SimpleNamespace(output_asset_id=uuid4(), payload=payload)
    related = worker._job_related_asset_ids(job)
    _expect(len(related) == 3, "Expected output+clip+thumbnail UUIDs")

    conn = SimpleNamespace(account_label="Creator Account", external_account_id="acct123")
    asset = SimpleNamespace(id=uuid4())
    yt = worker._publish_result_for_provider(provider="youtube", connection=conn, asset=asset, payload={"title": "t"})
    tk = worker._publish_result_for_provider(provider="tiktok", connection=conn, asset=asset, payload={})
    ig = worker._publish_result_for_provider(provider="instagram", connection=conn, asset=asset, payload={})
    fb = worker._publish_result_for_provider(provider="facebook", connection=conn, asset=asset, payload={})
    _expect("youtube.com" in yt["published_url"], "Expected youtube URL")
    _expect("tiktok.com" in tk["published_url"], "Expected tiktok URL")
    _expect("instagram.com" in ig["published_url"], "Expected instagram URL")
    _expect("facebook.com" in fb["published_url"], "Expected facebook URL")

    _expect(worker._publish_provider_from_step("publish_youtube", {}) == "youtube", "Expected provider from typed step")
    _expect(worker._publish_provider_from_step("publish", {"provider": "facebook"}) == "facebook", "Expected provider from payload")
    try:
        worker._publish_provider_from_step("publish", {"provider": "unknown"})
        raise AssertionError("Expected unsupported provider failure")
    except ValueError:
        pass

    local_file = tmp_path / "asset.bin"
    local_file.write_bytes(b"1234")
    monkeypatch.setattr(worker, "is_remote_uri", lambda _uri: False)
    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(media_root=str(tmp_path)))
    size = worker._asset_size_bytes(SimpleNamespace(uri=str(local_file.relative_to(tmp_path))))
    _expect(size == 4, "Expected local asset size bytes")

