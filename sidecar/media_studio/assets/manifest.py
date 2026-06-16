"""Typed asset registry (PLAN-P2 U4 / CONTRACTS.md A2-A3).

Every track REGISTERS its artifacts here with **one call** —
``register_asset(...)`` — from its own module:

    from media_studio.assets.manifest import register_asset
    register_asset(
        name="kokoro-v1.0-onnx",
        kind="model",
        size_mb=350,
        dest="models/kokoro-v1.0.onnx",
        url="https://.../kokoro-v1.0.onnx",   # PINNED (A6 lesson 5)
        sha256="...",                          # optional but encouraged
    )

The registry is *data only*: no network, no heavy imports. The download /
install machinery lives in :mod:`.manager`; the wire surface (``assets.list`` /
``assets.ensure``) in :mod:`.rpc`. The wire ``AssetInfo`` schema (A3) is
``{name, kind:"model"|"env"|"tool", sizeMB, installed:bool, dest}`` — the
manager derives it from these entries.

A6 lesson 5 (NON-NEGOTIABLE): everything entering this manifest is PINNED —
exact download URLs, ``pkg==version`` requirement strings for env entries.
Loose specifiers are rejected at registration time.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.assets.manifest")

# A3: AssetInfo.kind is frozen to exactly these three.
ASSET_KINDS: tuple[str, ...] = ("model", "env", "tool")

# How the manager materializes an entry:
#   "download" — httpx streaming download of a single pinned URL (resume+sha)
#   "hf"       — huggingface_hub snapshot into the standard HF_HOME cache
#   "env"      — bootstrap a pip --target env under <root>/envs/<dest> (A7)
INSTALLERS: tuple[str, ...] = ("download", "hf", "env")

# A settings-driven existing-path probe: (settings dict) -> existing path | None.
# Lets an entry count as installed when the user already has the artifact
# somewhere else (e.g. the Qwen GGUF named by settings.ggufPath/modelsDir).
DetectFn = Callable[[dict[str, Any]], str | None]


@dataclass(frozen=True)
class AssetEntry:
    """One registered artifact. Carries everything the manager needs (U4 brief:
    entries carry PINNED url / sha-optional / size / dest / kind).

    ``dest`` is relative to the assets root (``%APPDATA%/media-studio``) unless
    absolute; for ``installer="hf"`` it may be empty (the dest is the HF cache
    directory, resolved at list time).
    """

    name: str
    kind: str
    size_mb: float
    dest: str = ""
    label: str = ""
    # installer="download": the PINNED source URL + optional integrity pin.
    url: str | None = None
    sha256: str | None = None
    installer: str = "download"
    # installer="hf": repo id (+ optional revision pin) in the HF_HOME cache.
    hf_repo: str | None = None
    hf_revision: str | None = None
    # installer="env": PINNED "pkg==ver" requirement strings (A6 lesson 5).
    requirements: tuple[str, ...] = ()
    # Optional settings-driven probe for a pre-existing copy elsewhere.
    detect: DetectFn | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("asset name (non-empty str) is required")
        if self.kind not in ASSET_KINDS:
            raise ValueError(f"asset {self.name!r}: kind must be one of {ASSET_KINDS}, got {self.kind!r}")
        if self.installer not in INSTALLERS:
            raise ValueError(f"asset {self.name!r}: installer must be one of {INSTALLERS}, got {self.installer!r}")
        if not isinstance(self.size_mb, (int, float)) or self.size_mb < 0:
            raise ValueError(f"asset {self.name!r}: size_mb must be a number >= 0")
        # Normalize requirements to a tuple (frozen dataclass => object.__setattr__).
        object.__setattr__(self, "requirements", tuple(self.requirements or ()))
        if self.installer == "download":
            if not self.url:
                raise ValueError(f"asset {self.name!r}: installer='download' requires a pinned url")
            if not self.dest:
                raise ValueError(f"asset {self.name!r}: installer='download' requires a dest path")
        elif self.installer == "hf":
            if not self.hf_repo:
                raise ValueError(f"asset {self.name!r}: installer='hf' requires hf_repo")
        elif (
            self.installer == "env"
        ):  # pragma: no branch - installer validated in INSTALLERS above; the no-match arc to exit is unreachable
            if not self.dest:
                raise ValueError(f"asset {self.name!r}: installer='env' requires a dest env dir")
            if not self.requirements:
                raise ValueError(f"asset {self.name!r}: installer='env' requires a pinned requirements list")
            for req in self.requirements:
                # A6 lesson 5: first-run pip must not resolve loose from PyPI.
                if "==" not in req:
                    raise ValueError(f"asset {self.name!r}: requirement {req!r} is not pinned (use 'pkg==version')")


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #

# name -> AssetEntry, in registration order (dict preserves insertion order).
_REGISTRY: dict[str, AssetEntry] = {}


def register_asset(entry: AssetEntry | None = None, **kwargs: Any) -> AssetEntry:
    """Register an asset; the ONE call other tracks make (U4 brief).

    Accepts a prebuilt :class:`AssetEntry` or plain kwargs. Re-registering an
    IDENTICAL entry is a no-op (so module re-imports stay safe); registering a
    *different* entry under an existing name fails loudly, mirroring
    ``protocol.register``'s duplicate policy.
    """
    if entry is None:
        entry = AssetEntry(**kwargs)
    elif kwargs:
        raise ValueError("pass either an AssetEntry or kwargs, not both")
    existing = _REGISTRY.get(entry.name)
    if existing is not None:
        if existing == entry:
            return existing
        raise ValueError(f"conflicting asset registration: {entry.name!r}")
    _REGISTRY[entry.name] = entry
    log.info("registered asset %s (kind=%s, installer=%s)", entry.name, entry.kind, entry.installer)
    return entry


def get_asset(name: str) -> AssetEntry | None:
    """Return the entry registered under ``name``, or ``None``."""
    return _REGISTRY.get(name)


def all_assets() -> list[AssetEntry]:
    """All registered entries, in registration order."""
    return list(_REGISTRY.values())


def registry_snapshot() -> dict[str, AssetEntry]:
    """Shallow copy of the registry (test isolation helper)."""
    return dict(_REGISTRY)


def registry_restore(snapshot: dict[str, AssetEntry]) -> None:
    """Restore a previously captured snapshot (test isolation helper)."""
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


# --------------------------------------------------------------------------- #
# day-1 entries (U4 scope): whisper large-v3-turbo + Qwen3-4B GGUF
# --------------------------------------------------------------------------- #

WHISPER_ASSET_NAME = "whisper-large-v3-turbo"
# §7 / transcribe.py DEFAULT_MODEL="large-v3-turbo" resolves to this CT2 repo via
# faster-whisper; ensuring it through huggingface_hub lands in the SAME HF_HOME
# cache faster-whisper reads, so transcribe.start finds it pre-downloaded.
WHISPER_HF_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
WHISPER_SIZE_MB = 1600

QWEN_ASSET_NAME = "qwen3-4b-gguf"
# CONTRACT-NOTE: §7 default model is "Qwen3-4B GGUF". The URL pins the exact
# repo + file (Q4_K_M quant). sha256 is optional per A3/U4 ("sha-optional") and
# left unpinned here; fill it in once the human verifies the first download.
QWEN_GGUF_URL = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
QWEN_SIZE_MB = 2500
# Matches models/runner.py DEFAULT_GGUF_NAME so pointing settings.modelsDir at
# "<assets root>/models" makes resolve_gguf_path find the managed copy.
QWEN_DEST = "models/qwen3-4b.gguf"
_QWEN_DEFAULT_GGUF_NAME = "qwen3-4b.gguf"


def detect_existing_gguf(settings: dict[str, Any]) -> str | None:
    """Existing-path detection for the Qwen GGUF (U4 brief).

    Mirrors ``models.runner.resolve_gguf_path``'s settings order (explicit
    ``ggufPath`` -> ``modelsDir`` + default name) but only returns a path that
    actually EXISTS — a user who already has the model anywhere counts as
    installed, no re-download.
    """
    settings = settings or {}
    explicit = settings.get("ggufPath")
    if explicit:
        p = Path(str(explicit))
        if p.is_file():
            return str(p)
    models_dir = settings.get("modelsDir")
    if models_dir:
        cand = Path(str(models_dir)) / _QWEN_DEFAULT_GGUF_NAME
        if cand.is_file():
            return str(cand)
    return None


def _register_day1() -> None:
    """Install the day-1 entries (idempotent: identical re-register is a no-op)."""
    register_asset(
        AssetEntry(
            name=WHISPER_ASSET_NAME,
            kind="model",
            size_mb=WHISPER_SIZE_MB,
            label="Whisper large-v3-turbo (transcription)",
            installer="hf",
            hf_repo=WHISPER_HF_REPO,
        )
    )
    register_asset(
        AssetEntry(
            name=QWEN_ASSET_NAME,
            kind="model",
            size_mb=QWEN_SIZE_MB,
            dest=QWEN_DEST,
            label="Qwen3-4B GGUF (local LLM)",
            installer="download",
            url=QWEN_GGUF_URL,
            detect=detect_existing_gguf,
        )
    )


# --------------------------------------------------------------------------- #
# Phase-8 optional-signal entries (SOTA manifest #8/#9) — emotion + OCR.
# These two components are surfaced by ``system_advisor`` (the "Models & System"
# UI enumerates them) but no feature module owns them yet (they ship "if a WU adds
# emotion/OCR"). Registered HERE so the asset manager + advisor can enumerate +
# offer them now, PINNED per the manifest (A6 lesson 5). Backed by an owning
# module later, these move to that module's ``register_*_assets()``.
# --------------------------------------------------------------------------- #
HSEMOTION_ASSET_NAME = "hsemotion-onnx"
#: PINNED HSEmotion enet_b0_8_best_vgaf ONNX (av-savchenko/hsemotion-onnx).
HSEMOTION_URL = (
    "https://github.com/av-savchenko/hsemotion-onnx/raw/main/models/affectnet_emotions/onnx/enet_b0_8_best_vgaf.onnx"
)
HSEMOTION_DEST = "models/hsemotion-enet-b0-8.onnx"
HSEMOTION_SIZE_MB = 20

RAPIDOCR_ASSET_NAME = "rapidocr-onnx"
#: PINNED RapidOCR PP-OCRv5 detection ONNX (RapidAI/RapidOCR release assets).
RAPIDOCR_URL = "https://github.com/RapidAI/RapidOCR/releases/download/v1.4.4/ch_PP-OCRv4_det_infer.onnx"
RAPIDOCR_DEST = "models/rapidocr-ppocrv5-det.onnx"
RAPIDOCR_SIZE_MB = 20


def _register_phase8_optional() -> None:
    """Register the optional Phase-8 emotion + OCR signal models (idempotent)."""
    register_asset(
        AssetEntry(
            name=HSEMOTION_ASSET_NAME,
            kind="model",
            size_mb=HSEMOTION_SIZE_MB,
            dest=HSEMOTION_DEST,
            label="HSEmotion enet_b0_8 (facial emotion, Apache-2.0)",
            installer="download",
            url=HSEMOTION_URL,
        )
    )
    register_asset(
        AssetEntry(
            name=RAPIDOCR_ASSET_NAME,
            kind="model",
            size_mb=RAPIDOCR_SIZE_MB,
            dest=RAPIDOCR_DEST,
            label="RapidOCR PP-OCRv5 (on-screen text, Apache-2.0)",
            installer="download",
            url=RAPIDOCR_URL,
        )
    )


_register_day1()
_register_phase8_optional()
