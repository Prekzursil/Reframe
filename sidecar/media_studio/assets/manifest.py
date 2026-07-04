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
        sha256="...",                          # REQUIRED for installer='download' (F3c)
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

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import get_logger

log = get_logger("media_studio.assets.manifest")

# F3c (security hardening): integrity + revision pinning is NON-NEGOTIABLE.
#   * A 64-char lowercase/uppercase hex string is a valid sha256 digest.
#   * A 40-char hex string is a git/HF commit hash (a branch/tag like "main"
#     is a MOVING target and is rejected — a pinned commit can't silently change
#     under us between the day a hash is recorded and the day a user downloads).
_SHA256_RE = re.compile(r"\A[0-9a-fA-F]{64}\Z")
_COMMIT_HASH_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")
# An HF "resolve" download URL embeds the ref it pins:
#   https://huggingface.co/<repo>/resolve/<ref>/<path>
# The <ref> MUST be a commit hash, never a branch/tag.
_HF_RESOLVE_RE = re.compile(r"https?://huggingface\.co/.+?/resolve/([^/]+)/")

# A3: AssetInfo.kind is frozen to exactly these three.
ASSET_KINDS: tuple[str, ...] = ("model", "env", "tool")

# How the manager materializes an entry:
#   "download" — httpx streaming download of a single pinned URL (resume+sha)
#   "hf"       — huggingface_hub snapshot into the standard HF_HOME cache
#   "env"      — bootstrap a pip --target env under <root>/envs/<dest> (A7)
INSTALLERS: tuple[str, ...] = ("download", "hf", "env")

# Which interpreter an installer="env" entry installs with (the manager resolves
# the marker to a concrete python). "host" = the manager-wide python (the py3.12
# sidecar interpreter); "chatterbox" = the dedicated py3.14 embeddable (torch
# 2.10 only resolves there). Paths are per-machine, so entries carry the MARKER,
# never an absolute interpreter path.
PYTHON_KINDS: tuple[str, ...] = ("host", "chatterbox")

# WU C1 (installer profiles): every entry carries a PROFILE TIER so ``assets.ensure``
# can materialize a whole install profile from one choice, not a hand-picked list:
#   "core"     — the Default-profile core models (Whisper ASR, YuNet detector, the
#                small local LLM, the always-on face/ASD reframe weights). CPU-only.
#   "optional" — extra on-demand signals/backends (semantic embedder, emotion, OCR,
#                the occlusion-robust tracker). Pulled only in the Full profile (or
#                hand-picked in Custom). This is the DEFAULT tier — an unclassified
#                entry is on-demand, never force-installed into Default.
#   "gpu"      — GPU-only stacks (larger LLMs, dubbing/diarization envs). Full only.
# The Minimum profile pulls NOTHING (app + slim python; everything on demand).
ASSET_TIERS: tuple[str, ...] = ("core", "optional", "gpu")

# The four installer profiles (U-facing) and the tiers each pulls. "custom" pulls
# an explicit hand-picked component list (see :func:`resolve_profile`), so it maps
# to no fixed tier set.
PROFILES: tuple[str, ...] = ("minimum", "default", "full", "custom")
PROFILE_TIERS: dict[str, tuple[str, ...]] = {
    "minimum": (),
    "default": ("core",),
    "full": ("core", "optional", "gpu"),
    "custom": (),
}

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
    # WU C1: which install PROFILE tier pulls this entry (see ASSET_TIERS). Default
    # "optional" — an unclassified entry is on-demand, never forced into Default.
    tier: str = "optional"
    # WU C1: a plain-English WHY this component exists — surfaced (with label=what +
    # size_mb) by ``assets.plan`` so a user sees what a multi-GB download buys BEFORE
    # committing to it.
    why: str = ""
    # installer="download": the PINNED source URL + optional integrity pin.
    url: str | None = None
    sha256: str | None = None
    installer: str = "download"
    # installer="hf": repo id (+ optional revision pin) in the HF_HOME cache.
    hf_repo: str | None = None
    hf_revision: str | None = None
    # installer="env": PINNED "pkg==ver" requirement strings (A6 lesson 5).
    requirements: tuple[str, ...] = ()
    # installer="env": which interpreter to install with (see PYTHON_KINDS).
    # Default "host"; "chatterbox" routes to the dedicated py3.14 embeddable.
    python_kind: str = "host"
    # installer="env" (WU C4): an optional fully-hashed lockfile over the FULL
    # transitive closure. When set + staged, the env installs with
    # ``pip --require-hashes --only-binary=:all: --no-deps -r <lock>`` so every
    # wheel is hash-verified before exec (the inline ``requirements`` above are
    # the top-level pins + the installed-detection sentinel; the lock is the
    # verified install source). Its CONTENT is an F1 build-prep artifact (real
    # hashes need PyPI + the cu128 torch index), staged like the ffmpeg binary —
    # absolute path, or relative to the assets root.
    lock_file: str | None = None
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
        if self.python_kind not in PYTHON_KINDS:
            raise ValueError(
                f"asset {self.name!r}: python_kind must be one of {PYTHON_KINDS}, got {self.python_kind!r}"
            )
        if self.tier not in ASSET_TIERS:
            raise ValueError(f"asset {self.name!r}: tier must be one of {ASSET_TIERS}, got {self.tier!r}")
        # Normalize requirements to a tuple (frozen dataclass => object.__setattr__).
        object.__setattr__(self, "requirements", tuple(self.requirements or ()))
        # WU C4: a hashed lockfile only means anything for a pip --target env.
        if self.lock_file and self.installer != "env":
            raise ValueError(f"asset {self.name!r}: lock_file is only valid for installer='env'")
        if self.installer == "download":
            if not self.url:
                raise ValueError(f"asset {self.name!r}: installer='download' requires a pinned url")
            if not self.dest:
                raise ValueError(f"asset {self.name!r}: installer='download' requires a dest path")
            # F3c: a download with no integrity pin is rejected — a downloaded
            # blob (incl. the EXECUTED get-pip.py) must be content-verified.
            if not self.sha256:
                raise ValueError(f"asset {self.name!r}: installer='download' requires a sha256 integrity pin")
            if not _SHA256_RE.match(self.sha256):
                raise ValueError(f"asset {self.name!r}: sha256 must be 64 hex chars, got {self.sha256!r}")
            # F3c: an HF resolve URL must pin a COMMIT HASH, never a branch/tag.
            hf_match = _HF_RESOLVE_RE.match(self.url)
            if hf_match and not _COMMIT_HASH_RE.match(hf_match.group(1)):
                raise ValueError(
                    f"asset {self.name!r}: HF download url must pin a commit hash "
                    f"(40 hex), not branch/tag {hf_match.group(1)!r}"
                )
        elif self.installer == "hf":
            if not self.hf_repo:
                raise ValueError(f"asset {self.name!r}: installer='hf' requires hf_repo")
            # F3c: an hf snapshot must pin a COMMIT HASH revision (no floating main).
            if not self.hf_revision:
                raise ValueError(f"asset {self.name!r}: installer='hf' requires a pinned hf_revision")
            if not _COMMIT_HASH_RE.match(self.hf_revision):
                raise ValueError(
                    f"asset {self.name!r}: hf_revision must be a commit hash (40 hex), got {self.hf_revision!r}"
                )
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


def resolve_profile(profile: str, custom: Sequence[str] | None = None) -> list[str]:
    """Asset names to install for an installer PROFILE (WU C1).

    * ``minimum`` — nothing (app + slim python; everything on demand) -> ``[]``.
    * ``default`` — every ``core``-tier entry.
    * ``full``    — every ``core``/``optional``/``gpu``-tier entry.
    * ``custom``  — the explicit ``custom`` name list (order preserved, de-duped);
      each name MUST be a registered asset (unknown names fail loudly, never
      silently dropped).

    The profile is matched case-insensitively. An unknown profile raises
    ``ValueError`` (fail loud — no silent empty-set fallback).
    """
    key = str(profile).lower()
    if key not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}, got {profile!r}")
    if key == "custom":
        seen: dict[str, None] = {}
        for name in custom or ():
            if get_asset(name) is None:
                raise ValueError(f"custom profile: unknown asset {name!r}")
            seen.setdefault(name, None)
        return list(seen)
    tiers = PROFILE_TIERS[key]
    return [entry.name for entry in all_assets() if entry.tier in tiers]


# --------------------------------------------------------------------------- #
# day-1 entries (U4 scope): whisper large-v3-turbo + Qwen3-4B GGUF
# --------------------------------------------------------------------------- #

WHISPER_ASSET_NAME = "whisper-large-v3-turbo"
# §7 / transcribe.py DEFAULT_MODEL="large-v3-turbo" resolves to this CT2 repo via
# faster-whisper; ensuring it through huggingface_hub lands in the SAME HF_HOME
# cache faster-whisper reads, so transcribe.start finds it pre-downloaded.
WHISPER_HF_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
# F3c: pin the HF snapshot to a COMMIT HASH (never floating "main"). Verified via
# the HF revision API (commit of refs/heads/main on 2026-06-28).
WHISPER_HF_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
WHISPER_SIZE_MB = 1600

QWEN_ASSET_NAME = "qwen3-4b-gguf"
# CONTRACT-NOTE: §7 default model is "Qwen3-4B GGUF". The URL pins the exact
# repo + file (Q4_K_M quant). F3c: the resolve ref is the repo's main COMMIT HASH
# (verified via the HF revision API) and the sha256 is the file's LFS oid
# (verified via the HF tree API, 2,497,280,256 B) — a download is now mandatorily
# integrity-pinned (no more "fill it in later").
QWEN_GGUF_COMMIT = "bc640142c66e1fdd12af0bd68f40445458f3869b"
QWEN_GGUF_URL = f"https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/{QWEN_GGUF_COMMIT}/Qwen3-4B-Q4_K_M.gguf"
QWEN_SHA256 = "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5"
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


EMBEDDER_ASSET_NAME = "all-minilm-l6-v2-onnx"
# WU-A3 (resolves G-A3 asset): the pinned small local embedder for the semantic
# index. all-MiniLM-L6-v2 emits 384-dim vectors — matching the local-backstop
# dimension ``embedder.DEFAULT_LOCAL_EMBED_DIM`` (WU-A2) — and is Apache-2.0. The
# URL pins the exact repo + ONNX file and the sha256 is the file's LFS oid (A6
# lesson 5: PINNED). Routed via the existing "download" installer (no new type).
# F3c: the resolve ref is the repo's main COMMIT HASH (verified via the HF
# revision API 2026-06-28), not the floating "main" branch.
EMBEDDER_COMMIT = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDER_ONNX_URL = (
    f"https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{EMBEDDER_COMMIT}/onnx/model.onnx"
)
# LFS oid of onnx/model.onnx @ main (verified via the HF tree API, 90,405,214 B).
EMBEDDER_SHA256 = "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"
EMBEDDER_DEST = "models/all-minilm-l6-v2.onnx"
EMBEDDER_SIZE_MB = 87


def _register_day1() -> None:
    """Install the day-1 entries (idempotent: identical re-register is a no-op)."""
    register_asset(
        AssetEntry(
            name=WHISPER_ASSET_NAME,
            kind="model",
            size_mb=WHISPER_SIZE_MB,
            label="Whisper large-v3-turbo (transcription)",
            tier="core",
            why="Transcribes speech to text — the base for captions, subtitles, and Director planning.",
            installer="hf",
            hf_repo=WHISPER_HF_REPO,
            hf_revision=WHISPER_HF_REVISION,
        )
    )
    register_asset(
        AssetEntry(
            name=QWEN_ASSET_NAME,
            kind="model",
            size_mb=QWEN_SIZE_MB,
            dest=QWEN_DEST,
            label="Qwen3-4B GGUF (local LLM)",
            tier="core",
            why="Runs the local language model that powers clip selection, titles, and the Director — fully offline.",
            installer="download",
            url=QWEN_GGUF_URL,
            sha256=QWEN_SHA256,
            detect=detect_existing_gguf,
        )
    )
    register_asset(
        AssetEntry(
            name=EMBEDDER_ASSET_NAME,
            kind="model",
            size_mb=EMBEDDER_SIZE_MB,
            dest=EMBEDDER_DEST,
            label="all-MiniLM-L6-v2 ONNX (semantic-index embeddings, Apache-2.0)",
            tier="optional",
            why="Builds the semantic index for finding related moments across your library — optional search quality boost.",
            installer="download",
            url=EMBEDDER_ONNX_URL,
            sha256=EMBEDDER_SHA256,
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
# F3c: the GitHub raw ref is pinned to a COMMIT HASH (not "main") and the file is
# sha256-verified (both confirmed via the GitHub API + a download, 2026-06-28).
HSEMOTION_COMMIT = "bd500bd3a685013d18883c349e8940d020cacd98"
HSEMOTION_URL = (
    f"https://github.com/av-savchenko/hsemotion-onnx/raw/{HSEMOTION_COMMIT}"
    "/models/affectnet_emotions/onnx/enet_b0_8_best_vgaf.onnx"
)
HSEMOTION_SHA256 = "00085f9a8ef0bf8fc24a645550185703768951a53aff9f141c8637529eba1840"
HSEMOTION_DEST = "models/hsemotion-enet-b0-8.onnx"
HSEMOTION_SIZE_MB = 20

RAPIDOCR_ASSET_NAME = "rapidocr-onnx"
#: PINNED RapidOCR PP-OCRv4 detection ONNX.
# F3c re-point: the previous GitHub-release URL (v1.4.4) now 404s — RapidOCR moved
# model hosting off GitHub releases. Re-pointed to the maintainer's canonical HF
# repo (SWHL/RapidOCR), pinned to a COMMIT HASH, with the file's LFS oid as the
# sha256 (both verified via the HF tree + revision APIs, 4,745,517 B, 2026-06-28).
RAPIDOCR_COMMIT = "1cfba2e90fc938db55889873735088de210cc173"
RAPIDOCR_URL = f"https://huggingface.co/SWHL/RapidOCR/resolve/{RAPIDOCR_COMMIT}/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx"
RAPIDOCR_SHA256 = "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9"
RAPIDOCR_DEST = "models/rapidocr-ppocrv4-det.onnx"
RAPIDOCR_SIZE_MB = 20


# --------------------------------------------------------------------------- #
# R1 multi-speaker reframe — vendored LR-ASD visual active-speaker weights.
# Two on-demand weights for the vendored S3FD detector + LR-ASD model
# (sidecar/media_studio/features/_lightasd/, MIT). LR-ASD (IJCV 2025) is the
# strictly-Pareto-better successor of Light-ASD; the ASD weight is its smaller
# finetuning_TalkSet.model. BOTH are sha256-pinned to the exact bytes of the
# GPU-validated copies (A6 lesson 5).
# --------------------------------------------------------------------------- #
LIGHTASD_S3FD_ASSET_NAME = "lightasd-s3fd"
# The S3FD face-detector weight (sfd_face.pth). NOT in the Light-ASD GitHub repo
# (the upstream fetches it via gdown from Google Drive, which is not a pinnable
# direct download). Re-pointed to a loader-identical, COMMIT-pinned HF mirror; the
# sha256 is the file's verified digest (== the ~/Light-ASD copy, 89,844,381 B,
# downloaded + sha256-checked 2026-06-29).
LIGHTASD_S3FD_COMMIT = "345f55fc8d94d74437095b34158c68645e113c01"
LIGHTASD_S3FD_URL = f"https://huggingface.co/lithiumice/syncnet/resolve/{LIGHTASD_S3FD_COMMIT}/sfd_face.pth"
LIGHTASD_S3FD_SHA256 = "d54a87c2b7543b64729c9a25eafd188da15fd3f6e02f0ecec76ae1b30d86c491"
LIGHTASD_S3FD_DEST = "models/lightasd-sfd-face.pth"
LIGHTASD_S3FD_SIZE_MB = 86

LIGHTASD_ASD_ASSET_NAME = "lightasd-asd"
# The LR-ASD active-speaker weight (finetuning_TalkSet.model). LR-ASD (IJCV 2025)
# is the strictly-Pareto-better successor of Light-ASD by the same author; its
# smaller model REPLACES the Light-ASD one. Tracked directly in the upstream
# GitHub repo, so the URL pins a GitHub-raw COMMIT (not LFS, served verbatim); the
# sha256 is the file's verified digest (== the ~/LR-ASD copy, 3,426,337 B,
# sha256-checked 2026-06-29).
LIGHTASD_ASD_COMMIT = "1b6dcd2d8fc2895683de6508ec6294ec47d388ca"
LIGHTASD_ASD_URL = f"https://github.com/Junhua-Liao/LR-ASD/raw/{LIGHTASD_ASD_COMMIT}/weight/finetuning_TalkSet.model"
LIGHTASD_ASD_SHA256 = "6b4ef53694e874e96cf630198dc479c78aebb3993bbf166aee3d926dfe7d9342"
LIGHTASD_ASD_DEST = "models/lightasd-finetuning-talkset.model"
LIGHTASD_ASD_SIZE_MB = 4


def _register_lightasd() -> None:
    """Register the vendored Light-ASD S3FD + ASD weights (idempotent)."""
    register_asset(
        AssetEntry(
            name=LIGHTASD_S3FD_ASSET_NAME,
            kind="model",
            size_mb=LIGHTASD_S3FD_SIZE_MB,
            dest=LIGHTASD_S3FD_DEST,
            label="S3FD face detector (Light-ASD visual ASD, MIT)",
            tier="core",
            why="Detects faces for the always-on speaker tracker so vertical reframes follow the person talking.",
            installer="download",
            url=LIGHTASD_S3FD_URL,
            sha256=LIGHTASD_S3FD_SHA256,
        )
    )
    register_asset(
        AssetEntry(
            name=LIGHTASD_ASD_ASSET_NAME,
            kind="model",
            size_mb=LIGHTASD_ASD_SIZE_MB,
            dest=LIGHTASD_ASD_DEST,
            label="LR-ASD active-speaker model (finetuning_TalkSet, MIT)",
            tier="core",
            why="Picks which visible face is actually speaking so multi-person reframes track the right subject.",
            installer="download",
            url=LIGHTASD_ASD_URL,
            sha256=LIGHTASD_ASD_SHA256,
        )
    )


# --------------------------------------------------------------------------- #
# v1.2.0 WU1 — YuNet face detector for the claudeshorts reframe engine.
# YuNet (cv2.FaceDetectorYN, a tiny ONNX CNN) REPLACES the OpenCV haar-cascade /
# HOG face+body detector in ``features.reframe_claudeshorts`` — it holds turned
# and profile faces far better, so the crop tracks the speaker instead of
# collapsing to a centre crop. Sourced from the OFFICIAL OpenCV HF mirror
# (opencv/face_detection_yunet, MIT — © 2020 Shiqi Yu). F3c: the resolve URL
# pins a COMMIT HASH (verified via the HF refs API) and the sha256 is the file's
# LFS oid (verified by downloading + hashing the bytes, 232,589 B, 2026-07-03).
# --------------------------------------------------------------------------- #
YUNET_ASSET_NAME = "yunet-face-detection"
YUNET_COMMIT = "3cc26e7f1014a5ee5d74a42acee58bafc9d0a310"
YUNET_URL = (
    f"https://huggingface.co/opencv/face_detection_yunet/resolve/{YUNET_COMMIT}/face_detection_yunet_2023mar.onnx"
)
# sha256 == the LFS oid of face_detection_yunet_2023mar.onnx @ the pinned commit
# (== the downloaded + hashed bytes, 232,589 B).
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_DEST = "models/yunet-face-detection-2023mar.onnx"
# The ONNX is only ~0.23 MB; keep size_mb below ~0.44 so the manager's
# file_size_ok floor (0.5 * size_mb) still counts the fully-downloaded file as
# installed rather than a truncated leftover.
YUNET_SIZE_MB = 0.3


def _register_yunet() -> None:
    """Register the sha256-pinned YuNet face-detection ONNX (idempotent)."""
    register_asset(
        AssetEntry(
            name=YUNET_ASSET_NAME,
            kind="model",
            size_mb=YUNET_SIZE_MB,
            dest=YUNET_DEST,
            label="YuNet face detector (claudeshorts speaker tracking, MIT)",
            tier="core",
            why="The default face detector that keeps the vertical crop centred on the speaker — no silent centre-crop.",
            installer="download",
            url=YUNET_URL,
            sha256=YUNET_SHA256,
        )
    )


# --------------------------------------------------------------------------- #
# v1.2.0 WU2 — EdgeTAM occlusion-robust video tracker (OPT-IN reframe backend).
# EdgeTAM (facebookresearch/EdgeTAM, Apache-2.0) is an on-device, edge-optimized
# SAM2 successor for "track anything" video segmentation. It is the OPT-IN
# ``reframeTracker="edgetam"`` speaker-tracking backend for the claudeshorts
# reframe engine: unlike the per-frame YuNet face detector (the DEFAULT), it
# propagates a single subject mask THROUGH occlusions, so the crop keeps tracking
# a speaker who is briefly blocked / turns fully away instead of losing them.
#
# LICENSE (verified 2026-07-03, task brief): Apache-2.0 — commercial use is
# permitted under the standard attribution/NOTICE obligations (no field-of-use or
# non-commercial restriction). EdgeTAM's checkpoint was trained on "Our mix"
# which explicitly EXCLUDES SAM2's internal datasets, so the weights carry no
# encumbered-data question; the research-only SA-1B *dataset* license governs raw
# data, not these trained weights.
#
# F3c pinning: the checkpoint ships IN the repo (a 56 MB git blob, NOT LFS), so it
# is pinned via a GitHub-raw URL carrying a 40-hex COMMIT HASH (never a moving
# branch/tag) and the sha256 is the downloaded file's verified digest
# (56,116,523 B, hashed 2026-07-03).
# --------------------------------------------------------------------------- #
EDGETAM_ASSET_NAME = "edgetam-video-tracker"
EDGETAM_COMMIT = "7711e012a30a2402c4eaab637bdb00a521302c91"
EDGETAM_URL = f"https://github.com/facebookresearch/EdgeTAM/raw/{EDGETAM_COMMIT}/checkpoints/edgetam.pt"
# sha256 of checkpoints/edgetam.pt @ the pinned commit (== the downloaded +
# hashed bytes, 56,116,523 B, 2026-07-03).
EDGETAM_SHA256 = "ed2d4850b8792c239689b043c47046ec239b6e808a3d9b6ae676c803fd8780df"
EDGETAM_DEST = "models/edgetam.pt"
# ~53.5 MB; kept a touch below the real size so the manager's file_size_ok floor
# (0.5 * size_mb) still counts the fully-downloaded file as installed.
EDGETAM_SIZE_MB = 53.5


def _register_edgetam() -> None:
    """Register the sha256-pinned EdgeTAM tracker checkpoint (idempotent)."""
    register_asset(
        AssetEntry(
            name=EDGETAM_ASSET_NAME,
            kind="model",
            size_mb=EDGETAM_SIZE_MB,
            dest=EDGETAM_DEST,
            label="EdgeTAM video tracker (opt-in occlusion-robust reframe tracking, Apache-2.0)",
            tier="optional",
            why="Opt-in tracker that follows a subject through occlusions and full turn-aways — better than the default on tricky clips.",
            installer="download",
            url=EDGETAM_URL,
            sha256=EDGETAM_SHA256,
        )
    )


def _register_phase8_optional() -> None:
    """Register the optional Phase-8 emotion + OCR signal models (idempotent)."""
    register_asset(
        AssetEntry(
            name=HSEMOTION_ASSET_NAME,
            kind="model",
            size_mb=HSEMOTION_SIZE_MB,
            dest=HSEMOTION_DEST,
            label="HSEmotion enet_b0_8 (facial emotion, Apache-2.0)",
            tier="optional",
            why="Scores facial emotion to help find the most expressive moments — an optional highlight signal.",
            installer="download",
            url=HSEMOTION_URL,
            sha256=HSEMOTION_SHA256,
        )
    )
    register_asset(
        AssetEntry(
            name=RAPIDOCR_ASSET_NAME,
            kind="model",
            size_mb=RAPIDOCR_SIZE_MB,
            dest=RAPIDOCR_DEST,
            label="RapidOCR PP-OCRv4 det (on-screen text, Apache-2.0)",
            tier="optional",
            why="Reads on-screen text so captions avoid covering it and text-heavy moments score higher — optional.",
            installer="download",
            url=RAPIDOCR_URL,
            sha256=RAPIDOCR_SHA256,
        )
    )


_register_day1()
_register_phase8_optional()
_register_lightasd()
_register_yunet()
_register_edgetam()
