// batchQueue.conformance.test.ts — the Batch queue surface is actually STYLED (W05).
//
// Measured before this guard existed: `features/BatchQueue.tsx` declares 21
// distinct `batch-queue*` class names and NOT ONE of them appeared in any
// renderer stylesheet, so the primary folder-to-shorts panel rendered as raw
// platform chrome inside a dark editorial app — native checkboxes, a native
// button voice (`components/shell.css` gives the raised/accent voice only to
// `.feature-panel`/`.shortmaker`/`.timeline__toolbar` descendants, and
// `.batch-queue` is mounted by `views/Repurpose.tsx` AND `views/Deliver.tsx`,
// neither with a `.feature-panel` ancestor), and no status colour on the
// per-source rows.
//
// The surface is BOTH components: `BatchConsentCard.tsx` is mounted from exactly
// one place — inside `<section className="batch-queue">`, mid-flow — and its
// eleven `batch-consent*` classes were unstyled as well. The first version of this
// guard enumerated only `batch-queue*` names and therefore reported the panel
// fully styled while a whole card on it was still raw chrome; both prefixes are
// checked now.
//
// This file imports no TS source; it is a pure style-conformance check over the
// stylesheets + the component source, mirroring `styles/tokens.conformance.test.ts`.

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const RENDERER_SRC = resolve(HERE, '..');
const BATCH_QUEUE_TSX = resolve(HERE, 'BatchQueue.tsx');
const BATCH_CONSENT_TSX = resolve(HERE, 'BatchConsentCard.tsx');
const BATCH_QUEUE_CSS = resolve(HERE, 'batchQueue.css');
const SHELL_CSS = resolve(HERE, '..', 'components', 'shell.css');

/** The class-name prefixes this panel owns across its two components. */
const PANEL_PREFIXES = ['batch-queue', 'batch-consent'] as const;

/** True when `name` belongs to the panel surface. */
function isPanelClass(name: string): boolean {
  return PANEL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

/** Strip `/* … *\/` comment blocks so prose can never register as a real rule. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

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

/**
 * Every class name that appears in a `className="…"` attribute of a component.
 *
 * DETECTOR LIMIT (stated, not hidden): this reads static double-quoted
 * `className` attributes only. A class assembled in a template literal or a
 * variable would be invisible here. Both `BatchQueue.tsx` and
 * `BatchConsentCard.tsx` use static literals exclusively today, and the count
 * floor asserted below is what would catch a
 * wholesale regression; a single future dynamic class would not be seen. The
 * settling experiment for that gap is a runtime render + `classList` walk, which
 * the component tests in `BatchQueue.test.tsx` already do per-class.
 */
function classNamesOf(tsx: string): readonly string[] {
  const out = new Set<string>();
  const attr = /className="([^"]*)"/g;
  for (let m = attr.exec(tsx); m !== null; m = attr.exec(tsx)) {
    for (const token of m[1].split(/\s+/)) {
      if (token !== '') out.add(token);
    }
  }
  return [...out];
}

/** Every class name that any SELECTOR in a stylesheet targets. */
function styledClasses(css: string): readonly string[] {
  const out: string[] = [];
  const body = stripComments(css);
  const rule = /([^{}]+)\{[^{}]*\}/g;
  for (let m = rule.exec(body); m !== null; m = rule.exec(body)) {
    const cls = /\.([A-Za-z0-9_-]+)/g;
    for (let c = cls.exec(m[1]); c !== null; c = cls.exec(m[1])) {
      out.push(c[1]);
    }
  }
  return out;
}

/** The union of every class styled anywhere in the renderer CSS. */
function allStyledClasses(): ReadonlySet<string> {
  const styled = new Set<string>();
  for (const file of collectCssFiles(RENDERER_SRC)) {
    for (const name of styledClasses(readFileSync(file, 'utf8'))) styled.add(name);
  }
  return styled;
}

/** Escape a CSS selector for literal use inside a RegExp. */
function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * True when `selector` appears in `css` as a WHOLE selector — i.e. terminated by
 * a `,` or the rule's `{`.
 *
 * A bare substring test cannot express this and silently degrades to a weaker
 * gate: `'…:hover:not(:disabled)'.includes('.batch-queue button')` is `true`, so
 * a `toContain('.batch-queue button')` assertion is satisfied by any of the
 * LONGER sibling selectors and can never fail while they exist. That is exactly
 * the entry a "consolidate the raised voice" refactor would drop. The boundary is
 * the whole fix; the "rejects a longer-sibling-only match" case below is its
 * detector control, and it asserts BOTH readings of the same fixture.
 */
function listsSelector(css: string, selector: string): boolean {
  return new RegExp(`${escapeRe(selector)}\\s*(?:,|\\{)`).test(css);
}

describe('the Batch queue surface is styled (W05)', () => {
  it('the detector sees a known-styled class and rejects a known-absent one', () => {
    // Verify the instrument BEFORE trusting any absence it reports (a selector
    // scanner that matches nothing would make the next test vacuously green).
    const styled = allStyledClasses();
    expect(styled.has('social-publish')).toBe(true); // features/panels.css
    expect(styled.has('definitely-not-a-real-class-xyz')).toBe(false);
  });

  it('extracts the panel class vocabulary from both components (floor: 20 + 11)', () => {
    const queueNames = classNamesOf(readFileSync(BATCH_QUEUE_TSX, 'utf8')).filter(isPanelClass);
    const consentNames = classNamesOf(readFileSync(BATCH_CONSENT_TSX, 'utf8')).filter(isPanelClass);
    expect(queueNames.length).toBeGreaterThanOrEqual(20);
    expect(consentNames.length).toBeGreaterThanOrEqual(11);
    // Spot-anchor the extremes of each component so a regex that silently stopped
    // matching would not pass on count alone.
    expect(queueNames).toContain('batch-queue');
    expect(queueNames).toContain('batch-queue__row-status');
    expect(consentNames).toContain('batch-consent');
    expect(consentNames).toContain('batch-consent__hint');
  });

  it('styles EVERY panel class the two components render', () => {
    const styled = allStyledClasses();
    const rendered = [
      ...classNamesOf(readFileSync(BATCH_QUEUE_TSX, 'utf8')),
      ...classNamesOf(readFileSync(BATCH_CONSENT_TSX, 'utf8')),
    ];
    const unstyled = rendered
      .filter(isPanelClass)
      .filter((n) => !styled.has(n))
      .sort();
    expect(
      unstyled,
      'These Batch-queue panel classes render with no stylesheet rule at all — ' +
        'the surface falls back to raw platform chrome. Add a rule in ' +
        'features/batchQueue.css (tokens only).',
    ).toEqual([]);
  });

  it('the selector-boundary detector rejects a longer-sibling-only match', () => {
    // The control for the test below, and the reason it is not written with
    // `toContain`. Both states, on a fixture: with ONLY the longer sibling present
    // the base entry must read as ABSENT (a substring test reports it present);
    // with the base entry present it must read as present.
    const siblingOnly = '.batch-queue button:hover:not(:disabled) { color: red; }';
    expect(siblingOnly).toContain('.batch-queue button'); // the weaker gate is fooled
    expect(listsSelector(siblingOnly, '.batch-queue button')).toBe(false);
    expect(listsSelector(`.x,\n.batch-queue button {\n}`, '.batch-queue button')).toBe(true);
    expect(listsSelector('.batch-queue button {}', '.batch-queue button')).toBe(true);
  });

  it('joins the shared raised-button voice instead of re-declaring one', () => {
    // The panel has no `.feature-panel` ancestor, so `components/shell.css` had to
    // list it explicitly or every control kept the platform look. The
    // every-class-styled test cannot see this: it only asks whether `.batch-queue`
    // is styled SOMEWHERE, and features/batchQueue.css satisfies that on its own.
    //
    // All five entries are checked as WHOLE selectors. Written with `toContain`
    // this loop advertised five and enforced four: `.batch-queue button` is a
    // substring of each of the other four, so the rest-state entry — the one a
    // "consolidate the raised voice" refactor drops — could be deleted with the
    // suite still green. Measured, not theorised: removing that line from
    // shell.css left this file passing.
    const shell = stripComments(readFileSync(SHELL_CSS, 'utf8'));
    for (const selector of [
      '.batch-queue button',
      '.batch-queue button:hover:not(:disabled)',
      '.batch-queue button:active:not(:disabled)',
      '.batch-queue button:disabled',
      '.batch-queue button:focus-visible',
    ]) {
      expect(
        listsSelector(shell, selector),
        `shell.css must give ${selector} the shared voice`,
      ).toBe(true);
    }
  });

  it('imports the sheet from the component (a file nobody imports styles nothing)', () => {
    expect(readFileSync(BATCH_QUEUE_TSX, 'utf8')).toContain("import './batchQueue.css'");
  });

  it('uses NO raw colour literals — every value routes through a token', () => {
    const css = stripComments(readFileSync(BATCH_QUEUE_CSS, 'utf8'));
    expect(css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
    expect(css.match(/\b(?:rgba?|hsla?)\(/g) ?? []).toEqual([]);
  });
});
