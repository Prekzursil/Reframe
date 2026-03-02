# Hosted SaaS V2 Hardening & Scale Design (2026-03-02)

## Context

- Baseline hosted SaaS roadmap work (section 23) is already implemented on `main`.
- Current gap is not first-pass capability; it is deterministic hardening and operational reliability:
  - strict-23 rollout confidence (`#91`, `#92`)
  - branch-protection audit trustworthiness (`#89`)
  - ops digest signal quality (`#88`)
  - budget guardrails for growth-stage multi-tenant hosted usage

This document defines net-new V2 scope on top of latest `main` without reopening completed section 23 items.

## Goals

1. Make policy and gate drift measurable and machine-verifiable.
2. Prevent false-positive/noisy audit outcomes.
3. Improve operator observability quality with trend-aware weekly digest.
4. Add org-level budget guardrails that are explicit, testable, and tenant-safe.

## Non-goals

1. Rebuild auth/org/billing foundations already complete in section 23.
2. Change public auth protocols beyond current JWT/OAuth scaffolding.
3. Introduce new external billing providers (Stripe remains default).

## Architecture

### 1) strict-23 preflight subsystem

- New script: `scripts/strict23_preflight.py`
- Inputs: branch protection required contexts (`gh api .../branches/main/protection`), recent check-run contexts for target SHA (`gh api .../check-runs`), and policy source (`docs/branch-protection-policy.json` for canonical set).
- Outputs: JSON artifact (`docs/plans/<stamp>-strict23-preflight.json`) and markdown summary (`docs/plans/<stamp>-strict23-preflight.md`).
- Status classes: `compliant` (all canonical contexts observed), `non_compliant` (missing/drifted contexts), and `inconclusive_permissions` (token scope cannot read required policy/check endpoints).

### 2) branch protection deterministic audit

- Existing audit script remains source for branch policy checks.
- Audit behavior change: no "missing protection" claims on permission-denied responses; policy mismatch emits exact diff against `docs/branch-protection-policy.json`.
- Workflow behavior: create/update finding issue only on true mismatch and append run URL plus policy delta in the issue body.

### 3) ops digest quality improvements

- Extend digest computation:
  - 7d window metrics
  - previous 7d baseline
  - trend deltas
- Health classification:
  - `ok`, `watch`, `action_required`
- Preserve one rolling issue model and artifact upload behavior.

### 4) budget guardrails

- New table/model: `OrgBudgetPolicy`
  - `org_id`
  - `monthly_soft_limit_cents`
  - `monthly_hard_limit_cents`
  - `enforce_hard_limit` (bool)
  - `updated_by_user_id`, timestamps
- API:
  - `GET /api/v1/usage/budget-policy`
  - `PUT /api/v1/usage/budget-policy`
- Enforcement:
  - on queued expensive jobs, estimate projected monthly usage/cost
  - if hard-limit exceeded and enforcement enabled, reject with `quota_exceeded`
  - always include actionable details in error payload (`current`, `projected`, `limit`)
- UI:
  - usage page budget card
  - policy update form for org admin/owner roles
  - projected overrun warning indicator

## Data Flow

1. Operator dispatches strict-23 preflight workflow or it runs on PR.
2. Script reads policy and live check contexts; emits JSON+MD artifact.
3. Branch-protection audit reads same policy source and emits deterministic status.
4. Weekly digest pulls metrics, computes trends, updates rolling issue.
5. Budget policy is configured via API/UI and enforced at job admission.

## Failure Modes and Handling

1. GitHub API permission gap: classify `inconclusive_permissions` and do not emit false non-compliance.
2. Missing canonical context: classify `non_compliant` and output missing context list with remediation hints.
3. Budget policy absent: default to existing plan-based behavior and return explicit default object on GET.
4. Cost projection unavailable: fail open for transient estimator errors with audit event, and fail closed only when hard-limit confidence is high with complete data.

## Testing Strategy

1. Unit tests for strict-23 preflight parsing/diff/status classification.
2. Unit tests for branch protection permission-denied vs drifted policy.
3. Unit tests for ops digest trend calculations and health labeling.
4. API tests for budget-policy CRUD and org-level RBAC.
5. API tests for budget hard-limit enforcement on job submission.
6. Web tests for usage budget card rendering and update flow.
7. Full regression: `make verify`, `make smoke-hosted`, `make smoke-local`, `make smoke-security`, `make smoke-workflows`, `make smoke-perf-cost`, and `make release-readiness`.

## Rollout Sequence

1. Merge sync/validation evidence updates and TODO section 25.
2. Land strict-23 preflight + branch-protection audit hardening.
3. Land ops digest trend and noise controls.
4. Land budget guardrails (model/API/UI/enforcement).
5. Re-run readiness and confirm no regressions in hosted/local modes.

## Merge Gate

- Required checks must remain green per branch protection.
- PR evidence must include:
  - strict-23 artifact links
  - readiness summary link
  - updated TODO status for section 25 items touched in the PR
