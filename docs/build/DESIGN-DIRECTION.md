# DESIGN-DIRECTION — media-studio

**Direction: Dark Editorial.** media-studio is a video tool, so it follows the rule every
serious video app follows: the footage is the brightest, most saturated thing on screen.
The chrome is near-black and tonal; hierarchy comes from type contrast (big numbers and
titles, quiet tracked-caps labels); depth comes from a layered surface ladder and shadow —
not borders around everything. One accent, used semantically, never decoratively.

Single source of truth: `app/renderer/src/styles/tokens.css` (imported first in `App.tsx`).
No component sheet may introduce a color, radius, duration, or font that is not a token.

---

## Palette (exact values)

### Surface ladder (depth = tone, not borders)

| Token | Value | Use |
|---|---|---|
| `--surface-deep` | `#08090b` | Media wells: player strip, thumbnails, timeline lane, progress tracks, inputs |
| `--surface-bg` | `#0e0f12` | The app canvas |
| `--surface-raised` | `#16181d` | Cards, app bar, tab strip, panels — one step toward the user |
| `--surface-overlay` | `#1d2026` | JobQueue slide-over, toasts, popovers — floats above all |
| `--surface-hover` | `#22252d` | Hover tint |
| `--surface-active` | `#2a2e38` | Pressed tint |

Edges are hairlines used sparingly: `--edge` `rgba(255,255,255,0.07)`,
`--edge-strong` `rgba(255,255,255,0.15)`. If you're reaching for a border to separate
two regions, change the surface tone instead.

### Text ladder

`--text-primary` `#f4f5f7` · `--text-secondary` `#b0b6c0` · `--text-muted` `#7d8390` ·
`--text-faint` `#50555f`. Four real steps — pick the step, don't invent grays.

### The accent: **Signal Amber** `#f2a33c`

Hover `#ffb554` · pressed `#d88a1f` · ink-on-accent `#211404` · soft wash
`rgba(242,163,60,.14)` · edge/ring `rgba(242,163,60,.5)`. Warm tungsten amber — the
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

`--status-success` `#46c483` · `--status-error` `#e5484d` · `--status-warn` `#e7c14b`
(yellow-leaning, distinct from the orange-leaning accent; warn always rides on text/labels,
e.g. ShortMaker's "(nudged)"). Each has a `-soft` wash for chips/banners. Errors are
left-edge banners (3px rail + soft wash), not red boxes.

---

## Type pairing (system stack, weighted deliberately)

- **UI sans** `--font-ui` (system-ui stack) — weight does the talking: display 750/-0.022em,
  titles 650/-0.01em, body 400.
- **Mono** `--font-mono` (ui-monospace…) — the *editing-room voice*: every timecode,
  duration badge, percent, file path, rank score. Always `tabular-nums`.
- **Editorial serif** `--font-editorial` (Georgia…) — ONE place only: the ShortMaker hook
  line, set 15px italic like a pull-quote. It is the editorial signature; do not spread it.

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
