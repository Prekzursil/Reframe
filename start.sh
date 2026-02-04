#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="${ROOT_DIR}/infra"
ENV_FILE="${ROOT_DIR}/.env"

COMPOSE=(docker compose)
if command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

usage() {
  cat <<'EOF'
Usage:
  ./start.sh up     # build + run docker compose (default)
  ./start.sh down   # stop containers
  ./start.sh logs   # follow logs

This script will create a local .env (if missing) with docker-friendly defaults:
- sqlite DB stored in the shared media volume
- redis://redis:6379/0 for broker/result backend
- offline mode enabled by default
EOF
}

ensure_prereqs() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not installed." >&2
    exit 1
  fi
  if ! "${COMPOSE[@]}" version >/dev/null 2>&1; then
    echo "ERROR: docker compose is not available." >&2
    exit 1
  fi
  if [[ ! -d "${COMPOSE_DIR}" ]]; then
    echo "ERROR: infra/ directory not found (expected ${COMPOSE_DIR})." >&2
    exit 1
  fi
}

ensure_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    return 0
  fi

  cat >"${ENV_FILE}" <<'EOF'
# API settings (docker compose defaults)
DATABASE_URL=sqlite:////data/media/reframe.db
REFRAME_MEDIA_ROOT=/data/media
BROKER_URL=redis://redis:6379/0
RESULT_BACKEND=redis://redis:6379/0

# Disable all network-backed providers by default.
REFRAME_OFFLINE_MODE=true

# Optional (required for some gated models like pyannote diarization)
HF_TOKEN=

# Upload safety (0 disables)
REFRAME_MAX_UPLOAD_BYTES=1073741824

# Local retention for generated files
REFRAME_CLEANUP_TTL_HOURS=24
REFRAME_CLEANUP_INTERVAL_SECONDS=3600

# Optional providers (disabled by offline mode)
OPENAI_API_KEY=
GROQ_API_KEY=
TRANSLATOR_PROVIDER=
TRANSLATOR_API_KEY=

# Optional remote storage (S3/R2)
REFRAME_STORAGE_BACKEND=local
REFRAME_S3_BUCKET=
REFRAME_S3_PREFIX=
REFRAME_S3_REGION=
REFRAME_S3_ENDPOINT_URL=
REFRAME_S3_PUBLIC_BASE_URL=
REFRAME_S3_PRESIGN_EXPIRES_SECONDS=604800
REFRAME_S3_ACCESS_KEY_ID=
REFRAME_S3_SECRET_ACCESS_KEY=
REFRAME_S3_SESSION_TOKEN=

# Web app settings (runs in your browser)
VITE_API_BASE_URL=http://localhost:8000/api/v1
EOF

  echo "Created ${ENV_FILE} with docker-friendly defaults."
}

cmd="${1:-up}"
case "${cmd}" in
  up|start)
    ensure_prereqs
    ensure_env_file
    echo "Starting Reframe..."
    echo "  Web: http://localhost:5173"
    echo "  API: http://localhost:8000 (OpenAPI: /docs)"
    cd "${COMPOSE_DIR}"
    "${COMPOSE[@]}" up --build
    ;;
  down|stop)
    ensure_prereqs
    cd "${COMPOSE_DIR}"
    "${COMPOSE[@]}" down
    ;;
  logs)
    ensure_prereqs
    cd "${COMPOSE_DIR}"
    "${COMPOSE[@]}" logs -f
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    usage
    exit 2
    ;;
esac
