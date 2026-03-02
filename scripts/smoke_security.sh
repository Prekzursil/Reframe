#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"

cd "$ROOT"
TMPDIR=/tmp PYTHONPATH=.:apps/api:packages/media-core/src "$PYTHON_BIN" -m pytest --rootdir=. \
  apps/api/tests/test_security_auth.py \
  apps/api/tests/test_org_collaboration.py \
  apps/api/tests/test_sso_okta.py \
  apps/api/tests/test_scim_users_groups.py \
  apps/api/tests/test_project_collaboration.py \
  apps/api/tests/test_enterprise_workflows_and_costs.py
