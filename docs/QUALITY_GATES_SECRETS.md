# Quality Gates Secrets Setup

This repository now enforces fail-closed quality gates. Missing secrets or variables will fail PR/main checks. Semgrep is workflow-based and does not require a dedicated repository secret.

## Required GitHub Secrets

```bash
gh secret set SONAR_TOKEN --body '<token>'
gh secret set CODACY_API_TOKEN --body '<token>'
gh secret set CODECOV_TOKEN --body '<token>'
gh secret set SENTRY_AUTH_TOKEN --body '<token>'
gh secret set APPLITOOLS_API_KEY --body '<token>'
gh secret set PERCY_TOKEN --body '<token>'
gh secret set BROWSERSTACK_USERNAME --body '<username>'
gh secret set BROWSERSTACK_ACCESS_KEY --body '<access-key>'
```

## Required GitHub Variables

```bash
gh variable set SENTRY_ORG --body 'your-org-slug'
gh variable set SENTRY_PROJECT_BACKEND --body 'backend-project-slug'
gh variable set SENTRY_PROJECT_WEB --body 'web-project-slug'
```

## DeepScan note

DeepScan does not provide a repository-level open-issues API contract suitable for fail-closed totals in this repo.  
`DeepScan Zero` therefore enforces the vendor `DeepScan` status context directly via GitHub checks.

## Validation

Run locally:

```bash
python3 scripts/quality/check_quality_secrets.py
```

CI runs this check as `Quality Secrets Preflight`.
