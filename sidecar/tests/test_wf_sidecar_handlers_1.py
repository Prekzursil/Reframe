"""WF-unit ``sidecar-handlers-1`` regression tests.

Isolated, uniquely-named suite covering the verified-findings fixes in
``handlers/media_ops.py`` and ``handlers/ai_ops.py``:

* transcribe.start is GPU-tagged (jobs.py gpu serialization) and threads the
  per-job ``alignWords`` trigger into the transcript job body.
* ``_maybe_align_words`` runs the ctc-forced-aligner 2nd pass on EITHER the
  per-job ``align_words`` flag OR ``settings['karaoke']``, short-circuits an
  already-cancelled job, and forwards the job progress/cancel callbacks.
* ``_dub_translator`` builds its tier3 hosted pool through
  ``_translator_for_function('translation')`` so Offline mode forces a
  LOCAL-only pool (no transcript-text egress), while online routing is kept.

Every heavy seam is monkeypatched — no torch / ffmpeg / real aligner / network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _JobCtx:
    """Minimal stand-in for the job context (``cancelled`` + ``progress``)."""

    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled
        self.progress_calls: list[tuple[float, str]] = []

    def progress(self, pct: float, msg: str) -> None:
        self.progress_calls.append((pct, msg))


class _RecordingJobs:
    """A jobs registry stub that records ``start()`` kwargs and returns a Job."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def start(self, handler: Any, **kwargs: Any) -> Any:
        self.calls.append((handler, kwargs))
        return type("_Job", (), {"id": "job-1"})()


def _ctx(jobs: Any) -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=jobs)


# --------------------------------------------------------------------------- #
# transcribe.start — GPU tagging (finding 640) + alignWords threading (520)
# --------------------------------------------------------------------------- #
def test_transcribe_start_gpu_tagged_and_threads_align_words(tmp_path: Path) -> None:
    """transcribe.start claims the gpu slot and forwards alignWords=True."""
    svc = Services(data_dir=tmp_path / "d")
    svc._resolve_video_path = lambda vid: "/resolved/a.mp4"  # type: ignore[assignment]
    captured: dict[str, Any] = {}

    def fake_persist(video_id: str, job_ctx: Any, *, language: str | None = None, align_words: bool = False):
        captured.update(video_id=video_id, language=language, align_words=align_words)
        return {"language": language, "align": align_words}

    svc._transcribe_and_persist = fake_persist  # type: ignore[assignment]
    jobs = _RecordingJobs()

    out = svc.transcribe_start({"videoId": "v1", "alignWords": True, "language": "en"}, _ctx(jobs))

    assert out == {"jobId": "job-1"}
    handler, kwargs = jobs.calls[0]
    assert kwargs == {"feature": "transcribe", "label": "transcribe.start", "videoId": "v1", "gpu": True}
    # Invoke the job body to prove the alignWords trigger threads through.
    assert handler(_JobCtx()) == {"transcript": {"language": "en", "align": True}}
    assert captured == {"video_id": "v1", "language": "en", "align_words": True}


def test_transcribe_start_align_words_defaults_false(tmp_path: Path) -> None:
    """An absent alignWords param resolves to False (the settings-key path stays)."""
    svc = Services(data_dir=tmp_path / "d")
    svc._resolve_video_path = lambda vid: "/resolved/a.mp4"  # type: ignore[assignment]
    captured: dict[str, Any] = {}

    def fake_persist(video_id: str, job_ctx: Any, *, language: str | None = None, align_words: bool = False):
        captured["align_words"] = align_words
        return {"ok": True}

    svc._transcribe_and_persist = fake_persist  # type: ignore[assignment]
    jobs = _RecordingJobs()

    svc.transcribe_start({"videoId": "v1"}, _ctx(jobs))

    _handler, kwargs = jobs.calls[0]
    assert kwargs["gpu"] is True
    _handler(_JobCtx())
    assert captured["align_words"] is False


# --------------------------------------------------------------------------- #
# _maybe_align_words — dual trigger + cancel short-circuit + callback forward
# (findings 520 & 868)
# --------------------------------------------------------------------------- #
def test_maybe_align_words_noop_when_no_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither align_words nor settings['karaoke'] -> input returned, aligner never runs."""
    from media_studio.features import ctc_align

    calls = {"n": 0}

    def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls["n"] += 1
        return {}

    monkeypatch.setattr(ctc_align, "align_words", _boom)
    svc = Services(data_dir=tmp_path / "d")
    transcript = {"language": "en", "segments": []}
    assert svc._maybe_align_words(transcript, "/x.mp4", {}, _JobCtx()) is transcript
    assert calls["n"] == 0


def test_maybe_align_words_runs_when_align_words_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-job align_words=True trigger forces the 2nd pass (first `or` operand)."""
    from media_studio.features import ctc_align

    seen: dict[str, Any] = {}

    def _fake(transcript: dict[str, Any], audio_path: str, *, settings: Any = None, **_k: Any) -> dict[str, Any]:
        seen["audio"] = audio_path
        seen["settings"] = settings
        return {**transcript, "aligned": True}

    monkeypatch.setattr(ctc_align, "align_words", _fake)
    svc = Services(data_dir=tmp_path / "d")
    out = svc._maybe_align_words({"segments": []}, "/a.wav", {}, _JobCtx(), align_words=True)
    assert out["aligned"] is True
    assert seen["audio"] == "/a.wav"


def test_maybe_align_words_runs_when_karaoke_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings['karaoke'] alone forces the 2nd pass (second `or` operand)."""
    from media_studio.features import ctc_align

    monkeypatch.setattr(ctc_align, "align_words", lambda transcript, audio_path, **_k: {**transcript, "aligned": True})
    svc = Services(data_dir=tmp_path / "d")
    out = svc._maybe_align_words({"segments": []}, "/a.wav", {"karaoke": True}, _JobCtx())
    assert out["aligned"] is True


def test_maybe_align_words_skips_when_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An already-cancelled job never starts CTC alignment (cancel short-circuit)."""
    from media_studio.features import ctc_align

    calls = {"n": 0}

    def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls["n"] += 1
        return {}

    monkeypatch.setattr(ctc_align, "align_words", _boom)
    svc = Services(data_dir=tmp_path / "d")
    transcript = {"segments": []}
    result = svc._maybe_align_words(transcript, "/a.wav", {}, _JobCtx(cancelled=True), align_words=True)
    assert result is transcript
    assert calls["n"] == 0


def test_maybe_align_words_forwards_progress_and_cancel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The job progress/cancel callbacks are forwarded into align_words."""
    from media_studio.features import ctc_align

    caps: dict[str, Any] = {}

    def _fake(
        transcript: dict[str, Any],
        audio_path: str,
        *,
        settings: Any = None,
        on_progress: Any = None,
        should_cancel: Any = None,
    ) -> dict[str, Any]:
        caps["on_progress"] = on_progress
        caps["should_cancel"] = should_cancel
        return transcript

    monkeypatch.setattr(ctc_align, "align_words", _fake)
    svc = Services(data_dir=tmp_path / "d")
    job_ctx = _JobCtx(cancelled=False)
    svc._maybe_align_words({"segments": []}, "/a.wav", {}, job_ctx, align_words=True)

    # The forwarded on_progress lambda drives job_ctx.progress.
    caps["on_progress"](42.0, "aligning")
    assert job_ctx.progress_calls == [(42.0, "aligning")]
    # The forwarded should_cancel lambda reflects job_ctx.cancelled live.
    assert caps["should_cancel"]() is False
    job_ctx.cancelled = True
    assert caps["should_cancel"]() is True


# --------------------------------------------------------------------------- #
# _dub_translator — offline gate + online routing (finding 916)
# --------------------------------------------------------------------------- #
def test_dub_translator_forces_local_pool_when_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline mode forces the dub tier3 pool LOCAL-only (no transcript egress)."""
    from media_studio.models import provider as _pm
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy_get_translator(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None):
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy_get_translator)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "offline": True,
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            "providers": [
                {
                    "id": "cloudy",
                    "provider": "cloudy",
                    "kind": "cloud",
                    "apiKeys": ["k"],
                    "enabled": True,
                    "capabilities": ["text"],
                    "baseUrl": "http://c",
                    "model": "m",
                },
            ],
        }
    )
    svc._dub_translator()
    assert captured["prefer"] == _pm.LOCAL_PROVIDER_ID, "offline dub did not force a local-only pool"


def test_dub_translator_threads_routed_prefer_when_online(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When NOT offline the dub tier3 keeps its per-function routed provider."""
    from media_studio.models import translation as _tm

    captured: dict[str, Any] = {}

    def spy_get_translator(settings: Any, *, runner: Any = None, prefer: Any = None, ensure: Any = None):
        captured["prefer"] = prefer
        return object()

    monkeypatch.setattr(_tm, "get_translator", spy_get_translator)
    svc = Services(data_dir=tmp_path / "d")
    svc.settings.set(
        {
            "routing": {"perFunction": {"translation": {"provider": "cloudy"}}},
            # dub translation now flows through _translator_for_function, which
            # enforces the RoutingPolicy (default 'local') + per-provider TEXT
            # consent that this path used to bypass — so cloud routing needs both
            # granted for the routed provider to survive when online.
            "routingPolicy": {"global": "cloud"},
            "consent": {"perProvider": {"cloudy": {"text": True}}},
            "providers": [
                {
                    "id": "cloudy",
                    "provider": "cloudy",
                    "kind": "cloud",
                    "apiKeys": ["k"],
                    "enabled": True,
                    "capabilities": ["text"],
                    "baseUrl": "http://c",
                    "model": "m",
                },
            ],
        }
    )
    svc._dub_translator()
    assert captured["prefer"] == "cloudy", "online dub dropped the routed tier3 provider"
