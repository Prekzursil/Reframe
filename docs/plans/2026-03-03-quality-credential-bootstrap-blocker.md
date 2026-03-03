# Quality Credential Bootstrap Blocker (Playwright)

- captured_utc: `2026-03-03T03:28:54Z`
- status: `blocked`

## Observations

- Playwright skill wrapper is currently incompatible with the installed package shape:
  - command executed: `~/.codex/skills/playwright/scripts/playwright_cli.sh --session reframe-quality open ...`
  - result: `playwright-cli: not found` (current `@playwright/mcp` exposes `playwright-mcp`, not `playwright-cli`).
- Direct Playwright automation check (`node + playwright`) confirms there is no authenticated browser session available to mint tokens:
  - `sentry`: authenticated=`False`
    - URL: `https://sentry.io/settings/account/api/auth-tokens/`
    - Final URL: `https://sentry.io/auth/login/`
  - `deepscan`: authenticated=`False`
    - URL: `https://deepscan.io/`
    - Final URL: `https://deepscan.io/`
    - page signal includes `Log in with GitHub`.

## GitHub configuration state (current)

- Present secrets: `SONAR_TOKEN`, `CODACY_API_TOKEN`, `CODECOV_TOKEN`, `SNYK_TOKEN`, `APPLITOOLS_API_KEY`, `PERCY_TOKEN`, `BROWSERSTACK_USERNAME`, `BROWSERSTACK_ACCESS_KEY`
- Missing secrets: `SENTRY_AUTH_TOKEN`, `DEEPSCAN_API_TOKEN`
- Present variables: `SENTRY_ORG=4509310842634240`
- Missing variables: `SENTRY_PROJECT_BACKEND`, `SENTRY_PROJECT_WEB`, `DEEPSCAN_OPEN_ISSUES_URL`

## Required unblock values

- secret: `SENTRY_AUTH_TOKEN`
- secret: `DEEPSCAN_API_TOKEN`
- variable: `SENTRY_PROJECT_BACKEND`
- variable: `SENTRY_PROJECT_WEB`
- variable: `DEEPSCAN_OPEN_ISSUES_URL`

## Next action

- Credential bootstrap is blocked without authenticated sessions or explicit values. Per plan fallback policy, execution must stop here until missing values are provided.
