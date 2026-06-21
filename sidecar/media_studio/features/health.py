"""Self-diagnosing SYSTEM HEALTH report (this group's feature 1).

One ``system.health`` RPC answers "is my setup OK?" in a single call:

  * **ffmpeg / ffprobe** — resolved absolute path (via the existing
    :mod:`media_studio.ffmpeg` chain) + a parsed version string (``ffmpeg
    -version`` first line). Missing -> ``{present:false}`` with a fix hint.
  * **offline mode** — the enforced :mod:`offline` setting's current value, so
    the panel can show (and toggle) it.
  * **optional ML backends** — which heavy libraries are importable WITHOUT
    importing them into this process: a spec probe (``importlib.util.find_spec``)
    so the health check itself never pulls faster-whisper / torch / speechbrain
    into memory. Reports ``installed`` + the discovered version (read from
    package metadata, still no import).
  * **model-cache paths** — the data root, the models dir, the HF cache, the
    llama-tools dirs — with an ``exists`` flag each, so a user can see where
    artifacts live and whether they are populated.
  * **engine availability** — the external tools (llama-server / node-runner /
    wsl) resolved through :mod:`tools_resolver`, each ``available`` + its path.

Pure, dependency-free, network-free: every heavy thing is behind an injectable
seam (``run`` for the version subprocess, ``find_spec`` / ``pkg_version`` for the
backend probe) so tests never spawn a process or import a model library. The
version subprocess uses an argv LIST + drained pipes (``subprocess.run``), never
``shell=True`` (A6 lesson 4).
"""

from __future__ import annotations

import importlib.metadata as _md
import importlib.util as _util
import os
import subprocess  # noqa: S404 - argv-list subprocess only, never shell=True
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .. import ffmpeg as _ffmpeg
from .. import protocol, tools_resolver
from ..assets.manager import hf_cache_dir
from ..protocol import RpcContext
from ..settings_store import default_config_dir
from ..util import get_logger
from . import offline as _offline

log = get_logger("media_studio.features.health")

# A subprocess runner seam: (argv) -> CompletedProcess-like (has .stdout/.returncode).
RunFn = Callable[..., Any]
# A "find_spec" seam: (module name) -> spec | None.
SpecFn = Callable[[str], Any]
# A "package version" seam: (distribution name) -> version str (raises if absent).
VersionFn = Callable[[str], str]

#: Optional ML backends we report on. Each is (label, import-module, dist-name).
#: import-module is what we PROBE (never import); dist-name is the PyPI package
#: whose metadata version we read. They differ for several (faster_whisper vs
#: faster-whisper). Order = display order in the panel.
ML_BACKENDS: tuple[tuple[str, str, str], ...] = (
    ("faster-whisper (transcription)", "faster_whisper", "faster-whisper"),
    ("ctranslate2 (whisper runtime)", "ctranslate2", "ctranslate2"),
    ("torch (ML runtime)", "torch", "torch"),
    ("speechbrain (diarization)", "speechbrain", "speechbrain"),
    ("torchaudio (audio I/O)", "torchaudio", "torchaudio"),
    ("scenedetect (scene cuts)", "scenedetect", "scenedetect"),
    ("huggingface_hub (model fetch)", "huggingface_hub", "huggingface_hub"),
    ("kokoro (TTS)", "kokoro", "kokoro"),
)

#: external engines reported under "engines" (tools_resolver chain names).
ENGINE_TOOLS: tuple[tuple[str, str], ...] = (
    ("llama-server", "Local LLM server (translation / scoring)"),
    ("node-runner", "Remotion caption renderer"),
    ("wsl", "WSL2 (GPU reframe fallback)"),
)


def _default_run(argv: list[str]) -> Any:
    """Drained-pipe subprocess for a ``<tool> -version`` probe (A6 lesson 4)."""
    return subprocess.run(  # noqa: S603 - argv list, shell never
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def parse_ffmpeg_version(output: str) -> str:
    """Pull the version token out of ``ffmpeg -version`` output.

    The first line is ``ffmpeg version <X> Copyright ...`` (or ``ffprobe
    version ...``); we return ``<X>``. Falls back to the trimmed first line when
    the shape is unexpected, and "" for empty output.
    """
    first = (output or "").strip().splitlines()
    if not first:
        return ""
    line = first[0].strip()
    parts = line.split()
    # tokens: [<tool>, "version", "<X>", "Copyright", ...]
    if len(parts) >= 3 and parts[1] == "version":
        return parts[2]
    return line


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #
class Health:
    """Builds the ``system.health`` report over injectable seams.

    Seams: ``settings_provider`` (the §2 settings getter), ``root`` (the data
    root, defaults to the per-user config dir), ``run`` (the version
    subprocess), ``find_spec`` / ``pkg_version`` (the no-import backend probe),
    and ``env`` (so the offline/HF-cache probes never touch ``os.environ``).
    """

    def __init__(
        self,
        *,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        root: str | os.PathLike | None = None,
        run: RunFn | None = None,
        find_spec: SpecFn | None = None,
        pkg_version: VersionFn | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._settings_provider = settings_provider or (lambda: {})
        self._root = Path(root) if root is not None else default_config_dir()
        self._run: RunFn = run or _default_run
        self._find_spec: SpecFn = find_spec or _util.find_spec
        self._pkg_version: VersionFn = pkg_version or _md.version
        self._env = env

    # -- internals ---------------------------------------------------------
    def _settings(self) -> dict[str, Any]:
        try:
            return dict(self._settings_provider() or {})
        except Exception:  # noqa: BLE001 - health must never crash on settings
            log.warning("settings provider failed during health check")
            return {}

    def _tool_version(self, name: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Resolve + version-probe ffmpeg/ffprobe. Always returns a dict."""
        try:
            path = _ffmpeg.resolve_binary(name, settings)
        except _ffmpeg.FfmpegNotFound:
            return {
                "name": name,
                "present": False,
                "path": "",
                "version": "",
                "hint": f"install {name} or set settings.ffmpegPath",
            }
        version = ""
        try:
            completed = self._run([path, "-version"])
            if getattr(completed, "returncode", 1) == 0:
                version = parse_ffmpeg_version(getattr(completed, "stdout", "") or "")
        except Exception as exc:  # noqa: BLE001 - a probe miss != fatal
            log.warning("%s -version probe failed: %s", name, exc)
        return {"name": name, "present": True, "path": str(path), "version": version, "hint": ""}

    def _backend(self, label: str, module: str, dist: str) -> dict[str, Any]:
        """No-import probe for one optional ML backend."""
        installed = False
        try:
            installed = self._find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            # find_spec can raise for a broken/partial install — treat as absent.
            installed = False
        version = ""
        if installed:
            try:
                version = self._pkg_version(dist)
            except Exception:  # noqa: BLE001 - metadata absent != not installed
                version = ""
        return {"label": label, "module": module, "installed": installed, "version": version}

    def _path_entry(self, label: str, path: Path) -> dict[str, Any]:
        return {"label": label, "path": str(path), "exists": path.exists()}

    def _model_paths(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        """The model-cache locations the panel surfaces (with exists flags)."""
        entries = [
            self._path_entry("Data root", self._root),
            self._path_entry("Models", self._root / "models"),
            self._path_entry("HF cache", hf_cache_dir(self._env)),
            self._path_entry("llama (CUDA)", self._root / tools_resolver.TOOL_DIR_CUDA),
            self._path_entry("llama (CPU)", self._root / tools_resolver.TOOL_DIR_CPU),
        ]
        models_dir = settings.get("modelsDir")
        if isinstance(models_dir, str) and models_dir.strip():
            entries.append(self._path_entry("Models dir (setting)", Path(models_dir)))
        return entries

    def _engines(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        """External-engine availability via the tools_resolver chains."""
        out: list[dict[str, Any]] = []
        for name, desc in ENGINE_TOOLS:
            try:
                path = tools_resolver.resolve_tool(name, settings, env=self._env, root=self._root)
            except Exception as exc:  # noqa: BLE001 - resolution must never crash health
                log.warning("engine resolve for %s failed: %s", name, exc)
                path = None
            out.append(
                {
                    "name": name,
                    "description": desc,
                    "available": bool(path),
                    "path": str(path) if path else "",
                }
            )
        return out

    # -- system.health -----------------------------------------------------
    def report(self, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        """``system.health()`` -> the full diagnostic report (direct-return).

        Shape (field names FROZEN, mirrored on the TS side)::

            {
              ok: bool,                       # ffmpeg + ffprobe both present
              offline: bool,                  # offline mode in force
              platform: str,                  # sys.platform-ish os name
              tools: [{name, present, path, version, hint}],   # ffmpeg/ffprobe
              backends: [{label, module, installed, version}], # ML libs (probed)
              modelPaths: [{label, path, exists}],
              engines: [{name, description, available, path}],
            }
        """
        settings = self._settings()
        tools = [self._tool_version("ffmpeg", settings), self._tool_version("ffprobe", settings)]
        backends = [self._backend(label, mod, dist) for label, mod, dist in ML_BACKENDS]
        report = {
            "ok": all(t["present"] for t in tools),
            "offline": _offline.is_offline(settings, env=self._env),
            "platform": os.name,
            "tools": tools,
            "backends": backends,
            "modelPaths": self._model_paths(settings),
            "engines": self._engines(settings),
        }
        return report


# --------------------------------------------------------------------------- #
# registration (mirrors shorts.register / assets.rpc.register)
# --------------------------------------------------------------------------- #
def register(
    *,
    settings_provider: Callable[[], dict[str, Any]] | None = None,
    root: str | os.PathLike | None = None,
    run: RunFn | None = None,
    find_spec: SpecFn | None = None,
    pkg_version: VersionFn | None = None,
    register_fn: Callable[[str, Any], None] | None = None,
) -> Health:
    """Create a :class:`Health` and register ``system.health`` (direct-return).

    ``register_fn`` defaults to :func:`protocol.register`; tests inject a fake
    registrar + fake seams. Returns the service so the caller can hold it.
    """
    service = Health(
        settings_provider=settings_provider,
        root=root,
        run=run,
        find_spec=find_spec,
        pkg_version=pkg_version,
    )
    reg = register_fn if register_fn is not None else protocol.register
    reg("system.health", service.report)
    return service


__all__ = ["ENGINE_TOOLS", "ML_BACKENDS", "Health", "parse_ffmpeg_version", "register"]
