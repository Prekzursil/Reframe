"""WU-2 — ``system.selfTest`` handler wiring tests.

The handler composes the pure :mod:`media_studio.features.self_test` diagnostic
over the runtime services: the real ``data_dir`` writability probe (a tmp dir
here), the injected HardwareProbe seam (no GPU), and the ffmpeg/ffprobe chain via
:mod:`media_studio.tools_resolver` (monkeypatched so no real ffmpeg is needed). It
returns the camelCase wire report the Electron setup-status panel renders 1:1.
"""

from __future__ import annotations

import importlib.util
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


def test_self_test_cv2_row_is_green_when_opencv_is_importable(
    tmp_path: Path, ctx: RpcContext, monkeypatch: Any
) -> None:
    """F37 end-to-end: a provisioned install must not report the reframe row red.

    Runs over the REAL ``importlib.find_spec`` seam (``system_self_test`` injects
    none), so this asserts the actual wire values the setup-status panel renders —
    not a fixture's own copy.

    SCOPED TO THE ``cv2`` ROW DELIBERATELY. ``out["ok"]``/``out["problems"]`` also
    fold in the REQUIRED ``asr`` row, and .github/workflows/quality.yml installs
    neither faster-whisper nor a stub for it (``pip install -e "sidecar[dev]"
    --no-deps`` plus only httpx/numpy/opencv-python-headless/blake3), so asserting
    the rollup would be permanently red in CI regardless of this fix.
    ``opencv-python-headless`` IS installed there, so the ``cv2`` row is a valid
    CI assertion.
    """
    if importlib.util.find_spec("cv2") is None:  # pragma: no cover - env guard
        pytest.skip("opencv is not importable here, so the cv2 row cannot be green")
    monkeypatch.setattr(tools_resolver, "resolve_tool", lambda name, _s=None: f"/usr/bin/{name}")
    out = _services(tmp_path).system_self_test({}, ctx)

    by_id = {c["id"]: c for c in out["checks"]}
    assert by_id["cv2"]["ok"] is True, by_id["cv2"]["detail"]
    assert by_id["cv2"]["fixHint"] == ""
    # No OpenCV problem line may reach the panel on a correctly provisioned env.
    assert not any("OpenCV" in p for p in out["problems"]), out["problems"]


def test_self_test_surfaces_missing_ffmpeg(tmp_path: Path, ctx: RpcContext, monkeypatch: Any) -> None:
    monkeypatch.setattr(tools_resolver, "resolve_tool", lambda name, _s=None: None)
    out = _services(tmp_path).system_self_test({}, ctx)
    by_id = {c["id"]: c for c in out["checks"]}
    assert by_id["ffmpeg"]["ok"] is False
    assert out["ok"] is False
    assert any("FFmpeg" in p or "ffmpeg" in p for p in out["problems"])
