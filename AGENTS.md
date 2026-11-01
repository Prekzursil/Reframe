# AGENTS.md — rules for humans and automation

1. **Verify before claiming done.** A change is green only when the `quality`
   workflow says so on the PR — not when it looks right locally.
2. **Never weaken a gate.** Coverage thresholds, the deps severity floor
   (`any`), the SAST/secrets lanes and CodeQL suites are fixed. Fix the code
   instead; if a gate is genuinely impossible to satisfy, say so on the PR
   with the exact gap.
3. **Tests ship with the change.** New behaviour is uncovered until a test
   proves it; coverage regressions are red, not style nits.
4. **Never push to the default branch.** Everything lands through a pull
   request; admins bypass only via PR (audited), never by pushing past rules.
5. **Secrets never enter the tree.** If a scan fires, rotate first (human
   only), then clean; allowlists are reviewed, dated and reasoned.
6. **Follow the existing patterns.** The repo has established seams for path
   confinement (`app/render-cli/src/jobPath.ts`, `sidecar/.../pathsafe.py`)
   and log sanitising (`clean_for_log`) — reuse them instead of inventing new
   barriers.
