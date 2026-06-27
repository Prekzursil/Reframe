"""Device-ranked LOCAL model recommendation + local-runner advice (WU-models/device).

The pure brain behind two V1 surfaces (docs/V1-GRILL-DECISIONS.md (f)/(h)):

  * **Device-ranked model recommendation** ("recommended for your machine: X
    because RAM/VRAM Y"): given the host's probed VRAM / RAM / GPU, pick the best
    *whisper* ASR variant AND the best LLM that fits — each with a human reason
    that NAMES the device numbers. This is the "X because Y" string the renderer
    surfaces verbatim (deliverable G-7/8/9, extended to local runners).
  * **Local-runner advice** for Ollama / LM Studio: for each known runner, say
    whether it is RUNNING (folded in from :func:`local_detect.detect_local_servers`),
    which model(s) it already serves, the device-fit model to PULL (with a copy-able
    pull hint), and — when absent — the official INSTALL link (advice, never an
    auto-install). Detection/recommendation are best-effort and NEVER raise.

PURE + import-light: this module imports nothing heavy, opens no socket, and reads
no clock. Hardware comes in as the plain ``system.probe`` wire dict
(``{vramMb, ramMb, gpuPresent}``) and detected servers as the
:class:`local_detect.PoolEntry` wire dicts — so every input is a JSON-safe value a
test injects directly (mirrors :mod:`media_studio.features.recommender`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

# --------------------------------------------------------------------------- #
# device-ranked model ladders (pure data; best-first within each ladder)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelTier:
    """One rung of a device-fit ladder: a model + the floor it needs to run.

    ``min_vram_mb`` is the GPU VRAM a fp16/quant load needs; ``min_ram_mb`` the
    system RAM a CPU run needs. The LAST tier of every ladder is the guaranteed
    floor (both floors ``0``) so a pick always exists, even on an unknown device.
    """

    model: str
    label: str
    min_vram_mb: int
    min_ram_mb: int


#: Whisper (faster-whisper) ASR variants, best -> floor. VRAM/RAM floors are the
#: rough resident cost of each model size; large-v3-turbo is the quality pick when
#: a GPU can hold it, small/base the CPU-friendly floors.
WHISPER_LADDER: tuple[ModelTier, ...] = (
    ModelTier("large-v3-turbo", "Whisper large-v3-turbo", min_vram_mb=2000, min_ram_mb=12000),
    ModelTier("medium", "Whisper medium", min_vram_mb=1200, min_ram_mb=8000),
    ModelTier("small", "Whisper small", min_vram_mb=600, min_ram_mb=4000),
    ModelTier("base", "Whisper base", min_vram_mb=0, min_ram_mb=0),
)

#: LLM (Ollama / LM Studio GGUF) variants, best -> floor. Floors are the rough q4
#: resident VRAM per model; the 1.5B floor always fits (CPU backstop).
LLM_LADDER: tuple[ModelTier, ...] = (
    ModelTier("qwen2.5:14b", "Qwen2.5 14B", min_vram_mb=11000, min_ram_mb=32000),
    ModelTier("qwen2.5:7b", "Qwen2.5 7B", min_vram_mb=6000, min_ram_mb=16000),
    ModelTier("qwen2.5:3b", "Qwen2.5 3B", min_vram_mb=3000, min_ram_mb=8000),
    ModelTier("qwen2.5:1.5b", "Qwen2.5 1.5B", min_vram_mb=0, min_ram_mb=0),
)


# --------------------------------------------------------------------------- #
# known local runners (pure data)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunnerSpec:
    """Static facts about one known local runner (Ollama / LM Studio)."""

    kind: str
    label: str
    base_url: str
    install_url: str


#: The two well-known OpenAI-compatible local runners V1 advises on. ``base_url``
#: mirrors :mod:`local_detect`'s probe defaults; ``install_url`` is the official
#: download page (advice only — V1 NEVER auto-installs a runner).
RUNNERS: tuple[RunnerSpec, ...] = (
    RunnerSpec("ollama", "Ollama", "http://127.0.0.1:11434/v1", "https://ollama.com/download"),
    RunnerSpec("lmstudio", "LM Studio", "http://127.0.0.1:1234/v1", "https://lmstudio.ai"),
)


# --------------------------------------------------------------------------- #
# typed wire result shapes
# --------------------------------------------------------------------------- #


class ModelReco(TypedDict):
    """A device-ranked model pick + the "X because RAM/VRAM Y" reason."""

    model: str
    label: str
    reason: str


class RunnerModelReco(ModelReco):
    """A runner's pull recommendation: a :class:`ModelReco` + a copy-able pull hint."""

    pull: str


class RunnerAdvice(TypedDict):
    """Per-runner detect + recommend + install advice (the UI's runner card)."""

    kind: str
    label: str
    present: bool
    baseUrl: str
    installUrl: str
    installHint: str
    installedModels: list[str]
    recommendedModel: RunnerModelReco


class LocalModelPlan(TypedDict):
    """The full local-models plan the ``models.runners`` RPC returns."""

    whisper: ModelReco
    llm: ModelReco
    runners: list[RunnerAdvice]


# --------------------------------------------------------------------------- #
# device-fit picking (pure)
# --------------------------------------------------------------------------- #


def _as_int(value: Any) -> int | None:
    """Coerce a wire number to ``int``, or ``None`` for missing/garbage values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _device_reason(*, vram_mb: int | None, ram_mb: int | None, gpu_present: bool) -> str:
    """The "because <device>" clause naming the numbers the pick was made against."""
    if gpu_present and vram_mb is not None:
        return f"fits your GPU ({vram_mb} MB VRAM)"
    if ram_mb is not None:
        return f"fits your CPU ({ram_mb} MB RAM)"
    return "device not detected — using the safe baseline"


def _fits(tier: ModelTier, *, vram_mb: int | None, ram_mb: int | None, gpu_present: bool) -> bool:
    """Whether ``tier`` runs on the device (GPU VRAM when present, else CPU RAM)."""
    if gpu_present and vram_mb is not None:
        return vram_mb >= tier.min_vram_mb
    if ram_mb is not None:
        return ram_mb >= tier.min_ram_mb
    return tier.min_vram_mb == 0 and tier.min_ram_mb == 0


def _pick(ladder: tuple[ModelTier, ...], *, vram_mb: int | None, ram_mb: int | None, gpu_present: bool) -> ModelTier:
    """The best (highest) ladder rung that fits the device; the floor otherwise.

    Walks best -> worst and returns the first fitting rung. The ladder's last rung
    is the guaranteed floor (both floors ``0``), so when nothing else fits — or the
    device is wholly unknown — that floor is returned (a pick always exists).
    """
    for tier in ladder:
        if _fits(tier, vram_mb=vram_mb, ram_mb=ram_mb, gpu_present=gpu_present):
            return tier
    return ladder[-1]  # pragma: no cover -- the floor rung always _fits; defensive


def _reco_for(ladder: tuple[ModelTier, ...], hardware: dict[str, Any]) -> ModelReco:
    """Pick a ladder's device-fit model and build its ``{model,label,reason}``."""
    vram_mb = _as_int(hardware.get("vramMb"))
    ram_mb = _as_int(hardware.get("ramMb"))
    gpu_present = bool(hardware.get("gpuPresent"))
    tier = _pick(ladder, vram_mb=vram_mb, ram_mb=ram_mb, gpu_present=gpu_present)
    reason = f"{tier.label} — {_device_reason(vram_mb=vram_mb, ram_mb=ram_mb, gpu_present=gpu_present)}"
    return ModelReco(model=tier.model, label=tier.label, reason=reason)


def recommend_whisper(hardware: dict[str, Any]) -> ModelReco:
    """Device-ranked whisper (ASR) recommendation (the "X because Y" string)."""
    return _reco_for(WHISPER_LADDER, hardware)


def recommend_llm(hardware: dict[str, Any]) -> ModelReco:
    """Device-ranked LLM recommendation (the runner pull target's "X because Y")."""
    return _reco_for(LLM_LADDER, hardware)


# --------------------------------------------------------------------------- #
# local-runner advice (pure; folds in detected servers)
# --------------------------------------------------------------------------- #


def _pull_hint(kind: str, model: str) -> str:
    """The copy-able pull instruction for a runner kind (advice text, no exec)."""
    if kind == "ollama":
        return f"ollama pull {model}"
    return f"Search '{model}' in the LM Studio model browser to download it"


def _detected_by_kind(detected_local: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index detected pool-entry dicts by their runner kind (last wins, robust)."""
    by_kind: dict[str, dict[str, Any]] = {}
    for entry in detected_local:
        kind = entry.get("kind") or entry.get("id")
        if isinstance(kind, str) and kind:
            by_kind[kind] = entry
    return by_kind


def _runner_advice_for(spec: RunnerSpec, entry: dict[str, Any] | None, llm: ModelReco) -> RunnerAdvice:
    """Build one runner's advice card from its spec + (optional) detected entry."""
    present = entry is not None
    base_url = str(entry.get("base_url") or spec.base_url) if entry is not None else spec.base_url
    installed_models: list[str] = []
    if entry is not None:
        model = entry.get("model")
        if isinstance(model, str) and model:
            installed_models.append(model)
    install_hint = (
        f"{spec.label} is running — no install needed."
        if present
        else f"{spec.label} is not running. Install it from {spec.install_url} (we never auto-install)."
    )
    recommended = RunnerModelReco(
        model=llm["model"],
        label=llm["label"],
        reason=llm["reason"],
        pull=_pull_hint(spec.kind, llm["model"]),
    )
    return RunnerAdvice(
        kind=spec.kind,
        label=spec.label,
        present=present,
        baseUrl=base_url,
        installUrl=spec.install_url,
        installHint=install_hint,
        installedModels=installed_models,
        recommendedModel=recommended,
    )


def runner_advice(detected_local: list[dict[str, Any]], hardware: dict[str, Any]) -> list[RunnerAdvice]:
    """Per-known-runner detect + device-fit pull recommendation + install advice."""
    by_kind = _detected_by_kind(detected_local)
    llm = recommend_llm(hardware)
    return [_runner_advice_for(spec, by_kind.get(spec.kind), llm) for spec in RUNNERS]


def recommend_local_models(hardware: dict[str, Any], detected_local: list[dict[str, Any]]) -> LocalModelPlan:
    """Compose the full local-models plan: device whisper + LLM + per-runner advice."""
    return LocalModelPlan(
        whisper=recommend_whisper(hardware),
        llm=recommend_llm(hardware),
        runners=runner_advice(detected_local, hardware),
    )


__all__ = [
    "LLM_LADDER",
    "RUNNERS",
    "WHISPER_LADDER",
    "LocalModelPlan",
    "ModelReco",
    "ModelTier",
    "RunnerAdvice",
    "RunnerModelReco",
    "RunnerSpec",
    "recommend_llm",
    "recommend_local_models",
    "recommend_whisper",
    "runner_advice",
]
