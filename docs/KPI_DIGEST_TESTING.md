# Ops Weekly Digest Testing Guide

## Overview

This guide validates the consolidated weekly digest automation implemented in:

- `.github/workflows/ops-weekly-digest.yml`
- `scripts/generate_ops_digest.py`
- `scripts/upsert_ops_digest_issue.py`

The workflow is artifact-first and issue-upsert based:

- It does **not** push commits to `main`.
- It uploads JSON/Markdown artifacts for every run.
- It upserts a single rolling issue (`Weekly Ops Digest (rolling)`) instead of creating repetitive weekly issues.

## Prerequisites

- GitHub Actions enabled on the repository.
- `GITHUB_TOKEN` available in Actions runtime.
- Repository contains PR/issue/activity history in the selected time window.

## Core Validation Scenarios

### 1. Manual Dispatch Success

1. Open Actions -> `Ops Weekly Digest`.
2. Run workflow on `main`.
3. Wait for completion.

Expected:

- Job status is `success`.
- Artifact `ops-weekly-digest` exists and contains:
  - `digest.json`
  - `digest.md`
  - `upsert.json`

### 2. Artifact Integrity

Download the artifact and verify:

- `digest.json` includes `window_start_utc`, `window_end_utc`, and `metrics`.
- `digest.json` includes `metrics_previous_window` and `trends`.
- `digest.md` renders the same metric values.
- `digest.md` includes a baseline section and trend deltas (`current - previous`).
- `upsert.json` indicates `created` or `updated` with issue URL.

### 2b. Trend/Health Classification

Expected:

- `health.main_ci_failure_rate_trend` is one of `improving|stable|worsening`.
- Positive `main_ci_failure_rate_pct_delta` maps to degraded/worsening trend.
- Negative `main_ci_failure_rate_pct_delta` maps to improving trend.
- Rolling issue snapshot JSON includes `metrics`, `trends`, and `health`.

### 3. Rolling Issue Upsert Behavior

Run the workflow twice.

Expected:

- First run creates `Weekly Ops Digest (rolling)` if absent.
- Second run updates the same issue body.
- No duplicate weekly digest issues are created.

### 4. No Repository Mutation

Expected:

- Workflow does not commit/push generated files.
- `main` history remains unchanged by digest execution.

### 5. Failure Handling

- If API token scope is missing, run should fail with clear script error.
- If GitHub API returns transient error, workflow should fail without partial issue corruption.

## Local Script Checks

Run locally using an authenticated token:

```bash
export GITHUB_TOKEN="$(gh auth token)"
python3 scripts/generate_ops_digest.py \
  --repo Prekzursil/Reframe \
  --out-json /tmp/ops-digest.json \
  --out-md /tmp/ops-digest.md

python3 scripts/upsert_ops_digest_issue.py \
  --repo Prekzursil/Reframe \
  --digest-json /tmp/ops-digest.json \
  --digest-md /tmp/ops-digest.md \
  --out-json /tmp/ops-upsert.json
```

## Troubleshooting

### `Resource not accessible by integration`

- Confirm workflow `permissions` includes `issues: write`, `pull-requests: read`, `actions: read`.
- Confirm repository-level Actions permissions are not restricted below workflow needs.

### Duplicate digest issues

- Ensure title is exactly `Weekly Ops Digest (rolling)`.
- Ensure `upsert_ops_digest_issue.py` is the only issue-writing digest automation on schedule.

### Unexpected zero metrics

- Confirm window selection (`--window-days`) matches expected period.
- Verify repository activity actually occurred in that window.

### Trend looks wrong

- Verify both windows are populated:
  - current window (`window_start_utc` -> `window_end_utc`)
  - previous window (`previous_window_start_utc` -> `previous_window_end_utc`)
- Confirm workflow-run filter is still constrained to `head_branch=main`.
- Re-run digest with the same token and compare artifact `digest.json` values directly.

## Operational Notes

- Keep metric threshold interpretation in `docs/KPI_METRICS.md`.
- Use workflow artifacts as immutable historical evidence for each run.
