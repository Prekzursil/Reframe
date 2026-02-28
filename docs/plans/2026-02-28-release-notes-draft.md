# Reframe v0.1.7 Release Notes (Draft)

Date: 2026-02-28
Branch: `feat/best-of-best-completion`
Baseline: `origin/main@8593ead`

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

## Current Readiness Decision

- `NOT_READY`

### Blocking

- Desktop updater OS matrix evidence incomplete (Windows/macOS pending).

### External blocker

- Hugging Face gated access for `pyannote/speaker-diarization-3.1` is blocked (403).
- Tracking issue: https://github.com/Prekzursil/Reframe/issues/80

## Operator Guidance

- To move to `READY`, run desktop updater E2E matrix on Windows/macOS and publish artifacts.
- To move to `READY_WITH_EXTERNAL_BLOCKER`, keep updater matrix green and retain issue #80 open until HF access is granted.
- To move to `READY`, close issue #80 after successful pyannote CPU benchmark execution.
