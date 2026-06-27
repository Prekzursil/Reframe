"""First-run self-diagnostic — validate the install END-TO-END and report LOUDLY.

WU-2: a single ``system.selfTest`` RPC that checks, in one pass over injectable
probe seams, the things a fresh install needs before it can render a single frame,
and returns a structured pass/fail report the Electron setup-status panel renders
1:1. NO silent partial state: every failing capability surfaces a human problem
line + an actionable fix hint, so the app never proceeds into a broken render.

Checks (the wire ``id`` the panel keys on):

  * ``data``   — the per-user data dir is writable (write+read+delete a probe).
  * ``device`` — the hardware probe (:mod:`system_advisor`) runs: GPU / VRAM / RAM
    / free disk (informational — a missing GPU degrades speed, not capability).
  * ``cv2``    — OpenCV + MediaPipe importable (the reframe subject-tracking core).
  * ``asr``    — the Whisper ASR backend (``faster_whisper``) importable.
  * ``ffmpeg`` — ffmpeg + ffprobe resolvable via :mod:`tools_resolver`.

Design mirrors :mod:`system_advisor`: PURE verdict builders + injectable probe
seams (filesystem write, hardware detect, ``importlib.find_spec``, tool resolve).
Nothing heavy is ever imported; a probe failure degrades to a reported problem,
never a crash.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..util import get_logger

log = get_logger("media_studio.features.self_test")

# --------------------------------------------------------------------------- #
# human copy (labels + fix hints) — surfaced verbatim in the setup-status panel
# --------------------------------------------------------------------------- #
DATA_LABEL = "Writable data folder"
DATA_FIX = "Choose a different data folder in Settings, or fix the folder's permissions, then re-run the check."

DEVICE_LABEL = "Device probe"
DEVICE_FIX = "Update your GPU driver. The app still works without a GPU — moment-finding just runs slower on CPU."

CV2_LABEL = "Reframe engine (OpenCV + MediaPipe)"
CV2_FIX = "Reframe needs OpenCV + MediaPipe — reinstall the app or run setup to restore the bundled Python deps."

ASR_LABEL = "Speech-to-text engine (Whisper)"
ASR_FIX = "The Whisper engine needs faster-whisper — reinstall the app or run setup to restore the bundled Python deps."

FFMPEG_LABEL = "Media tools (FFmpeg)"
FFMPEG_FIX = "ffmpeg/ffprobe were not found — install FFmpeg and add it to PATH, or set its path in Settings."

# Probe-key module names (a single import-availability family per dependency).
_CV2_MODULES: tuple[str, ...] = ("cv2", "mediapipe")
_ASR_MODULES: tuple[str, ...] = ("faster_whisper",)
_DEP_MODULES: tuple[str, ...] = ("cv2", "mediapipe", "faster_whisper")
_FFMPEG_TOOLS: tuple[str, ...] = ("ffmpeg", "ffprobe")

#: the probe file the data-dir writability check writes/reads/deletes.
_PROBE_NAME = ".reframe-selftest-probe"
_PROBE_TOKEN = "reframe-selftest-ok"


# --------------------------------------------------------------------------- #
# report shape (frozen, JSON-safe for the RPC the UI renders)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CheckResult:
    """One self-diagnostic check's verdict for the UI.

    ``required`` marks a check whose failure BLOCKS a working render (data / deps /
    media tools); an informational check (``device``) is surfaced but does not flip
    the overall ``ok``. ``fix_hint`` is the actionable remedy, populated only when
    the check failed (empty on success).
    """

    id: str
    label: str
    ok: bool
    required: bool
    detail: str
    fix_hint: str


@dataclass(frozen=True)
class SelfTestReport:
    """The full diagnostic result — a JSON-serializable frozen tree for the UI."""

    ok: bool
    checks: tuple[CheckResult, ...]
    problems: tuple[str, ...]


# --------------------------------------------------------------------------- #
# pure check builders
# --------------------------------------------------------------------------- #
def _mb(value: int | None) -> str:
    """Render an MB count for the device summary (``None`` -> ``"unknown"``)."""
    return f"{value} MB" if value is not None else "unknown"


def data_check(*, writable: bool, error: str = "") -> CheckResult:
    """Verdict for the data-dir writability probe (a REQUIRED check)."""
    if writable:
        return CheckResult("data", DATA_LABEL, True, True, "Data folder is writable.", "")
    detail = f"Cannot write to the data folder: {error}" if error else "Cannot write to the data folder."
    return CheckResult("data", DATA_LABEL, False, True, detail, DATA_FIX)


def device_check(
    *,
    vram_mb: int | None,
    ram_mb: int | None,
    cpu_count: int | None,
    gpu_present: bool,
    disk_free_mb: int | None,
    error: str = "",
) -> CheckResult:
    """Verdict for the hardware probe (INFORMATIONAL — never blocks ``ok``)."""
    if error:
        return CheckResult("device", DEVICE_LABEL, False, False, f"Device probe failed: {error}", DEVICE_FIX)
    detail = "; ".join(
        [
            f"GPU: {'yes' if gpu_present else 'none'}",
            f"VRAM: {_mb(vram_mb)}",
            f"RAM: {_mb(ram_mb)}",
            f"CPU cores: {cpu_count if cpu_count is not None else 'unknown'}",
            f"free disk: {_mb(disk_free_mb)}",
        ]
    )
    return CheckResult("device", DEVICE_LABEL, True, False, detail, "")


def dependency_check(
    check_id: str,
    label: str,
    fix_hint: str,
    *,
    present_map: Mapping[str, bool],
    modules: Sequence[str],
) -> CheckResult:
    """Verdict for a native-dependency family (REQUIRED) from an import-availability map."""
    missing = [m for m in modules if not present_map.get(m, False)]
    if not missing:
        return CheckResult(check_id, label, True, True, f"{label} available.", "")
    return CheckResult(check_id, label, False, True, f"missing: {', '.join(missing)}", fix_hint)


def tool_check(
    check_id: str,
    label: str,
    fix_hint: str,
    *,
    paths: Mapping[str, str | None],
    names: Sequence[str],
) -> CheckResult:
    """Verdict for a set of external tools (REQUIRED) from their resolved paths."""
    missing = [n for n in names if not paths.get(n)]
    if not missing:
        return CheckResult(check_id, label, True, True, "; ".join(f"{n}: {paths[n]}" for n in names), "")
    return CheckResult(check_id, label, False, True, f"not found: {', '.join(missing)}", fix_hint)


def build_report(checks: Sequence[CheckResult]) -> SelfTestReport:
    """Roll a list of checks up to the report: ``ok`` iff all REQUIRED checks pass.

    ``problems`` lists EVERY failing check (required or not) as a human line with
    its fix hint, so the panel surfaces an informational failure (e.g. no GPU)
    without flipping the blocking ``ok`` verdict.
    """
    checks = tuple(checks)
    ok = all(c.ok for c in checks if c.required)
    problems = tuple(
        f"{c.label}: {c.detail} Fix: {c.fix_hint}" if c.fix_hint else f"{c.label}: {c.detail}"
        for c in checks
        if not c.ok
    )
    return SelfTestReport(ok=ok, checks=checks, problems=problems)


# --------------------------------------------------------------------------- #
# probe seams (real I/O behind injectable callables; every default fail-open)
# --------------------------------------------------------------------------- #
def probe_data_dir(
    data_dir: str | Path,
    *,
    probe_io: Callable[[Path], str] | None = None,
) -> tuple[bool, str]:
    """Write+read+delete a probe file under ``data_dir``; return ``(writable, error)``.

    ``probe_io`` is an injectable seam returning the read-back token; the default
    does the real round-trip. Any failure (permission, full disk) is caught and
    returned as a human error string — never raised.
    """
    runner = probe_io or _default_data_probe_io
    try:
        echoed = runner(Path(data_dir))
    except Exception as exc:
        log.debug("data-dir writability probe failed", exc_info=True)
        return False, str(exc)
    if echoed != _PROBE_TOKEN:
        return False, "probe file readback mismatch"
    return True, ""


def _default_data_probe_io(data_dir: Path) -> str:
    """Real round-trip: mkdir -> write -> read -> delete; return the read content."""
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = data_dir / _PROBE_NAME
    probe.write_text(_PROBE_TOKEN, encoding="utf-8")
    content = probe.read_text(encoding="utf-8")
    probe.unlink()
    return content


def probe_dependencies(*, find_spec: Callable[[str], object] | None = None) -> dict[str, bool]:
    """Build the import-availability map for the native deps WITHOUT importing them.

    Uses ``importlib.util.find_spec`` (an injectable seam) so nothing heavy is
    imported. A bad spec lookup degrades to absent, never raises.
    """
    spec_fn = find_spec or _default_find_spec
    out: dict[str, bool] = {}
    for module_name in _DEP_MODULES:
        try:
            out[module_name] = spec_fn(module_name) is not None
        except Exception:
            out[module_name] = False
    return out


def _default_find_spec(module_name: str) -> object:
    """Default import-availability probe (no actual import)."""
    return importlib.util.find_spec(module_name)


def probe_disk_free_mb(
    path: str | Path,
    *,
    disk_usage: Callable[[Path], object] | None = None,
) -> int | None:
    """Free disk space (MB) on ``path``'s volume, or ``None`` when undeterminable."""
    usage_fn = disk_usage or _default_disk_usage
    try:
        usage = usage_fn(Path(path))
    except Exception:
        log.debug("disk-usage probe failed", exc_info=True)
        return None
    free = getattr(usage, "free", None)
    if free is None:
        return None
    return int(free // (1024 * 1024))


def _default_disk_usage(path: Path) -> object:
    """Default free-space probe via ``shutil.disk_usage``."""
    return shutil.disk_usage(path)


# --------------------------------------------------------------------------- #
# end-to-end composition
# --------------------------------------------------------------------------- #
def run(
    *,
    data_dir: str | Path,
    hardware_probe: object,
    resolve_tool: Callable[[str], str | None],
    find_spec: Callable[[str], object] | None = None,
    probe_io: Callable[[Path], str] | None = None,
    disk_usage: Callable[[Path], object] | None = None,
) -> SelfTestReport:
    """Probe everything and assemble the :class:`SelfTestReport`.

    ``hardware_probe`` is any object with a ``detect()`` returning VRAM/RAM/CPU/GPU
    facts (the :class:`system_advisor.HardwareProbe`); a probe that raises is
    reported as a (non-blocking) device failure. ``resolve_tool`` resolves an
    external tool name to a path (or ``None``). All other heavy probes are behind
    seams; nothing heavy is imported.
    """
    writable, error = probe_data_dir(data_dir, probe_io=probe_io)
    data = data_check(writable=writable, error=error)

    try:
        hw: object | None = hardware_probe.detect()  # type: ignore[attr-defined]
        device_error = ""
    except Exception as exc:
        log.debug("hardware probe failed during self-test", exc_info=True)
        hw = None
        device_error = str(exc)
    device = device_check(
        vram_mb=getattr(hw, "vram_mb", None),
        ram_mb=getattr(hw, "ram_mb", None),
        cpu_count=getattr(hw, "cpu_count", None),
        gpu_present=bool(getattr(hw, "gpu_present", False)),
        disk_free_mb=probe_disk_free_mb(data_dir, disk_usage=disk_usage),
        error=device_error,
    )

    deps = probe_dependencies(find_spec=find_spec)
    cv2 = dependency_check("cv2", CV2_LABEL, CV2_FIX, present_map=deps, modules=_CV2_MODULES)
    asr = dependency_check("asr", ASR_LABEL, ASR_FIX, present_map=deps, modules=_ASR_MODULES)

    tool_paths = {name: resolve_tool(name) for name in _FFMPEG_TOOLS}
    ffmpeg = tool_check("ffmpeg", FFMPEG_LABEL, FFMPEG_FIX, paths=tool_paths, names=_FFMPEG_TOOLS)

    return build_report([data, device, cv2, asr, ffmpeg])


__all__ = [
    "CheckResult",
    "SelfTestReport",
    "build_report",
    "data_check",
    "dependency_check",
    "device_check",
    "probe_data_dir",
    "probe_dependencies",
    "probe_disk_free_mb",
    "run",
    "tool_check",
]
