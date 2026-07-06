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

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const TOKENS_CSS = resolve(HERE, 'tokens.css');
const USAGE_BAR_CSS = resolve(HERE, '..', 'components', 'usageBar.css');

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
