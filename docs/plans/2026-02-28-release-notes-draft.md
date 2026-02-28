# Reframe v0.1.7 Release Notes (Draft)

Date: 2026-02-28
Branch: `feat/pyannote-ready-closure`
Baseline: `origin/main@246317a`

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
- Hardened branch protection audit workflow checks in:
  - `.github/workflows/branch-protection-audit.yml`

## Validation Evidence

- Linux updater E2E evidence:
  - `docs/plans/2026-02-28-updater-e2e-linux.json`
  - `docs/plans/2026-02-28-updater-e2e-linux.md`
- Pyannote access and benchmark evidence:
  - `docs/plans/2026-02-28-pyannote-access.json`
  - `docs/plans/2026-02-28-pyannote-benchmark-status.json`
  - `docs/plans/2026-02-28-pyannote-benchmark-cpu.md`
  - `docs/plans/2026-02-28-pyannote-benchmark-gpu.md`
- Readiness summary:
  - `docs/plans/2026-02-28-release-readiness-summary.json`
  - `docs/plans/2026-02-28-release-confidence-report.md`

## Mainline Workflow Snapshots (2026-02-28)

- Release Readiness (main): https://github.com/Prekzursil/Reframe/actions/runs/22523603682
  - Artifact (`release-readiness-evidence`): https://api.github.com/repos/Prekzursil/Reframe/actions/artifacts/5704024538/zip
  - Result status: `READY_WITH_EXTERNAL_BLOCKER`
- Diarization Benchmark (main): https://github.com/Prekzursil/Reframe/actions/runs/22523641493
  - Artifact (`diarization-benchmark-cpu`): https://api.github.com/repos/Prekzursil/Reframe/actions/artifacts/5704027602/zip
  - Probe status: `blocked_403` (HTTP 403)
- Diarization Benchmark (branch): https://github.com/Prekzursil/Reframe/actions/runs/22524197888
  - Probe detail: `speaker-diarization-3.1=ok`, `segmentation-3.0=blocked_403`

## Current Readiness Decision

- `READY_WITH_EXTERNAL_BLOCKER`

### Blocking

- None (all local release-readiness gates are currently passing).

### External blocker

- Hugging Face gated dependency access for `pyannote/segmentation-3.0` remains blocked (403), while `pyannote/speaker-diarization-3.1` now resolves successfully.
- Tracking issue: https://github.com/Prekzursil/Reframe/issues/80

## Operator Guidance

- Maintain updater matrix pass status (Windows/macOS/Linux) on future release tags.
- Keep issue #80 open until HF access is granted for both required pyannote repositories and a true pyannote benchmark can run.
- Move from `READY_WITH_EXTERNAL_BLOCKER` to `READY` after issue #80 is closed with successful pyannote CPU results.
