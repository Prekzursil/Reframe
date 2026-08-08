# Reframe Redesign — Synthesized Design Direction

> **Status:** ACTIVE

**Verdict: ADOPT-WITH-CHANGES.** All six review lenses independently returned `adopt-with-changes`. The 5-phase editor IA + three-zone shell + content-first Library is **structurally sound and worth building** — every required change is *additive*, none demands abandoning the locked IA. The prototype is a strong **layout/IA proof**; it is **not** a color, token, state, or accessibility source of truth. Build the real screens against the shipped `tokens.css` (extended deliberately), not against the prototype's literal values.

This document is the acceptance artifact that gates screen build-out. It is grounded in the actual prototype (`reframe-redesign.html`), the shipped `tokens.css` + its conformance guard, the live visual audit, the competitor research, the locked v1.5 program, and a direct inspection of the current renderer (`app/renderer/src`).

---

## 1. GO / NO-GO on the 5-phase editor IA

**GO — with five sub-decisions resolved before any screen ships.** The five phases (Transcribe → Edit → Reframe → Caption → Export) correctly collapse the audit's #1 P0 (the 16+ horizontal-tab wall), and the three-zone shell (stage / inspector / persistent timeline) is the correct NLE mental model. The current codebase already evolves *toward* this (TaskHub, Workspace's 4-cluster regrouping, TopTabBar ARIA tablist), so it is an evolution of a shipped pattern, not a from-scratch gamble. **But the clean 5-phase strip is tidy partly by omission** — its tidiness hides real features that have no home. Ship the IA only after these five sub-decisions land:

| # | Sub-decision | Ruling |
|---|---|---|
| 1 | **One-source → many-shorts + clip-finding** (the app's headline job) has NO home in the linear 5-phase model | **BLOCKER.** Add an explicit clip-finding flow (a "Find" step before/beside the phases, or a Library→candidates step) AND make the Library "3 shorts" label open a real produced-shorts gallery. This is the single largest existing feature area (CandidateList, CandidateReview, ProducedShorts, ShortMaker*, MakeShorts, Shorts, useShortsGallery — all verified present) and a top-3 competitor differentiator. Resolve before building any real screen. |
| 2 | **No audio home** for Dub (a locked v1.5 flagship) + mix/duck/silence-trim | Rename Phase 2 **"Edit → Edit & Audio"** (or add an Audio sub-context inside Edit). Do **not** add a 6th phase (re-sprawls the locked 5) and do **not** bolt Dub onto Export. Name the flagship's home now. |
| 3 | **Export duplicated** as Phase 5 *and* a rail "Deliver" zone, unlinked | Keep BOTH but scope + link them (see §2, disagreement 6): Phase 5 = per-video render; Deliver = batch/cross-video publish + aspect-matrix + platform presets. |
| 4 | **Wizard semantics** (01–05, ✓, "→ Caption") imply a false transcribe-first gate | Keep the numbers as **completion-state + orientation** (real info); DROP the forward-only "→ next" / gate implication. Phases are **freely-jumpable contexts**; gate ONLY where a true data dependency exists, each with a stated reason (see §2, disagreement 7). |
| 5 | **~6 panels + the whole novice surface are unmapped** (Search, Refine, Tracks, Recipes, Assets, Repurpose) | Every surface gets an explicit new home or a documented cut. The full mapping table (§6) is the IA acceptance artifact — no screen builds until it is signed off. |

---

## 2. Disagreements between lenses — resolved (which wins + why)

The six lenses converge far more than they conflict. The genuine tensions and their rulings:

**1 — Which critical issue is #1: the IA gap (IA lens) vs the a11y/state gaps (Interaction + A11y lenses)?**
→ **IA map wins the #1 slot; a11y/state foundation is #2.** Both are must-do "critical" findings, so this is an *ordering* call, not exclusion. The IA map is the upstream **spec** artifact — you cannot furnish (accessibly build) rooms you have not yet defined, and it resolves the sharpest single finding (homeless shorts-finding). The a11y/state model is a **build-quality** foundation established once in shared primitives and inherited by all four screens — it comes second only because it presupposes knowing what the screens are.

**2 — Director: a separate rail destination vs an omnipresent input?**
→ **Reconciled — all three positions are simultaneously satisfiable.** Feasibility + Interaction win on "keep Director as a first-class **rail destination** built on the shipped DirectorPanel" (lowest-risk ~1:1 reuse, and the prototype's demotion of Director to a dead icon is the actual bug). The IA lens wins on its real concern: Director's **output must land as reviewable per-phase diffs** (cuts→Edit, keyframes→Caption, crop nudges→Reframe), NOT in a divorced parallel editor. Also expose Director invocation from Cmd-K. Do **not** fold Director into the linear stepper — it is cross-cutting, not a step.

**3 — Canvas surface: the prototype's near-black `#0E0F12` vs the shipped cool-lifted `#121620`?**
→ **Shipped tokens win, unambiguously.** No lens defends the prototype's palette. Its `--bg #0E0F12` (b−r=4, relLum≈0.0048) fails the conformance guard's cool-cast (b−r≥8) *and* lift (relLum>0.006) invariants — the test comment literally names `#0e0f12 ≈ 0.0046` as the previously-rejected value. Neutral near-black is *more* generic (against the anti-template brief) and *worsens* contrast headroom under already-quiet text. Keep the shipped ramp; media wells step DOWN to `--surface-deep`.

**4 — Type scale: bump body 13→14 and add a 26px page-title, vs snap to the shipped ladder?**
→ **Snap to the ladder wins.** Reconcile the Library h1 (26px, off the 22/30 scale) to `--type-display` (30px) rather than inventing a new rung; keep body at 13px (a deliberate dense-editor choice, not a defect); drop ALL `.5px` sizes (10.5/11.5/12.5/13.5 — sub-pixel-rounding fragile). Evolve tokens deliberately only where justified (fonts — see §5).

**5 — Caption inspector: is the prototype's 320px column enough?**
→ **"Caption needs a wider/nested surface" wins** (IA + hierarchy + feasibility all agree). The inspector is not a fixed 320px for every phase. Caption's density (six CaptionX components + the viral-caption engine, all verified present) requires a template-preset **gallery that expands over the timeline**, not a cramped column.

**6 — Export vs Deliver: keep both distinct (IA lens) vs collapse to one word (Content lens)?**
→ **Keep-both-distinct wins on substance; the one-word lens wins on naming discipline.** The app genuinely has TWO delivery scales: finishing ONE clip (Phase 5) and batch/aspect-matrix publish of MANY (BatchQueue + Repurpose + ProducedShorts — all present and needing a home). A single per-video "Export" phase cannot host batch-publish-across-4-aspects, so the batch surface must survive. BUT the Content lens's real complaint — two differently-named doors reintroduce the P0 nav-inconsistency — is honored: name them so the relationship is legible ("Export" the shared verb for per-video render; "Deliver" explicitly scoped as batch/cross-video), and make finishing Phase 5 link INTO Deliver. Not two random synonyms. (Dub → Edit & Audio, not Export — both lenses agree.)

**7 — Phase numbering: meaningful state (Content lens likes it) vs false linear gate (IA lens)?**
→ **Free-jump-by-default wins the model; the "numbers encode real state" insight is preserved, not discarded.** The Content lens is right that `01✓/02✓/03` carries genuine completion + position info — keep it. The IA lens is right that the "→ Caption" push + transcribe-first implication regresses the current TaskHub's freedom (reframe needs no transcript) — so DROP the forward-only wizard language and the blanket gate. Phases are freely-jumpable named contexts; define a per-phase disabled state ONLY where a true data dependency exists (e.g. Caption needs a transcript → "generate captions first"), each with a stated reason. Do not ship the ambiguous hybrid the IA lens flags.

**8 — Is the audit's "Library foregrounds plumbing" finding current or stale?**
→ **The feasibility lens's "stale" reading wins on fact.** Verified: `ReadinessRollup.tsx` exists and `Library.tsx` already consumes it to demote model-readiness. The audit's P1 was captured against an older win32 baseline (predates #278). This does **not** change the design direction (content-first is right regardless) — it changes the *migration-cost* framing: the content-first Library is a **re-skin of a partly-shipped win**, making it the lowest-cost screen, not a rebuild.

---

## 3. Ranked priority list

Ordered by (blocks-downstream-work × cross-lens consensus × locked-scope alignment). Each item folds the duplicate findings the six lenses raised under different names.

**P0 — Complete the IA map before building any screen (the spec blocker).**
Produce the full old-surface → new-home mapping (§6). Sharpest sub-item: give the **one-source → many-shorts** relationship a real model — a clip-finding flow + a browsable produced-shorts gallery (the Library "3 shorts" label must open it). Both the IA and feasibility lenses call every unmapped "where does X go?" a spec blocker, not an implementation detail. *Why #1:* you cannot build Caption/Director/Export/Library — or accessibly furnish them — without knowing where shorts-finding, Dub, Assets, Search, batch, and Repurpose live. It also resolves the single most severe finding.

**P1 — Establish the accessible, stateful control foundation ONCE, before screens.**
Shared control primitives: every interactive element is a native `button`/`a[href]` or a role-complete widget with `tabindex` + key handlers; a visible `--focus-ring` on `:focus-visible` (survives the reset); polite + assertive `aria-live` regions; a global `prefers-reduced-motion` block; and a disabled/gating model (busy → done transitions, precondition-disabled with hover reasons). *Why #2:* the prototype ships ZERO focus/aria/tabindex and re-introduces the exact mouse-only WCAG-A barrier the program was **chartered to eliminate** (program line 31) — shipping it regresses locked scope on the highest-weighted DESIGN-EVAL axis. Build it once as primitives or pay to retrofit it four times. Adopt DirectorPanel (12 verified aria/role/focus hits) as the reference implementation.

**P2 — Design the full job/state lifecycle (terminal states, errors, empty, loading, guarded Export).**
Pill states for queued/running(determinate)/done/failed/cancelled; a failure surface with a recovery action; a crashed-sidecar alert; first-run-empty + filter-empty + no-video-selected; loading skeletons + async posters; and Export as a **guarded commit** (pre-flight summary, confirm, spend/egress guard, real cancel, terminal success/failure). *Why #3:* the prototype's optimistic-only job pill re-canonizes the "forever-spinning job UI" that **Wave-0 is fixing in code** — the design must not contradict the code fix. Export is the one irreversible spend/file-write action and is currently unguarded. These are cross-cutting comps every screen consumes.

**P3 — Reconcile the token layer (contrast fix + surface ramp + namespace) and evolve fonts deliberately.**
Bind to the shipped tokens; carry NONE of the prototype's literal hex (full list in §5). *Why #4:* the `#50555F` contrast regression is the **highest cross-lens consensus item** (cited by 5 of 6 lenses) and re-breaks a WCAG 1.4.3 fix `tokens.css` already shipped — but it ranks below P0–P2 because it is largely mechanical ("consume the existing token"), not missing-design. The contrast fix is a **non-negotiable guardrail** that rides along with every screen and is pinned by the conformance test (building from the prototype's hex breaks CI).

**P4 — Design the core direct-manipulation objects: on-canvas crop + the multi-lane timeline.**
On-canvas crop with grab/resize handles, move cursor, keyframe markers, keyboard nudge (the "Open crop editor" / orphaned ReframeOverridePanel becomes an *enhancement*, not the only path). The persistent multi-lane timeline is a **net-new build** (the shipped Timeline.tsx is a single-lane subtitle cue editor, not the video/audio/caption transport the prototype draws) with its own keyboard model (focusable clips, J/K/L, arrow-nudge). *Why #5:* the crop box IS the product yet is static in the mock; the timeline is the single largest net-new UI. High effort → scope as dedicated work units and build the timeline **last** so the shell isn't blocked on it.

**P5 — Content/UX-writing pass: eliminate jargon at source, make numbers honest, make card meta additive.**
One string-table pass on `advisorMeta.ts` so every capability reads as what it DOES ("Follow the speaker", not "Saliency assist (UNISAL)") and no model codename ever reaches the UI (proof it's coupled to plumbing: the Wave-1 ViNet-S→UNISAL swap would force the UI string to change). Tie the "Reframe confidence 94%" badge to an action (Director's `summarizePlan` pattern: "94% — 2 spans need a look → review") or drop it. Make card meta additive (never a duplicate of the badge); fix the chip to "Capabilities: 8 of 11 installed" (a plumbing count must not collide with the visible card count). *Why #6:* the redesign relocated jargon rather than eliminating it — the fix is at the source so it reads correctly in all four places the label appears.

**P6 — Responsive/reflow + Director-first-class + Library batch/scale affordances.**
Breakpoints where the 320px inspector collapses to a drawer and the topbar truncates (a resizable Electron window; declare `BrowserWindow` min-width/height); Director promoted from dead icon to first-class screen; Library multi-select + batch actions (reframe/export/repurpose) + per-library search/sort that the scale story depends on. *Why #7:* real but lower-consensus, and mostly additive on top of the P0–P3 foundation.

---

## 4. Per-screen build plan

### Library — *lowest migration cost (re-skin, not rebuild)*
The content-first grid is validated by every lens and fixes audit P1 — which `ReadinessRollup.tsx` already partly ships. Adopt the `auto-fill minmax(215px,1fr)` grid as the responsive model. Then:
- **Wire the one-to-many model (P0):** the "3 shorts" label opens a real produced-shorts gallery/picker (ProducedShorts + useShortsGallery); each short is editable in Studio.
- **Add the scale affordances:** multi-select + batch actions (BatchQueue / Repurpose) and per-library search/sort — Cmd-K is global but must not substitute for in-context filtering at hundreds of videos.
- **Fix the chip:** "Capabilities: 8 of 11 installed ⌄" (bind the noun; separate the plumbing count from the 8 visible cards) with a designed expanded state. Do the `advisorMeta.ts` jargon rewrite before this ships — the disclosure is where those labels resurface.
- **Card meta additive, not duplicated:** shorts count OR date/size; demote "READY" (let the shorts count be the done-signal); reserve badges for attention states — and ADD a FAILED badge (mock has only ready/work).
- **State matrix:** first-run empty (reuse the audit-praised "No shorts yet" icon + heading + CTA), loading skeleton + async per-thumbnail posters (useVideoThumbnail — fixes the raw-magenta flag), filter-empty.
- **A11y/depth:** cards are real focusable buttons/links (`aria-label` = title+status+duration, Enter/Space to open, `--focus-ring`); keep the good `translateY(-2px)` hover but swap the resting `border:1px` for `--elev-1` + a tone step so cards read as raised.

### Caption — *the best PILOT phase (richest reusable substrate)*
Compose the existing **CaptionCustomizer / CaptionDesigner / CaptionStylePicker / CaptionBox / CaptionPreferences / CaptionOverlay** + the pure lib modules (captionTemplates / captionKaraokePreset / captionOverride / captionOverridePreview / captionDesign / captionPosition) into the inspector; render the live caption on the shared Stage via `captionOverridePreview`. **Prove the inspector + shared-stage + EditorContext pattern here first** (feasibility's pilot) — logic cost LOW, layout cost MEDIUM.
- **Surface:** NOT a 320px column — a template-preset **gallery that expands over the timeline** (or a nested panel). Relocate subtitle **Tracks** management here explicitly.
- **Naming:** styles by their LOOK ("Word-by-word pop" / "Emoji burst" / "Keyword highlight"), with a live preview of each; never surface font/codec/model names.
- **Editorial voice:** this is where the (evolved) serif finally earns its token — style previews + hook cards are the pull-quote moment. **GUARD:** the template gallery is the single most likely place a decorative second accent (a lone acid-green pop) sneaks in — hold the line at ONE semantic amber; differentiate templates by type/layout, not new hues.
- **Interaction/a11y:** keyboard-operable caption clips with drag + resize handles (do NOT copy the current mouse-only Timeline — that IS the WCAG-A barrier being removed); disabled state when no transcript ("generate captions first"); a reversibility signal for burn (hardsub permanent vs soft-mux toggleable) surfaced as a guarded choice; gate the karaoke scale-pop preview behind `prefers-reduced-motion` with a static fallback.

### Director — *near-1:1 reuse, lowest-risk, and the crown jewel the prototype demoted to a dead icon (the single biggest miss)*
- **Placement (resolved):** a **first-class rail destination** built on the shipped DirectorPanel (do NOT fold into the stepper). Its proposed multi-step edit lands as **reviewable per-phase diffs** in the inspectors it touches; also invokable from Cmd-K.
- **Adopt DirectorPanel's patterns wholesale** (it is the reference state-model impl): empty ("No video open" + Choose-video CTA), busy ("Working…" + `aria-live="polite"`), error (`role="alert"`), the reviewable collapsible storyboard with per-op enable/disable/reorder that is keyboard-complete (Enter/Space/Arrow), the per-data-type cost/egress banner, the Apply gate echoing the budget cacheKey, one-shot Undo, and "Adjust & re-plan" carrying the prior goal forward.
- **Hierarchy:** make this the ONE consciously LOW-density, editorial-spacious screen — use the upper spacing rungs (`--space-6/7/8` = 24/32/48), the strongest home for the serif display voice with a real scale jump, left-anchored and composed (do NOT strand a form top-left with 60% dead space, the audit-era failure).
- **Voice:** keep the reviewable/reversible trust microcopy VERBATIM ("plans a reviewable, reversible edit — nothing is applied until you confirm"; "Text will leave your machine.") — it is the brand's signature — but render it in the AA-safe quiet step, never `#50555F`. Gate any streaming/"thinking" animation behind `prefers-reduced-motion`; reflow vertically at narrow widths (do not trap it in the 320px aside).

### Export — *the most state-critical screen: the ONE irreversible, spend/file-writing action*
- **First fix naming + division of labor** (resolves the Export/Deliver duplication): Phase 5 **"Export"** = per-video render/finish (guarded commit); rail **"Deliver"** = cross-video/batch publish + platform presets + Repurpose's aspect-ratio matrix (9:16/4:5/1:1/16:9). Reconcile the four existing Deliver-cluster tabs: Convert (format/codec at render) → Phase 5; NleExport (EDL/CSV pro-handoff) + ExportPresetsPanel + BatchQueue → Deliver. Finishing Phase 5 links INTO Deliver. Confirm Dub is NOT here (Edit & Audio).
- **Design as a guarded commit** ("nothing is baked until Export" means Export IS the bake): pre-flight summary (N clips, aspect matrix, duration, est. time/spend); explicit confirm; per-platform preset matrix with selected/disabled/unavailable states; determinate progress + a real **CANCEL** control (Wave-0 real-cancel needs its UI home here); terminal SUCCESS wired to real output locations (OutputTray) AND terminal FAILURE/partial (SidecarBanner/toast); spend/egress guards (SpendCap, BatchConsentCard exist). Batch renders use the BatchQueue `LiveStatusRegion` polite+assertive announcer.
- **Hierarchy + a11y:** rank the primary export (ONE amber approve button) above secondary presets via scale + the `--elev` ladder, NOT equal-weight tiles (avoid the banned uniform-card-grid). Presets = recognizable destinations (TikTok / Reels / Shorts implying aspect/length/loudness), never codec/bitrate jargon. Build the matrix as a real `fieldset`/`radiogroup` (`role="radio"` + `aria-checked`, arrow-key selectable). Reuse the amber "signal" semantics + mono tabular-nums for progress. Restate the privacy beat ("stays on your machine — nothing uploads") with the SAME trust sentence the Studio inspector uses. Panel `overflow-y:auto` so the CTA is never clipped at short window heights.

---

## 5. Token changes

Build the shell against the EXISTING `tokens.css` namespace and extend it deliberately through the conformance guard + `DESIGN-DIRECTION.md`. Treat the prototype's tokens as **intent, not values to copy** — a half-migrated namespace fails the WU-D7 test (any unresolved `var()` fails CI).

### A. Reconcile back (carry NONE of the prototype's literal values)

| Prototype (drop) | Bind to shipped token | Why |
|---|---|---|
| `--t4:#50555F` on `.hint`, `.phase small`, `.zoom`, ruler timecodes, card meta | `--text-faint:#a6aebd` (AA on all elevation + hover/active planes) | Re-breaks a WCAG 1.4.3 fix already shipped (`#50555f ≈ 2.4:1`). Reserve `#50555F` for pure decoration only (waveform bars, inactive glyph strokes). If more hierarchy headroom is wanted, introduce a NEW darker-but-AA rung (~`#8A909C`, ~5.5:1 on raised) — never below 4.5:1. Cap at ≤3 readable text tones on these surfaces. |
| `--floor#0A0B0D / --bg#0E0F12 / --raised#16181D / --overlay#1D2026` | `--surface-deep#0b0d12 / --surface-bg#121620 / --surface-raised#1b212e / --surface-overlay#252d3d` | The prototype ramp fails the conformance-pinned cool-cast (b−r≥8) AND lift (relLum>0.006) invariants; media wells step DOWN to `--surface-deep`. |
| `#1a1205` (accent-ink on amber buttons) | `--accent-ink:#211404` | The pinned ink-on-accent value. |
| `.18s / .2s / .15s` inline | `--dur-fast/base/slow` (120/180/260ms) + `--ease-out` | The motion ladder; also where `prefers-reduced-motion` hooks in. |
| terse fork `--floor/--raised/--t1..t4/--amber/--r-s/m/l` | canonical `--surface-*/--text-*/--accent-*/--radius-*/--font-*` | WU-D7 fails on any unresolved `var()`; ship the canonical namespace. |
| (none — missing) | wire `--focus-ring` / `--focus-glow` on every interactive element; use `--elev-1/2/3`, `--shadow-raise`, `--atmos-toplight` for resting depth | Replaces borders-everywhere with tone-step + elevation ("surfaces, not boxes"); supplies the interactive-state + depth layers the prototype ships none of. |
| `26px` h1, `13.5` card title, `10.5` caps, all `.5px` sizes, `.13em` caps tracking, body `14` | `--type-display`(30) for the Library h1; `--type-card-title-size`(14); `--type-chip`/`--type-caption`(10/11); keep body at `--type-body-size`(13); one caps tracking ~0.08–0.1em | Snap to the pinned integer ladder; the sheets carry NO raw font-size. |
| `9/11/13/14/18/20` paddings; one-off radii `5/7/8` | 4px rhythm (9→8, 11→12, 13→12, 14→12/16); radii → `4/6/10/14` | Snap to `--space-*` and `--radius-*`. If the 16→24 gap keeps forcing 18/20, add a deliberate `--space-5b:20px` rung rather than let panels invent it. |

### B. Evolve forward (deliberate, per Wave-2 scope — through the conformance guard)

- **Fonts (the one place the prototype leads tokens):** update `--font-ui` to lead with a bundled non-generic face (Inter, or Geist per the program) and `--font-editorial` → **Newsreader** (self-hosted, CSP) — this matches the program's Wave-2 "bundled Inter/Geist + IBM Plex Mono + Newsreader" and supersedes the current stale `system-ui` + `Georgia`. AND actually EXERCISE the serif (Director / hook-card / caption-preview) — otherwise drop the token. `tokens.css` currently does NOT specify Inter and uses Georgia for editorial; this evolution is intended, not a regression.
- **Add the locked Wave-2 layers** the prototype/tokens don't yet encode: a **glass layer** (backdrop-blur floating surfaces), **Cmd-K** palette tokens, and any new motion tokens — all pinned by the conformance guard.
- **Platform-adapt the accelerator glyph:** `⌘K` → `Ctrl K` on the Windows-x64 target; pair the "Run on: Cloud" toggle with an always-visible "what uploads" affordance so the routing choice never silently contradicts the local-first brand.

---

## 6. Old-surface → new-home IA mapping (acceptance artifact)

Sign this off before any screen builds. Every current surface has an explicit home or a documented cut.

| Current surface (verified present) | New home |
|---|---|
| `Library` view | **Library** rail destination (content-first grid) — re-skin |
| `MakeShorts`, `Shorts`, `CandidateList`, `CandidateReview`, `ProducedShorts`, `ShortMaker*`, `useShortsGallery` | **NEW "Find" flow** (clip-finding step) + **produced-shorts gallery** reachable from Library cards — the P0 one-to-many model |
| `TaskHub`, `Edit`, `Workspace` | The **Studio** three-zone shell (phase stepper replaces tab clusters; keep an "Advanced / all tools" escape until every panel migrates) |
| `Transcribe`, `Diarize`, `Refine` | **Phase 1 — Transcribe** (Diarize / Refine as sub-contexts) |
| Frame&Cut, silence-trim, filler-removal | **Phase 2 — Edit** |
| `Dub` + audio mix/duck/silence-trim | **Phase 2 — "Edit & Audio"** (flagship home named now) — NOT Export |
| `Assets` (B-roll library) | Inside **Edit** (the B-roll source) — flagship auto-B-roll home |
| Reframe tracking/saliency + `ReframeOverridePanel` (orphaned) | **Phase 3 — Reframe** (wire ReframeOverridePanel as the on-canvas crop editor) |
| `Subtitles`, all six `Caption*`, `TemplateEditor`, `Tracks` | **Phase 4 — Caption** (Tracks = subtitle-track mgmt here) |
| `Convert` (format/codec) | **Phase 5 — Export** (per-video render) |
| `ExportPresetsPanel`, `Repurpose` (aspect matrix), `NleExport` (EDL/CSV), `BatchQueue`, `BatchConsentCard` | Rail **"Deliver"** (batch / cross-video publish) |
| `SemanticSearch`, `Recipes` | **Cmd-K** command palette |
| `DirectorPanel` | Rail **"Director"** (first-class; output → phase diffs; also Cmd-K-invokable) |
| `Settings`, `ModelsSystemPanel`, `ProvidersKeys`, `SpendCap`, `SystemHealth`, `ReadinessRollup` | Rail **"Settings"** (+ ReadinessRollup surfaces as the Library "Capabilities" chip disclosure) |
| `Lineage*`, `LibraryProvenance` | Per-video provenance/history (Library card detail or a Studio "history" affordance) |

---

## 7. Non-big-bang build sequence

Land incrementally behind the existing seams so the mature, 100%-covered surfaces are never stranded and the blocking coverage gate never sits red for long:

1. **Now (safe, parallel):** re-skin Library to the grid using the existing card/thumbnail/ReadinessRollup components; swap TopTabBar → left rail (presentational only, routing unchanged); reconcile tokens (§5) and lock the conformance test against the evolved token file.
2. **Pilot ONE phase end-to-end — Caption** (richest reusable substrate): extract a shared `EditorContext` (video, cues, cropPlan, caption style, playhead, selection) that the stage, timeline, and inspector all read/write, so panels become thin consumers instead of layout owners. Measure the real inspector-over-shared-stage cost before committing all five.
3. **Sequence per-panel inspector refactors AFTER Wave-0 regenerates the RPC contract** for those panels' calls (they touch the same schemas.ts / client.ts / Services surface Wave-0 is rewriting) — refactor once against the new typed client, not twice.
4. **Build the multi-lane timeline LAST** as its own TDD work unit (net-new, with a real keyboard model) so the rest of the shell isn't blocked on it.
5. **Defer Cmd-K** until the shell + phase migration stabilizes (it's a net-new subsystem: registry + fuzzy search + global key capture + its own a11y); source its command list from the same route/phase registry the rail uses so the two nav models cannot desync.
6. Never delete a working panel until its phase replacement passes the coverage gate.

---

## 8. Definition of done (gates every screen must clear)

- **Contrast:** no readable text below 4.5:1; the tokens conformance ladder test passes against the evolved token file. (Non-negotiable — the 5-lens consensus item.)
- **Keyboard:** every control is a native element or role-complete widget with a visible `--focus-ring`; the timeline + caption clips + phase stepper are keyboard-operable (closes the locked WCAG-A barrier).
- **State completeness:** empty, loading, busy/disabled-with-reason, terminal success, and terminal failure/cancel all exist for every async surface; the job pill and errors announce via `aria-live`.
- **Motion:** `prefers-reduced-motion` neutralizes all infinite/decorative animation with a static fallback.
- **Responsive:** no horizontal overflow at the declared `BrowserWindow` min-width; the inspector collapses to a drawer and the topbar truncates at narrow widths.
- **One-accent discipline:** amber is the only accent (progress/active/approve); status strictly green/amber/red; no decorative second hue (guard the caption gallery).
- **Voice:** no engineer jargon or model codenames in any user-visible string (fixed at `advisorMeta.ts` source); trust microcopy preserved verbatim in the AA-safe quiet step.
- **IA integrity:** the §6 mapping is signed off; no working feature is stranded; Export/Deliver, Dub-in-Edit&Audio, and the shorts-finding flow all have their homes wired.
