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
        # An explicit empty clips object = a GENUINE empty selection (the text
        # path proposes nothing, so these tests exercise the vision/egress path).
        # NOTE: a bare "[]" would now be a PARSE FAILURE (no JSON clips object,
        # F1) and raise SelectionParseError — use the valid empty-clips object.
        return '{"clips": []}'

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
        disk_free_mb: int | None = 200000,
    ) -> None:
        from media_studio.features.system_advisor import HardwareInfo

        self._info = HardwareInfo(
            vram_mb=vram_mb,
            ram_mb=ram_mb,
            cpu_count=cpu_count,
            gpu_present=vram_mb is not None,
            disk_free_mb=disk_free_mb,
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
    assert out == {
        "vramMb": 6000,
        "ramMb": 16000,
        "cpuCount": 8,
        "gpuPresent": True,
        "diskFreeMb": 200000,
    }


# --------------------------------------------------------------------------- #
# models.runners (WU-models/device) — device-ranked local-model plan + runner advice
# --------------------------------------------------------------------------- #
def test_models_runners_composes_device_plan(tmp_path: Path) -> None:
    # A detected Ollama server + a known device -> device-ranked whisper/LLM picks
    # and per-runner advice (Ollama present, LM Studio absent with install link).
    detected = [{"kind": "ollama", "model": "qwen2.5:7b", "base_url": "http://127.0.0.1:11434/v1"}]
    svc = _phase8_services(tmp_path, local_detector=lambda _s: detected)
    direct = RpcContext(emit_notification=lambda obj: None, jobs=None)
    out = svc.models_runners({}, direct)
    assert out["whisper"]["model"] == "large-v3-turbo"  # 6000MB GPU fits turbo
    assert out["llm"]["model"] == "qwen2.5:7b"  # 6000MB GPU fits 7b
    by_kind = {r["kind"]: r for r in out["runners"]}
    assert by_kind["ollama"]["present"] is True
    assert by_kind["ollama"]["installedModels"] == ["qwen2.5:7b"]
    assert by_kind["lmstudio"]["present"] is False
    assert "https://lmstudio.ai" in by_kind["lmstudio"]["installHint"]


def test_models_runners_registered(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "models.runners" in registered


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


# --------------------------------------------------------------------------- #
# phase8.select WU-vision wiring — frame-egress consent gate + cloud/local/off
# vlm_reranker resolution. A FAKE vision transport (the rotation pool's HTTP seam)
# proves frames egress ONLY with consent. No real model / no network.
# --------------------------------------------------------------------------- #
def _vision_chat_envelope(content: str = "0") -> dict[str, Any]:
    """An OpenAI-style chat-completions success envelope (a clip ranking reply)."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class VisionTransport:
    """A fake chat transport the vision pool calls; records every request body.

    ``saw_base64`` is set True the first time a request carries an ``image_url``
    data-URI part, proving a FRAME left the machine. ``calls`` counts invocations
    so a no-consent run can assert it was NEVER touched.
    """

    def __init__(self, content: str = "0") -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []
        self.saw_base64 = False

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.calls.append({"url": url, "body": body, "headers": headers})
        for msg in body.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url_val = str(part.get("image_url", {}).get("url", ""))
                        if "base64," in url_val:
                            self.saw_base64 = True
        return _vision_chat_envelope(self.content)


def _fake_clip_loader(path: str, spans: Any) -> list[Any]:
    """One synthetic frame stack per span (no cv2)."""
    return [[f"frame@{lo}-{hi}"] for lo, hi in spans]


def _vision_provider_settings(*, with_consent: bool) -> dict[str, Any]:
    """Settings wiring a vision-capable cloud provider + routing + optional consent."""
    consent_frames = with_consent
    return {
        # the text-egress budget ack gate (WU-budget) is orthogonal to the frame
        # consent under test here; disable it so the run proceeds to the re-rank.
        "confirmCloudBudget": False,
        "providers": [
            {
                "id": "gemini",
                "provider": "Gemini",
                "kind": "cloud",
                "baseUrl": "https://example/v1",
                "model": "gemini-flash",
                "apiKeys": ["sk-vision-key-9999"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            }
        ],
        "routing": {"perFunction": {"vision": {"provider": "gemini", "fallback": []}}},
        "consent": {"perProvider": {"Gemini": {"frames": consent_frames}}},
    }


def _run_select_with_vision(
    tmp_path: Path,
    video_file: Path,
    *,
    settings_patch: dict[str, Any],
    transport: Any | None = None,
    models_present: Any | None = None,
) -> tuple[Services, RpcContext, str]:
    """Wire a Services for a vision select run with the injected seams, run it.

    The TEXT select path uses the injected FakeProvider (returns ``"[]"`` — no
    socket); the independent VISION pool uses the fake ``vlm_chat_transport`` so
    frame egress is observable. The two paths are separate by design (WU-vision).
    """
    svc = _phase8_services(
        tmp_path,
        provider=FakeProvider(),  # text select path; vision uses the vlm transport
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_frame_encoder=lambda frame: f"ENC<{frame}>",
        vlm_models_present=models_present if models_present is not None else (lambda s: False),
        vlm_chat_transport=transport,
    )
    ctx = _phase8_ctx()
    vid = _add_video(svc, video_file)
    _transcribe_sync(svc, ctx, vid)
    svc.settings.set(settings_patch)
    out = svc.phase8_select({"videoId": vid, "prompt": "best", "controls": {}, "tier": 2}, ctx)
    assert "jobId" in out
    ctx.jobs.join(timeout=5)
    return svc, ctx, vid


def test_phase8_select_no_vision_provider_passes_none(tmp_path: Path, video_file: Path) -> None:
    # No vision provider configured + no local weights -> vlm_reranker=None (the
    # existing transcript-only path). The select job still completes + caches.
    svc = _phase8_services(tmp_path, vlm_models_present=lambda s: False)
    ctx = _phase8_ctx()
    vid = _add_video(svc, video_file)
    _transcribe_sync(svc, ctx, vid)
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4") is None
    svc.phase8_select({"videoId": vid, "prompt": "best", "controls": {}, "tier": 2}, ctx)
    ctx.jobs.join(timeout=5)
    done = [e for e in ctx.events if e[0] == "done"]  # type: ignore[attr-defined]
    assert "candidates" in done[-1][2]


def test_phase8_select_cloud_vision_with_consent_egresses_frames(tmp_path: Path, video_file: Path) -> None:
    # End-to-end through phase8.select: the run completes, then we PROVE the
    # resolved cloud reranker egresses base64 frames when actually invoked (the
    # short fixture transcript may yield <2 candidates, so re-ranking is a no-op
    # in the job; the egress invariant is asserted on the resolved reranker).
    transport = VisionTransport(content="0")
    svc, ctx, vid = _run_select_with_vision(
        tmp_path,
        video_file,
        settings_patch=_vision_provider_settings(with_consent=True),
        transport=transport,
    )
    selects = [e for e in ctx.events if e[0] == "done" and "candidates" in e[2]]  # type: ignore[attr-defined]
    assert selects, "select job did not complete"
    # the resolved reranker is the cloud closure -> invoking it egresses frames.
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path=str(video_file))
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    rr.rerank_top_k([{"start": 0.0, "end": 1.0, "hook": "a"}, {"start": 1.0, "end": 2.0, "hook": "b"}], top_k=2)
    assert transport.calls, "cloud vision pool was never called"
    assert transport.saw_base64 is True


def test_phase8_select_cloud_vision_without_consent_no_frame_egress(tmp_path: Path, video_file: Path) -> None:
    transport = VisionTransport(content="0")
    svc, ctx, vid = _run_select_with_vision(
        tmp_path,
        video_file,
        settings_patch=_vision_provider_settings(with_consent=False),
        transport=transport,
        models_present=lambda s: False,
    )
    # NO frame consent -> cloud path refused; the fake vision transport NEVER touched.
    assert transport.calls == [], "frames egressed without consent"
    assert transport.saw_base64 is False
    selects = [e for e in ctx.events if e[0] == "done" and "candidates" in e[2]]  # type: ignore[attr-defined]
    assert selects, "select job did not complete (degraded to transcript-only)"
    # and the resolved reranker is NOT a cloud closure (no vision pool reachable).
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path=str(video_file)) is None


def test_resolve_vlm_reranker_cloud_when_consent_granted(tmp_path: Path) -> None:
    svc = _phase8_services(
        tmp_path,
        provider=None,
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_frame_encoder=lambda f: "b",
        vlm_models_present=lambda s: False,
    )
    svc.settings.set(_vision_provider_settings(with_consent=True))
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    backend = rr._factory(svc.settings.get())  # the closure builds the cloud backend
    assert isinstance(backend, sv.CloudVlmBackend)


def test_resolve_vlm_reranker_local_when_no_cloud_but_weights_present(tmp_path: Path) -> None:
    svc = _phase8_services(
        tmp_path,
        provider=None,
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_models_present=lambda s: True,  # local weights present
    )
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    # local path -> the backend factory is smolvlm2's default (NOT a cloud closure)
    assert rr._factory is sv._default_backend_factory


def test_resolve_vlm_reranker_off_when_no_cloud_no_weights(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path, provider=None, vlm_models_present=lambda s: False)
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4") is None


def test_resolve_vlm_reranker_cloud_selected_but_no_consent_falls_through(tmp_path: Path) -> None:
    # Cloud vision is routed but frames consent is absent -> NOT cloud; with local
    # weights present it falls through to the local reranker.
    svc = _phase8_services(
        tmp_path,
        provider=None,
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_models_present=lambda s: True,
    )
    svc.settings.set(_vision_provider_settings(with_consent=False))
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    assert rr._factory is sv._default_backend_factory  # local, not cloud


def test_vision_provider_for_consent_returns_first_vision_cloud_name(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path, provider=None)
    svc.settings.set(_vision_provider_settings(with_consent=True))
    name = svc._vision_provider_for_consent(svc.settings.get_raw())
    assert name == "Gemini"


# --------------------------------------------------------------------------- #
# OFFLINE ENFORCEMENT (bug fix): offline forbids cloud vision egress even when
# the provider is fully frame-consented + routed. Mirrors the consent fall-through
# above — offline drops the cloud branch so the resolver degrades to local/None.
# --------------------------------------------------------------------------- #
def test_resolve_vlm_reranker_offline_skips_cloud_falls_through_to_local(tmp_path: Path) -> None:
    # Cloud vision is routed AND frame-consented, but offline is ON: the cloud
    # branch must be refused (no frame egress); with local weights present the
    # resolver falls through to the LOCAL reranker (zero network).
    svc = _phase8_services(
        tmp_path,
        provider=None,
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_models_present=lambda s: True,
    )
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    assert rr._factory is sv._default_backend_factory  # local, not the cloud closure


def test_resolve_vlm_reranker_offline_no_weights_is_none(tmp_path: Path) -> None:
    # Cloud vision routed + consented, offline ON, NO local weights -> None
    # (transcript-only). No cloud closure is ever built, so no frame can egress.
    svc = _phase8_services(tmp_path, provider=None, vlm_models_present=lambda s: False)
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4") is None


def test_phase8_select_offline_no_frame_egress(tmp_path: Path, video_file: Path) -> None:
    # End-to-end: offline + a fully frame-consented cloud vision provider -> the
    # cloud vision pool is NEVER touched (the fake vision transport records zero
    # calls). The select job still completes (degraded to transcript-only).
    transport = VisionTransport(content="0")
    svc, ctx, vid = _run_select_with_vision(
        tmp_path,
        video_file,
        settings_patch={**_vision_provider_settings(with_consent=True), "offline": True},
        transport=transport,
        models_present=lambda s: False,
    )
    assert transport.calls == [], "frames egressed while offline"
    assert transport.saw_base64 is False
    selects = [e for e in ctx.events if e[0] == "done" and "candidates" in e[2]]  # type: ignore[attr-defined]
    assert selects, "select job did not complete (should degrade to transcript-only)"
    assert svc._resolve_vlm_reranker(svc.settings.get(), media_path=str(video_file)) is None


def test_phase8_select_offline_text_select_routes_local_no_egress(tmp_path: Path, video_file: Path) -> None:
    # The PRIMARY text egress (the select chat provider) must also be refused
    # offline: with offline ON + a routed text-capable cloud provider, the select
    # provider is built over cloud-STRIPPED settings, so a 429 can never fail over
    # to cloud and select_unified cannot egress. The resolved provider exposes only
    # local entries (no cloud egress target).
    svc = _phase8_services(tmp_path, provider=None, vlm_models_present=lambda s: False)
    svc.settings.set({**_vision_provider_settings(with_consent=True), "offline": True})
    provider = svc._select_provider_or_local()
    pool = getattr(provider, "entries", None)
    assert pool is not None, "expected a rotating pool with inspectable entries"
    assert all(entry.local for entry in pool), "offline select provider still carries a cloud egress target"


def test_select_provider_or_local_online_honors_select_route(tmp_path: Path) -> None:
    # ONLINE (offline off) + no injected provider: the select route is honored,
    # so a configured cloud entry is the pool's first (egress) target. The M3
    # RoutingPolicy global must ALLOW cloud (flipped to cloud) — otherwise the
    # fail-closed local default would short-circuit the seam to local-only.
    from media_studio.models import provider as provider_mod

    svc = _phase8_services(tmp_path, provider=None)
    svc.settings.set(_vision_provider_settings(with_consent=True))  # offline absent -> online
    svc.settings.set(
        {
            **_vision_provider_settings(with_consent=True),
            "routingPolicy": {"global": "cloud"},
            "routing": {"perFunction": {"select": {"provider": "gemini", "fallback": []}}},
        }
    )
    pool = svc._select_provider_or_local()
    assert isinstance(pool, provider_mod.RotatingProvider)
    assert pool.entries[0].provider == "Gemini", "online select route was not honored"


def _two_vision_provider_settings(*, first_consent: bool, second_consent: bool) -> dict[str, Any]:
    """Two vision-capable cloud providers, each with its OWN frame-consent flag.

    The FIRST (Gemini, routed first) and the SECOND (OpenAI) are both
    vision-capable. The regression case: first frame-consented but it 429s, second
    NOT frame-consented — proving rotation can never reach the non-consented one.
    """
    return {
        "confirmCloudBudget": False,
        "providers": [
            {
                "id": "gemini",
                "provider": "Gemini",
                "kind": "cloud",
                "baseUrl": "https://gemini.example/v1",
                "model": "gemini-flash",
                "apiKeys": ["sk-gemini-1111"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            },
            {
                "id": "openai",
                "provider": "OpenAI",
                "kind": "cloud",
                "baseUrl": "https://openai.example/v1",
                "model": "gpt-4o-mini",
                "apiKeys": ["sk-openai-2222"],
                "enabled": True,
                "capabilities": ["text", "vision"],
                "unit": "req",
            },
        ],
        "routing": {"perFunction": {"vision": {"provider": "gemini", "fallback": []}}},
        "consent": {
            "perProvider": {
                "Gemini": {"frames": first_consent},
                "OpenAI": {"frames": second_consent},
            }
        },
    }


class RotatingVisionTransport:
    """Fake chat transport that 429s the consented provider and records ALL targets.

    Raises ``ProviderError("LLM HTTP 429: ...")`` for any request to ``fail_host``
    (forcing the pool to rotate). For every request it records the target host and
    whether the body carried base64 frames, so a test can assert a non-consented
    host was NEVER reached with frames.
    """

    def __init__(self, *, fail_host: str) -> None:
        self._fail_host = fail_host
        self.hosts: list[str] = []
        self.frame_hosts: list[str] = []

    def __call__(self, url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
        self.hosts.append(url)
        saw_base64 = any(
            isinstance(part, dict)
            and part.get("type") == "image_url"
            and "base64," in str(part.get("image_url", {}).get("url", ""))
            for msg in body.get("messages", [])
            if isinstance(msg.get("content"), list)
            for part in msg["content"]
        )
        if saw_base64:
            self.frame_hosts.append(url)
        if self._fail_host in url:
            from media_studio.models.provider import ProviderError

            raise ProviderError("LLM HTTP 429: rate limited; retry-after=60")
        return _vision_chat_envelope("0")


def test_phase8_vision_rotation_never_egresses_to_non_consented_provider(tmp_path: Path) -> None:
    # REGRESSION (privacy CRITICAL): two vision-capable cloud providers — Gemini
    # (routed first, frame-consented) and OpenAI (vision-capable, NO frame
    # consent). Gemini 429s; the pool must NOT fail over to OpenAI with frames,
    # because OpenAI's frame consent was never granted. The consented pool is
    # filtered to Gemini only, so OpenAI is never even a rotation candidate.
    transport = RotatingVisionTransport(fail_host="gemini.example")
    svc = _phase8_services(
        tmp_path,
        provider=None,
        vlm_clip_frame_loader=_fake_clip_loader,
        vlm_frame_encoder=lambda frame: f"ENC<{frame}>",
        vlm_models_present=lambda s: False,
        vlm_chat_transport=transport,
    )
    svc.settings.set(_two_vision_provider_settings(first_consent=True, second_consent=False))

    rr = svc._resolve_vlm_reranker(svc.settings.get(), media_path="/v.mp4")
    from media_studio.features import smolvlm2 as sv

    assert isinstance(rr, sv.SmolVlmReranker)
    # invoking the reranker drives the vision pool; Gemini 429s, then exhausts
    # (no eligible consented fallback) — the input order is kept (no-op re-rank).
    cands = [{"start": 0.0, "end": 1.0, "hook": "a"}, {"start": 1.0, "end": 2.0, "hook": "b"}]
    out = rr.rerank_top_k(cands, top_k=2)

    assert [c["hook"] for c in out] == ["a", "b"], "degraded to input order on pool exhaustion"
    # the non-consented provider (OpenAI) was NEVER reached at all, with or w/o frames.
    assert not any("openai.example" in h for h in transport.hosts), "rotated to a non-consented provider"
    assert all("gemini.example" in h for h in transport.frame_hosts), "frame egress reached a non-consented host"
    # and the consented Gemini WAS attempted (the leak path is otherwise vacuous).
    assert any("gemini.example" in h for h in transport.frame_hosts), "consented provider was never tried"


def test_phase8_vision_pool_contains_only_frame_consented_cloud_entries(tmp_path: Path) -> None:
    # Direct assertion on the filtered pool: with Gemini consented and OpenAI not,
    # the cloud egress pool's vision-capable CLOUD entries are EXACTLY {Gemini}.
    svc = _phase8_services(tmp_path, provider=None, vlm_chat_transport=RotatingVisionTransport(fail_host="none"))
    svc.settings.set(_two_vision_provider_settings(first_consent=True, second_consent=False))
    raw = svc.settings.get_raw()
    pool = svc._vision_pool(svc._frame_consented_vision_settings(raw))
    cloud_vision = [e.provider for e in pool.entries if not e.local and "vision" in e.capabilities]
    assert cloud_vision == ["Gemini"], "non-consented vision provider leaked into the pool"


def test_frame_consented_vision_settings_drops_non_consented(tmp_path: Path) -> None:
    # The pure filter: only frame-consented providers survive; original untouched.
    svc = _phase8_services(tmp_path, provider=None)
    raw = _two_vision_provider_settings(first_consent=False, second_consent=True)
    filtered = svc._frame_consented_vision_settings(raw)
    assert [p["provider"] for p in filtered["providers"]] == ["OpenAI"]
    assert len(raw["providers"]) == 2, "input settings were mutated"


def test_frame_consented_vision_settings_no_providers_passthrough(tmp_path: Path) -> None:
    # No providers list -> settings returned unchanged (the branch with no list).
    svc = _phase8_services(tmp_path, provider=None)
    assert svc._frame_consented_vision_settings({"foo": 1}) == {"foo": 1}


def test_vision_provider_for_consent_none_when_no_vision_cloud(tmp_path: Path) -> None:
    svc = _phase8_services(tmp_path, provider=None)
    # only a TEXT provider configured -> no vision egress target
    svc.settings.set(
        {
            "providers": [
                {
                    "id": "groq",
                    "provider": "Groq",
                    "baseUrl": "https://example/v1",
                    "model": "m",
                    "apiKeys": ["k"],
                    "enabled": True,
                    "capabilities": ["text"],
                }
            ],
            "routing": {"perFunction": {"vision": {"provider": "groq"}}},
        }
    )
    assert svc._vision_provider_for_consent(svc.settings.get_raw()) is None


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
    # Importing smolvlm2 registers its asset (top-level register_*_assets()), so the
    # "present-but-not-installed" branch is exercised deterministically — not reliant
    # on another test having imported it first (prior latent ordering dependency).
    from media_studio.assets import manifest as _manifest
    from media_studio.features import smolvlm2 as _sv  # noqa: F401 - import for its registration side effect

    # Isolate the HF cache to an empty tmp dir: smolvlm2 is an installer='hf' asset
    # whose installed-probe reads the real HF cache, so without this a dev box that
    # has the snapshot cached would report it INSTALLED (host-dependent flake).
    empty_hf = tmp_path / "hf-empty"
    empty_hf.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(empty_hf))
    monkeypatch.setenv("HF_HOME", str(empty_hf))

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
