<!-- Gate checklist — maps 1:1 to .github/workflows/quality.yml (CONTRACTS.md). -->

## What

<!-- One paragraph: the behaviour change and why. -->

## Gate checklist (CI runs all of these)

- [ ] gate:1 — lint + format clean (`pre-commit run --all-files`: ruff, oxlint, biome)
- [ ] gate:2 — types clean (`tsc --noEmit` app + render-cli; sidecar passes under ruff/basedpyright per pre-commit)
- [ ] gate:3 — tests + STRICT 100% line/branch coverage (sidecar pytest, app vitest; exclusions only per vitest.config/CONTRIBUTING)
- [ ] gate:4 — SAST (opengrep) clean
- [ ] gate:5 — secrets (gitleaks) clean
- [ ] gate:6 — deps: osv-scanner reports 0 actionable CVEs (`deps-severity-floor: any`)

## Rules

- Never weaken a gate to make a branch green — fix the code, or state the exact gap.
- Tests ship with the change; coverage regression = red.
- No pushes to `main`; everything lands through this PR.
