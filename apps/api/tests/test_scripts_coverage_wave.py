from __future__ import annotations

import argparse
import json
import sys
import types
from dataclasses import dataclass
from enum import Enum
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_script(name: str):
    scripts_dir = _repo_root() / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    module_path = scripts_dir / f"{name}.py"
    spec = spec_from_file_location(name, module_path)
    _expect(spec is not None and spec.loader is not None, f"Unable to load module spec for {name}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_readiness_helpers_and_safe_paths(tmp_path):
    module = _load_script("release_readiness_report")

    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)

    safe = module._safe_output_path("docs/out.json", root / "fallback.json", root=root)
    _expect(safe == (root / "docs" / "out.json"), "Expected relative path to resolve under repo root")

    with pytest.raises(ValueError):
        module._safe_output_path("../escape.json", root / "fallback.json", root=root)

    rel = module._display_path(root / "docs" / "out.json", root)
    _expect(rel.replace("\\", "/") == "docs/out.json", "Expected display path relative to repo root")


def test_release_readiness_resolve_status_matrix():
    module = _load_script("release_readiness_report")

    status, blocking, external = module._resolve_status(local_ok=True, updater_ok=True, pyannote_cpu_status="ok")
    _expect(status == "READY", "Expected READY when all gates are green")
    _expect(blocking == [], "Expected no blocking reasons")
    _expect(external == [], "Expected no external blockers")

    status, blocking, external = module._resolve_status(
        local_ok=True,
        updater_ok=True,
        pyannote_cpu_status="blocked_external",
    )
    _expect(status == "READY_WITH_EXTERNAL_BLOCKER", "Expected external-blocker readiness status")
    _expect(blocking == [], "Expected no blocking reasons for external-only blocker")
    _expect(len(external) == 1, "Expected one external blocker detail")

    status, blocking, _external = module._resolve_status(local_ok=False, updater_ok=False, pyannote_cpu_status="failed")
    _expect(status == "NOT_READY", "Expected NOT_READY for failed local/updater/pyannote")
    _expect(len(blocking) == 3, "Expected three blocking reasons")


def test_release_readiness_main_ready_with_external_blocker(monkeypatch):
    module = _load_script("release_readiness_report")

    stamp = "2099-01-01"
    out_md = "tmp/release-readiness-wave/report.md"
    out_json = "tmp/release-readiness-wave/report.json"

    def fake_load_json(path: Path):
        text = str(path).replace("\\", "/")
        if text.endswith(f"{stamp}-updater-e2e-windows.json"):
            return {"success": True, "platform": "windows"}
        if text.endswith(f"{stamp}-updater-e2e-macos.json"):
            return {"success": True, "platform": "macos"}
        if text.endswith(f"{stamp}-updater-e2e-linux.json"):
            return {"success": True, "platform": "linux"}
        if text.endswith(f"{stamp}-pyannote-benchmark-status.json"):
            return {"cpu": {"status": "blocked_external"}, "gpu": {"status": "unknown"}}
        return None

    monkeypatch.setattr(module, "_load_json", fake_load_json)
    monkeypatch.setattr(module, "_load_latest_updater_result", lambda _plans, _platform: (None, None))
    monkeypatch.setattr(module, "_collect_gh_status", lambda _repo: {"ci": {"conclusion": "success"}, "codeql": {"conclusion": "success"}, "branch_protection": {"required_reviews": 1, "linear_history": True}})

    rc = module.main(
        [
            "--stamp",
            stamp,
            "--verify-exit",
            "0",
            "--smoke-hosted-exit",
            "0",
            "--smoke-local-exit",
            "0",
            "--smoke-security-exit",
            "0",
            "--smoke-workflows-exit",
            "0",
            "--smoke-perf-cost-exit",
            "0",
            "--diarization-exit",
            "0",
            "--out-md",
            out_md,
            "--out-json",
            out_json,
        ]
    )

    _expect(rc == 0, "Expected READY_WITH_EXTERNAL_BLOCKER to be non-failing")
    repo = _repo_root()
    payload = json.loads((repo / out_json).read_text(encoding="utf-8"))
    _expect(payload["status"] == "READY_WITH_EXTERNAL_BLOCKER", "Expected external blocker status in summary")
    _expect(payload.get("external_blocker_tracking", {}).get("issue_url"), "Expected external blocker tracking metadata")


def test_upsert_ops_digest_main_create_and_update(monkeypatch, tmp_path):
    module = _load_script("upsert_ops_digest_issue")

    repo = _repo_root()
    digest_json = repo / "tmp" / "ops-digest" / "digest.json"
    digest_md = repo / "tmp" / "ops-digest" / "digest.md"
    out_json = repo / "tmp" / "ops-digest" / "out.json"
    digest_json.parent.mkdir(parents=True, exist_ok=True)
    digest_json.write_text(json.dumps({"metrics": {}, "trends": {}, "health": {}}), encoding="utf-8")
    digest_md.write_text("# digest\n", encoding="utf-8")

    monkeypatch.setenv("GITHUB_TOKEN", "token")

    args = argparse.Namespace(
        repo="Prekzursil/Reframe",
        digest_json=str(digest_json.relative_to(repo)),
        digest_md=str(digest_md.relative_to(repo)),
        out_json=str(out_json.relative_to(repo)),
        title="Weekly Ops Digest (rolling)",
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)

    calls = {"mode": "create", "posts": 0, "patches": 0}

    def fake_request(path: str, token: str, method: str = "GET", body=None):
        _ = token
        if method == "GET" and path.startswith("/repos/Prekzursil/Reframe/issues?"):
            return [] if calls["mode"] == "create" else [{"number": 88, "title": "Weekly Ops Digest (rolling)", "html_url": "https://example.test/88"}]
        if method == "POST":
            calls["posts"] += 1
            return {"number": 88, "html_url": "https://example.test/88"}
        if method == "PATCH":
            calls["patches"] += 1
            return {"number": 88, "html_url": "https://example.test/88"}
        raise AssertionError(f"Unexpected request: {method} {path} body={body!r}")

    monkeypatch.setattr(module, "_request_json", fake_request)

    rc_create = module.main()
    _expect(rc_create == 0, "Expected create flow to succeed")
    _expect(calls["posts"] == 1, "Expected one POST for create flow")

    calls["mode"] = "update"
    rc_update = module.main()
    _expect(rc_update == 0, "Expected update flow to succeed")
    _expect(calls["patches"] == 1, "Expected one PATCH for update flow")


def test_benchmark_diarization_extract_and_main_paths(monkeypatch, tmp_path, capsys):
    module = _load_script("benchmark_diarization")

    with pytest.raises(FileNotFoundError):
        monkeypatch.setattr(module.shutil, "which", lambda _name: None)
        module._extract_wav_16k_mono(tmp_path / "in.wav", tmp_path / "out.wav")

    recorded = {}
    monkeypatch.setattr(module.shutil, "which", lambda _name: "ffmpeg")
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, check, capture_output, shell: recorded.setdefault("cmd", cmd))
    module._extract_wav_16k_mono(tmp_path / "in.wav", tmp_path / "out.wav")
    _expect(recorded["cmd"][0] == "ffmpeg", "Expected ffmpeg command execution")

    fake_path_guard = types.ModuleType("media_core.transcribe.path_guard")
    def _validate_media_input_path(value):
        return Path(value)

    fake_path_guard.validate_media_input_path = _validate_media_input_path

    class _Backend(Enum):
        PYANNOTE = "pyannote"
        SPEECHBRAIN = "speechbrain"

    @dataclass
    class _Config:
        backend: _Backend
        model: str
        huggingface_token: str | None
        min_segment_duration: float

    fake_diarize = types.ModuleType("media_core.diarize")
    fake_diarize.DiarizationBackend = _Backend
    fake_diarize.DiarizationConfig = _Config
    fake_diarize.diarize_audio = lambda _wav, _cfg: ["s1", "s2"]

    monkeypatch.setitem(sys.modules, "media_core.transcribe.path_guard", fake_path_guard)
    monkeypatch.setitem(sys.modules, "media_core.diarize", fake_diarize)

    input_file = tmp_path / "sample.wav"
    input_file.write_bytes(b"wav")
    monkeypatch.setattr(module, "_extract_wav_16k_mono", lambda _inp, out: out.write_bytes(b"wav16"))
    monkeypatch.setattr(module, "_get_peak_rss_mb", lambda: 123.4)

    rc_blocked = module.main([
        str(input_file),
        "--backend",
        "pyannote",
        "--model",
        "pyannote/speaker-diarization-3.1",
    ])
    _expect(rc_blocked == 2, "Expected missing HF token path to return 2")

    rc_ok = module.main([
        str(input_file),
        "--backend",
        "speechbrain",
        "--runs",
        "2",
        "--format",
        "md",
    ])
    _expect(rc_ok == 0, "Expected benchmark main success for speechbrain backend")
    _expect("Diarization benchmark" in capsys.readouterr().out, "Expected markdown output")


def test_transcribe_main_module_paths(monkeypatch, tmp_path, capsys):
    module_path = _repo_root() / "packages" / "media-core" / "src" / "media_core" / "transcribe" / "__main__.py"
    spec = spec_from_file_location("media_core.transcribe.__main__", module_path)
    _expect(spec is not None and spec.loader is not None, "Expected __main__ module spec")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    media_file = tmp_path / "audio.wav"
    media_file.write_bytes(b"audio")

    monkeypatch.setattr(module, "parse_args", lambda: argparse.Namespace(input=str(media_file), language="en", backend="noop", model="whisper-1", device="cpu"))
    monkeypatch.setattr(module, "validate_media_input_path", lambda _p: media_file)

    class _Result:
        def model_dump(self):
            return {"text": "ok", "words": []}

    monkeypatch.setattr(module, "transcribe_noop", lambda _path, _cfg: _Result())
    _expect(module.main() == 0, "Expected noop backend path to pass")

    monkeypatch.setattr(module, "parse_args", lambda: argparse.Namespace(input=str(media_file), language=None, backend="invalid", model="m", device=None))
    _expect(module.main() == 1, "Expected invalid backend to fail")

    monkeypatch.setattr(module, "parse_args", lambda: argparse.Namespace(input=str(media_file), language="en", backend="noop", model="m", device=None))
    monkeypatch.setattr(module, "validate_media_input_path", lambda _p: (_ for _ in ()).throw(ValueError("bad path")))
    _expect(module.main() == 1, "Expected invalid input path to fail")

    monkeypatch.setattr(module, "validate_media_input_path", lambda _p: media_file)
    monkeypatch.setattr(module, "transcribe_noop", lambda _path, _cfg: (_ for _ in ()).throw(RuntimeError("boom")))
    _expect(module.main() == 1, "Expected transcription exception path to fail")
    _expect("Tip: use backend 'noop'" in capsys.readouterr().err, "Expected offline tip on transcription failure")
