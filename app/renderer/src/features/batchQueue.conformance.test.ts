// batchQueue.conformance.test.ts — the Batch queue surface is actually STYLED (W05).
//
// Measured before this guard existed: `features/BatchQueue.tsx` declares 21
// distinct `batch-queue*` class names and NOT ONE of them appeared in any
// renderer stylesheet, so the primary folder-to-shorts panel rendered as raw
// platform chrome inside a dark editorial app — native checkboxes, a native
// button voice (`components/shell.css` gives the raised/accent voice only to
// `.feature-panel`/`.shortmaker`/`.timeline__toolbar` descendants, and
// `.batch-queue` is mounted by `views/Repurpose.tsx` with no `.feature-panel`
// ancestor), and no status colour on the per-source rows.
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
const BATCH_QUEUE_CSS = resolve(HERE, 'batchQueue.css');
const SHELL_CSS = resolve(HERE, '..', 'components', 'shell.css');

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
 * variable would be invisible here. `BatchQueue.tsx` uses static literals
 * exclusively today, and the count floor asserted below is what would catch a
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

describe('the Batch queue surface is styled (W05)', () => {
  it('the detector sees a known-styled class and rejects a known-absent one', () => {
    // Verify the instrument BEFORE trusting any absence it reports (a selector
    // scanner that matches nothing would make the next test vacuously green).
    const styled = allStyledClasses();
    expect(styled.has('social-publish')).toBe(true); // features/panels.css
    expect(styled.has('definitely-not-a-real-class-xyz')).toBe(false);
  });

  it('extracts the panel class vocabulary from BatchQueue.tsx (floor: 20 names)', () => {
    const names = classNamesOf(readFileSync(BATCH_QUEUE_TSX, 'utf8'));
    const batchNames = names.filter((n) => n.startsWith('batch-queue'));
    expect(batchNames.length).toBeGreaterThanOrEqual(20);
    // Spot-anchor the two extremes of the surface so a regex that silently
    // stopped matching would not pass on count alone.
    expect(batchNames).toContain('batch-queue');
    expect(batchNames).toContain('batch-queue__row-status');
  });

  it('styles EVERY batch-queue class the component renders', () => {
    const styled = allStyledClasses();
    const unstyled = classNamesOf(readFileSync(BATCH_QUEUE_TSX, 'utf8'))
      .filter((n) => n.startsWith('batch-queue'))
      .filter((n) => !styled.has(n))
      .sort();
    expect(
      unstyled,
      'These BatchQueue classes render with no stylesheet rule at all — the ' +
        'panel falls back to raw platform chrome. Add a rule in ' +
        'features/batchQueue.css (tokens only).',
    ).toEqual([]);
  });

  it('joins the shared raised-button voice instead of re-declaring one', () => {
    // The panel has no `.feature-panel` ancestor, so `components/shell.css` had to
    // list it explicitly or every control kept the platform look. The previous test
    // cannot see this: it only asks whether `.batch-queue` is styled SOMEWHERE, and
    // features/batchQueue.css satisfies that on its own. So the button voice needs
    // its own assertion — checked on the four interaction states plus the focus
    // ring, because a partial addition (rest but no focus) is the realistic
    // regression, not a wholesale removal.
    const shell = stripComments(readFileSync(SHELL_CSS, 'utf8'));
    for (const selector of [
      '.batch-queue button',
      '.batch-queue button:hover:not(:disabled)',
      '.batch-queue button:active:not(:disabled)',
      '.batch-queue button:disabled',
      '.batch-queue button:focus-visible',
    ]) {
      expect(shell, `shell.css must give ${selector} the shared voice`).toContain(selector);
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
