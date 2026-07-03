"""Load-use-free model lifecycle: the llama.cpp server process + in-proc whisper.

CONTRACTS.md §7 names "a managed llama.cpp **server** (OpenAI-compatible /v1) the
sidecar starts/stops" and "faster-whisper (large-v3-turbo)" loaded in-process,
with a **load-use-free, one-heavy-model-at-a-time** policy. This module owns that
lifecycle:

  * **llama.cpp server PROCESS** — :class:`ModelRunner` builds an **argv list**
    (never ``shell=True``) to launch ``D:/tools/llama-cpp-cuda/llama-server.exe
    -m <gguf> --port 8088`` and starts/stops it via an injectable ``popen`` seam.
  * **model-identity-aware (T3)** — the runner tracks WHICH GGUF the live server
    was launched with (:attr:`ModelRunner.current_model_path`). Requesting a
    *different* model gracefully stops the running server and relaunches with the
    new GGUF; requesting the *same* model reuses the live process. This is what
    lets the tiered translator swap Qwen3-4B <-> TranslateGemma on one port.
  * **faster-whisper in-proc** — loaded on demand behind a loader seam (so this
    module never imports the heavy library) and freed (``torch.cuda.empty_cache``
    style) when released, behind an injectable free-hook.
  * **one heavy model at a time** — a simple :class:`LaneLock` (a plain re-entrant
    mutex per lane), NOT a hardened scheduler. Acquiring the heavy lane evicts the
    *other* heavy resident first so VRAM only ever holds one of {llama, whisper}.

Everything heavy (the subprocess, the whisper model, the CUDA free-hook) is
injected, so tests drive the full lifecycle without spawning a process, importing
faster-whisper, or touching a GPU.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from ..pathsafe import clean_for_log
from ..util import get_logger

log = get_logger("media_studio.models.runner")

# --------------------------------------------------------------------------- #
# Defaults (CONTRACTS.md §7). The llama.cpp server binary lives on D: per the
# task brief; the port matches provider.DEFAULT_LOCAL_BASE_URL (8088).
# --------------------------------------------------------------------------- #
DEFAULT_LLAMA_SERVER: str = "D:/tools/llama-cpp-cuda/llama-server.exe"
DEFAULT_PORT: int = 8088
DEFAULT_HOST: str = "127.0.0.1"
#: §7 default model is a Qwen3-4B GGUF. The actual path is resolved from settings
#: (modelsDir + this filename) or an explicit gguf_path; this is only the default
#: filename used when settings name a models directory but not a file.
DEFAULT_GGUF_NAME: str = "qwen3-4b.gguf"
#: A conservative context size + GPU offload for a 4B model on a single GPU.
DEFAULT_CTX_SIZE: int = 8192
DEFAULT_GPU_LAYERS: int = 999  # offload all layers; llama.cpp clamps to available

# Lane identifiers for the single-heavy-model lock.
LANE_LLAMA: str = "llama"
LANE_WHISPER: str = "whisper"

# A subprocess spawn seam: (argv list) -> a process handle. Injected in tests.
PopenLike = Callable[..., Any]
# A whisper loader seam: () -> a loaded model object. Injected in tests so the
# heavy faster-whisper import never happens here.
WhisperLoad = Callable[[], Any]
# A CUDA/torch free-hook: () -> None (e.g. torch.cuda.empty_cache). Injected so no
# torch import is required; default is a no-op.
FreeHook = Callable[[], None]


def _noop_free() -> None:
    """Default free-hook: do nothing (no torch present / nothing to free)."""
    return None


def _normalize_model_path(path: str) -> str:
    """Normalize a GGUF path for identity comparison (T3 model-switch).

    Backslashes become forward slashes and case is folded so the same Windows
    file spelled two ways compares equal. CONTRACT-NOTE: casefolding may treat
    two genuinely case-distinct files on a case-sensitive filesystem as the same
    model — acceptable for model files, which never differ by case alone.
    """
    return str(path).replace("\\", "/").casefold()


def _same_model(current: str | None, requested: str | None) -> bool:
    """True when ``requested`` names the model already serving (both non-None)."""
    if current is None or requested is None:
        return False
    return _normalize_model_path(current) == _normalize_model_path(requested)


# --------------------------------------------------------------------------- #
# argv builder (pure function — fully unit-testable, no subprocess)
# --------------------------------------------------------------------------- #
def build_server_argv(
    gguf_path: str,
    *,
    server_path: str = DEFAULT_LLAMA_SERVER,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    ctx_size: int = DEFAULT_CTX_SIZE,
    gpu_layers: int = DEFAULT_GPU_LAYERS,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the argv list to launch the llama.cpp server (CONTRACTS.md §7).

    Returns a **list** (never a shell string) so a GGUF path with spaces is safe.
    Mirrors the task brief: ``<server> -m <gguf> --port <port>`` plus host, ctx,
    and GPU-offload flags. ``extra_args`` are appended verbatim for power users.
    """
    if not gguf_path:
        raise ValueError("gguf_path is required to launch the llama.cpp server")
    argv: list[str] = [
        server_path,
        "-m",
        gguf_path,
        "--host",
        host,
        "--port",
        str(int(port)),
        "--ctx-size",
        str(int(ctx_size)),
        "--n-gpu-layers",
        str(int(gpu_layers)),
    ]
    if extra_args:
        argv += [str(a) for a in extra_args]
    return argv


def resolve_gguf_path(
    settings: dict[str, Any] | None = None,
    *,
    default_name: str = DEFAULT_GGUF_NAME,
) -> str | None:
    """Resolve the GGUF model path from ``settings`` (CONTRACTS.md §2).

    Order: explicit ``settings.ggufPath`` (a file) -> ``settings.modelsDir`` +
    ``default_name``. Returns ``None`` when neither is configured (the caller then
    raises a clear error rather than launching with a bogus path). Path joining is
    string-level (no filesystem touch) so this stays a pure, testable helper.
    """
    settings = settings or {}
    explicit = settings.get("ggufPath")
    if explicit:
        return str(explicit)
    models_dir = settings.get("modelsDir")
    if models_dir:
        base = str(models_dir).replace("\\", "/").rstrip("/")
        return f"{base}/{default_name}"
    return None


# --------------------------------------------------------------------------- #
# LaneLock: enforce ONE heavy model resident at a time
# --------------------------------------------------------------------------- #
class LaneLock:
    """A dead-simple single-occupant lane (CONTRACTS.md §7 "one heavy model").

    NOT a hardened scheduler: just a mutex protecting a single ``occupant`` slot.
    Acquiring a lane for one occupant when a *different* occupant holds it invokes
    an injected ``evict`` callback for the current occupant first, then records the
    new one. Re-acquiring for the same occupant is a no-op (idempotent).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._occupant: str | None = None

    @property
    def occupant(self) -> str | None:
        """The lane currently resident in the heavy slot (or ``None``)."""
        with self._lock:
            return self._occupant

    def acquire(self, lane: str, evict: Callable[[str], None]) -> None:
        """Make ``lane`` the sole occupant, evicting any different current one.

        ``evict(current_lane)`` is called (under the lock) to free the displaced
        resident before ``lane`` takes the slot. No-op when ``lane`` already holds
        it. ``evict`` must not raise; the runner wraps the real free-hook so a
        free failure cannot wedge the lane.
        """
        with self._lock:
            if self._occupant == lane:
                return
            if self._occupant is not None:
                log.info("lane swap: evicting %s for %s", self._occupant, lane)
                evict(self._occupant)
            self._occupant = lane

    def release(self, lane: str) -> None:
        """Clear the slot iff ``lane`` is the current occupant (else no-op)."""
        with self._lock:
            if self._occupant == lane:
                self._occupant = None


# --------------------------------------------------------------------------- #
# ModelRunner: the lifecycle owner
# --------------------------------------------------------------------------- #
class ModelRunner:
    """Owns the llama.cpp server process and the in-proc whisper model (§7).

    Load-use-free: nothing heavy is resident until something is needed, and the
    :class:`LaneLock` guarantees only one of {llama server, whisper model} holds
    the heavy slot at a time (the other is torn down on demand).

    All heavy effects are injected:
      * ``popen``        — spawns the llama.cpp server (default ``subprocess.Popen``)
      * ``whisper_load`` — returns a loaded whisper model (no default; required to
                           load whisper, but never imported here)
      * ``free_hook``    — CUDA/torch cache-clear after freeing whisper (default no-op)
    """

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        popen: PopenLike = subprocess.Popen,
        whisper_load: WhisperLoad | None = None,
        free_hook: FreeHook = _noop_free,
        server_path: str = DEFAULT_LLAMA_SERVER,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._settings = dict(settings or {})
        self._popen = popen
        self._whisper_load = whisper_load
        self._free_hook = free_hook
        self._server_path = server_path
        self._host = host
        self._port = port

        self._lane = LaneLock()
        self._server_proc: Any | None = None
        self._server_model_path: str | None = None
        self._whisper_model: Any | None = None
        self._lock = threading.RLock()

    # -- introspection -----------------------------------------------------
    @property
    def server_running(self) -> bool:
        """True while a llama.cpp server process is live (started, not stopped)."""
        with self._lock:
            return self._server_proc is not None and not _proc_exited(self._server_proc)

    @property
    def whisper_loaded(self) -> bool:
        """True while a whisper model is resident in-process."""
        with self._lock:
            return self._whisper_model is not None

    @property
    def current_model_path(self) -> str | None:
        """The GGUF path the live llama.cpp server was launched with (T3).

        ``None`` when no server has been started or after it was stopped. The
        path is recorded verbatim (un-normalized); identity comparison happens
        through :func:`_same_model`.
        """
        with self._lock:
            return self._server_model_path

    @property
    def heavy_occupant(self) -> str | None:
        """Which lane currently holds the single heavy slot (or ``None``)."""
        return self._lane.occupant

    # -- the per-lane evictor (wired into the LaneLock) --------------------
    def _evict(self, lane: str) -> None:
        """Free whichever resident currently holds ``lane`` (never raises).

        Called by :class:`LaneLock` when a different lane needs the heavy slot.
        Wrapped so a teardown failure is logged but cannot wedge the lock.
        """
        try:
            if lane == LANE_LLAMA:
                self._stop_server_locked()
            elif lane == LANE_WHISPER:
                self._free_whisper_locked()
        except Exception as exc:  # noqa: BLE001 - eviction must not raise into the lock
            log.warning("evict of lane %s failed: %s", lane, exc)

    # -- llama.cpp server PROCESS lifecycle --------------------------------
    def start_server(
        self,
        *,
        gguf_path: str | None = None,
        gpu_layers: int | None = None,
        extra_args: list[str] | None = None,
    ) -> Any:
        """Start the llama.cpp server, claiming the heavy lane (evicts whisper).

        Resolves the GGUF path from ``gguf_path`` or settings, builds the argv
        list, and spawns via the injected ``popen``. Returns the process handle.

        Model-identity-aware (T3): if a server is already running with the SAME
        model (or no model could be resolved at all), the live process is reused
        as-is; if it is serving a DIFFERENT GGUF, it is gracefully stopped
        (terminate -> wait -> kill) and a fresh server is launched with the new
        model. ``gpu_layers`` overrides the default full offload (the tiered
        translator's heavy tier launches with partial offload); ``extra_args``
        are appended verbatim.

        CONTRACT-NOTE: §7 — starting the LLM server evicts a resident whisper
        model first so only one heavy model occupies VRAM at a time. The lane
        lock semantics are unchanged: a model SWITCH stays within LANE_LLAMA.
        CONTRACT-NOTE: launch options (gpu_layers/extra_args) are NOT part of
        the model identity — re-requesting the same GGUF with different options
        reuses the running server rather than restarting it.
        """
        with self._lock:
            requested = gguf_path or resolve_gguf_path(self._settings)
            if self._server_proc is not None:
                if not _proc_exited(self._server_proc):
                    if requested is None or _same_model(self._server_model_path, requested):
                        return self._server_proc
                    # Different model requested: graceful stop, then relaunch.
                    log.info("model switch: %s -> %s", self._server_model_path, requested)
                    self._stop_server_locked()
                else:
                    # Stale handle (the server crashed/exited on its own).
                    self._stop_server_locked()
            if not requested:
                raise ValueError("no GGUF model configured (set settings.ggufPath or settings.modelsDir)")
            # Claim the heavy lane BEFORE spawning so whisper is freed first.
            self._lane.acquire(LANE_LLAMA, self._evict)
            # T5 (WIRING-T5 §3): an UNTOUCHED default resolves through the
            # tools_resolver chain (settings.llamaServerPath -> env
            # MEDIA_STUDIO_LLAMA_SERVER -> %APPDATA% tool dirs -> dev path) so a
            # fresh machine needs no D:\tools; an injected server_path (tests/
            # explicit config) is used verbatim.
            server_path = self._server_path
            if server_path == DEFAULT_LLAMA_SERVER:
                from .. import tools_resolver  # local import: keeps module light

                server_path = tools_resolver.resolve_llama_server(self._settings) or server_path
            argv = build_server_argv(
                requested,
                server_path=server_path,
                host=self._host,
                port=self._port,
                gpu_layers=DEFAULT_GPU_LAYERS if gpu_layers is None else int(gpu_layers),
                extra_args=extra_args,
            )
            log.info("starting llama.cpp server: %s", clean_for_log(" ".join(argv)))
            # argv list only — no shell=True (CONTRACTS.md §6 subprocess safety).
            # stdout/stderr -> DEVNULL: the server runs for the sidecar's
            # lifetime, so an inherited stdout would pollute the JSON-RPC
            # protocol stream and an unread PIPE would freeze it (A6 lesson 2).
            self._server_proc = self._popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._server_model_path = requested
            return self._server_proc

    def stop_server(self) -> None:
        """Stop the llama.cpp server (terminate, then kill if it lingers)."""
        with self._lock:
            self._stop_server_locked()
            self._lane.release(LANE_LLAMA)

    def _stop_server_locked(self) -> None:
        """Inner stop (caller holds ``self._lock``); leaves lane handling to caller."""
        proc = self._server_proc
        if proc is None:
            return
        log.info("stopping llama.cpp server")
        _terminate_proc(proc)
        self._server_proc = None
        self._server_model_path = None

    # -- faster-whisper in-proc lifecycle ----------------------------------
    def load_whisper(self) -> Any:
        """Load the whisper model in-proc, claiming the heavy lane (evicts llama).

        The actual model construction happens in the injected ``whisper_load`` seam
        (so faster-whisper is never imported here). Idempotent: a model already
        resident is returned as-is. Returns the loaded model.

        CONTRACT-NOTE: §7 — loading whisper evicts a running llama.cpp server first
        (stops the process) so VRAM holds only one heavy model.
        """
        with self._lock:
            if self._whisper_model is not None:
                return self._whisper_model
            if self._whisper_load is None:
                raise ValueError("ModelRunner was constructed without a whisper_load seam")
            # Claim the heavy lane BEFORE loading so the llama server is stopped first.
            self._lane.acquire(LANE_WHISPER, self._evict)
            log.info("loading faster-whisper in-proc")
            self._whisper_model = self._whisper_load()
            return self._whisper_model

    def free_whisper(self) -> None:
        """Free the resident whisper model and run the CUDA free-hook (§7)."""
        with self._lock:
            self._free_whisper_locked()
            self._lane.release(LANE_WHISPER)

    def _free_whisper_locked(self) -> None:
        """Inner free (caller holds ``self._lock``); drops the ref + clears CUDA."""
        if self._whisper_model is None:
            return
        log.info("freeing faster-whisper + clearing CUDA cache")
        self._whisper_model = None
        try:
            # torch.cuda.empty_cache()-style reclamation behind an injected hook.
            self._free_hook()
        except Exception as exc:  # noqa: BLE001 - cache-clear failure is non-fatal
            log.warning("free_hook failed: %s", exc)

    # -- whole-runner teardown --------------------------------------------
    def shutdown(self) -> None:
        """Tear everything down (server + whisper); safe to call repeatedly."""
        with self._lock:
            self._stop_server_locked()
            self._free_whisper_locked()
            self._lane.release(LANE_LLAMA)
            self._lane.release(LANE_WHISPER)

    # -- context-manager sugar (load-use-free ergonomics) ------------------
    def __enter__(self) -> ModelRunner:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.shutdown()


# --------------------------------------------------------------------------- #
# process helpers (mirror ffmpeg._terminate; injectable handles in tests)
# --------------------------------------------------------------------------- #
def _proc_exited(proc: Any) -> bool:
    """True if ``proc`` has already exited (``poll()`` returns non-None)."""
    poll = getattr(proc, "poll", None)
    if poll is None:
        return False
    try:
        return poll() is not None
    except Exception:  # noqa: BLE001 - a flaky poll() must not crash status checks
        return False


def _terminate_proc(proc: Any) -> None:
    """Cooperatively stop a process: terminate, wait, then kill if it lingers."""
    with contextlib.suppress(Exception):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        with contextlib.suppress(Exception):
            proc.kill()
