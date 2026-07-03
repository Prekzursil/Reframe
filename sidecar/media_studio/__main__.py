"""Assembled sidecar entry point — ``python -m media_studio``.

This is the process the Electron app launches (CONTRACTS.md §1/§2). It is the
composition root the bare ``media_studio.rpc`` core deliberately is NOT: it imports
:mod:`media_studio.handlers` and calls :func:`register_all` so EVERY §2 feature
method lands in ``protocol.METHODS`` BEFORE the stdio JSON-RPC loop starts, then
delegates to ``rpc.main`` to serve stdin until EOF.

Running ``python -m media_studio.rpc`` instead would start the bare core with only
``ping``/``job.*`` registered (every feature call -> METHOD_NOT_FOUND) — that gap
(no composition root) was the whole INTEGRATION-REPORT headline. Launch THIS module.
"""

from __future__ import annotations

import site
import sys
from pathlib import Path

from . import handlers, rpc
from .job_store import DiskJobStore
from .pathsafe import ensure_within
from .settings_store import default_config_dir

#: the first-run env subdir under the data root. Mirrors
#: ``runtime_setup.bootstrap.SIDECAR_ENV_NAME`` (kept a local literal so the
#: runtime never imports the build-time ``runtime_setup`` package).
_SIDECAR_ENV_DIRNAME = "sidecar"


def _activate_sidecar_env() -> None:
    """Put the first-run sidecar env on ``sys.path`` FROM THE DATA ROOT.

    The heavy runtime deps (httpx, numpy, faster-whisper, kokoro-onnx, ...)
    install into the relocatable DATA ROOT at ``<data root>/envs/sidecar`` —
    NEVER the install dir. The embeddable interpreter's ``python3XX._pth`` is the
    *other* mechanism that puts that env on ``sys.path``, but a read-only install
    dir (e.g. ``C:\\Program Files``) CANNOT have its ``._pth`` rewritten by
    first-run bootstrap. The runtime therefore MUST NOT depend on that write: we
    add the env dir via :func:`site.addsitedir` here so its ``site-packages`` and
    ``.pth`` files resolve whether or not the install dir was writable.

    Idempotent (skips when the dir is already on ``sys.path``) and best-effort
    (absence is fine on a dev box that runs from a venv; any filesystem probe
    error returns quietly rather than bricking startup — the ``._pth`` activation
    may still have succeeded). The data root is resolved the SAME way the rest of
    the sidecar resolves it (``MEDIA_STUDIO_CONFIG_DIR`` -> ``%APPDATA%`` -> XDG),
    so it always matches the dir bootstrap provisioned into.
    """
    try:
        env_dir = Path(ensure_within(default_config_dir(), "envs", _SIDECAR_ENV_DIRNAME))
        if not env_dir.is_dir():
            return
        resolved = str(env_dir)
        if resolved in sys.path:
            return
        site.addsitedir(resolved)
    except OSError:
        # A malformed/unreadable data-root path must never crash startup; the
        # ._pth activation (when the install dir was writable) is the fallback.
        return


def _suppress_windows_error_dialogs() -> None:
    """Fail fast instead of blocking on hidden system dialogs (Windows).

    In a windowless piped process, a failed DLL load (e.g. a missing CUDA
    runtime) can pop an INVISIBLE modal error dialog and block the whole
    sidecar forever with zero output — observed live in Phase 0 (the
    cublas64_12.dll hang). SetErrorMode makes such failures raise normal
    exceptions instead, which the job framework reports as job errors.
    """
    if sys.platform != "win32":  # pragma: no cover - windows-only guard
        return
    import ctypes  # noqa: PLC0415 - windows-only, keep import local

    SEM_FAILCRITICALERRORS = 0x0001
    SEM_NOGPFAULTERRORBOX = 0x0002
    SEM_NOOPENFILEERRORBOX = 0x8000
    ctypes.windll.kernel32.SetErrorMode(  # type: ignore[attr-defined]
        SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
    )


def _preimport_native_modules() -> None:
    """Import native-extension modules in the MAIN thread, before serve().

    Phase-0 spine finding (verified with a 4-run matrix + faulthandler stacks):
    on Windows, loading a C-extension DLL (numpy's ``_multiarray_umath`` via
    ``faster_whisper``) from a JOB THREAD deadlocks while the main thread is
    blocked in ``sys.stdin.readline()`` — the sidecar's normal serving state.
    Pre-importing the natives here means job threads never trigger the DLL
    load. Guarded: absence is fine (CPU-only/dev boxes; tests mock the seams).
    Any NEW native dep used inside a job (cv2/scenedetect/mediapipe/onnxruntime)
    MUST be added here, or its first job-thread import can hang the sidecar.
    """
    # P2 additions (A6 lesson 1): mediapipe (T4b claudeshorts reframe),
    # onnxruntime + kokoro_onnx (T2 kokoro TTS), aiohttp (T2 edge-tts C parser).
    # NOT added: soundfile (T2 uses stdlib wave only), scenedetect (pure Python;
    # its native backends cv2/numpy are already in the tuple).
    for mod in (
        "numpy",
        "ctranslate2",
        "cv2",
        "mediapipe",
        "onnxruntime",
        "kokoro_onnx",
        "aiohttp",
        "av",  # faster-whisper's audio decoder (PyAV) — native, loads at transcribe
    ):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001 - optional native, absence is fine
            pass


def main(argv: list[str] | None = None) -> int:
    """Register all feature handlers, then run the stdio JSON-RPC server.

    WU-6 composition seam: ``register_all`` returns the assembled ``Services``
    (the only owner of ``data_dir``), and the ``JobRegistry`` is owned by the
    ``RpcServer`` ``rpc.main`` builds. This is the ONLY place both are visible,
    so here we build a :class:`DiskJobStore` rooted at ``svc.data_dir/jobs`` and
    inject it — ``rpc.main`` rehydrates it once at startup so a job interrupted
    by a prior exit reappears as INTERRUPTED (never auto-restarted, §5).
    """
    _suppress_windows_error_dialogs()
    # Activate the data-root env BEFORE pre-importing natives (they live in it),
    # so the runtime never depends on a writable install dir (the read-only
    # Program Files first-run failure this hardening fixes).
    _activate_sidecar_env()
    _preimport_native_modules()
    svc = handlers.register_all()
    store = DiskJobStore(svc.data_dir / "jobs")
    return rpc.main(argv, store=store)


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
