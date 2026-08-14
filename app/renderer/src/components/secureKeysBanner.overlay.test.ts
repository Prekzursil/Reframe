// secureKeysBanner.overlay.test.ts — the NON-BLOCKING contract for the secure-key
// storage warning strip.
//
// WHY A STYLESHEET TEST AND NOT A DOM TEST. jsdom performs no layout and no
// hit-testing, so no DOM test in this repo can observe whether a fixed-position
// element swallows a click meant for what is underneath it. Same reasoning as
// confirmDialog.overlay.test.ts, whose helpers this mirrors.
//
// THE DEFECT THIS EXISTS TO CATCH (found by e2e run 31812888847, and shipped):
// SecureKeysBanner.css:1-4 describes the strip as "a bottom-pinned, NON-BLOCKING
// warning strip (no backdrop, no focus capture)", but the rule declared no
// `pointer-events`, so it defaulted to `auto`. Being `position: fixed` at
// `bottom: var(--space-5)` with `z-index: 1050`, it sat directly over the bottom
// edge of whatever was on screen and intercepted clicks there.
//
// Measured consequence: `e2e/overlay-hittest.spec.ts` — the suite whose entire
// purpose is "an overlay must not swallow the video's native controls" — probed
// the MakeShorts caption designer's control bar and the topmost element was
// `SPAN.secure-keys-banner__message`, not the <video>. The banner had become the
// exact defect class its neighbours (captionOverlay.css:70 "never steal the
// player's controls", captionBox.css:15) already guard against.
//
// It went unseen because that e2e test timed out earlier in its own navigation —
// a broken detector, not a passing one.
//
// SAFE BY CONSTRUCTION: SecureKeysBanner.tsx:191-198 renders a <div> containing
// only <span> messages — no button, link, input or focusable node — so there is
// nothing inside it that needs to receive a pointer event. If an interactive
// control is ever added, it MUST carry `pointer-events: auto` (the mandatory
// companion pattern captionBox.css:22-26 documents) and this test must be
// extended rather than deleted.
//
// This file imports no TS source; it is a pure style-file conformance check.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const BANNER_CSS = resolve(HERE, 'SecureKeysBanner.css');
const BANNER_TSX = resolve(HERE, 'SecureKeysBanner.tsx');

/** Strip block comments so the file's own prose never satisfies an assertion. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** The declaration body of the rule whose selector list is EXACTLY `selector`. */
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

describe('SecureKeysBanner — the non-blocking contract', () => {
  const css = stripComments(readFileSync(BANNER_CSS, 'utf8'));

  it('DETECTOR CONTROL — the rule is found and carries its known geometry', () => {
    // If this fails, every assertion below is answering about the wrong rule (or
    // no rule at all) and their verdicts mean nothing. Pins the two properties
    // that MAKE it an overlay: without `position: fixed` it could not cover
    // anything, and the z-index is why it wins against the content beneath.
    const body = ruleBody(css, '.secure-keys-banner');
    expect(body, 'no rule with the exact selector `.secure-keys-banner`').not.toBeNull();
    expect(decl(body as string, 'position')).toBe('fixed');
    expect(decl(body as string, 'z-index')).toBe('1050');
  });

  it('does not intercept pointer events meant for the app beneath it', () => {
    const body = ruleBody(css, '.secure-keys-banner') as string;
    expect(
      decl(body, 'pointer-events'),
      'a fixed, z-index:1050 strip with no `pointer-events: none` swallows clicks ' +
        'on whatever it covers — it ate the caption designer video controls once',
    ).toBe('none');
  });

  it('stays safe by construction — the banner has no interactive descendant', () => {
    // The justification for `pointer-events: none` is that nothing inside needs a
    // pointer. Pin that, so adding a button here goes RED instead of shipping a
    // silently-unclickable control.
    const tsx = readFileSync(BANNER_TSX, 'utf8').replace(/\/\/[^\n]*|\/\*[\s\S]*?\*\//g, '');
    for (const tag of ['<button', '<a ', '<input', '<select', '<textarea']) {
      expect(
        tsx.includes(tag),
        `${tag}> added to SecureKeysBanner: it cannot receive clicks while the ` +
          'container is `pointer-events: none`. Give it `pointer-events: auto` ' +
          '(see captionBox.css:22-26) and extend this test.',
      ).toBe(false);
    }
  });
});
