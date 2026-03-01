# Reframe Phase 2 Hardening Plan (2026-03-01)

## Scope

Follow-on umbrella phase after PR #87 merge (`main@55a9acb`) focused on quality hardening and operational tightening without introducing new public API surface.

## Objectives

1. Reduce Codacy `action_required` debt on large enterprise/workflow/perf additions.
2. Remove sensitive-token exposure risk from local process command lines in diarization/docker helpers.
3. Eliminate weak JWT key warnings in tests by using >=32-byte deterministic test secrets.
4. Improve release-readiness runtime profile by skipping heavy benchmark reruns when same-stamp evidence is fresh.
5. Add deterministic CI check-summary export for easier merge-go/no-go visibility.

## Guardrails

- Keep changes in one umbrella PR with chunked commit/push updates.
- No secret material in repo files or command arguments.
- Preserve existing required branch protection contexts (`CodeQL`, `CodeRabbit`, CI checks).

## Planned Chunks

1. Security-hardening chunk: token handling path + tests.
2. Test-warning cleanup chunk: JWT test secret normalization.
3. Readiness-runtime chunk: idempotent evidence re-use for same stamp.
4. Static-analysis chunk: highest-impact Codacy findings in touched files.
5. Evidence chunk: updated stabilization/readiness notes and check rollup.

## Success Criteria

- `make verify` green.
- Required GitHub checks green.
- No new critical/high security findings.
- Codacy delta trend improved versus PR #87 baseline.
