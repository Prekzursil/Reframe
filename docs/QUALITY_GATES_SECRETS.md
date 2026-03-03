# Quality Gates Secrets Setup

This repository now enforces fail-closed quality gates. Missing secrets or variables will fail PR/main checks.

## Required GitHub Secrets

```bash
gh secret set SONAR_TOKEN --body '<token>'
gh secret set CODACY_API_TOKEN --body '<token>'
gh secret set CODECOV_TOKEN --body '<token>'
gh secret set SNYK_TOKEN --body '<token>'
gh secret set SENTRY_AUTH_TOKEN --body '<token>'
gh secret set APPLITOOLS_API_KEY --body '<token>'
gh secret set PERCY_TOKEN --body '<token>'
gh secret set BROWSERSTACK_USERNAME --body '<username>'
gh secret set BROWSERSTACK_ACCESS_KEY --body '<access-key>'
gh secret set DEEPSCAN_API_TOKEN --body '<token>'
```

## Required GitHub Variables

```bash
gh variable set SENTRY_ORG --body 'your-org-slug'
gh variable set SENTRY_PROJECT_BACKEND --body 'backend-project-slug'
gh variable set SENTRY_PROJECT_WEB --body 'web-project-slug'
gh variable set DEEPSCAN_OPEN_ISSUES_URL --body 'https://deepscan.example/api/open-issues'
```

## Validation

Run locally:

```bash
python3 scripts/quality/check_quality_secrets.py
```

CI runs this check as `Quality Secrets Preflight`.
