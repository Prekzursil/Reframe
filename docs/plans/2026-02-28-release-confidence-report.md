# Reframe Release Confidence Report (2026-02-28)

- status: `READY_WITH_EXTERNAL_BLOCKER`
- generated_utc: `2026-02-28T04:54:44.079138+00:00`

## Local gates

- make verify: `PASS` (exit `0`)
- smoke-hosted: `PASS` (exit `0`)
- smoke-local: `PASS` (exit `0`)
- diarization-orchestrator: `PASS` (exit `0`)

## Desktop updater matrix

- windows: `PASS`
- macos: `PASS`
- linux: `PASS`

## Pyannote benchmark

- cpu_status: `blocked_external`
- gpu_status: `skipped`

## GitHub policy/check snapshot

- ci: `success`
- codeql: `success`
- required_reviews: `0`
- linear_history: `False`

## External blockers

- Pyannote gated-model access is blocked externally (Hugging Face authorization).
- Tracking issue: https://github.com/Prekzursil/Reframe/issues/80 (owner: @Prekzursil, recheck target: 2026-03-07)

## Evidence files

- `docs/plans/2026-02-28-release-readiness-summary.json`
- `docs/plans/2026-02-28-updater-e2e-*.json`
- `docs/plans/2026-02-28-pyannote-benchmark-status.json`
