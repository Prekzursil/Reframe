# Reframe v1.5 Zero-Defect — Grill Decision Queue

> **Status:** ACTIVE

Modes: **expansion + red-team + prioritization**. Started 2026-07-26.
Method: `grill-me-extensive`. One question per turn, each with a recommendation.
This file is the audit trail — every answer gets appended as it lands.

## Ground truth established BEFORE grilling (do not re-derive)

| fact | evidence |
|---|---|
| `main` = `91240473` | Windows packaging fix (#307) merged |
| Windows staging + packaging + packaged-`.exe` e2e | **SUCCESS on main** — first ever in repo history |
| Sole remaining Windows CI failure | `E2E GUI — VISUAL screenshot-diff + A11Y` — 9 failed / 9 passed |
| The a11y failure | `aria-valid-attr-value` **critical**: `aria-controls="tabpanel-make"` -> non-existent id |
| Visual failures | 8 `toHaveScreenshot` diffs: Library, Make Shorts, Director, Edit, Settings x2, Spend-cap, Workspace preview |
| `e2e-sidecar` failure | 3 tests; `provider pool exhausted (text): local -> no GGUF model configured`. **Pre-existing, cause-verified identical at baseline `97600e86`** |
| `macos-13` leg | Retired runner, queued forever. Dropped on `fix/v1.5-zero-defect` |
| Branch classification (deterministic, `.audit/classify_branches.py` <!-- ssot-allow: names the throwaway probe that produced the number -->) | **BR-AHEAD = 0 on all 11 branches**; 2592 MAIN-AHEAD; 333 DIVERGED |
| Falsification of "main wins everywhere" | **REFUTED IN PART** — 264 paths hold real branch-only lines; 3 declare identifiers main lacks |
| `feat/v1.5-bundle-fonts` | **100% already in main** — font work is landed |
| 12 lens reports in `.audit/v15/` <!-- ssot-allow: names scratch that MUST NOT be cited as authority --> | **UNFILLED SKELETONS** — agents died pre-measurement. MUST NOT BE CITED |
| Installed app | Reframe **1.4.1**, `D:\Program Files\Reframe`, uninstaller `/allusers` (needs elevation) |
| Data root | `MEDIA_STUDIO_CONFIG_DIR=D:\Reframe\data` (owner chose **CLEAN WIPE**) |

## Already decided (this session, by owner)

| # | decision | answer |
|---|---|---|
| P-0a | Data on uninstall | **Clean wipe** — delete `D:\Reframe\data`, fresh first-run |
| P-0b | Visual baselines policy | **Investigate each**, classify REGEN vs FIX-CODE with diff evidence |
| P-0c | UI scope | **Fix defects + full audit + land the pending redesign** |
| P-0d | Agent scale | **300-1000**, owner reaffirmed after my pushback |

## Decision queue

### FOUNDATION (F) — ask first, reframes everything
- [ ] **F-1** What is v1.5 *for* — personal tool, or something you intend to ship to others?
- [ ] **F-2** Ambition ceiling: is there a deadline, or is this open-ended until perfect?

### DESIGN SALVAGE (D) — the 264 diverged files
- [ ] **D-1** Salvage strategy: per-file cherry-pick / re-implement on main / abandon
- [ ] **D-2** `wt/design-shell` is a strict subset of `wt/design-other` — canonical pick
- [ ] **D-3** `feat/ui-redesign`: 759 files MAIN-AHEAD, dated 2026-06-21. Abandon?
- [ ] **D-4** 3 branch-only test functions main lacks — port them?
- [ ] **D-5** Push the 10 LOCAL-ONLY branches before touching them (single copy on this box)?
- [ ] **D-6** After salvage: delete the stale branches, or retain as archive?

### VISUAL + A11Y (V)
- [ ] **V-1** Per-spec REGEN vs FIX-CODE outcomes (pending audit evidence)
- [ ] **V-2** `aria-controls` fix scope: the one tab, or every tab in the tablist
- [ ] **V-3** Should the visual/a11y suite BLOCK (move to `quality.yml`) or stay opt-in?
- [ ] **V-4** a11y bar: serious+critical only, or include moderate?
- [ ] **V-5** Baselines are `*-win32.png` only — add linux/mac baselines?

### SIDECAR E2E (S)
- [ ] **S-1** The 3 GGUF failures: product bug (pool ordering) / CI env gap (ship a tiny GGUF) / xfail
- [ ] **S-2** Should `e2e-sidecar` block?

### BUILD + INSTALL (B)
- [ ] **B-1** Version string for this release
- [ ] **B-2** Unsigned installer — confirm (memory says signing = NONE by design)
- [ ] **B-3** Wipe order: before or after the 1.4.1 uninstall
- [ ] **B-4** Which models to re-provision post-wipe (first-run pulls GBs)
- [ ] **B-5** Retain the 1.4.1 installer as a rollback path?
- [ ] **B-6** Auto-update feed for v1.5: GitHub Releases, or disabled?

### ACCEPTANCE GATE (A) — makes "no bugs" falsifiable
- [ ] **A-1** The definitive gate list that means "done"
- [ ] **A-2** Golden-journey definition: the exact flow that must work end to end
- [ ] **A-3** Manual owner drive required in addition to CI?
- [ ] **A-4** Hold 100% coverage on sidecar + renderer?
- [ ] **A-5** OS matrix: is dropping macos-13 right, or add macos-14?

### PROCESS (P)
- [ ] **P-1** `.audit/`: gitignore, or commit as the audit trail?
- [ ] **P-2** Branch/merge strategy for the fix work
- [ ] **P-3** Re-run the 12 dead lens agents standalone, or trust the resumed workflow?

## Answers log

### B-1 — Version: **1.4.2**, not 1.5.0 (2026-07-29)

The tree still declared **1.4.1** — already shipped and tagged `v1.4.1` — so the first local
build emitted `media-studio-1.4.1-win-x64.exe`, indistinguishable from the installed app. NSIS
would treat an equal version as a repair, electron-updater would never see it as newer, and the
artifact name (`artifactName: ${name}-${version}-win-${arch}.${ext}`) mislabelled real work.

Bumped to **1.4.2** (maintenance), deliberately NOT 1.5.0: the locked v1.5 scope — 4 flagships,
keystone schema-first RPC refactor, full pro-shell redesign — is still unlanded, so a 1.5.0 tag
would tell a future reader the program shipped when it did not. What actually landed since
v1.4.1 is #304 (8 security fixes incl. the RCE write-refusal), #307 (Windows packaging unblock),
#308 (critical a11y + 8 refreshed baselines). PR **#309**.

**`app/main/brand.test.ts` pins the version on purpose** (forces conscious bumps, not drift) —
retargeted to 1.4.2 with the reasoning inline, NOT deleted. Lockfile kept in sync in both places
because CI runs `npm ci`.

⚠️ **TRAP:** a naive find/replace of `1.4.1` corrupts ~10 references to **WCAG 1.4.1**
("Use of Color") across readinessMeta / ReadinessBadge / providersKeysLogic / spendCapLogic /
schemas.ts. And `updateVerify.test.ts` holds `'1.4.1'`/`'1.4.2'` as DOWNGRADE-CHECK FIXTURES, not
as the app version. Only two sites are genuine. Use-vs-mention, again.

### V-1 — Visual baselines: **REGEN ALL 8** (2026-07-29) — RESOLVED BY EVIDENCE, not judgement

Owner asked for per-spec REGEN-vs-FIX-CODE with diff evidence. Answered with git dates
(deterministic) rather than agent opinion, per the rule that a mechanical question gets an
algorithm. **None of the 8 is a regression.**

| baselines | last committed |
|---|---|
| `create`, `director`, `repurpose`, `settings-providers-keys`, `spend-cap` | 2026-06-25 (`e38d5d3a`) |
| `library`, `settings-models-system`, `workspace-preview` | 2026-07-09 (`e85c3cbf`) |

Both predate TWO intentional, already-merged shell changes that every full-page shot captures
(6 of the 8 are `expect(win).toHaveScreenshot`, i.e. whole-shell):
- `0b652f6a` **2026-07-11** "feat: v1.5 shell — token reconciliation" (`TopTabBar.tsx`, `topTabBar.css`)
- `ffa5a607` **2026-07-18** "feat: bundle self-hosted fonts" (`App.tsx`, `tokens.css`) — added **7 real
  font binaries** (Inter Variable, IBM Plex Mono, Newsreader) + `@font-face` bindings. Before it the
  app rendered in system fallback fonts. **Every screenshot containing text necessarily differs.**

The newest baseline is 9 days OLDER than the font bundling.

**Causal chain — this was never a regression, it was invisible debt:**
1. The packaged-runtime staging step was broken -> the visual suite **never ran in CI**.
2. Shell + fonts changed intentionally (07-11, 07-18).
3. Nobody refreshed baselines because nothing was failing — the suite could not execute.
4. Fixing staging (#307) made it run for the first time -> 8 stale baselines surfaced at once.

**Mechanism:** do NOT hand-generate locally. `e2e.yml` has `workflow_dispatch` input
`update_visual_baselines=true` -> runs `test:e2e:visual:update` on the SAME Windows runner +
`RF_E2E_DEV=1` env that validates them -> uploads `updated-visual-baselines` artifact WITHOUT
committing. Regen dispatched as run `30463728543` on the a11y-fix commit `7641603f`.
(Local Windows rasterisation/DPI/GPU can differ from the CI runner, so baselines must be born
where they are checked.)

### F-1 — Purpose: **PERSONAL TOOL, owner only** (2026-07-26)
Not shipped to others. Downstream consequences now BINDING on every later decision:
- **a11y** = a CI-gate obligation, not a user-exclusion or legal one. Fix `critical` (the gate
  demands it and it is cheap); do NOT chase `moderate` findings.
- **Visual baselines** = regressions detectors for the owner's own eye, not contracts. REGEN is
  acceptable wherever the evidence says the UI changed intentionally.
- **Design salvage** = scoped to what the OWNER will notice in use. A diverged file whose only
  delta is invisible in normal operation is not worth hand-merging.
- **Signing** stays NONE (already by design). No SmartScreen concern to solve.
- **First-run** only has to survive THIS machine + an empty `D:\Reframe\data`.
- Commercial-model license manifest is not binding for personal use, but it is an existing repo
  invariant with tests — do NOT relax it unilaterally as part of this work.
