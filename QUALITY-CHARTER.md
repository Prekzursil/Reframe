# Quality Charter — Lean Deterministic Gate Model

This repository runs a **closed set of 6 deterministic, local-first quality gates**
behind **one** CI status check named `quality`. Every gate is a tool that runs the
same way locally and in CI, with **pinned versions** and an in-repo config. There is
no SaaS quality platform, no baseline files, and no auto-fetched rulesets.

Media Studio is an Electron app (TypeScript renderer + main under `app/`, the Remotion
render CLI under `app/render-cli/`) with an embedded Python compute sidecar under
`sidecar/`. There is **no Rust / Tauri** in this app, so the Rust lint/format/deps
gates that exist in the source charter do not apply here and have been dropped.

## The closed gate list

<!-- BEGIN GATES (parsed by .quality/charter_check.py — keep this table in sync with .github/workflows/quality.yml) -->

| # | Gate | Tool(s) (pinned) | What it enforces |
|---|------|------------------|------------------|
| 1 | lint-format | ruff 0.15.17 · oxlint 1.70.0 · biome 2.5.0 | Lint + format + security-lint across Python (sidecar) and JS/TS (app). Auto-fixers: `ruff check --fix` + `ruff format`; `oxlint --fix --deny-warnings`; `biome format --write`. |
| 2 | types | tsc (typescript 5.x) · basedpyright 1.39.8 | `tsc --noEmit` for `app/` (main + renderer) and `app/render-cli/`; basedpyright (`typeCheckingMode=standard`) for `sidecar/media_studio`. |
| 3 | tests-coverage | pytest 9 + pytest-cov (branch, `--cov-fail-under=100`) · vitest 1 (100% thresholds) | Strict 100% line+branch coverage. Reasoned `# pragma: no cover — <reason>` / `/* v8 ignore */` allowed for genuinely-untestable platform branches. |
| 4 | sast | opengrep 1.22.0 (CI) / semgrep 1.166.0 (local) | Static security analysis using the curated in-repo ruleset under `.quality/opengrep/` (NOT `--config auto`). Clean-zero lock: 0 findings, no baseline. |
| 5 | secrets | gitleaks 8.30.1 | Secret scanning with the committed `.gitleaks.toml` allowlist (vendored deps + reasoned test fixtures only). Gate on 0. |
| 6 | deps | osv-scanner 2.3.8 | Known-CVE scan of the lockfiles (`app` + `app/render-cli` npm, `sidecar` pyproject). Reasoned per-vuln ignores only in `osv-scanner.toml`; no baseline. Gate on 0. |

<!-- END GATES -->

Dependency freshness is additionally automated via Dependabot (`.github/dependabot.yml`,
weekly patch/minor groups for the `app`, `app/render-cli` npm trees, the `sidecar` pip
tree, and github-actions); that is supply-chain hygiene, not part of the 6-gate set.

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

- **No Rust gate.** Media Studio has no Tauri/Rust crate (the desktop shell is
  Electron); the rustfmt/clippy lint-format coverage and the `Cargo.lock` osv lockfile
  from the source charter were dropped, not ported.
- **JS/TS formatter = Biome (format-only), not oxfmt.** As of the build date the OXC
  formatter (`oxfmt`) is still **beta** (no 1.0/GA), so the formatter gate uses
  Biome 2.5.0 `format --write` (linter disabled in `biome.json`; linting is oxlint's job).
- **basedpyright mode = `standard`** (not `strict`) so "literal zero" stays achievable
  on partly-untyped code and untyped third-party libraries.
- **react-hooks/exhaustive-deps = off** in oxlint: it is advisory and its auto-fix can
  introduce render loops; it is treated as non-blocking.
- **Single oxlint config for the app.** Unlike the source repo's web/desktop split,
  Media Studio's TS lives in one tree (`app/`), so there is one `app/.oxlintrc.json`
  covering `main/`, `renderer/src/`, and `render-cli/src/`.
- **Quality-Zero-Platform (QZP) governance is retired.** Reframe no longer runs the
  legacy QZP control-plane machinery — the branch-protection audits, the "strict-23"
  canonical-context rollout, the remediation loops, and the weekly ops digest. Those
  bots auto-filed governance issues (e.g. "Branch protection audit", "strict-23 rollout
  preflight", "Weekly Ops Digest") against this repo. There is no QZP workflow inside
  Reframe; the single lean **`quality`** gate above is now the sole quality contract.
  Any future QZP-style issue should be closed as retired.
