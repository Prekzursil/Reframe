"""Tests for media_studio.features.health — the system.health diagnostic.

Every heavy/external probe is injected: a fake ``run`` for the ffmpeg version
subprocess, a fake ``find_spec`` / ``pkg_version`` for the no-import backend
probe, a tmp ``root`` for the model-cache paths. No subprocess, no model import.
"""

from __future__ import annotations

from typing import Any

import pytest
from media_studio import ffmpeg as _ffmpeg
from media_studio.features import health
from media_studio.protocol import RpcContext


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def fake_ctx() -> RpcContext:
    return RpcContext(emit_notification=lambda *_: None, jobs=None)


@pytest.fixture()
def settings():
    return {"offline": False}


# --------------------------------------------------------------------------- #
# pure: parse_ffmpeg_version
# --------------------------------------------------------------------------- #
class TestParseFfmpegVersion:
    def test_standard_line(self):
        out = "ffmpeg version 6.1.1 Copyright (c) 2000-2023\n built with gcc"
        assert health.parse_ffmpeg_version(out) == "6.1.1"

    def test_ffprobe_line(self):
        assert health.parse_ffmpeg_version("ffprobe version n7.0 Copyright") == "n7.0"

    def test_unexpected_shape_falls_back_to_first_line(self):
        assert health.parse_ffmpeg_version("custom build blah") == "custom build blah"

    def test_empty(self):
        assert health.parse_ffmpeg_version("") == ""
        assert health.parse_ffmpeg_version("   \n  ") == ""


# --------------------------------------------------------------------------- #
# Health.report
# --------------------------------------------------------------------------- #
class TestReport:
    def _service(self, monkeypatch, tmp_path, *, settings, present=True, run=None, spec=None, ver=None):
        # ffmpeg/ffprobe resolution: a present chain returns a path, else raises.
        if present:
            monkeypatch.setattr(_ffmpeg, "resolve_binary", lambda name, s: f"/bin/{name}")
        else:

            def _raise(name, s):
                raise _ffmpeg.FfmpegNotFound(name)

            monkeypatch.setattr(_ffmpeg, "resolve_binary", _raise)
        return health.Health(
            settings_provider=lambda: settings,
            root=tmp_path,
            run=run or (lambda argv: FakeCompleted(0, "ffmpeg version 6.1 Copyright")),
            find_spec=spec or (lambda mod: object()),  # everything "installed"
            pkg_version=ver or (lambda dist: "1.2.3"),
            env={},
        )

    def test_ok_true_when_both_tools_present(self, monkeypatch, tmp_path, settings):
        svc = self._service(monkeypatch, tmp_path, settings=settings, present=True)
        report = svc.report({}, fake_ctx())
        assert report["ok"] is True
        tools = {t["name"]: t for t in report["tools"]}
        assert tools["ffmpeg"]["present"] is True
        assert tools["ffmpeg"]["version"] == "6.1"
        assert tools["ffmpeg"]["path"] == "/bin/ffmpeg"

    def test_ok_false_and_hint_when_tool_missing(self, monkeypatch, tmp_path, settings):
        svc = self._service(monkeypatch, tmp_path, settings=settings, present=False)
        report = svc.report({}, fake_ctx())
        assert report["ok"] is False
        ff = next(t for t in report["tools"] if t["name"] == "ffmpeg")
        assert ff["present"] is False
        assert ff["hint"]  # actionable hint present

    def test_offline_reflected(self, monkeypatch, tmp_path):
        svc = self._service(monkeypatch, tmp_path, settings={"offline": True})
        assert svc.report({}, fake_ctx())["offline"] is True

    def test_backends_probed_without_import(self, monkeypatch, tmp_path, settings):
        # find_spec returns None for torch -> not installed; others installed.
        def spec(mod):
            return None if mod == "torch" else object()

        svc = self._service(monkeypatch, tmp_path, settings=settings, spec=spec)
        report = svc.report({}, fake_ctx())
        by_mod = {b["module"]: b for b in report["backends"]}
        assert by_mod["torch"]["installed"] is False
        assert by_mod["torch"]["version"] == ""
        assert by_mod["faster_whisper"]["installed"] is True
        assert by_mod["faster_whisper"]["version"] == "1.2.3"

    def test_backend_spec_error_is_treated_as_absent(self, monkeypatch, tmp_path, settings):
        def spec(mod):
            raise ImportError("broken install")

        svc = self._service(monkeypatch, tmp_path, settings=settings, spec=spec)
        report = svc.report({}, fake_ctx())
        assert all(b["installed"] is False for b in report["backends"])

    def test_backend_version_metadata_miss_is_blank(self, monkeypatch, tmp_path, settings):
        def ver(dist):
            raise health._md.PackageNotFoundError(dist)

        svc = self._service(monkeypatch, tmp_path, settings=settings, ver=ver)
        report = svc.report({}, fake_ctx())
        assert all(b["installed"] and b["version"] == "" for b in report["backends"])

    def test_model_paths_have_exists_flags(self, monkeypatch, tmp_path, settings):
        (tmp_path / "models").mkdir()
        svc = self._service(monkeypatch, tmp_path, settings=settings)
        report = svc.report({}, fake_ctx())
        labels = {p["label"]: p for p in report["modelPaths"]}
        assert labels["Data root"]["exists"] is True
        assert labels["Models"]["exists"] is True
        assert labels["llama (CUDA)"]["exists"] is False

    def test_models_dir_setting_surfaced(self, monkeypatch, tmp_path):
        svc = self._service(monkeypatch, tmp_path, settings={"modelsDir": "D:/m"})
        report = svc.report({}, fake_ctx())
        assert any(p["label"] == "Models dir (setting)" for p in report["modelPaths"])

    def test_engines_resolved(self, monkeypatch, tmp_path, settings):
        import media_studio.tools_resolver as tr

        monkeypatch.setattr(tr, "resolve_tool", lambda name, s, **kw: "/x/wsl" if name == "wsl" else None)
        svc = self._service(monkeypatch, tmp_path, settings=settings)
        report = svc.report({}, fake_ctx())
        by_name = {e["name"]: e for e in report["engines"]}
        assert by_name["wsl"]["available"] is True
        assert by_name["wsl"]["path"] == "/x/wsl"
        assert by_name["llama-server"]["available"] is False

    def test_engine_resolve_crash_is_swallowed(self, monkeypatch, tmp_path, settings):
        import media_studio.tools_resolver as tr

        def boom(name, s, **kw):
            raise RuntimeError("resolver blew up")

        monkeypatch.setattr(tr, "resolve_tool", boom)
        svc = self._service(monkeypatch, tmp_path, settings=settings)
        report = svc.report({}, fake_ctx())
        assert all(e["available"] is False for e in report["engines"])

    def test_settings_provider_failure_is_tolerated(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_ffmpeg, "resolve_binary", lambda name, s: f"/bin/{name}")

        def boom():
            raise RuntimeError("settings gone")

        svc = health.Health(settings_provider=boom, root=tmp_path, run=lambda a: FakeCompleted(0, ""), env={})
        report = svc.report({}, fake_ctx())
        assert report["ok"] is True  # still produced a report

    def test_version_subprocess_failure_is_blank(self, monkeypatch, tmp_path, settings):
        def run(argv):
            raise OSError("cannot spawn")

        svc = self._service(monkeypatch, tmp_path, settings=settings, run=run)
        report = svc.report({}, fake_ctx())
        ff = next(t for t in report["tools"] if t["name"] == "ffmpeg")
        assert ff["present"] is True
        assert ff["version"] == ""

    def test_version_nonzero_exit_is_blank(self, monkeypatch, tmp_path, settings):
        svc = self._service(monkeypatch, tmp_path, settings=settings, run=lambda a: FakeCompleted(1, "junk"))
        report = svc.report({}, fake_ctx())
        ff = next(t for t in report["tools"] if t["name"] == "ffmpeg")
        assert ff["version"] == ""


# --------------------------------------------------------------------------- #
# _default_run (the real subprocess seam — exercised with a mocked subprocess)
# --------------------------------------------------------------------------- #
def test_default_run_invokes_subprocess_with_drained_argv(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return FakeCompleted(0, "ffmpeg version 6.1 Copyright")

    monkeypatch.setattr(health.subprocess, "run", fake_run)
    completed = health._default_run(["/bin/ffmpeg", "-version"])
    assert completed.stdout.startswith("ffmpeg version")
    assert captured["argv"] == ["/bin/ffmpeg", "-version"]
    # argv list + drained pipes, shell never (A6 lesson 4)
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["check"] is False


# --------------------------------------------------------------------------- #
# register
# --------------------------------------------------------------------------- #
def test_register_installs_system_health():
    registered: dict[str, Any] = {}
    health.register(settings_provider=lambda: {}, register_fn=lambda n, f: registered.__setitem__(n, f))
    assert "system.health" in registered
