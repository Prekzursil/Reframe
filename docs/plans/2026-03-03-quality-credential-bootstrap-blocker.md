# Quality Credential Bootstrap Blocker (Playwright)

- captured_utc: `2026-03-03T03:03:48.745008+00:00`
- status: `blocked`

## Observations

- `sentry`: authenticated=`False` (Playwright session is not authenticated; token creation cannot proceed.)
  - URL: `https://sentry.io/settings/account/api/auth-tokens/`
  - Final URL: `https://sentry.io/auth/login/`
- `deepscan`: authenticated=`False` (No authenticated API-token management session discovered by automation.)
  - URL: `https://deepscan.io/dashboard/`
  - Final URL: `https://deepscan.io/dashboard/`

## Missing required values

- secret: `SENTRY_AUTH_TOKEN`
- secret: `DEEPSCAN_API_TOKEN`
- variable: `SENTRY_PROJECT_BACKEND`
- variable: `SENTRY_PROJECT_WEB`
- variable: `DEEPSCAN_OPEN_ISSUES_URL`

## Next action

- Credential bootstrap is blocked without authenticated sessions or explicit token values.
