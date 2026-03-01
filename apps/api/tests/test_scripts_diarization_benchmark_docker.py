from __future__ import annotations

from pathlib import Path


def test_benchmark_docker_script_forces_fresh_worker_build():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "benchmark_diarization_docker.sh"
    text = script_path.read_text(encoding="utf-8")

    assert (
        "run --rm --build" in text
    ), "benchmark_diarization_docker.sh must pass --build to docker compose run to avoid stale worker image code"


def test_benchmark_docker_script_does_not_embed_hf_token_values_in_cli_args():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "benchmark_diarization_docker.sh"
    text = script_path.read_text(encoding="utf-8")

    assert (
        'compose_run_env_args=(-e "HF_TOKEN=${hf_token}" -e "HUGGINGFACE_TOKEN=${hf_token}")' not in text
    ), "HF token values must not be passed directly in docker CLI arguments"
    assert (
        "compose_run_env_args=(-e HF_TOKEN -e HUGGINGFACE_TOKEN)" in text
    ), "docker compose should pass only variable names and read values from process env"
