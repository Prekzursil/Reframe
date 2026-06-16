"""Unit tests for media_studio.features.transcribe.

faster-whisper is MOCKED at the loader seam: no model is ever downloaded and the
``faster_whisper`` package is never imported. Both the segment/word normalizers
(attribute-objects AND plain dicts), the CPU-fallback policy, progress streaming,
cooperative cancellation, language auto-detect, and the ``transcribe.start`` RPC
wiring are covered without any heavy-ML import.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from media_studio import protocol
from media_studio.features import transcribe
from media_studio.jobs import JobRegistry
from media_studio.protocol import RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class _Word:
    def __init__(self, word: str, start: float, end: float):
        self.word = word
        self.start = start
        self.end = end


class _Segment:
    def __init__(self, start: float, end: float, text: str, words):
        self.start = start
        self.end = end
        self.text = text
        self.words = words


class _Info:
    def __init__(self, language: str, duration: float):
        self.language = language
        self.duration = duration


class FakeModel:
    """A stand-in WhisperModel recording its transcribe kwargs."""

    def __init__(self, segments, info: _Info):
        self._segments = segments
        self._info = info
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: str, **kwargs: Any):
        self.calls.append({"audio": audio, **kwargs})
        # Return a *generator* to mirror faster-whisper's lazy behaviour.
        return (s for s in self._segments), self._info


class FakeLoader:
    """A loader seam that hands back preconfigured models per call.

    ``fail_on`` is a set of devices whose ``load`` raises (to drive the
    CPU-fallback path). Records every (model, device, compute_type) requested.
    """

    def __init__(self, model: FakeModel, *, fail_on: set | None = None):
        self._model = model
        self.fail_on = fail_on or set()
        self.loads: list[tuple[str, str, str]] = []

    def load(self, model: str, device: str, compute_type: str):
        self.loads.append((model, device, compute_type))
        if device in self.fail_on:
            raise RuntimeError(f"no {device} runtime")
        return self._model


def _two_segment_model(language: str = "en", duration: float = 10.0) -> FakeModel:
    seg1 = _Segment(0.0, 2.0, " Hello world", [_Word(" Hello", 0.0, 1.0), _Word(" world", 1.0, 2.0)])
    seg2 = _Segment(2.0, 5.0, " second part", [_Word(" second", 2.0, 3.5), _Word(" part", 3.5, 5.0)])
    return FakeModel([seg1, seg2], _Info(language, duration))


# --------------------------------------------------------------------------- #
# transcribe_file: schema shape
# --------------------------------------------------------------------------- #
def test_transcribe_file_produces_transcript_schema():
    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_file("/a b/v.mp4", loader=loader)

    # Top-level Transcript fields (CONTRACTS.md §3) and nothing else.
    assert set(t.keys()) == {"language", "segments", "durationSec"}
    assert t["language"] == "en"
    assert t["durationSec"] == pytest.approx(10.0)
    assert len(t["segments"]) == 2


def test_transcribe_file_segment_and_word_fields_exact():
    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_file("/v.mp4", loader=loader)

    seg = t["segments"][0]
    assert set(seg.keys()) == {"start", "end", "text", "words"}
    assert seg["start"] == pytest.approx(0.0)
    assert seg["end"] == pytest.approx(2.0)
    assert seg["text"] == " Hello world"

    word = seg["words"][0]
    assert set(word.keys()) == {"text", "start", "end"}
    # faster-whisper's ``word`` field is mapped to ``text`` verbatim (leading space kept)
    assert word["text"] == " Hello"
    assert word["start"] == pytest.approx(0.0)
    assert word["end"] == pytest.approx(1.0)


def test_transcribe_file_word_timings_present_for_all_segments():
    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_file("/v.mp4", loader=loader)
    all_words = [w for s in t["segments"] for w in s["words"]]
    assert len(all_words) == 4
    assert [w["text"] for w in all_words] == [" Hello", " world", " second", " part"]


def test_transcribe_file_requests_word_timestamps():
    model = _two_segment_model()
    loader = FakeLoader(model)
    transcribe.transcribe_file("/v.mp4", loader=loader)
    assert model.calls[0]["word_timestamps"] is True
    assert model.calls[0]["audio"] == "/v.mp4"


# --------------------------------------------------------------------------- #
# language auto-detect vs explicit
# --------------------------------------------------------------------------- #
def test_language_auto_detected_when_none_passed():
    loader = FakeLoader(_two_segment_model(language="fr"))
    t = transcribe.transcribe_file("/v.mp4", loader=loader, language=None)
    # None is forwarded to faster-whisper (which auto-detects) ...
    assert loader._model.calls[0]["language"] is None
    # ... and the detected language is surfaced.
    assert t["language"] == "fr"


def test_explicit_language_forwarded_to_model():
    loader = FakeLoader(_two_segment_model(language="de"))
    transcribe.transcribe_file("/v.mp4", loader=loader, language="de")
    assert loader._model.calls[0]["language"] == "de"


def test_language_falls_back_to_requested_when_info_missing():
    # info with empty language -> use the explicitly requested code rather than ""
    model = FakeModel([], _Info("", 3.0))
    loader = FakeLoader(model)
    t = transcribe.transcribe_file("/v.mp4", loader=loader, language="es")
    assert t["language"] == "es"


# --------------------------------------------------------------------------- #
# dict-shaped segments/words (normalizer tolerance)
# --------------------------------------------------------------------------- #
def test_normalizer_accepts_dict_shaped_segments_and_words():
    seg = {
        "start": 1.0,
        "end": 4.0,
        "text": "dict seg",
        "words": [{"text": "dict", "start": 1.0, "end": 2.0}],
    }
    model = FakeModel([seg], _Info("en", 4.0))
    loader = FakeLoader(model)
    t = transcribe.transcribe_file("/v.mp4", loader=loader)
    out = t["segments"][0]
    assert out["text"] == "dict seg"
    assert out["words"][0] == {"text": "dict", "start": pytest.approx(1.0), "end": pytest.approx(2.0)}


def test_normalizer_defaults_missing_word_and_segment_fields():
    # A segment object missing words / a word object missing fields -> graceful defaults.
    seg = _Segment(0.0, 1.0, "", [_Word("", 0.0, 0.0)])
    seg.words = [object()]  # an object with no word/start/end attrs at all
    model = FakeModel([seg], _Info("en", 1.0))
    loader = FakeLoader(model)
    t = transcribe.transcribe_file("/v.mp4", loader=loader)
    w = t["segments"][0]["words"][0]
    assert w == {"text": "", "start": 0.0, "end": 0.0}


# --------------------------------------------------------------------------- #
# CPU fallback
# --------------------------------------------------------------------------- #
def test_cpu_fallback_on_gpu_load_failure():
    model = _two_segment_model()
    loader = FakeLoader(model, fail_on={"cuda"})
    inst, device = transcribe.load_model_with_cpu_fallback(loader)
    assert device == transcribe.CPU_DEVICE
    # first tried cuda/float16, then cpu/int8
    assert loader.loads[0] == (transcribe.DEFAULT_MODEL, "cuda", "float16")
    assert loader.loads[1] == (transcribe.DEFAULT_MODEL, "cpu", "int8")
    assert inst is model


def test_no_fallback_when_gpu_succeeds():
    model = _two_segment_model()
    loader = FakeLoader(model)
    inst, device = transcribe.load_model_with_cpu_fallback(loader)
    assert device == "cuda"
    assert loader.loads == [(transcribe.DEFAULT_MODEL, "cuda", "float16")]
    assert inst is model


def test_cpu_failure_is_hard_error_no_further_fallback():
    model = _two_segment_model()
    loader = FakeLoader(model, fail_on={"cpu"})
    with pytest.raises(RuntimeError):
        transcribe.load_model_with_cpu_fallback(
            loader, device=transcribe.CPU_DEVICE, compute_type=transcribe.CPU_COMPUTE
        )


def test_transcribe_file_uses_cpu_fallback_end_to_end():
    model = _two_segment_model()
    loader = FakeLoader(model, fail_on={"cuda"})
    t = transcribe.transcribe_file("/v.mp4", loader=loader)
    # produced a transcript despite the GPU load failing
    assert len(t["segments"]) == 2
    assert ("cuda" in [d for (_, d, _) in loader.loads]) and ("cpu" in [d for (_, d, _) in loader.loads])


# --------------------------------------------------------------------------- #
# progress streaming
# --------------------------------------------------------------------------- #
def test_progress_is_monotonic_and_ends_at_100():
    loader = FakeLoader(_two_segment_model(duration=10.0))
    events: list[tuple[float, str]] = []
    transcribe.transcribe_file("/v.mp4", loader=loader, on_progress=lambda p, m: events.append((p, m)))
    pcts = [p for p, _ in events]
    # starts at 0, mid values reflect segment.end/duration, final is 100
    assert pcts[0] == 0.0
    assert pcts[-1] == 100.0
    assert pcts == sorted(pcts)  # non-decreasing
    # seg1 end=2.0/10 -> 20, seg2 end=5.0/10 -> 50
    assert 20.0 in pcts and 50.0 in pcts


def test_progress_capped_below_100_until_done():
    # A segment ending exactly at duration must not report 100 mid-stream (kept <=99).
    seg = _Segment(0.0, 10.0, "whole", [])
    model = FakeModel([seg], _Info("en", 10.0))
    loader = FakeLoader(model)
    mid: list[float] = []
    transcribe.transcribe_file("/v.mp4", loader=loader, on_progress=lambda p, m: mid.append(p))
    # last is the explicit 100 "done"; everything before it stays <=99
    assert mid[-1] == 100.0
    assert all(p <= 99.0 for p in mid[:-1])


def test_progress_skipped_when_duration_unknown():
    # duration 0 -> only the 0 start and 100 done bookends, no division-by-zero.
    model = _two_segment_model(duration=0.0)
    loader = FakeLoader(model)
    pcts: list[float] = []
    transcribe.transcribe_file("/v.mp4", loader=loader, on_progress=lambda p, m: pcts.append(p))
    assert pcts == [0.0, 100.0]


def test_no_progress_callback_is_fine():
    loader = FakeLoader(_two_segment_model())
    # Should not raise when on_progress is None.
    t = transcribe.transcribe_file("/v.mp4", loader=loader, on_progress=None)
    assert t["durationSec"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# cooperative cancellation
# --------------------------------------------------------------------------- #
def test_should_cancel_stops_consuming_segments():
    # Cancel before the first segment -> zero segments collected.
    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_file("/v.mp4", loader=loader, should_cancel=lambda: True)
    assert t["segments"] == []
    # language/duration still populated from info
    assert t["language"] == "en"


def test_cancel_after_first_segment():
    state = {"n": 0}

    def cancel() -> bool:
        # allow the first segment, cancel before the second
        state["n"] += 1
        return state["n"] > 1

    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_file("/v.mp4", loader=loader, should_cancel=cancel)
    assert len(t["segments"]) == 1


# --------------------------------------------------------------------------- #
# RPC handler: transcribe.start (long-job shape)
# --------------------------------------------------------------------------- #
def _registry_with_recorder():
    collected: list[tuple[str, tuple]] = []

    def emit_progress(job_id: str, pct: int, message: str) -> None:
        collected.append(("progress", (job_id, pct, message)))

    def emit_done(job_id: str, result: Any) -> None:
        collected.append(("done", (job_id, result)))

    return JobRegistry(emit_progress=emit_progress, emit_done=emit_done), collected


def _ctx_for(registry: JobRegistry) -> RpcContext:
    notes: list[dict[str, Any]] = []
    ctx = RpcContext(emit_notification=lambda obj: notes.append(obj), jobs=registry)
    ctx._notes = notes  # type: ignore[attr-defined]
    return ctx


def test_handler_returns_jobid_immediately_and_streams_done():
    registry, collected = _registry_with_recorder()
    ctx = _ctx_for(registry)
    loader = FakeLoader(_two_segment_model())
    handler = transcribe.make_transcribe_handler(lambda vid: "/media/v.mp4" if vid == "v1" else None, loader=loader)

    out = handler({"videoId": "v1"}, ctx)
    assert set(out.keys()) == {"jobId"}
    job = registry.get(out["jobId"])
    assert job is not None
    assert job.wait(timeout=5.0)

    # job.done.result == {transcript} (§2)
    dones = [payload for kind, payload in collected if kind == "done"]
    assert len(dones) == 1
    done_job_id, result = dones[0]
    assert done_job_id == out["jobId"]
    assert set(result.keys()) == {"transcript"}
    assert result["transcript"]["language"] == "en"
    assert len(result["transcript"]["segments"]) == 2


def test_handler_streams_progress_notifications():
    registry, collected = _registry_with_recorder()
    ctx = _ctx_for(registry)
    loader = FakeLoader(_two_segment_model(duration=10.0))
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=loader)

    out = handler({"videoId": "v1"}, ctx)
    registry.get(out["jobId"]).wait(timeout=5.0)
    progresses = [payload for kind, payload in collected if kind == "progress"]
    assert progresses, "expected at least one progress notification"
    # pct is an int (clamped by the registry/jobs layer) and ends at 100
    assert progresses[-1][1] == 100


def test_handler_passes_language_through():
    registry, _ = _registry_with_recorder()
    ctx = _ctx_for(registry)
    model = _two_segment_model(language="it")
    loader = FakeLoader(model)
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=loader)
    out = handler({"videoId": "v1", "language": "it"}, ctx)
    registry.get(out["jobId"]).wait(timeout=5.0)
    assert model.calls[0]["language"] == "it"


def test_handler_marks_transcribed_hook_called():
    registry, _ = _registry_with_recorder()
    ctx = _ctx_for(registry)
    loader = FakeLoader(_two_segment_model())
    marked: list[str] = []
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=loader, on_transcribed=marked.append)
    out = handler({"videoId": "v1"}, ctx)
    registry.get(out["jobId"]).wait(timeout=5.0)
    assert marked == ["v1"]


def test_handler_transcribed_hook_failure_does_not_fail_job():
    registry, collected = _registry_with_recorder()
    ctx = _ctx_for(registry)
    loader = FakeLoader(_two_segment_model())

    def boom(_vid: str) -> None:
        raise RuntimeError("bookkeeping blew up")

    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=loader, on_transcribed=boom)
    out = handler({"videoId": "v1"}, ctx)
    job = registry.get(out["jobId"])
    job.wait(timeout=5.0)
    # job still completes (done emitted), the hook error is swallowed
    assert job.status.value == "done"
    assert any(kind == "done" for kind, _ in collected)


def test_handler_rejects_missing_video_id():
    registry, _ = _registry_with_recorder()
    ctx = _ctx_for(registry)
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))
    with pytest.raises(RpcError):
        handler({}, ctx)
    with pytest.raises(RpcError):
        handler({"videoId": 123}, ctx)


def test_handler_rejects_non_string_language():
    registry, _ = _registry_with_recorder()
    ctx = _ctx_for(registry)
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))
    with pytest.raises(RpcError):
        handler({"videoId": "v1", "language": 7}, ctx)


def test_handler_rejects_unknown_video():
    registry, _ = _registry_with_recorder()
    ctx = _ctx_for(registry)
    handler = transcribe.make_transcribe_handler(lambda vid: None, loader=FakeLoader(_two_segment_model()))
    with pytest.raises(RpcError):
        handler({"videoId": "ghost"}, ctx)


def test_handler_requires_job_registry():
    ctx = RpcContext(emit_notification=lambda obj: None, jobs=None)
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))
    with pytest.raises(RpcError):
        handler({"videoId": "v1"}, ctx)


def test_handler_cancel_stops_job():
    registry, collected = _registry_with_recorder()
    ctx = _ctx_for(registry)

    # A model whose generator blocks until we let it proceed, so we can cancel mid-run.
    gate = threading.Event()

    class BlockingModel:
        calls: list[dict[str, Any]] = []

        def transcribe(self, audio: str, **kwargs: Any):
            self.calls.append({"audio": audio, **kwargs})

            def gen():
                for i in range(3):
                    gate.wait(timeout=5.0)
                    yield _Segment(float(i), float(i + 1), f"s{i}", [])

            return gen(), _Info("en", 3.0)

    loader = FakeLoader(BlockingModel())  # type: ignore[arg-type]
    handler = transcribe.make_transcribe_handler(lambda vid: "/m/v.mp4", loader=loader)
    out = handler({"videoId": "v1"}, ctx)
    job_id = out["jobId"]
    registry.cancel(job_id)
    gate.set()  # release the generator; the cancel check should stop consumption
    registry.get(job_id).wait(timeout=5.0)
    job = registry.get(job_id)
    # cancellation is observed cooperatively -> CANCELLED, not ERROR
    assert job.status.value == "cancelled"


# --------------------------------------------------------------------------- #
# register(): installs transcribe.start on the global METHODS table
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _restore_methods():
    saved = dict(protocol.METHODS)
    try:
        yield
    finally:
        protocol.METHODS.clear()
        protocol.METHODS.update(saved)


def test_register_installs_transcribe_start():
    assert "transcribe.start" not in protocol.METHODS
    transcribe.register(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))
    assert "transcribe.start" in protocol.METHODS
    # the registered method is dispatchable through the protocol layer
    registry, collected = _registry_with_recorder()
    ctx = _ctx_for(registry)
    result = protocol.METHODS["transcribe.start"]({"videoId": "v1"}, ctx)
    assert "jobId" in result
    registry.get(result["jobId"]).wait(timeout=5.0)
    assert any(kind == "done" for kind, _ in collected)


def test_register_duplicate_raises():
    transcribe.register(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))
    with pytest.raises(ValueError):
        transcribe.register(lambda vid: "/m/v.mp4", loader=FakeLoader(_two_segment_model()))


# --------------------------------------------------------------------------- #
# FasterWhisperLoader — the DEFAULT (production) loader seam
#
# The heavy ``faster_whisper`` import lives INSIDE FasterWhisperLoader.load(); we
# stub the module in sys.modules so .load() builds a fake model (no download), and
# assert the per-key cache + release() behaviour without any real model.
# --------------------------------------------------------------------------- #
import sys  # noqa: E402
import types  # noqa: E402


class _FakeFasterWhisperModel:
    """Records the ctor args the loader passes through to WhisperModel(...)."""

    instances: list[tuple[str, str, str]] = []

    def __init__(self, model: str, *, device: str, compute_type: str):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        _FakeFasterWhisperModel.instances.append((model, device, compute_type))


@pytest.fixture()
def _stub_faster_whisper(monkeypatch):
    """Install a fake ``faster_whisper`` module so .load() never downloads."""
    _FakeFasterWhisperModel.instances = []
    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = _FakeFasterWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
    # Don't let the Windows CUDA-DLL hook fire on real sys.path during this test.
    monkeypatch.setattr(transcribe, "_register_cuda_dll_dirs", lambda: None)
    return fake_mod


def test_faster_whisper_loader_builds_and_caches(_stub_faster_whisper):
    loader = transcribe.FasterWhisperLoader()
    m1 = loader.load("large-v3-turbo", "cuda", "float16")
    assert isinstance(m1, _FakeFasterWhisperModel)
    assert (m1.model, m1.device, m1.compute_type) == ("large-v3-turbo", "cuda", "float16")
    # Second call with the SAME key returns the cached instance (no rebuild).
    m2 = loader.load("large-v3-turbo", "cuda", "float16")
    assert m2 is m1
    assert len(_FakeFasterWhisperModel.instances) == 1


def test_faster_whisper_loader_distinct_keys_build_separate_models(_stub_faster_whisper):
    loader = transcribe.FasterWhisperLoader()
    cuda = loader.load("large-v3-turbo", "cuda", "float16")
    cpu = loader.load("large-v3-turbo", "cpu", "int8")
    assert cuda is not cpu
    assert len(_FakeFasterWhisperModel.instances) == 2


def test_faster_whisper_loader_release_drops_cache(_stub_faster_whisper):
    loader = transcribe.FasterWhisperLoader()
    first = loader.load("large-v3-turbo", "cuda", "float16")
    loader.release()
    # After release the next load rebuilds (a fresh instance is constructed).
    rebuilt = loader.load("large-v3-turbo", "cuda", "float16")
    assert rebuilt is not first
    assert len(_FakeFasterWhisperModel.instances) == 2


# --------------------------------------------------------------------------- #
# _register_cuda_dll_dirs — the Windows pip-wheel CUDA DLL hook
# --------------------------------------------------------------------------- #
def test_register_cuda_dll_dirs_noop_off_windows(monkeypatch):
    monkeypatch.setattr(transcribe, "_cuda_dirs_registered", False)
    monkeypatch.setattr(transcribe.sys, "platform", "linux")
    called: list[str] = []
    monkeypatch.setattr(transcribe.os, "add_dll_directory", lambda d: called.append(d), raising=False)
    transcribe._register_cuda_dll_dirs()
    assert called == []  # off-Windows: hook is a no-op


def test_register_cuda_dll_dirs_registers_wheel_bin_dirs(monkeypatch, tmp_path):
    # A fake site-packages with an nvidia/<pkg>/bin layout the wheels create.
    sp = tmp_path / "site-packages"
    cublas_bin = sp / "nvidia" / "cublas" / "bin"
    cudnn_bin = sp / "nvidia" / "cudnn" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)

    monkeypatch.setattr(transcribe, "_cuda_dirs_registered", False)
    monkeypatch.setattr(transcribe.sys, "platform", "win32")
    monkeypatch.setattr(transcribe.sys, "path", [str(sp), str(tmp_path / "no-nvidia-here")])

    added: list[str] = []
    monkeypatch.setattr(transcribe.os, "add_dll_directory", lambda d: added.append(d), raising=False)
    monkeypatch.setattr(transcribe.os, "environ", {"PATH": "existing"})

    transcribe._register_cuda_dll_dirs()
    assert str(cublas_bin) in added
    assert str(cudnn_bin) in added
    # PATH was prepended with the bin dirs.
    assert "bin" in transcribe.os.environ["PATH"]


def test_register_cuda_dll_dirs_is_idempotent(monkeypatch, tmp_path):
    sp = tmp_path / "sp"
    (sp / "nvidia" / "cublas" / "bin").mkdir(parents=True)
    monkeypatch.setattr(transcribe, "_cuda_dirs_registered", True)  # already done
    monkeypatch.setattr(transcribe.sys, "platform", "win32")
    monkeypatch.setattr(transcribe.sys, "path", [str(sp)])
    added: list[str] = []
    monkeypatch.setattr(transcribe.os, "add_dll_directory", lambda d: added.append(d), raising=False)
    transcribe._register_cuda_dll_dirs()
    assert added == []  # the registered flag short-circuits


# --------------------------------------------------------------------------- #
# ASR-engine selection (WU7 wiring): whisper (default) | parakeet
# --------------------------------------------------------------------------- #
def test_selected_asr_engine_defaults_to_whisper():
    assert transcribe.selected_asr_engine(None) == transcribe.WHISPER_ENGINE
    assert transcribe.selected_asr_engine({}) == transcribe.WHISPER_ENGINE
    # unknown / non-str values fall back to the safe default
    assert transcribe.selected_asr_engine({"asrEngine": "whisperx"}) == transcribe.WHISPER_ENGINE
    assert transcribe.selected_asr_engine({"asrEngine": 1}) == transcribe.WHISPER_ENGINE


def test_selected_asr_engine_picks_parakeet_case_insensitive():
    assert transcribe.selected_asr_engine({"asrEngine": "parakeet"}) == transcribe.PARAKEET_ENGINE
    assert transcribe.selected_asr_engine({"asrEngine": "  Parakeet "}) == transcribe.PARAKEET_ENGINE


def test_transcribe_with_engine_default_uses_whisper():
    loader = FakeLoader(_two_segment_model())
    t = transcribe.transcribe_with_engine("/v.mp4", loader=loader, settings={})
    assert t["language"] == "en"
    assert len(t["segments"]) == 2
    # the parakeet seam was never touched (whisper loader did the work)
    assert loader.loads


def test_transcribe_with_engine_parakeet_runner_selected():
    loader = FakeLoader(_two_segment_model())
    calls: list[dict[str, Any]] = []

    def fake_parakeet(audio_path: str, **kwargs: Any):
        calls.append({"audio": audio_path, **kwargs})
        return {
            "language": "ro",
            "segments": [{"start": 0.0, "end": 1.0, "text": "salut", "words": []}],
            "durationSec": 1.0,
        }

    t = transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=loader,
        settings={"asrEngine": "parakeet"},
        language="ro",
        duration=42.0,
        parakeet_runner=fake_parakeet,
    )
    assert t["language"] == "ro"
    assert t["segments"][0]["text"] == "salut"
    # the whisper loader was NOT consulted (parakeet handled it)
    assert loader.loads == []
    # the duration was forwarded so parakeet can chunk
    assert calls[0]["duration"] == 42.0
    assert calls[0]["language"] == "ro"


def test_transcribe_with_engine_parakeet_empty_falls_back_to_whisper():
    loader = FakeLoader(_two_segment_model())

    def empty_parakeet(audio_path: str, **kwargs: Any):
        # parakeet degraded (offline + weights missing) -> empty transcript
        return {"language": "", "segments": [], "durationSec": 0.0}

    t = transcribe.transcribe_with_engine(
        "/v.mp4",
        loader=loader,
        settings={"asrEngine": "parakeet"},
        parakeet_runner=empty_parakeet,
    )
    # fell back to whisper -> non-empty transcript
    assert len(t["segments"]) == 2
    assert loader.loads, "whisper fallback should have loaded a model"


def test_default_parakeet_runner_delegates_to_real_module(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_transcribe_file(audio_path: str, **kwargs: Any):
        captured["audio"] = audio_path
        captured.update(kwargs)
        return {"language": "ro", "segments": [], "durationSec": 0.0}

    from media_studio.features import parakeet_asr

    monkeypatch.setattr(parakeet_asr, "transcribe_file", fake_transcribe_file)
    out = transcribe._default_parakeet_runner("/clip.mp4", language="ro")
    assert out["language"] == "ro"
    assert captured["audio"] == "/clip.mp4"
    assert captured["language"] == "ro"
