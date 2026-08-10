// shorts.conformance.test.ts — the gallery play-preview button has a focus ring
// that can actually be PAINTED (W59).
//
// The pain this pins is geometric, not a missing declaration. The play-preview
// button is `.shorts__thumb-btn`, and:
//
//   * its parent `.shorts__thumb` sets `overflow: hidden` (shorts.css:216), so it
//     clips its descendants to its padding box;
//   * the button sets `width: 100%; height: 100%` (:225-226), so its border box
//     COINCIDES with that clip rectangle;
//   * the button declared no `:focus-visible` of its own, so it fell through to the
//     global rule at components/shell.css:75-83 — whose `outline` is deliberately
//     `transparent` (a forced-colors carrier, see the comment there) and whose only
//     VISIBLE ring is `box-shadow: var(--focus-ring)`;
//   * `--focus-ring` is `0 0 0 2px …, 0 0 0 4px …` (styles/tokens.css:206) — an
//     entirely OUTSET shadow, i.e. painted wholly outside the border box.
//
// An outset shadow on a box whose edges are the clip edges is painted entirely
// outside the clip and is therefore invisible. Ancestor `overflow` clipping applies
// to a descendant's outline and box-shadow, not only to its content. Net effect: a
// keyboard user tabbing the gallery got NO focus indication on the primary control
// of every card — WCAG 2.4.7. Note the ring was never "missing"; it was computed
// and then clipped, which is why a declaration-presence check would have passed.
//
// The fix must paint INWARD (inset shadow / negative outline-offset), and these
// tests assert that property rather than the presence of any ring at all.
//
// This file imports no TS source; it is a pure style-file conformance check,
// following styles/tokens.conformance.test.ts.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHORTS_CSS = resolve(HERE, 'shorts.css');
const TOKENS_CSS = resolve(HERE, '..', 'styles', 'tokens.css');

/** Strip comment blocks so prose can never register as a declaration. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The declaration body of the FIRST rule whose selector matches exactly. */
function ruleBody(css: string, selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\\-:]/g, '\\$&');
  const match = new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match ? match[1] : null;
}

/** True when a `box-shadow` in this body has at least one INSET layer. */
function hasInsetShadow(body: string): boolean {
  const decl = /box-shadow\s*:([^;]*)/.exec(body);
  return decl !== null && /(?:^|[\s,(])inset(?:[\s,]|$)/.test(decl[1]);
}

/** True when this body pulls the outline INWARD with a negative offset. */
function hasNegativeOutlineOffset(body: string): boolean {
  const decl = /outline-offset\s*:\s*(-?[\d.]+)/.exec(body);
  return decl !== null && Number.parseFloat(decl[1]) < 0;
}

const CSS = stripComments(readFileSync(SHORTS_CSS, 'utf8'));
const TOKENS = stripComments(readFileSync(TOKENS_CSS, 'utf8'));

describe('gallery play-preview focus ring is paintable (W59)', () => {
  it('the inward-paint detectors accept inward rings and REJECT the outset one', () => {
    // Both-states control, and the load-bearing one for this whole file: the defect
    // is a ring that IS declared but cannot be seen, so a detector that merely finds
    // "some focus styling" would report the broken state as fixed. These assert the
    // predicates separate the two shapes.
    const outset = 'box-shadow: 0 0 0 2px var(--surface-bg), 0 0 0 4px var(--accent-edge);';
    const inset = 'box-shadow: inset 0 0 0 2px var(--surface-bg);';
    expect(hasInsetShadow(outset)).toBe(false);
    expect(hasInsetShadow(inset)).toBe(true);
    // A trailing `inset` (the keyword is position-free in the grammar) still counts…
    expect(hasInsetShadow('box-shadow: 0 0 0 2px var(--accent-edge) inset;')).toBe(true);
    // …but a class or word merely CONTAINING "inset" does not.
    expect(hasInsetShadow('box-shadow: 0 0 0 2px var(--inset-ish);')).toBe(false);
    expect(hasNegativeOutlineOffset('outline-offset: 2px;')).toBe(false);
    expect(hasNegativeOutlineOffset('outline-offset: 0;')).toBe(false);
    expect(hasNegativeOutlineOffset('outline-offset: -2px;')).toBe(true);
    expect(hasNegativeOutlineOffset('outline: 2px solid red;')).toBe(false);
  });

  it('the clipping geometry that causes the defect still holds', () => {
    // If any of these three premises stops being true, the inset ring below is no
    // longer REQUIRED and this file should be re-derived rather than trusted. Pinned
    // so the fix can never become cargo-cult.
    const thumb = ruleBody(CSS, '.shorts__thumb');
    expect(thumb).not.toBeNull();
    expect(thumb).toMatch(/overflow:\s*hidden/);
    const btn = ruleBody(CSS, '.shorts__thumb-btn');
    expect(btn).not.toBeNull();
    expect(btn).toMatch(/width:\s*100%/);
    expect(btn).toMatch(/height:\s*100%/);
  });

  it('the shared --focus-ring token is entirely OUTSET (so it cannot survive)', () => {
    // The other half of the premise, read from the token rather than assumed: the
    // global ring is unusable HERE precisely because it has no inset layer.
    const decl = /--focus-ring:\s*([^;]*)/.exec(TOKENS);
    expect(decl, 'tokens.css must still define --focus-ring').not.toBeNull();
    expect(hasInsetShadow(`box-shadow: ${decl?.[1] ?? ''};`)).toBe(false);
  });

  it('.shorts__thumb-btn:focus-visible paints its ring INSIDE the clip', () => {
    const body = ruleBody(CSS, '.shorts__thumb-btn:focus-visible');
    expect(
      body,
      '.shorts__thumb-btn has no :focus-visible rule, so it inherits the global ' +
        'OUTSET ring (components/shell.css:82) which its own `overflow: hidden` ' +
        'parent clips away entirely — a keyboard user sees nothing.',
    ).not.toBeNull();
    const inward = body ?? '';
    // The palette channel: an inset shadow is painted inside the border box, so the
    // coincident clip rectangle cannot remove it.
    expect(
      hasInsetShadow(inward),
      'the ring must use an INSET box-shadow; an outset one is clipped away',
    ).toBe(true);
    // The forced-colors channel: Chromium force-clears box-shadow under
    // `forced-colors: active` but preserves outline width/style and substitutes a
    // system colour — so a real outline must carry the ring there too, and its offset
    // must be NEGATIVE or it lands outside the clip exactly as the shadow did.
    expect(inward, 'the ring needs a real outline for forced-colors').toMatch(
      /outline:\s*[^;]*solid/,
    );
    expect(
      hasNegativeOutlineOffset(inward),
      'outline-offset must be NEGATIVE; a positive offset paints outside the clip',
    ).toBe(true);
  });

  it('every FILLING control with a focus ring in this sheet paints inward', () => {
    // Sheet-wide generalisation. `.shorts__reload` / `.shorts__sort-btn` are NOT inside
    // a coincident clipping ancestor, so their positive-offset outlines are correct and
    // must NOT be "fixed" — this test must leave them alone. The set it governs is
    // derived, not hardcoded: controls whose own rule sets BOTH dimensions to 100%.
    //
    // Why "fills 100%x100%" is the right proxy in THIS sheet, measured rather than
    // assumed: the only three such classes are `.shorts__thumb-btn` (:225-226),
    // `.shorts__thumb-img` (:243-244) and `.shorts__player` (:255-256), and all three
    // are children of `.shorts__thumb` — the one `overflow: hidden` box here. So in
    // this sheet, filling implies clipped. The clipping set is asserted below so that
    // premise is checked and not merely stated.
    //
    // DETECTOR LIMIT, stated inline: ancestry is inferred from this sheet's own text; a
    // clipping ancestor contributed by another stylesheet or an inline style would not
    // be seen, and a control sized by a shorthand (`inset: 0`) rather than
    // width/height would not be classed as filling. Settling experiment for the general
    // case: focus each control in a real Chromium and diff the focused vs resting
    // screenshot of its bounding box — the only check that observes actual paint.
    const clipping = new Set<string>();
    const rules: readonly (readonly [string, string])[] = [
      ...stripComments(CSS).matchAll(/([^{}]+)\{([^{}]*)\}/g),
    ].map((m) => [m[1].trim(), m[2]] as const);
    for (const [selector, body] of rules) {
      if (!/overflow:\s*hidden/.test(body)) continue;
      for (const cls of selector.matchAll(/\.([A-Za-z0-9_-]+)/g)) clipping.add(cls[1]);
    }
    // The derivation really derived, and the premise above really holds.
    expect(clipping.has('shorts__thumb')).toBe(true);

    const fillingRings = rules.filter(([selector]) => {
      if (!selector.includes(':focus-visible')) return false;
      const base = /^\.([A-Za-z0-9_-]+)/.exec(selector)?.[1];
      if (base === undefined) return false;
      const rest = ruleBody(CSS, `.${base}`) ?? '';
      return /width:\s*100%/.test(rest) && /height:\s*100%/.test(rest);
    });
    // NON-VACUITY GATE. In the broken state this set was EMPTY — the defective control
    // had no `:focus-visible` rule at all — so the assertion below passed while the bug
    // was live. Requiring a member makes the test measure something.
    expect(
      fillingRings.map(([s]) => s),
      'no focus ring on a filling control was found at all, so the check below would ' +
        'be vacuous — the ring is MISSING, not merely mis-painted',
    ).toContain('.shorts__thumb-btn:focus-visible');

    const offenders = fillingRings
      .filter(([, body]) => !hasInsetShadow(body) || !hasNegativeOutlineOffset(body))
      .map(([selector]) => selector)
      .sort();
    expect(
      offenders,
      'These focus rings sit on a control that fills a clipping box but do not paint ' +
        'inward, so the ring is computed and then clipped away.',
    ).toEqual([]);
  });
});
