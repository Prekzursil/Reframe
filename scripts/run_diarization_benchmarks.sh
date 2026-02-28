#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_PATH="${1:-}"
if [[ -z "$INPUT_PATH" ]]; then
  echo "Usage: bash scripts/run_diarization_benchmarks.sh <input-media> [--stamp YYYY-MM-DD] [--runs N] [--run-gpu]" >&2
  exit 2
fi
shift

STAMP="$(date -u +%F)"
RUNS="1"
RUN_GPU="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stamp)
      STAMP="${2:-$STAMP}"
      shift 2
      ;;
    --runs)
      RUNS="${2:-1}"
      shift 2
      ;;
    --run-gpu)
      RUN_GPU="true"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

cd "$ROOT_DIR"
mkdir -p docs/plans

CREATED_ENV_FILE="false"
cleanup_env_file() {
  if [[ "${CREATED_ENV_FILE}" == "true" && -f "${ROOT_DIR}/.env" ]]; then
    rm -f "${ROOT_DIR}/.env"
  fi
}
trap cleanup_env_file EXIT

if [[ ! -f "${ROOT_DIR}/.env" && -f "${ROOT_DIR}/.env.example" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
  CREATED_ENV_FILE="true"
fi

COMPOSE_ENV_FILE_ARGS=()
if [[ -f "${ROOT_DIR}/.env" ]]; then
  COMPOSE_ENV_FILE_ARGS=(--env-file "${ROOT_DIR}/.env")
elif [[ -f "${ROOT_DIR}/.env.example" ]]; then
  COMPOSE_ENV_FILE_ARGS=(--env-file "${ROOT_DIR}/.env.example")
fi

ACCESS_JSON="docs/plans/${STAMP}-pyannote-access.json"
STATUS_JSON="docs/plans/${STAMP}-pyannote-benchmark-status.json"
CPU_MD="docs/plans/${STAMP}-pyannote-benchmark-cpu.md"
GPU_MD="docs/plans/${STAMP}-pyannote-benchmark-gpu.md"
GPU_CAP_JSON="docs/plans/${STAMP}-pyannote-gpu-capability.json"

INPUT_ABS="$(python3 - <<'PY' "$INPUT_PATH"
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)"

PROBE_RC=0
python3 scripts/verify_hf_model_access.py --model pyannote/speaker-diarization-3.1 --out-json "$ACCESS_JSON" >/dev/null || PROBE_RC=$?

CPU_STATUS="not_run"
GPU_STATUS="not_run"
CPU_LOG=""
GPU_LOG=""
DETAILS=""

if [[ "$PROBE_RC" -eq 0 ]]; then
  if HF_TOKEN="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}" bash scripts/benchmark_diarization_docker.sh "$INPUT_ABS" --backend pyannote --warmup --runs "$RUNS" --format md >"$CPU_MD" 2>&1; then
    CPU_STATUS="ok"
  else
    CPU_STATUS="failed"
    CPU_LOG="$CPU_MD"
  fi
else
  CPU_STATUS="blocked_external"
  DETAILS="HF gated access probe failed (exit=${PROBE_RC})."
  cat >"$CPU_MD" <<EOF_CPU
# Pyannote CPU benchmark status (${STAMP})

- status: \`${CPU_STATUS}\`
- reason: \`${DETAILS}\`
- probe_json: \`${ACCESS_JSON}\`

The benchmark command was not executed because model access is not available.
EOF_CPU
fi

GPU_CAP_RC=0
docker compose "${COMPOSE_ENV_FILE_ARGS[@]}" -f infra/docker-compose.yml run --rm worker python - <<'PY' >"$GPU_CAP_JSON" 2>/dev/null || GPU_CAP_RC=$?
import json
import torch
print(json.dumps({
    "torch_version": torch.__version__,
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_device_count": int(torch.cuda.device_count() if torch.cuda.is_available() else 0),
}))
PY

CUDA_AVAILABLE="false"
if [[ "$GPU_CAP_RC" -eq 0 ]]; then
  CUDA_AVAILABLE="$(python3 - <<'PY' "$GPU_CAP_JSON"
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
obj=json.loads(p.read_text(encoding='utf-8'))
print('true' if obj.get('cuda_available') else 'false')
PY
)"
else
  cat >"$GPU_CAP_JSON" <<EOF_GPU_JSON
{"cuda_available": false, "cuda_device_count": 0, "error": "docker probe failed"}
EOF_GPU_JSON
fi

if [[ "$RUN_GPU" == "true" && "$CUDA_AVAILABLE" == "true" && "$PROBE_RC" -eq 0 ]]; then
  if HF_TOKEN="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}" bash scripts/benchmark_diarization_docker.sh "$INPUT_ABS" --backend pyannote --warmup --runs "$RUNS" --format md >"$GPU_MD" 2>&1; then
    GPU_STATUS="ok"
  else
    GPU_STATUS="failed"
    GPU_LOG="$GPU_MD"
  fi
else
  if [[ "$RUN_GPU" != "true" ]]; then
    GPU_STATUS="skipped"
  elif [[ "$CUDA_AVAILABLE" != "true" ]]; then
    GPU_STATUS="gpu_unavailable"
  else
    GPU_STATUS="blocked_external"
  fi
  cat >"$GPU_MD" <<EOF_GPU
# Pyannote GPU benchmark status (${STAMP})

- status: \`${GPU_STATUS}\`
- run_gpu_flag: \`${RUN_GPU}\`
- cuda_available: \`${CUDA_AVAILABLE}\`
- probe_exit: \`${PROBE_RC}\`
- gpu_capability_json: \`${GPU_CAP_JSON}\`
EOF_GPU
fi

python3 - <<'PY' "$STATUS_JSON" "$STAMP" "$INPUT_ABS" "$ACCESS_JSON" "$CPU_MD" "$GPU_MD" "$GPU_CAP_JSON" "$CPU_STATUS" "$GPU_STATUS" "$CPU_LOG" "$GPU_LOG" "$DETAILS"
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    out_json,
    stamp,
    input_abs,
    access_json,
    cpu_md,
    gpu_md,
    gpu_cap_json,
    cpu_status,
    gpu_status,
    cpu_log,
    gpu_log,
    details,
) = sys.argv[1:]

payload = {
    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    "stamp": stamp,
    "input": input_abs,
    "probe_json": access_json,
    "cpu": {
        "status": cpu_status,
        "report_md": cpu_md,
        "log": cpu_log or None,
    },
    "gpu": {
        "status": gpu_status,
        "report_md": gpu_md,
        "capability_json": gpu_cap_json,
        "log": gpu_log or None,
    },
    "details": details or None,
}

Path(out_json).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY

exit 0
