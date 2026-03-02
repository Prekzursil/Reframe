# 2026-03-02 Mainline Sync + Validation Report

## Scope

- Repository: `Prekzursil/Reframe`
- Validation branch: `feat/reframe-sync-saas-v2-2026-03-02`
- Base/source-of-truth: `origin/main@02fd4b5`
- Related PR: [#93](https://github.com/Prekzursil/Reframe/pull/93)

## Sync Reality Check

- Local stale workspace (`/mnt/c/Users/Prekzursil/Downloads/Reframe`) remains historical input only:
  - branch: `feat/worker-real-pipeline-batch-01`
  - head: `dd1d4f2`
  - dirty status persists intentionally (quarantined)
- Sync evidence replayed from prior branch commit:
  - `docs/plans/2026-03-01-stale-todo-delta.md`

## Local Gate Results (worktree)

- Command: `PYTHON=.venv/bin/python make verify`
  - Result: pass (`112 passed, 6 skipped`; web tests `26 passed`; web build succeeded)
- Command: `PYTHON=.venv/bin/python make smoke-hosted`
  - Result: pass (`12 passed`)
- Command: `PYTHON=.venv/bin/python make smoke-local`
  - Result: pass (`6 passed, 5 skipped` + web tests pass)
- Command: `PYTHON=.venv/bin/python make smoke-security`
  - Result: pass (`7 passed`)
- Command: `PYTHON=.venv/bin/python make smoke-workflows`
  - Result: pass (`2 passed`)
- Command: `PYTHON=.venv/bin/python make smoke-perf-cost`
  - Result: pass (`3 passed`)
- Command: `HF_TOKEN=*** HUGGINGFACE_TOKEN=*** PYTHON=.venv/bin/python make release-readiness`
  - Result: pass (`status=READY`) in `docs/plans/2026-03-02-release-readiness-summary.json`

## CI Parity Runs (dispatched March 2, 2026 UTC)

- Branch release-readiness:
  - run: `22586189984`
  - url: https://github.com/Prekzursil/Reframe/actions/runs/22586189984
  - conclusion: `success`
- Main release-readiness:
  - run: `22586191139`
  - url: [actions run 22586191139](https://github.com/Prekzursil/Reframe/actions/runs/22586191139)
  - conclusion: `success`
- Main diarization benchmark:
  - run: `22586192267`
  - url: [actions run 22586192267](https://github.com/Prekzursil/Reframe/actions/runs/22586192267)
  - conclusion: `success`

Status notes:

- All three parity runs completed successfully during this batch: [branch readiness](https://github.com/Prekzursil/Reframe/actions/runs/22586189984), [main readiness](https://github.com/Prekzursil/Reframe/actions/runs/22586191139), and [main diarization](https://github.com/Prekzursil/Reframe/actions/runs/22586192267).

## Diarization Notes

- HF gated-model access probe is `ok` in local artifact:
  - `docs/plans/2026-03-02-pyannote-access.json`
- Local environment does not expose `docker compose`, so local benchmark execution reuses valid prior benchmark evidence for stamp continuity in this branch run.
- Current readiness summary records:
  - cpu: `ok`
  - gpu: `skipped`

## Artifacts Produced/Updated in This Batch

- `docs/plans/2026-03-02-release-readiness-summary.json`
- `docs/plans/2026-03-02-release-confidence-report.md`
- `docs/plans/2026-03-02-pyannote-access.json`
- `docs/plans/2026-03-02-pyannote-benchmark-cpu.md`
- `docs/plans/2026-03-02-pyannote-benchmark-gpu.md`
- `docs/plans/2026-03-02-pyannote-benchmark-status.json`
- `docs/plans/2026-03-02-pyannote-gpu-capability.json`

## Decision Snapshot

- Local branch readiness classification: `READY`
- Remaining work for this umbrella PR moves to SaaS V2 extension items in TODO section 25.
