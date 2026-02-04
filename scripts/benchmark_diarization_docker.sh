#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/infra/docker-compose.yml"

COMPOSE=(docker compose)
if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

usage() {
  cat <<'EOF'
Usage:
  bash scripts/benchmark_diarization_docker.sh /path/to/media.mp4 [options]

Runs diarization benchmarks inside the Docker Compose worker container (so you don't need to install torch/pyannote locally).

Options:
  --backend pyannote|speechbrain   (default: pyannote)
  --model <model-id>              (optional)
  --warmup                         (optional)
  --runs <N>                       (default: 1)
  --min-segment-duration <secs>    (default: 0.0)
  --format text|md                 (default: text)

Examples:
  HF_TOKEN=... bash scripts/benchmark_diarization_docker.sh ./samples/sample.mp4 --backend pyannote --warmup --runs 1 --format md
  bash scripts/benchmark_diarization_docker.sh ./samples/sample.mp4 --backend speechbrain --warmup --runs 1 --format md
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  usage
  exit 0
fi

input_path="${1:-}"
if [[ -z "${input_path}" ]]; then
  echo "ERROR: missing input file path" >&2
  usage
  exit 2
fi
shift

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed." >&2
  exit 1
fi
if ! "${COMPOSE[@]}" version >/dev/null 2>&1; then
  echo "ERROR: docker compose is not available." >&2
  exit 1
fi
if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "ERROR: compose file not found: ${COMPOSE_FILE}" >&2
  exit 1
fi

python3 - <<'PY' "${input_path}" >/dev/null
from pathlib import Path
import sys
path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"ERROR: input file not found: {path}")
PY

abs_input="$(python3 - <<'PY' "${input_path}"
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
)"
input_dir="$(dirname "${abs_input}")"
input_base="$(basename "${abs_input}")"
container_input="/bench/${input_base}"

backend="pyannote"
model=""
warmup="false"
runs="1"
min_segment_duration="0.0"
format="text"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)
      backend="${2:-}"
      shift 2
      ;;
    --model)
      model="${2:-}"
      shift 2
      ;;
    --warmup)
      warmup="true"
      shift
      ;;
    --runs)
      runs="${2:-1}"
      shift 2
      ;;
    --min-segment-duration)
      min_segment_duration="${2:-0.0}"
      shift 2
      ;;
    --format)
      format="${2:-text}"
      shift 2
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

extra=""
case "${backend}" in
  pyannote) extra="diarize-pyannote" ;;
  speechbrain) extra="diarize-speechbrain" ;;
  *)
    echo "ERROR: unsupported backend: ${backend} (expected: pyannote|speechbrain)" >&2
    exit 2
    ;;
esac

py_args=(
  "${container_input}"
  "--backend" "${backend}"
  "--runs" "${runs}"
  "--min-segment-duration" "${min_segment_duration}"
  "--format" "${format}"
)
if [[ "${warmup}" == "true" ]]; then
  py_args+=("--warmup")
fi
if [[ -n "${model}" ]]; then
  py_args+=("--model" "${model}")
fi

quoted_py_args="$(printf '%q ' "${py_args[@]}")"

cd "${ROOT_DIR}"
echo "Running in Docker worker:"
echo "  input:   ${abs_input}"
echo "  backend: ${backend}"
echo "  extra:   ${extra}"
echo ""

"${COMPOSE[@]}" -f infra/docker-compose.yml run --rm \
  -v "${input_dir}:/bench:ro" \
  worker \
  bash -lc "pip install --no-cache-dir '/worker/packages/media-core[${extra}]' && python /worker/scripts/benchmark_diarization.py ${quoted_py_args}"

