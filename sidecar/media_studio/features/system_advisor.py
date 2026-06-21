"""System Advisor — capability + preset advisor (the graphics-settings UI brain).

A USER-FACING capability that answers, in ONE pure call, "what can my machine
run, and which Phase-8 preset should I pick?". It is the brain behind a
graphics-settings-style panel: each of the manifest's 15 components (plus the
OpenCV/numpy floors) gets a *quality-vs-cost* verdict — ``fits`` (``ok``),
``tight`` (``degraded``), or ``wont_run`` (``unavailable``) — measured against
the user's available VRAM under the **sequential load -> infer -> unload** rule
(one heavy model resident at a time), and the runnable tiers are rolled up into a
recommended preset (Tier-0 numeric floor / Tier-1 multimodal / Tier-2 video-LLM).

Design (PURE logic + probe seams — NO heavy-ML imports, ever):

  * The per-component facts (VRAM@infer, on-disk size, license, what each model
    improves, approx speed) are encoded as a frozen :data:`COMPONENTS` table
    sourced directly from ``reports/PHASE8-SOTA-MANIFEST.md`` so the UI tooltips
    stay grounded in the manifest rows.
  * :func:`advise` is a deterministic decision table over hand-supplied
    ``probes`` (which deps are importable) + ``vram_mb`` + ``commercial`` +
    ``models_present``. It NEVER imports torch / transformers / pynvml — the
    caller supplies the booleans. In production a thin lazy ``importlib`` probe
    fills them (see :func:`probe_capabilities`); tests inject hand-built maps.
  * The hardware probe (GPU/VRAM, RAM, CPU count) lives behind injectable
    callable seams (:class:`HardwareProbe`). The default seams lazily try
    ``pynvml`` -> ``nvidia-smi`` -> ``torch.cuda`` for VRAM and ``psutil`` ->
    ``os`` for RAM, importing each ONLY inside the seam at runtime — so this
    module and its tests load none of them. Every seam is wrapped so a missing
    dependency degrades to "absent", never raises.

Output shape (:class:`AdvisorReport`) is a frozen-dataclass tree, JSON-safe for
the Wave-2 RPC the UI renders. Per-component / per-tier verdict rules follow the
design spec's ``advisor_contract`` exactly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from ..util import get_logger

log = get_logger("media_studio.features.system_advisor")

# A three-state verdict shared by components and tiers (wire-stable strings).
Verdict = Literal["ok", "degraded", "unavailable"]

# Hardware-probe seams: each returns its measurement (callable -> value). The
# defaults lazily try optional deps; tests inject fakes returning fixed numbers.
VramProbe = Callable[[], int | None]  # total GPU VRAM in MB, or None if no GPU.
RamProbe = Callable[[], int | None]  # total system RAM in MB, or None if unknown.
CpuProbe = Callable[[], int | None]  # logical CPU count, or None if unknown.

#: VRAM budget headroom: a component whose resident VRAM exceeds this fraction of
#: the budget is "tight" (``degraded``) even though it nominally fits.
TIGHT_FRACTION = 0.85


# --------------------------------------------------------------------------- #
# the manifest-sourced component table (pure data; grounds the UI tooltips)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComponentSpec:
    """Static facts about ONE component, lifted from the SOTA manifest row.

    ``requires`` is the import-availability key the ``probes`` map is keyed on
    (a single dependency family per component — e.g. ``"torch"``); the floors
    (motion/diversity) use ``"opencv"`` / ``"numpy"`` which are always present in
    the runtime. ``model_backed`` components also need their weights installed
    (the ``models_present`` map) to run while offline.
    """

    name: str
    requires: str  # probe key: which dep family must be importable
    model_backed: bool  # True => also needs downloaded weights (models_present)
    vram_mb: int  # resident VRAM @ infer (0 for CPU/no-model floors)
    size_mb: int  # on-disk artifact size (0 for no-download floors)
    license_commercial_ok: bool
    improves: str  # WHAT this component improves (human one-line)
    speed: str  # approx speed / cost note (human one-line)
    reason_ok: str  # tooltip when it runs fine
    reason_block: str  # tooltip when license/commercial blocks it


#: The 15 manifest components + the two zero-download CPU floors (motion gets the
#: ``opencv`` floor; diversity/ranker are pure numpy/sklearn-class). Field values
#: come verbatim from PHASE8-SOTA-MANIFEST.md (sizes, VRAM table, licenses).
COMPONENTS: tuple[ComponentSpec, ...] = (
    # ---- Tier-0 CPU floor (zero downloads) ----
    ComponentSpec(
        name="motion",
        requires="opencv",
        model_backed=False,
        vram_mb=0,
        size_mb=0,
        license_commercial_ok=True,
        improves="motion-energy scoring (abs-diff + Farneback flow)",
        speed="CPU, real-time, no download",
        reason_ok="Apache-2.0 OpenCV floor; CPU, zero download",
        reason_block="",
    ),
    ComponentSpec(
        name="diversity",
        requires="numpy",
        model_backed=False,
        vram_mb=0,
        size_mb=0,
        license_commercial_ok=True,
        improves="near-duplicate removal (DPP-MAP + MMR re-rank)",
        speed="CPU, instant, pure NumPy",
        reason_ok="pure NumPy (DPP/MMR); CPU, zero download",
        reason_block="",
    ),
    ComponentSpec(
        name="ranker",
        requires="lightgbm",
        model_backed=False,
        vram_mb=0,
        size_mb=3,
        license_commercial_ok=True,
        improves="learned re-rank from your feedback.jsonl (LambdaMART)",
        speed="CPU, trains in seconds on local feedback",
        reason_ok="MIT LightGBM; CPU, trains on local feedback",
        reason_block="",
    ),
    # ---- Tier-1 multimodal ----
    ComponentSpec(
        name="saliency",
        requires="torch",
        model_backed=True,
        vram_mb=1000,
        size_mb=36,
        license_commercial_ok=False,
        improves="no-face crop-track + per-frame interestingness (ViNet-S)",
        speed="GPU fp16, <1GB, >1000fps reported",
        reason_ok="ViNet-S fp16 <1GB fits 6GB",
        reason_block="CC-BY-NC-SA 4.0 non-commercial; local-only — dropped for commercial build",
    ),
    ComponentSpec(
        name="audio_saliency",
        requires="panns",
        model_backed=True,
        vram_mb=0,
        size_mb=300,
        license_commercial_ok=True,
        improves="laughter/applause/music/loudness peaks (PANNs CNN14)",
        speed="CPU-designed, no GPU needed",
        reason_ok="MIT PANNs CNN14; CPU, no GPU needed",
        reason_block="",
    ),
    ComponentSpec(
        name="scene_transnet",
        requires="torch",
        model_backed=True,
        vram_mb=1000,
        size_mb=40,
        license_commercial_ok=True,
        improves="dissolve/shot-cut detection PySceneDetect misses (TransNetV2)",
        speed="GPU fp16, <1GB, CPU fallback feasible",
        reason_ok="MIT TransNetV2 fp16 <1GB fits 6GB",
        reason_block="",
    ),
    ComponentSpec(
        name="vlm_backbone",
        requires="transformers",
        model_backed=True,
        vram_mb=2300,
        size_mb=4540,
        license_commercial_ok=True,
        improves="aesthetic + zero-shot interestingness + novelty (SigLIP-2, one load)",
        speed="GPU fp16 ~2.3GB; one load serves 3 sub-scores",
        reason_ok="Apache-2.0 SigLIP-2; fp16 ~2.3GB fits 6GB",
        reason_block="",
    ),
    ComponentSpec(
        name="quality_gate",
        requires="torch",
        model_backed=True,
        vram_mb=1900,
        size_mb=240,
        license_commercial_ok=False,
        improves="late demotion of shaky/blurry/compressed clips (DOVER)",
        speed="GPU fp16 <1.9GB; CPU 1.4s/vid (Mobile)",
        reason_ok="DOVER-Mobile fp16 <1.9GB fits 6GB",
        reason_block="S-Lab License 1.0 non-commercial; local-only — dropped for commercial build",
    ),
    ComponentSpec(
        name="aesthetic",
        requires="torch",
        model_backed=True,
        vram_mb=1700,
        size_mb=1,
        license_commercial_ok=False,
        improves="aesthetic scorer (Aesthetic-Predictor-V2.5 MLP head)",
        speed="GPU; as-shipped loads its own SigLIP-1 ~1.7GB",
        reason_ok="head reimplemented on shared SigLIP-2 (sidesteps AGPL)",
        reason_block="AGPL-3.0 network copyleft; reimplement head on SigLIP-2 for commercial",
    ),
    ComponentSpec(
        name="emotion",
        requires="onnxruntime",
        model_backed=True,
        vram_mb=500,
        size_mb=20,
        license_commercial_ok=True,
        improves="reaction/emotion peaks on faces (HSEmotion)",
        speed="ONNX, <0.5GB, CPU-capable",
        reason_ok="Apache-2.0 HSEmotion ONNX; <0.5GB",
        reason_block="",
    ),
    ComponentSpec(
        name="ocr",
        requires="onnxruntime",
        model_backed=True,
        vram_mb=1000,
        size_mb=20,
        license_commercial_ok=True,
        improves="on-screen/gameplay/tutorial text presence (RapidOCR)",
        speed="ONNX, <1GB, CPU-capable",
        reason_ok="Apache-2.0 RapidOCR ONNX; CPU-capable",
        reason_block="",
    ),
    # ---- SPEECH ----
    ComponentSpec(
        name="parakeet",
        requires="nemo",
        model_backed=True,
        vram_mb=3000,
        size_mb=2400,
        license_commercial_ok=True,
        improves="multilingual ASR incl. Romanian (Parakeet-TDT-0.6B-v3)",
        speed="GPU fp16 ~2-3GB; fits 6GB only with audio chunking",
        reason_ok="CC-BY-4.0 Parakeet; fits 6GB with audio chunking",
        reason_block="",
    ),
    ComponentSpec(
        name="ctc_aligner",
        requires="torch",
        model_backed=True,
        vram_mb=2000,
        size_mb=1200,
        license_commercial_ok=False,
        improves="karaoke word-timing 2nd pass (ctc-forced-aligner)",
        speed="GPU/CPU ~1-2GB; ONNX + PyTorch backends",
        reason_ok="BSD code; commercial via MIT wav2vec2 model override",
        reason_block="default mms-300m model CC-BY-NC-4.0; override with MIT wav2vec2 for commercial",
    ),
    ComponentSpec(
        name="pyannote",
        requires="torch",
        model_backed=True,
        vram_mb=2000,
        size_mb=1600,
        license_commercial_ok=True,
        improves="speaker diarization / speaker labels (pyannote 3.1)",
        speed="GPU fp16 ~1.5-2GB; CPU slower",
        reason_ok="MIT code+weights (GATED: HF token + accept two repos)",
        reason_block="",
    ),
    # ---- Tier-2 video-LLM ----
    ComponentSpec(
        name="smolvlm2",
        requires="transformers",
        model_backed=True,
        vram_mb=5200,
        size_mb=4500,
        license_commercial_ok=True,
        improves="Tier-2 video-LLM re-rank of top-K (SmolVLM2-2.2B)",
        speed="GPU bf16 ~5.2GB; 6GB-tight, runs ALONE, opt-in",
        reason_ok="Apache-2.0 SmolVLM2; bf16 ~5.2GB 6GB-tight, runs alone",
        reason_block="",
    ),
)

#: components keyed by name for O(1) lookup.
_BY_NAME: dict[str, ComponentSpec] = {c.name: c for c in COMPONENTS}


# --------------------------------------------------------------------------- #
# tiers (the runnable presets the UI offers)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TierSpec:
    """A runnable tier = a labelled bundle of component names (a UI preset)."""

    tier: int
    label: str
    preset: str  # the recommended_preset id this tier maps to
    components: tuple[str, ...]


#: Tier definitions (the UI presets). Tier-0 is the always-runnable CPU floor.
TIERS: tuple[TierSpec, ...] = (
    TierSpec(
        tier=0,
        label="Numeric floor (silent-OK, zero downloads)",
        preset="tier0-numeric",
        components=("motion", "diversity", "ranker"),
    ),
    TierSpec(
        tier=1,
        label="Multimodal (visual+audio+transcript)",
        preset="tier1-multimodal",
        components=("saliency", "audio_saliency", "scene_transnet", "vlm_backbone", "quality_gate"),
    ),
    TierSpec(
        tier=2,
        label="Video-LLM re-rank (heavy, opt-in)",
        preset="tier2-vlm",
        components=("smolvlm2",),
    ),
)

#: Standing notes surfaced verbatim in the UI (the manifest's hard rules + alerts).
NOTES: tuple[str, ...] = (
    "Parakeet ASR fits only with audio CHUNKING",
    "SmolVLM2 int8 (bnb) broken — BF16+unload or GGUF",
    "Commercial build: drop DOVER/ViNet/Aesthetic or replace (see license alerts)",
)


# --------------------------------------------------------------------------- #
# the report shape (frozen tree, JSON-safe for the Wave-2 RPC)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComponentStatus:
    """One component's verdict for the UI (mirrors the advisor_contract shape)."""

    name: str
    present: bool
    verdict: Verdict
    vram_mb: int | None
    license_commercial_ok: bool
    reason: str


@dataclass(frozen=True)
class TierStatus:
    """One tier's rolled-up verdict + its member component names."""

    tier: int
    label: str
    verdict: Verdict
    components: tuple[str, ...]


@dataclass(frozen=True)
class AdvisorReport:
    """The full advisor result — a JSON-serializable frozen tree for the UI."""

    components: tuple[ComponentStatus, ...]
    tiers: tuple[TierStatus, ...]
    recommended_preset: str
    vram_budget_mb: int
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HardwareInfo:
    """Probed hardware facts (all optional — None when a probe found nothing)."""

    vram_mb: int | None
    ram_mb: int | None
    cpu_count: int | None
    gpu_present: bool


# --------------------------------------------------------------------------- #
# pure verdict logic
# --------------------------------------------------------------------------- #
def _component_verdict(
    spec: ComponentSpec,
    *,
    importable: bool,
    model_installed: bool,
    offline: bool,
    vram_budget_mb: int,
    commercial: bool,
) -> tuple[Verdict, str]:
    """Decide ONE component's (verdict, reason) per the advisor_contract rule.

    ``unavailable`` if its dep isn't importable, OR (model-backed and not
    installed while offline), OR (commercial build and the license forbids it).
    ``degraded`` if it runs but is VRAM-tight (resident > budget * TIGHT_FRACTION)
    — that is the only fallback/tight case here. Otherwise ``ok``.
    """
    if commercial and not spec.license_commercial_ok:
        return "unavailable", spec.reason_block
    if not importable:
        return "unavailable", f"{spec.requires} not importable — install the dependency to enable {spec.name}"
    if spec.model_backed and offline and not model_installed:
        return "unavailable", f"model weights for {spec.name} not installed and Offline mode is on (download blocked)"
    if spec.vram_mb > vram_budget_mb:
        return "unavailable", f"needs ~{spec.vram_mb}MB VRAM, over the {vram_budget_mb}MB budget"
    if spec.vram_mb > int(vram_budget_mb * TIGHT_FRACTION):
        return "degraded", f"{spec.reason_ok} — VRAM-tight (~{spec.vram_mb}MB of {vram_budget_mb}MB budget)"
    return "ok", spec.reason_ok


def _tier_verdict(component_verdicts: Sequence[Verdict]) -> Verdict:
    """Roll component verdicts up to a tier verdict.

    ``ok`` only if ALL run cleanly; ``unavailable`` if NONE run; ``degraded`` if
    at least one runs but some are degraded or unavailable.
    """
    if not component_verdicts or all(v == "unavailable" for v in component_verdicts):
        return "unavailable"
    if all(v == "ok" for v in component_verdicts):
        return "ok"
    return "degraded"


def advise(
    *,
    probes: Mapping[str, bool],
    vram_mb: int,
    commercial: bool = False,
    models_present: Mapping[str, bool] | None = None,
    offline: bool = False,
) -> AdvisorReport:
    """Compute the full :class:`AdvisorReport` from hand-supplied capability facts.

    ``probes`` maps a component's ``requires`` key (e.g. ``"torch"``,
    ``"opencv"``) -> is it importable. Missing keys default to absent. ``vram_mb``
    is the available VRAM budget. ``models_present`` maps component name -> are
    its weights installed (only consulted for model-backed components when
    ``offline``). ``commercial`` flips non-commercial-licensed components to
    ``unavailable``. Pure: imports nothing heavy.
    """
    models = models_present or {}
    statuses: list[ComponentStatus] = []
    verdict_by_name: dict[str, Verdict] = {}
    for spec in COMPONENTS:
        importable = bool(probes.get(spec.requires, False))
        installed = bool(models.get(spec.name, False))
        verdict, reason = _component_verdict(
            spec,
            importable=importable,
            model_installed=installed,
            offline=offline,
            vram_budget_mb=vram_mb,
            commercial=commercial,
        )
        verdict_by_name[spec.name] = verdict
        statuses.append(
            ComponentStatus(
                name=spec.name,
                present=verdict != "unavailable",
                verdict=verdict,
                vram_mb=spec.vram_mb if spec.vram_mb > 0 else None,
                license_commercial_ok=spec.license_commercial_ok,
                reason=reason,
            )
        )

    tiers: list[TierStatus] = []
    for tspec in TIERS:
        member_verdicts: list[Verdict] = [verdict_by_name[name] for name in tspec.components]
        tiers.append(
            TierStatus(
                tier=tspec.tier,
                label=tspec.label,
                verdict=_tier_verdict(member_verdicts),
                components=tspec.components,
            )
        )

    report = AdvisorReport(
        components=tuple(statuses),
        tiers=tuple(tiers),
        recommended_preset="tier0-numeric",
        vram_budget_mb=vram_mb,
        notes=NOTES,
    )
    return AdvisorReport(
        components=report.components,
        tiers=report.tiers,
        recommended_preset=recommended_preset(report),
        vram_budget_mb=report.vram_budget_mb,
        notes=report.notes,
    )


def recommended_preset(report: AdvisorReport) -> str:
    """The highest tier whose verdict is ``ok`` -> its preset id.

    Always at least ``tier0-numeric`` (the CPU floor with zero downloads is the
    guaranteed baseline). Walks tiers high -> low and returns the first fully-OK
    tier's preset.
    """
    preset_by_tier = {t.tier: t.preset for t in TIERS}
    for tstatus in sorted(report.tiers, key=lambda t: t.tier, reverse=True):
        if tstatus.verdict == "ok":
            return preset_by_tier.get(tstatus.tier, "tier0-numeric")
    return "tier0-numeric"


# --------------------------------------------------------------------------- #
# hardware probe seams (lazy optional deps; defaults degrade, never raise)
# --------------------------------------------------------------------------- #
class HardwareProbe:
    """Bundles the three hardware-probe seams (VRAM / RAM / CPU).

    Each seam is a plain callable; the defaults lazily try optional deps and
    swallow any failure (returning None / a degraded value). Tests inject fakes
    returning fixed numbers — no GPU, no psutil, no torch required.
    """

    def __init__(
        self,
        *,
        vram_probe: VramProbe | None = None,
        ram_probe: RamProbe | None = None,
        cpu_probe: CpuProbe | None = None,
    ) -> None:
        self._vram_probe = vram_probe or default_vram_probe
        self._ram_probe = ram_probe or default_ram_probe
        self._cpu_probe = cpu_probe or default_cpu_probe

    def detect(self) -> HardwareInfo:
        """Run all three seams (each fail-safe) -> a :class:`HardwareInfo`."""
        vram = self._call(self._vram_probe)
        ram = self._call(self._ram_probe)
        cpu = self._call(self._cpu_probe)
        return HardwareInfo(
            vram_mb=vram,
            ram_mb=ram,
            cpu_count=cpu,
            gpu_present=vram is not None,
        )

    @staticmethod
    def _call(probe: Callable[[], int | None]) -> int | None:
        """Invoke a probe, mapping any failure to None (fail-open)."""
        try:
            return probe()
        except Exception:  # noqa: BLE001 - a probe must never crash the advisor
            log.debug("hardware probe failed; treating as absent", exc_info=True)
            return None


def default_vram_probe() -> int | None:
    """Total GPU VRAM in MB via pynvml -> nvidia-smi -> torch.cuda (lazy, optional).

    Tries the lightest reliable source first and falls through on any failure,
    so a machine with no GPU (or none of these deps) returns None. Heavy imports
    happen INSIDE this function only — never at module load.
    """
    for source in (_vram_from_pynvml, _vram_from_nvidia_smi, _vram_from_torch):
        try:
            value = source()
        except Exception:  # noqa: BLE001 - fall through to the next source
            value = None
        if value is not None:
            return value
    return None


def _vram_from_pynvml() -> int | None:
    """VRAM (MB) of GPU 0 via pynvml, or None if unavailable."""
    import pynvml  # noqa: PLC0415 - optional, lazy  # pyright: ignore[reportMissingImports]

    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.total // (1024 * 1024))
    finally:
        pynvml.nvmlShutdown()


def _vram_from_nvidia_smi(
    run: Callable[..., object] | None = None,
) -> int | None:
    """VRAM (MB) of GPU 0 by parsing ``nvidia-smi`` output, or None.

    ``run`` is an injectable subprocess seam (defaults to a lazy
    ``subprocess.run`` with an argv LIST, never ``shell=True``).
    """
    runner = run or _default_smi_runner
    out = runner()
    text = getattr(out, "stdout", out)
    if not isinstance(text, str):
        return None
    first = text.strip().splitlines()[0] if text.strip() else ""
    digits = first.strip().split()[0] if first.strip() else ""
    return int(digits) if digits.isdigit() else None


def _default_smi_runner() -> object:
    """Lazy ``nvidia-smi`` invocation (argv list, captured stdout)."""
    import subprocess  # noqa: PLC0415, S404 - argv-list only, never shell=True

    return subprocess.run(  # noqa: S603 - fixed argv, no user input, no shell
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _vram_from_torch() -> int | None:
    """VRAM (MB) of CUDA device 0 via torch, or None if torch/CUDA absent."""
    import torch  # noqa: PLC0415 - optional, lazy  # pyright: ignore[reportMissingImports]

    if not torch.cuda.is_available():
        return None
    props = torch.cuda.get_device_properties(0)
    return int(props.total_memory // (1024 * 1024))


def default_ram_probe() -> int | None:
    """Total system RAM in MB via psutil, else os.sysconf, else None (lazy)."""
    try:
        import psutil  # noqa: PLC0415 - optional, lazy  # pyright: ignore[reportMissingImports]

        return int(psutil.virtual_memory().total // (1024 * 1024))
    except Exception:  # noqa: BLE001 - fall back to os
        return _ram_from_os()


def _ram_from_os() -> int | None:
    """Total RAM (MB) via ``os.sysconf`` (POSIX), or None where unsupported."""
    import os  # noqa: PLC0415 - stdlib, lazy for symmetry

    try:
        pages = os.sysconf("SC_PHYS_PAGES")  # pyright: ignore[reportAttributeAccessIssue]
        page_size = os.sysconf("SC_PAGE_SIZE")  # pyright: ignore[reportAttributeAccessIssue]
    except (AttributeError, ValueError, OSError):
        return None
    return int((pages * page_size) // (1024 * 1024))


def default_cpu_probe() -> int | None:
    """Logical CPU count via ``os.cpu_count`` (lazy; None when undeterminable)."""
    import os  # noqa: PLC0415 - stdlib, lazy for symmetry

    return os.cpu_count()


def probe_capabilities(
    *,
    find_spec: Callable[[str], object] | None = None,
) -> dict[str, bool]:
    """Build the ``probes`` import-availability map WITHOUT importing heavy deps.

    Uses ``importlib.util.find_spec`` (an injectable seam) so nothing is actually
    imported — a spec probe only checks installability. Each component's
    ``requires`` family maps to a real import name here. Defaults cover the
    standard runtime; tests inject a fake ``find_spec`` to simulate any machine.
    """
    spec_fn = find_spec or _default_find_spec
    #: probe-key -> the module name whose spec we look up.
    import_names: dict[str, str] = {
        "opencv": "cv2",
        "numpy": "numpy",
        "lightgbm": "lightgbm",
        "torch": "torch",
        "transformers": "transformers",
        "onnxruntime": "onnxruntime",
        "panns": "panns_inference",
        "nemo": "nemo",
    }
    out: dict[str, bool] = {}
    for key, module_name in import_names.items():
        try:
            out[key] = spec_fn(module_name) is not None
        except Exception:  # noqa: BLE001 - a bad spec lookup => treat as absent
            out[key] = False
    return out


def _default_find_spec(module_name: str) -> object:
    """Lazy ``importlib.util.find_spec`` (kept behind a seam for testing)."""
    import importlib.util  # noqa: PLC0415 - stdlib, lazy for symmetry

    return importlib.util.find_spec(module_name)


def advise_for_hardware(
    *,
    hardware: HardwareInfo | None = None,
    probe: HardwareProbe | None = None,
    probes: Mapping[str, bool] | None = None,
    find_spec: Callable[[str], object] | None = None,
    commercial: bool = False,
    models_present: Mapping[str, bool] | None = None,
    offline: bool = False,
    fallback_vram_mb: int = 0,
) -> AdvisorReport:
    """End-to-end convenience: probe hardware + deps, then :func:`advise`.

    Resolves a VRAM budget from ``hardware`` (or by running ``probe``), an
    import map from ``probes`` (or by running :func:`probe_capabilities` with the
    injected ``find_spec``), and feeds them to :func:`advise`. A machine with no
    GPU falls back to ``fallback_vram_mb`` (0 by default -> only the CPU floor is
    ``ok``). Every heavy probe is behind a seam; nothing heavy is imported.
    """
    hw = hardware if hardware is not None else (probe or HardwareProbe()).detect()
    vram_budget = hw.vram_mb if hw.vram_mb is not None else fallback_vram_mb
    import_map = probes if probes is not None else probe_capabilities(find_spec=find_spec)
    return advise(
        probes=import_map,
        vram_mb=vram_budget,
        commercial=commercial,
        models_present=models_present,
        offline=offline,
    )


__all__ = [
    "COMPONENTS",
    "NOTES",
    "TIERS",
    "TIGHT_FRACTION",
    "AdvisorReport",
    "ComponentSpec",
    "ComponentStatus",
    "HardwareInfo",
    "HardwareProbe",
    "TierSpec",
    "TierStatus",
    "Verdict",
    "advise",
    "advise_for_hardware",
    "default_cpu_probe",
    "default_ram_probe",
    "default_vram_probe",
    "probe_capabilities",
    "recommended_preset",
]
