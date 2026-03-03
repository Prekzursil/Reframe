# Org-Wide Codecov + Zero-Issue Gates Tracker (2026-03-03)

## Scope

- Wave branch: `feat/quality-zero-gates-2026-03-03`
- Policy: 100% coverage + zero-open findings + fail-closed preflight
- Repos in wave: 10

## PRs

- SWFOC-Mod-Menu: [PR #98](https://github.com/Prekzursil/SWFOC-Mod-Menu/pull/98)
- event-link: [PR #94](https://github.com/Prekzursil/event-link/pull/94)
- env-inspector: [PR #17](https://github.com/Prekzursil/env-inspector/pull/17)
- DevExtreme-Filter-Go-Language: [PR #9](https://github.com/Prekzursil/DevExtreme-Filter-Go-Language/pull/9)
- Star-Wars-Galactic-Battlegrounds-Save-Game-Editor: [PR #10](https://github.com/Prekzursil/Star-Wars-Galactic-Battlegrounds-Save-Game-Editor/pull/10)
- pbinfo-get-unsolved: [PR #9](https://github.com/Prekzursil/pbinfo-get-unsolved/pull/9)
- Airline-Reservations-System: [PR #12](https://github.com/Prekzursil/Airline-Reservations-System/pull/12)
- Personal-Finance-Management: [PR #9](https://github.com/Prekzursil/Personal-Finance-Management/pull/9)
- TanksFlashMobile: [PR #29](https://github.com/Prekzursil/TanksFlashMobile/pull/29)
- WebCoder: [PR #16](https://github.com/Prekzursil/WebCoder/pull/16)

## Implemented in each repo

- Added `codecov.yml` with strict 100% target and momentstudio-style sections:
  - `codecov.require_ci_to_pass`
  - `comment.layout`
  - `component_management`
  - `bundle_analysis`
- Added quality scripts under `scripts/quality/`:
  - `assert_coverage_100.py`
  - `check_quality_secrets.py`
  - `check_required_checks.py`
  - `check_sonar_zero.py`
  - `check_codacy_zero.py`
  - `check_deepscan_zero.py` (then adapted to vendor context mode)
  - `check_sentry_zero.py`
- Added workflows:
  - `coverage-100.yml`
  - `codecov-analytics.yml`
  - `sonar-zero.yml`
  - `codacy-zero.yml`
  - `snyk-zero.yml`
  - `sentry-zero.yml`
  - `deepscan-zero.yml`
  - `quality-zero-gate.yml`

## Secret bootstrap applied

Configured across target repos:

- `APPLITOOLS_API_KEY`
- `CODACY_API_TOKEN`
- `SENTRY_AUTH_TOKEN`
- `SNYK_TOKEN`
- `SONAR_TOKEN`

Configured vars across target repos:

- `SENTRY_ORG=prekzursil`
- `SENTRY_PROJECT=<repo-name>`
- `DEEPSCAN_POLICY_MODE=github_check_context`

## Branch protection updates applied

Updated default-branch required status checks for all 10 repos to include:

- `Coverage 100 Gate`
- `Codecov Analytics`
- `Quality Zero Gate`
- `SonarCloud Code Analysis`
- `Codacy Static Code Analysis`
- `DeepScan`
- `Snyk Zero`
- `Sentry Zero`
- `Sonar Zero`
- `Codacy Zero`
- `DeepScan Zero`

## Current expected blockers

- Coverage 100 failures (test depth gaps)
- Sonar/Codacy/Snyk/Sentry non-zero findings in several repos
- Codecov upload/config checks still warming up after workflow fix wave
