# Reframe UI/UX + QOL Audit — 2026-08-08

> **Status:** ACTIVE

**Auditor:** uiux subagent (Opus 5). **Mode:** READ-ONLY on app source — drove + inspected, never edited.
**Target:** `D:\Program Files\Reframe\Reframe.exe` launched with `--force-renderer-accessibility`, pid 17292.
**Method:** Windows UI Automation (`AutomationElement.FromHandle`) for the control tree + actuation;
`PrintWindow(flag=2)` window-scoped screenshots with a distinct-colour assert; repo source read for
corroboration. **All 8 rail destinations and all 8 Settings sub-tabs were ACTUATED, not merely read.**

**Honesty contract:** UNVERIFIED sits inline next to the claim it qualifies, naming the settling
experiment. A control never actuated is `NOT-CHECKED`, never "works".

> **READ THIS BEFORE ACTING ON ANY FINDING — reconciled 2026-08-10 against the tree at `db61ea6e`.**
> This is an audit of the build as it stood on **2026-08-08**, and part of it has been fixed since. The
> observations are preserved rather than rewritten (an audit that edits its own history stops being
> evidence); each superseded one now carries a dated `SUPERSEDED`/`FIXED`/`Correction` note *inline*.
> What changed: **C2, H1 and M7 are FIXED**; **H2 keeps its conclusion but lost its grounding** — §4.1's
> "no `Menu`" is now false, and `app/main/appMenu.ts:4` cites this very section as the reason it was
> written; **M3's** four-treatment count survives with its taxonomy now spelled out, because the prose
> disagreed with §1's own table; **M6 was four surfaces, measured six**; and **every `file:line` in
> §4.5 had drifted** (`views/Shorts.tsx:147` and `features/useShortsGallery.ts:99` are no longer confirm
> sites at all). Cite the SYMBOL, not the line — three of the four anchors in that cluster rotted within
> two days, which is the durable lesson here.

## COVERAGE

| Section | Status |
|---|---|
| 0. Ground truth / instrument corrections | MEASURED |
| 1. Rail destinations (8/8 actuated) | MEASURED |
| 2. Settings sub-sections (8/8 actuated) | MEASURED |
| 3. Design-system conformance | MEASURED (live geometry + source; no computed-style access) |
| 4. QOL sweep | MEASURED for menus/shortcuts/jobs/drag-drop/confirmations; media flows NOT-CHECKED |
| 5. Ranked findings | MEASURED |
| 6. Evidence anchors | MEASURED |

**Biggest coverage hole:** the Library is empty, so no end-to-end media flow was exercised. Everything
about actually producing a Short is `NOT-CHECKED`. I deliberately did not add media — that would mutate
the owner's library. **A first-run walkthrough with one real video is the single most valuable follow-up
and nothing below substitutes for it.**

## 0. Ground truth and instrument corrections

Two premises in my brief were wrong, and four of my own probes were wrong. Recording all six because a
reader who trusts my first pass would be misled.

1. **The app was NOT running when I started.** `Get-Process -Name Reframe` and
   `Get-CimInstance Win32_Process -Filter "Name='Reframe.exe'"` both returned empty (two mechanically
   independent probes). I launched it.
2. **`docs/build/DESIGN-DIRECTION.md` is stale.** Its own line 3 reads *"Status: SUPERSEDED BY
   docs/design-system.md (2026-08-08)"*, it is titled "media-studio", and
   `app/renderer/src/styles/tokens.css:103` calls its `system-ui`/`Georgia` fonts and `#08090b` ladder
   **stale**. I judged the app against `docs/design-system.md` (ACTIVE), citing the older doc only where
   the newer one restates the same intent.

   > **RESOLVED 2026-08-12 (measured at `1fa9a69f`).** True when written; no longer true. That doc's
   > palette values are deleted and its font bullets corrected, and the class is pinned by
   > `C8-colour:*` / `C8-binding:*` in `docs/validation/tools/verify_ssot_claims.py`. The finding is
   > kept rather than deleted so a later reader inherits the resolution instead of re-deriving the
   > defect. **Two citation defects in the sentence above, recorded because this repo has been bitten
   > by both before.** (a) `tokens.css:103` is a bare line number into a file that moves: the sentence
   > it points at spans `:101-110` today and the anchor survived only by luck. Cite the SYMBOL
   > (`--font-ui` / `--font-editorial`) or a FIXED commit. (b) That comment never mentions the ladder
   > at all — it supersedes the `system-ui`/`Georgia` font leads only — so attributing the `#08090b`
   > verdict to it was a real over-attribution. The ladder claim was independently true; its evidence
   > is the value comparison against `tokens.css`, not that comment.

**My detector failures, and what each nearly caused me to report:**

| My wrong reading | Broken probe | What corrected it |
|---|---|---|
| "Make Shorts renders the Library panel" (a routing bug) | UIA tree read 1400 ms after the click — Chromium updates the a11y tree asynchronously | the screenshot moments later showed Make Shorts correct. Rewrote the dumper to block until the expected `tabpanel-*` is live (settle 319–856 ms). **No routing bug exists.** |
| "Jobs / Capabilities have no actuation pattern" | my click script only tried Invoke/SelectionItem/Toggle | both are `ExpandCollapse`. Added it; both actuate fine |
| "DONE jobs render white, not green" | eyeballing a compressed PNG; then a pixel sampler that returned an identical surface colour for visually different regions — a self-contradicting output, so a broken instrument | `jobqueue.css:214-216` — `.jobqueue__status--done { color: var(--status-success) }`. **The CSS is correct; I withdraw this finding** |
| "the app has no destructive-action confirmations" | grepped `window.confirm` | the code used `globalThis.confirm` (`Library.tsx:480`) *as audited* — W04 has since replaced it with the themed gate, see the §4.5 correction. **Confirmations do exist**; see §4.5 |

One further transient: a whole script run returned `matches=0` for every control including a known-present
one, from a valid window handle — the renderer a11y tree had dropped. All affected steps were re-run after
adding a canary self-check that refuses to report an absence unless a known control is simultaneously
visible. No finding below rests on that run.

## 1. Rail destinations — all 8 actuated

| Destination | Empty state | CTA offered | Notes |
|---|---|---|---|
| Library | ghost-poster + "No videos yet" | **Add videos** (amber) | Search + Sort render live on 0 items; accepts file drops |
| Make Shorts | ghost-poster + "No video selected" | `Select a video…` combo | sub-tabs MAKE / PRODUCED SHORTS / BATCH & TEMPLATES |
| Edit | "No video open" + prose | **none** | dead end — no way forward from the screen |
| Caption | "Open a video to caption" | `← Library` | |
| Export | "Open a video to export" | `← Library` | |
| Deliver | per-section prose | `← Library` | unstyled `fieldset`; 23×20 px native `select` |
| Director | ghost-poster in a card | **Choose a video** + `What is Director?` | title in the editorial serif (§3.1) |
| Settings | n/a | n/a | 8 sub-tabs, all actuated |

**Four different CTA treatments for the same "you need media" state**, taxonomy stated so the count is
checkable against the table above rather than taken on trust: a **primary button** (Library's amber
*Add videos*, Director's *Choose a video*), a **combo** (Make Shorts), a **`← Library` back-link**
(Caption, Export, Deliver), and **nothing at all** (Edit). Edit offering *nothing* is the worst case.

> **Correction 2026-08-10.** The parenthetical here used to read "(amber button / combo / nothing /
> `← Library`)", which omitted Director even though the row above gives Director its own CTA — so the
> doc's prose and its own table disagreed on how the four were reached, and a reader recounting from
> the table got five. The count of four survives; only the enumeration was incomplete. Grouping
> Director's *Choose a video* with Library's amber button is a taxonomy CHOICE, now written down
> instead of left implicit. **UNVERIFIED that eight live destinations still present exactly these four
> treatments** — that was measured by actuation on 2026-08-08 and nothing re-drives the app on commit.
> Settling experiment: re-run the §0 UIA walk over all 8 rail destinations and re-derive the table.

## 2. Settings sub-sections — all 8 actuated

All 8 actuated against the real preload bridge, each panel's own `tabpanel-*` node verified live. No
degraded or error state observed.

**Best-executed surfaces:** SETUP (green summary banner + 5 PASS rows on left-rail status) and SYSTEM
HEALTH (tracked-caps section labels, consistent rows, semantic green). These match the design system
closely and should be the template for the rest.

**Content taller than the 673 px viewport, primary action below the fold:** CAPTION DEFAULTS is 952 px
tall and its **`Save defaults` button sits at y=1198** — the panel's only commit action, with no sticky
footer. SYSTEM HEALTH (887 px) and PROVIDERS & KEYS also push content offscreen.

## 3. Design-system conformance (vs `docs/design-system.md`, ACTIVE)

### 3.1 The editorial serif has spread to 15 sites (documented limit: 1)

`docs/design-system.md:49` — "Georgia editorial serif (ShortMaker hook pull-quotes **ONLY**)". The
superseded doc was blunter: *"ONE place only … do not spread it."*

`--font-editorial` is referenced in **15** stylesheets. The clearest case is visible on screen:
`app/renderer/src/views/director.css:48-56` sets `.director-view__title` to `--font-editorial` at
`--type-display-size` (30 px) — a **view title**, not a 15 px italic pull-quote. The comment at
`director.css:47` calls it "the editorial moment", so the spread is deliberate in code and simply never
reconciled with the SSOT. Others: `caption.css:96`, `export.css:94`,
`features/export/export.css:277,454`, `features/caption/captionStage.css:88`, `captionInspector.css:24`,
`captionGallery.css:29`, `components/library-shell.css:232`, `components/firstRunSetup.css:40`,
`components/profilePicker.css:31`, `components/shell.css:1480`, `features/lineage.css:71`,
`features/director/directorHandoff.css:21`, plus the sanctioned `views/shorts.css:336`.

`docs/design-system.md:6` says `tokens.conformance.test.ts` guards "one-accent discipline" — it evidently
does **not** guard serif rationing. **Fix:** add a conformance test capping `--font-editorial` usage, or
amend the doc to the real intent. Today doc and code disagree and nothing detects it.

### 3.2 Accent rationing is exceeded on every screen

`docs/design-system.md:30` — "Rationed: **at most one accent touchpoint per surface**." On Settings ›
MODELS & SYSTEM I count ≈**7**: brand tick, `AI MODEL: Local` ring, `WHERE JOBS RUN: Local` ring, Settings
rail item, active sub-tab underline + text, `Analyze my system` fill, `Privacy / offline` card border +
`ACTIVE` chip.

UNVERIFIED — whether "surface" means *screen* or *region*. Under a per-region reading the header alone
still carries 2, so the rule is exceeded either way, but severity depends on the reading. Settling
experiment: have the design owner fix the unit, then encode it as a conformance test counting
accent-valued declarations per component.

### 3.3 Two label voices coexist, sometimes on one screen

`docs/design-system.md`'s `## Type` table defines the `--type-caption-size` role — caption 11 px/600
tracked CAPS — as *the* label voice.

> **CORRECTED (2026-08-12) — cited by SYMBOL, not by line.** This sentence cited
> `docs/design-system.md:43`, which was byte-exact at `1fa9a69f`, until a 9-line retraction
> inserted at that file's `:34` pushed the caption row down to `:52` and left the citation
> resolving onto a line of the retraction itself. Fifth bare-same-file-line-range rot in this
> corpus, and the first caused by the very pass that wrote the no-bare-line-ranges rule down.
> `C13-anchor` now fails on any `docs/*.md:N` citation that resolves onto a `>` line. Scope,
> stated rather than implied: it catches only the *retraction-line* subclass, and it skips
> blockquotes, so this note is invisible to it. Three anchors in this file (`:49`, `:65-66`,
> `:78-81`) rotted onto ordinary lines BEFORE this branch and are untouched — they need a
> sweep that re-derives each true anchor, which this pass did not do.

Honoured on
Library (`SORT`), the header (`AI MODEL`) and most Settings headings — but Deliver renders `Sources` and
`Template` as sentence-case body text, Make Shorts renders `Video`, EXPORT PRESETS renders `Save current
settings as`, and MODELS & SYSTEM mixes a sentence-case `OpenRouter spend` heading among tracked-caps
siblings.

### 3.4 Native form controls leak through the design system

Measured from live bounding boxes — a clean discriminator, since styled controls render 32–33 px tall and
raw native ones 20 px:

- **Styled (8):** `Sort videos` 132×33 · `#asr-engine` 452×32 · `#diarize-backend` 452×32 ·
  `#fn-select`/`#fn-subtitles`/`#fn-translation`/`#fn-vision`/`#fn-editPlan` 389×33.
- **Raw native (3):** Deliver `Template` **23×20** · `#prefs-subtitle-mode` 98×20 ·
  `#:r1:` Default language 94×20.

Deliver's `Template` at **23 px wide** is the worst — a bare caret with no room for a value. The cause is
structural: there is no global `select` rule. `app/renderer/src/views/makeShorts.css:34` styles
`.make-shorts__picker select` with `appearance:none` and a hand-drawn caret; every other select is styled
ad hoc or not at all. This is the same feature-namespaced-selector debt `docs/design-system.md:65-66`
already admits for buttons, unacknowledged for selects.

Deliver also renders an **unstyled `<fieldset>`** ("Sources") with a default notched legend and a
full-strength grey border — against "depth via TONE … borders almost eliminated"
(`docs/design-system.md:13`, anti-template gate #3).

Checkboxes split the same way: `COMMERCIAL USE` 23×17 and `#spend-cap-enforce` 22×17 vs
`#prefs-caption-polish` / `#prefs-caption-speakers` at **13×14**. All fall under the WCAG 2.5.8 AA 24×24
target minimum. UNVERIFIED whether the associated label extends the hit target (which would satisfy the
exception) — settling experiment: click the label text, not the box, and watch for a toggle.

### 3.5 What the design system gets right

Worth protecting: the shared ghost-poster empty state (deep 16:9 well, play glyph, mono `--:--` timecode)
on Library / Make Shorts / Director; the surface ladder and near-total absence of borders on Library,
Settings and Health; the mono tabular voice for versions, paths and timecodes; the double focus ring,
which rendered visibly on every rail item I actuated; SETUP and SYSTEM HEALTH's status treatments; and 17
caption-style presets with visual `Aa` previews.

## 4. QOL sweep

### 4.1 The app shipped Electron's stock menu — no application-level shortcuts

> **SUPERSEDED 2026-08-10 — signal (a) is now FALSE; this section describes the pre-fix build.**
> A real application menu has since landed, and it cites *this section* as its reason
> (`app/main/appMenu.ts:4` — "docs/plans/v1.5/uiux-qol-audit-2026-08.md §4.1, §5"). Re-measured:
> `app/main/main.ts:13` now imports `Menu`, `:14` imports `buildAppMenuTemplate`, `:1562` calls
> `Menu.setApplicationMenu(Menu.buildFromTemplate(buildAppMenuTemplate({ isDev })))`, and
> `app/main/appMenu.ts:62` builds the template (File · Text · View · Window · Help). So
> `setApplicationMenu`/`buildFromTemplate` DO now exist under `app/`. Detector control for that
> re-measure — **BOTH-STATES, ONE scope, and the scope is stated**: over every tracked *non-test*
> `.ts`/`.tsx` under `app/`, the matcher `setApplicationMenu|buildFromTemplate|accelerator` returns
> **0× at the parent of the commit that added `appMenu.ts`** (`5d99bd2e`) and **3× at that commit and
> still at HEAD** (`appMenu.ts:25`, `main.ts:1562` ×2), while the known-present `BrowserWindow` reads
> **25× in all three** — so the matcher fires only in the state it should, and its file walk is intact
> in both states.
> **The control this paragraph carried before was fabricated, and is REFUTED:** it paired
> `BrowserWindow` **25×** with **11** alternation hits, and *no single scope yields both* — 25 requires
> tests EXCLUDED (with tests the same matcher counts 41), while 11 requires them INCLUDED (without
> tests it is 3). 9 of those 11 sit in `appMenu.test.ts` — **REFUTED, this said 8**: re-measured at
> `81a04965` the with-tests reading is 11 matching LINES (12 occurrences), of which the two
> non-test lines are `appMenu.ts` and `main.ts` and the remaining **nine** are all in
> `appMenu.test.ts` (`:6 :11 :84 :85 :88 :90 :93 :145 :146`); the last two are the
> `expect(src).toMatch(/Menu\.setApplicationMenu\(/)` pair, which an `accelerator`-only reading
> misses. The correction does not move the verdict — it makes the arithmetic close. Note the two
> units in this sentence are not the same: `3` counts OCCURRENCES (on 2 lines) and `11` counts
> LINES. The refutation stands under either unit, because the 25-scope yields 3/2 and never 11.
> Its `accelerator` matches assert the
> attribute's ABSENCE (`:93 expect(item.accelerator).toBeUndefined()`) — cited as evidence of a
> non-empty production reading while asserting the opposite. A pair stitched from two scopes is a
> detector failure, not a control. Consequences below: **C2 and H1 are fixed** (no `Edit` menu at all — the items are
> `Text ▸ Undo typing`/`Redo typing`, and the dev View items are gated on `isDev = !app.isPackaged`);
> **H2's conclusion narrowly survives** — a menu exists, but `appMenu.ts:25-34` deliberately sets NO
> `accelerator` on any item (an explicit one overrides the role's per-platform default), so the app
> still adds no `Ctrl+O`/`Ctrl+,`/`Ctrl+E` of its own. The observation is preserved rather than
> rewritten: this is an audit of a dated build, and the finding is what triggered the fix.
>
> **Re-verified independently at `81a04965`.** The replacement control reproduces exactly. The
> scope that yields the stated pair is the literal one written above — every tracked `.ts`/`.tsx`
> under `app/` with `.test.` excluded, which keeps `app/e2e/*.spec.ts` and `app/vitest.config.ts`
> in. Enumerated glob-free (`git ls-tree -r` + `git cat-file --batch`, filtering in code) rather
> than by pathspec, because `git grep -- 'app/**/*.ts'` silently drops `app/vitest.config.ts` and
> reads **23** instead of 25 — git pathspec needs `:(glob)` magic for `**`, and
> `:(glob)app/**/*.ts` does read 25. (**REFUTED, kept: this sentence first said "reads 21".** It
> paired a one-file cause with a three-file number — 21 comes only from `app/main/*.ts`, which
> additionally drops `app/e2e/preview.spec.ts` and `app/e2e/visual/_visualSetup.ts`, two files
> the scope sentence above explicitly keeps IN. `app/vitest.config.ts` holds 2 occurrences, so
> the route it does drop reads 25 − 2 = 23. That is verbatim the failure this paragraph refutes
> above — "a pair stitched from two scopes is a detector failure, not a control" — committed
> inside the sentence certifying that the fix for it reproduces. The verdict figures are
> untouched: 0 / 3 / 3 and 25 / 25 / 25 both reproduce.) Measured:
> matcher 0 / 3 / 3 occurrences and `BrowserWindow` 25 / 25 / 25 across `5d99bd2e^` / `5d99bd2e` /
> HEAD. The both-states property therefore holds, and the known-present control is flat across all
> three revisions, which is the property that proves the file walk did not change under it.

Two independent signals: (a) `app/main/main.ts:13` imports `app, BrowserWindow, ipcMain, net,
safeStorage, session, shell` — **no `Menu`**, and no `setApplicationMenu`/`buildFromTemplate`/`accelerator`
anywhere under `app/`; (b) a desktop capture of the open menus shows exactly the Electron defaults:

- **View:** Reload `Ctrl+R` · Force Reload `Ctrl+Shift+R` · **Toggle Developer Tools `Ctrl+Shift+I`** ·
  Actual Size `Ctrl+0` · Zoom In/Out · Toggle Full Screen `F11`.
- **Edit:** Undo `Ctrl+Z` · Redo `Ctrl+Y` · Cut/Copy/Paste · Delete · Select All.

Consequences: DevTools and Force Reload are exposed in a production consumer build; `Edit ▸ Undo` is a
text-field role in an app whose rail has a dedicated **Edit** destination; and there is no `Ctrl+O`,
`Space`, `I`/`O`, `Ctrl+E` or `Ctrl+,`.

**Scoped precisely:** *per-widget* keyboard support does exist and is reasonably broad — 48 key-handler
occurrences across 16 renderer components, concentrated in `TabBar.tsx` (10), `TopTabBar.tsx` (6),
`DirectorPanel.tsx` (6), `CandidateReview.tsx`, `CaptionClipLane.tsx`, `ShortMaker.tsx` (3 each). CAPTION
DEFAULTS' caption-region widget is fully keyboard-operable — accessible name *"Caption region — arrow keys
move; Tab to a handle then arrow keys to resize"*, with 8 named resize handles as real buttons. **The gap
is global accelerators only**, not keyboard support in general.

UNVERIFIED whether a running job survives `Ctrl+R` — settling experiment: start a long export, press
`Ctrl+R`, observe whether the job continues and whether the UI recovers its progress.

### 4.2 A cancelled job is an unremovable, unactionable dead row

Actuated: the Jobs slide-over holds four boot-time entries, all labelled identically (`assets` /
`assets.ensure`) — three DONE 100%, one **CANCELLED at 2%** with no button of any kind. That is by
construction:

- `canCancel('cancelled')` → false (`JobQueue.test.tsx:115`)
- retry applies to **error only** (`JobQueue.test.tsx:118-119`)
- `canResume` = `status === 'interrupted'` only (`JobQueue.tsx:41-43`)
- `JobQueue.tsx` contains **no** clear/dismiss/remove path (the only match for "clear" is `clearInterval`)
- `jobqueue.css` defines colours for `--running`/`--error`/`--done`/`--interrupted` but **not**
  `cancelled`, so it falls through to `--text-muted`

The queue is also rehydrated from disk across sidecar restarts (`JobQueue.tsx:36-37`), so these rows are
durable. Net effect: finished and cancelled jobs accumulate permanently, indistinguishably labelled, with
no user control. **Fix:** add a `cancelled` status colour, allow retry-from-cancelled (or say why not), and
add "Clear finished".

**Credit where due:** resumability is real and honestly labelled. `RESUME_TITLE`
(`JobQueue.tsx:51-54`) tells the user it *"restarts at 0%, not where it stopped"* and that a cloud
provider will re-ask for budget confirmation. That is exactly the right register; generalise it.

### 4.3 Controls that are live but cannot do anything

Library **Search videos** and **Sort videos** render enabled on 0 items. Deliver's `Template` select is
empty and 23 px wide; `Run batch` is correctly `[DISABLED]`, but the screen stacks *three* separate
blocked-state messages. EXPORT PRESETS offers **"Save current settings as"** with no indication of *which*
settings are captured — the panel shows no export setting at all — and its name field stretches ~810 px
with placeholder-as-label.

### 4.4 Jargon and help affordances

`Capabilities: 10 of 11 installed` (Library) — I actuated it: expanded, it **does** name the gap
(`Multimodal (visual + audio + transcript)` → `NEEDS DOWNLOAD` + a Download button). So the information
exists; the defect is narrower than it looks — the collapsed chip gives no hint that anything is
actionable, and its Download button sits at the far right edge where the Jobs slide-over overlaps it.
`Lineage view`, `PRO HANDOFF`, `DIARIZATION BACKEND`, `Instant numeric`, `Video-LLM re-rank` and
`dover-mobile-quality` carry no tooltip. `What is Director?` is the only explicit help affordance I found.

### 4.5 Destructive actions: guarded, but (as audited) by an unstyled native dialog

> **SUPERSEDED 2026-08-10 for the FIRST residual; the second still stands. Every `file:line` in this
> section had also drifted.** Re-measured:
>
> * **The native dialog is gone (W04)** — but the probe that first "proved" it measured nothing, so
>   the evidence below is a different probe. The destructive gate is now the themed `useConfirm` hook
>   (`components/ConfirmDialog.tsx`, imported at **5 production sites**: `features/ExportPresetsPanel.tsx`,
>   `features/Tracks.tsx`, `features/useShortsGallery.ts`, `views/Library.tsx`, `views/Shorts.tsx`).
>   **REFUTED — "17 import sites" was wrong by 3.4×**: `17` is the raw `useConfirm` occurrence count
>   across 7 files, which includes the hook's own definition (3) and its test (4); the import
>   statements number 6, of which 5 are production. A reader sizing the migration's reach was handed
>   the wrong quantity, in a section whose whole subject is wrong quantities.
>   **And the stated control was invalid — it failed the both-states test.** A
>   `globalThis\.confirm\(`/`window\.confirm\(` matcher returns **0 in the BROKEN state too**, because
>   pre-W04 the six sites were spelled `(globalThis as { confirm?: … }).confirm?.(` — an optional call
>   behind a cast. Measured over the same one scope (tracked non-test `app/renderer/src/**` `.ts`/`.tsx`)
>   at `a44ba906`'s parent and at HEAD: the naive matcher reads `0 / 0` (it measures nothing), while a
>   matcher that allows the cast and `?.(` reads **6 pre-fix → 0 post-fix**, and the 6 sites it names
>   are exactly the ones W04's own commit message claims to have replaced. Six native sites across five
>   files is also why the import count is 5. **M7 is therefore FIXED**, on that second probe, and the
>   "≈95% confidence" native-styling claim is moot.
> * **The line numbers below are stale — cite the SYMBOL, not the line.** Measured today, the confirm
>   sites are `Library.deleteShort` (`views/Library.tsx:474`, `confirm(` at `:488`),
>   `Shorts.handleDelete` (`views/Shorts.tsx:156`, `confirm(` at `:161`) and
>   `useShortsGallery.deleteShort` (`features/useShortsGallery.ts:106`, `confirm(` at `:111`). The cited
>   `views/Shorts.tsx:147` is now `client.package.export(...)` and `useShortsGallery.ts:99` is a `catch`
>   in the *re-export* handler — neither is a confirm site, so following either anchor lands a reader on
>   unrelated code. `KeepCopyControl.tsx:21` is still exact (and the file is at
>   `app/renderer/src/features/`, not `components/` — my first probe looked in the wrong directory and
>   briefly read as "the file is deleted"; the `git ls-files` cross-check corrected it, which is why the
>   full path is spelled out here).
> * **The second residual is real and its anchor moved by one:** the *"the adapter owns any confirm"*
>   contract comment is at `Library.tsx:54` (on `remove`), not `:53` (now `openFolder`).
>
> The three stale line numbers are a *class*, not three typos: a line number in prose rots on the next
> edit above it, and nothing checks it. The same four confirm-site comments in the source carry the same
> stale anchors — see the residual list in this unit's report; they are outside this lane's file scope.
>
> **Re-verified independently at `81a04965`, and this is the sharper of the two controls.** Every
> figure reproduces: naive matcher `0 / 0` at `a44ba906`'s parent and at HEAD (it measures nothing,
> as claimed); cast-aware matcher **6 → 0**, the six being `features/ExportPresetsPanel.tsx` ×2,
> `features/Tracks.tsx`, `features/useShortsGallery.ts`, `views/Library.tsx`, `views/Shorts.tsx` —
> six sites across the same five files as the five production imports, so the two figures do
> reconcile; `useConfirm` raw occurrences 17 across 7 files; import statements 6, of which 5
> production. A `useState` control reads 530 / 532 / 597 across the three revisions, so the file
> walk was alive in the broken state too — without that, a `0` pre-fix could not be told from an
> empty walk. And a caution earned the hard way in the re-verification: the cast-aware matcher must
> be built from the ACTUAL pre-fix bytes. My first attempt used `[^)]{0,80}` between `globalThis`
> and `.confirm`, which cannot cross the parens inside the cast type
> `{ confirm?: (m: string) => boolean }`, so it read **0 pre-fix** and briefly looked like a
> refutation of this paragraph. It was a broken matcher of mine — the same failure class this
> paragraph documents, reproduced while checking it. The matcher that works is the plain
> `\.confirm\?\.\(`.

Confirmations exist. `app/renderer/src/views/Library.tsx:470-483` calls `globalThis.confirm(...)` before
`shorts.delete`, and its comment records that this surface was *the* unguarded one because "four separate
comments each delegated the confirm to another layer and it landed nowhere", naming the standard at
`KeepCopyControl.tsx:21` — *"never a silent one-click destructive action"* — and two sibling call sites
(`views/Shorts.tsx:147`, `features/useShortsGallery.ts:99`).

Two residual issues. First, `globalThis.confirm` renders **Chromium's native dialog**, which app CSS
cannot theme — so the app's only destructive-confirm modal is visually foreign to the dark-editorial
system (≈95% confidence; a native `confirm()` is not styleable in Electron). Second, the
`LibraryShortsApi.remove` contract at `Library.tsx:53` still documents *"the adapter owns any confirm"* —
the exact delegation the comment at `:478` identifies as having previously failed, so the class can recur.

NOT-CHECKED: whether the *other* destructive paths (remove a provider key, Change data folder, delete a
managed copy) confirm. I could not reach them without media/keys.

### 4.6 Drag-and-drop is Library-only

Implemented at `Library.tsx:309,321,510,512` via `webUtils.getPathForFile` (`preload.ts:340`), with real
tests for edge cases. No other surface accepts a drop, and **six** of the other seven rail destinations
gate on having media: Make Shorts, Edit, Caption, Export, Deliver and Director (Settings is the only
one that does not). A user dragging a file onto Edit gets nothing.

> **Correction 2026-08-10 — the count and the quote were both wrong.** This paragraph named only four
> surfaces (Edit / Caption / Export / Director) and asserted their empty states "all say *Pick a video
> from the Library*". Measured against the §1 table above and against source: the media-gated set is
> **six**, not four — Make Shorts and Deliver were omitted while appearing in the very table this
> section builds on. And that quoted string is exact for only **two** of them: `views/Caption.tsx:100`
> and `views/Export.tsx:277` say "Pick a video from the Library to …"; the other **four** say something
> else entirely — `views/Edit.tsx:181` "No video open", `views/MakeShorts.tsx:433` "No video selected",
> `panels/DirectorPanel.tsx:561` "No video open", and `views/Deliver.tsx:83` "Open a video from the
> Library to hand its clips off to Premiere or DaVinci Resolve." Attributing one uniform sentence to
> four surfaces made the finding sound tidier than the evidence, and would have sent a fixer grepping
> for a string that four of them never render. **M6 is restated to six below.**
>
> **A correction inside the correction, recorded rather than quietly patched:** the first version of
> this paragraph enumerated only three of the four non-matching surfaces — it dropped **Deliver**,
> which is the *same* omission it exists to correct, one sentence later. Deliver is restored above.
> Anchor discipline: the quoted STRING is the durable anchor in each of these six citations; the line
> number is a convenience that rots, so grep the string if it does not land.

### 4.7 Aggregate health verdicts contradict their own detail

SYSTEM HEALTH prints **"Setup OK"** and `ML BACKENDS (7/8)` while listing `kokoro (TTS) not installed`,
and reports `llama-server available` under ENGINES while `llama (CUDA)` and `llama (CPU)` both read
`empty` under MODEL & CACHE PATHS on the same page. UNVERIFIED whether those are genuinely optional —
settling experiment: run a TTS/dub job and a local-LLM job and see whether either fails against a page
that said OK. SETUP and SYSTEM HEALTH also substantially duplicate each other.

## 5. Ranked findings

### CRITICAL — blocks a task

**C1. Settings ▸ MODELS & SYSTEM opens scrolled ~503 px down, hiding its own title and the entire
capability list.** Reproduced on two independent fresh entries (Library→Settings, and HEALTH→MODELS): the
`Models & System` heading reports `y = -258` both times, while the control panel SYSTEM HEALTH reports its
heading at `y = +269`. Lost above the fold: `WHAT WORKS RIGHT NOW` and the **only**
`Download the Multimodal (visual + audio + transcript) model` button — the one control a new user needs to
enable multimodal moment-finding. This is the default Settings tab, so it is the first thing seen.
Fix: `app/renderer/src/panels/ModelsSystemPanel.tsx` — scope the mount-time `scrollIntoView`/`focus()`, or
reset `scrollTop` on tab activation. UNVERIFIED — the exact triggering call; inferred from the reproducible
offset. Settling experiment: `Ctrl+Shift+I`, log `scrollTop` on the panel's scroll container.

**C2. `Edit ▸ Undo (Ctrl+Z)` promises an undo the app does not have.** Stock Electron text-field role in an
app with a dedicated Edit destination. Fix: `app/main/main.ts` — install a real `setApplicationMenu` and
either wire Undo to a genuine edit-history stack or remove the item.
**FIXED 2026-08-10** — `app/main/appMenu.ts` ships no `Edit` menu at all; the working text roles moved to
a `Text` menu labelled `Undo typing` / `Redo typing`, installed at `main.ts:1562`. (§4.1 correction.)

### HIGH

**H1. DevTools + Force Reload shipped to end users** (§4.1). Gate the dev items behind `!app.isPackaged`.
**FIXED 2026-08-10** — `appMenu.ts:47,91` puts Reload / Force Reload / DevTools behind
`isDev = !app.isPackaged`; Zoom and full screen stay in both builds.
**H2. No application-level keyboard shortcuts** (§4.1) — add `Ctrl+O`, `Ctrl+,`, `Ctrl+E`, and renderer
`Space` / `I` / `O`.
**STILL OPEN 2026-08-10, but re-grounded** — an application menu now exists, so the original grounding
("no `Menu`", "no `setApplicationMenu`") is false; the *conclusion* survives because `appMenu.ts:25-34`
deliberately sets no `accelerator` on any item, so the app still contributes no shortcut of its own.
**H3. Two identical `Analyze my system` buttons on one panel.** `ModelsSystemPanel.tsx:799-804` (toolbar,
label cycles `Analyzing…`/`Re-analyze`) and `:842-847` (`empty-state__cta`), both calling the same
`analyze()`; measured live at `552,161` **and** `576,326`. C1 currently hides the first, so **the two
defects mask each other** — fixing C1 alone makes the duplicate visible.
**H4. A cancelled job cannot be retried, cleared, or even coloured** (§4.2).
**H5. Deliver leaks unstyled native HTML** — a raw `<fieldset>` and a 23×20 px `Template` select (§3.4).
Add a global `select` rule to the token layer; replace the fieldset with a raised card.
**H6. `EXPORT PRESETS ▸ Save current settings as` gives no idea what will be saved** (§4.3).
**H7. The editorial serif is used in 15 places against a documented limit of 1** (§3.1), undetected by the
conformance suite that already guards the accent.

### MEDIUM

**M1.** Primary actions below the fold with no sticky footer — CAPTION DEFAULTS' `Save defaults` (§2).
**M2.** `Edit`'s empty state offers no action at all — the only one of 8 with no way forward.
**M3.** Four different CTA treatments for the same "you need media" state — primary button (Library,
Director) / combo (Make Shorts) / `← Library` back-link (Caption, Export, Deliver) / nothing (Edit). The
taxonomy is spelled out because the bare number disagreed with §1's own table (§1).
**M4.** Accent rationing exceeded on every screen (§3.2).
**M5.** Two label voices, sometimes on one screen (§3.3).
**M6.** Drag-and-drop works only on Library, while **six** other rail destinations gate on having media —
Make Shorts, Edit, Caption, Export, Deliver, Director (§4.6). Was written as "four": Make Shorts and
Deliver were omitted despite appearing in §1's table.
**M7.** Destructive confirmation uses an unthemeable native `confirm()` dialog (§4.5).
**FIXED 2026-08-10** — W04 replaced it with the themed `useConfirm` gate; `globalThis.confirm` /
`window.confirm` now appear zero times in non-test renderer source (§4.5 correction).
**M8.** Search + Sort live on an empty Library; three stacked blocked-state messages on Deliver (§4.3).
**M9.** `AI MODEL` vs `WHERE JOBS RUN` remain near-identical twins — same Local/Cloud vocabulary, same
visual treatment, adjacent. `docs/design-system.md:78-81` records this as already "disambiguated (v1.4)"
via a seam divider; the seam is present, but they still read as one duplicated control. Distinguish by
form, not only by label.
**M10.** `last checked 575m ago` — raw minutes instead of a humanised interval.
**M11.** Health verdicts contradict their own detail rows; SETUP and SYSTEM HEALTH duplicate (§4.7).
**M12.** The collapsed `Capabilities` chip hides an actionable download behind a click with no hint (§4.4).

### LOW

**L1.** Checkbox hit targets 13×14 px, under the WCAG 2.5.8 AA 24×24 minimum; label-extension unverified.
**L2.** `REQ LIMITS` renders a full-width bar for `0 req` — a full bar reads as 100%. UNVERIFIED whether
the element is a fill or an empty track; settling experiment: inspect the `<meter>` value/max in DevTools.
**L3.** Placeholder-as-label on the preset-name field.
**L4.** `← Library` back buttons on sibling rail destinations mix a hierarchical affordance into a flat rail.
**L5.** `LibraryShortsApi.remove`'s "the adapter owns any confirm" contract (`Library.tsx:54` — cited as
`:53` until 2026-08-10; `:53` is now `openFolder`) preserves the delegation pattern that already failed
once (§4.5). **STILL OPEN** — the comment is unchanged; only the anchor moved.

## 6. Evidence anchors

1. **Screen · control:** Settings ▸ MODELS & SYSTEM, `Models & System` heading — UIA reports `y = -258` on
   two fresh entries; the SYSTEM HEALTH control reports `y = +269`. (C1)
2. `app/renderer/src/panels/ModelsSystemPanel.tsx:799-804` and `:842-847` — two buttons, one `analyze()`.
3. `app/renderer/src/views/director.css:48-56` — `.director-view__title` uses `--font-editorial` at
   `--type-display-size`; `docs/design-system.md:49` says pull-quotes ONLY.
4. `app/main/main.ts:13` — electron import list contains no `Menu`; no `setApplicationMenu` under `app/`.
   Corroborated by a desktop capture of `View` showing `Toggle Developer Tools  Ctrl+Shift+I`.
5. **Screen · control:** Deliver ▸ BATCH PUBLISH, `Template` select — live bounding box **23×20 px** vs
   styled peers at 32–33 px; no global `select` rule exists (`views/makeShorts.css:34` styles only
   `.make-shorts__picker select`).
6. `app/renderer/src/components/JobQueue.tsx:41-43` + `JobQueue.test.tsx:115,118-119` + no clear path in
   `JobQueue.tsx` — a `cancelled` job has no available action. (H4)
7. `app/renderer/src/views/Library.tsx:470-483` — `globalThis.confirm` guards `shorts.delete`; the comment
   records the prior unguarded state and names the standard at
   `app/renderer/src/features/KeepCopyControl.tsx:21`. (§4.5) **Re-anchored 2026-08-10:** the guard is now
   the themed `useConfirm` gate in `Library.deleteShort` (`:474`, `confirm(` at `:488`) — cite the SYMBOL,
   not the line.
