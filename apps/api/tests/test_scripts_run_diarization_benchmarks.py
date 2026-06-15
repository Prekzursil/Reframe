from __future__ import annotations

from pathlib import Path


def test_run_diarization_benchmarks_avoids_inline_token_assignment_in_command_line():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "run_diarization_benchmarks.sh"
    text = script_path.read_text(encoding="utf-8")

    if 'if HF_TOKEN="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}" bash scripts/benchmark_diarization_docker.sh' in text:
        raise AssertionError("inline HF_TOKEN=... command prefix leaks token values in process args")
    if "export HF_TOKEN=" not in text or "export HUGGINGFACE_TOKEN=" not in text:
        raise AssertionError("script must export token variables before invoking benchmark helper")


def test_run_diarization_benchmarks_supports_local_reuse_flag_and_validation():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "run_diarization_benchmarks.sh"
    text = script_path.read_text(encoding="utf-8")

    required_snippets = (
        "--reuse-existing",
        'REUSE_EXISTING="true"',
        "can_reuse_existing_benchmark()",
        'if [[ "${REUSE_EXISTING}" == "true" ]] && can_reuse_existing_benchmark; then',
        'cpu_status == "failed"',
        'payload.get("stamp") != expected_stamp',
        'cat "${STATUS_JSON}"',
    )
    for snippet in required_snippets:
        if snippet not in text:
            raise AssertionError(f"missing reuse guard snippet: {snippet}")
