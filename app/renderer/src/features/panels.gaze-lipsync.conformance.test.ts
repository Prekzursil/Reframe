// panels.gaze-lipsync.conformance.test.ts — the Eye-contact and Lip-sync panels
// are actually STYLED (W19 / W20 follow-up).
//
// Measured before this guard existed: `features/Gaze.tsx` and
// `features/LipSync.tsx` render 23 distinct `gaze-*` / `lipsync-*` class names and
// NOT ONE of them appeared in any renderer stylesheet (the same scan, controlled
// against known-present classes, found selectors for their siblings). Both panels
// therefore inherited only the shared `.feature-panel` shell — buttons, inputs and
// focus rings — while every panel-SPECIFIC surface rendered as unstyled flow
// content: the likeness-attestation fieldset, the hint paragraphs, the audit
// record, the correction-strength readout, and the refusal / unwired / unavailable
// notices.
//
// The consent fieldset is the reason this is more than cosmetic. `.gaze-consent` is
// a GATE — the Run button stays disabled until the operator names the subject and
// attests, and `models/likeness.py` refuses independently. Rendered as a bare
// `<fieldset>` it reads as fine print rather than a commitment, which is exactly
// the framing error its sibling `.dub-panel .dub-consent` was given a warning rail
// to avoid (features/panels.css:258-259). So the tests below assert the SEMANTICS
// of a few load-bearing surfaces, not merely that some rule exists.
//
// Structure follows `features/batchQueue.conformance.test.ts`, which pins the same
// defect class (W05) for the Batch queue. This file imports no TS source; it is a
// pure style-conformance check over the stylesheets plus the component source.
//
// COUPLING, disclosed: the vocabulary is read from the two `.tsx` files, so adding
// a new `gaze-*` / `lipsync-*` class without a rule turns this RED. That is the
// guard working as intended (it is the whole defect class), and it matches the
// batchQueue precedent — but it does mean a lane touching those components owns the
// matching rule too.

import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const RENDERER_SRC = resolve(HERE, '..');
const GAZE_TSX = resolve(HERE, 'Gaze.tsx');
const LIPSYNC_TSX = resolve(HERE, 'LipSync.tsx');
const PANELS_CSS = resolve(HERE, 'panels.css');

// The helpers below are deliberately LOCAL copies of their namesakes in
// `batchQueue.conformance.test.ts` / `styles/tokens.conformance.test.ts`, for the
// reason that file already records at its own copy: importing across test files
// would execute the other suite's module body here too. `isPanelClass` is also not
// the same function — it closes over a different prefix set.

/** The class-name prefixes these two panels own. */
const PANEL_PREFIXES = ['gaze-', 'lipsync-'] as const;

/** True when `name` belongs to one of the two panel surfaces. */
function isPanelClass(name: string): boolean {
  return PANEL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

/** Strip comment blocks so prose can never register as a real rule. */
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
 * Every class name in a static double-quoted `className` attribute.
 *
 * DETECTOR LIMIT (stated, not hidden): static `className="…"` only. A class built
 * in a template literal or a variable is invisible here. Both components use
 * static literals exclusively today; the count floors below are what would catch a
 * wholesale regression. Settling experiment for the gap: a render + `classList`
 * walk, which `Gaze.test.tsx` / `LipSync.test.tsx` already do per-class.
 */
function classNamesOf(tsx: string): readonly string[] {
  const out = new Set<string>();
  const attr = /className="([^"]*)"/g;
  for (let m = attr.exec(tsx); m !== null; m = attr.exec(tsx)) {
    for (const token of m[1].split(/\s+/)) if (token !== '') out.add(token);
  }
  return [...out];
}

/**
 * Every class that is the SUBJECT of a rule — the right-most compound selector, the
 * element the declarations actually apply to.
 *
 * REFUTED, and this is the correction: the first version of this helper harvested
 * EVERY `.class` token anywhere in the selector, so a class counted as "styled"
 * merely by appearing as an ANCESTOR in someone else's selector. Measured on the live
 * tree, two of the 23 rendered classes — `gaze-panel` and `gaze-strength` — are the
 * subject of NO rule anywhere and passed only through the `.gaze-panel .gaze-…` /
 * `.gaze-strength .gaze-strength-hint` prefixes. Harmless today (they inherit
 * `.feature-panel` / `.field`), but it means a future `gaze-foo` could satisfy the
 * completeness guard by being used as a prefix and nothing else — the exact
 * omission-by-default hole this file exists to close.
 *
 * Functional-pseudo ARGUMENTS are stripped first: in `.a:has(.b)` the subject is `.a`
 * — `.b` is a condition, not a target — so `:has()`/`:is()`/`:where()`/`:not()`
 * contents must not be read as subjects.
 *
 * The same harvesting shape lives in `batchQueue.conformance.test.ts:87` and has the
 * same property; it is NOT changed here — a different WU owns that file.
 */
function subjectClasses(css: string): readonly string[] {
  const out: string[] = [];
  for (const m of stripComments(css).matchAll(/([^{}]+)\{[^{}]*\}/g)) {
    for (const entry of m[1].split(',')) {
      const flat = entry.replace(/:(?:has|is|where|not)\([^)]*\)/g, '').trim();
      const compounds = flat.split(/\s*[>+~]\s*|\s+/).filter((s) => s !== '');
      const subject = compounds.at(-1) ?? '';
      for (const c of subject.matchAll(/\.([A-Za-z0-9_-]+)/g)) out.push(c[1]);
    }
  }
  return out;
}

/**
 * Classes that are deliberately styled ONLY through inheritance plus their
 * descendants' selectors, never as a rule subject.
 *
 * Both are containers whose own appearance comes from a shared shell — `.gaze-panel`
 * from `.feature-panel`, `.gaze-strength` from `.field` — so a rule of their own
 * would be an empty one. Enumerated rather than tolerated by the matcher, so adding a
 * member is a deliberate act a reviewer can see.
 */
const ANCESTOR_ONLY = new Set(['gaze-panel', 'gaze-strength']);

/** The union of every class that is the SUBJECT of a rule in the renderer CSS. */
function allStyledClasses(): ReadonlySet<string> {
  const styled = new Set<string>();
  for (const file of collectCssFiles(RENDERER_SRC)) {
    for (const name of subjectClasses(readFileSync(file, 'utf8'))) styled.add(name);
  }
  return styled;
}

/**
 * The declaration body of the rule that lists `selector` as a WHOLE entry.
 *
 * Deliberately not a `<selector>\s*\{` regex. That form cannot see a selector in a
 * COMMA-GROUPED list — `.a,\n.b { … }` — because `.a` is followed by `,`, so it
 * reports a perfectly good rule as absent. Two of the rules this file checks are
 * grouped (the two AI disclosures share one), and the first version of this helper
 * failed on exactly that, which would have pushed the SHEET into being split into
 * one rule per selector to satisfy a weak test. Same boundary problem
 * `batchQueue.conformance.test.ts:114-128` documents for its `listsSelector`.
 *
 * Whitespace inside the selector is normalised on both sides so
 * `.a   .b` and `.a .b` compare equal.
 */
function ruleBody(css: string, selector: string): string | null {
  const want = selector.replace(/\s+/g, ' ').trim();
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const entries = m[1].split(',').map((s) => s.replace(/\s+/g, ' ').trim());
    if (entries.includes(want)) return m[2];
  }
  return null;
}

const PANELS = stripComments(readFileSync(PANELS_CSS, 'utf8'));

describe('the Eye-contact and Lip-sync panels are styled (W19 / W20)', () => {
  it('the detector sees known-styled classes and rejects a known-absent one', () => {
    // Verify the instrument BEFORE trusting any absence it reports: a selector
    // scanner that matched nothing would make the completeness test vacuously green.
    const styled = allStyledClasses();
    expect(styled.has('dub-consent')).toBe(true); // features/panels.css
    expect(styled.has('social-publish')).toBe(true); // features/panels.css
    expect(styled.has('definitely-not-a-real-class-xyz')).toBe(false);
  });

  it('the detector reads the rule SUBJECT, not every class in the selector', () => {
    // The distinguishing case, fed as a fixture: an ancestor is NOT a subject. Without
    // this the completeness test can be satisfied by using a class as a prefix.
    expect(subjectClasses('.a .b { color: red; }')).toEqual(['b']);
    expect(subjectClasses('.a > .b, .c ~ .d { color: red; }')).toEqual(['b', 'd']);
    // A functional pseudo's argument is a condition, not a target.
    expect(subjectClasses('.a:has(.b) { color: red; }')).toEqual(['a']);
    // A compound subject contributes both of its classes.
    expect(subjectClasses('.a .b.c { color: red; }')).toEqual(['b', 'c']);
    // …and on the LIVE tree the two allowlisted containers really are ancestor-only.
    // If this fails because one of them gained a rule of its own, delete it from
    // ANCESTOR_ONLY — the allowlist entry is then dead weight, not a finding.
    const styled = allStyledClasses();
    for (const name of ANCESTOR_ONLY) {
      expect(styled.has(name), `${name} is now a rule subject — drop it from ANCESTOR_ONLY`).toBe(
        false,
      );
    }
  });

  it('ruleBody finds a COMMA-GROUPED selector, and misses nothing real', () => {
    // Control for the instrument the two semantic tests below depend on. A
    // `<selector>\s*\{` regex reports a grouped entry as ABSENT, which would have
    // read "this surface has no rule" for a surface that is perfectly styled.
    const fixture = '.a .x,\n.b .y { color: red; }\n.solo { color: blue; }';
    expect(ruleBody(fixture, '.a .x')).toBe(' color: red; '); // first entry
    expect(ruleBody(fixture, '.b .y')).toBe(' color: red; '); // second entry
    expect(ruleBody(fixture, '.solo')).toBe(' color: blue; '); // ungrouped still works
    expect(ruleBody(fixture, '.a')).toBeNull(); // a PREFIX is not a whole entry
    expect(ruleBody(fixture, '.a .z')).toBeNull(); // genuinely absent
    expect(ruleBody('.a  .x { color: red; }', '.a .x')).toBe(' color: red; '); // ws-normalised
    // …and it really is reading the live sheet, on a grouped rule that exists there.
    expect(ruleBody(PANELS, '.gaze-panel .gaze-unavailable')).not.toBeNull();
    expect(ruleBody(PANELS, '.gaze-panel .gaze-nothing')).not.toBeNull();
  });

  it('extracts the panel class vocabulary from both components (floor: 15 + 8)', () => {
    const gaze = classNamesOf(readFileSync(GAZE_TSX, 'utf8')).filter(isPanelClass);
    const lipsync = classNamesOf(readFileSync(LIPSYNC_TSX, 'utf8')).filter(isPanelClass);
    expect(gaze.length).toBeGreaterThanOrEqual(15);
    expect(lipsync.length).toBeGreaterThanOrEqual(8);
    // Spot-anchor the extremes of each so a regex that silently stopped matching
    // could not pass on count alone.
    expect(gaze).toContain('gaze-panel');
    expect(gaze).toContain('gaze-consent-attest');
    expect(lipsync).toContain('lipsync-section');
    expect(lipsync).toContain('lipsync-confidence');
  });

  it('every gaze-/lipsync- class the components render is a rule SUBJECT', () => {
    // Scoped exactly to what is measured: each rendered class is the subject of some
    // rule, or is one of the two enumerated containers that are styled purely by
    // inheritance. Appearing as an ancestor in another rule's selector does NOT count
    // — see `subjectClasses`.
    const styled = allStyledClasses();
    const rendered = [
      ...classNamesOf(readFileSync(GAZE_TSX, 'utf8')),
      ...classNamesOf(readFileSync(LIPSYNC_TSX, 'utf8')),
    ];
    const unstyled = rendered
      .filter(isPanelClass)
      .filter((n) => !styled.has(n) && !ANCESTOR_ONLY.has(n))
      .sort();
    expect(
      unstyled,
      'These Eye-contact / Lip-sync classes are the subject of NO rule anywhere, so ' +
        'those surfaces fall back to unstyled flow content. Add a rule in ' +
        'features/panels.css (tokens only) — or, if the surface is deliberately styled ' +
        'only by inheritance, add it to ANCESTOR_ONLY with the reason.',
    ).toEqual([]);
  });

  it('the likeness consent gate reads as a GATE, like its dub sibling', () => {
    // Semantics, not presence. A consent fieldset styled as ordinary body copy is
    // the framing error the dub gate carries a warning rail to avoid; matching it
    // keeps ONE visual language for "you are attesting to something".
    const gate = ruleBody(PANELS, '.gaze-panel .gaze-consent');
    expect(gate, '.gaze-panel .gaze-consent must have its own rule').not.toBeNull();
    expect(gate).toMatch(/border[^;]*var\(--status-warn/);
    // The attestation line is the loudest thing in the block — it is a statement the
    // operator makes, not a field label — exactly as panels.css:280-290 has it.
    const attest = ruleBody(PANELS, '.gaze-panel .gaze-consent .gaze-consent-attest');
    expect(attest).not.toBeNull();
    expect(attest).toMatch(/color:\s*var\(--text-primary\)/);
    // …and the same warn language the dub gate uses, so the two cannot drift apart.
    expect(ruleBody(PANELS, '.dub-panel .dub-consent')).toMatch(/var\(--status-warn/);
  });

  it('the AI disclosures are information rails, NOT alarms', () => {
    // panels.css:362-364 states the rule for the dub disclosure: legible and
    // unmissable without competing with the consent gate, which is the only
    // warn-coloured element on the panel. Pinned here for the two new disclosures so
    // a later restyle cannot escalate them into a second alarm.
    for (const selector of [
      '.gaze-panel .gaze-ai-disclosure',
      '.lipsync-section .lipsync-ai-disclosure',
    ]) {
      const body = ruleBody(PANELS, selector);
      expect(body, `${selector} must have its own rule`).not.toBeNull();
      expect(body).not.toMatch(/var\(--status-warn/);
      expect(body).not.toMatch(/var\(--status-error/);
      expect(body).not.toMatch(/var\(--danger/);
    }
  });

  it('panels.css uses NO raw colour literals — every value routes through a token', () => {
    // Measured clean before this change (0 hex, 0 rgb/hsl), so this is a real floor
    // and not a retroactive allowance.
    expect(PANELS.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
    expect(PANELS.match(/\b(?:rgba?|hsla?)\(/g) ?? []).toEqual([]);
  });

  it('both components import the sheet (a file nobody imports styles nothing)', () => {
    expect(readFileSync(GAZE_TSX, 'utf8')).toContain("import './panels.css'");
    expect(readFileSync(LIPSYNC_TSX, 'utf8')).toContain("import './panels.css'");
  });
});
