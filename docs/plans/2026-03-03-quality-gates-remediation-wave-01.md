# Quality Gates Remediation Wave 01 (2026-03-03)

## Scope
- Branch: `feat/quality-zero-gates-2026-03-03`
- PR: `#104`
- Head SHA: `103a9a055ccd7df7d09487c220a2f7ffefb61bd1`

## Changes in this wave
1. `de2330e` `fix: stabilize quality gate workflow execution`
   - Regenerated `apps/web/package-lock.json` with npm 10 compatible metadata.
   - Added `.env` bootstrap in:
     - `.github/workflows/percy-visual.yml`
     - `.github/workflows/applitools-visual.yml`
     - `.github/workflows/browserstack-e2e.yml`
   - Made compose failure-log and teardown steps non-blocking (`|| true`) in visual/browser workflows.
   - Updated `quality-zero-gate.yml` so aggregate gate always runs and fails explicitly when secrets preflight is not successful.
   - Updated `scripts/quality/check_codacy_zero.py` to use Codacy v3 `POST .../issues/search` with provider fallback.
2. `103a9a0` `fix: use BrowserStack local hostname for e2e base url`
   - Set BrowserStack workflow `E2E_BASE_URL` to `http://bs-local.com:5173`.

## Local verification
- `TMPDIR=/tmp .venv/bin/python -m pytest apps/api/tests/test_scripts_quality_gates.py apps/api/tests/test_scripts_strict23_preflight.py -q` -> `14 passed`.
- `cd apps/web && npm test` -> pass (`11` files, `29` tests).
- `cd apps/desktop && npm test` -> pass (`1` file, `2` tests).
- `make verify PYTHON=.venv/bin/python` -> pass (`136 passed, 6 skipped`) and web build pass.
- `cd apps/web && npm run test:coverage` -> deterministic strict fail (coverage below 100%).
- `cd apps/desktop && npm run test:coverage` -> deterministic strict fail (coverage below 100%).

## CI snapshot (post-wave)
- Codacy Zero now reaches real API data and fails on policy value, not integration error:
  - run `22605225554`: `open_issues=760`.
- DeepScan Zero fails fail-closed due missing contract inputs:
  - run `22605225567`: missing `DEEPSCAN_API_TOKEN`, `DEEPSCAN_OPEN_ISSUES_URL`.
- Sentry Zero fails fail-closed due missing contract inputs:
  - latest run indicates missing `SENTRY_AUTH_TOKEN` and project vars.
- Snyk Zero fails with existing open findings:
  - run `22605225594`: multiple issues (includes existing codebase findings and newly scanned script paths).
- Coverage 100 / Sonar Zero / Codecov Analytics fail because strict 100% coverage policy is active and current coverage is below target.
- BrowserStack E2E routing mismatch was fixed in `103a9a0`; rerun pending from updated commit.

## Current blocker classes
1. **Policy debt (real findings)**
   - Codacy Static Code Analysis, Codacy Zero, SonarCloud Code Analysis, Sonar Zero, Snyk Zero.
2. **Secret contract debt (fail-closed by design)**
   - Sentry and DeepScan missing secrets/vars.
3. **Coverage debt under immediate 100% policy**
   - Web and desktop coverage far below required thresholds.
4. **Dependency audit debt**
   - Node dependency audit high finding (currently transitive via visual test toolchain dependency graph).

## Next wave entry points
1. Secrets/vars provisioning for DeepScan and Sentry to unblock those gates.
2. Decide whether to remediate or replace current visual dependency chain causing high npm audit finding.
3. Prioritize coverage expansion for `apps/web/src/App.tsx`, `apps/web/src/api/client.ts`, and desktop `main.ts` to move toward 100% gate.
4. Execute targeted remediation against Codacy/Sonar/Snyk top offenders before broad refactors.
