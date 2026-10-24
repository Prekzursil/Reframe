# Contributing to Reframe

Thanks for wanting to help! This guide explains how changes get into
`Prekzursil/Reframe` and the quality bar every change has to clear.

Bugs and feature requests go through the
[issue tracker](https://github.com/Prekzursil/Reframe/issues/new/choose).
Anything that looks security-sensitive does **not** — follow
[SECURITY.md](SECURITY.md) instead.

## The one rule

**Every gate must pass for the right reason. Never weaken a gate to pass it.**

That means no lowered thresholds, no new ignore/allowlist entries, no
`# noqa`, `# type: ignore`, `# pragma: no cover`, `eslint-disable` or
`@ts-ignore` added just to go green, and no skipped or deleted tests. If a gate
is genuinely wrong, say so in the pull request and fix the gate itself in
[quality-zero-platform](https://github.com/Prekzursil/quality-zero-platform)
(see [Changing the gates](#changing-the-gates-operator-only)).

## Workflow

1. Branch from `main` (external contributors: fork first).
2. Make the change **together with the tests that exercise it** — in the same
   commit or pull request, never "tests later".
3. Run the gates locally (below) until every lane is green.
4. Open a pull request and fill in the checklist from the pull-request
   template; it maps 1:1 to what CI enforces.
5. Every required check must be green, the branch must be up to date with
   `main`, and every review conversation must be resolved before
   merging.

## The gates — zero tolerance

CI runs the QZP lean gate: `.github/workflows/quality.yml` calls
quality-zero-platform's `reusable-quality.yml`, pinned to an exact commit.
A finding of **any** severity fails the gate — there is no
"high and above only" floor anywhere.

| Gate | What runs | Passes when |
| ---- | --------- | ----------- |
| 1 · lint + format | ruff check + ruff format --check; oxlint --deny-warnings + biome format check | zero findings and zero format diffs |
| 2 · types | basedpyright (standard mode); tsc --noEmit for every tsconfig | zero errors **and** zero warnings |
| 3 · tests + coverage | the Python test suite under branch coverage; the `test:coverage` npm script + a coverage-number assert | every test passes at 100 % line **and** branch |
| 4 · SAST | opengrep with the curated `.quality/opengrep` ruleset (seeded from QZP) | zero findings |
| 5 · secrets | gitleaks | zero findings |
| 6 · dependencies | osv-scanner on every lockfile and manifest (`osv-scanner.toml`) | zero known advisories, any severity |

On top of the lean gate:

- **CodeQL** — GitHub default setup with the *extended* query suite and the remote + local threat model, on every pull request and weekly; a pull request that introduces a code-scanning alert of any severity cannot be merged.
- **Dependabot** — `.github/dependabot.yml` keeps every manifest tree on a weekly update rail.

## Running the gates locally

```bash
bash scripts/verify
```

`scripts/verify` runs QZP's preflight at the exact commit that
`.github/workflows/quality.yml` pins, so every CI lane runs locally with the
same pinned tool versions. Run it from this repository's root before every
push. A lane that cannot run locally (for example a missing toolchain) is
reported as `SKIP`, never as a silent pass — CI will still run it.

Language-specific test commands for quick iteration:

- Python: `python -m pytest --cov --cov-branch --cov-report=term-missing`
- JS/TS (`app`): `npm ci && npm run test:coverage`

## Coverage: 100 % line **and** branch

Coverage is measured on every lane that has source code, and the bar is 100 %
of lines **and** 100 % of branches. Line-only 100 % is not enough: once
branches are counted, line-clean code typically sits at 99.x % and still fails.
Every new or changed line needs a test that executes it in the same change.

## Dependencies

Dependabot proposes updates weekly: minor and patch updates are grouped per
ecosystem, security updates are grouped so one pull request can clear every
open advisory, and major updates arrive one by one for review. Because the
dependency gate fails on *any* known advisory, keep lockfiles current — an
unmerged security update turns every other pull request red too.

## Changing the gates (operator-only)

The quality lanes are **not** defined in this repository. They live in
[quality-zero-platform](https://github.com/Prekzursil/quality-zero-platform),
which governs every repository in the fleet:

- Gate changes happen in QZP, through a pull request — never by editing lanes
  here and never by weakening a check locally.
- This repository picks up a gate change when its `quality.yml` pin is bumped
  to the QZP commit that contains it.
- If a gate change turns this repository red, the fix belongs in the code (or,
  if the gate is wrong, in QZP) — not in a local exception.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
Report conduct violations privately via [private vulnerability reporting](https://github.com/Prekzursil/Reframe/security/advisories/new) (a private channel to the maintainer) or through the maintainer's [GitHub profile](https://github.com/Prekzursil).
