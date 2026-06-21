# Reframe — PR Purge & SaaS-Gate Cleanup Checklist (READ-ONLY AUDIT)

**Repo:** `Prekzursil/Reframe` (public) · default branch `main`
**Compiled:** 2026-06-16 · **Read-only audit — NOTHING was changed.** Every item below is an action for *you* to click through.
**Context:** Migrating from the old SaaS-heavy "quality-zero-platform" CI to a single lean deterministic `quality` gate (PR #202). The old SaaS status checks are still **required** on `main`, so they permanently block every PR.

---

## 1. Branch-protection required status checks on `main` (the blockers)

`main` requires **19** status-check contexts (`strict: true` = must also be up-to-date). The new lean model emits only one GitHub-Actions job named **`quality`** (see PR #202) plus `codeql / CodeQL`. **17 of the 19 required contexts will NEVER report on the lean model → every PR stays `BLOCKED` forever.**

Other protection settings (FYI, not blockers): linear history ON, force-push OFF, deletions OFF, required approvals **0**, enforce-admins OFF, signatures OFF.

### Required contexts → KEEP / REMOVE

| # | Required context | Source | Recommendation |
|---|---|---|---|
| 1 | `Chromatic Playwright` | Chromatic SaaS | **REMOVE** — SaaS visual, not in lean model |
| 2 | `Applitools Visual` | Applitools SaaS | **REMOVE** — SaaS visual |
| 3 | `SonarCloud Code Analysis` | SonarCloud SaaS | **REMOVE** — replaced by local opengrep/qlty-free |
| 4 | `Python API & worker checks` | old SaaS-platform workflow | **REMOVE** — superseded by lean `quality` |
| 5 | `Web build` | old SaaS-platform workflow | **REMOVE** (or fold into `quality`) |
| 6 | `DeepScan` | DeepScan SaaS | **REMOVE** — SaaS |
| 7 | `CodeRabbit` | CodeRabbit SaaS | **REMOVE** — SaaS review bot |
| 8 | `Codacy Static Code Analysis` | Codacy SaaS | **REMOVE** — SaaS |
| 9 | `qlty check` | qlty SaaS | **REMOVE** — SaaS (lean uses local checks) |
| 10 | `qlty coverage` | qlty SaaS | **REMOVE** — SaaS |
| 11 | `qlty coverage diff` | qlty SaaS | **REMOVE** — SaaS |
| 12 | `shared-scanner-matrix / Coverage 100 Gate` | old shared-matrix workflow | **REMOVE** — coverage now enforced inside `quality` |
| 13 | `shared-codecov-analytics / Codecov Analytics` | Codecov SaaS | **REMOVE** — SaaS |
| 14 | `shared-scanner-matrix / Sonar Zero` | old shared-matrix | **REMOVE** |
| 15 | `shared-scanner-matrix / Codacy Zero` | old shared-matrix | **REMOVE** |
| 16 | `shared-scanner-matrix / Semgrep Zero` | old shared-matrix | **REMOVE** |
| 17 | `shared-scanner-matrix / Sentry Zero` | old shared-matrix | **REMOVE** |
| 18 | `shared-scanner-matrix / DeepScan Zero` | old shared-matrix | **REMOVE** |
| 19 | `codeql / CodeQL` | GitHub-native CodeQL | **KEEP** — native, free, runs on PR #202 |

**ACTION:** Settings → Branches → `main` → Edit → "Require status checks to pass" → **remove the 18 SaaS/old-matrix contexts above**, then **add the new `quality` context** (the lean GitHub-Actions job name). Keep `codeql / CodeQL`.
After this, the lean PRs (#200/#201/#202) become mergeable on their real `quality` result.

> NOTE: contexts only become *removable from the picker* once they stop being reported; you can delete them from the required-list immediately via the branch-protection UI/API regardless. There is also a `branch-protection-audit.yml` workflow in the repo that may re-assert contexts — disable or update it too (see §3).

---

## 2. Open pull requests (45 total) — merge / close recommendations

All show `BLOCKED` purely because of the §1 required SaaS contexts (every one is `MERGEABLE` at the git level unless noted). Fix §1 first, then:

### Feature / quality PRs (decide individually)

| PR | Title | Git state | Recommendation | Reason |
|---|---|---|---|---|
| **#202** | feat(quality): lean deterministic gate model (proof) | MERGEABLE | **MERGE FIRST** | This *is* the new gate. Its `quality` job ran (failing only on residual SaaS app-checks, not the lean job's own logic). Land it, then it defines the keep-context for §1. |
| **#201** | fix(quality): Sonar-zero remediation R1 (29 files) | MERGEABLE | **MERGE or CLOSE** | If the lean model drops SonarCloud (it does), this Sonar-specific remediation is largely moot. Keep only if the file fixes are independently good; otherwise close. |
| **#200** | feat(desktop-electron): land Reframe Media Studio (Electron) | MERGEABLE | **HOLD → re-evaluate** | This is the desktop fat-client RFC. The current local `media-studio` branch work (sidecar + features) likely supersedes/overlaps it. Reconcile against the local branch before merging; may need rebase or close-in-favor-of the new branch. **User decision.** |
| #196 | chore: markdownlint structural fixes (MD022/032/031) | MERGEABLE | **MERGE** (low risk) or close if docs since changed | Pure doc lint; cheap to land after §1. |
| #193 | feat: add Reframe ECC bundle (app/ecc-tools) | MERGEABLE | **CLOSE** | Auto-generated ECC bundle PR; workspace curation has moved on. Close unless you still want the bundle. |
| #192 | fix: CodeQL findings + Rust desktop unit tests | MERGEABLE | **REVIEW → MERGE** | Real CodeQL fixes + tests are worth keeping (CodeQL stays required). Rebase + merge. |
| #191 | chore: dependabot grouping + ruff CodeQL fixes (QZP) | MERGEABLE | **CLOSE** | "QZP" = quality-zero-platform, the SaaS model being retired. The dependabot-grouping config may still be useful — cherry-pick that, close the rest. |
| **#114** | chore: adopt quality-zero-platform wrappers | **CONFLICTING (DIRTY)** | **CLOSE** | Directly adopts the SaaS platform you're abandoning + has conflicts. Close. |
| **#107** | feat: strict coverage truth + desktop runtime release wave | **CONFLICTING (DIRTY)** | **CLOSE** | Old (2026-03-04), conflicting, predates the lean model + new desktop branch. Close; salvage any unique idea manually. |

### Dependabot PRs (36 open)

36 dependabot PRs, oldest from 2026-03-26 (#125), spanning `apps/web`, `apps/desktop`, `apps/api`, `services/worker`, `packages/media-core`, github-actions. Several are `BEHIND` (#132, #130, #125) and need rebase.

**Recommendation — batch handling after §1:**
- **The new desktop product lives in `apps/desktop` / the new `media-studio` branch sidecar** — dependency bumps for `apps/web`, `apps/api`, `services/worker` (the old SaaS backend) are **low value** if those surfaces are being deprecated. **Decide first whether the SaaS backend (`apps/api`, `services/worker`, `apps/web`) is still in scope.**
  - If **deprecating the SaaS backend:** **CLOSE** all dependabot PRs scoped to `apps/web`, `apps/api`, `services/worker` (that's the large majority — ~#143–#199 web + #153–#170 api/worker).
  - If **keeping it:** let dependabot rebase, then merge the security-relevant ones (undici #194/#195, qs #182, shell-quote #197, follow-redirects #150, lodash #143, protobufjs #199) first; defer dev-only patch bumps.
- **`apps/desktop` bumps** (#194, #188, #171, #125, vite/undici/picomatch) — **KEEP & merge** (this surface stays).
- **`packages/media-core` torch/torchaudio** (#178, #132) — **KEEP** if media-core is shared by the desktop/sidecar pipeline; these matter for the Phase-8 ML stack.
- **`.github/actions` group** (#134) — **MERGE** (CI hygiene).

> Quickest path once scope is decided: in the Dependabot settings, narrow the `directories`/`package-ecosystems` to only the surfaces you keep, then bulk-close the rest with a comment. This also stops the flood from regenerating.

---

## 3. Installed GitHub Apps — SaaS uninstall candidates

> The PAT in use cannot list org/user app *installations* directly (403). The list below is derived from the **check-suite apps actually posting to this repo** + the branch-protection `app_id`s — i.e. the apps that are demonstrably installed and active.

Apps observed posting checks/suites to `Prekzursil/Reframe`:

| App (slug) | Role | Still needed for lean model? | Recommendation |
|---|---|---|---|
| `github-actions` (app_id 15368) | native CI runner | YES | **KEEP** — runs the lean `quality` + codeql |
| CodeQL (native) | SAST | YES | **KEEP** |
| `codacy-production` (app_id 56611) | SaaS static analysis | NO | **UNINSTALL** |
| `qltysh` (app_id 890766) | SaaS quality/coverage | NO | **UNINSTALL** |
| `sonarqubecloud` | SaaS static analysis | NO | **UNINSTALL** |
| `deepsource-io` | SaaS static analysis | NO | **UNINSTALL** |
| `codecov` | SaaS coverage analytics | NO | **UNINSTALL** |
| `coderabbitai` | SaaS AI review | NO (optional) | **UNINSTALL** unless you want AI PR review |
| `chromatic-com` | SaaS visual regression | NO | **UNINSTALL** |
| `sentry` | SaaS error monitoring | only at runtime, not CI gate | **KEEP install** but **remove its required CI context** (§1 #17) |
| `semgrep-code-prekzursil` | Semgrep Cloud SAST | NO (lean uses local opengrep) | **UNINSTALL** |
| Applitools (app_id 15368 ctx) | SaaS visual | NO | **UNINSTALL** |
| BrowserStack | SaaS E2E | optional | **UNINSTALL** unless you keep cross-browser E2E |
| Socket Security | SaaS dep scanning | optional (overlaps osv-scanner) | **UNINSTALL** unless wanted; osv-scanner covers deps locally |
| DeepScan | SaaS JS analysis | NO | **UNINSTALL** |
| `greptile-apps` | SaaS AI code search/review | NO | **UNINSTALL** unless used |
| `netlify` | SaaS web preview deploy | only if keeping `apps/web` | **UNINSTALL** if deprecating the web app |
| `vercel` | SaaS web preview deploy | only if keeping `apps/web` | **UNINSTALL** if deprecating the web app |
| `figma` | design integration | not a CI gate | KEEP/ignore (harmless) |
| `claude` | Claude GitHub app | dev tooling | KEEP (your tooling) |

**ACTION:** Settings → Integrations → GitHub Apps (and/or https://github.com/settings/installations) → **Configure** each "UNINSTALL" app → remove access to `Reframe` (or uninstall entirely). Uninstalling stops them attaching new checks; combined with §1 this fully unblocks PRs.

> Two apps to handle carefully, NOT blind-uninstall: **Netlify/Vercel** (only drop if the `apps/web` SaaS frontend is being retired — confirm scope decision from §2 first) and **Sentry** (keep the install for runtime error reporting; just drop its *required-check* status).

---

## Recommended execution order (for the user to click)

1. **Merge PR #202** (lands the lean `quality` gate) — or at least confirm its `quality` job is the intended single gate.
2. **Edit `main` branch protection** (§1): remove the 18 SaaS/old-matrix required contexts, add `quality`, keep `codeql / CodeQL`.
3. **Disable/update `branch-protection-audit.yml`** + the `quality-zero-*.yml` workflows so they don't re-assert the old contexts.
4. **Decide SaaS-backend scope** (`apps/web` / `apps/api` / `services/worker`): keep or deprecate. This drives the dependabot + Netlify/Vercel decisions.
5. **Triage PRs** (§2): merge #202 → (review #192, #196) → close #114, #107, #193, #191, #201(if Sonar dropped) → reconcile #200 against the local `media-studio` branch.
6. **Bulk-close out-of-scope dependabot PRs**; narrow Dependabot config to kept surfaces.
7. **Uninstall the SaaS apps** (§3) once their checks are no longer required.

---

## Honest gaps / things I could NOT verify (no changes made)

- **App installation list is indirect.** The PAT returned 403 for `user/installations` and 401 for the repo-installation JWT endpoint. The §3 list is reconstructed from active check-suite apps + branch-protection app_ids — it is accurate for *apps currently posting to the repo*, but a silent/never-posting installed app would not appear. Verify the full list visually at https://github.com/settings/installations.
- **`quality` exact context name:** PR #202's GitHub-Actions job reports as `quality`. Confirm the precise required-context string when adding it to branch protection (it may render as `quality` or `CI / quality` depending on the workflow's job id/name in `ci.yml`).
- **#200 vs local branch overlap** is a judgment call I flagged for you — I did not diff the PR against the in-flight `media-studio` branch (that repo is owned by the other session right now).
