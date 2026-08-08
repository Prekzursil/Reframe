"""WU-2 — first-run self-diagnostic (``self_test`` pure module) tests.

The diagnostic validates a fresh install END-TO-END and reports LOUDLY: a data-dir
writability probe, a device probe (system_advisor hardware), the required native
deps (cv2 for reframe's YuNet detector, the faster-whisper ASR backend), and
ffmpeg/ffprobe resolution. Every probe is an INJECTED seam here so the suite touches no
real GPU, no heavy import, and (mostly) no real filesystem — the §WU-2 acceptance
criteria are pinned directly on the pure :func:`run` composition:

  * ok-path -> every check green, no problems;
  * missing cv2 -> a reported problem with an OpenCV fix hint;
  * non-writable data dir -> a reported problem with a fix hint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from media_studio import ffmpeg as _ff
from media_studio.features import self_test as st
from media_studio.features.system_advisor import HardwareInfo
from runtime_setup.bootstrap import SIDECAR_REQUIREMENTS, load_requirements


class _FakeProbe:
    """A HardwareProbe-shaped seam: ``detect()`` returns a fixed HardwareInfo."""

    def __init__(self, info: HardwareInfo | None = None, *, raises: bool = False) -> None:
        self._info = info or HardwareInfo(vram_mb=6000, ram_mb=16000, cpu_count=8, gpu_present=True)
        self._raises = raises

    def detect(self) -> HardwareInfo:
        if self._raises:
            raise RuntimeError("nvml exploded")
        return self._info


def _find_spec(present: set[str]):
    """A find_spec seam: returns a truthy spec only for module names in ``present``."""
    return lambda name: object() if name in present else None


def _disk(free_mb: int):
    """A disk_usage seam returning an object with a ``.free`` byte count."""
    return lambda _p: type("U", (), {"free": free_mb * 1024 * 1024})()


def _all_present() -> set[str]:
    return {"cv2", "faster_whisper"}


def _run(tmp_path: Path, **over: Any) -> st.SelfTestReport:
    base: dict[str, Any] = {
        "data_dir": tmp_path / "data",
        "hardware_probe": _FakeProbe(),
        "resolve_tool": lambda name: f"/usr/bin/{name}",
        "find_spec": _find_spec(_all_present()),
        "disk_usage": _disk(50_000),
        # `resolve_tool` above hands back a FICTIONAL path, so the real
        # `ffmpeg -encoders` seam would (correctly) fail on it. Stub the encoder
        # probe to a capable build so these cases keep testing what they are about.
        # The encoder check's own behaviour is covered in test_ffmpeg_encoders.py,
        # against the REAL captured output of both the GPL and LGPL builds.
        "probe_encoders": lambda _p: {_ff.H264_ENCODER, "aac"},
    }
    base.update(over)
    return st.run(**base)


# --------------------------------------------------------------------------- #
# §WU-2 acceptance — the three falsifiable paths
# --------------------------------------------------------------------------- #
def test_ok_path_all_green(tmp_path: Path) -> None:
    report = _run(tmp_path)
    assert report.ok is True
    assert report.problems == ()
    assert all(c.ok for c in report.checks)
    # `encoder` follows `ffmpeg` deliberately: presence first, then CAPABILITY on
    # that same resolved binary (a resolvable ffmpeg that cannot encode H.264 is
    # exactly the state that shipped a fully-green panel over a broken product).
    assert [c.id for c in report.checks] == ["data", "device", "cv2", "asr", "ffmpeg", "encoder"]


def test_missing_cv2_is_reported_with_fix_hint(tmp_path: Path) -> None:
    report = _run(tmp_path, find_spec=_find_spec({"faster_whisper"}))
    assert report.ok is False
    cv2 = next(c for c in report.checks if c.id == "cv2")
    assert cv2.ok is False
    assert "cv2" in cv2.detail
    assert "OpenCV" in cv2.fix_hint
    assert any("OpenCV" in p for p in report.problems)


def test_non_writable_data_dir_is_reported(tmp_path: Path) -> None:
    def boom(_p: Path) -> str:
        raise PermissionError("read-only file system")

    report = _run(tmp_path, probe_io=boom)
    assert report.ok is False
    data = next(c for c in report.checks if c.id == "data")
    assert data.ok is False
    assert "read-only file system" in data.detail
    assert data.fix_hint != ""
    assert any("read-only file system" in p for p in report.problems)


# --------------------------------------------------------------------------- #
# pure check builders
# --------------------------------------------------------------------------- #
def test_data_check_ok() -> None:
    c = st.data_check(writable=True)
    assert c.id == "data" and c.ok is True and c.required is True and c.fix_hint == ""


def test_data_check_failure_with_error() -> None:
    c = st.data_check(writable=False, error="disk full")
    assert c.ok is False and "disk full" in c.detail and c.fix_hint != ""


def test_data_check_failure_without_error() -> None:
    c = st.data_check(writable=False)
    assert c.ok is False and c.detail and c.fix_hint != ""


def test_device_check_ok_summarizes_hardware() -> None:
    c = st.device_check(vram_mb=6000, ram_mb=16000, cpu_count=8, gpu_present=True, disk_free_mb=50_000)
    assert c.id == "device" and c.ok is True and c.required is False
    assert "6000 MB" in c.detail and "50000 MB" in c.detail and "yes" in c.detail


def test_device_check_handles_unknown_fields() -> None:
    c = st.device_check(vram_mb=None, ram_mb=None, cpu_count=None, gpu_present=False, disk_free_mb=None)
    assert c.ok is True and "unknown" in c.detail and "none" in c.detail


def test_device_check_failure_when_probe_raised() -> None:
    c = st.device_check(
        vram_mb=None,
        ram_mb=None,
        cpu_count=None,
        gpu_present=False,
        disk_free_mb=None,
        error="nvml exploded",
    )
    assert c.ok is False and "nvml exploded" in c.detail and c.fix_hint != ""


def test_dependency_check_all_present() -> None:
    # A generic MULTI-module family (the builder takes any ``modules`` tuple).
    c = st.dependency_check(
        "deps",
        "Native deps",
        "reinstall",
        present_map={"cv2": True, "faster_whisper": True},
        modules=("cv2", "faster_whisper"),
    )
    assert c.ok is True and c.fix_hint == ""


def test_dependency_check_reports_missing() -> None:
    c = st.dependency_check(
        "deps",
        "Native deps",
        "reinstall",
        present_map={"cv2": True, "faster_whisper": False},
        modules=("cv2", "faster_whisper"),
    )
    assert c.ok is False and "faster_whisper" in c.detail and c.fix_hint == "reinstall"


def test_tool_check_all_present() -> None:
    c = st.tool_check(
        "ffmpeg",
        "FFmpeg",
        "add to PATH",
        paths={"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"},
        names=("ffmpeg", "ffprobe"),
    )
    assert c.ok is True and "/usr/bin/ffmpeg" in c.detail and c.fix_hint == ""


def test_tool_check_reports_missing() -> None:
    c = st.tool_check(
        "ffmpeg",
        "FFmpeg",
        "add to PATH",
        paths={"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": None},
        names=("ffmpeg", "ffprobe"),
    )
    assert c.ok is False and "ffprobe" in c.detail and c.fix_hint == "add to PATH"


# --------------------------------------------------------------------------- #
# build_report rollup
# --------------------------------------------------------------------------- #
def test_build_report_ok_when_required_pass_even_if_optional_fails() -> None:
    checks = [
        st.CheckResult("data", "Data", True, True, "ok", ""),
        st.CheckResult("device", "Device", False, False, "probe failed", "plug in a GPU"),
    ]
    report = st.build_report(checks)
    # The optional device failure does NOT block ok, but is still surfaced.
    assert report.ok is True
    assert any("plug in a GPU" in p for p in report.problems)


def test_build_report_not_ok_when_required_fails() -> None:
    checks = [st.CheckResult("data", "Data", False, True, "no write", "fix perms")]
    report = st.build_report(checks)
    assert report.ok is False and report.problems and "fix perms" in report.problems[0]


def test_build_report_problem_without_fix_hint() -> None:
    checks = [st.CheckResult("x", "X", False, True, "broke", "")]
    report = st.build_report(checks)
    assert report.problems == ("X: broke",)


# --------------------------------------------------------------------------- #
# probe seams
# --------------------------------------------------------------------------- #
def test_probe_data_dir_real_roundtrip(tmp_path: Path) -> None:
    writable, error = st.probe_data_dir(tmp_path / "fresh")
    assert writable is True and error == ""
    # The probe file is cleaned up (no residue).
    assert list((tmp_path / "fresh").iterdir()) == []


def test_probe_data_dir_reports_io_failure(tmp_path: Path) -> None:
    def boom(_p: Path) -> str:
        raise OSError("nope")

    writable, error = st.probe_data_dir(tmp_path, probe_io=boom)
    assert writable is False and "nope" in error


def test_probe_data_dir_detects_readback_mismatch(tmp_path: Path) -> None:
    writable, error = st.probe_data_dir(tmp_path, probe_io=lambda _p: "corrupted")
    assert writable is False and "mismatch" in error


def test_probe_dependencies_with_injected_find_spec() -> None:
    out = st.probe_dependencies(find_spec=_find_spec({"cv2"}))
    assert out["cv2"] is True and out["faster_whisper"] is False


def test_probe_dependencies_fail_open_on_find_spec_error() -> None:
    def boom(_name: str) -> object:
        raise ImportError("broken loader")

    out = st.probe_dependencies(find_spec=boom)
    assert out == {"cv2": False, "faster_whisper": False}


def test_probe_dependencies_default_find_spec_runs() -> None:
    # Exercises the real importlib seam (no injection). Only the KEY SET is
    # asserted: whether each dep is present is environment-dependent (CI installs
    # opencv-python-headless but deliberately not faster-whisper).
    out = st.probe_dependencies()
    assert set(out) == {"cv2", "faster_whisper"}


def test_probe_disk_free_mb_with_seam() -> None:
    assert st.probe_disk_free_mb(Path("."), disk_usage=_disk(1234)) == 1234


def test_probe_disk_free_mb_none_when_no_free_field() -> None:
    assert st.probe_disk_free_mb(Path("."), disk_usage=lambda _p: object()) is None


def test_probe_disk_free_mb_fail_open(tmp_path: Path) -> None:
    def boom(_p: Path) -> object:
        raise OSError("statvfs failed")

    assert st.probe_disk_free_mb(tmp_path, disk_usage=boom) is None


def test_probe_disk_free_mb_default_runs(tmp_path: Path) -> None:
    # Exercises the real shutil.disk_usage seam on a real dir.
    free = st.probe_disk_free_mb(tmp_path)
    assert free is None or free >= 0


# --------------------------------------------------------------------------- #
# run() composition — device-probe failure path
# --------------------------------------------------------------------------- #
def test_run_reports_device_probe_failure(tmp_path: Path) -> None:
    report = _run(tmp_path, hardware_probe=_FakeProbe(raises=True))
    device = next(c for c in report.checks if c.id == "device")
    assert device.ok is False and "nvml exploded" in device.detail
    # device is optional, so a green data/cv2/asr/ffmpeg still leaves ok True.
    assert report.ok is True


def test_run_uses_real_disk_seam_by_default(tmp_path: Path) -> None:
    report = _run(tmp_path, disk_usage=None)
    assert report.ok is True


@pytest.mark.parametrize("missing", ["ffmpeg", "ffprobe"])
def test_run_reports_missing_ffmpeg_tool(tmp_path: Path, missing: str) -> None:
    report = _run(tmp_path, resolve_tool=lambda name: None if name == missing else f"/b/{name}")
    ffmpeg = next(c for c in report.checks if c.id == "ffmpeg")
    assert ffmpeg.ok is False and missing in ffmpeg.detail
    assert report.ok is False


# --------------------------------------------------------------------------- #
# INVARIANT — a REQUIRED probe may only name a module the provisioner installs
# --------------------------------------------------------------------------- #
#: pinned dist name (in requirements-sidecar.txt) -> the import name probed here.
#: Only dists whose import name differs from a ``-``->``_`` normalisation need a row.
_DIST_TO_IMPORT_NAME = {"opencv-python": "cv2", "faster-whisper": "faster_whisper"}


def _provisioned_import_names() -> set[str]:
    """Import names the FIRST-RUN provisioner actually installs.

    Derived from the shipped pin list that :mod:`runtime_setup.bootstrap` installs
    from (``SIDECAR_REQUIREMENTS``), so the invariant below is HERMETIC — it reads
    a committed file and never consults the ambient environment.
    """
    dists = {pin.split("==", 1)[0].strip() for pin in load_requirements(SIDECAR_REQUIREMENTS).pins}
    return {_DIST_TO_IMPORT_NAME.get(d, d.replace("-", "_")) for d in dists}


@pytest.mark.parametrize("attr", ["_DEP_MODULES", "_CV2_MODULES", "_ASR_MODULES"])
def test_every_required_probe_module_is_provisioned(attr: str) -> None:
    """A REQUIRED check may only probe modules first-run provisioning installs.

    F37: ``mediapipe`` sat in ``_CV2_MODULES``/``_DEP_MODULES`` while
    ``requirements-sidecar.txt`` DELIBERATELY excludes it (the Solutions-API
    wheels declare ``numpy<2``, a hard conflict with the pinned ``numpy==2.5.1``),
    so EVERY correctly-provisioned install reported the blocking red setup banner
    with a fix hint that could not possibly work. This pins the whole regression
    class shut — any future required module that is not pinned — not just the one
    stale name. ``_ASR_MODULES`` is the passing control: it proves the detector
    can also report a clean subset, so a red here is a real violation.
    """
    unprovisioned = sorted(set(getattr(st, attr)) - _provisioned_import_names())
    assert unprovisioned == [], (
        f"self_test.{attr} makes a REQUIRED check probe module(s) that "
        f"runtime_setup/requirements-sidecar.txt never installs: {unprovisioned}. "
        f"Either pin the dist there, or stop requiring the module."
    )
