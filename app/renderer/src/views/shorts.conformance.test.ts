// shorts.conformance.test.ts — the gallery play-preview button has a focus ring
// that can actually be PAINTED (W59).
//
// THE DEFECT, and the FIRST FIX THAT DID NOT FIX IT. Two independent things could
// eat this ring, and the first version of this file (2b25bf62) only saw one:
//
//   1. THE CLIP. `.shorts__thumb` sets `overflow: hidden` (shorts.css:216) and the
//      button is `width/height: 100%` (:225-226), so the button's border box
//      COINCIDES with the clip rectangle. The global `:focus-visible` ring is
//      `box-shadow: var(--focus-ring)` = `0 0 0 2px …, 0 0 0 4px …` (tokens.css:206),
//      entirely OUTSET — painted wholly outside the clip, therefore removed.
//   2. THE OCCLUDER. `.shorts__thumb-img` is an absolutely-positioned CHILD of the
//      button (Shorts.tsx:337 inside :330-344; shorts.css:273-279 `position:
//      absolute; inset: 0; width/height: 100%; object-fit: cover`) that covers the
//      whole border box. A positioned descendant paints in step 6 of CSS 2.1
//      Appendix E — AFTER the element's own background, inset shadows AND (in
//      Chromium) its outline. So a ring painted on the button's own box is hidden
//      by the poster.
//
// The first fix reflected the ring INWARD (`box-shadow: inset …` + `outline-offset:
// -2px`) which defeats (1) and walks straight into (2). MEASURED in headless
// Chromium on that exact CSS, keyboard-focused, deviceScaleFactor 1, with the
// poster's paint proven by a control (naturalWidth 9, resting strip 255.255.255):
// the focused strip was BYTE-IDENTICAL to the resting one — 0 of 24 pixels changed.
// Zero focus indication on every card that has a thumbnail, which is the normal
// state (useShortThumbnail.ts:46-52 serves an existing poster immediately and
// generates one on demand; the ▶ glyph is the documented FALLBACK). WCAG 2.4.7 was
// still open. In the glyph fallback the same CSS did paint 2px — which is why a
// no-poster check would have called it fixed.
//
// THE FIX THIS FILE NOW GUARDS: paint the house ring on the UNCLIPPED PARENT,
// `.shorts__thumb:has(.shorts__thumb-btn:focus-visible)`. An element's own
// box decorations are never clipped by its OWN `overflow`, and an OUTSET shadow
// lands outside its border box — where no descendant of it can ever be painted. So
// the fix is immune to both causes at once, and it reuses `--focus-ring` verbatim
// instead of inventing a second focus look. Measured on the shipped CSS: 4 device
// pixels change on focus WITH the poster present (x=4,5 `134.98.53` = the composited
// `--accent-edge`; x=6,7 `18.22.32` = the `--surface-bg` gap; the thumb's edge is at
// x=8), and 2 pixels under `forced-colors: active` (`0.0.0` from the substituted
// outline). Probe: %TEMP%/rf-ui-remediate/probe.mjs.
//
// WHAT THESE TESTS ARE, STATED PLAINLY: static parses of this sheet and of
// Shorts.tsx. They read the exact properties the painting algorithm consumes —
// which box the ring is painted on, whether it is inside or outside that box, what
// is nested inside it, and whether a channel is visible at all — but they do NOT
// paint, so they cannot by themselves certify a rendered pixel. UNVERIFIED IN CI:
// no automated gate in this repo observes this ring's pixels; the executed
// focused-vs-resting pixel diff above is the settling experiment and it lives in a
// scratch probe, not in the suite. Re-run it (or an equivalent `e2e/visual`
// screenshot of a focused card) before trusting any future change here.
//
// This file imports no TS source; it is a pure source-conformance check, following
// styles/tokens.conformance.test.ts.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { describe, it, expect } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHORTS_CSS = resolve(HERE, 'shorts.css');
const SHORTS_TSX = resolve(HERE, 'Shorts.tsx');
const TOKENS_CSS = resolve(HERE, '..', 'styles', 'tokens.css');

/** Strip comment blocks so prose can never register as a declaration. */
function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** `[selector, body]` for every rule in a stylesheet. */
function rules(css: string): readonly (readonly [string, string])[] {
  return [...stripComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(
    (m) => [m[1].trim(), m[2]] as const,
  );
}

/** The declaration body of the FIRST rule whose selector matches exactly. */
function ruleBody(css: string, selector: string): string | null {
  const want = selector.replace(/\s+/g, ' ').trim();
  for (const [sel, body] of rules(css)) {
    if (sel.split(',').some((s) => s.replace(/\s+/g, ' ').trim() === want)) return body;
  }
  return null;
}

/** The value of a declaration in a rule body (`null` when absent). */
function decl(body: string, prop: string): string | null {
  const m = new RegExp(`(?:^|;)\\s*${prop}\\s*:([^;]*)`).exec(body);
  return m ? m[1].trim() : null;
}

/** Expand `var(--x)` against a token sheet, recursively (tokens nest one level). */
function expandVars(value: string, tokens: string, depth = 4): string {
  if (depth === 0 || !value.includes('var(')) return value;
  const next = value.replace(/var\(\s*(--[A-Za-z0-9-]+)\s*\)/g, (whole, name: string) => {
    const m = new RegExp(`${name}\\s*:([^;]*)`).exec(tokens);
    return m ? m[1].trim() : whole;
  });
  return next === value ? value : expandVars(next, tokens, depth - 1);
}

/** True when a colour token would paint nothing: `transparent`, or alpha 0. */
function isInvisibleColor(color: string): boolean {
  if (/\btransparent\b/.test(color)) return true;
  const rgba = /rgba?\([^)]*?,\s*(0|0?\.0+)\s*\)/.exec(color);
  return rgba !== null;
}

/** True when a value carries at least one non-zero CSS length. */
function hasNonZeroLength(value: string): boolean {
  return [...value.matchAll(/(-?\d*\.?\d+)(px|rem|em|%)/g)].some(
    (m) => Number.parseFloat(m[1]) !== 0,
  );
}

/**
 * Does this rule body declare a ring channel that is VISIBLE in the normal palette?
 *
 * This is the assertion class the first version of this file lacked, and it is why
 * an equivalent mutant survived it: `outline: 2px solid transparent; outline-offset:
 * -0.01px; box-shadow: inset 0 0 0 0 transparent;` satisfies "has an inset shadow"
 * and "has a negative offset" while painting literally nothing. A channel counts
 * only when it has a non-zero length AND a colour that is not transparent.
 *
 * A transparent outline is NOT counted even though it is the sheet's deliberate
 * `forced-colors` carrier (shell.css:76-81) — under forced colours the UA
 * substitutes a system colour, so it is a ring THERE but not here, and this
 * predicate is about the normal palette.
 */
function hasVisibleRing(body: string, tokens: string): boolean {
  const shadow = decl(body, 'box-shadow');
  if (shadow !== null) {
    const expanded = expandVars(shadow, tokens);
    for (const layer of expanded.split(/,(?![^(]*\))/)) {
      if (hasNonZeroLength(layer) && !isInvisibleColor(layer)) return true;
    }
  }
  const border = expandVars(decl(body, 'border') ?? '', tokens);
  if (hasNonZeroLength(border) && !isInvisibleColor(border)) return true;
  const outline = decl(body, 'outline');
  const width = decl(body, 'outline-width');
  const color = decl(body, 'outline-color');
  const combined = expandVars([outline, width, color].filter((v) => v !== null).join(' '), tokens);
  return hasNonZeroLength(combined) && !isInvisibleColor(combined) && /solid|dashed/.test(combined);
}

/**
 * The source span of the JSX element that carries `className="<cls>"` — everything
 * BETWEEN its open and close tag. `''` for a self-closing element (no children).
 *
 * Deliberately structural rather than a "does the file mention X near Y" grep: the
 * whole point is which classes are NESTED INSIDE the ring's host, because that is
 * what decides paint order. The controls below prove the span is really bounded (a
 * sibling that sits OUTSIDE the button must not appear in it).
 */
function elementSpan(tsx: string, cls: string): string {
  const at = tsx.indexOf(`className="${cls}"`);
  if (at === -1) return '';
  const open = tsx.lastIndexOf('<', at);
  const tag = /^<([A-Za-z][\w.]*)/.exec(tsx.slice(open))?.[1];
  if (tag === undefined) return '';
  const gt = tsx.indexOf('>', at);
  if (gt === -1 || tsx[gt - 1] === '/') return '';
  const close = tsx.indexOf(`</${tag}>`, gt);
  return close === -1 ? '' : tsx.slice(gt + 1, close);
}

/** Class names rendered INSIDE the element that carries `className="<cls>"`. */
function childClassesOf(tsx: string, cls: string): readonly string[] {
  const span = elementSpan(tsx, cls);
  const out = new Set<string>();
  for (const m of span.matchAll(/className="([^"]*)"/g)) {
    for (const token of m[1].split(/\s+/)) if (token !== '') out.add(token);
  }
  return [...out];
}

/** Classes nested inside `cls` whose own rule makes them PAINT ABOVE its box. */
function occludersOf(css: string, tsx: string, cls: string): readonly string[] {
  return childClassesOf(tsx, cls)
    .filter((child) => {
      const body = ruleBody(css, `.${child}`);
      if (body === null) return false;
      if (!/position:\s*(?:absolute|relative|fixed|sticky)/.test(body)) return false;
      // A positioned descendant with `z-index: auto | 0` paints in step 6 of CSS 2.1
      // Appendix E, above the parent's own box decorations. A NEGATIVE z-index would
      // paint below them (step 2) and could not occlude a ring.
      const z = decl(body, 'z-index');
      return z === null || Number.parseFloat(z) >= 0 || Number.isNaN(Number.parseFloat(z));
    })
    .sort();
}

/** Where one `:focus-visible` rule paints its ring. */
interface RingSite {
  /** The full selector, for the failure message. */
  readonly selector: string;
  /** The class whose BOX the ring is painted on. */
  readonly host: string;
  /** The class that has to be focused for it to appear. */
  readonly control: string;
  /** True when the ring lands INSIDE `host`'s border box. */
  readonly inward: boolean;
  /** True when the ring is on a pseudo stacked ABOVE the host's positioned kids. */
  readonly stacked: boolean;
  /** True when at least one channel would actually paint. */
  readonly visible: boolean;
}

/**
 * Every focus-ring site in a stylesheet, classified.
 *
 * `host` is the subject of the selector, `control` the class carrying
 * `:focus-visible` — they differ exactly when the ring is moved to an ancestor via
 * `:has()`, which is the shape of the fix. A ring is `inward` when it is an inset
 * shadow, a negative outline-offset, or an `inset: 0` pseudo overlay.
 */
function ringSites(css: string, tokens: string): readonly RingSite[] {
  const out: RingSite[] = [];
  for (const [selector, body] of rules(css)) {
    if (!selector.includes(':focus-visible')) continue;
    const host = /^\.([A-Za-z0-9_-]+)/.exec(selector)?.[1];
    if (host === undefined) continue;
    const viaHas = /:has\(\s*\.([A-Za-z0-9_-]+):focus-visible/.exec(selector)?.[1];
    const pseudo = /::(?:before|after)\b/.test(selector);
    const offset = decl(body, 'outline-offset');
    const shadow = expandVars(decl(body, 'box-shadow') ?? '', tokens);
    const insetShadow = /(?:^|[\s,(])inset(?:[\s,]|$)/.test(shadow);
    const negativeOffset = offset !== null && Number.parseFloat(offset) < 0;
    const overlay = pseudo && /position:\s*absolute/.test(body);
    const z = Number.parseFloat(decl(body, 'z-index') ?? 'NaN');
    out.push({
      selector,
      host,
      control: viaHas ?? host,
      inward: insetShadow || negativeOffset || overlay,
      stacked: overlay && z > 0,
      visible: hasVisibleRing(body, tokens),
    });
  }
  return out;
}

/**
 * Controls whose every focus-ring site is eaten — occluded by a nested positioned
 * element, clipped away by a coincident ancestor clip, or invisible by colour.
 *
 * This is the whole gate. It is deliberately shape-AGNOSTIC: any site that survives
 * all three hazards clears the control, so the four fix shapes in the control test
 * below (ancestor ring, stacked pseudo overlay) both pass, while the two broken
 * ones (inward ring under a poster, transparent ring) both fail. The previous
 * version mandated ONE mechanism — an inset shadow plus a negative outline-offset —
 * which pinned the mechanism that measurably paints nothing and would have forced a
 * correct fix RED.
 */
function unringedControls(css: string, tsx: string, tokens: string): readonly string[] {
  const sites = ringSites(css, tokens);
  const clipping = new Set<string>();
  for (const [selector, body] of rules(css)) {
    if (!/overflow:\s*(?:hidden|clip)/.test(body)) continue;
    for (const cls of selector.matchAll(/\.([A-Za-z0-9_-]+)/g)) clipping.add(cls[1]);
  }
  /** Does `host` fill a clipping box, so an OUTSET ring on it is clipped away? */
  const fillsAClip = (host: string): boolean => {
    const body = ruleBody(css, `.${host}`) ?? '';
    if (!/width:\s*100%/.test(body) || !/height:\s*100%/.test(body)) return false;
    return [...clipping].some((c) => c !== host);
  };
  const byControl = new Map<string, RingSite[]>();
  for (const site of sites) {
    byControl.set(site.control, [...(byControl.get(site.control) ?? []), site]);
  }
  const bad: string[] = [];
  for (const [control, group] of byControl) {
    const survives = group.some((site) => {
      if (!site.visible) return false;
      if (site.inward && !site.stacked && occludersOf(css, tsx, site.host).length > 0) return false;
      if (!site.inward && fillsAClip(site.host)) return false;
      return true;
    });
    if (!survives) bad.push(control);
  }
  return bad.sort();
}

const CSS = readFileSync(SHORTS_CSS, 'utf8');
const TSX = readFileSync(SHORTS_TSX, 'utf8');
const TOKENS = stripComments(readFileSync(TOKENS_CSS, 'utf8'));

describe('gallery play-preview focus ring is paintable (W59)', () => {
  it('the JSX nesting reader is really bounded by the element (both controls)', () => {
    // The occlusion half of the gate rests entirely on this: which classes are
    // INSIDE the button. A reader that swept the whole file would drag in siblings
    // and manufacture occluders; one that found nothing would make the gate vacuous.
    const inside = childClassesOf(TSX, 'shorts__thumb-btn');
    expect(inside).toContain('shorts__thumb-img'); // the real occluder
    expect(inside).toContain('shorts__thumb-duration');
    // …and NOT the badge that is a SIBLING of the button (Shorts.tsx:346-351), nor
    // the parent. Either would prove the span was not bounded.
    expect(inside).not.toContain('shorts__virality');
    expect(inside).not.toContain('shorts__thumb');
    // A self-closing element has no children at all.
    expect(childClassesOf(TSX, 'shorts__thumb-img')).toEqual([]);
  });

  it('the occluder finder needs BOTH nesting and positioning', () => {
    // Two independent sources decide paint order and both are required: the TSX
    // says what is nested, the CSS says whether it is positioned. Drop either and
    // the answer flips — which is why this is checked rather than asserted.
    expect(occludersOf(CSS, TSX, 'shorts__thumb-btn')).toEqual([
      'shorts__thumb-duration',
      'shorts__thumb-img',
    ]);
    // A nested class that is NOT positioned cannot occlude (the ▶ glyph).
    expect(occludersOf(CSS, TSX, 'shorts__thumb-btn')).not.toContain('shorts__thumb-glyph');
    // A negative z-index paints BELOW the parent's box decorations, so it is not an
    // occluder — fed as a fixture because the live sheet has no such rule.
    const sunk = '.a { position: absolute; z-index: -1; }';
    expect(occludersOf(sunk, '<div className="p"><span className="a"/></div>', 'p')).toEqual([]);
  });

  it('the visibility predicate rejects the ring that paints nothing', () => {
    // The mutant that survived the first version of this file, verbatim.
    expect(
      hasVisibleRing(
        'outline: 2px solid transparent; outline-offset: -0.01px; box-shadow: inset 0 0 0 0 transparent;',
        TOKENS,
      ),
    ).toBe(false);
    // Zero-width, opaque: still nothing.
    expect(hasVisibleRing('box-shadow: inset 0 0 0 0 var(--accent);', TOKENS)).toBe(false);
    // …and the real channels ARE seen, including through a token that itself nests
    // `var()` (`--focus-ring` expands to two layers, one of them `--accent-edge`).
    expect(hasVisibleRing('box-shadow: var(--focus-ring);', TOKENS)).toBe(true);
    expect(hasVisibleRing('outline: 2px solid var(--accent-edge);', TOKENS)).toBe(true);
    expect(hasVisibleRing('border: 2px solid var(--accent);', TOKENS)).toBe(true);
    // A var() that does not resolve must not be reported as visible by accident.
    expect(hasVisibleRing('box-shadow: 0 0 0 2px var(--no-such-token);', TOKENS)).toBe(true);
  });

  it('the gate FIRES on both broken shapes and clears both correct ones', () => {
    // The four-way both-states control, and the load-bearing test in this file. The
    // shipped CSS is one of the two accepted shapes; a gate that could not tell
    // these four apart would certify the broken tree, which is exactly what
    // happened at 2b25bf62.
    const stage = [
      '.shorts__thumb { position: relative; overflow: hidden; }',
      '.shorts__thumb-btn { width: 100%; height: 100%; }',
      '.shorts__thumb-img { position: absolute; inset: 0; width: 100%; height: 100%; }',
    ].join('\n');
    const tsx =
      '<div className="shorts__thumb"><button className="shorts__thumb-btn">' +
      '<img className="shorts__thumb-img"/></button></div>';
    // (a) BROKEN — the shipped-at-2b25bf62 inward ring, under the poster. 0 px.
    const inwardUnderPoster =
      '.shorts__thumb-btn:focus-visible { outline: 2px solid var(--accent-edge); outline-offset: -2px; box-shadow: inset 0 0 0 2px var(--surface-bg); }';
    expect(unringedControls(`${stage}\n${inwardUnderPoster}`, tsx, TOKENS)).toEqual([
      'shorts__thumb-btn',
    ]);
    // (b) BROKEN — the outset house ring on the button itself: clipped away.
    const outsetOnButton = '.shorts__thumb-btn:focus-visible { box-shadow: var(--focus-ring); }';
    expect(unringedControls(`${stage}\n${outsetOnButton}`, tsx, TOKENS)).toEqual([
      'shorts__thumb-btn',
    ]);
    // (c) BROKEN — a declared-but-invisible ring in the accepted ancestor shape.
    const transparentOnParent =
      '.shorts__thumb:has(.shorts__thumb-btn:focus-visible) { outline: 2px solid transparent; outline-offset: 2px; }';
    expect(unringedControls(`${stage}\n${transparentOnParent}`, tsx, TOKENS)).toEqual([
      'shorts__thumb-btn',
    ]);
    // (d) CORRECT — the house ring on the unclipped ancestor (what ships).
    const onParent =
      '.shorts__thumb:has(.shorts__thumb-btn:focus-visible) { outline: 2px solid transparent; outline-offset: 2px; box-shadow: var(--focus-ring); }';
    expect(unringedControls(`${stage}\n${onParent}`, tsx, TOKENS)).toEqual([]);
    // (e) CORRECT — the OTHER viable shape: an opaque overlay on a pseudo stacked
    // above the poster. Accepted so this gate cannot forbid a legitimate fix.
    const overlay =
      '.shorts__thumb-btn:focus-visible::after { content: ""; position: absolute; inset: 0; z-index: 2; border: 2px solid var(--accent); }';
    expect(unringedControls(`${stage}\n${overlay}`, tsx, TOKENS)).toEqual([]);
    // …and the same overlay WITHOUT the winning z-index is back to being occluded.
    expect(
      unringedControls(`${stage}\n${overlay.replace('z-index: 2;', '')}`, tsx, TOKENS),
    ).toEqual(['shorts__thumb-btn']);
  });

  it('the two geometry premises the fix depends on still hold', () => {
    // If either stops being true the fix must be re-derived rather than trusted.
    // (i) the button still fills its clipping parent — so an OUTSET ring on the
    // BUTTON is still impossible, which is why the ring is on the parent;
    const thumb = ruleBody(CSS, '.shorts__thumb');
    expect(thumb).not.toBeNull();
    expect(thumb).toMatch(/overflow:\s*hidden/);
    const btn = ruleBody(CSS, '.shorts__thumb-btn');
    expect(btn).toMatch(/width:\s*100%/);
    expect(btn).toMatch(/height:\s*100%/);
    // (ii) the ring's host is a CHILD of `.shorts__card`, and that card does NOT
    // clip — otherwise the outset ring would be cut off in turn. `.shorts__grid` is
    // `overflow: auto` (:188) and clips at the SCROLL boundary; the ring sits inside
    // the card's own padding (measured: 4px in from the card edge, thumb edge at
    // 8px), so it is not at that boundary. UNVERIFIED: the appearance of a card
    // half-scrolled out of the grid — settling experiment: screenshot a focused card
    // pinned at the grid's top edge.
    expect(ruleBody(CSS, '.shorts__card')).not.toMatch(/overflow:\s*(?:hidden|clip)/);
    expect(elementSpan(TSX, 'shorts__thumb')).toContain('className="shorts__thumb-btn"');
  });

  it('the shared --focus-ring token is entirely OUTSET (so the host must not clip)', () => {
    // Read from the token, not assumed: the house ring has no inset layer, which is
    // both why it could never survive ON the button and why it works on the parent.
    const value = /--focus-ring:\s*([^;]*)/.exec(TOKENS);
    expect(value, 'tokens.css must still define --focus-ring').not.toBeNull();
    expect(/(?:^|[\s,(])inset(?:[\s,]|$)/.test(value?.[1] ?? '')).toBe(false);
  });

  it('every focus ring in this sheet actually reaches the screen', () => {
    // Sheet-wide, derived rather than hardcoded: `.shorts__reload` / `.shorts__sort-btn`
    // are not inside a coincident clip and have no positioned children, so their
    // plain outlines are correct and must NOT be "fixed".
    //
    // DETECTOR LIMITS, stated inline: nesting is read from Shorts.tsx only, so a
    // control rendered by another component contributes no occluders; a clipping
    // ancestor contributed by another stylesheet is invisible here; and this decides
    // paint ORDER from the properties the spec's painting algorithm uses, not from
    // pixels. Settling experiment: focus each control in a real Chromium and diff
    // the focused vs resting screenshot of its bounding box.
    const sites = ringSites(CSS, TOKENS);
    // NON-VACUITY, and NOT by hardcoding the mechanism: the defective control must
    // appear as a ring site under SOME shape, otherwise the scan below is empty.
    expect(sites.map((s) => s.control)).toContain('shorts__thumb-btn');
    expect(sites.length).toBeGreaterThan(1);
    expect(
      unringedControls(CSS, TSX, TOKENS),
      'Every focus ring for these controls is eaten before it reaches the screen — ' +
        'clipped by an ancestor, hidden under a positioned child, or transparent. A ' +
        'keyboard user gets no focus indication at all (WCAG 2.4.7).',
    ).toEqual([]);
  });
});
