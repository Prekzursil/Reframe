# Reframe UI/UX + QOL Audit — 2026-08-08

> **Status:** ACTIVE

**Auditor:** uiux subagent (Opus 5). **Mode:** READ-ONLY on app source — drove + inspected, never edited.
**Target:** `D:\Program Files\Reframe\Reframe.exe` launched with `--force-renderer-accessibility`, pid 17292.
**Method:** Windows UI Automation (`AutomationElement.FromHandle`) for the control tree + actuation;
`PrintWindow(flag=2)` window-scoped screenshots with a distinct-colour assert for pixels; repo source read
for corroboration. **Every rail destination and every Settings sub-tab was ACTUATED, not merely read.**

**Honesty contract:** UNVERIFIED is inline next to the claim it qualifies, naming the settling experiment.
Sherman-Kent bands on forward-looking claims. A control never actuated is `NOT-CHECKED`, never "works".

## COVERAGE

| Section | Status |
|---|---|
| 0. Ground truth / instrument corrections | MEASURED |
| 1. Rail destinations (8/8 actuated) | MEASURED |
| 2. Settings sub-sections (8/8 actuated) | MEASURED |
| 3. Design-direction conformance | MEASURED (static + pixel; no computed-style access) |
| 4. QOL sweep | PARTIAL — menus/shortcuts MEASURED; undo/redo, drag-drop, job cancel/resume from source read |
| 5. Ranked findings | MEASURED |
| 6. Evidence anchors | MEASURED |

## 0. Ground truth and instrument corrections

Two premises in my brief were wrong; correcting them because they change what the evidence means.

1. **The app was NOT running when I started.** `Get-Process -Name Reframe` and
   `Get-CimInstance Win32_Process -Filter "Name='Reframe.exe'"` both returned empty (two mechanically
   independent probes). I launched it myself with `--force-renderer-accessibility`.
2. **`docs/build/DESIGN-DIRECTION.md` is stale.** Its own line 3 reads
   *"Status: SUPERSEDED BY docs/design-system.md (2026-08-08)"*, it is titled "media-studio" not Reframe,
   and `app/renderer/src/styles/tokens.css:103` explicitly calls its `system-ui`/`Georgia` font values
   and its `#08090b` surface ladder **stale**. I therefore judged the app against
   `docs/design-system.md` (Status: ACTIVE) and used DESIGN-DIRECTION.md only where the newer doc
   restates the same intent.

**Instrument correction (recorded so no one cites my first pass).** My initial rail sweep reported that
"Make Shorts" rendered the Library panel — an apparent routing bug. It was **my detector, not the app**:
Chromium updates the UIA accessibility tree asynchronously, and a 1400 ms settle returned the previous
panel's nodes. The screenshot taken moments later showed Make Shorts rendering correctly. I rewrote the
dumper (`uia_dump2.ps1`) to block until the expected `tabpanel-*` node is live, and re-ran everything;
observed settle times were 319–856 ms once the wait was correct. **No routing bug exists.**

**Second instrument correction.** UIA menu enumeration failed twice (no `InvokePattern`; then no popup
items surfaced). Rather than attempt a third variant I pivoted to two independent methods — a
desktop-region screen capture with the menu open, and a source read — which agreed.

## 1. Rail destinations — all 8 actuated

| Destination | Empty state | CTA offered | Notes |
|---|---|---|---|
| Library | ghost-poster + "No videos yet" | **Add videos** (amber) | Search + Sort render live on an empty library |
| Make Shorts | ghost-poster + "No video selected" | `Select a video…` combo | 3 sub-tabs: MAKE / PRODUCED SHORTS / BATCH & TEMPLATES |
| Edit | "No video open" + prose | **none** | dead end — no way forward from the screen |
| Caption | "Open a video to caption" | `← Library` | |
| Export | "Open a video to export" | `← Library` | |
| Deliver | per-section prose | `← Library` | 3 sub-tabs; unstyled `fieldset`; 23×20 px native `select` |
| Director | ghost-poster in a card | **Choose a video** + `What is Director?` | title set in the editorial serif (see §3) |
| Settings | n/a | n/a | 8 sub-tabs, all actuated |

Library is empty, so every media-dependent flow is `NOT-CHECKED` end-to-end. I did **not** add media —
that would mutate the owner's library. **The single most valuable follow-up is a first-run walkthrough
with one real video**; nothing below substitutes for it.

**Four different CTA treatments for the same "you need media" state** (amber button / combo / nothing /
`← Library`). Edit offering *nothing* is the worst case.

## 2. Settings sub-sections — all 8 actuated

All 8 actuated against the real preload bridge; each panel's own `tabpanel-*` node verified live
(settle 319–856 ms). No degraded or error state observed.

MODELS & SYSTEM · SETUP · PROVIDERS & KEYS · STORAGE · CAPTION DEFAULTS · SYSTEM HEALTH · LICENSES ·
EXPORT PRESETS.

**Best-executed surfaces:** SETUP (green summary banner + 5 PASS rows with left-rail status) and
SYSTEM HEALTH (tracked-caps section labels, consistent rows, semantic green). These match the design
system closely and should be the template for the others.

**Content taller than the 673 px viewport, with primary actions below the fold:**
CAPTION DEFAULTS is 952 px tall and its **`Save defaults` button sits at y=1198** — the panel's only
commit action is unreachable without scrolling, with no sticky footer. SYSTEM HEALTH (887 px) and
PROVIDERS & KEYS both push content offscreen too.

## 3. Design-direction conformance (vs `docs/design-system.md`, Status: ACTIVE)

### 3.1 The editorial serif has spread to 15 sites (documented limit: 1)

`docs/design-system.md:49` — "Georgia editorial serif (ShortMaker hook pull-quotes **ONLY**)". The superseded
doc was blunter: *"ONE place only … It is the editorial signature; **do not spread it**."*

`--font-editorial` is referenced in **15** stylesheets. The clearest violation is visible on screen:
`app/renderer/src/views/director.css:48-56` sets `.director-view__title` to `--font-editorial` at
`--type-display-size` (30 px) — a **view title**, not a 15 px italic pull-quote. The code comment at
`director.css:47` calls it "the editorial moment", so the spread is deliberate in code and simply never
reconciled with the design SSOT. Other sites: `caption.css:96`, `export.css:94`,
`features/export/export.css:277,454`, `features/caption/captionStage.css:88`, `captionInspector.css:24`,
`captionGallery.css:29`, `components/library-shell.css:232`, `components/firstRunSetup.css:40`,
`components/profilePicker.css:31`, `components/shell.css:1480`, `features/lineage.css:71`,
`features/director/directorHandoff.css:21`, plus the sanctioned `views/shorts.css:336`.

`docs/design-system.md:6` says `tokens.conformance.test.ts` guards "one-accent discipline" — it evidently does
**not** guard serif rationing. **Fix:** either add a conformance test capping `--font-editorial` usage, or
amend the doc to describe the real intent. Right now doc and code disagree and nothing detects it.

### 3.2 Accent rationing is exceeded on every screen

`docs/design-system.md:30` — "Rationed: **at most one accent touchpoint per surface**." Counted from pixels on
Settings › MODELS & SYSTEM: brand tick, `AI MODEL: Local` ring, `WHERE JOBS RUN: Local` ring, Settings
rail item, active sub-tab underline + text, `Analyze my system` fill, and the `Privacy / offline` card
border + `ACTIVE` chip ≈ **7**.

UNVERIFIED — whether "surface" means *screen* or *region*: under a per-region reading the header alone
still carries 2 (both toggle groups), so the rule is exceeded either way, but the severity depends on the
reading. Settling experiment: have the design owner state the unit, then encode it as a conformance test
counting accent-valued declarations per component.

### 3.3 Two label voices coexist, sometimes on one screen

`docs/design-system.md:43` defines caption 11 px/600 tracked CAPS as *the* label voice. Honoured on Library
(`SORT`), the header (`AI MODEL`), and most Settings headings — but Deliver renders `Sources` and
`Template` as sentence-case body text, Make Shorts renders `Video`, EXPORT PRESETS renders
`Save current settings as`, and MODELS & SYSTEM mixes a sentence-case `OpenRouter spend` heading among
tracked-caps siblings.

### 3.4 Native form controls leak through the design system

Measured from live bounding boxes — a clean discriminator, since styled controls render 32–33 px tall and
raw native ones 20 px:

- **Styled (8):** `Sort videos` 132×33 · `#asr-engine` 452×32 · `#diarize-backend` 452×32 ·
  `#fn-select` / `#fn-subtitles` / `#fn-translation` / `#fn-vision` / `#fn-editPlan` 389×33.
- **Raw native (3):** Deliver `Template` **23×20** · `#prefs-subtitle-mode` 98×20 ·
  `#:r1:` Default language 94×20.

Deliver's `Template` at **23 px wide** is the worst: it renders as a bare caret with no room for a value.
Root cause is structural — there is no global `select` rule; `app/renderer/src/views/makeShorts.css:34`
styles `.make-shorts__picker select` with `appearance:none` and a hand-drawn caret, and every other select
is styled ad hoc or not at all. This is the same feature-namespaced-selector debt
`docs/design-system.md:65-66` already admits for buttons, unacknowledged for selects.

Deliver also renders an **unstyled `<fieldset>`** ("Sources") with a default notched legend and a
full-strength grey border — directly against "depth via TONE … borders almost eliminated"
(`docs/design-system.md:13`, anti-template gate #3).

Checkboxes split the same way: `COMMERCIAL USE` 23×17 and `#spend-cap-enforce` 22×17 vs
`#prefs-caption-polish` and `#prefs-caption-speakers` at **13×14**. All are under the WCAG 2.5.8 AA
24×24 target minimum. UNVERIFIED whether the associated label extends the hit target (which would satisfy
the exception) — settling experiment: click the label text, not the box, and observe the toggle.

### 3.5 What the design system gets right

Genuinely strong and worth protecting: the shared ghost-poster empty state (deep 16:9 well, play glyph,
mono `--:--` timecode) on Library / Make Shorts / Director; the surface ladder and near-total absence of
borders on Library, Settings and Health; the mono tabular voice for versions, paths and timecodes; the
double focus ring, which rendered visibly on every rail item I actuated; the SETUP and SYSTEM HEALTH
status treatments; and 17 caption-style presets with visual `Aa` previews.

## 4. QOL sweep

### 4.1 The app ships Electron's stock menu — no application shortcuts

Two independent signals: (a) `app/main/main.ts:13` imports `app, BrowserWindow, ipcMain, net, safeStorage,
session, shell` — **no `Menu`**, and no `setApplicationMenu` / `buildFromTemplate` / `accelerator` appears
anywhere under `app/`; (b) a desktop capture of the open menus shows exactly the Electron defaults.

- **View:** Reload `Ctrl+R` · Force Reload `Ctrl+Shift+R` · **Toggle Developer Tools `Ctrl+Shift+I`** ·
  Actual Size `Ctrl+0` · Zoom In/Out · Toggle Full Screen `F11`.
- **Edit:** Undo `Ctrl+Z` · Redo `Ctrl+Y` · Cut/Copy/Paste · Delete · Select All.

Consequences:
1. **DevTools and Force Reload are exposed in a production consumer build.** `Ctrl+R` mid-job hard-reloads
   the renderer. UNVERIFIED whether a running job survives it — settling experiment: start a long export,
   press `Ctrl+R`, observe whether the job continues and whether the UI recovers its progress.
2. **`Edit ▸ Undo (Ctrl+Z)` is a text-field role, not an edit-history undo.** In an app whose rail has a
   dedicated **Edit** destination for trimming and cutting, a top-level Undo that cannot undo a trim is
   actively misleading.
3. **No app shortcut exists for any core action** — no `Ctrl+O` add-videos, no `Space` play/pause, no
   `I`/`O` in/out, no `Ctrl+E` export, no `Ctrl+,` settings. For a video tool this is the single largest
   QOL gap.

Positive: CAPTION DEFAULTS' caption-region widget is keyboard-operable — its accessible name is
*"Caption region — arrow keys move; Tab to a handle then arrow keys to resize"*, with 8 named resize
handles as real buttons. That pattern should be generalised, not left as an island.

### 4.2 Controls that are live but cannot do anything

- Library **Search videos** and **Sort videos** render enabled with 0 items.
- Deliver **Template** select is empty and 23 px wide; **Run batch** is correctly `[DISABLED]`, but the
  screen stacks *three* separate blocked-state messages ("Add videos in your Library first." / "Save a
  template first." / "Select at least one source and a template to run a batch.").
- EXPORT PRESETS offers **"Save current settings as"** with no indication of *which* settings are
  captured — the panel shows no export setting at all, and the name field stretches ~810 px for a short
  string with placeholder-as-label.

### 4.3 Unexplained jargon with no help affordance

`Capabilities: 10 of 11 installed` (Library) names neither the missing capability nor whether it blocks
anything. `Lineage view`, `PRO HANDOFF`, `DIARIZATION BACKEND`, `Instant numeric`, `Video-LLM re-rank`,
`dover-mobile-quality` all appear with no tooltip. `What is Director?` is the only explicit help
affordance I found in the whole app.

### 4.4 Aggregate health verdicts contradict their own detail

SYSTEM HEALTH prints **"Setup OK"** and `ML BACKENDS (7/8)` while listing `kokoro (TTS) not installed`,
and reports `llama-server available` under ENGINES while `llama (CUDA)` and `llama (CPU)` both read
`empty` under MODEL & CACHE PATHS on the same page. UNVERIFIED whether those are genuinely optional —
settling experiment: run a TTS/dub job and a local-LLM job and see whether either fails against a page
that said OK.

SETUP and SYSTEM HEALTH also substantially duplicate each other (both answer "is my install OK", with
different data and different wording).

## 5. Ranked findings

Ranking is by user impact. "Screen · control" then the concrete fix.

### CRITICAL — blocks a task

**C1. Settings ▸ MODELS & SYSTEM opens scrolled ~503 px down, hiding its own title and the entire
capability list.** Reproduced on two independent fresh entries (Library→Settings, and HEALTH→MODELS):
the `Models & System` heading reports `y = -258` both times, while the control panel SYSTEM HEALTH reports
its heading at `y = +269`. Everything above the fold is lost, including `WHAT WORKS RIGHT NOW` and the
**only** `Download the Multimodal (visual + audio + transcript) model` button — the one control a new user
needs to enable multimodal moment-finding. This is the default Settings tab, so it is the first thing
seen. Fix: `app/renderer/src/panels/ModelsSystemPanel.tsx` — find the mount-time `scrollIntoView`/`focus()`
that pulls the panel down and scope it, or reset `scrollTop` on tab activation.
UNVERIFIED — the exact triggering call; I inferred it from the reproducible offset and did not read the
mount effect. Settling experiment: `Ctrl+Shift+I` and log `scrollTop` on the panel's scroll container.

**C2. `Edit ▸ Undo (Ctrl+Z)` promises an undo the app does not have.** Stock Electron text-field role in
an app with a dedicated Edit destination. Fix: `app/main/main.ts` — install a real
`Menu.setApplicationMenu` and either wire Undo to a genuine edit-history stack or remove the item.

### HIGH

**H1. DevTools + Force Reload shipped to end users.** `View ▸ Toggle Developer Tools (Ctrl+Shift+I)`,
`Reload (Ctrl+R)`, `Force Reload (Ctrl+Shift+R)`. Fix: same custom menu in `app/main/main.ts`; gate the
dev items behind `!app.isPackaged`.

**H2. No application keyboard shortcuts at all** (§4.1). Fix: a custom menu with `Ctrl+O` (Add videos),
`Ctrl+,` (Settings), `Ctrl+E` (Export), and renderer bindings for `Space` play/pause and `I`/`O` in/out.

**H3. Two identical `Analyze my system` buttons on one panel.** `ModelsSystemPanel.tsx:799-804` (toolbar,
label cycles `Analyzing…`/`Re-analyze`) and `:842-847` (`empty-state__cta`, always "Analyze my system"),
both calling the same `analyze()`. Measured live at `552,161` **and** `576,326`. C1 currently hides the
first one, so **the two defects mask each other** — fixing C1 alone will make the duplicate visible.
Fix: render the empty-state CTA only when the toolbar button is not visible, or drop one.

**H4. `Capabilities: 10 of 11 installed` names neither the gap nor its consequence.** Fix: name the
missing capability inline and say what it blocks, with a direct action to install it.

**H5. Deliver leaks unstyled native HTML** — a raw `<fieldset>`/legend and a **23×20 px** `Template`
select (§3.4). Fix: add a global `select` rule to the token layer; replace the fieldset with a raised
card.

**H6. `EXPORT PRESETS ▸ Save current settings as` gives no idea what will be saved.** Fix: list the
captured settings, cap the input width, and use a real label instead of a placeholder.

**H7. The editorial serif is used in 15 places against a documented limit of 1** (§3.1), undetected by the
conformance suite that already guards the accent.

### MEDIUM

**M1. Primary actions below the fold with no sticky footer** — CAPTION DEFAULTS' `Save defaults` at
y=1198 in a 673 px viewport (§2).
**M2. `Edit`'s empty state offers no action at all** — the only one of 8 destinations with no way forward.
**M3. Four different CTA treatments for the same "you need media" state** (§1).
**M4. Accent rationing exceeded on every screen** (§3.2).
**M5. Two label voices, sometimes on one screen** (§3.3).
**M6. Search + Sort live on an empty Library** (§4.2).
**M7. Three stacked blocked-state messages on Deliver ▸ BATCH PUBLISH** (§4.2).
**M8. SETUP and SYSTEM HEALTH duplicate each other** (§4.4).
**M9. `AI MODEL` and `WHERE JOBS RUN` remain near-identical twins** — same Local/Cloud vocabulary, same
visual treatment, adjacent. `docs/design-system.md:78-81` records this as already "disambiguated (v1.4)" via a
seam divider and distinct scope labels; the seam is present, but they still read as one duplicated
control. Fix: distinguish by form, not only by label.
**M10. `last checked 575m ago`** — raw minutes instead of a humanised interval.
**M11. Health verdicts contradict their own detail rows** (§4.4).

### LOW

**L1. Checkbox hit targets 13×14 px** (§3.4), under the WCAG 2.5.8 AA 24×24 minimum; label-extension
unverified.
**L2. `REQ LIMITS` meter renders a full-width green bar for `0 req`** — a full bar reads as 100%, and per
`docs/design-system.md:28` progress should be accent-amber while green means done. UNVERIFIED whether the
element is a fill or a track; settling experiment: inspect the `<meter>` value/max in DevTools.
**L3. Placeholder-as-label** on the preset-name field.
**L4. `← Library` back buttons on sibling rail destinations** mix a hierarchical affordance into a flat
rail.

## 6. Evidence anchors

1. **Screen · control:** Settings ▸ MODELS & SYSTEM, `Models & System` heading — UIA reports
   `y = -258` on two fresh entries; SYSTEM HEALTH control reports `y = +269`. (C1)
2. `app/renderer/src/panels/ModelsSystemPanel.tsx:799-804` and `:842-847` — two buttons, one `analyze()`.
3. `app/renderer/src/views/director.css:48-56` — `.director-view__title` uses `--font-editorial` at
   `--type-display-size`; `docs/design-system.md:49` says pull-quotes ONLY.
4. `app/main/main.ts:13` — electron import list contains no `Menu`; no `setApplicationMenu` under `app/`.
   Corroborated by a desktop capture of `View` showing `Toggle Developer Tools  Ctrl+Shift+I`.
5. **Screen · control:** Deliver ▸ BATCH PUBLISH, `Template` select — live bounding box **23×20 px**
   vs styled peers at 32–33 px; no global `select` rule exists
   (`app/renderer/src/views/makeShorts.css:34` styles only `.make-shorts__picker select`).
