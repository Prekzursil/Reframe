<!-- Check an item only when you ran it and it passed. Reviewers re-run
     everything; CI enforces every item below with zero tolerance. -->

## What & why

<!-- One paragraph: what changes and why. Link the issue if there is one. -->

## Gate checklist — 1:1 with CI

Run `bash scripts/verify` from the repository root (see CONTRIBUTING.md).
Any finding of any severity fails CI.

- [ ] **gate 1 · lint + format** — ruff check + ruff format --check; oxlint --deny-warnings + biome format check: zero findings and zero format diffs
- [ ] **gate 2 · types** — basedpyright (standard mode); tsc --noEmit for every tsconfig: zero errors **and** zero warnings
- [ ] **gate 3 · tests + coverage** — the Python test suite under branch coverage; the `test:coverage` npm script + a coverage-number assert: every test passes at 100 % line **and** branch
- [ ] **gate 4 · SAST** — opengrep with the curated `.quality/opengrep` ruleset (seeded from QZP): zero findings
- [ ] **gate 5 · secrets** — gitleaks: zero findings
- [ ] **gate 6 · dependencies** — osv-scanner on every lockfile and manifest (`osv-scanner.toml`): zero known advisories, any severity

## Tests

- [ ] Every new or changed line is executed by a test added in this pull
      request (100 % line **and** branch coverage)
- [ ] No test was skipped, deleted or weakened to make CI pass
- [ ] No suppression (`noqa`, `type: ignore`, `pragma: no cover`,
      `eslint-disable`, `@ts-ignore`, allowlist entry) was added to go green

## Not applicable

<!-- Strike the items that do not apply and say why. -->

---

**Never weaken a gate to pass it.** If a gate is wrong, say so here and link
the quality-zero-platform change that fixes it (see CONTRIBUTING.md).
