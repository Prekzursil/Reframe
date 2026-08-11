# Quality Charter — Lean Deterministic Gate Model

> **Status:** ACTIVE

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
| 1 | lint-format | ruff 0.15.17 · oxlint 1.69.0 · biome 2.5.0 · docs_check · reachability_check · electron_hardening_check (all stdlib) | Lint + format + security-lint across Python (sidecar) and JS/TS (app), **plus three stdlib anti-drift checkers**. Auto-fixers: `ruff check --fix` + `ruff format`; `oxlint --fix --deny-warnings`; `biome format --write`. `.quality/docs_check.py` enforces the anti-drift rules in [`docs/INDEX.md`](docs/INDEX.md#anti-drift) — status line, no dangling `docs/**` citation, every live doc indexed, no gitignored path cited, no bare-basename citation. `.quality/reachability_check.py` (W26) fails on a production `app/**` module that no entry point can reach, and on a dead waiver in `.quality/reachability_allowlist.json`. `.quality/electron_hardening_check.py` (W66) fails when `electron-builder.yml` stops declaring the required Electron fuses or `app/main/main.ts` stops declaring the BrowserWindow sandbox triple. |
| 2 | types | tsc (typescript 5.x) · basedpyright 1.39.8 | `tsc --noEmit` for `app/` (main + renderer) and `app/render-cli/`; basedpyright (`typeCheckingMode=standard`) for `sidecar/media_studio`. |
| 3 | tests-coverage | pytest 9 + pytest-cov (branch, `--cov-fail-under=100`) · vitest 3 (100% thresholds) | Strict 100% line+branch coverage **everywhere** — sidecar (`media_studio` **and** `contract`, two `--cov` roots under one floor over their union) **and** the renderer (`renderer/src/**`). No hybrid/ratchet floor. Reasoned `# pragma: no cover — <reason>` / `# pragma: no branch — <reason>` / `/* v8 ignore — <reason> */` allowed only for genuinely-untestable platform/defensive branches. |
| 4 | sast | opengrep 1.22.0 (CI) / semgrep 1.166.0 (local) | Static security analysis using the curated in-repo ruleset under `.quality/opengrep/` (NOT `--config auto`). Clean-zero lock: 0 findings, no baseline. |
| 5 | secrets | gitleaks 8.30.1 | Secret scanning with the committed `.gitleaks.toml` allowlist (vendored deps + reasoned test fixtures only). Gate on 0. |
| 6 | deps | osv-scanner 2.3.8 | Known-CVE scan of **five lockfiles**: the `app` + `app/render-cli` npm lockfiles, the resolved `sidecar/requirements.lock.txt`, and both first-run `pip --target` environments (`sidecar/runtime_setup/requirements-sidecar.txt` plus `requirements-chatterbox.txt`, whose own `+cu128` torch build no other lockfile can contain). Read flat (`--no-resolve`), so declared pins rather than the transitive closure. **NOT scanned by this gate:** the `reframe-gpu` extra in `sidecar/pyproject.toml` (`torch==2.6.0`, inside GHSA-rrmf-rvhw-rf47's range), which the shipped sidecar asks the user to install at runtime — an open item, covered today only by the advisory Dependabot rail. Reasoned, dated per-vuln ignores only in `osv-scanner.toml`; no baseline. Gate on 0. |

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
- **The deps gate scans environments, not just the two npm trees.** The isolated
  py3.14 chatterbox voice-clone env is a *deliberate* separation — `sidecar/pyproject.toml`
  forbids chatterbox-tts/torch in the main sidecar env, and the env exists at all because
  chatterbox-tts 0.1.7 only accepts py3.14 — so the fix for its missing CVE coverage was to
  add its requirements file to the EXISTING gate-6 lockfile set, never to unify the torch
  pins. Adding a scanned lockfile is not a new gate and does not touch the one-in/one-out
  rule (rule 2), which is about the closed list of six gates. Section 5 of
  `sidecar/tests/test_supply_chain_pins.py` asserts that every **discovered** shipped
  environment has a `--lockfile` argument.
  **Scope of that invariant, measured — it is three globs, not a closure.** An earlier
  wording here claimed a fourth environment "cannot be added unscanned" full stop; three
  reviewers refuted it by executing the discovery against synthetic trees. A new environment
  is caught only if it arrives as `app/package-lock.json`,
  `app/<immediate-subdir>/package-lock.json`, `sidecar/requirements*.txt`, or
  `sidecar/runtime_setup/requirements*.txt`. One declared anywhere else is invisible to it —
  a repo-root lockfile, two levels under `app/`, a sibling top-level tree, a `sidecar/envs/…`
  tree, a pin list not named `requirements*`, or a dependency set declared as a `pyproject`
  extra. The last is live, not hypothetical: it is exactly how `reframe-gpu` escapes gate 6.
  Both directions are asserted by `TestDiscoveryScopeIsTheThreeGlobs` (4 discovered shapes as
  a detector control, 6 undiscovered shapes as the boundary), so this paragraph cannot drift
  away from the code silently. Widening a glob must update that test and this text together.
- **Reachability rides gate 1; the RPC half rides gate 3 (W26).** Five defects this
  programme fixed (W16-W20) were *built, tested, 100%-covered and mounted nowhere*, and
  gate 3 caught none of them — coverage proves a line EXECUTED under some test, which an
  unreachable module still does. `.quality/reachability_check.py` walks the `app/**` TS
  import graph from five declared entry points; the sidecar RPC surface is enumerated by
  RUNNING `register_all` with a collecting registrar, so that half lives in
  `sidecar/tests/test_reachability_gate.py` (a static scan of 14 handler modules would be
  a guess). Both read one allowlist, `.quality/reachability_allowlist.json`, where every
  waiver carries a WRITTEN reason — an allowlist is required because this repo ships some
  code unreachable on purpose (the generated RPC-contract POC artifacts; `reframe.analyze`
  / `reframe.render`, registered backend-only while the renderer wave is unstarted).
  Waivers are checked in BOTH directions (u2/u3 + `test_no_dead_rpc_waivers`), so the list
  tracks the tree rather than history. Neither half is a new gate.
  **Scope, stated so it is not read as more:** this is MODULE reachability, not per-EXPORT
  deadness — a module imported for one symbol while three others are dead still passes.
  UNVERIFIED whether per-export deadness exists in this tree; the settling experiment is a
  pinned in-repo `knip`/`ts-prune` run, which rule 3 (determinism, no network-fetched rule
  packs) does not admit today.
- **Electron hardening is enforced from the packaging config, and Electronegativity is
  deliberately NOT wired (W66).** `.quality/electron_hardening_check.py` asserts (e1)
  `electron-builder.yml` declares `asar: true`, a NON-EMPTY top-level `electronFuses:`
  block, and each of the eight required fuses with its required value **inside that block,
  at every occurrence** — ASAR integrity + `onlyLoadAppFromAsar` ON, `NODE_OPTIONS`/
  `--inspect` OFF, and `runAsNode` pinned **true** because the caption render path spawns
  the Electron exe as plain Node — and (e2)
  `app/main/main.ts` still declares `contextIsolation`/`nodeIntegration`/`sandbox`, with no
  `app/main/**` file re-opening the renderer via `webSecurity: false`. e2 exists because of
  a measured overclaim caught while writing this very note: `app/main/security.test.ts`
  asserts the CSP header only, and the three `webPreferences` literals at
  `main.ts:1080-1085` had NO assertion anywhere. Doyensec's Electronegativity itself would
  have to be fetched and installed to be verified, and a blocking step whose first real run
  happens on a shared runner is the "green gate that was never seen red" failure this
  charter exists to prevent. Revisit it as a pinned devDependency once someone can run it
  locally first.
  **TWO earlier wordings of the e1 sentence above are REFUTED, recorded rather than
  deleted.** (1) "declares the whole `electronFuses` block" was written against the
  pre-#409 gate, which proved only that the HEADER line existed and then matched fuses
  anywhere in the file, first occurrence only — wider than the code it described.
  (2) Its replacement, drafted 2026-08-11 against branch base `81a04965`, said the gate
  asserts a header line **and** the eight fuse values, and stated as measured fact that
  re-homing all eight fuses under another top-level key with `electronFuses:` left empty
  was CLEAN, that a second contradicting `enableEmbeddedAsarIntegrityValidation: false`
  was CLEAN, and that "this paragraph tightens when PR #409 lands". PR #409 had ALREADY
  merged (`60f1a43e`, 2026-08-11T02:43:13Z — fourteen minutes after that commit), so the
  wording landed false the moment it was written. Re-measured against `origin/main` by
  calling `check_fuses` on the real yml plus mutations: BOTH of those mutations are now
  CAUGHT (`has an EMPTY electronFuses: block — it flips nothing`; `fuse
  enableEmbeddedAsarIntegrityValidation is false, must be true`), because #409 added
  `fuses_block()` block-slicing, an explicit empty-block rejection, and a `finditer`
  every-occurrence walk. Both wordings ALSO omitted the third assertion the checker makes,
  `asar: true` (`_ASAR_TRUE_RE`, asserted identically at both revisions — mutating it to
  `false` is CAUGHT before and after). Detector control for the flipped pair: the
  unmutated yml is CLEAN, and a deleted fuse line and a commented-out header are each
  CAUGHT, at BOTH revisions — so the difference is the gate change, not a broken probe.
  Standing lesson, not a to-do: a dated measurement taken against an OPEN PR expires the
  moment that PR merges. Re-probe `origin/main` before quoting gate behaviour here.
  **What is NOT proven by this gate:** it reads CONFIG, so it proves the fuses are
  *declared*, not that the bits are flipped in a built exe. Settling experiment:
  `npx electron-builder --config ../electron-builder.yml --win`, then
  `npx electron-fuses read --app dist/win-unpacked/Reframe.exe`. Agents do not run builds.
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
