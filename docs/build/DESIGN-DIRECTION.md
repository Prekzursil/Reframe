# DESIGN-DIRECTION — media-studio

> **Status:** SUPERSEDED BY docs/design-system.md (2026-08-08)

**Direction: Dark Editorial.** media-studio is a video tool, so it follows the rule every
serious video app follows: the footage is the brightest, most saturated thing on screen.
The chrome is near-black and tonal; hierarchy comes from type contrast (big numbers and
titles, quiet tracked-caps labels); depth comes from a layered surface ladder and shadow —
not borders around everything. One accent, used semantically, never decoratively.

Single source of truth: `app/renderer/src/styles/tokens.css` (imported first in `App.tsx`).
No component sheet may introduce a color, radius, duration, or font that is not a token.

---

## Palette — values live in `tokens.css`, not here

> **CORRECTED (2026-08-12, measured at `1fa9a69f`).** This section used to be headed
> *"Palette (exact values)"* and reprinted the whole ladder. **Nine of the sixteen values it
> stated contradicted `app/renderer/src/styles/tokens.css`** — the six `--surface-*` steps,
> `--edge`, `--text-muted` and `--text-faint` — which is a doc asserting exact numbers that
> the code disagrees with, three lines under its own sentence naming `tokens.css` the single
> source of truth. The dead values are DELETED rather than refreshed: this document has been
> `SUPERSEDED` since 2026-08-08, and a superseded doc that carries a second copy of the palette
> re-earns the same drift the moment the tokens move again. The correction is recorded here
> instead of applied silently so the next reader inherits it rather than re-deriving it.
>
> Verbatim, so the retraction is checkable and not merely asserted:
> `--surface-deep #08090b` (real `#0b0d12`) · `--surface-bg #0e0f12` (`#121620`) ·
> `--surface-raised #16181d` (`#1b212e`) · `--surface-overlay #1d2026` (`#252d3d`) ·
> `--surface-hover #22252d` (`#2c3448`) · `--surface-active #2a2e38` (`#353f56`) ·
> `--edge rgba(255,255,255,0.07)` (`rgba(255,255,255,0.09)`) · `--text-muted #7d8390`
> (`#adb4c2`) · `--text-faint #50555f` (`#a6aebd`). The seven that agreed are not restated.
>
> Checked by `docs/validation/tools/verify_ssot_claims.py` (`C8-colour:*` / `C8-binding:*`)
> over the **two** design docs its `DESIGN_DOCS` tuple enumerates — `docs/design-system.md`
> and this file — which fail if either prints a colour `tokens.css` does not define or binds
> a token name to a value it does not hold. Both directions are needed: `#50555f` still
> appears in `tokens.css` — inside the comment recording that it was *replaced* — so the
> colour check alone reads it as live and only the binding check sees it.
>
> **CORRECTED (2026-08-12).** This paragraph said *"Enforced from now on … if **any** design
> doc …"*. Both halves were wider than the code and are REFUTED; the rescoped wording above
> is the claim. (1) `DESIGN_DOCS` enumerates two paths, so a NEW design doc gets zero
> coverage until it is added to that tuple. A third one already exists —
> `docs/plans/v1.5/DESIGN-DIRECTION.md`, `**Status:** ACTIVE`, same basename — and is
> deliberately NOT covered: its off-token hexes are a prototype-**rejection** table quoted in
> order to forbid them, so admitting it without a use-vs-mention narrowing would emit false
> positives, and widening the tuple needs that narrowing first. `C8-scope-prose` catches a
> re-widening of this paragraph **only in the UNEMPHASISED, unwrapped spelling**. MEASURED
> 2026-08-12, and re-derived on every run by `C8-scope-measured` rather than pinned to a commit
> a reader may not have: its pattern needs literal whitespace between the words, so the
> `**any** design doc` quoted above, `*any* design doc`, and a re-widening that wraps across a
> blockquote continuation all report GREEN — it is a partial re-introduction guard, not a ban.
> (This sentence used to read "now fails if this paragraph re-widens to a universal", which was
> the same over-wide-promise defect the paragraph above retracts, one level up. Widening the
> pattern would fire on that retraction itself, so the repair is the wording; `C8-scope-measured`
> re-measures the shipped pattern every run so this qualifier cannot go stale unnoticed.)
> (2) "Enforced" overstated a **manual** verifier:
> no CI job and no `pre-commit` hook invokes it. Run it yourself —
> `python docs/validation/tools/verify_ssot_claims.py`. Settling experiment for the unwired
> claim: `git grep -n verify_ssot_claims -- .github/ .pre-commit-config.yaml` returns zero
> hits.
>
> **What these two checks currently examine in THIS file is zero and zero** — every hex above
> now sits inside a retraction blockquote, which they skip by design — so here they are a
> re-introduction guard, not a live measurement. They bite on `docs/design-system.md`. The
> per-doc examined counts are printed by the run itself (`examined N colour value(s)` /
> `examined N token binding(s)`) and deliberately not retyped here, because a hand-written
> count in this corpus has drifted every time.

**Read the values from `app/renderer/src/styles/tokens.css`.** The portable spec derived from
it is [`docs/design-system.md`](../design-system.md) (ACTIVE), guarded by
`app/renderer/src/styles/tokens.conformance.test.ts`. What survives below is *direction* —
the rules for how the ladder is used, which do not go stale when a hex moves.

### Surface ladder (depth = tone, not borders)

Six rungs, `--surface-deep` → `--surface-active`, luminance climbing monotonically. Media
wells (player strip, thumbnails, timeline lane, progress tracks, inputs) step DOWN to
`--surface-deep` so footage floats in black; the canvas is `--surface-bg`; cards, app bar,
tab strip and panels sit one step toward the user at `--surface-raised`; the JobQueue
slide-over, toasts and popovers float above everything at `--surface-overlay`; hover and
pressed are `--surface-hover` / `--surface-active`.

Edges are hairlines used sparingly: `--edge`, and `--edge-strong` where a seam must read.
If you're reaching for a border to separate two regions, change the surface tone instead.

### Text ladder

`--text-primary` → `--text-secondary` → `--text-muted` → `--text-faint`. Four real steps —
pick the step, don't invent grays. Muted is the LOUDER label voice and must stay lighter
than faint; the ordering and the AA floor on every plane are pinned by the conformance test.

### The accent: **Signal Amber** (`--accent`)

`--accent-hover` · `--accent-pressed` · ink-on-accent `--accent-ink` · soft wash
`--accent-soft` · edge/ring `--accent-edge`. Warm tungsten amber — the
edit-room lamp, the Resolve-school selection color — deliberately not template blue.

**Accent MAY be used for (semantic only):**
- **Progress in motion** — all progress fills (`.progress__fill`, native `<progress>`, JobQueue bar), `running` status text, the proxy-build player note.
- **Active / selected** — active tab underline, selected ShortMaker candidate rail, selected timeline cue, playhead, `is-active` quality segment, expanded Jobs toggle, in/out preview markers, the brand tick.
- **Approve / primary action** — exactly one accent-filled button per surface: Add videos, panel submit (Find clips / Transcribe / Convert…), Approve, Export approved.
- Focus rings (shared `--focus-ring` double ring) and `accent-color` on checkboxes.

**Accent may NOT be used for:** body text or links, icons at rest, borders/dividers,
empty/loading states, toasts (status colors own those), hover states of neutral controls,
secondary/cancel/remove buttons, badges that merely label (transcript badge = success-soft),
or any second accent-filled button on the same surface. If everything glows amber, nothing
is in progress.

### Status (never decorative)

`--status-success` · `--status-error` · `--status-warn` (yellow-leaning, distinct from the
orange-leaning accent; warn always rides on text/labels, e.g. ShortMaker's "(nudged)").
Each has a `-soft` wash for chips/banners. Errors are left-edge banners (3px rail + soft
wash), not red boxes. Red STRINGS use the lighter `--status-error-text` step, which the
solid signal red is too dark to satisfy AA for.

---

## Type pairing (system stack, weighted deliberately)

> **CORRECTED (2026-08-12, measured at `1fa9a69f`).** All three bullets below described a
> system-font stack that the tree no longer ships. `app/renderer/src/styles/fonts.css`
> binds three bundled OFL faces with `@font-face` — Inter, IBM Plex Mono and Newsreader —
> and `app/renderer/src/styles/tokens.css` heads each stack with the bundled face, so the
> system names in those stacks are FALLBACKS, not the design. Previous wording, refuted:
> UI sans *"(system-ui stack)"*; editorial serif *"(Georgia…)"* and *"ONE place only: the
> ShortMaker hook line"*. The one-site limit was already overtaken by 15 real uses —
> see `docs/design-system.md` and `docs/plans/v1.5/uiux-qol-audit-2026-08.md` §3.1.

- **UI sans** `--font-ui` (**Inter**, self-hosted; system stack only as fallback) — weight
  does the talking: display 750/-0.022em, titles 650/-0.01em, body 400.
- **Mono** `--font-mono` (**IBM Plex Mono**, self-hosted) — the *editing-room voice*: every
  timecode, duration badge, percent, file path, rank score. Always `tabular-nums`.
- **Editorial serif** `--font-editorial` (**Newsreader**, self-hosted) — a SCARCE channel,
  not a one-site rule: hook pull-quotes, empty-state titles, and panel/modal display titles.
  Never body text, labels, controls, data/timecode, or view headers. New sites need an
  entry in the `tokens.conformance.test.ts` allowlist, so spreading it is a reviewed
  decision rather than drift.

Scale: display 30px (Library title) · title 17px (Workspace/panel titles) · body 13px ·
caption 11px/600/+0.08em tracked CAPS (all labels, tabs, statuses, field names). The jump
from 11px caps to 24–30px numerals/titles is the hierarchy engine — don't flatten it.

Spacing: 4px-base rhythm `--space-1..8` (2/4/8/12/16/24/32/48), used asymmetrically
(headers breathe at 24, card internals sit at 8–12). Radius: 4/6/10/14/pill — chips <
buttons < cards < wells. Motion: 120/180/260ms with `--ease-out`
`cubic-bezier(0.16,1,0.3,1)`; reduced-motion collapses all of it.

---

## Per-surface notes

**Library grid** — Display-scale "Library" title; cards are `--surface-raised` with NO
border: hover = tone-up + lift (−2px translate + `--shadow-raise`) + slow 1.03 poster zoom;
focus-visible = shared ring; active = press-down. Poster sits in a deep well; duration badge
is mono tabular on `--surface-deep`. Path lines are faint mono. Transcript badge =
success-soft chip (labels, doesn't shout). Drag-over = inset amber ring + wash across the
whole canvas (it IS an active state). Add videos = the surface's one amber button.

**Workspace tabs** — Tab strip is a raised tonal seam (inset hairline, no border-bottom
rule). Tabs are 11px tracked-caps: muted → secondary on hover (with a gray underline ghost)
→ primary + 2px amber underline when active. The underline is the only amber in the chrome.

**Panels (Transcribe/Subtitles/Tracks/Convert/Dub/Assets)** — 17px/650 titles; field labels
in tracked caps over deep-well inputs (hairline border, brightens on hover). One amber
button per panel (submit / first action), everything else ghost; cancel/`.secondary` stays
neutral, remove-ish hovers go error-soft. Rows (tracks/assets/audio) are raised cards that
tone-up on hover. Progress = amber fill in a deep track + mono percent. Errors/status =
left-rail banners.

**ShortMaker review** — The richest surface, so the strictest rationing: preview floats in a
deep well with amber in/out timecode markers; candidate cards are raised with a 3px left
rail — transparent at rest, **amber = selected**, green = approved; discarded fades to 55%.
Inside a card: #rank is a 24px/800 tabular numeral (the big number), score is mono caption,
status is a caps chip (soft semantic fills), the hook is the serif pull-quote, why-text is
secondary body, times are faint mono with warn-colored "(nudged)". Nudge buttons are tiny
mono ghosts; Approve is the amber action, Discard hovers error-soft. Export strip repeats
the count in 650 weight next to the amber Export button.

**JobQueue** — `--surface-overlay` slide-over (260ms ease-out slide, heavy
`--shadow-overlay`, no border-left). Caps "JOBS" header; each job is a tone-step card
(hover tone-up). Status text is the semantic legend: running = amber, done = green,
error = red. Bar = amber fill in a deep pill track; percent = mono tabular right-aligned.
Retry hovers amber-soft (it restarts progress), Cancel hovers error-soft. The header Jobs
pill goes amber-soft only while expanded (active state).

**Toasts** — Overlay surface + `--shadow-overlay`, 10px radius, rise-in 260ms. The 3px left
edge is the only color: neutral hairline for info, green success, red error. No amber ever
(a toast is a report, not an active thing). Action button is a neutral raised chip;
close is a ghost ×. The Library's inline fallback strip mirrors the same anatomy.

---

## Anti-template gate (review checklist)

1. Hierarchy via scale contrast — 30px display + 24px ranks vs 11px tracked caps.
2. Color used semantically — amber strictly progress/active/approve; status trio elsewhere.
3. Depth via layered surfaces/shadow — 4-step ladder + wells; borders almost eliminated.
4. Designed hover/focus/active everywhere — tone-up + lift + zoom on cards, ghost underline
   on tabs, press-down on buttons, one double focus ring across the app.
5. Type with character — mono timecode voice + a single serif pull-quote moment.
6. Intentional rhythm — 4px scale used asymmetrically, not uniform padding.
