# Reframe UI/UX + QOL Audit — 2026-08-08

> **Status:** ACTIVE

**Auditor:** uiux subagent (Opus 5). **Mode:** READ-ONLY on app source — drove + inspected, never edited.
**Target:** `D:\Program Files\Reframe\Reframe.exe` launched with `--force-renderer-accessibility`, pid 17292.
**Method:** Windows UI Automation (`AutomationElement.FromHandle`) for the control tree + actuation;
`PrintWindow(flag=2)` window-scoped screenshots with a distinct-colour assert; repo source read for
corroboration. **All 8 rail destinations and all 8 Settings sub-tabs were ACTUATED, not merely read.**

**Honesty contract:** UNVERIFIED sits inline next to the claim it qualifies, naming the settling
experiment. A control never actuated is `NOT-CHECKED`, never "works".

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

**My detector failures, and what each nearly caused me to report:**

| My wrong reading | Broken probe | What corrected it |
|---|---|---|
| "Make Shorts renders the Library panel" (a routing bug) | UIA tree read 1400 ms after the click — Chromium updates the a11y tree asynchronously | the screenshot moments later showed Make Shorts correct. Rewrote the dumper to block until the expected `tabpanel-*` is live (settle 319–856 ms). **No routing bug exists.** |
| "Jobs / Capabilities have no actuation pattern" | my click script only tried Invoke/SelectionItem/Toggle | both are `ExpandCollapse`. Added it; both actuate fine |
| "DONE jobs render white, not green" | eyeballing a compressed PNG; then a pixel sampler that returned an identical surface colour for visually different regions — a self-contradicting output, so a broken instrument | `jobqueue.css:214-216` — `.jobqueue__status--done { color: var(--status-success) }`. **The CSS is correct; I withdraw this finding** |
| "the app has no destructive-action confirmations" | grepped `window.confirm` | the code uses `globalThis.confirm` (`Library.tsx:480`). **Confirmations do exist**; see §4.5 |

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

**Four different CTA treatments for the same "you need media" state** (amber button / combo / nothing /
`← Library`). Edit offering *nothing* is the worst case.

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

`docs/design-system.md:43` defines caption 11 px/600 tracked CAPS as *the* label voice. Honoured on
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

### 4.1 The app ships Electron's stock menu — no application-level shortcuts

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

### 4.5 Destructive actions: guarded, but by an unstyled native dialog

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
tests for edge cases. No other surface accepts a drop — including Edit / Caption / Export / Director,
whose empty states all say "Pick a video from the Library". A user dragging a file onto Edit gets nothing.

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

### HIGH

**H1. DevTools + Force Reload shipped to end users** (§4.1). Gate the dev items behind `!app.isPackaged`.
**H2. No application-level keyboard shortcuts** (§4.1) — add `Ctrl+O`, `Ctrl+,`, `Ctrl+E`, and renderer
`Space` / `I` / `O`.
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
**M3.** Four different CTA treatments for the same "you need media" state (§1).
**M4.** Accent rationing exceeded on every screen (§3.2).
**M5.** Two label voices, sometimes on one screen (§3.3).
**M6.** Drag-and-drop works only on Library, while four other surfaces tell you to go get a video (§4.6).
**M7.** Destructive confirmation uses an unthemeable native `confirm()` dialog (§4.5).
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
**L5.** `LibraryShortsApi.remove`'s "the adapter owns any confirm" contract (`Library.tsx:53`) preserves
the delegation pattern that already failed once (§4.5).

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
   records the prior unguarded state and names the standard at `KeepCopyControl.tsx:21`. (§4.5)
