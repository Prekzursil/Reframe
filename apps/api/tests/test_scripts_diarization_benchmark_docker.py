from __future__ import annotations

from pathlib import Path


def test_benchmark_docker_script_forces_fresh_worker_build():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "benchmark_diarization_docker.sh"
    text = script_path.read_text(encoding="utf-8")

    assert (
        "run --rm --build" in text
    ), "benchmark_diarization_docker.sh must pass --build to docker compose run to avoid stale worker image code"
