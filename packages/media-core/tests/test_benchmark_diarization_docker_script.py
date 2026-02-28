from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_benchmark_script_builds_worker_image_before_run(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "benchmark_diarization_docker.sh"
    assert script_path.is_file()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log_path = tmp_path / "compose_calls.log"
    input_path = tmp_path / "sample.wav"
    input_path.write_bytes(b"RIFF....WAVEfmt ")

    docker_compose = f"""#!/usr/bin/env bash
set -eu
echo "docker-compose $*" >> "{log_path}"
exit 0
"""
    docker = f"""#!/usr/bin/env bash
set -eu
echo "docker $*" >> "{log_path}"
exit 0
"""
    _write_exec(fake_bin / "docker-compose", docker_compose)
    _write_exec(fake_bin / "docker", docker)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    proc = subprocess.run(
        ["bash", str(script_path), str(input_path), "--backend", "speechbrain", "--runs", "1"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr

    calls = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    build_idx = next(i for i, line in enumerate(calls) if " build " in f" {line} ")
    run_idx = next(i for i, line in enumerate(calls) if " run " in f" {line} ")
    assert build_idx < run_idx, calls


def test_benchmark_script_retries_failed_build_before_run(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "benchmark_diarization_docker.sh"
    assert script_path.is_file()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    log_path = tmp_path / "compose_calls_retry.log"
    state_path = tmp_path / "build_attempts.txt"
    input_path = tmp_path / "sample.wav"
    input_path.write_bytes(b"RIFF....WAVEfmt ")

    docker_compose = f"""#!/usr/bin/env bash
set -eu
echo "docker-compose $*" >> "{log_path}"
if echo " $* " | grep -q " build "; then
  n=0
  if [ -f "{state_path}" ]; then
    n="$(cat "{state_path}")"
  fi
  n="$((n + 1))"
  echo "$n" > "{state_path}"
  if [ "$n" -eq 1 ]; then
    exit 1
  fi
fi
exit 0
"""
    docker = f"""#!/usr/bin/env bash
set -eu
echo "docker $*" >> "{log_path}"
exit 0
"""
    _write_exec(fake_bin / "docker-compose", docker_compose)
    _write_exec(fake_bin / "docker", docker)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["REFRAME_DOCKER_BUILD_ATTEMPTS"] = "2"

    proc = subprocess.run(
        ["bash", str(script_path), str(input_path), "--backend", "speechbrain", "--runs", "1"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr

    calls = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    build_calls = [line for line in calls if " build " in f" {line} "]
    run_calls = [line for line in calls if " run " in f" {line} "]
    assert len(build_calls) == 2, calls
    assert len(run_calls) == 1, calls
