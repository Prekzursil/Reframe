"""Unit tests for media_studio.models.model_recommend (device-ranked local models).

Covers the PURE device-fit picking (whisper + LLM ladders), the "X because
RAM/VRAM Y" reason strings, and the Ollama / LM Studio runner advice (detect +
device-fit pull recommendation + install link). Every input is a plain wire dict;
no socket, no clock, no heavy import.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio.models import model_recommend as mr


# --------------------------------------------------------------------------- #
# _as_int coercion
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (8000, 8000),
        (8000.7, 8000),
        (None, None),
        ("8000", None),
        (True, None),  # bool is not a usable number
    ],
)
def test_as_int(value: Any, expected: int | None) -> None:
    assert mr._as_int(value) == expected


# --------------------------------------------------------------------------- #
# _device_reason — the three "because" clauses
# --------------------------------------------------------------------------- #
def test_device_reason_gpu() -> None:
    assert mr._device_reason(vram_mb=6000, ram_mb=16000, gpu_present=True) == "fits your GPU (6000 MB VRAM)"


def test_device_reason_cpu_when_no_gpu() -> None:
    assert mr._device_reason(vram_mb=None, ram_mb=16000, gpu_present=False) == "fits your CPU (16000 MB RAM)"


def test_device_reason_gpu_present_but_vram_unknown_falls_to_ram() -> None:
    # gpu_present True but no VRAM number -> CPU/RAM clause (no crash).
    assert mr._device_reason(vram_mb=None, ram_mb=4000, gpu_present=True) == "fits your CPU (4000 MB RAM)"


def test_device_reason_unknown_device() -> None:
    assert (
        mr._device_reason(vram_mb=None, ram_mb=None, gpu_present=False)
        == "device not detected — using the safe baseline"
    )


# --------------------------------------------------------------------------- #
# _fits — GPU vram path / CPU ram path / wholly-unknown floor path
# --------------------------------------------------------------------------- #
def test_fits_gpu_vram() -> None:
    big = mr.LLM_LADDER[0]
    assert mr._fits(big, vram_mb=12000, ram_mb=None, gpu_present=True) is True
    assert mr._fits(big, vram_mb=4000, ram_mb=None, gpu_present=True) is False


def test_fits_cpu_ram() -> None:
    small = mr.WHISPER_LADDER[2]  # small
    assert mr._fits(small, vram_mb=None, ram_mb=4000, gpu_present=False) is True
    assert mr._fits(small, vram_mb=None, ram_mb=1000, gpu_present=False) is False


def test_fits_unknown_device_only_floor() -> None:
    floor = mr.WHISPER_LADDER[-1]
    top = mr.WHISPER_LADDER[0]
    assert mr._fits(floor, vram_mb=None, ram_mb=None, gpu_present=False) is True
    assert mr._fits(top, vram_mb=None, ram_mb=None, gpu_present=False) is False


# --------------------------------------------------------------------------- #
# recommend_whisper / recommend_llm — device ranking + reason wording
# --------------------------------------------------------------------------- #
def test_recommend_whisper_big_gpu_picks_turbo() -> None:
    reco = mr.recommend_whisper({"vramMb": 8000, "ramMb": 32000, "gpuPresent": True})
    assert reco["model"] == "large-v3-turbo"
    assert "GPU (8000 MB VRAM)" in reco["reason"]
    assert reco["label"] == "Whisper large-v3-turbo"


def test_recommend_whisper_cpu_box_picks_small() -> None:
    reco = mr.recommend_whisper({"vramMb": None, "ramMb": 4000, "gpuPresent": False})
    assert reco["model"] == "small"
    assert "CPU (4000 MB RAM)" in reco["reason"]


def test_recommend_whisper_unknown_device_picks_floor() -> None:
    reco = mr.recommend_whisper({})
    assert reco["model"] == "base"
    assert "device not detected" in reco["reason"]


def test_recommend_llm_mid_gpu_picks_7b() -> None:
    reco = mr.recommend_llm({"vramMb": 8000, "ramMb": 16000, "gpuPresent": True})
    assert reco["model"] == "qwen2.5:7b"


def test_recommend_llm_low_gpu_picks_3b() -> None:
    reco = mr.recommend_llm({"vramMb": 4000, "ramMb": 8000, "gpuPresent": True})
    assert reco["model"] == "qwen2.5:3b"


def test_recommend_llm_unknown_picks_floor() -> None:
    assert mr.recommend_llm({})["model"] == "qwen2.5:1.5b"


# --------------------------------------------------------------------------- #
# _pull_hint — per-runner copy-able instruction
# --------------------------------------------------------------------------- #
def test_pull_hint_ollama() -> None:
    assert mr._pull_hint("ollama", "qwen2.5:7b") == "ollama pull qwen2.5:7b"


def test_pull_hint_lmstudio() -> None:
    assert "LM Studio model browser" in mr._pull_hint("lmstudio", "qwen2.5:7b")


# --------------------------------------------------------------------------- #
# _detected_by_kind — keying robustness
# --------------------------------------------------------------------------- #
def test_detected_by_kind_uses_kind_then_id() -> None:
    detected = [
        {"kind": "ollama", "model": "llama3.2", "base_url": "http://x/v1"},
        {"id": "lmstudio", "model": "studio"},  # id fallback
        {"model": "orphan"},  # neither kind nor id -> skipped
    ]
    by_kind = mr._detected_by_kind(detected)
    assert set(by_kind) == {"ollama", "lmstudio"}


# --------------------------------------------------------------------------- #
# runner_advice — present (with/without model) + absent (install advice)
# --------------------------------------------------------------------------- #
def test_runner_advice_present_running_server() -> None:
    detected = [{"kind": "ollama", "model": "llama3.2", "base_url": "http://127.0.0.1:11434/v1"}]
    advice = mr.runner_advice(detected, {"vramMb": 8000, "gpuPresent": True})
    by_kind = {a["kind"]: a for a in advice}
    ollama = by_kind["ollama"]
    assert ollama["present"] is True
    assert ollama["installedModels"] == ["llama3.2"]
    assert "no install needed" in ollama["installHint"]
    assert ollama["recommendedModel"]["pull"] == "ollama pull qwen2.5:7b"
    # The absent runner advises install with the official link.
    lmstudio = by_kind["lmstudio"]
    assert lmstudio["present"] is False
    assert lmstudio["installedModels"] == []
    assert lmstudio["installUrl"] == "https://lmstudio.ai"
    assert "https://lmstudio.ai" in lmstudio["installHint"]
    assert "never auto-install" in lmstudio["installHint"]


def test_runner_advice_present_without_model_id() -> None:
    # A detected server with no usable model id still counts as present (no crash),
    # just with an empty installedModels list.
    detected = [{"kind": "ollama", "base_url": "http://127.0.0.1:11434/v1"}]
    [ollama] = [a for a in mr.runner_advice(detected, {}) if a["kind"] == "ollama"]
    assert ollama["present"] is True
    assert ollama["installedModels"] == []


def test_runner_advice_present_non_string_model_skipped() -> None:
    detected = [{"kind": "ollama", "model": 123}]
    [ollama] = [a for a in mr.runner_advice(detected, {}) if a["kind"] == "ollama"]
    assert ollama["installedModels"] == []


def test_runner_advice_none_detected_uses_default_base_url() -> None:
    [ollama] = [a for a in mr.runner_advice([], {}) if a["kind"] == "ollama"]
    assert ollama["baseUrl"] == "http://127.0.0.1:11434/v1"
    assert ollama["present"] is False


# --------------------------------------------------------------------------- #
# recommend_local_models — the full composed plan
# --------------------------------------------------------------------------- #
def test_recommend_local_models_full_plan() -> None:
    plan = mr.recommend_local_models(
        {"vramMb": 12000, "ramMb": 32000, "gpuPresent": True},
        [{"kind": "ollama", "model": "qwen2.5:14b"}],
    )
    assert plan["whisper"]["model"] == "large-v3-turbo"
    assert plan["llm"]["model"] == "qwen2.5:14b"
    assert [r["kind"] for r in plan["runners"]] == ["ollama", "lmstudio"]


def test_module_is_import_light() -> None:
    # No clock / socket leakage (mirrors the local_detect no-time guard).
    assert not hasattr(mr, "time")
    assert not hasattr(mr, "socket")


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    raise SystemExit(pytest.main([__file__, "-q"]))
