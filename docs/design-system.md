# Reframe Design System (v1.4)

Codified from the v1.4 token system (`app/renderer/src/styles/tokens.css`) — guarded by
`tokens.conformance.test.ts` (WCAG-AA on every plane, cool-cast, monotonic ladder, one-accent discipline,
no undefined tokens, no raw font-weight/size). Mood: **cool blue-gray dark-editorial** + a single **signal-amber**
accent. Source of truth = `tokens.css`; this doc is the portable spec, ready to push to a Figma library via the
`figma-generate-library` flow. Figma auth verified (Prekzursil, Full seat).

## Color

### Surface ladder — depth via TONE (cool-cast `b > g > r` locked, monotonic luminance)
| Token | Hex | Role |
|---|---|---|
| `--surface-deep` | `#0b0d12` | media wells (darkest) |
| `--surface-bg` | `#121620` | canvas |
| `--surface-raised` | `#1b212e` | cards / panels / headers |
| `--surface-overlay` | `#252d3d` | slide-overs / toasts / popovers |
| `--surface-hover` | `#2c3448` | interaction tint |
| `--surface-active` | `#353f56` | interaction tint |
| `--edge` | `rgba(255,255,255,.09)` | hairlines · `--edge-strong` `.15` |

### Text ladder (AA ≥4.5:1 on all four planes + hover/active — conformance-guarded)
`--text-primary #f4f5f7` > `--text-secondary #b0b6c0` > `--text-muted #adb4c2` (louder label voice) >
`--text-faint #a6aebd` (quietest).

### Accent — SEMANTIC (progress / active / approve ONLY)
`--accent #f2a33c` · hover `#ffb554` · pressed `#d88a1f` · ink `#211404` · `--accent-soft rgba(.14)` ·
`--accent-edge rgba(.5)` · `--accent-glow` (lit-from-within). Rationed: at most one accent touchpoint per surface.

### Status (separate from accent)
`--status-success #46c483` · `--status-error #e5484d` · `--status-warn #e7c14b` (+ `-soft`).
Sanctioned off-ladder exception: abundance `--abundance #9b6cff` (never color-alone).

## Type (role = size / weight / tracking / leading)
| Role | Size | Weight | Notes |
|---|---|---|---|
| display | `--type-display-size 30` | 750 | view titles; `-.022em` |
| subhead | `--type-subhead-size 22` | — | fills the title→display gap |
| title | `--type-title-size 17` | 650 | `-.01em` |
| body | `--type-body-size 13` | `var(--weight-regular)` 400 | leading 1.5 |
| caption | `--type-caption-size 11` | 600 | tracked CAPS = label voice |
| control | `--type-control-size 12` | `--weight-medium` | buttons/tabs/toggles |
| card-title 14 · hook 15 · rank 24 · chip 10 | — | — | role tokens |

**Weight ramp:** `--weight-regular 400 / -medium 600 / -semibold 650 / -bold 700 / -heavy 800`.
**Fonts:** `--font-ui` (system sans) · `--font-mono` (ui-monospace — timecode, tabular-nums) ·
Georgia editorial serif (ShortMaker hook pull-quotes ONLY).

## Spacing (4px base) & Radius
Space: `2 / 4 / 8 / 12 / 16 / 24 / 32 / 48` (`--space-1…8`).
Radius: `--radius-xs 4 / -sm 6 / -md 10 / -lg 14 / -pill 999`.
Control padding: `--control-pad-toggle/-btn/-input/-toptab/-tab/-mini`. Sizes: `--size-icon 18 / -glyph 20 /
-glyph-lg 26 / -dot 8 / -dot-sm 5`.

## Elevation & Motion
Elevation: `--elev-0` flush → `--elev-3` floating (each = inset top-highlight + drop) + `--shadow-raise` /
`--shadow-overlay`, `--atmos-toplight` (bar sheen), `--atmos-well` (media-well vignette), `--scrim-bottom`.
Motion: `--dur-fast 120` (hover/color) / `--dur-base 180` (fills/lifts) / `--dur-slow 260` (overlays);
`--ease-out cubic-bezier(.16,1,.3,1)` / `--ease-in-out`. Global `prefers-reduced-motion` collapse.

## Components
- **Button voices** — RAISED (surface + edge + `--elev-1`), GHOST (transparent, tint on hover), ACCENT (accent
  fill + `--accent-glow`, one per surface), DESTRUCTIVE-GHOST (error on hover). *Debt (v1.5): factor into
  `.btn--*` variant classes (currently feature-namespaced selector lists).*
- **Card** — raised, no border, `--elev-1` at rest → `--shadow-raise` + `translateY(-3px)` on hover → active;
  `--radius-md`; gradient scrim under the timecode badge; provenance chip row.
- **Tabs** — muted → active accent text + soft wash + a 2px accent underline (shape *and* color).
- **Input** — `--surface-deep` + 1px edge; focus = accent edge + `--focus-glow`.
- **Banner** — overlay + status wash + left rail: warn = amber pulse, error = red static.
- **Chip / status dot** — pill on `--surface-hover`, tracked micro-caps + a status dot.
- **Empty state** — shared ghost-poster (deep 16:9 well + play glyph + mono timecode + peeking second poster +
  display-scale title). Applied to Library / Make Shorts / Edit / Director / Assets.
- **Skeleton** — card-shaped shimmer (pulse off `--surface-hover`, staggered delays), layout-stable.
- **Focus** — one global double `--focus-ring` on every `button/[role=button]/[role=tab]/input/[tabindex]:focus-visible`.

## Header controls (disambiguated, v1.4)
Two genuinely-distinct settings, kept separate with a seam divider + shared Local/Cloud vocab + distinct scope
labels: **"AI model"** (`settings.useCloud` — where models run) vs **"Where jobs run"** (`routingPolicy.global`
Local/Cloud/Auto). A tokenized egress dot on cloud-capable modes; a live Jobs status pill.
