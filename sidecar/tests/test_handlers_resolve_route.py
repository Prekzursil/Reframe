"""Tests for the M5 ``models.resolveRoute`` concrete-route handler.

Composes the read-only ``models.overview`` (local plan + detected runners +
redacted providers) and resolves the concrete ``{mode, model, runner|provider}``
per AI function (DESIGN §2.3 step 4). Heavy-free: the HardwareProbe + local
detector are injected as fakes; the handler makes ZERO provider/LLM calls and
NEVER mutates settings. The loud degrade-to-local notice is asserted on a
cloud-routed function with no key on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_studio import handlers
from media_studio.handlers import Services
from media_studio.models import routing_resolve as rr
from media_studio.protocol import RpcContext


class _FakeHardwareProbe:
    def __init__(self) -> None:
        from media_studio.features.system_advisor import HardwareInfo

        self._info = HardwareInfo(vram_mb=6000, ram_mb=16000, cpu_count=8, gpu_present=True, disk_free_mb=200000)

    def detect(self) -> Any:
        return self._info


class _ExplodingProvider:
    def chat(self, *args: Any, **kwargs: Any) -> str:  # pragma: no cover - must never run
        raise AssertionError("models.resolveRoute must make ZERO provider calls")


def _services(tmp_path: Path, **over: Any) -> Services:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "hardware_probe": _FakeHardwareProbe(),
        "provider": _ExplodingProvider(),
        "local_detector": lambda _settings: [],
        "ollama_meta_transport": lambda url, method, body, timeout: {},
    }
    base.update(over)
    return Services(**base)


def _direct() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _with_key() -> dict[str, Any]:
    return {
        "providers": [{"id": "openrouter", "provider": "OpenRouter", "apiKeys": ["sk-or-secret"]}],
    }


# --------------------------------------------------------------------------- #
# (a) registration
# --------------------------------------------------------------------------- #
def test_register_all_wires_resolve_route(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "models.resolveRoute" in registered


# --------------------------------------------------------------------------- #
# (b) resolve all functions (default body)
# --------------------------------------------------------------------------- #
def test_resolve_all_returns_one_route_per_function(tmp_path: Path) -> None:
    out = _services(tmp_path).models_resolve_route({}, _direct())
    assert [r["fn"] for r in out["routes"]] == list(rr.AI_FUNCTIONS)
    # local default -> every route local, none degraded.
    assert all(r["mode"] == "local" and r["degraded"] is False for r in out["routes"])


# --------------------------------------------------------------------------- #
# (c) resolve a single function
# --------------------------------------------------------------------------- #
def test_resolve_single_function(tmp_path: Path) -> None:
    out = _services(tmp_path).models_resolve_route({"fn": "asr"}, _direct())
    assert "routes" not in out
    assert out["route"]["fn"] == "asr"
    assert out["route"]["mode"] == "local"


def test_blank_fn_resolves_all(tmp_path: Path) -> None:
    out = _services(tmp_path).models_resolve_route({"fn": ""}, _direct())
    assert "routes" in out


def test_non_string_fn_resolves_all(tmp_path: Path) -> None:
    out = _services(tmp_path).models_resolve_route({"fn": 7}, _direct())
    assert "routes" in out


# --------------------------------------------------------------------------- #
# (d) cloud route + loud degrade
# --------------------------------------------------------------------------- #
def test_cloud_route_with_key_targets_provider(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": {"global": "cloud"}, **_with_key()})
    out = svc.models_resolve_route({"fn": "select"}, _direct())
    assert out["route"]["mode"] == "cloud"
    assert out["route"]["provider"] == "openrouter"
    assert out["route"]["degraded"] is False


def test_cloud_route_without_key_degrades_loud(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": {"global": "cloud"}})
    out = svc.models_resolve_route({"fn": "select"}, _direct())
    route = out["route"]
    assert route["mode"] == "local"
    assert route["requestedMode"] == "cloud"
    assert route["degraded"] is True
    assert route["notice"] == rr.ROUTE_DEGRADED_NOTICE


# --------------------------------------------------------------------------- #
# (e) read-only: the resolve never persists / leaks a raw key
# --------------------------------------------------------------------------- #
def test_resolve_does_not_mutate_settings(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": {"global": "cloud"}, **_with_key()})
    before = dict(svc.settings.get())
    svc.models_resolve_route({}, _direct())
    assert svc.settings.get() == before


def test_resolve_never_leaks_raw_key(tmp_path: Path) -> None:
    svc = _services(tmp_path)
    svc.settings.set({"routingPolicy": {"global": "cloud"}, **_with_key()})
    out = svc.models_resolve_route({}, _direct())
    assert "sk-or-secret" not in repr(out)
