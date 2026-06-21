"""Smoke coverage for the assembled sidecar entry point (``python -m
media_studio`` -> media_studio.__main__).

No real stdio loop is served and no native module is actually imported: the
composition-root seams (handlers.register_all, rpc.main) and the two pre-serve
guards are mocked/driven directly so the body is exercised without spawning the
JSON-RPC server or touching numpy/cv2/etc.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import media_studio.__main__ as entry
from media_studio.job_store import DiskJobStore


def test_main_composes_and_delegates_to_rpc_main(monkeypatch, tmp_path):
    """main(): runs both pre-serve guards, registers all handlers, builds a
    DiskJobStore rooted at the returned Services.data_dir/jobs, and forwards it
    into rpc.main(argv) — returning rpc.main's exit code (WU-6 composition seam).
    """
    calls: list[str] = []

    monkeypatch.setattr(entry, "_suppress_windows_error_dialogs", lambda: calls.append("suppress"))
    monkeypatch.setattr(entry, "_preimport_native_modules", lambda: calls.append("preimport"))

    fake_svc = SimpleNamespace(data_dir=tmp_path)

    def fake_register_all():
        calls.append("register")
        return fake_svc

    monkeypatch.setattr(entry.handlers, "register_all", fake_register_all)

    captured = {}

    def fake_rpc_main(argv=None, *, store=None):
        captured["argv"] = argv
        captured["store"] = store
        return 0

    monkeypatch.setattr(entry.rpc, "main", fake_rpc_main)

    rc = entry.main(["--flag"])
    assert rc == 0
    # ordering: guards FIRST, then registration, then serve
    assert calls == ["suppress", "preimport", "register"]
    assert captured["argv"] == ["--flag"]
    # the composition seam carries data_dir: a DiskJobStore at data_dir/jobs
    store = captured["store"]
    assert isinstance(store, DiskJobStore)
    assert store.root == Path(tmp_path) / "jobs"


def test_main_propagates_rpc_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(entry, "_suppress_windows_error_dialogs", lambda: None)
    monkeypatch.setattr(entry, "_preimport_native_modules", lambda: None)
    monkeypatch.setattr(entry.handlers, "register_all", lambda: SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(entry.rpc, "main", lambda argv=None, *, store=None: 130)
    assert entry.main() == 130


def test_suppress_windows_error_dialogs_non_win32_is_noop(monkeypatch):
    """On a non-win32 platform the guard returns immediately (the early-return
    pragma branch is skipped — this drives the function's win32==False path)."""
    monkeypatch.setattr(entry.sys, "platform", "linux")
    # Must not touch ctypes; if it did on linux it would explode.
    entry._suppress_windows_error_dialogs()  # returns None, no exception


def test_suppress_windows_error_dialogs_win32_calls_seterrormode(monkeypatch):
    """On win32 the guard imports ctypes and calls SetErrorMode with the three
    SEM_* flags OR'd together."""
    monkeypatch.setattr(entry.sys, "platform", "win32")

    seen = {}

    class FakeKernel32:
        def SetErrorMode(self, mode):  # noqa: N802 - mimic the Windows API name
            seen["mode"] = mode

    class FakeWindll:
        kernel32 = FakeKernel32()

    import ctypes

    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    entry._suppress_windows_error_dialogs()
    # 0x0001 | 0x0002 | 0x8000 == 0x8003
    assert seen["mode"] == 0x8003


def test_preimport_native_modules_swallows_import_errors(monkeypatch):
    """_preimport_native_modules tries each native module and swallows any import
    failure (the absence-is-fine guard). Drive it with a builtins.__import__ that
    always raises so the loop body + except run without importing real natives."""
    import builtins

    attempted: list[str] = []
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {
            "numpy",
            "ctranslate2",
            "cv2",
            "mediapipe",
            "onnxruntime",
            "kokoro_onnx",
            "aiohttp",
            "av",
        }:
            attempted.append(name)
            raise ImportError(f"no {name} here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    entry._preimport_native_modules()  # must not raise
    # every native in the tuple was attempted (and its ImportError swallowed)
    assert "numpy" in attempted
    assert "av" in attempted


def test_preimport_native_modules_imports_present_module(monkeypatch):
    """When a native IS importable the __import__ succeeds (covers the happy
    branch of the try). We make every name resolve to the stdlib `sys` module."""
    import builtins

    real_import = builtins.__import__
    natives = {
        "numpy",
        "ctranslate2",
        "cv2",
        "mediapipe",
        "onnxruntime",
        "kokoro_onnx",
        "aiohttp",
        "av",
    }

    def fake_import(name, *args, **kwargs):
        if name in natives:
            return sys  # a real, already-loaded module: success, no exception
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    entry._preimport_native_modules()  # must not raise
