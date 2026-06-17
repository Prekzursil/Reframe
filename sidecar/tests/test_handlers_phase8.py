"""Tests for the Phase-8 handler wiring (system.* + asr.engines + phase8.*).

Heavy-ML-free: the HardwareProbe and the signal-compute runner are injected as
fakes (no GPU, no torch, no cv2). Direct handlers return their wire dicts; the
job handlers run on a real JobRegistry and their ``job.done.result`` is asserted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.handlers import Services
from media_studio.jobs import JobRegistry
from media_studio.protocol import ErrorCode, RpcContext, RpcError


# --------------------------------------------------------------------------- #
# fakes / seams (no heavy imports, no subprocess, no network)
# --------------------------------------------------------------------------- #
def fake_run(argv: Any, **kwargs: Any) -> int:
    return 0


def fake_probe(path: str) -> float:
    return 12.0


class FakeWhisperModel:
    def transcribe(self, audio: str, **kwargs: Any) -> Any:
        seg = {
            "start": 0.0,
            "end": 2.0,
            "text": "Hello world.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": "world.", "start": 1.0, "end": 2.0},
            ],
        }
        info = {"duration": 2.0, "language": "en"}
        return iter([seg]), info


class FakeWhisperLoader:
    def load(self, model: str, device: str, compute_type: str) -> FakeWhisperModel:
        return FakeWhisperModel()


class FakeProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:
        # never reached by the silent-path tests; present so select() has a provider.
        return "[]"

    def exemplar_block(self, language: str | None = None) -> str | None:
        return None

    def calibrated_pct(self, raw: float) -> int | None:
        return None


class _FakeHardwareProbe:
    """A HardwareProbe-shaped seam returning a fixed HardwareInfo (no GPU deps)."""

    def __init__(
        self,
        vram_mb: int | None = 6000,
        ram_mb: int | None = 16000,
        cpu_count: int | None = 8,
    ) -> None:
        from media_studio.features.system_advisor import HardwareInfo

        self._info = HardwareInfo(
            vram_mb=vram_mb,
            ram_mb=ram_mb,
            cpu_count=cpu_count,
            gpu_present=vram_mb is not None,
        )

    def detect(self) -> Any:
        return self._info


def _signal_track(channel: str, *, present: bool, n: int = 0) -> Any:
    """A duck-typed SignalTrack: ``.channel`` / ``.signals`` / ``.present``."""
    sig = type("S", (), {"start": 0.0, "end": 1.0, "value": 0.5})
    return type(
        "T",
        (),
        {"channel": channel, "present": present, "signals": tuple(sig() for _ in range(n))},
    )()


def _fake_runner(
    path: str,
    *,
    tier: int,
    settings: dict[str, Any],
    duration_probe: Any,
    **kw: Any,
) -> dict[str, Any]:
    """A phase8 runner that exercises the progress/cancel seams + returns tracks."""
    on_progress = kw.get("on_progress")
    if on_progress is not None:
        on_progress(50.0, "running")
    should_cancel = kw.get("should_cancel")
    if should_cancel is not None:
        should_cancel()
    tracks: dict[str, Any] = {"motion": _signal_track("motion", present=True, n=3)}
    if tier >= 1:
        tracks["saliency"] = _signal_track("saliency", present=False, n=0)
    return tracks


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "talk.mp4"
    p.write_bytes(b"\x00fake")
    return p


def _phase8_services(tmp_path: Path, **over: Any) -> Services:
    """A Services wired with the Phase-8 fakes (probe + runner) over a tmp dir."""
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "whisper_loader": FakeWhisperLoader(),
        "ffmpeg_run": fake_run,
        "ffprobe_duration": fake_probe,
        "silence_run": lambda argv, **k: type("C", (), {"stderr": "", "returncode": 0})(),
        "scene_detector": lambda p: [],
        "provider": FakeProvider(),
        "hardware_probe": _FakeHardwareProbe(),
        "phase8_runner": _fake_runner,
    }
    base.update(over)
    return Services(**base)


def _phase8_ctx() -> RpcContext:
    events: list[Any] = []
    jobs = JobRegistry(
        emit_progress=lambda jid, pct, msg: events.append(("progress", jid, pct, msg)),
        emit_done=lambda jid, result: events.append(("done", jid, result)),
    )
    context = RpcContext(emit_notification=lambda obj: None, jobs=jobs)
    context.events = events  # type: ignore[attr-defined]
    return context


def _add_video(services: Services, video_file: Path) -> str:
    from media_studio import library as _library

    services.library = _library.Library(services.data_dir / "library.json", probe_duration=lambda _p: 12.0)
    video = services.library.add(str(video_file))
    return video["id"]


def _transcribe_sync(services: Services, ctx: RpcContext, vid: str) -> None:
    services.transcribe_start({"videoId": vid}, ctx)
    ctx.jobs.join(timeout=5)


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #
def test_register_all_wires_phase8_methods(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    for method in ("system.probe", "system.advisor", "asr.engines", "phase8.signals", "phase8.select"):
        assert method in registered, f"{method} was not registered"


# --------------------------------------------------------------------------- #
# system.probe / system.advisor / asr.engines (direct)
# --------------------------------------------------------------------------- #
def test_system_probe_returns_hardware_info(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = svc.system_probe({}, direct)
    assert out == {"vramMb": 6000, "ramMb": 16000, "cpuCount": 8, "gpuPresent": True}


def test_system_advisor_returns_wire_report(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = svc.system_advisor({}, direct)
    assert {"components", "tiers", "recommendedPreset", "vramBudgetMb", "notes"} <= set(out)
    assert out["vramBudgetMb"] == 6000
    names = {c["name"] for c in out["components"]}
    assert {"motion", "saliency", "smolvlm2"} <= names
    a_component = out["components"][0]
    assert {"name", "present", "verdict", "vramMb", "licenseCommercialOk", "reason"} == set(a_component)
    assert all({"tier", "label", "verdict", "components"} == set(t) for t in out["tiers"])


def test_system_advisor_commercial_flag_drops_noncommercial(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = svc.system_advisor({"commercial": True}, direct)
    by_name = {c["name"]: c for c in out["components"]}
    # ViNet-S saliency is CC-BY-NC-SA -> unavailable for a commercial build.
    assert by_name["saliency"]["verdict"] == "unavailable"
    assert by_name["saliency"]["licenseCommercialOk"] is False


def test_asr_engines_lists_whisper_and_parakeet(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = svc.asr_engines({}, direct)
    ids = {e["id"] for e in out["engines"]}
    assert ids == {"whisper", "parakeet"}
    whisper = next(e for e in out["engines"] if e["id"] == "whisper")
    parakeet = next(e for e in out["engines"] if e["id"] == "parakeet")
    assert whisper["installed"] is True
    assert parakeet["installed"] is False  # weights not installed in the tmp dir


# --------------------------------------------------------------------------- #
# phase8.signals / phase8.select (jobs)
# --------------------------------------------------------------------------- #
def test_phase8_signals_runs_job_and_summarizes(tmp_path: Path, video_file: Path) -> None:
    svc = _phase8_services(tmp_path)
    ctx = _phase8_ctx()
    vid = _add_video(svc, video_file)
    out = svc.phase8_signals({"videoId": vid, "tier": 1}, ctx)
    assert "jobId" in out
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    result = done[-1][2]
    assert result == {
        "tracks": {"motion": 3, "saliency": 0},
        "present": {"motion": True, "saliency": False},
    }


def test_phase8_signals_requires_known_video(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    ctx = _phase8_ctx()
    with pytest.raises(RpcError) as ei:
        svc.phase8_signals({"videoId": "nope"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_phase8_signals_requires_jobs(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    nojobs = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        svc.phase8_signals({"videoId": "x"}, nojobs)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


def test_phase8_select_runs_job_and_caches(tmp_path: Path, video_file: Path) -> None:
    svc = _phase8_services(tmp_path)
    ctx = _phase8_ctx()
    vid = _add_video(svc, video_file)
    _transcribe_sync(svc, ctx, vid)
    out = svc.phase8_select({"videoId": vid, "prompt": "best", "controls": {}, "tier": 2}, ctx)
    assert "jobId" in out
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    result = done[-1][2]
    assert "candidates" in result
    assert vid in svc._selection_cache  # cached for a later shortmaker.export


def test_phase8_select_requires_known_video(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    ctx = _phase8_ctx()
    with pytest.raises(RpcError) as ei:
        svc.phase8_select({"videoId": "nope"}, ctx)
    assert ei.value.code == ErrorCode.INVALID_PARAMS


def test_phase8_select_requires_jobs(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path)
    nojobs = RpcContext(emit_notification=lambda obj: None, jobs=None)
    with pytest.raises(RpcError) as ei:
        svc.phase8_select({"videoId": "x"}, nojobs)
    assert ei.value.code == ErrorCode.INTERNAL_ERROR


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_coerce_tier_clamps_and_defaults() -> None:
    assert handlers._coerce_tier(0, {}) == 0
    assert handlers._coerce_tier(2, {}) == 2
    assert handlers._coerce_tier(99, {}) == 2  # clamp high
    assert handlers._coerce_tier(-5, {}) == 0  # clamp low
    assert handlers._coerce_tier("bad", {}) == 1  # non-int -> default
    assert handlers._coerce_tier(None, {"phase8Tier": 2}) == 2  # settings fallback
    assert handlers._coerce_tier(None, {}) == 1  # ultimate default


def test_default_phase8_runner_is_the_module_runner(tmp_path: Path) -> None:
    svc = Services(data_dir=tmp_path / "d")
    assert svc._default_phase8_runner() is handlers._run_phase8_signals


def test_models_present_map_omits_missing_and_fails_open(tmp_path: Path, monkeypatch: Any) -> None:
    svc = _phase8_services(tmp_path)
    from media_studio.assets import manifest as _manifest

    real_get = _manifest.get_asset

    def fake_get(name: str) -> Any:
        if name == "vinet-s-saliency":
            return None  # missing entry -> component omitted (the `continue` arc)
        return real_get(name)

    monkeypatch.setattr("media_studio.assets.manifest.get_asset", fake_get)
    out = svc._models_present_map(svc.settings.get())
    assert "saliency" not in out  # omitted (no entry)
    assert out.get("smolvlm2") is False  # present-but-not-installed in the tmp dir


def test_models_present_map_fail_open_on_probe_error(tmp_path: Path, monkeypatch: Any) -> None:
    svc = _phase8_services(tmp_path)

    def boom(self: Any, entry: Any) -> Any:
        raise RuntimeError("probe blew up")

    monkeypatch.setattr("media_studio.assets.manager.AssetManager.installed_path", boom)
    out = svc._models_present_map(svc.settings.get())
    # every model-backed component degrades to False rather than raising.
    assert out and all(v is False for v in out.values())
