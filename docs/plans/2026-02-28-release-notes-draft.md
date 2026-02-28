# Reframe v0.1.7 Release Notes (Draft)

Date: 2026-02-28
Branch: `feat/pyannote-ready-final`
Baseline: `origin/main@db77fd2`

## Highlights

- Added automated desktop updater end-to-end verification tooling:
  - `scripts/desktop_updater_e2e.py`
  - `scripts/desktop_updater_e2e_windows.ps1`
  - `scripts/desktop_updater_e2e_macos.sh`
  - `scripts/desktop_updater_e2e_linux.sh`
  - `.github/workflows/desktop-updater-e2e.yml`
- Added automated pyannote access probe + benchmark orchestration:
  - `scripts/verify_hf_model_access.py`
  - `scripts/run_diarization_benchmarks.sh`
  - `.github/workflows/diarization-benchmark.yml`
- Added unified release-readiness gate and reporting:
  - `make smoke-hosted`
  - `make smoke-local`
  - `make release-readiness`
  - `scripts/release_readiness_report.py`
  - `.github/workflows/release-readiness.yml`
- Added dependency audit workflow:
  - `.github/workflows/dependency-audit.yml`
- Hardened branch-protection audit checks in:
  - `.github/workflows/branch-protection-audit.yml`

## Validation Evidence

- Updater E2E matrix evidence:
  - `docs/plans/2026-02-28-updater-e2e-windows.json`
  - `docs/plans/2026-02-28-updater-e2e-macos.json`
  - `docs/plans/2026-02-28-updater-e2e-linux.json`
- Pyannote access and benchmark evidence:
  - `docs/plans/2026-02-28-pyannote-access.json`
  - `docs/plans/2026-02-28-pyannote-benchmark-status.json`
  - `docs/plans/2026-02-28-pyannote-benchmark-cpu.md`
- Readiness summary:
  - `docs/plans/2026-02-28-release-readiness-summary.json`
  - `docs/plans/2026-02-28-release-confidence-report.md`

## Key Workflow Runs

- Diarization Benchmark (branch): https://github.com/Prekzursil/Reframe/actions/runs/22526417778
  - Probe status: all required pyannote repositories `ok`
  - CPU benchmark status: `ok`
  - GPU status: `skipped` (no CUDA runner)
- Release Readiness (branch): https://github.com/Prekzursil/Reframe/actions/runs/22526874023
  - Conclusion: `success`
  - Status classification: `READY`
- Release Readiness (main, historical): https://github.com/Prekzursil/Reframe/actions/runs/22524606622
  - Historical status at that point: `READY_WITH_EXTERNAL_BLOCKER`
- Diarization Benchmark (main stabilization dispatch): https://github.com/Prekzursil/Reframe/actions/runs/22531176153
  - Conclusion: `success`
  - Probe status: `ok`
  - CPU benchmark status: `ok`
  - GPU status: `skipped` (no CUDA runner)
- Release Readiness (main stabilization dispatch): https://github.com/Prekzursil/Reframe/actions/runs/22531175640
  - Conclusion: `success`
  - Stabilization report: `docs/plans/2026-03-01-mainline-stabilization-report.md`
- Release Readiness (stabilization branch dispatch): https://github.com/Prekzursil/Reframe/actions/runs/22531270273
  - Status at draft update time: `queued`
- Diarization Benchmark (stabilization branch dispatch): https://github.com/Prekzursil/Reframe/actions/runs/22531269296
  - Status at draft update time: `in_progress`

## Current Readiness Decision

- `READY`

### Blocking

- None.

### External blockers

- None.
- Previously tracked blocker issue is now closed: https://github.com/Prekzursil/Reframe/issues/80

## Operator Guidance

- Maintain updater matrix pass status (Windows/macOS/Linux) for future desktop tags.
- Re-run diarization benchmark workflow if pyannote model dependencies or Hugging Face access policy changes.
- Keep commit/push/PR checkpoints for each substantial implementation chunk.
