# Handoff Prompt — finish Reframe v1.4 + the hooks upgrade (paste into the ⠐ REPO / HOOKS_UPGRADE+REFRAME session)

You are picking up two intertwined tracks from a prior session: **finishing the Reframe v1.4 app**
(a real, stable, working release) and **the agent-harness hooks upgrade** (the "agentic-perfection"
program in `agent-skills-toolchain`). Everything below is verified state — trust it, but re-verify with
the external signals named, never self-certify.

## THE METHOD (use it for every remaining item)
The done-signal for an app is **not** coverage or green units — those are a proxy the implementer
controls (Goodhart). The only trustworthy signal is a **held-out golden-journey** that drives the REAL
app and asserts a REAL artifact on disk. Work red→fix→red: reproduce the failure end-to-end first, fix,
re-run, let the journey reveal the next blocker. When you claim "fixed/works", attach the real artifact
(the produced mp4 / ffprobe output / job.done payload), not a unit test. Forbid yourself new
`pragma:no-cover` / `xfail` / `skip` / coverage-omit / `-m` markers; diff-check every test/CI/coverage
change.

## WHAT'S ALREADY DONE (do not redo)
- **Golden-journey gem**: `Reframe/app/e2e/golden-journey.spec.ts` (committed on `feat/reframe-v1.4`) —
  launches the real Electron app + live sidecar, drives Make Shorts (manual interval), asserts a real
  vertical short on disk via the `shorts.list` RPC. This is the Make Shorts merge gate.
- **3 Windows-only Make-Shorts bugs fixed + committed** on `feat/reframe-v1.4` (see
  `Reframe/docs/research/GOLDEN-JOURNEY-FINDINGS-2026-07-07.md` for full root-cause):
  1. `789300d` — CRLF in `verthor_reframe.sh`/`wsl-verthor-bootstrap.sh` (WSL `set -euo pipefail\r`) +
     `.gitattributes *.sh text eol=lf` guard.
  2. `789300d` — verthor teardown SIGSEGV (exit 139): the wrapper now tolerates a post-render crash
     when `$OUT` is a genuinely valid video.
  3. `b2deba8` — vidstab `.trf` path broke the ffmpeg `-vf` filtergraph on Windows; now uses bare
     basename + `cwd=<trf dir>` (added optional `cwd` to `ffmpeg.run`; regression test added).
  4. `0372079` — the findings doc.
- **Proven**: forcing `reframeEngine:"verthor"`, the FULL export completes end-to-end and returns a real
  short (`job.done → clips:[{path:".../01-sample.mp4"}]`).
- **Harness (in `agent-skills-toolchain`, PR #43 merged to main)**: `claim-guard` G1 (functional-
  acceptance category needing external e2e/golden-journey evidence; opt-in `CLAIM_GUARD_MODE=block`) +
  `test-tamper-guard` G2 (opt-in `TEST_TAMPER_MODE=block`), synced live in default `warn`. Design doc:
  `docs/agentic-perfection/AGENTIC-REPAIR-RELIABILITY.md`.

## REFRAME — REMAINING WORK
### R0. Make the golden-journey GREEN (the Make Shorts gate)
It sends the UI default `reframeEngine:"auto"`, which resolves to the **claudeshorts** engine and dies
with `ClaudeShortsBackendUnavailableError: the YuNet face-detection model is not provisioned` — a
first-run/`assets.ensure` provisioning step, not a code bug. Choose:
- (a) provision the reframe model in the E2E setup (`assets.ensure` for `yunet-face-detection`, mirroring
  a real first-run), and/or
- (b) also exercise the proven verthor path.
Then confirm the golden-journey passes (real short on disk). **Fast repro without the 3.5-min Electron
E2E**: a direct sidecar-RPC harness (`export_repro.py` pattern) — spawn `python -m media_studio`
(cwd=`sidecar`), send `library.add` then `shortmaker.export` with a manual candidate, read stdout
notifications until `job.done` and drain stderr (the `jobs.py:650` traceback lives there). Consider
whether `auto` should fall back to verthor when the claudeshorts model is absent (a real UX question).

### R1–R6. The documented remediation plan (`Reframe/docs/plans/v1.4-remediation.md`)
This is the larger v1.4 finish, independent of the Make-Shorts bugs above. Execute its work units, each
command-proven (do NOT self-cert):
- **WU1** — green `origin/main` + reconcile the unmerged post-v1.2.0 commits (torch `2.11.0+cu128`
  re-pair; `git log feat/reframe-v1.4..origin/main` empty; `quality.yml` green).
- **WU2** — renderer resilience (P0 white-screen): a **tested** `ErrorBoundary` wrapping `<App/>`; guard
  every eager-rpc render/effect `bridge()`/`client.*` site so no unhandled throw escapes render (component
  test with `window.api` undefined → inline error, not blank); `main.ts` crash handlers.
- **WU3** — the two LIVE P0 security bugs behind `xfail(strict=True)` (consent-egress leak + auth-header
  corruption): remove each marker → watch RED → fix → GREEN; fix the redacted-key `UnicodeEncodeError`;
  rewrite the stale no-op control test + docstring. `grep -Pzo 'xfail\([^)]*strict=True' sidecar/tests`
  must return 0.
- **WU4** — full independent sweep (sidecar `pytest --cov ... --cov-fail-under=100` AND `pytest -m e2e`
  with ffmpeg on PATH; `npx vitest run --coverage` + `npx jest`; basedpyright/ruff/tsc/biome; charter
  check; pre-commit). No new coverage-exclusions (diff-check).
- **WU5** — docs + packaging (README stale 1.2.0 → 1.4.0; CodeQL workflow).
- **WU6** — ship: a real `media-studio-1.4.0-win-x64.exe` installs on a clean Win-x64 box, completes
  first-run bootstrap, does a REAL transcribe→reframe→export offline → usable Library UI, no white
  screen / "sidecar not running" / player code-4. If un-runnable in-harness, hand back an exact repro
  script; do NOT claim success.

## HOOKS UPGRADE — REMAINING WORK (`agent-skills-toolchain`)
- **Enable the gems per-repo after burn-in**: once `claim-guard`/`test-tamper-guard` have run in `warn`
  without false-positives, set `CLAIM_GUARD_MODE=block` / `TEST_TAMPER_MODE=block` in the target repo's
  env (they default to `warn` = unchanged).
- **Wire Reframe to the golden-journey as its functional-acceptance evidence** so a "shorts work" claim
  requires the golden-journey to have run.
- **Next unbuilt gems** (from the SOTA research; respect the ~6-active-hook latency ceiling — consolidate
  onto shared PreToolUse/PostToolUse/Stop/SessionStart seams, never one always-on hook per check):
  1. **Journey-coverage gate** — every declared app user-journey must have ≥1 passing E2E before "done"
     (auto-extract journeys à la TestSprite/Pathfinder; gate the diff).
  2. **Cross-model acceptance reviewer** — a fresh-context / different-model (Codex/Gemini) reviewer over
     the *running* app + the diff, at the "done" boundary (VeriMAP/MetaGPT-style verifier separation).
  3. **Mutation micro-check** at the verify boundary (break the fn under test → ≥1 test must go red).
- **Other orphaned live hooks**: audit `~/.claude/hooks` for anything not in the repo's `hooks/` (like
  claim-guard/test-tamper-guard were) and back-port so `sync-hooks.ps1` manages them.

## TOOLS / HARNESS AVAILABLE
Subagents (default substantive ones to Opus), the `Workflow` orchestrator for fan-out, `gh` for GitHub,
Playwright for the E2E, WSL for verthor, the sidecar-RPC repro pattern above. Quality gates:
`ruff`/`basedpyright`/`opengrep`/`gitleaks`/`osv` (toolchain CI = `quality.yml`); Reframe coverage SSOT =
`.coverage-thresholds.json` (100/100/100/100). Reframe metaswarm workflow gates apply (design/plan review
for big features).

## GUARDRAILS (non-negotiable)
TDD (tests first, watch fail). Never `--no-verify`. Never `git push --force` to main without explicit
approval. Secrets are git-crypt (`accounts.json`) — never stage plaintext. Stay in declared file scope.
Never self-certify — the golden-journey / external signal validates. On Windows, avoid `Remove-Item`/
`rd`/`del` command tokens (use a `.ps1` with .NET delete).

## DEFINITION OF DONE
1. `e2e/golden-journey.spec.ts` PASSES (real vertical short on disk) — the Make Shorts gate is green.
2. All of `v1.4-remediation.md`'s WU DoDs met, command-proven (both P0 tests pass by fix; no
   `xfail(strict=True)` in `sidecar/tests`; ErrorBoundary tested; full sweep green; no new coverage
   exclusions).
3. `feat/reframe-v1.4` → `main` PR with `quality.yml` + `e2e.yml` + `mutation.yml` green; a real 1.4.0
   installer verified (or an exact repro handed back).
4. Hooks: golden-journey wired as functional-acceptance evidence; block modes enabled where burned-in;
   `/self-reflect` learnings committed before the PR.
