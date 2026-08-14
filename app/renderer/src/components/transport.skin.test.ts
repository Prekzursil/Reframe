// transport.skin.test.ts — the SKIN CONTRACT for Transport.tsx: every class the
// component renders must have a CSS rule somewhere in the renderer tree.
//
// WHY THIS EXISTS. Transport.tsx shipped emitting `transport`, `transport__button`,
// `transport__button--play`, `transport__scrubber`, `transport__time` and
// `transport__rate` with NO rule for ANY of them anywhere under renderer/src — the
// component built to replace Chromium's native control bar rendered as default
// browser buttons and a default range input. Nothing caught it: the renderer suite
// asserts behaviour and ARIA, and jsdom applies no stylesheet, so an unstyled
// component is indistinguishable from a styled one at that level.
//
// The sibling TabBar lane shipped this exact guard in the same wave
// (TabBar.test.tsx, "TabBar skin contract"), but hard-pinned to TabBar.tsx — so it
// could not see this component one directory away. This applies the same mechanism
// to Transport rather than restating the principle in a comment.
//
// The extractor is deliberately the same shape as TabBar's, including the two
// traps it documents:
//   * comments are stripped from BOTH sides (use-vs-mention): a class merely NAMED
//     in prose must not read as emitted, nor as styled.
//   * the `(?![\w-])` guard stops `.transport` matching `.transport__button` and
//     reporting a genuinely unstyled class as styled by a longer neighbour.

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { describe, it, expect } from 'vitest';

const SRC_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

const stripComments = (text: string): string => text.replace(/\/\*[\s\S]*?\*\//g, ' ');

/** Every `.css` under the renderer source tree. */
const cssFiles = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return cssFiles(full);
    return entry.name.endsWith('.css') ? [full] : [];
  });

/** Class names emitted by a component source: plain `className="…"` plus every
 *  string literal inside a `className={…}` expression. */
const emittedClasses = (source: string): string[] => {
  const code = stripComments(source).replace(/\/\/[^\n]*/g, ' ');
  const found = new Set<string>();
  const add = (list: string): void => {
    for (const cls of list.split(/\s+/)) if (/^[A-Za-z_-][\w-]*$/.test(cls)) found.add(cls);
  };
  for (const m of code.matchAll(/className="([^"]*)"/g)) add(m[1] ?? '');
  for (const m of code.matchAll(/className=\{([^}]*)\}/g)) {
    const expr = m[1] ?? '';
    for (const lit of [
      ...[...expr.matchAll(/'([^']*)'/g)].map((x) => x[1] ?? ''),
      ...[...expr.matchAll(/"([^"]*)"/g)].map((x) => x[1] ?? ''),
    ]) {
      add(lit);
    }
  }
  return [...found].sort();
};

describe('Transport skin contract (every emitted class has a rule)', () => {
  it('declares a CSS rule for every class name Transport.tsx renders', () => {
    const source = readFileSync(join(SRC_ROOT, 'components', 'Transport.tsx'), 'utf8');
    const classes = emittedClasses(source);

    // DETECTOR CONTROL. If the extractor ever silently stops finding classes, the
    // assertion below would pass vacuously against an empty list. `transport__button`
    // is the class this component cannot stop emitting — it is on all three of its
    // buttons. Without this line a broken extractor reports a perfect skin.
    expect(classes).toContain('transport__button');
    expect(classes.length).toBeGreaterThanOrEqual(5);

    const css = cssFiles(SRC_ROOT)
      .map((file) => readFileSync(file, 'utf8'))
      .map(stripComments)
      .join('\n');

    const unstyled = classes.filter((cls) => !new RegExp(`\\.${cls}(?![\\w-])`).test(css));
    expect(
      unstyled,
      'Transport renders these classes but no stylesheet declares a rule for them. ' +
        'An unstyled custom transport is worse than the native control bar it replaces.',
    ).toEqual([]);
  });

  it('imports its own stylesheet, so the rules actually reach the bundle', () => {
    // The rule-exists check above is necessary but NOT sufficient: a stylesheet
    // nothing imports contributes nothing at runtime, and this component's classes
    // appear in no other sheet. Without this assertion, deleting the import would
    // ship the exact original defect while the contract above still passed green.
    const source = readFileSync(join(SRC_ROOT, 'components', 'Transport.tsx'), 'utf8');
    expect(
      /import\s+['"]\.\/transport\.css['"]/.test(source),
      'Transport.tsx must import ./transport.css — an unimported sheet styles nothing',
    ).toBe(true);
  });

  it('DETECTOR CONTROL — a class that exists only in a COMMENT is not counted', () => {
    // Proves the use-vs-mention half: if comment stripping regressed, prose naming
    // a class would demand a rule for markup nothing renders, and this guard would
    // start failing for the wrong reason.
    const withMention = '// see .transport__ghost for history\nconst a = 1;';
    expect(emittedClasses(withMention)).toEqual([]);
  });

  it('DETECTOR CONTROL — the matcher does not let a longer class satisfy a shorter one', () => {
    // `.transport` must NOT be reported styled merely because `.transport__button`
    // has a rule. This is the `(?![\w-])` guard, measured rather than assumed.
    const css = '.transport__button { color: red; }';
    const styled = new RegExp(`\\.transport(?![\\w-])`).test(css);
    expect(styled).toBe(false);
  });
});
