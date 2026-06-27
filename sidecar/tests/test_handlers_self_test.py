"""WU-2 — ``system.selfTest`` handler wiring tests.

The handler composes the pure :mod:`media_studio.features.self_test` diagnostic
over the runtime services: the real ``data_dir`` writability probe (a tmp dir
here), the injected HardwareProbe seam (no GPU), and the ffmpeg/ffprobe chain via
:mod:`media_studio.tools_resolver` (monkeypatched so no real ffmpeg is needed). It
returns the camelCase wire report the Electron setup-status panel renders 1:1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import handlers, tools_resolver
from media_studio.handlers import Services
from media_studio.protocol import RpcContext


class _FakeHardwareProbe:
    def detect(self) -> Any:
        from media_studio.features.system_advisor import HardwareInfo

        return HardwareInfo(vram_mb=6000, ram_mb=16000, cpu_count=8, gpu_present=True)


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda obj: None, jobs=None)


def _services(tmp_path: Path) -> Services:
    return Services(data_dir=tmp_path / "data", hardware_probe=_FakeHardwareProbe())


def test_register_all_wires_system_self_test(tmp_path: Path) -> None:
    registered: dict[str, Any] = {}
    handlers.register_all(
        services=Services(data_dir=tmp_path / "d"),
        register=lambda name, fn: registered.__setitem__(name, fn),
    )
    assert "system.selfTest" in registered


def test_self_test_returns_wire_report(tmp_path: Path, ctx: RpcContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(tools_resolver, "resolve_tool", lambda name, _s=None: f"/usr/bin/{name}")
    out = _services(tmp_path).system_self_test({}, ctx)

    assert set(out) == {"ok", "checks", "problems"}
    assert isinstance(out["ok"], bool)
    assert [c["id"] for c in out["checks"]] == ["data", "device", "cv2", "asr", "ffmpeg"]
    a_check = out["checks"][0]
    assert set(a_check) == {"id", "label", "ok", "required", "detail", "fixHint"}
    # The tmp data dir is writable and the injected probe + monkeypatched tools pass.
    by_id = {c["id"]: c for c in out["checks"]}
    assert by_id["data"]["ok"] is True
    assert by_id["device"]["ok"] is True
    assert by_id["ffmpeg"]["ok"] is True


def test_self_test_surfaces_missing_ffmpeg(tmp_path: Path, ctx: RpcContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(tools_resolver, "resolve_tool", lambda name, _s=None: None)
    out = _services(tmp_path).system_self_test({}, ctx)
    by_id = {c["id"]: c for c in out["checks"]}
    assert by_id["ffmpeg"]["ok"] is False
    assert out["ok"] is False
    assert any("FFmpeg" in p or "ffmpeg" in p for p in out["problems"])
