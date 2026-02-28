# Reframe Mainline Stabilization Report (2026-03-01)

## Scope

- Local stale workspace was preserved and quarantined.
- Clean integration worktree was created from latest `origin/main` (`5094dc2`).
- Full local gate pack was rerun (`verify`, `smoke-hosted`, `smoke-local`).
- Pyannote access + CPU benchmark were revalidated with real execution.
- Mainline workflow parity checks were dispatched.

## Workspace Reconciliation

- Stale workspace: `/mnt/c/Users/Prekzursil/Downloads/Reframe` on `feat/worker-real-pipeline-batch-01@dd1d4f2`.
- Quarantine artifacts:
  - `~/.reframe-quarantine/2026-03-01-dd1d4f2.patch`
  - `~/.reframe-quarantine/2026-03-01-dd1d4f2-staged.patch`
  - `~/.reframe-quarantine/2026-03-01-untracked.tar.gz`
  - `~/.reframe-quarantine/2026-03-01-stale-branch-note.txt`
- Archive branch pointer:
  - `archive/dd1d4f2-local-wip-2026-03-01`
- Integration worktree:
  - `/tmp/reframe-worktrees/mainline-stabilize-2026-03-01`
  - Branch: `chore/mainline-stabilize-2026-03-01`
  - Base commit: `5094dc2` (`Finalize pyannote closure and readiness READY (#85)`)

## Gate Results

- `PYTHON=.venv/bin/python make verify`: `PASS`
  - Python tests: `98 passed, 6 skipped`
  - Web tests: `26 passed`
  - Web build: success
- `PYTHON=.venv/bin/python make smoke-hosted`: `PASS`
- `PYTHON=.venv/bin/python make smoke-local`: `PASS`
- Readiness aggregate regenerated to `READY`:
  - `docs/plans/2026-02-28-release-readiness-summary.json`
  - `docs/plans/2026-02-28-release-confidence-report.md`

## Pyannote Follow-up

- Access probe: `ok` for all required repositories in `docs/plans/2026-02-28-pyannote-access.json`.
- Benchmark orchestrator: CPU `ok`, GPU `skipped` in `docs/plans/2026-02-28-pyannote-benchmark-status.json`.
- CPU metrics from `docs/plans/2026-02-28-pyannote-benchmark-cpu.md`:
  - `duration_s_avg=1.391`
  - `peak_rss_mb=1049.7`
- Regression fix included:
  - `scripts/benchmark_diarization_docker.sh` now uses `docker compose run --build`.
  - Regression test added: `apps/api/tests/test_scripts_diarization_benchmark_docker.py`.

## Mainline Workflow Parity

- Release Readiness (`main`) run `22531175640`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22531175640`
  - Status: `completed` / `success`
  - Artifact: `release-readiness-evidence` (`https://api.github.com/repos/Prekzursil/Reframe/actions/artifacts/5706165673/zip`)
- Diarization Benchmark (`main`) run `22531176153`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22531176153`
  - Status: `completed` / `success`
  - Artifact: `diarization-benchmark-cpu` (`https://api.github.com/repos/Prekzursil/Reframe/actions/artifacts/5706157111/zip`)
- Release Readiness (`chore/mainline-stabilize-2026-03-01`) run `22531270273`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22531270273`
  - Status at report update time: `queued`
- Diarization Benchmark (`chore/mainline-stabilize-2026-03-01`) run `22531269296`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22531269296`
  - Status at report update time: `in_progress`
- Branch Protection Audit (`main`) latest run `22523705202`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22523705202`
  - Status: `completed` / `success`
- CodeQL (`main`) latest run `22527282432`:
  - URL: `https://github.com/Prekzursil/Reframe/actions/runs/22527282432`
  - Status: `completed` / `success`

## Decision

- Readiness classification after stabilization evidence refresh: `READY`.
