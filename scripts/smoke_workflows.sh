#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT"
TMPDIR=/tmp PYTHONPATH=.:apps/api:packages/media-core/src "$PYTHON_BIN" -m pytest --rootdir=. \
  apps/api/tests/test_enterprise_workflows_and_costs.py \
  services/worker/test_worker_workflow_pipeline.py
