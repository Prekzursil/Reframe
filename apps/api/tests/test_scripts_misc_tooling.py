from __future__ import annotations

import argparse
import json
import sys
import types
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


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


def test_prefetch_whisper_model_missing_dependency(capsys):
    module = _load_script("prefetch_whisper_model")

    rc = module.main(["--model", "large-v3"])

    _expect(rc == 2, "Expected missing faster-whisper dependency to return 2")
    _expect("faster-whisper is not installed" in capsys.readouterr().err, "Expected dependency error message")


def test_prefetch_whisper_model_success(monkeypatch, capsys):
    module = _load_script("prefetch_whisper_model")

    calls: list[tuple[str, dict[str, str]]] = []

    class FakeWhisperModel:
        def __init__(self, model_name: str, **kwargs):
            calls.append((model_name, kwargs))

    fake_backend = types.ModuleType("media_core.transcribe.backends.faster_whisper")
    fake_backend._normalize_model_name = lambda value: f"normalized-{value}"

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = FakeWhisperModel

    monkeypatch.setitem(sys.modules, "media_core.transcribe.backends.faster_whisper", fake_backend)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)

    rc = module.main(["--model", "large-v3", "--device", "cpu"])

    _expect(rc == 0, "Expected successful prefetch")
    _expect(calls == [("normalized-large-v3", {"device": "cpu"})], "Expected normalized model and device kwargs")
    _expect("Prefetching faster-whisper model" in capsys.readouterr().out, "Expected prefetch output")


def test_install_argos_pack_paths(monkeypatch, capsys):
    module = _load_script("install_argos_pack")

    class FakePackage:
        def __init__(self, src: str, tgt: str):
            self.from_code = src
            self.to_code = tgt

        def download(self):
            return "/tmp/fake.argosmodel"

    class FakeArgos:
        def __init__(self):
            self.updated = False
            self.installed_path = ""

        def update_package_index(self):
            self.updated = True

        def get_available_packages(self):
            return [FakePackage("en", "es"), FakePackage("en", "fr")]

        def install_from_path(self, path: str):
            self.installed_path = path

    fake_argos = FakeArgos()
    monkeypatch.setattr(module, "_ensure_argos", lambda: fake_argos)

    _expect(module.main(["--list"]) == 0, "Expected list flow to pass")
    _expect("en->es" in capsys.readouterr().out, "Expected list output to include en->es")

    _expect(module.main([]) == 2, "Expected missing src/tgt to fail")
    _expect("--src and --tgt are required" in capsys.readouterr().err, "Expected src/tgt requirement message")

    _expect(module.main(["--src", "en", "--tgt", "de"]) == 3, "Expected unavailable pair to fail")
    _expect("No Argos pack found for en->de" in capsys.readouterr().err, "Expected no-pack message")

    _expect(module.main(["--src", "en", "--tgt", "es"]) == 0, "Expected install flow to pass")
    _expect(fake_argos.installed_path == "/tmp/fake.argosmodel", "Expected install_from_path invocation")


def test_generate_benchmark_sample_main_and_path_guard(monkeypatch, tmp_path):
    module = _load_script("generate_benchmark_sample")

    _expect(module._sample_value(2.2) == 0.0, "Expected silent bucket sample to be zero")

    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    try:
        module._safe_output_path("../escape.wav", base=repo)
        raise AssertionError("Expected ValueError for escaping output path")
    except ValueError:
        pass

    out_wav = tmp_path / "sample.wav"
    args = argparse.Namespace(out="samples/sample.wav", duration=0.02, sample_rate=8000)
    monkeypatch.setattr(module.argparse.ArgumentParser, "parse_args", lambda _self: args)
    monkeypatch.setattr(module, "_safe_output_path", lambda *_args, **_kwargs: out_wav)

    rc = module.main()

    _expect(rc == 0, "Expected benchmark sample generation to succeed")
    _expect(out_wav.is_file(), "Expected WAV output file to exist")
    _expect(out_wav.stat().st_size > 44, "Expected WAV file with audio payload")


def test_download_whispercpp_model_behaviors(monkeypatch, tmp_path, capsys):
    module = _load_script("download_whispercpp_model")

    _expect(module._normalize_filename("large-v3") == "ggml-large-v3.bin", "Expected normalized ggml filename")
    _expect(module._normalize_filename("ggml-base.en.bin") == "ggml-base.en.bin", "Expected pre-prefixed filename")

    try:
        module._normalize_filename("bad*name")
        raise AssertionError("Expected invalid filename to fail")
    except ValueError:
        pass

    out_dir = tmp_path / "models"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "ggml-large-v3.bin"
    existing.write_text("ready", encoding="utf-8")

    monkeypatch.setattr(module, "_resolve_output_dir", lambda *_args, **_kwargs: out_dir)
    rc_existing = module.main(["--model", "large-v3"])
    _expect(rc_existing == 0, "Expected existing file fast-path")
    _expect("Already present" in capsys.readouterr().out, "Expected already-present message")

    rc_bad_url = module.main(["--base-url", "http://example.com"])
    _expect(rc_bad_url == 2, "Expected non-https base URL to fail")

    downloaded = out_dir / "ggml-small.bin"
    monkeypatch.setattr(module, "_download", lambda _url, dest: dest.write_text("model", encoding="utf-8"))
    rc_download = module.main(["--model", "small", "--force"])
    _expect(rc_download == 0, "Expected download path to succeed")
    _expect(downloaded.is_file(), "Expected downloaded model file")


def test_verify_desktop_updater_release_main_paths(monkeypatch, capsys):
    module = _load_script("verify_desktop_updater_release")

    payload = {
        "version": "0.1.8",
        "pub_date": "2026-03-03T00:00:00Z",
        "platforms": {
            "windows-x86_64": {
                "url": "https://example.com/app.exe",
                "signature": "A" * 40,
            }
        },
    }
    monkeypatch.setattr(module, "_fetch_bytes", lambda _url: json.dumps(payload).encode("utf-8"))
    monkeypatch.setattr(module, "_head_with_retries", lambda _url: 200)

    rc_ok = module.main(["--endpoint", "https://example.com/latest.json"])
    _expect(rc_ok == 0, "Expected updater release verification to pass")
    _expect("OK: updater JSON looks valid" in capsys.readouterr().out, "Expected success output")

    monkeypatch.setattr(module, "_head_with_retries", lambda _url: 404)
    rc_fail = module.main(["--endpoint", "https://example.com/latest.json"])
    _expect(rc_fail == 1, "Expected inaccessible platform URL to fail")


def test_verify_hf_model_access_paths(monkeypatch, tmp_path):
    module = _load_script("verify_hf_model_access")

    dotenv_repo = tmp_path / "repo"
    dotenv_repo.mkdir(parents=True, exist_ok=True)
    (dotenv_repo / ".env").write_text("HF_TOKEN=token-from-env-file\n", encoding="utf-8")

    token = module._load_token("", dotenv_repo)
    _expect(token == "token-from-env-file", "Expected token lookup from .env")

    missing = module._probe("https://huggingface.co/x/resolve/main/config.yaml", "", model="x")
    _expect(missing.status == "missing_token", "Expected missing-token probe state")

    @dataclass
    class _FakeResult:
        timestamp_utc: str
        status: str
        model: str
        url: str
        http_status: int | None
        error: str | None

    monkeypatch.setattr(module, "_probe", lambda _url, _token, model: _FakeResult("ts", "ok", model, _url, 200, None))
    rc_ok = module.main(["--token", "abc", "--model", "pyannote/speaker-diarization-3.1"])
    _expect(rc_ok == 0, "Expected hf probe main success")

    monkeypatch.setattr(module, "_probe", lambda _url, _token, model: _FakeResult("ts", "blocked_403", model, _url, 403, "blocked"))
    rc_blocked = module.main(["--token", "abc", "--model", "pyannote/speaker-diarization-3.1"])
    _expect(rc_blocked == 4, "Expected blocked status exit code")


def test_desktop_updater_e2e_paths(monkeypatch, tmp_path):
    module = _load_script("desktop_updater_e2e")

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "_repo_root", lambda: repo)

    verify_failure = module.subprocess.CompletedProcess(args=["verify"], returncode=1, stdout="", stderr="err")

    def run_fail(cmd, *, cwd, env=None):
        _ = (cmd, cwd, env)
        return verify_failure

    monkeypatch.setattr(module, "_run", run_fail)
    rc_fail = module.main(["--platform", "linux"])
    _expect(rc_fail == 1, "Expected verify failure to fail wrapper")

    verify_ok = module.subprocess.CompletedProcess(args=["verify"], returncode=0, stdout="ok", stderr="")
    helper_ok = module.subprocess.CompletedProcess(
        args=["helper"],
        returncode=0,
        stdout=json.dumps({"success": True, "observed_old_version": "0.1.6", "observed_new_version": "0.1.7"}),
        stderr="",
    )
    calls = {"count": 0}

    def run_success(cmd, *, cwd, env=None):
        _ = (cmd, cwd, env)
        calls["count"] += 1
        return verify_ok if calls["count"] == 1 else helper_ok

    monkeypatch.setattr(module, "_run", run_success)
    rc_ok = module.main(["--platform", "linux"])
    _expect(rc_ok == 0, "Expected successful updater e2e wrapper")
