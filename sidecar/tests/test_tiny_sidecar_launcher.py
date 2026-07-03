"""Lean-gate unit coverage for the E2E tiny-CPU sidecar launcher's Windows-hang
fix (bug #4).

``tests/e2e/_tiny_sidecar.py`` is spawned as a CHILD process by the real-pipeline
E2E harness (``real_pipeline_smoke.py`` PHASE B). On Windows the FIRST import of a
native C-extension DLL (numpy / av / ctranslate2 / ...) from a JOB THREAD deadlocks
while the main thread is parked in ``sys.stdin.readline()`` (the sidecar's normal
serving state). The production composition root ``media_studio.__main__`` already
guards this by pre-importing the natives in the MAIN thread before it serves; the
E2E launcher previously omitted that step, so the harness hung forever at
``transcribe.start`` on Windows.

These tests pin that the launcher REUSES the exact production pre-serve hardening
(so the native list can never drift) and runs it BEFORE any handler registration
or the stdio serve loop. No real stdio loop is served and no native is actually
imported: the seams are monkeypatched. Marked lean (NOT ``e2e``) so it runs in the
default 100%-coverage gate.
"""

from __future__ import annotations

import tests.e2e._tiny_sidecar as tiny


def test_main_runs_windows_native_hardening_before_serving(monkeypatch, tmp_path):
    """main(): suppresses Windows error dialogs and PRE-IMPORTS the natives in the
    main thread BEFORE it registers handlers or serves — the bug #4 Windows-hang
    fix — then registers a tiny/cpu whisper loader at the env data dir and returns
    ``rpc.main()``'s exit code."""
    calls: list[str] = []
    monkeypatch.setenv("MEDIA_STUDIO_E2E_DATADIR", str(tmp_path))
    monkeypatch.setattr(tiny, "_suppress_windows_error_dialogs", lambda: calls.append("suppress"))
    monkeypatch.setattr(tiny, "_preimport_native_modules", lambda: calls.append("preimport"))

    captured: dict[str, object] = {}

    def fake_register_all(services):
        calls.append("register")
        captured["services"] = services

    def fake_rpc_main():
        calls.append("serve")
        return 0

    monkeypatch.setattr(tiny.handlers, "register_all", fake_register_all)
    monkeypatch.setattr(tiny.rpc, "main", fake_rpc_main)

    rc = tiny.main()

    assert rc == 0
    # The native pre-import MUST happen (main thread) BEFORE any handler wiring or
    # the serve loop — otherwise the first job-thread DLL load deadlocks the child.
    assert calls == ["suppress", "preimport", "register", "serve"]
    # Forced-deviation preserved: a tiny/cpu whisper loader rooted at the env dir.
    svc = captured["services"]
    assert isinstance(svc, tiny.handlers.Services)
    assert svc.data_dir == tmp_path
    assert isinstance(svc._whisper_loader, tiny.TinyCpuWhisperLoader)


def test_main_reuses_production_hardening_seams(monkeypatch):
    """The launcher must REUSE the production ``media_studio.__main__`` hardening
    (not a private reimplementation), so the pre-imported native list can never
    drift from production. Assert the launcher's bound names ARE those functions."""
    import media_studio.__main__ as entry

    assert tiny._preimport_native_modules is entry._preimport_native_modules
    assert tiny._suppress_windows_error_dialogs is entry._suppress_windows_error_dialogs


def test_main_requires_datadir_env(monkeypatch, capsys):
    """No data dir -> exit 2, and the hardening/serve seams are never reached."""
    monkeypatch.delenv("MEDIA_STUDIO_E2E_DATADIR", raising=False)
    reached: list[str] = []
    monkeypatch.setattr(tiny, "_preimport_native_modules", lambda: reached.append("preimport"))
    monkeypatch.setattr(tiny.rpc, "main", lambda: reached.append("serve"))

    assert tiny.main() == 2
    assert reached == []
    assert "MEDIA_STUDIO_E2E_DATADIR is required" in capsys.readouterr().err
