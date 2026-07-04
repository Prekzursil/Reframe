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
