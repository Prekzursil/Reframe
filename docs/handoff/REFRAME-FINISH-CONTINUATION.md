# CONTINUATION PROMPT — finish Reframe v1.4 (paste into the ⠐ REPO / HOOKS_UPGRADE+REFRAME session)

You are the finishing session for the **Reframe** app (`C:\Users\Prekzursil\Documents\GitHub\Reframe`,
branch `feat/reframe-v1.4`). Everything else in the program is DONE — your job is the Reframe v1.4 finish
and a few small residuals. Do not redo the completed work below.

## WHAT'S ALREADY DONE (do NOT redo)
- **Make Shorts works.** Three Windows-only bugs were root-caused + fixed + committed on `feat/reframe-v1.4`
  (see `docs/research/GOLDEN-JOURNEY-FINDINGS-2026-07-07.md`): CRLF in the WSL scripts (`789300d`), verthor
  teardown SIGSEGV tolerance (`789300d`), vidstab `.trf` filtergraph path → bare-basename+cwd (`b2deba8`),
  and a stabilize abspath guard (`f74b8cc`). The full pipeline produces a real vertical short.
- **The golden-journey is FULLY GREEN (both tests, `37dd956`).** `app/e2e/golden-journey.spec.ts` drives
  the real Electron GUI + sidecar, provisions YuNet (a real first-run), asserts a real 1080x1920 short on
  disk (default `auto`→claudeshorts path), AND passes the "no console errors" check. Wire it into CI (B6).
- **The whole harness gem/skill program is built + merged + live** (agent-skills-toolchain) — you can USE
  these on this work: skills `seed-golden-journey`, `two-tier-verify`, `acceptance-review` (cross-model:
  codex/gemini/fresh-Claude), `mutation-check`, `triage-dispatch`, `fresh-context-verify`; Stop-hooks
  claim-guard/test-tamper-guard/journey-coverage already gate "done" claims.

## YOUR JOB — Reframe v1.4 finish (`docs/plans/v1.4-remediation.md`), command-proven, no self-cert
- **WU1** — green `origin/main` + reconcile the ~77 local-only `feat/reframe-v1.4` commits (torch
  `2.11.0+cu128` re-pair). `git log feat/reframe-v1.4..origin/main` empty; `quality.yml` green.
- **WU2** — renderer resilience P0 (white-screen): a TESTED `ErrorBoundary` wrapping `<App/>`; guard every
  eager-rpc render/effect `bridge()`/`client.*` site (component test with `window.api` undefined → inline
  error, not blank); `main.ts` render-process-gone / uncaughtException handlers.
- **WU3** — the two LIVE P0 security bugs behind `xfail(strict=True)` (consent-egress leak + auth-header
  corruption): remove each marker → watch RED → fix → GREEN; fix the redacted-key UnicodeEncodeError;
  rewrite the stale no-op control test. `grep -Pzo 'xfail\([^)]*strict=True' sidecar/tests` returns 0.
- **WU4** — full independent sweep: sidecar `pytest --cov ... --cov-fail-under=100` (default) AND
  `pytest -m e2e` (ffmpeg on PATH); `vitest run --coverage` + `jest`; basedpyright/ruff/tsc/biome; charter;
  pre-commit. No new coverage-exclusions (diff-check).
- **WU5** — docs/packaging: README 1.2.0 → 1.4.0; CodeQL workflow.
- **WU6** — ship: a real `media-studio-1.4.0-win-x64.exe` installs on a clean Win-x64 box → real
  transcribe→reframe→export offline, no white screen / "sidecar not running" / player code-4. If
  un-runnable in-harness, hand back an exact repro script; do NOT claim success.

## DEFERRED RESIDUALS (mine, handed to you)
- **B1 (poster 404) — DONE (`37dd956`), golden-journey fully green.** Root-caused by runtime
  instrumentation: `os.tmpdir()` gave main a 8.3 SHORT-name `DATA_ROOT` (`PREKZU~1`) while the sidecar
  canonicalized its poster path to the LONG name (`Prekzursil`), so the mstream `thumb:` containment guard
  rejected the existing poster → 404. Fixed by canonicalizing the E2E data root with
  `realpathSync.native`. Optional WU2 hardening: `exportPath.resolveScopedMediaPath` compares LEXICALLY
  before its realpath re-check, so it would 404 for ANY short/long-form split — canonicalize the guard's
  inputs if a short-name `DATA_ROOT` could reach production.
- **B4 (auto→verthor fallback): a DESIGN DECISION, not a bug.** `resolve_engine_name` is deliberate (P3
  flip: claudeshorts default, verthor explicit-only, "no silent substitution"). If YuNet is unprovisioned,
  `auto` raises rather than falling back. DECIDE whether to keep that (provisioning is first-run's job) or
  add a graceful degrade — it's your architectural call, not a defect.
- **B6:** wire `golden-journey.spec.ts` into `e2e.yml` as the Make Shorts merge gate (fold into WU1/WU4 CI).
- **B2:** the verthor teardown SIGSEGV is tolerated at the wrapper (valid-output gate); the upstream fix
  (`os._exit(0)` after a clean write) lives in the WSL verthor package — out of scope unless you own it.

## METHOD + GUARDRAILS
Use `triage-dispatch` for the multi-WU work (audit → capture the REAL error, never infer the stage → defect
graph → parallel bounded fixes → inner/outer verify → `acceptance-review`). Use `seed-golden-journey` to add
any new journey gates; `two-tier-verify` for the loops; `mutation-check` at the done boundary. TDD; never
`--no-verify`; never `git push --force` to main without approval; git-crypt secrets (`accounts.json`) never
staged in plaintext; the metaswarm design/plan gates apply for the big WUs. Coverage SSOT =
`.coverage-thresholds.json` (100/100/100/100). "Green mocked tests ≠ works" — the golden-journey is the truth.

## DEFINITION OF DONE
`feat/reframe-v1.4` → `main` PR with `quality.yml` + `e2e.yml` + `mutation.yml` green on the full diff; both
P0 tests pass by fix; no `xfail(strict=True)` in `sidecar/tests`; ErrorBoundary tested; full sweep green;
golden-journey (both tests) green + wired as the gate; a real 1.4.0 installer verified (or an exact repro
handed back); no blocker/high left. Run `/self-reflect` and commit learnings before the PR.
