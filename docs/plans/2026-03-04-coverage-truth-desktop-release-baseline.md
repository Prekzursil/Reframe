# 2026-03-04 Coverage Truth + Desktop Release Baseline

- captured_at_utc: 2026-03-04T06:02:10.4850475Z
- branch: feat/coverage-truth-desktop-product-2026-03-04
- head_sha: 4f7349caf2966f25902a72e8384cdd43a9b2a65e
- pr: https://github.com/Prekzursil/Reframe/pull/107

## Coverage baseline (strict script output)

- source report: docs/plans/2026-03-04-coverage-truth-baseline.md
- python: 63.92% (6627/10367)
- web: 65.85% (1475/2240)
- desktop-ts: 100.00% (197/197)
- combined: 64.82% (8299/12804)
- expected files: 83
- missing files: 5
- uncovered files: 58

## Exclusion baseline

- codecov.yml ignore list currently excludes only generated/build/vendor-style areas and test files.
- apps/web/vite.config.ts coverage excludes only test and e2e scaffolding.
- apps/desktop/vitest.config.ts thresholds are currently all set to 100.

## Desktop release baseline

- current desktop release: Reframe Desktop v0.1.8 (tag desktop-v0.1.8)
- prerelease: true
- release URL: https://github.com/Prekzursil/Reframe/releases/tag/desktop-v0.1.8
- key Windows artifacts present:
  - Reframe_0.1.8_x64-setup.exe
  - Reframe_0.1.8_x64_en-US.msi

## Known UX/runtime baseline gaps

- Desktop currently uses an operator-oriented command vocabulary in UI/runtime surface (compose_* naming and diagnostics-first framing).
- Product-first in-app onboarding and guided flow still needs hardening for non-operator users.