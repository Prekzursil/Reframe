"""Tests for the WU-B2 ``system.recommend`` handler wiring.

Heavy-free: the HardwareProbe and the local-server detector are injected as fakes
(no GPU, no torch, no socket). ``system.recommend`` is a DIRECT-return RPC that
composes the existing cheap probes (advisor + present-map + local-server detect +
asr engines) through the PURE :func:`recommender.recommend` and makes ZERO
provider/LLM calls. The tests assert: registration, that the handler forwards the
probe outputs into the recommender (spy), the offline/commercial passthrough, the
G-B1 "unavailable" fallback (no exception), zero provider calls, and the default
local-detector seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers
from media_studio.features import recommender as _recommender
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


# --------------------------------------------------------------------------- #
# fakes / seams (no heavy imports, no subprocess, no network)
# --------------------------------------------------------------------------- #
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


class _ExplodingProvider:
    """A provider that fails the test loudly if any chat/embed call is attempted."""

    def chat(self, *args: Any, **kwargs: Any) -> str:  # pragma: no cover - must never run
        raise AssertionError("system.recommend must make ZERO provider calls")


def _pool_entry(*, kind: str = "ollama", capabilities: list[str] | None = None) -> dict[str, Any]:
    """A ``detect_local_servers`` PoolEntry wire dict."""
    return {
        "id": kind,
        "kind": kind,
        "base_url": f"http://localhost/{kind}",
        "model": "llama3",
        "capabilities": capabilities if capabilities is not None else ["chat"],
        "unit": "req",
    }


def _services(tmp_path: Path, **over: Any) -> Services:
    """A Services wired with WU-B2 fakes (probe + provider that must never fire)."""
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "hardware_probe": _FakeHardwareProbe(),
        "provider": _ExplodingProvider(),
        "local_detector": lambda _settings: [],
    }
    base.update(over)
    return Services(**base)


def _direct() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# (a) registration
# --------------------------------------------------------------------------- #
def test_register_all_wires_system_recommend(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "system.recommend" in registered, "system.recommend was not registered"


# --------------------------------------------------------------------------- #
# happy path: returns the recommender output verbatim under {recommendation}
# --------------------------------------------------------------------------- #
def test_system_recommend_returns_recommendation_envelope(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.system_recommend({}, _direct())
    assert set(out) == {"recommendation"}
    rec = out["recommendation"]
    assert set(rec) == {"preset", "routing", "asrEngine", "downloads", "rationale"}
    assert rec["preset"] in {"privacy", "balanced", "bestFreeCloud"}


# --------------------------------------------------------------------------- #
# (b) the handler forwards the composed probes into recommender.recommend
# --------------------------------------------------------------------------- #
def test_system_recommend_forwards_probes_into_recommender(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def spy_recommend(report: Any, present: Any, detected_local: Any, asr_engines: Any, **kw: Any) -> Any:
        captured["report"] = report
        captured["present"] = present
        captured["detected_local"] = detected_local
        captured["asr_engines"] = asr_engines
        captured["offline"] = kw["offline"]
        captured["commercial"] = kw["commercial"]
        return {
            "preset": "privacy",
            "routing": {"perFunction": {}},
            "asrEngine": None,
            "downloads": [],
            "rationale": [],
        }

    monkeypatch.setattr(_recommender, "recommend", spy_recommend)
    detected = [_pool_entry()]
    svc = _services(tmp_path, local_detector=lambda _s: detected)
    out = svc.system_recommend({"commercial": True}, _direct())

    # forwarded the advisor wire report (has recommendedPreset + components)
    assert "recommendedPreset" in captured["report"]
    assert isinstance(captured["report"].get("components"), list)
    # forwarded the present-map, the detected local servers, and the asr engines
    assert isinstance(captured["present"], dict)
    assert captured["detected_local"] == detected
    assert {"engines"} <= set(captured["asr_engines"])
    # (b) commercial from params + offline from offline.is_offline forwarded
    assert captured["commercial"] is True
    assert captured["offline"] is False
    # returned verbatim
    assert out["recommendation"]["preset"] == "privacy"


def test_system_recommend_forwards_offline_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _recommender,
        "recommend",
        lambda *a, **kw: (
            captured.update(offline=kw["offline"])
            or {
                "preset": "privacy",
                "routing": {"perFunction": {}},
                "asrEngine": None,
                "downloads": [],
                "rationale": [],
            }
        ),
    )
    svc = _services(tmp_path)
    svc.settings.set({"offline": True})
    svc.system_recommend({}, _direct())
    assert captured["offline"] is True


def test_system_recommend_commercial_defaults_to_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _recommender,
        "recommend",
        lambda *a, **kw: (
            captured.update(commercial=kw["commercial"])
            or {
                "preset": "privacy",
                "routing": {"perFunction": {}},
                "asrEngine": None,
                "downloads": [],
                "rationale": [],
            }
        ),
    )
    svc = _services(tmp_path)
    svc.settings.set({"commercial": True})
    svc.system_recommend({}, _direct())  # no commercial in params -> falls back to settings
    assert captured["commercial"] is True


# --------------------------------------------------------------------------- #
# (c) malformed advisor report -> the G-B1 "unavailable" recommendation, no crash
# --------------------------------------------------------------------------- #
def test_system_recommend_unavailable_on_no_probe_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the advisor wire to lack recommendedPreset (the recommender's G-B1 trigger).
    monkeypatch.setattr(handlers, "_advisor_report_to_wire", lambda _r: {"components": []})
    svc = _services(tmp_path)
    out = svc.system_recommend({}, _direct())  # must NOT raise
    rec = out["recommendation"]
    assert rec["preset"] == "privacy"
    assert rec["routing"]["perFunction"] == {}
    assert rec["downloads"] == []
    assert any("Could not detect" in line for line in rec["rationale"])


# --------------------------------------------------------------------------- #
# (d) ZERO provider calls (composes probes only)
# --------------------------------------------------------------------------- #
def test_system_recommend_makes_zero_provider_calls(tmp_path: Path) -> None:
    # _ExplodingProvider raises on any chat() call; reaching it fails the test.
    svc = _services(tmp_path)
    out = svc.system_recommend({}, _direct())
    assert "recommendation" in out  # got here => provider was never invoked


# --------------------------------------------------------------------------- #
# default local-detector seam (no injected detector -> real detector over a
# fake GET transport that reports no server -> []), still composes a recommendation
# --------------------------------------------------------------------------- #
def test_system_recommend_default_detector_uses_urllib_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_get(url: str, body: Any, headers: Any, timeout: float) -> dict[str, Any]:
        calls.append(url)
        return {}  # no usable model -> detect_local_servers returns []

    from media_studio.models import provider as _provider_mod

    monkeypatch.setattr(_provider_mod, "urllib_get_json", fake_get)
    svc = Services(
        data_dir=tmp_path / "data",
        hardware_probe=_FakeHardwareProbe(),
        provider=_ExplodingProvider(),
    )  # NO local_detector -> exercises the real-detector branch
    out = svc.system_recommend({}, _direct())
    assert "recommendation" in out
    assert calls, "the default detector should have probed at least one local /models endpoint"
