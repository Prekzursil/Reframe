// confirmDialog.overlay.test.ts — the SCRIM GEOMETRY contract for the themed
// destructive-confirm gate (W04 remediation).
//
// WHY A STYLESHEET TEST AND NOT A DOM TEST. `aria-modal="true"` tells assistive
// tech that everything outside the dialog is inert. The keyboard half of that
// claim is cheap to pin in jsdom (ConfirmDialog.test.tsx cages Tab). The POINTER
// half is pure CSS geometry, and jsdom performs no layout and no hit-testing, so
// no DOM test in this repo can observe it.
//
// THE DEFECT THIS EXISTS TO CATCH (found by adversarial review, and shipped once):
// the scrim was `.confirm-dialog::before { position: fixed; inset: 0 }` on a card
// that was itself `position: fixed` + `transform: translate(-50%,-50%)`. Per CSS
// Transforms Level 1 §3, a `transform` other than `none` makes the element a
// containing block for its fixed-position descendants — so `inset: 0` resolved
// against the CARD. The "full-viewport" scrim was card-sized and painted behind
// the card: no visible dim, no pointer interception, and an `aria-modal` that
// lied. Every assertion below fails against that stylesheet; each is the exact
// shape of one half of the trap.
//
// The real-browser counterpart (does a click at (10,10) actually land on the
// scrim?) is e2e/confirm-scrim.hittest.spec.ts, which loads THIS file's CSS in
// Chromium and asks `document.elementFromPoint`. This test is the fast gate; that
// one is the ground truth.
//
// This file imports no TS source; it is a pure style-file conformance check.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIRM_CSS = resolve(HERE, 'confirmDialog.css');

/** Strip `/* … *\/` blocks so the file's own prose never satisfies an assertion. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/**
 * The declaration body of the rule whose selector list is EXACTLY `selector`.
 *
 * Exact-match on the whole selector list, not `includes`, so
 * `.confirm-dialog-scrim` can never be answered by the `.confirm-dialog` rule
 * (one contains the other as a prefix) and a grouped `a, b {}` rule is not
 * silently read as a rule for `a`.
 */
function ruleBody(css: string, selector: string): string | null {
  for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if ((match[1] ?? '').trim() === selector) return match[2] ?? '';
  }
  return null;
}

/** The value of `prop` in a declaration body, or null when it is not declared. */
function decl(body: string, prop: string): string | null {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'i').exec(body);
  return m ? (m[1] ?? '').trim() : null;
}

describe('confirmDialog.css — the modal scrim is a real, viewport-sized, opaque layer', () => {
  const css = stripComments(readFileSync(CONFIRM_CSS, 'utf8'));

  it('paints the scrim as its OWN element rule, never a pseudo-element', () => {
    // A `::before`/`::after` scrim is what the containing-block trap bites: it is
    // a descendant of the card, so it inherits the card's containing block.
    const pseudoOverlays = [
      ...css.matchAll(/([^{}]*::(?:before|after)[^{}]*)\{([^{}]*)\}/g),
    ].filter(([, , body]) => /position\s*:\s*fixed/i.test(body ?? ''));
    expect(pseudoOverlays.map(([, sel]) => (sel ?? '').trim())).toEqual([]);
    expect(ruleBody(css, '.confirm-dialog-scrim')).not.toBeNull();
  });

  it('anchors the scrim to the VIEWPORT and covers all four edges', () => {
    const scrim = ruleBody(css, '.confirm-dialog-scrim') ?? '';
    expect(decl(scrim, 'position')).toBe('fixed');
    expect(decl(scrim, 'inset')).toBe('0');
    // `transform` on the scrim itself would not break its own anchoring, but it
    // would make it a containing block for anything fixed inside it — the same
    // trap one level down. There is no reason to have one here.
    expect(decl(scrim, 'transform')).toBeNull();
  });

  it('leaves the scrim hit-testable, so it swallows clicks aimed at the page', () => {
    const scrim = ruleBody(css, '.confirm-dialog-scrim') ?? '';
    // `pointer-events: none` would make the dim purely cosmetic while `aria-modal`
    // kept claiming the page behind is inert.
    expect(decl(scrim, 'pointer-events')).toBeNull();
    expect(decl(scrim, 'background')).toBe('var(--overlay-scrim)');
  });

  it('stacks the scrim above the shorts-modal backdrop it can be raised from', () => {
    // library-shell.css `.shorts-modal__backdrop` is z-index 100 and the Library
    // raises this gate from inside that modal.
    const scrim = ruleBody(css, '.confirm-dialog-scrim') ?? '';
    expect(Number(decl(scrim, 'z-index'))).toBeGreaterThan(100);
  });

  it('keeps the CARD free of the fixed-position + transform combination', () => {
    // The card is centred by the scrim's flexbox now. If it ever goes back to
    // `position: fixed` + `transform` centring, any fixed descendant it grows
    // (including a re-added scrim) is silently clipped to the card.
    const card = ruleBody(css, '.confirm-dialog') ?? '';
    expect(card).not.toBe('');
    expect(decl(card, 'position')).toBeNull();
    expect(decl(card, 'transform')).toBeNull();
  });

  it('has exactly one fixed-position layer — the scrim', () => {
    const fixed = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, , body]) => /position\s*:\s*fixed/i.test(body ?? ''))
      .map(([, sel]) => (sel ?? '').trim());
    expect(fixed).toEqual(['.confirm-dialog-scrim']);
  });
});
