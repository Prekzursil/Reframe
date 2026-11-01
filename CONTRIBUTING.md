# Contributing to Reframe

Reframe is a local-first desktop app (Electron + TypeScript app in `app/`,
Python sidecar in `sidecar/`, Remotion render CLI in `app/render-cli/`).
Every change lands through a pull request; the `quality` workflow gates it.

## The gates (`.github/workflows/quality.yml`)

| # | Gate | What runs |
|---|------|-----------|
| 1 | Lint + format | `pre-commit run --all-files` — ruff (lint+format) for `sidecar/**`, oxlint + biome for `app/**` |
| 2 | Types | `tsc --noEmit` (app), `tsc -p . --noEmit` (render-cli); typed via the repos' tsconfigs |
| 3 | Tests + coverage | sidecar: `pytest` with STRICT 100% line+branch (`--cov-branch --cov-fail-under=100`); app: `vitest run --coverage` with STRICT 100% line/branch/function/statement on the declared scope |
| 4 | SAST | opengrep over the tree (curated ruleset) |
| 5 | Secrets | gitleaks (always on; `.gitleaks.toml` is a reviewed allowlist only) |
| 6 | Deps | osv-scanner over all lockfiles — **zero tolerance**: every advisory blocks, `UNKNOWN` severity included |

## Declared coverage scope

- `app/renderer/src/**` is held to 100% (see `app/vitest.config.ts`).
- Security-critical main files (`main/socialAuth.ts`, `main/updateVerify.ts`,
  `main/updater.ts`) are also 100%-gated; the rest of `main/**` runs its tests
  but is bootstrap/IPC wiring not held to the threshold (declared in
  `app/vitest.config.ts`).
- `sidecar` is 100% line+branch via pytest-cov.
- Vendored research/archival trees are excluded **by name**, never rewritten.

Genuinely untestable runtime guards carry inline `/* v8 ignore … -- reason -- @preserve */`
pragmas — one per site, with the reason. Never a blanket ignore.

## Local commands

```bash
# everything CI gate:1 runs
pre-commit run --all-files

# sidecar tests (from sidecar/)
python -m pytest

# app tests + coverage (from app/)
npm ci && npx vitest run --coverage

# render-cli typecheck
npm --prefix app/render-cli run typecheck
```

## Rules

- Never weaken a gate to make a branch green. Fix the code or name the gap.
- Alerts (dependabot / code-scanning) are fixed by dependency bumps or code
  fixes — never dismissed.
- No direct pushes to `main`.
