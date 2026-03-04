# Coverage Truth + Desktop Product Baseline (2026-03-04)

## Branch
- branch: `feat/coverage-truth-desktop-product-2026-03-04`
- head: `d8e1556`
- base main: `8db2a7c`

## Coverage truth baseline
Source: `coverage-100/coverage.local.wave3.json`

- python: `78.18%` (`8831/11296`)
- web: `83.85%` (`1884/2247`)
- desktop-ts: `100.00%` (`209/209`)
- combined: `79.44%` (`10924/13752`)

Inventory findings:
- expected files: `80`
- missing files: `2` (`apps/desktop/src-tauri/src/lib.rs`, `apps/desktop/src-tauri/src/main.rs`)
- uncovered files: `57`

Largest hotspots by line volume:
- `apps/web/src/App.tsx` -> `1418/1762`
- `services/worker/worker.py` -> `913/1326`
- `apps/api/app/api.py` -> `1068/1482`
- `apps/api/app/auth_api.py` -> `436/663`
- `apps/api/app/identity_api.py` -> `363/495`

## Config posture (truth-restored)
- `codecov.yml` no longer ignores first-party app/runtime trees.
- `apps/web/vite.config.ts` tracks all `src/**/*.ts(x)` except test/bootstrap files.
- `apps/desktop/vitest.config.ts` thresholds are strict `100/100/100/100`.
- `scripts/quality/assert_coverage_100.py` enforces tracked-file inventory presence and uncovered-file diagnostics.

## Desktop runtime posture baseline
- Desktop app currently uses bundled local runtime bootstrap (`REFRAME_LOCAL_QUEUE_MODE=true`), no Docker dependency for runtime path.
- UX is functional but still diagnostics-heavy; next wave will streamline first-run product flow and guided creation path.
