// shell.buttonVoice.conformance.test.ts — the two bare-`.panel` surfaces join the
// shared control voice, and the focus-ring specificity repair covers every
// selector it has to (Q1 + Q2).
//
// MEASURED BEFORE THIS GUARD EXISTED
// ----------------------------------
// `components/shell.css` gives the raised button voice to exactly seven selectors
// (`:395-401`) and none of them matches a surface whose root is `className="…
// panel"`, because `.panel` itself has ZERO rules in the tree — only
// `.panel--missing` / `.panel--loading` (`shell.css:1109-1110`). Two live surfaces
// mount that way and therefore painted as raw dark Chromium UA chrome, with no
// hover and NO press feedback at all, beside fully-voiced siblings:
//
//   * `features/VideoTimeline.tsx:514` — `<section className="panel vtl">`; five
//     toolbar buttons (`:516,524,527,535,547`), two lane-head buttons (`:583,598`)
//     and a `<progress>` (`:558`, whose styling is scoped to
//     `.feature-panel` / `.sm-progress`, `shell.css:1209-1230`). Its ancestor chain
//     is `.workspace > .workspace__body` (`views/Workspace.tsx:450,513`) — no
//     `.feature-panel`.
//   * `components/CaptionPreferences.tsx:115` — `<section className="caption-prefs
//     panel">`; the Save button (`:220`) and the subtitle-mode `<select>` (`:152`).
//     Mounted into `.settings__panel` (`views/Settings.tsx:197,281`) — again no
//     `.feature-panel` ancestor.
//
// The repo already fixed this exact failure once, for `.batch-queue`, and wrote
// down why at `shell.css:391-394`; `features/batchQueue.conformance.test.ts` is the
// guard that keeps it fixed. This file is its sibling for the remaining two
// surfaces, and it adds the focus half.
//
// THE TWO TRAPS THIS FILE PINS (both measured on this tree, not theorised)
// -----------------------------------------------------------------------
// 1. NARROW selectors, never `.vtl button` / `.caption-prefs button`. A broad
//    descendant selector is (0,1,1) and would out-specify two (0,1,0) component
//    voices nested INSIDE those panels, silently repainting them:
//      - `.vtl__clip` (`features/videoTimeline.css:74`) — the timeline clips are
//        `<button>` elements (`VideoTimeline.tsx:631`), so a broad rule would
//        overwrite their background, border, padding, font-size and `cursor: grab`.
//      - `.caption-style-swatch` (`components/captionStylePicker.css:9`) — the
//        style-picker swatches are `<button>` elements (`CaptionStylePicker.tsx:54`)
//        rendered inside the caption-prefs panel.
//    So the voice is joined at `.vtl__bar` / `.vtl__laneHead` /
//    `.caption-prefs__actions`, which contain only real toolbar controls.
// 2. The DISABLED list must not inherit its neighbour's omission. `shell.css:456-459`
//    lists `.feature-panel`, `.shortmaker`, `.library__add-btn` and `.batch-queue`
//    but NOT `.timeline__toolbar button:disabled` (that surface is covered instead
//    by `features/timeline.css:83`). Disabled is the DOMINANT state on the video
//    timeline's toolbar — four of its five buttons are disabled until a clip is
//    selected — so copying the neighbour verbatim would skip the state that shows
//    most.
//
// This file imports no TS source; it is a pure conformance check over the
// stylesheet + the component sources, mirroring `features/batchQueue.conformance.test.ts`.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHELL_CSS = resolve(HERE, 'shell.css');
const CAPTION_PREFS_TSX = resolve(HERE, 'CaptionPreferences.tsx');
const VIDEO_TIMELINE_TSX = resolve(HERE, '..', 'features', 'VideoTimeline.tsx');

/** Strip `/* … *\/` comment blocks so prose can never register as a real rule. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Escape a CSS selector for literal use inside a RegExp. */
function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * True when `selector` appears in `css` as a WHOLE selector — terminated by a `,`
 * or by the rule's `{`, and preceded by a start-of-selector boundary.
 *
 * A bare substring test cannot express this and degrades to a weaker gate in BOTH
 * directions: `'.vtl__bar button:hover'.includes('.vtl__bar button')` is true (a
 * longer sibling satisfies the rest-state assertion), and
 * `'.x .vtl__bar button'.includes('.vtl__bar button')` is true as well (a
 * differently-scoped rule satisfies it). Both readings are asserted on fixtures in
 * the detector-control test below.
 */
function listsSelector(css: string, selector: string): boolean {
  return new RegExp(`(?:^|[,{}])\\s*${escapeRe(selector)}\\s*(?:,|\\{)`, 'm').test(css);
}

/** Every `[selectorList, body]` pair in a stylesheet, comments already stripped. */
function rules(css: string): readonly (readonly [string, string])[] {
  const out: (readonly [string, string])[] = [];
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (let m = rule.exec(css); m !== null; m = rule.exec(css)) {
    out.push([m[1].trim(), m[2]] as const);
  }
  return out;
}

/** The bodies of every rule whose selector list contains `selector` as a whole entry. */
function bodiesFor(css: string, selector: string): readonly string[] {
  return rules(css)
    .filter(([list]) => listsSelector(`${list} {`, selector))
    .map(([, body]) => body);
}

/** One declaration's value, or null. */
function decl(body: string, prop: string): string | null {
  return new RegExp(`(?:^|;)\\s*${escapeRe(prop)}\\s*:([^;]*)`).exec(body)?.[1].trim() ?? null;
}

/** Class names in a component's static `className="…"` attributes. */
function classNamesOf(tsx: string): ReadonlySet<string> {
  const out = new Set<string>();
  const attr = /className="([^"]*)"/g;
  for (let m = attr.exec(tsx); m !== null; m = attr.exec(tsx)) {
    for (const token of m[1].split(/\s+/)) if (token !== '') out.add(token);
  }
  return out;
}

const SHELL = stripComments(readFileSync(SHELL_CSS, 'utf8'));
const PREFS_TSX = readFileSync(CAPTION_PREFS_TSX, 'utf8');
const VTL_TSX = readFileSync(VIDEO_TIMELINE_TSX, 'utf8');

/** The control hosts that join the shared raised-button voice in this change. */
const VOICED = ['.vtl__bar button', '.vtl__laneHead button', '.caption-prefs__actions button'];

/** The five lists a control has to appear in to be fully voiced. */
const STATES = [
  '',
  ':hover:not(:disabled)',
  ':active:not(:disabled)',
  ':disabled',
  ':focus-visible',
];

/** The selectors the focus-ring specificity repair was missing (Q2). */
const FOCUS_REPAIRED = [
  '.library__add-btn:focus-visible',
  '.library__remove-btn:focus-visible',
  '.workspace__back:focus-visible',
];

describe('the bare-`.panel` surfaces join the shared control voice (Q1)', () => {
  it('the selector-boundary detector rejects both weaker matches', () => {
    // Verify the instrument BEFORE trusting anything it reports. Both states, on
    // fixtures: a longer sibling alone must read ABSENT, a differently-scoped rule
    // must read ABSENT, and the real entry must read PRESENT in both positions.
    const siblingOnly = '.vtl__bar button:hover:not(:disabled) { color: red; }';
    expect(siblingOnly).toContain('.vtl__bar button'); // the weaker gate is fooled
    expect(listsSelector(siblingOnly, '.vtl__bar button')).toBe(false);
    expect(listsSelector('.x .vtl__bar button { color: red; }', '.vtl__bar button')).toBe(false);
    expect(listsSelector('.x,\n.vtl__bar button {\n}', '.vtl__bar button')).toBe(true);
    expect(listsSelector('.vtl__bar button {}', '.vtl__bar button')).toBe(true);
    // …and it finds a selector that is already in the real sheet, so a regex that
    // silently stopped matching could not make the suite vacuously green.
    expect(listsSelector(SHELL, '.batch-queue button')).toBe(true);
    expect(listsSelector(SHELL, '.definitely-not-a-real-selector-xyz')).toBe(false);
  });

  it('gives BOTH panels the voice in all five states (disabled included)', () => {
    for (const host of VOICED) {
      for (const state of STATES) {
        expect(
          listsSelector(SHELL, `${host}${state}`),
          `shell.css must list ${host}${state} — otherwise that state falls through ` +
            'to raw platform chrome (trap 2: the disabled list omits .timeline__toolbar).',
        ).toBe(true);
      }
    }
  });

  it('styles the video timeline <progress> instead of leaving it UA chrome', () => {
    for (const selector of [
      '.vtl progress',
      '.vtl progress::-webkit-progress-bar',
      '.vtl progress::-webkit-progress-value',
    ]) {
      expect(listsSelector(SHELL, selector), `shell.css must list ${selector}`).toBe(true);
    }
  });

  it('gives the caption-prefs <select> the shared input voice', () => {
    for (const state of ['', ':hover', ':focus-visible']) {
      expect(
        listsSelector(SHELL, `.caption-prefs__select${state}`),
        `shell.css must list .caption-prefs__select${state}`,
      ).toBe(true);
    }
  });

  it('does NOT reach the nested component buttons (the broad-selector trap)', () => {
    // `.vtl__clip` and `.caption-style-swatch` are <button>s living inside these
    // panels with their own (0,1,0) voices. A broad `.vtl button` /
    // `.caption-prefs button` entry is (0,1,1) and would repaint both.
    for (const broad of [
      '.vtl button',
      '.vtl button:hover:not(:disabled)',
      '.caption-prefs button',
      '.caption-prefs button:hover:not(:disabled)',
    ]) {
      expect(
        listsSelector(SHELL, broad),
        `${broad} is too broad — it out-specifies .vtl__clip / .caption-style-swatch`,
      ).toBe(false);
    }
  });

  it('adds NO `.panel` base surface rule (it would double-pad three fallbacks)', () => {
    // `.workspace__body` (shell.css:1106) and the three `panel panel--loading`
    // fallbacks (shell.css:1111) already carry `padding: var(--space-6)`.
    expect(listsSelector(SHELL, '.panel')).toBe(false);
  });

  it('the selectors match markup that actually exists (no dead rules)', () => {
    const vtl = classNamesOf(VTL_TSX);
    expect(vtl.has('vtl__bar'), 'VideoTimeline.tsx must still render .vtl__bar').toBe(true);
    expect(vtl.has('vtl__laneHead'), 'VideoTimeline.tsx must still render .vtl__laneHead').toBe(
      true,
    );
    expect(VTL_TSX, 'VideoTimeline.tsx must still render a <progress>').toContain('<progress');
    const prefs = classNamesOf(PREFS_TSX);
    expect(
      prefs.has('caption-prefs__actions'),
      'CaptionPreferences.tsx must still render .caption-prefs__actions',
    ).toBe(true);
    expect(
      prefs.has('caption-prefs__select'),
      'CaptionPreferences.tsx must class the subtitle-mode <select> so the shared ' +
        'input voice can reach it without a structural `>` selector',
    ).toBe(true);
  });
});

describe('the focus-ring specificity repair names every selector it needs (Q2)', () => {
  it('repairs Library Add, Library Remove and Workspace Back', () => {
    // `:where(…):focus-visible` is (0,1,0) and loses on source order to the later
    // (0,1,0) rules that set `box-shadow` on these three — `--accent-glow` at
    // shell.css:475 for Add, `none` at :447 for Remove/Back. Without an entry here
    // keyboard focus paints NOTHING on the Library's primary action, its
    // destructive action, and the Workspace's only back navigation (WCAG 2.4.7 AA).
    for (const selector of FOCUS_REPAIRED) {
      expect(listsSelector(SHELL, selector), `shell.css must repair ${selector}`).toBe(true);
    }
  });

  it('keeps the primary`s accent glow — Add is COMPOSED, not plain', () => {
    const bodies = bodiesFor(SHELL, '.library__add-btn:focus-visible');
    expect(bodies.length).toBeGreaterThan(0);
    for (const body of bodies) {
      const shadow = decl(body, 'box-shadow');
      if (shadow === null) continue;
      expect(shadow, 'the Add repair must compose the ring WITH the accent glow').toContain(
        'var(--focus-ring)',
      );
      expect(shadow, 'a plain focus-ring block would strip the primary accent glow').toContain(
        'var(--accent-glow)',
      );
    }
  });

  it('the ring no longer depends on winning a box-shadow tie (durable form)', () => {
    // The global rule sets `outline: 2px solid transparent` (shell.css:80) so the
    // designed ring is a box-shadow — a channel any later same-specificity rule can
    // take away, which is exactly how these three lost it. A real outline COLOUR on
    // the repaired selectors lands on the same 2px..4px band as the token`s outer
    // ring, so it is visually identical where the shadow paints, and it is the only
    // thing left when a hover rule out-specifies the shadow.
    const repaired = [...FOCUS_REPAIRED, ...VOICED.map((h) => `${h}:focus-visible`)];
    for (const selector of repaired) {
      const bodies = bodiesFor(SHELL, selector);
      expect(bodies.length, `no rule lists ${selector}`).toBeGreaterThan(0);
      const colours = bodies.map((b) => decl(b, 'outline-color')).filter((c) => c !== null);
      expect(colours.length, `${selector} must set a real outline-color`).toBeGreaterThan(0);
      for (const colour of colours) {
        expect(colour, `${selector} must not keep the invisible outline`).not.toBe('transparent');
      }
    }
  });
});
