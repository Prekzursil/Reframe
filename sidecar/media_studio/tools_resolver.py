"""External-tool path resolution chains + llama-server tool-asset registration (T5).

CONTRACTS.md A7/A8 (T5 lane): the sidecar needs absolute paths to a handful of
EXTERNAL executables. Every one resolves through an explicit, testable chain —
first hit wins, missing candidates fall through to the next link, ``None`` when
the whole chain misses (callers raise their own typed error or use
:func:`require_tool`):

  * ``llama-server`` — settings.llamaServerPath -> env ``MEDIA_STUDIO_LLAMA_SERVER``
    -> ``%APPDATA%/media-studio/tools/llama-server-cuda/`` -> ``.../llama-server-cpu/``
    -> the dev path ``D:/tools/llama-cpp-cuda`` (PLAN-P2 T5: a fresh machine needs
    no ``D:\\tools``; the dev path is the LAST link, not the first).
  * ``node-runner`` — the Node-capable executable the Remotion render CLI runs
    under (A4: the ELECTRON EXE with ``ELECTRON_RUN_AS_NODE=1``). Chain:
    settings.nodeExePath -> env ``MEDIA_STUDIO_NODE_EXE`` (injected by the
    Electron supervisor at sidecar spawn; SAME names as caption_remotion.py)
    -> the dev ``app/node_modules`` electron -> ``node`` on PATH (last resort).
  * ``ffmpeg`` / ``ffprobe`` — DELEGATED to :mod:`media_studio.ffmpeg`'s existing
    resolver (settings -> env -> bundled -> PATH); this module only adapts its
    raise-on-miss behavior to the chain's ``None``-on-miss convention.
  * ``wsl`` — presence probe (PATH lookup only, no subprocess) consumed by T4b's
    reframe fallback: when WSL/verthor is absent, reframe falls back to the
    claude-shorts engine with a typed notice.

Also registers the llama.cpp server builds (CUDA + cudart runtime + CPU) as U4
**tool assets** with PINNED ggml-org release URLs (A6 lesson 5), so
``assets.ensure`` can download them on a fresh machine. The zips are extracted
by the first-run bootstrap (``runtime_setup/bootstrap.py``) into
``<root>/tools/...``; each asset carries a ``detect`` probe so an extracted exe
(or the dev-path copy) counts as installed without keeping the zip around.

Pure path logic only: no subprocess, no network, no heavy imports.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ffmpeg as _ffmpeg
from .assets import manifest
from .pathsafe import ensure_within
from .settings_store import default_config_dir
from .util import get_logger

log = get_logger("media_studio.tools_resolver")

_EXE = ".exe" if os.name == "nt" else ""

#: executable file names (platform-suffixed)
LLAMA_EXE = f"llama-server{_EXE}"
ELECTRON_EXE = f"electron{_EXE}"

#: env override names (mirror ffmpeg.py's MEDIA_STUDIO_<NAME> convention).
#: The node-runner pair matches features/caption_remotion.py (T4a, the primary
#: consumer) EXACTLY so the supervisor injects ONE env var for both chains.
ENV_LLAMA_SERVER = "MEDIA_STUDIO_LLAMA_SERVER"
ENV_NODE_RUNNER = "MEDIA_STUDIO_NODE_EXE"

#: settings keys (CONTRACT-NOTE: §2 settings is an open object — these keys
#: extend it the same way ffmpegPath does; the UI may surface them later)
SETTING_LLAMA_SERVER = "llamaServerPath"
SETTING_NODE_RUNNER = "nodeExePath"

#: the dev-machine llama.cpp dir (models/runner.py's historical default).
#: Module attribute so tests (and exotic setups) can repoint it.
DEV_LLAMA_DIR = "D:/tools/llama-cpp-cuda"

#: tool dirs under the assets root (%APPDATA%/media-studio)
TOOL_DIR_CUDA = "tools/llama-server-cuda"
TOOL_DIR_CPU = "tools/llama-server-cpu"

#: the repo root for dev fallbacks (media_studio/ -> sidecar/ -> repo).
#: Module attribute so tests can repoint it at a tmp tree.
REPO_ROOT = Path(__file__).resolve().parents[2]

WhichFn = Callable[[str], str | None]


class ToolNotFound(RuntimeError):
    """Raised by :func:`require_tool` when a whole chain misses."""


# --------------------------------------------------------------------------- #
# chain helpers
# --------------------------------------------------------------------------- #
def _as_executable(candidate: str | None, exe_name: str) -> str | None:
    """Normalize a settings/env value to an executable file path (or ``None``).

    A FILE is taken as-is (custom-named binaries allowed); a DIRECTORY is
    probed for ``exe_name`` inside it; anything missing falls through.
    """
    if not candidate:
        return None
    # Canonicalise the settings/env-supplied value through the recognised barrier
    # (bare ensure_within never raises) so the file/dir probes are sanitised sinks.
    p = Path(ensure_within(str(candidate)))
    if p.is_file():
        return str(p)
    if p.is_dir():
        inner = Path(ensure_within(p, exe_name))
        if inner.is_file():
            return str(inner)
    return None


def _tools_root(root: str | os.PathLike | None = None) -> Path:
    """The assets root the tool dirs live under (injectable for tests)."""
    return Path(root) if root is not None else default_config_dir()


# --------------------------------------------------------------------------- #
# per-tool resolvers
# --------------------------------------------------------------------------- #
def resolve_llama_server(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    root: str | os.PathLike | None = None,
) -> str | None:
    """Resolve the llama.cpp server exe (T5 chain). ``None`` when nothing hits.

    Order: settings.llamaServerPath (file or dir) -> env MEDIA_STUDIO_LLAMA_SERVER
    (file or dir) -> ``<root>/tools/llama-server-cuda/`` -> ``.../llama-server-cpu/``
    -> ``DEV_LLAMA_DIR``. The CUDA build outranks CPU when both are installed.
    """
    settings = settings or {}
    env_map = env if env is not None else os.environ

    found = _as_executable(settings.get(SETTING_LLAMA_SERVER), LLAMA_EXE)
    if found:
        return found
    found = _as_executable(env_map.get(ENV_LLAMA_SERVER), LLAMA_EXE)
    if found:
        return found
    base = _tools_root(root)
    for sub in (TOOL_DIR_CUDA, TOOL_DIR_CPU):
        cand = Path(ensure_within(base, sub, LLAMA_EXE))
        if cand.is_file():
            return str(cand)
    dev = Path(DEV_LLAMA_DIR) / LLAMA_EXE
    if dev.is_file():
        return str(dev)
    return None


def resolve_node_runner(
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    which: WhichFn = shutil.which,
) -> str | None:
    """Resolve the Node-capable exe for the Remotion render CLI (A4).

    Order: settings.nodeExePath -> env MEDIA_STUDIO_NODE_EXE (the
    supervisor injects ``process.execPath`` here in the packaged app — see
    WIRING-T5.md) -> the dev electron exe under ``app/node_modules`` -> plain
    ``node`` on PATH. The CALLER sets ``ELECTRON_RUN_AS_NODE=1`` when spawning
    an Electron binary; that env contract is T4a's (caption_remotion).
    """
    settings = settings or {}
    env_map = env if env is not None else os.environ

    found = _as_executable(settings.get(SETTING_NODE_RUNNER), ELECTRON_EXE)
    if found:
        return found
    found = _as_executable(env_map.get(ENV_NODE_RUNNER), ELECTRON_EXE)
    if found:
        return found
    dev = Path(REPO_ROOT) / "app" / "node_modules" / "electron" / "dist" / ELECTRON_EXE
    if dev.is_file():
        return str(dev)
    node = which("node")
    if node:
        return node
    return None


def resolve_ffmpeg_tool(name: str, settings: dict[str, Any] | None = None) -> str | None:
    """Delegate ffmpeg/ffprobe to :func:`media_studio.ffmpeg.resolve_binary`.

    The ffmpeg module owns its (settings -> env -> bundled -> PATH) chain; we
    only adapt its raise-on-miss to this module's ``None``-on-miss convention.
    """
    try:
        return _ffmpeg.resolve_binary(name, settings)
    except _ffmpeg.FfmpegNotFound:
        return None


def wsl_available(*, which: WhichFn = shutil.which) -> bool:
    """WSL presence probe (consumed by T4b's reframe fallback).

    PATH lookup only — deliberately NO subprocess (``wsl --status`` can hang on
    a half-installed WSL, and a presence probe must never block a job thread).
    """
    return which("wsl") is not None


# --------------------------------------------------------------------------- #
# the public entry points
# --------------------------------------------------------------------------- #
TOOL_NAMES: tuple[str, ...] = ("llama-server", "node-runner", "ffmpeg", "ffprobe", "wsl")


def resolve_tool(
    name: str,
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    root: str | os.PathLike | None = None,
    which: WhichFn = shutil.which,
) -> str | None:
    """Resolve ``name`` through its chain; ``None`` when the whole chain misses.

    ``env`` / ``root`` / ``which`` are injectable seams so tests never touch the
    real environment, %APPDATA%, or PATH.
    """
    if name == "llama-server":
        return resolve_llama_server(settings, env=env, root=root)
    if name == "node-runner":
        return resolve_node_runner(settings, env=env, which=which)
    if name in ("ffmpeg", "ffprobe"):
        return resolve_ffmpeg_tool(name, settings)
    if name == "wsl":
        return which("wsl")
    raise ValueError(f"unknown tool: {name!r} (known: {', '.join(TOOL_NAMES)})")


def require_tool(
    name: str,
    settings: dict[str, Any] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    root: str | os.PathLike | None = None,
    which: WhichFn = shutil.which,
) -> str:
    """Like :func:`resolve_tool` but raises :class:`ToolNotFound` on a miss.

    The message names the settings key + asset so the failure surfaces a FIX
    (A6 lesson 3: failures must surface usefully, not vanish).
    """
    found = resolve_tool(name, settings, env=env, root=root, which=which)
    if found:
        return found
    hints = {
        "llama-server": (
            f"set settings.{SETTING_LLAMA_SERVER} or install the '{LLAMA_CUDA_ASSET}' / '{LLAMA_CPU_ASSET}' assets"
        ),
        "node-runner": (
            f"set settings.{SETTING_NODE_RUNNER} or launch through the app (the supervisor injects {ENV_NODE_RUNNER})"
        ),
        "ffmpeg": "set settings.ffmpegPath or add ffmpeg to PATH",
        "ffprobe": "set settings.ffmpegPath or add ffprobe to PATH",
        "wsl": "install WSL2 (or use the claude-shorts reframe fallback)",
    }
    raise ToolNotFound(f"{name} not found ({hints.get(name, 'no chain hit')})")


# --------------------------------------------------------------------------- #
# llama-server tool assets (U4 manifest entries; PINNED per A6 lesson 5)
# --------------------------------------------------------------------------- #

# CONTRACT-NOTE: pinned to the ggml-org/llama.cpp release tag below. The asset
# file names follow the release's win-x64 naming scheme. F3c (security hardening):
# every download is now sha256-pinned (verified by streaming the real release
# zips on 2026-06-28). NOTE: release b5192 ships NO `win-cpu-x64.zip` — the CPU
# fallback build is the AVX2 variant, so the CPU URL was corrected accordingly.
LLAMA_RELEASE_TAG = "b5192"
_LLAMA_BASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE_TAG}"

LLAMA_CUDA_ASSET = "llama-server-cuda"
LLAMA_CUDART_ASSET = "llama-server-cuda-cudart"
LLAMA_CPU_ASSET = "llama-server-cpu"

# F3c: verified sha256 of each release zip (streamed from GitHub, 2026-06-28).
LLAMA_CUDA_SHA256 = "4e06e8577f3b1ca3a9ee9ecc002d6cf10c2c939db5084c0ecdfe8f90baeef238"
LLAMA_CUDART_SHA256 = "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6"
LLAMA_CPU_SHA256 = "8dd95fd642402a13c79c62ffcdee5736a893834109c5d7471a028b4aa53f1da2"

#: where the downloaded archives land (relative to the assets root); the
#: first-run bootstrap extracts them into TOOL_DIR_* and deletes the zip.
_DL_DIR = "tools/downloads"
LLAMA_CUDA_ZIP = f"{_DL_DIR}/llama-{LLAMA_RELEASE_TAG}-bin-win-cuda-cu12.4-x64.zip"
LLAMA_CUDART_ZIP = f"{_DL_DIR}/cudart-llama-bin-win-cu12.4-x64.zip"
LLAMA_CPU_ZIP = f"{_DL_DIR}/llama-{LLAMA_RELEASE_TAG}-bin-win-avx2-x64.zip"


@dataclass(frozen=True)
class ToolArchive:
    """One downloadable tool archive + where the bootstrap extracts it."""

    asset: str
    extract_to: str  # relative to the assets root


#: consumed by runtime_setup/bootstrap.extract_tool_archives. The cudart
#: runtime extracts INTO the CUDA dir (the server needs its DLLs beside it).
TOOL_ARCHIVES: tuple[ToolArchive, ...] = (
    ToolArchive(asset=LLAMA_CUDA_ASSET, extract_to=TOOL_DIR_CUDA),
    ToolArchive(asset=LLAMA_CUDART_ASSET, extract_to=TOOL_DIR_CUDA),
    ToolArchive(asset=LLAMA_CPU_ASSET, extract_to=TOOL_DIR_CPU),
)


def _detect_in_tool_dir(sub: str, file_name: str) -> str | None:
    """An extracted file under the CURRENT assets root (env-overridable)."""
    cand = Path(ensure_within(default_config_dir(), sub, file_name))
    return str(cand) if cand.is_file() else None


def detect_llama_cuda(settings: dict[str, Any]) -> str | None:
    """Installed-detection for the CUDA build (settings -> extracted -> dev)."""
    settings = settings or {}
    found = _as_executable(settings.get(SETTING_LLAMA_SERVER), LLAMA_EXE)
    if found:
        return found
    found = _detect_in_tool_dir(TOOL_DIR_CUDA, LLAMA_EXE)
    if found:
        return found
    dev = Path(DEV_LLAMA_DIR) / LLAMA_EXE
    return str(dev) if dev.is_file() else None


def detect_llama_cpu(settings: dict[str, Any]) -> str | None:
    """Installed-detection for the CPU build (extracted exe only)."""
    return _detect_in_tool_dir(TOOL_DIR_CPU, LLAMA_EXE)


def detect_llama_cudart(settings: dict[str, Any]) -> str | None:
    """Installed-detection for the cudart runtime (a cudart DLL beside the exe).

    The dev dir ships its own DLLs, so a dev-path hit counts here too.
    """
    for base in (default_config_dir() / TOOL_DIR_CUDA, Path(DEV_LLAMA_DIR)):
        if base.is_dir():
            for hit in base.glob("cudart64*.dll"):
                if hit.is_file():
                    return str(hit)
    return None


def register_tool_assets() -> None:
    """Register the llama-server builds as U4 tool assets (idempotent).

    PLAN-P2 T5: "llama-server (CUDA + CPU builds) so a fresh machine needs no
    D:\\tools path". Sizes are coarse (preflight/progress math only).
    """
    manifest.register_asset(
        manifest.AssetEntry(
            name=LLAMA_CUDA_ASSET,
            kind="tool",
            size_mb=260,
            dest=LLAMA_CUDA_ZIP,
            label="llama.cpp server (CUDA, win-x64)",
            installer="download",
            url=f"{_LLAMA_BASE_URL}/llama-{LLAMA_RELEASE_TAG}-bin-win-cuda-cu12.4-x64.zip",
            sha256=LLAMA_CUDA_SHA256,
            detect=detect_llama_cuda,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=LLAMA_CUDART_ASSET,
            kind="tool",
            size_mb=550,
            dest=LLAMA_CUDART_ZIP,
            label="CUDA runtime DLLs for llama.cpp (win-x64)",
            installer="download",
            url=f"{_LLAMA_BASE_URL}/cudart-llama-bin-win-cu12.4-x64.zip",
            sha256=LLAMA_CUDART_SHA256,
            detect=detect_llama_cudart,
        )
    )
    manifest.register_asset(
        manifest.AssetEntry(
            name=LLAMA_CPU_ASSET,
            kind="tool",
            size_mb=30,
            dest=LLAMA_CPU_ZIP,
            label="llama.cpp server (CPU fallback / AVX2, win-x64)",
            installer="download",
            url=f"{_LLAMA_BASE_URL}/llama-{LLAMA_RELEASE_TAG}-bin-win-avx2-x64.zip",
            sha256=LLAMA_CPU_SHA256,
            detect=detect_llama_cpu,
        )
    )


# Register at import (mirrors manifest._register_day1; identical re-register is
# a no-op). WIRING-T5.md asks handlers.register_all to import this module so
# the entries land in the manifest before assets.list is served.
register_tool_assets()
