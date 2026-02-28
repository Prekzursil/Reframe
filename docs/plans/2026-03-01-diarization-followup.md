# Pyannote Follow-up (2026-03-01)

## Outcome

- Hugging Face gated access remains `ok` for:
  - `pyannote/speaker-diarization-3.1`
  - `pyannote/segmentation-3.0`
  - `pyannote/speaker-diarization-community-1`
- CPU diarization benchmark status: `ok`
- GPU benchmark status: `skipped` (no CUDA device available in this environment)

Evidence:
- `docs/plans/2026-02-28-pyannote-access.json`
- `docs/plans/2026-02-28-pyannote-benchmark-status.json`
- `docs/plans/2026-02-28-pyannote-benchmark-cpu.md`
- `docs/plans/2026-02-28-pyannote-benchmark-gpu.md`

## Root Cause Found During Stabilization

The benchmark helper script could run against a stale Docker worker image because it invoked:

- `docker compose ... run --rm worker ...`

without a forced rebuild.

This produced a mismatch where the container used an older `media_core.diarize` implementation (`itertracks`-only path) even though the current branch already had compatibility logic for newer pyannote output wrappers.

## Fix Applied

1. Added regression test:
   - `apps/api/tests/test_scripts_diarization_benchmark_docker.py`
   - Verifies script includes `run --rm --build`.
2. Updated helper:
   - `scripts/benchmark_diarization_docker.sh`
   - Uses `docker compose run --rm --build ...`.

## Current CPU Metrics (local rerun)

From `docs/plans/2026-02-28-pyannote-benchmark-cpu.md`:
- `duration_s_avg=1.391`
- `peak_rss_mb=1049.7`
- `segments_last_run=0`

These are environment-specific sizing numbers and should be treated as directional.
