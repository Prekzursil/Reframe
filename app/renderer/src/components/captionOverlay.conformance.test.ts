// captionOverlay.conformance.test.ts — container-query units must HAVE a
// container (W58).
//
// The pain this pins: `components/captionOverlay.css` sizes the caption in `cqw`
// (container query width) at two sites — the hook slot (:25) and the active
// caption line (:43) — but NOT ONE `container-type` / `container-name`
// declaration existed anywhere in the renderer CSS. Per CSS Containment 3 §2.1, a
// `cq*` unit with no ancestor container falls back to the SMALL VIEWPORT, so the
// caption sized itself against the application window instead of the phone stage
// it is drawn on.
//
// That is not a cosmetic drift, because the stage is nearly fixed-width:
// `features/shortmaker.css:22` sets `.sm-phone { width: min(248px, 100%) }`.
// Resolving `font-size: clamp(0.95rem, 5cqw, 1.55rem)` (:43) both ways, at a 16px
// root:
//   * against the viewport at 1920px wide → 5cqw = 96px → clamped to the MAX, 24.8px
//   * against the 248px stage           → 5cqw = 12.4px → clamped to the MIN, 15.2px
// The two land on OPPOSITE ends of the clamp, and the middle (scaling) term is
// unreachable against the viewport at any window ≥ 496px — so the caption sat
// pinned at its ceiling on every realistic window size and the "scale with the
// stage" intent was entirely dead. It also meant resizing the app window changed
// the caption size while the stage it floats on did not move.
//
// This file imports no TS source; it is a pure style-file conformance check,
// following `styles/tokens.conformance.test.ts` and
// `components/jobqueue.conformance.test.ts`.

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const OVERLAY_CSS = resolve(HERE, 'captionOverlay.css');
const RENDERER_SRC = resolve(HERE, '..');

/** Strip comment blocks so prose describing a unit never registers as a use. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Recursively collect every `*.css` file path under a directory. */
function collectCssFiles(dir: string): readonly string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...collectCssFiles(full));
    else if (entry.isFile() && entry.name.endsWith('.css')) out.push(full);
  }
  return out;
}

/**
 * A container-query LENGTH unit used as a real value — `4.5cqw`, `5cqh`, `2cqi`…
 *
 * Anchored on a digit boundary and a trailing non-word so it cannot match the
 * tail of an identifier (a bare `cqw` substring would also hit a class called
 * `.acqw`, and `\d+cq[whib]` alone would hit `10cqwide`). `cqmin`/`cqmax` are in
 * the alternation because they are the same defect with a different spelling.
 */
const CQ_UNIT = /\d(?:\.\d+)?(cq(?:w|h|i|b|min|max))\b/g;

/** A rule that ESTABLISHES a query container. */
const CONTAINER_DECL = /container-type\s*:|container-name\s*:|(?<![-\w])container\s*:/;

/** Selectors of every rule in `css` that uses a container-query unit. */
function cqUsingSelectors(css: string): readonly string[] {
  const out: string[] = [];
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = rule.exec(stripComments(css)); m !== null; m = rule.exec(stripComments(css))) {
    if (new RegExp(CQ_UNIT.source).test(m[2])) out.push(m[1].trim());
  }
  return out;
}

describe('container-query units have a container (W58)', () => {
  it('the cq-unit detector sees the known sites and rejects a look-alike', () => {
    // Control the instrument BEFORE trusting any count it reports. Two real sites
    // exist in this sheet; a pattern that matched nothing would make every
    // assertion below vacuous, and one that matched too loosely would manufacture
    // sites that are not there.
    const css = stripComments(readFileSync(OVERLAY_CSS, 'utf8'));
    const found = [...css.matchAll(CQ_UNIT)].map((m) => m[1]);
    expect(found).toEqual(['cqw', 'cqw']);
    // A class or identifier merely ENDING in the unit name is not a use.
    expect([...'.acqw { color: red } .x { width: 10cqwide }'.matchAll(CQ_UNIT)]).toEqual([]);
    // …and a genuine use IS caught in each supported spelling.
    for (const unit of ['4.5cqw', '5cqh', '2cqi', '3cqb', '1cqmin', '9cqmax']) {
      expect([...`.x { font-size: ${unit}; }`.matchAll(CQ_UNIT)]).toHaveLength(1);
    }
  });

  it('the container detector fires on each spelling and stays silent otherwise', () => {
    // Both-states control for the assertions below: a `container-*` matcher that
    // could never fire would report "no container" in the FIXED state too, which is
    // exactly how this defect survived a green suite.
    expect(CONTAINER_DECL.test('.x { container-type: inline-size; }')).toBe(true);
    expect(CONTAINER_DECL.test('.x { container-name: stage; }')).toBe(true);
    expect(CONTAINER_DECL.test('.x { container: stage / inline-size; }')).toBe(true);
    expect(CONTAINER_DECL.test('.x { color: red; }')).toBe(false);
    // `container-type` is the property; `contain` is a DIFFERENT property that does
    // NOT establish a query container, so it must not be mistaken for one.
    expect(CONTAINER_DECL.test('.x { contain: layout style; }')).toBe(false);
  });

  it('.caption-overlay establishes an inline-size query container', () => {
    const css = stripComments(readFileSync(OVERLAY_CSS, 'utf8'));
    const rule = /\.caption-overlay\s*\{([^}]*)\}/.exec(css);
    expect(rule, '.caption-overlay must still be a real rule in this sheet').not.toBeNull();
    // `inline-size` and not `size`: the overlay is `inset: 0` on the stage, so its
    // BLOCK size comes from the stage. `container-type: size` would additionally
    // apply block-size containment and require an explicit height.
    expect(rule?.[1]).toMatch(/container-type:\s*inline-size/);
  });

  it('every cq-unit site in this sheet is a DESCENDANT of that container', () => {
    // The unit resolves against the nearest ANCESTOR container, so a rule that uses
    // one must sit under `.caption-overlay` — an element is never its own container.
    const selectors = cqUsingSelectors(readFileSync(OVERLAY_CSS, 'utf8'));
    expect(selectors.length).toBeGreaterThanOrEqual(2);
    const orphans = selectors.filter((s) => !/^\.caption-overlay[\s_-]/.test(s)).sort();
    expect(
      orphans,
      'These rules size themselves in container-query units but are not descendants ' +
        'of `.caption-overlay`, the only container this sheet establishes — so their ' +
        'units resolve against the viewport, not the phone stage.',
    ).toEqual([]);
  });

  it('no renderer stylesheet uses a cq unit while the tree defines NO container', () => {
    // The tree-wide half: the measured defect was ZERO containers anywhere against
    // two live `cqw` sites. This is the guard that a future lane reaching for `cqw`
    // in a fresh sheet cannot re-open by omission.
    //
    // DETECTOR LIMIT, stated inline: this asserts a container exists SOMEWHERE in
    // the renderer CSS, not that it is an ancestor of each individual use — cross-
    // sheet ancestry is a DOM property that stylesheet text cannot decide. The
    // per-site ancestry check above covers the only sheet that uses these units
    // today. Settling experiment for the general case: `getComputedStyle` the
    // caption node in a real Chromium at two window widths with the stage width
    // pinned, and assert the font-size does NOT move with the window.
    const sheets = collectCssFiles(RENDERER_SRC);
    expect(sheets.length).toBeGreaterThan(20); // the scan is really scanning
    const users: string[] = [];
    let containers = 0;
    for (const file of sheets) {
      const css = stripComments(readFileSync(file, 'utf8'));
      if (new RegExp(CQ_UNIT.source).test(css)) users.push(file);
      if (CONTAINER_DECL.test(css)) containers += 1;
    }
    expect(users.length).toBeGreaterThan(0); // the premise still holds
    expect(
      containers,
      `${users.length} renderer stylesheet(s) size themselves in container-query ` +
        'units but NO stylesheet establishes a container, so every one of those ' +
        'units silently resolves against the viewport.',
    ).toBeGreaterThan(0);
  });
});
