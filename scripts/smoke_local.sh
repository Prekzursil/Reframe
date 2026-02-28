#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR"

export REFRAME_HOSTED_MODE="false"
export REFRAME_ENABLE_BILLING="false"
export REFRAME_ENABLE_OAUTH="false"
export REFRAME_OFFLINE_MODE="true"

TMPDIR=/tmp PYTHONPATH=.:apps/api:packages/media-core/src "$PYTHON_BIN" -m pytest --rootdir=. \
  apps/api/tests/test_integration_jobs.py \
  apps/api/tests/test_system_status.py \
  apps/api/tests/test_projects_api.py \
  apps/api/tests/test_usage_summary.py

(
  cd apps/web
  npm test
)
