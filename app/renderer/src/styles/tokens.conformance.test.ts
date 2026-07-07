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
