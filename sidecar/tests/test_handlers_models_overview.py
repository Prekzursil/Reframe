"""Tests for the M1a ``models.overview`` thin compose handler.

Heavy-free: the HardwareProbe and the local-server detector are injected as fakes
(no GPU, no torch, no socket). ``models.overview`` is a DIRECT-return RPC that
stitches the EXISTING cheap probes/handlers (probe + advisor + local detect +
recommend) with the redacted providers + per-key pool + fail-closed routing
policy into ONE screen, making ZERO provider/LLM calls and NEVER mutating
settings. The tests pin: registration, the exact compose shape, the redacted /
key-safe providers + keyPool, the GATE-2 fail-closed routing policy, the
commercial passthrough, and the read-only (no-mutation, no-provider-call)
invariants.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from media_studio import handlers
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


class _FakeHardwareProbe:
    """A HardwareProbe-shaped seam returning a fixed HardwareInfo (no GPU deps)."""

    def __init__(self, vram_mb: int | None = 6000, ram_mb: int | None = 16000) -> None:
        from media_studio.features.system_advisor import HardwareInfo

        self._info = HardwareInfo(
            vram_mb=vram_mb,
            ram_mb=ram_mb,
            cpu_count=8,
            gpu_present=vram_mb is not None,
            disk_free_mb=200000,
        )

    def detect(self) -> Any:
        return self._info


class _ExplodingProvider:
    """A provider that fails the test loudly if any chat/embed call is attempted."""

    def chat(self, *args: Any, **kwargs: Any) -> str:  # pragma: no cover - must never run
        raise AssertionError("models.overview must make ZERO provider calls")


def _pool_entry(kind: str = "ollama") -> dict[str, Any]:
    return {
        "id": kind,
        "kind": kind,
        "base_url": f"http://127.0.0.1/{kind}",
        "model": "qwen2.5:7b",
        "capabilities": ["chat"],
        "unit": "req",
    }


def _ollama_meta_transport(*, fits: bool = True) -> Any:
    """A method-aware Ollama transport fake: GET /api/tags + POST /api/show.

    Returns one capability-eligible q4 model so ``eligibility`` reports
    ``source="metadata"`` with a real quant + VRAM estimate. ``fits=False`` reports
    a giant model that cannot fit, so eligibility degrades to the static ladder.
    """
    params = "7.6B" if fits else "70B"

    def _transport(url: str, method: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        if url.endswith("/api/tags"):
            assert method == "GET"
            return {
                "models": [
                    {
                        "name": "qwen2.5:7b-instruct-q4_K_M",
                        "digest": "DIGEST_A",
                        "size": 4700,
                        "details": {"parameter_size": params, "quantization_level": "Q4_K_M"},
                    }
                ]
            }
        assert url.endswith("/api/show") and method == "POST"
        return {
            "capabilities": ["completion", "tools"],
            "details": {"parameter_size": params, "quantization_level": "Q4_K_M"},
        }

    return _transport


def _services(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "hardware_probe": _FakeHardwareProbe(),
        "provider": _ExplodingProvider(),
        "local_detector": lambda _settings: [],
        # M2: a default no-op transport (empty /api/tags) so an Ollama-detecting
        # test never opens a socket; eligibility degrades to the static ladder
        # unless a richer transport is injected.
        "ollama_meta_transport": lambda url, method, body, timeout: {},
    }
    base.update(over)
    return Services(**base)


def _direct() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


# --------------------------------------------------------------------------- #
# (a) registration
# --------------------------------------------------------------------------- #
def test_register_all_wires_models_overview(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "models.overview" in registered


# --------------------------------------------------------------------------- #
# (b) the compose shape — exactly the 8 DESIGN §2.3 fields, one screen
# --------------------------------------------------------------------------- #
def test_overview_returns_the_compose_shape(tmp_path: Path) -> None:
    detected = [_pool_entry()]
    svc = _services(tmp_path, local_detector=lambda _s: detected)
    out = svc.models_overview({}, _direct())
    assert set(out) == {
        "hardware",
        "tiers",
        "recommendedPreset",
        "runners",
        "localPlan",
        "providers",
        "keyPool",
        "routingPolicy",
        "eligibility",  # M2
    }
    # hardware = system.probe shape
    assert out["hardware"]["vramMb"] == 6000
    assert out["hardware"]["gpuPresent"] is True
    # tiers/recommendedPreset come from the advisor report
    assert isinstance(out["tiers"], list) and out["tiers"]
    assert isinstance(out["recommendedPreset"], str) and out["recommendedPreset"]
    # runners = the detected local servers verbatim
    assert out["runners"] == detected
    # localPlan = the device-ranked plan (whisper + llm + per-runner advice)
    assert out["localPlan"]["whisper"]["model"] == "large-v3-turbo"  # 6000MB GPU fits turbo
    assert out["localPlan"]["llm"]["model"] == "qwen2.5:7b"
    by_kind = {r["kind"]: r for r in out["localPlan"]["runners"]}
    assert by_kind["ollama"]["present"] is True
    assert by_kind["lmstudio"]["present"] is False


# --------------------------------------------------------------------------- #
# (b2) M2 eligibility — real quant + VRAM estimate when Ollama is detected;
# static-ladder fallback otherwise (drives the "using X because Y" reason strip)
# --------------------------------------------------------------------------- #
def test_overview_eligibility_is_ladder_without_an_ollama_runner(tmp_path: Path) -> None:
    # No detected runner -> the transport is never queried; eligibility degrades to
    # the static-ladder fallback (a usable LLM pick still exists).
    out = _services(tmp_path).models_overview({}, _direct())
    elig = out["eligibility"]
    assert elig["source"] == "ladder"
    assert elig["models"] == []
    assert elig["fallback"]["model"]  # a ladder pick always exists


def test_overview_eligibility_uses_real_ollama_metadata(tmp_path: Path) -> None:
    detected = [_pool_entry()]
    svc = _services(
        tmp_path,
        local_detector=lambda _s: detected,
        ollama_meta_transport=_ollama_meta_transport(fits=True),
    )
    out = svc.models_overview({}, _direct())
    elig = out["eligibility"]
    assert elig["source"] == "metadata"
    top = elig["models"][0]
    assert top["model"] == "qwen2.5:7b-instruct-q4_K_M"
    assert top["quantBits"] == 4
    assert top["paramsB"] == 7.6
    assert top["vramEstimateGb"] is not None and top["vramEstimateGb"] > 0
    assert top["fits"] is True


def test_overview_eligibility_degrades_to_ladder_when_nothing_fits(tmp_path: Path) -> None:
    # A detected Ollama serving only a model too big for the 6 GB GPU -> no
    # metadata model fits, so eligibility falls back to the static ladder.
    detected = [_pool_entry()]
    svc = _services(
        tmp_path,
        local_detector=lambda _s: detected,
        ollama_meta_transport=_ollama_meta_transport(fits=False),
    )
    out = svc.models_overview({}, _direct())
    assert out["eligibility"]["source"] == "ladder"
    assert out["eligibility"]["models"] == []


def test_overview_uses_default_ollama_transport_when_none_injected(tmp_path: Path) -> None:
    # No injected transport + no Ollama runner -> the lazy default transport
    # builder is exercised (its inner socket closure is never called: there is no
    # Ollama base URL to probe), so the overview composes a ladder eligibility.
    svc = Services(
        data_dir=tmp_path / "data",
        hardware_probe=_FakeHardwareProbe(),
        provider=_ExplodingProvider(),
        local_detector=lambda _s: [],
    )
    out = svc.models_overview({}, _direct())
    assert out["eligibility"]["source"] == "ladder"


def test_overview_default_routing_policy_is_local(tmp_path: Path) -> None:
    """With no persisted policy the overview reports the local-only default."""
    out = _services(tmp_path).models_overview({}, _direct())
    assert out["routingPolicy"] == {"global": "local", "overrides": {}}


def test_overview_reads_persisted_routing_policy(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": {"global": "auto", "overrides": {"select": "cloud"}}})
    out = svc.models_overview({}, _direct())
    assert out["routingPolicy"] == {"global": "auto", "overrides": {"select": "cloud"}}


def test_overview_routing_policy_fails_closed_on_corruption(tmp_path: Path) -> None:
    """GATE-2: a corrupt persisted policy fails CLOSED to local (zero egress)."""
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": "corrupt-not-a-dict"})
    out = svc.models_overview({}, _direct())
    assert out["routingPolicy"] == {"global": "local", "overrides": {}}


# --------------------------------------------------------------------------- #
# (c) redacted + key-safe providers / keyPool (no full key ever crosses RPC)
# --------------------------------------------------------------------------- #
def test_overview_providers_and_keypool_are_redacted(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set(
        {"providers": [{"id": "groq", "provider": "Groq", "apiKeys": ["sk-SECRET-RAW-KEY-1234"], "unit": "token"}]}
    )
    out = svc.models_overview({}, _direct())
    # the raw key never appears ANYWHERE in the serialized overview
    import json

    blob = json.dumps(out)
    assert "sk-SECRET-RAW-KEY-1234" not in blob
    assert "SECRET" not in blob
    # providers list is redacted to last-4
    assert out["providers"][0]["apiKeys"] == ["…1234"]
    # keyPool expands one redacted row per key, carrying ONLY the redaction
    assert out["keyPool"] == [
        {"id": "groq#0", "providerId": "groq", "redactedKey": "…1234", "unit": "token", "status": "active"}
    ]


def test_overview_keypool_empty_without_keys(tmp_path: Path) -> None:
    out = _services(tmp_path).models_overview({}, _direct())
    assert out["keyPool"] == []
    assert out["providers"] == []


# --------------------------------------------------------------------------- #
# (d) commercial passthrough into the advisor (tiers change with the flag)
# --------------------------------------------------------------------------- #
def test_overview_forwards_commercial_into_advisor(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    out = svc.models_overview({"commercial": True}, _direct())
    # advisor surfaced its tiers under the commercial flag (smoke: shape intact)
    assert {t["tier"] for t in out["tiers"]} == {0, 1, 2}


# --------------------------------------------------------------------------- #
# (e) read-only invariants: ZERO provider calls + NO settings mutation
# --------------------------------------------------------------------------- #
def test_overview_makes_zero_provider_calls(tmp_path: Path) -> None:
    # _ExplodingProvider raises on any chat(); reaching here proves none was made.
    out = _services(tmp_path).models_overview({}, _direct())
    assert "hardware" in out


def test_overview_does_not_mutate_settings(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"providers": [{"id": "groq", "apiKeys": ["sk-raw-9999"]}]})
    before = copy.deepcopy(svc.settings.get_raw())
    svc.models_overview({}, _direct())
    assert svc.settings.get_raw() == before


# --------------------------------------------------------------------------- #
# default local-detector seam (no injected detector -> real detector over a fake
# GET transport that finds no server -> []) still composes the overview
# --------------------------------------------------------------------------- #
def test_overview_default_detector_uses_urllib_transport(tmp_path: Path, monkeypatch: Any) -> None:
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
    out = svc.models_overview({}, _direct())
    assert out["runners"] == []
    assert calls, "the default detector should have probed at least one /models endpoint"
