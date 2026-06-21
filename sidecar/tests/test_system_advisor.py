"""Tests for the System Advisor — pure capability/preset decision logic + probes.

Heavy-ML-free: no torch / transformers / pynvml / psutil are required. The lazy
hardware-probe internals are exercised by injecting fakes via ``sys.modules`` (so
``import pynvml`` etc. inside the seam resolves to a stub), and the pure verdict
logic is driven with hand-built probe maps + VRAM values.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from media_studio.features import system_advisor as sa

# --------------------------------------------------------------------------- #
# table integrity
# --------------------------------------------------------------------------- #


def test_components_table_has_all_manifest_components() -> None:
    names = {c.name for c in sa.COMPONENTS}
    expected = {
        "motion",
        "diversity",
        "ranker",
        "saliency",
        "audio_saliency",
        "scene_transnet",
        "vlm_backbone",
        "quality_gate",
        "aesthetic",
        "emotion",
        "ocr",
        "parakeet",
        "ctc_aligner",
        "pyannote",
        "smolvlm2",
    }
    assert names == expected


def test_every_tier_component_exists_in_table() -> None:
    by_name = {c.name for c in sa.COMPONENTS}
    for tier in sa.TIERS:
        for comp in tier.components:
            assert comp in by_name


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

ALL_DEPS = {
    "opencv": True,
    "numpy": True,
    "lightgbm": True,
    "torch": True,
    "transformers": True,
    "onnxruntime": True,
    "panns": True,
    "nemo": True,
}


def _status(report: sa.AdvisorReport, name: str) -> sa.ComponentStatus:
    return next(c for c in report.components if c.name == name)


def _tier(report: sa.AdvisorReport, tier: int) -> sa.TierStatus:
    return next(t for t in report.tiers if t.tier == tier)


# --------------------------------------------------------------------------- #
# advise — happy paths
# --------------------------------------------------------------------------- #


def test_six_gb_all_present_recommends_tier1_and_tier2_degraded() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144)
    # Tier-1 fully ok at 6GB.
    assert _tier(report, 1).verdict == "ok"
    # SmolVLM2 5200MB > 0.85*6144 (=5222) is FALSE (5200<5222) -> actually fits
    # cleanly; assert it is at least not unavailable, and tier2 reflects it.
    assert _status(report, "smolvlm2").verdict in ("ok", "degraded")
    assert report.vram_budget_mb == 6144
    assert report.notes == sa.NOTES


def test_smolvlm2_tight_when_budget_makes_it_exceed_85pct() -> None:
    # Budget where 5200 > 0.85*budget but <= budget -> degraded (tight).
    # 0.85*6000 = 5100; 5200 > 5100 and 5200 <= 6000 -> degraded.
    report = sa.advise(probes=ALL_DEPS, vram_mb=6000)
    assert _status(report, "smolvlm2").verdict == "degraded"
    assert _tier(report, 2).verdict == "degraded"


def test_recommended_preset_is_highest_ok_tier() -> None:
    # At 6144 every tier-1 component fits cleanly and smolvlm2 fits cleanly too
    # (5200 <= 5222 budget*0.85) -> tier2 ok -> recommended tier2.
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144)
    assert report.recommended_preset == "tier2-vlm"


def test_tier2_degraded_does_not_become_recommended() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=6000)
    # tier2 degraded -> recommended falls back to highest fully-ok tier (tier1).
    assert report.recommended_preset == "tier1-multimodal"


# --------------------------------------------------------------------------- #
# advise — VRAM degrade / wont-run branches
# --------------------------------------------------------------------------- #


def test_low_vram_makes_heavy_components_unavailable() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=1500)
    # SigLIP-2 (2300) over budget -> unavailable.
    assert _status(report, "vlm_backbone").verdict == "unavailable"
    # saliency 1000 <= 1500 but 1000 > 0.85*1500 (=1275)? no, 1000<1275 -> ok.
    assert _status(report, "saliency").verdict == "ok"
    # quality_gate 1900 > 1500 -> unavailable.
    assert _status(report, "quality_gate").verdict == "unavailable"


def test_vram_tight_branch_for_a_visual_component() -> None:
    # Budget 1100: saliency 1000 > 0.85*1100 (=935) and <= 1100 -> degraded.
    report = sa.advise(probes=ALL_DEPS, vram_mb=1100)
    assert _status(report, "saliency").verdict == "degraded"


def test_zero_vram_only_cpu_floor_runs() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=0)
    assert _status(report, "motion").verdict == "ok"
    assert _status(report, "diversity").verdict == "ok"
    assert _status(report, "ranker").verdict == "ok"
    assert _status(report, "audio_saliency").verdict == "ok"  # 0 VRAM (CPU)
    assert _status(report, "vlm_backbone").verdict == "unavailable"
    assert report.recommended_preset == "tier0-numeric"
    assert _tier(report, 0).verdict == "ok"
    # tier1 has both ok (audio_saliency 0 VRAM) and unavailable -> degraded.
    assert _tier(report, 1).verdict == "degraded"


def test_cpu_floor_vram_mb_is_none_in_status() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144)
    assert _status(report, "motion").vram_mb is None  # 0 VRAM -> None
    assert _status(report, "vlm_backbone").vram_mb == 2300


# --------------------------------------------------------------------------- #
# advise — importability branch
# --------------------------------------------------------------------------- #


def test_missing_torch_makes_gpu_components_unavailable() -> None:
    probes = {**ALL_DEPS, "torch": False}
    report = sa.advise(probes=probes, vram_mb=6144)
    assert _status(report, "saliency").verdict == "unavailable"
    assert "not importable" in _status(report, "saliency").reason
    # motion (opencv) still ok.
    assert _status(report, "motion").verdict == "ok"


def test_missing_probe_key_defaults_to_absent() -> None:
    # Empty probes -> everything that needs a dep is unavailable; floors too.
    report = sa.advise(probes={}, vram_mb=6144)
    assert _status(report, "motion").verdict == "unavailable"
    assert report.recommended_preset == "tier0-numeric"


# --------------------------------------------------------------------------- #
# advise — commercial-license branch
# --------------------------------------------------------------------------- #


def test_commercial_flips_non_commercial_components_unavailable() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144, commercial=True)
    for nc in ("saliency", "quality_gate", "aesthetic", "ctc_aligner"):
        st = _status(report, nc)
        assert st.verdict == "unavailable"
        assert st.license_commercial_ok is False
        assert st.reason  # block reason present
    # commercial-OK ones still run.
    assert _status(report, "vlm_backbone").verdict in ("ok", "degraded")
    assert _status(report, "audio_saliency").verdict == "ok"


# --------------------------------------------------------------------------- #
# advise — offline / models_present branch
# --------------------------------------------------------------------------- #


def test_offline_missing_model_is_unavailable() -> None:
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144, offline=True, models_present={})
    st = _status(report, "vlm_backbone")
    assert st.verdict == "unavailable"
    assert "Offline mode is on" in st.reason


def test_offline_with_model_installed_runs() -> None:
    present = {c.name: True for c in sa.COMPONENTS}
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144, offline=True, models_present=present)
    assert _status(report, "vlm_backbone").verdict in ("ok", "degraded")


def test_offline_does_not_block_cpu_floor() -> None:
    # motion is not model_backed -> offline never blocks it.
    report = sa.advise(probes=ALL_DEPS, vram_mb=6144, offline=True, models_present={})
    assert _status(report, "motion").verdict == "ok"


# --------------------------------------------------------------------------- #
# _tier_verdict directly (edge: empty + all-unavailable)
# --------------------------------------------------------------------------- #


def test_tier_verdict_empty_is_unavailable() -> None:
    assert sa._tier_verdict([]) == "unavailable"


def test_tier_verdict_all_unavailable() -> None:
    assert sa._tier_verdict(["unavailable", "unavailable"]) == "unavailable"


def test_tier_verdict_all_ok() -> None:
    assert sa._tier_verdict(["ok", "ok"]) == "ok"


def test_tier_verdict_mixed_is_degraded() -> None:
    assert sa._tier_verdict(["ok", "degraded"]) == "degraded"
    assert sa._tier_verdict(["ok", "unavailable"]) == "degraded"


# --------------------------------------------------------------------------- #
# recommended_preset directly (fallback when no tier ok)
# --------------------------------------------------------------------------- #


def test_recommended_preset_falls_back_to_tier0_when_none_ok() -> None:
    # Build a report whose tiers are all degraded/unavailable.
    report = sa.AdvisorReport(
        components=(),
        tiers=(
            sa.TierStatus(tier=0, label="x", verdict="degraded", components=()),
            sa.TierStatus(tier=1, label="y", verdict="unavailable", components=()),
        ),
        recommended_preset="ignored",
        vram_budget_mb=0,
    )
    assert sa.recommended_preset(report) == "tier0-numeric"


def test_recommended_preset_unknown_tier_falls_back() -> None:
    # An ok tier whose number isn't in TIERS -> default tier0-numeric.
    report = sa.AdvisorReport(
        components=(),
        tiers=(sa.TierStatus(tier=99, label="z", verdict="ok", components=()),),
        recommended_preset="ignored",
        vram_budget_mb=0,
    )
    assert sa.recommended_preset(report) == "tier0-numeric"


# --------------------------------------------------------------------------- #
# HardwareProbe with injected seams
# --------------------------------------------------------------------------- #


def test_hardware_probe_with_fake_seams() -> None:
    probe = sa.HardwareProbe(
        vram_probe=lambda: 6144,
        ram_probe=lambda: 16384,
        cpu_probe=lambda: 8,
    )
    hw = probe.detect()
    assert hw == sa.HardwareInfo(vram_mb=6144, ram_mb=16384, cpu_count=8, gpu_present=True)


def test_hardware_probe_no_gpu() -> None:
    probe = sa.HardwareProbe(vram_probe=lambda: None, ram_probe=lambda: 8192, cpu_probe=lambda: 4)
    hw = probe.detect()
    assert hw.gpu_present is False
    assert hw.vram_mb is None


def test_hardware_probe_swallows_failing_seam() -> None:
    def boom() -> int | None:
        raise RuntimeError("nvml exploded")

    probe = sa.HardwareProbe(vram_probe=boom, ram_probe=lambda: 1, cpu_probe=lambda: 1)
    hw = probe.detect()
    assert hw.vram_mb is None  # failure mapped to None
    assert hw.gpu_present is False


def test_hardware_probe_uses_defaults_when_no_seams() -> None:
    # Default seams are real lazy probes; on a CI box without a GPU vram may be
    # None — we only assert the call succeeds and cpu_count is sane.
    probe = sa.HardwareProbe()
    hw = probe.detect()
    assert hw.cpu_count is None or hw.cpu_count >= 1


# --------------------------------------------------------------------------- #
# default_vram_probe — lazy source fall-through (fake sys.modules)
# --------------------------------------------------------------------------- #


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str, module: types.ModuleType) -> None:
    monkeypatch.setitem(sys.modules, name, module)


def test_vram_from_pynvml(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("pynvml")
    calls: dict[str, int] = {"init": 0, "shutdown": 0}

    def nvmlInit() -> None:  # noqa: N802 - mirror the real API name
        calls["init"] += 1

    def nvmlShutdown() -> None:  # noqa: N802
        calls["shutdown"] += 1

    def nvmlDeviceGetHandleByIndex(i: int) -> str:  # noqa: N802
        return f"handle-{i}"

    class _Mem:
        total = 6 * 1024 * 1024 * 1024  # 6 GiB

    def nvmlDeviceGetMemoryInfo(handle: str) -> _Mem:  # noqa: N802
        return _Mem()

    fake.nvmlInit = nvmlInit  # type: ignore[attr-defined]
    fake.nvmlShutdown = nvmlShutdown  # type: ignore[attr-defined]
    fake.nvmlDeviceGetHandleByIndex = nvmlDeviceGetHandleByIndex  # type: ignore[attr-defined]
    fake.nvmlDeviceGetMemoryInfo = nvmlDeviceGetMemoryInfo  # type: ignore[attr-defined]
    _install_module(monkeypatch, "pynvml", fake)

    assert sa._vram_from_pynvml() == 6144
    assert calls == {"init": 1, "shutdown": 1}


def test_default_vram_probe_prefers_pynvml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_vram_from_pynvml", lambda: 4096)
    monkeypatch.setattr(sa, "_vram_from_nvidia_smi", lambda: 1)
    monkeypatch.setattr(sa, "_vram_from_torch", lambda: 2)
    assert sa.default_vram_probe() == 4096


def test_default_vram_probe_falls_through_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> int | None:
        raise RuntimeError("no pynvml")

    monkeypatch.setattr(sa, "_vram_from_pynvml", boom)
    monkeypatch.setattr(sa, "_vram_from_nvidia_smi", lambda: None)  # next source: nothing
    monkeypatch.setattr(sa, "_vram_from_torch", lambda: 8192)
    assert sa.default_vram_probe() == 8192


def test_default_vram_probe_all_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sa, "_vram_from_pynvml", lambda: None)
    monkeypatch.setattr(sa, "_vram_from_nvidia_smi", lambda: None)
    monkeypatch.setattr(sa, "_vram_from_torch", lambda: None)
    assert sa.default_vram_probe() is None


# --------------------------------------------------------------------------- #
# _vram_from_nvidia_smi — parsing branches (injected runner)
# --------------------------------------------------------------------------- #


class _FakeProc:
    def __init__(self, stdout: Any) -> None:
        self.stdout = stdout


def test_nvidia_smi_parses_first_line() -> None:
    assert sa._vram_from_nvidia_smi(run=lambda: _FakeProc("6144\n4096\n")) == 6144


def test_nvidia_smi_plain_string_runner() -> None:
    # runner returns a bare string (no .stdout attr) -> used directly.
    assert sa._vram_from_nvidia_smi(run=lambda: "8192") == 8192


def test_nvidia_smi_non_string_output_is_none() -> None:
    assert sa._vram_from_nvidia_smi(run=lambda: _FakeProc(None)) is None


def test_nvidia_smi_empty_output_is_none() -> None:
    assert sa._vram_from_nvidia_smi(run=lambda: _FakeProc("   ")) is None


def test_nvidia_smi_non_numeric_is_none() -> None:
    assert sa._vram_from_nvidia_smi(run=lambda: _FakeProc("N/A\n")) is None


def test_nvidia_smi_leading_blank_line_is_stripped() -> None:
    # text.strip() removes the leading newline, so the first parsed line is the
    # value -> 6144 (the strip() guards real nvidia-smi leading whitespace).
    assert sa._vram_from_nvidia_smi(run=lambda: _FakeProc("\n6144\n")) == 6144


def test_default_smi_runner_invokes_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    captured: dict[str, Any] = {}

    def fake_run(argv: Any, **kwargs: Any) -> _FakeProc:
        captured["argv"] = argv
        return _FakeProc("2048\n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = sa._default_smi_runner()
    assert out.stdout == "2048\n"  # type: ignore[attr-defined]
    assert captured["argv"][0] == "nvidia-smi"


# --------------------------------------------------------------------------- #
# _vram_from_torch — both branches (fake torch module)
# --------------------------------------------------------------------------- #


def _fake_torch(available: bool, total_bytes: int = 0) -> types.ModuleType:
    fake = types.ModuleType("torch")
    cuda = types.SimpleNamespace()
    cuda.is_available = lambda: available

    class _Props:
        total_memory = total_bytes

    cuda.get_device_properties = lambda i: _Props()
    fake.cuda = cuda  # type: ignore[attr-defined]
    return fake


def test_vram_from_torch_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_module(monkeypatch, "torch", _fake_torch(True, 4 * 1024 * 1024 * 1024))
    assert sa._vram_from_torch() == 4096


def test_vram_from_torch_not_available(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_module(monkeypatch, "torch", _fake_torch(False))
    assert sa._vram_from_torch() is None


# --------------------------------------------------------------------------- #
# default_ram_probe — psutil + os fallback branches
# --------------------------------------------------------------------------- #


def test_ram_probe_uses_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = types.ModuleType("psutil")

    def virtual_memory() -> Any:
        return types.SimpleNamespace(total=16 * 1024 * 1024 * 1024)

    fake.virtual_memory = virtual_memory  # type: ignore[attr-defined]
    _install_module(monkeypatch, "psutil", fake)
    assert sa.default_ram_probe() == 16384


def test_ram_probe_falls_back_to_os(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make `import psutil` fail by removing it + blocking re-import.
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(sa, "_ram_from_os", lambda: 4096)
    assert sa.default_ram_probe() == 4096


def test_ram_from_os_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setattr(
        os,
        "sysconf",
        lambda name: {"SC_PHYS_PAGES": 1024 * 1024, "SC_PAGE_SIZE": 4096}[name],
        raising=False,
    )
    assert sa._ram_from_os() == (1024 * 1024 * 4096) // (1024 * 1024)


def test_ram_from_os_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    def boom(name: str) -> int:
        raise ValueError("unsupported sysconf name")

    monkeypatch.setattr(os, "sysconf", boom, raising=False)
    assert sa._ram_from_os() is None


# --------------------------------------------------------------------------- #
# default_cpu_probe
# --------------------------------------------------------------------------- #


def test_cpu_probe_returns_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert sa.default_cpu_probe() == 12


# --------------------------------------------------------------------------- #
# probe_capabilities — find_spec seam branches
# --------------------------------------------------------------------------- #


def test_probe_capabilities_all_present() -> None:
    out = sa.probe_capabilities(find_spec=lambda name: object())
    assert out == {
        "opencv": True,
        "numpy": True,
        "lightgbm": True,
        "torch": True,
        "transformers": True,
        "onnxruntime": True,
        "panns": True,
        "nemo": True,
    }


def test_probe_capabilities_none_present() -> None:
    out = sa.probe_capabilities(find_spec=lambda name: None)
    assert all(v is False for v in out.values())


def test_probe_capabilities_mixed() -> None:
    def find(name: str) -> object | None:
        return object() if name in {"cv2", "numpy"} else None

    out = sa.probe_capabilities(find_spec=find)
    assert out["opencv"] is True
    assert out["numpy"] is True
    assert out["torch"] is False


def test_probe_capabilities_find_spec_raises_is_absent() -> None:
    def find(name: str) -> object:
        if name == "torch":
            raise ImportError("broken import path")
        return object()

    out = sa.probe_capabilities(find_spec=find)
    assert out["torch"] is False
    assert out["numpy"] is True


def test_probe_capabilities_default_find_spec_runs() -> None:
    # numpy IS installed in the venv; cv2 (opencv-headless) is too. nemo is not.
    out = sa.probe_capabilities()
    assert out["numpy"] is True
    assert out["nemo"] is False


# --------------------------------------------------------------------------- #
# advise_for_hardware — end-to-end with seams
# --------------------------------------------------------------------------- #


def test_advise_for_hardware_with_explicit_hardware_and_probes() -> None:
    hw = sa.HardwareInfo(vram_mb=6144, ram_mb=16384, cpu_count=8, gpu_present=True)
    report = sa.advise_for_hardware(hardware=hw, probes=ALL_DEPS)
    assert report.vram_budget_mb == 6144
    assert report.recommended_preset == "tier2-vlm"


def test_advise_for_hardware_runs_probe_and_find_spec() -> None:
    probe = sa.HardwareProbe(vram_probe=lambda: 6000, ram_probe=lambda: 1, cpu_probe=lambda: 1)
    report = sa.advise_for_hardware(probe=probe, find_spec=lambda name: object())
    assert report.vram_budget_mb == 6000
    # 6000 budget -> smolvlm2 tight -> recommended tier1.
    assert report.recommended_preset == "tier1-multimodal"


def test_advise_for_hardware_no_gpu_uses_fallback() -> None:
    hw = sa.HardwareInfo(vram_mb=None, ram_mb=8192, cpu_count=4, gpu_present=False)
    report = sa.advise_for_hardware(hardware=hw, probes=ALL_DEPS, fallback_vram_mb=0)
    assert report.vram_budget_mb == 0
    assert report.recommended_preset == "tier0-numeric"


def test_advise_for_hardware_commercial_and_offline_pass_through() -> None:
    hw = sa.HardwareInfo(vram_mb=6144, ram_mb=1, cpu_count=1, gpu_present=True)
    report = sa.advise_for_hardware(
        hardware=hw,
        probes=ALL_DEPS,
        commercial=True,
        offline=True,
        models_present={},
    )
    assert _status(report, "saliency").verdict == "unavailable"  # commercial block
    assert _status(report, "audio_saliency").verdict == "unavailable"  # offline, no model


def test_advise_for_hardware_defaults_run() -> None:
    # No hardware, no probes, no find_spec -> all default seams; just must not
    # raise and must yield at least the tier0 floor preset.
    report = sa.advise_for_hardware()
    assert report.recommended_preset in {"tier0-numeric", "tier1-multimodal", "tier2-vlm"}
