# 2026-03-04 Coverage Truth + Desktop Baseline

- Timestamp (UTC): `2026-03-04T08:19:25.461993+00:00`
- Branch: `feat/coverage-truth-desktop-product-2026-03-04`
- Head SHA: `a2af872d2f9a9bd9a143f753693b7f3730fb48b4`
- PR: https://github.com/Prekzursil/Reframe/pull/107

## PR Check Snapshot
- Failures: `3`
- In progress: `3`
- FAIL `Codecov Analytics` (Codecov Analytics) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757675/job/65680193917
- FAIL `Coverage 100 Gate` (Coverage 100) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757757/job/65680193766
- FAIL `Sonar Zero` (Sonar Zero) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757682/job/65680193783
- In-progress contexts:
  - `BrowserStack E2E` (BrowserStack E2E) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757656/job/65680193822
  - `Percy Visual` (Percy Visual) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757659/job/65680194046
  - `Quality Zero Gate` (Quality Zero Gate) -> https://github.com/Prekzursil/Reframe/actions/runs/22660757718/job/65680207233

## Coverage Config Baseline
- Current `codecov.yml` ignore list:
  - `.venv/**`
  - `**/__pycache__/**`
  - `**/*.pyc`
  - `.github/**`
  - `docs/**`
  - `infra/**`
  - `apps/web/e2e/**`
  - `apps/web/playwright.config.ts`
  - `apps/web/browserstack.yml`
  - `apps/web/src/test/**`
  - `apps/web/src/**/*.test.ts`
  - `apps/web/src/**/*.test.tsx`
  - `apps/desktop/src/**/*.test.ts`
  - `apps/desktop/vitest.config.ts`
- Web Vitest has strict 100 thresholds: `True`
- Desktop Vitest has strict 100 thresholds: `True`
- Web coverage include is full src glob: `True`

## Desktop Release Baseline
- Release tag: `desktop-v0.1.8`
- Release URL: https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8
- Pre-release: `True`
- Published at: `2026-03-03T00:41:30Z`
- Asset count: `17`
- Key Windows assets:
  - `Reframe_0.1.8_x64-setup.exe` (2946411 bytes, downloads=1)
  - `Reframe_0.1.8_x64_en-US.msi` (4382720 bytes, downloads=0)
