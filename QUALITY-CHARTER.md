# Quality Charter — Lean Deterministic Gate Model

This repository runs a **closed set of 6 deterministic, local-first quality gates**
behind **one** CI status check named `quality`. Every gate is a tool that runs the
same way locally and in CI, with **pinned versions** and an in-repo config. There is
no SaaS quality platform, no baseline files, and no auto-fetched rulesets.

## The closed gate list

<!-- BEGIN GATES (parsed by .quality/charter_check.py — keep this table in sync with .github/workflows/quality.yml) -->

| # | Gate | Tool(s) (pinned) | What it enforces |
|---|------|------------------|------------------|
| 1 | lint-format | ruff 0.15.17 · oxlint 1.70.0 · biome 2.5.0 · rustfmt/clippy (rust 1.96.0) | Lint + format + security-lint across Python, JS/TS, Rust. Auto-fixers: `ruff check --fix` + `ruff format`; `oxlint --fix --deny-warnings`; `biome format --write`; `cargo fmt` + `cargo clippy --all-targets --all-features -- -D warnings`. |
| 2 | types | tsc (typescript 5.x) · basedpyright 1.39.8 | `tsc --noEmit` for apps/web + apps/desktop; basedpyright (`typeCheckingMode=standard`) for apps/api + services/worker + packages/media-core. |
| 3 | tests-coverage | pytest 9 + pytest-cov (branch, `--cov-fail-under=100`) · vitest 4 (100% thresholds) | Strict 100% line+branch coverage. Reasoned `# pragma: no cover — <reason>` / `/* v8 ignore */` allowed for genuinely-untestable platform branches. |
| 4 | sast | opengrep 1.22.0 (CI) / semgrep 1.166.0 (local) | Static security analysis using the curated in-repo ruleset under `.quality/opengrep/` (NOT `--config auto`). Clean-zero lock: 0 findings, no baseline. |
| 5 | secrets | gitleaks 8.30.1 | Secret scanning with the committed `.gitleaks.toml` allowlist (vendored deps + reasoned test fixtures only). Gate on 0. |
| 6 | deps | osv-scanner 2.3.8 | Known-CVE scan of the lockfiles (apps/web, apps/desktop npm + Cargo.lock, apps/api + services/worker requirements). Reasoned per-vuln ignores only in `osv-scanner.toml`; no baseline. Gate on 0. |

<!-- END GATES -->

## Rules of the charter

1. **One CI check.** All gates run inside the single `quality` job in
   `.github/workflows/quality.yml`. Branch protection requires only `quality`
   (plus the separate `CodeQL` analysis, which is GitHub-native security scanning,
   not part of this 6-gate set).
2. **One-in / one-out.** The gate list is closed. Adding a gate requires removing
   one (or an explicit charter amendment). Changing a tool requires updating its
   pinned version here, in `.pre-commit-config.yaml`, and in `quality.yml` together.
3. **Determinism.** Every tool is version-pinned and configured from an in-repo file.
   No `--config auto`, no registry login, no network-fetched rule packs in the gate.
4. **Clean-zero, no baselines.** Gates reach zero by fixing the finding or by a
   **reasoned, greppable** suppression (`# pragma: no cover — …`, `# noqa: <rule> — …`,
   `# nosemgrep: <rule> — …`, an allowlist entry, or a per-vuln ignore with a reason).
   We do not carry baseline/"accepted findings" files.
5. **Charter ↔ workflow sync.** `.quality/charter_check.py` parses this gate table
   and the steps in `quality.yml` and fails CI if they diverge.

## Notes on specific decisions

- **JS/TS formatter = Biome (format-only), not oxfmt.** As of the build date the OXC
  formatter (`oxfmt`) is still **beta** (0.55.0, no 1.0/GA), so the formatter gate uses
  Biome 2.5.0 `format --write` (linter disabled in `biome.json`; linting is oxlint's job).
- **basedpyright mode = `standard`** (not `strict`) so "literal zero" stays achievable
  on partly-untyped code and untyped third-party libraries.
- **react-hooks/exhaustive-deps = off** in oxlint: it is advisory and its auto-fix can
  introduce render loops; the original (dead) ESLint config treated it as a non-blocking
  warning.
- **ESLint is retired.** `apps/web/.eslintrc.cjs` was a dead config (plugins not
  installed); its intent was migrated to `.oxlintrc.json` via `@oxlint/migrate` and the
  file deleted.
