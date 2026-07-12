// tokens.conformance.test.ts — design-system one-accent discipline guard (WU A6).
//
// tokens.css states the rule of use: "Consume tokens only — no one-off hex values
// in component CSS." The usage panel's animated "superpowered / high-headroom"
// state historically shipped ad-hoc purple hex (#9b6cff / rgba(155,108,255,…) /
// #c2a3ff) baked straight into usageBar.css — an accent OFF the single-accent
// amber + RYG status ladder, undocumented as a token.
//
// These tests assert the reconcile:
//   1. usageBar.css carries NO raw color literals — every color routes through a
//      token custom property (var(--…)); and
//   2. the one sanctioned off-ladder exception (the "abundance" hue) is a
//      DOCUMENTED semantic token in tokens.css, not an ad-hoc component value.
//
// This file imports no TS source; it is a pure style-file conformance check and
// is excluded from the renderer coverage scope (styles are .css, not .ts/.tsx).

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join, relative } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const TOKENS_CSS = resolve(HERE, 'tokens.css');
const USAGE_BAR_CSS = resolve(HERE, '..', 'components', 'usageBar.css');
// Component sheets the WU-D1 TYPE/WEIGHT/CONTROL scale routes through.
const SHELL_CSS = resolve(HERE, '..', 'components', 'shell.css');
const TOPTAB_CSS = resolve(HERE, '..', 'components', 'topTabBar.css');
const LIB_CARDS_CSS = resolve(HERE, '..', 'components', 'library-cards.css');

/** Every raw color literal in a stylesheet: #rgb/#rrggbb(/aa) and rgb()/rgba(). */
const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(/g;

/** Strip `/* … *\/` comment blocks so documentation prose never trips the scan. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

describe('design-system one-accent discipline (WU A6)', () => {
  it('usageBar.css uses NO raw color literals — colors route through tokens only', () => {
    const css = stripComments(readFileSync(USAGE_BAR_CSS, 'utf8'));
    const leaks = css.match(RAW_COLOR) ?? [];
    expect(leaks).toEqual([]);
  });

  it('usageBar.css consumes the documented abundance token for the superpowered state', () => {
    const css = readFileSync(USAGE_BAR_CSS, 'utf8');
    // The border + wash + label of the superpowered group all go through the token.
    expect(css).toMatch(/var\(--status-abundance\)/);
    expect(css).toMatch(/var\(--status-abundance-soft\)/);
    expect(css).toMatch(/var\(--status-abundance-text\)/);
  });

  it('tokens.css DOCUMENTS the abundance hue as the single sanctioned off-ladder token', () => {
    const css = readFileSync(TOKENS_CSS, 'utf8');
    // The token family is defined (base / soft / text) alongside the RYG statuses…
    expect(css).toMatch(/--status-abundance:\s*#[0-9a-fA-F]{3,8}/);
    expect(css).toMatch(/--status-abundance-soft:\s*rgba?\(/);
    expect(css).toMatch(/--status-abundance-text:\s*#[0-9a-fA-F]{3,8}/);
    // …and is explicitly documented as the ONE exception to one-accent discipline.
    const doc = css.toLowerCase();
    expect(doc).toContain('abundance');
    expect(doc).toContain('exception');
  });
});

// --- WU-2a: dark-editorial surface-ladder recalibration guard --------------------
//
// The pain these tests pin: the ladder used to sit only ~4-6 luminance points apart
// on pure near-black, so a card, a panel and a media well merged into one flat
// plane ("feels like 1.1 / didn't see changes"). This block re-derives the WCAG
// relative-luminance + contrast math INDEPENDENTLY of tokens.css and asserts, as a
// REAL regression guard (not a value echo), that the recalibrated ladder is:
//   1. LIFTED off pure near-black,
//   2. COOL blue-gray (locked mood — blue channel dominant),
//   3. WIDENED into visibly distinct planes (minimum rung gaps), and
//   4. still AA for the faint text step (>=4.5:1) on every elevation plane.
// If anyone flattens the ladder back toward near-black, or warms/greys the tint,
// or drops faint below AA, these fail.

/** Parse every `--name: value;` custom property from tokens.css into a map. */
function readTokens(): Map<string, string> {
  const css = readFileSync(TOKENS_CSS, 'utf8');
  const map = new Map<string, string>();
  const decl = /(--[\w-]+):\s*([^;]+);/g;
  for (let m = decl.exec(css); m !== null; m = decl.exec(css)) {
    map.set(m[1], m[2].trim());
  }
  return map;
}

type Rgb = readonly [number, number, number];

/** #rrggbb -> [r, g, b] (0-255). Throws if the token is not a plain hex. */
function toRgb(tokens: Map<string, string>, name: string): Rgb {
  const raw = tokens.get(name);
  if (raw === undefined) throw new Error(`missing token ${name}`);
  const hex = /^#([0-9a-fA-F]{6})$/.exec(raw);
  if (hex === null) throw new Error(`token ${name} is not a plain hex: ${raw}`);
  const n = hex[1];
  return [
    Number.parseInt(n.slice(0, 2), 16),
    Number.parseInt(n.slice(2, 4), 16),
    Number.parseInt(n.slice(4, 6), 16),
  ];
}

/** sRGB channel -> linear (WCAG 2.x). */
function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance of an [r,g,b]. */
function relLum([r, g, b]: Rgb): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two colors. */
function contrast(a: Rgb, b: Rgb): number {
  const la = relLum(a);
  const lb = relLum(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

const ELEVATION_PLANES = [
  '--surface-deep',
  '--surface-bg',
  '--surface-raised',
  '--surface-overlay',
] as const;

// The transient interaction tints a card swaps its background to while the user
// hovers/presses it. They sit LIGHTER than the rest planes, so quiet text on a
// card must still clear AA against them — otherwise a timecode/label goes
// sub-4.5:1 the instant the card is touched. (WU-2d.)
const INTERACTION_PLANES = ['--surface-hover', '--surface-active'] as const;

describe('dark-editorial surface ladder recalibration (WU-2a)', () => {
  it('lifts the base OFF pure near-black (canvas is a real, not-black surface)', () => {
    const tokens = readTokens();
    const bg = toRgb(tokens, '--surface-bg');
    const deep = toRgb(tokens, '--surface-deep');
    // The canvas sits clearly above the media-well floor AND above a flat
    // near-black threshold (the old #0e0f12 canvas was ~0.0046).
    expect(relLum(bg)).toBeGreaterThan(0.006);
    expect(relLum(bg)).toBeGreaterThan(relLum(deep) * 1.4);
  });

  it('keeps the whole ladder COOL blue-gray (locked mood — blue channel dominant)', () => {
    const tokens = readTokens();
    for (const name of [
      '--surface-bg',
      '--surface-raised',
      '--surface-overlay',
      '--surface-hover',
      '--surface-active',
    ]) {
      const [r, g, b] = toRgb(tokens, name);
      // Blue leads, green sits between, red trails — a deliberate cool cast with
      // real margin, never a neutral or warm grey.
      expect(b).toBeGreaterThan(g);
      expect(g).toBeGreaterThan(r);
      expect(b - r).toBeGreaterThanOrEqual(8);
    }
  });

  it('WIDENS the ladder into monotonic, visibly distinct planes', () => {
    const tokens = readTokens();
    const order = [
      '--surface-deep',
      '--surface-bg',
      '--surface-raised',
      '--surface-overlay',
      '--surface-hover',
      '--surface-active',
    ];
    const lums = order.map((n) => relLum(toRgb(tokens, n)));
    for (let i = 1; i < lums.length; i += 1) {
      expect(lums[i]).toBeGreaterThan(lums[i - 1]);
    }
    // The canvas->card and card->overlay rungs (the actual "flat plane" complaint)
    // each carry a perceptible contrast step, and the total spread is real.
    expect(
      contrast(toRgb(tokens, '--surface-bg'), toRgb(tokens, '--surface-raised')),
    ).toBeGreaterThanOrEqual(1.1);
    expect(
      contrast(toRgb(tokens, '--surface-raised'), toRgb(tokens, '--surface-overlay')),
    ).toBeGreaterThanOrEqual(1.1);
    expect(
      contrast(toRgb(tokens, '--surface-deep'), toRgb(tokens, '--surface-overlay')),
    ).toBeGreaterThanOrEqual(1.3);
  });

  it('holds --text-faint at AA (>=4.5:1) on every elevation plane', () => {
    const tokens = readTokens();
    const faint = toRgb(tokens, '--text-faint');
    for (const plane of ELEVATION_PLANES) {
      expect(contrast(faint, toRgb(tokens, plane))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('holds --text-faint at AA (>=4.5:1) on the hover + active interaction tints too', () => {
    // WU-2d: cards flip their bg to --surface-hover / --surface-active on
    // interaction, so faint (its quietest text) must still clear AA there — not
    // just on the seated elevation planes.
    const tokens = readTokens();
    const faint = toRgb(tokens, '--text-faint');
    for (const plane of INTERACTION_PLANES) {
      expect(contrast(faint, toRgb(tokens, plane))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps a legible text hierarchy above the quiet steps', () => {
    const tokens = readTokens();
    const primary = relLum(toRgb(tokens, '--text-primary'));
    const secondary = relLum(toRgb(tokens, '--text-secondary'));
    const muted = relLum(toRgb(tokens, '--text-muted'));
    const faint = relLum(toRgb(tokens, '--text-faint'));
    // Primary reads loudest, secondary clearly above both quiet label steps.
    expect(primary).toBeGreaterThan(secondary);
    expect(secondary).toBeGreaterThan(muted);
    expect(secondary).toBeGreaterThan(faint);
    // WU-2d: muted is the LOUDER quiet step — it must sit lighter than faint
    // (fixes the WU-2a luminance inversion where muted was darker than faint).
    expect(muted).toBeGreaterThan(faint);
  });

  it('defines a layered elevation scale (e0 flush -> e3 lifted) for real depth', () => {
    const tokens = readTokens();
    expect(tokens.get('--elev-0')).toBe('none');
    // e1..e3 each pair an inset top-highlight with a drop shadow (layered depth),
    // and the ambient drop grows with height.
    for (const name of ['--elev-1', '--elev-2', '--elev-3']) {
      expect(tokens.get(name)).toContain('inset 0 1px 0');
    }
  });
});

// --- PR #290: red-text AA guard — error-alert text on the soft-error wash --------
//
// The error-alert TEXT (e.g. .director-view__error) sits on the translucent
// --status-error-soft wash. The saturated base --status-error (#e5484d),
// composited over that wash on the LIFTED elevation planes, drops to ~3.2-4.2:1 —
// a real WCAG 1.4.3 (AA) fail for body-size text. The fix is a dedicated red-TEXT
// token (--status-error-text, a lighter tint) mirroring the --status-abundance-text
// "lighter tint for AA on the wash" precedent. This guard re-derives the sRGB
// composite + WCAG contrast INDEPENDENTLY and pins that the red-text token clears
// 4.5:1 on EVERY elevation plane — and that it is genuinely lighter than (and the
// base red genuinely fails on) that wash — so alert text can never silently decay
// back to the sub-AA saturated red.

/** Parse an `rgba(r, g, b, a)` token into [r, g, b, a]. Throws if not an rgba(). */
function toRgba(
  tokens: Map<string, string>,
  name: string,
): readonly [number, number, number, number] {
  const raw = tokens.get(name);
  if (raw === undefined) throw new Error(`missing token ${name}`);
  const m = /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/.exec(raw);
  if (m === null) throw new Error(`token ${name} is not an rgba(): ${raw}`);
  return [Number(m[1]), Number(m[2]), Number(m[3]), Number.parseFloat(m[4])];
}

/** Alpha-composite a translucent wash over an opaque plane in sRGB 0-255 — how the
 * browser blends a background-color alpha over its backdrop (source-over). */
function over(wash: readonly [number, number, number, number], plane: Rgb): Rgb {
  const [wr, wg, wb, a] = wash;
  const [pr, pg, pb] = plane;
  return [a * wr + (1 - a) * pr, a * wg + (1 - a) * pg, a * wb + (1 - a) * pb];
}

describe('red-text token clears AA on the soft-error wash (PR #290)', () => {
  it('defines --status-error-text as a lighter tint than --status-error', () => {
    const tokens = readTokens();
    // toRgb throws unless the token is a plain #rrggbb; the text token is a
    // genuinely lighter red (the fix direction — it lifts the saturated base up to
    // an AA-legible tint on the wash), never a copy of the base value.
    expect(relLum(toRgb(tokens, '--status-error-text'))).toBeGreaterThan(
      relLum(toRgb(tokens, '--status-error')),
    );
  });

  it('holds --status-error-text at AA (>=4.5:1) on the wash over every elevation plane', () => {
    const tokens = readTokens();
    const text = toRgb(tokens, '--status-error-text');
    const wash = toRgba(tokens, '--status-error-soft');
    for (const plane of ELEVATION_PLANES) {
      expect(contrast(text, over(wash, toRgb(tokens, plane)))).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('proves the base --status-error FAILS AA on that wash (why the token exists)', () => {
    // Documents the exact regression the token fixes: the base red on the wash
    // drops below AA on the lifted planes (here --surface-raised, ~3.75:1), so a
    // component MUST route alert text through --status-error-text, not --status-error.
    const tokens = readTokens();
    const base = toRgb(tokens, '--status-error');
    const wash = toRgba(tokens, '--status-error-soft');
    expect(contrast(base, over(wash, toRgb(tokens, '--surface-raised')))).toBeLessThan(4.5);
  });
});

// --- WU-D1: TYPE / WEIGHT / CONTROL token-scale completeness guard ---------------
//
// The design review found the type layer incomplete: NO font-weight tokens (raw
// 400/600/650/700/800 scattered through the component CSS) and a spray of orphan
// font-sizes outside the 4-rung scale (the 12px control size on every
// button/tab/toggle, plus 10/14/15/24px roles and a 17->30 subhead gap), and the
// control geometry (18px icon, 5/8px dots, the off-grid control paddings) sat as
// raw px. WU-D1 pulls all of it onto ONE token vocabulary. These tests are the
// REAL guard: they pin the ramp order + the exact role/control values AND assert
// the component sheets carry NO raw font-weight/font-size (so nobody can silently
// re-scatter raw values), and that every new token is actually CONSUMED — not just
// defined then abandoned.

/** A raw numeric font-weight (`font-weight: 600`), i.e. NOT `var(--weight-…)`. */
const RAW_FONT_WEIGHT = /font-weight:\s*\d/g;
/** A raw pixel font-size (`font-size: 12px`), i.e. NOT `var(--type-…)`. */
const RAW_FONT_SIZE = /font-size:\s*\d+px/g;

describe('type / weight / control token scale (WU-D1)', () => {
  it('defines an ordered font-weight ramp (regular -> heavy), monotonically increasing', () => {
    const tokens = readTokens();
    const ramp = [
      '--weight-regular',
      '--weight-medium',
      '--weight-semibold',
      '--weight-bold',
      '--weight-heavy',
    ] as const;
    const values = ramp.map((name) => {
      const raw = tokens.get(name);
      if (raw === undefined) throw new Error(`missing weight token ${name}`);
      return Number.parseInt(raw, 10);
    });
    // Exact numeric contract — the scattered raw weights the ramp replaces.
    expect(values).toEqual([400, 600, 650, 700, 800]);
    // Strictly increasing, so the ladder can never invert.
    for (let i = 1; i < values.length; i += 1) {
      expect(values[i]).toBeGreaterThan(values[i - 1]);
    }
    // The display composite sits inside the heavy tier: bold < display(750) < heavy.
    const display = Number.parseInt(tokens.get('--type-display-weight') ?? '', 10);
    expect(display).toBeGreaterThan(values[3]);
    expect(display).toBeLessThan(values[4]);
  });

  it('defines the role type-size tokens the design review pulled back onto the scale', () => {
    const tokens = readTokens();
    const sizes: Readonly<Record<string, string>> = {
      '--type-subhead-size': '22px',
      '--type-control-size': '12px',
      '--type-card-title-size': '14px',
      '--type-hook-size': '15px',
      '--type-rank-size': '24px',
      '--type-chip-size': '10px',
    };
    for (const [name, px] of Object.entries(sizes)) {
      expect(tokens.get(name)).toBe(px);
    }
    // The subhead rung genuinely fills the title(17) -> display(30) gap.
    const px = (name: string): number => Number.parseInt(tokens.get(name) ?? '', 10);
    expect(px('--type-subhead-size')).toBeGreaterThan(px('--type-title-size'));
    expect(px('--type-subhead-size')).toBeLessThan(px('--type-display-size'));
  });

  it('defines the control-sizing tokens (icon + glyph + dots + control padding)', () => {
    const tokens = readTokens();
    expect(tokens.get('--size-icon')).toBe('18px');
    expect(tokens.get('--size-glyph')).toBe('20px');
    expect(tokens.get('--size-glyph-lg')).toBe('26px');
    expect(tokens.get('--size-dot')).toBe('8px');
    expect(tokens.get('--size-dot-sm')).toBe('5px');
    // A dot is smaller than a control icon (geometry sanity, not just presence).
    expect(Number.parseInt(tokens.get('--size-dot') ?? '', 10)).toBeLessThan(
      Number.parseInt(tokens.get('--size-icon') ?? '', 10),
    );
    // Control paddings are `<y>px <x>px` shorthands (value preserved, no restyle).
    for (const name of [
      '--control-pad-toggle',
      '--control-pad-btn',
      '--control-pad-input',
      '--control-pad-toptab',
      '--control-pad-tab',
      '--control-pad-mini',
    ]) {
      expect(tokens.get(name)).toMatch(/^\d+px \d+px$/);
    }
  });

  it('routes the component sheets through the tokens — NO raw font-weight/size survives', () => {
    for (const path of [SHELL_CSS, TOPTAB_CSS, LIB_CARDS_CSS]) {
      const css = stripComments(readFileSync(path, 'utf8'));
      expect(css.match(RAW_FONT_WEIGHT) ?? []).toEqual([]);
      expect(css.match(RAW_FONT_SIZE) ?? []).toEqual([]);
    }
  });

  it('proves the ramp + role + control tokens are actually CONSUMED (a real guard)', () => {
    const shell = stripComments(readFileSync(SHELL_CSS, 'utf8'));
    const toptab = stripComments(readFileSync(TOPTAB_CSS, 'utf8'));
    const cards = stripComments(readFileSync(LIB_CARDS_CSS, 'utf8'));
    // Weight ramp: the regular rung is consumed by the body-weight token itself
    // (--type-body-weight routes through var(--weight-regular), so the ramp is DRY
    // and no rung is a defined-then-abandoned orphan); the rest are consumed
    // explicitly in the shell.
    expect(readTokens().get('--type-body-weight')).toBe('var(--weight-regular)');
    for (const name of [
      '--weight-medium',
      '--weight-semibold',
      '--weight-bold',
      '--weight-heavy',
    ]) {
      expect(shell).toContain(`var(${name})`);
    }
    // Type role sizes.
    for (const name of [
      '--type-control-size',
      '--type-card-title-size',
      '--type-hook-size',
      '--type-rank-size',
      '--type-chip-size',
      '--type-subhead-size',
    ]) {
      expect(shell).toContain(`var(${name})`);
    }
    // Control sizing: dots + glyphs in the shell/cards, the icon slot in the top tabs.
    expect(shell).toContain('var(--size-dot)');
    expect(shell).toContain('var(--size-dot-sm)');
    expect(shell).toContain('var(--size-glyph)');
    expect(cards).toContain('var(--size-glyph-lg)');
    expect(toptab).toContain('var(--size-icon)');
    // Control padding role tokens.
    for (const name of [
      '--control-pad-toggle',
      '--control-pad-btn',
      '--control-pad-input',
      '--control-pad-tab',
      '--control-pad-mini',
    ]) {
      expect(shell).toContain(`var(${name})`);
    }
    expect(toptab).toContain('var(--control-pad-toptab)');
  });
});

// --- WU-D7: no undefined custom-property references anywhere in renderer CSS -----
//
// The design review found REPO-WIDE token sprawl: ~17 renderer sheets referenced
// custom properties that tokens.css never defines (e.g. --surface-1/2,
// --border-subtle, --type-small-size, --surface-edge, --status-danger,
// --status-warning, --muted, --text, --surface, --color-*). Several had NO
// fallback, so the whole declaration was INVALID and silently dropped — broken /
// off-theme styling that no test caught. WU-D7 remaps every one onto a REAL token
// (surface ladder / text ladder / --edge / --status-* / --type-* / --weight-* /
// --space-* / --radius-*).
//
// This is the REAL guard so it can never regress: it walks EVERY renderer *.css,
// collects the union of all DEFINED custom properties (tokens.css plus the handful
// of locally-scoped ones like --timeline-wave), then asserts that EVERY var(--x)
// reference — including tokens nested inside fallbacks — resolves to a defined
// property. A single stray var(--not-a-token) fails the suite with the offending
// token + file, so the sprawl cannot silently creep back.

const RENDERER_SRC = resolve(HERE, '..');

/** Recursively collect every `*.css` file path under a directory. */
function collectCssFiles(dir: string): readonly string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectCssFiles(full));
    } else if (entry.isFile() && entry.name.endsWith('.css')) {
      out.push(full);
    }
  }
  return out;
}

/** All custom-property NAMES defined (`--name: value;`) in a stylesheet body. */
function definedProps(css: string): readonly string[] {
  const decl = /(--[\w-]+)\s*:/g;
  const names: string[] = [];
  for (let m = decl.exec(css); m !== null; m = decl.exec(css)) {
    names.push(m[1]);
  }
  return names;
}

describe('no undefined custom-property references in renderer CSS (WU-D7)', () => {
  const cssFiles = collectCssFiles(RENDERER_SRC);

  it('finds the renderer stylesheets (guard is actually scanning something)', () => {
    // A dead scan that matches zero files would vacuously "pass" — pin a floor so
    // the guard proves it is exercising the real sheet set (there are dozens).
    expect(cssFiles.length).toBeGreaterThan(20);
    expect(cssFiles.some((f) => f.endsWith('tokens.css'))).toBe(true);
  });

  it('resolves EVERY var(--x) to a token defined somewhere in the renderer CSS', () => {
    // Union of every defined custom property: the tokens.css design system plus any
    // locally-scoped props a sheet declares for its own use (e.g. --timeline-wave).
    const defined = new Set<string>();
    for (const file of cssFiles) {
      for (const name of definedProps(stripComments(readFileSync(file, 'utf8')))) {
        defined.add(name);
      }
    }

    // Collect every reference that does NOT resolve, tagged with its file so a
    // failure names exactly what to fix.
    const offenders: string[] = [];
    for (const file of cssFiles) {
      const css = stripComments(readFileSync(file, 'utf8'));
      const ref = /var\(\s*(--[\w-]+)/g;
      for (let m = ref.exec(css); m !== null; m = ref.exec(css)) {
        if (!defined.has(m[1])) {
          offenders.push(`${relative(RENDERER_SRC, file).replace(/\\/g, '/')}: var(${m[1]})`);
        }
      }
    }

    // Empty is the only acceptable state — every consumed token must be real.
    expect(offenders).toEqual([]);
  });
});

// --- v1.5 pro-shell token evolution (Wave-2) -------------------------------------
//
// The v1.5 redesign consumes the SHIPPED tokens (never the prototype's literal
// hex — §5.A) and evolves the layer DELIBERATELY (§5.B): real bundled type faces
// leading the UI / editorial / mono families, and a glass / floating-surface
// layer for the produced-shorts modal (and the Cmd-K palette when it ships,
// §7.5). These are the LOCK on that evolution — additive to the guards above,
// never a weakening of them. A font family that decays back to a bare generic
// (`system-ui` / `Georgia` / `ui-monospace` leading), or a glass layer that
// loses its translucency / blur, fails here.

/** The FIRST family in a `font-family` list (before the first comma), trimmed. */
function leadFamily(value: string): string {
  return (value.split(',')[0] ?? '').trim().replace(/^["']|["']$/g, '');
}

/** The alpha channel of an `rgba(r,g,b,a)` value, or NaN when not an rgba(). */
function rgbaAlpha(value: string): number {
  const m = /rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)/.exec(value);
  return m ? Number.parseFloat(m[1]) : Number.NaN;
}

describe('v1.5 shell token evolution — type faces (WU-1.5)', () => {
  it('leads --font-ui with a bundled non-generic face (Inter / Geist), keeping a system fallback', () => {
    const value = readTokens().get('--font-ui') ?? '';
    // The lead is a real bundled UI face, NOT the generic system-ui the prototype
    // superseded (§5.B). A system fallback stays LAST so it renders before the
    // @font-face binaries are bundled (documented follow-up).
    expect(['Inter', 'Geist']).toContain(leadFamily(value));
    expect(value).toContain('system-ui');
    expect(value.trimEnd()).toMatch(/sans-serif;?$/);
  });

  it('sets --font-editorial to Newsreader with a serif fallback (the pull-quote voice)', () => {
    const value = readTokens().get('--font-editorial') ?? '';
    // Newsreader supersedes the stale Georgia lead; a generic serif stays as the
    // fallback so the editorial voice never collapses to sans.
    expect(leadFamily(value)).toBe('Newsreader');
    expect(value.trimEnd()).toMatch(/serif;?$/);
  });

  it('leads --font-mono with a bundled mono face, keeping a monospace fallback (timecode voice)', () => {
    const value = readTokens().get('--font-mono') ?? '';
    expect(leadFamily(value)).toBe('IBM Plex Mono');
    expect(value.trimEnd()).toMatch(/monospace;?$/);
  });
});

describe('v1.5 shell token evolution — glass / floating-surface layer (WU-1.5)', () => {
  it('defines a translucent glass surface + a real backdrop-blur radius', () => {
    const tokens = readTokens();
    // The glass surface is the raised plane at REDUCED opacity so a backdrop-blur
    // reads through it — a solid fill would defeat the layer.
    const glass = tokens.get('--surface-glass') ?? '';
    const alpha = rgbaAlpha(glass);
    expect(alpha).toBeGreaterThan(0);
    expect(alpha).toBeLessThan(1);
    // A non-zero px blur radius (the layer is meaningless at 0).
    const blur = tokens.get('--glass-blur') ?? '';
    expect(blur).toMatch(/^\d+px$/);
    expect(Number.parseInt(blur, 10)).toBeGreaterThan(0);
  });

  it('defines the centered-surface scrim + measure (modal now, Cmd-K palette later)', () => {
    const tokens = readTokens();
    // The scrim that dims the canvas behind a centered floating surface: a
    // translucent dark wash (alpha < 1 so the app stays faintly visible behind).
    const scrim = tokens.get('--overlay-scrim') ?? '';
    const alpha = rgbaAlpha(scrim);
    expect(alpha).toBeGreaterThan(0);
    expect(alpha).toBeLessThan(1);
    // A pixel max-measure so the floating surface never spans an ultrawide window.
    expect(tokens.get('--overlay-width') ?? '').toMatch(/^\d+px$/);
  });
});

describe('v1.5 shell token evolution — locks the reconciled §5.A guardrails (WU-1.5)', () => {
  it('pins the ink-on-accent value the redesign must bind (never the prototype #1a1205)', () => {
    expect(readTokens().get('--accent-ink')).toBe('#211404');
  });

  it('keeps --text-faint OFF the rejected sub-AA #50555F (the WCAG 1.4.3 regression)', () => {
    // The prototype re-introduced #50555F (~2.4:1) on quiet text; the shipped faint
    // step is a real AA tone. Guard the exact rejected value can never creep back.
    const faint = (readTokens().get('--text-faint') ?? '').toLowerCase();
    expect(faint).not.toBe('#50555f');
  });

  it('pins the motion ladder (fast < base < slow) + a real easing curve', () => {
    const tokens = readTokens();
    const ms = (name: string): number => Number.parseInt(tokens.get(name) ?? '', 10);
    const fast = ms('--dur-fast');
    const base = ms('--dur-base');
    const slow = ms('--dur-slow');
    expect(fast).toBe(120);
    expect(base).toBe(180);
    expect(slow).toBe(260);
    expect(fast).toBeLessThan(base);
    expect(base).toBeLessThan(slow);
    expect(tokens.get('--ease-out') ?? '').toContain('cubic-bezier(');
  });
});
