#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT_DIR"

export REFRAME_HOSTED_MODE="true"
export REFRAME_ENABLE_BILLING="true"
export REFRAME_ENABLE_OAUTH="true"

TMPDIR=/tmp PYTHONPATH=.:apps/api:packages/media-core/src "$PYTHON_BIN" -m pytest --rootdir=. \
  apps/api/tests/test_security_auth.py \
  apps/api/tests/test_org_collaboration.py \
  apps/api/tests/test_hosted_uploads.py \
  apps/api/tests/test_billing_seats.py \
  apps/api/tests/test_usage_summary.py
