// captionOverlay.conformance.test.ts — container-query units must HAVE a
// container (W58).
//
// The pain this pins: `components/captionOverlay.css` sizes the caption in `cqw`
// (container query width) at two sites — the hook slot and the active caption line
// (:25 and :43 as measured at db61ea6e, before the fix comment shifted them) — but
// NOT ONE `container-type` / `container-name`
// declaration existed anywhere in the renderer CSS. Per CSS Containment 3 §2.1, a
// `cq*` unit with no ancestor container falls back to the SMALL VIEWPORT, so the
// caption sized itself against the application window instead of the phone stage
// it is drawn on.
//
// That is not a cosmetic drift, because the stage is nearly fixed-width:
// `features/shortmaker.css:22` sets `.sm-phone { width: min(248px, 100%) }`.
//
// CORRECTED ARITHMETIC — the first version of this block resolved the `rem` terms
// against a 16px root and reported "24.8px → 15.2px" and "unreachable above 496px".
// Both figures were WRONG: the root font-size in this app is 13px, because
// `components/shell.css` sets `html { font-size: var(--type-body-size) }` and
// `styles/tokens.css:145` defines `--type-body-size: 13px`. The UA default never
// applies. Re-resolved at 13px:
//
//   .caption-overlay__line  clamp(12.35px, <cqw>, 20.15px)
//     viewport 1920px → 96.00px → clamped to MAX 20.15px
//     248px stage, 5cqw (before) → 12.40px
//   .caption-overlay__hook  clamp(11.70px, <cqw>, …)
//     viewport 1920px → 86.40px → clamped to MAX 18.20px
//     248px stage, 4.5cqw (before) → 11.16px → clamped to MIN 11.70px
//
// REFUTED, recorded rather than deleted: this block used to end "…and resizing the
// app rescaled the caption while the stage it floats on did not move." That is
// impossible in this app and the arithmetic two lines above it says so. The clamp
// maximum is reached at any container ≥ 403px, and the Electron window cannot be
// narrower than `minWidth: 940` (app/main/main.ts). So the pre-fix value was pinned
// at its CEILING at EVERY attainable window size and never varied with window width.
// Correctly scoped: a FIXED over-size relative to the stage — 20.15px of caption on
// a 248x441 stage — at every window size the app can have.
//
// AND THE CONTAINER ALONE WAS NOT THE FIX. With the container established the
// governing term became `5cqw` = 12.40px = 2.81% of the stage height, while the burn
// sizes captions at 4.5% of the frame height (`sidecar/media_studio/features/
// caption.py:416`) — so the preview under-represented the export by 37.5%, on the one
// surface whose stated job is to show "how captions would look"
// (features/CandidateReview.tsx:125-127). The old clamp CEILING (20.15px = 4.57% of
// the stage height) happened to be within 2% of the burn, which is why the pre-fix
// render looked right and the post-container render looked small. Measured in
// headless Chromium on the real sheets: 12.40px / 2.81% before, 19.84px / 4.50%
// after. The `cqw` middle terms are therefore DERIVED from the sidecar constants
// below, not chosen.
//
// The wrap width had to move with it. `.caption-overlay__line` was `left: 50%` with
// `right: auto`, so its shrink-to-fit width was only 124px of the 248px stage (50%),
// where the burn wraps at 1000/1080 = 92.6% (`caption.py:427` MarginL/R 40). At the
// export-faithful font size with the old 50% wrap the line is 280.5px tall in a
// 440.9px stage and OVERLAPS the hook by 174.2px (measured) — the exact defect this
// surface was flagged for. With the burn's wrap width it is 128.1px tall with 89.6px
// of clearance. Fidelity and geometry are one fix, not two.
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
const SHORTMAKER_CSS = resolve(HERE, '..', 'features', 'shortmaker.css');
const SIDECAR = resolve(HERE, '..', '..', '..', '..', 'sidecar', 'media_studio', 'features');
const CAPTION_PY = resolve(SIDECAR, 'caption.py');
const SHORTMAKER_PY = resolve(SIDECAR, 'shortmaker.py');

/**
 * The burn constants this preview has to mirror, read from the sidecar rather than
 * copied into this file.
 *
 * DELIBERATE CROSS-BOUNDARY COUPLING, disclosed: retuning the burn now fails a
 * RENDERER test. That is the intended direction — this overlay exists only to
 * approximate the export (features/CandidateReview.tsx:125-127), so a burn change
 * that the preview does not follow is a defect, not an inconvenience. The parse is
 * controlled below; a silently-broken regex must not read as "no constraint".
 */
function burnConstants(): {
  outWidth: number;
  aspectW: number;
  aspectH: number;
  lineFontFrac: number;
  hookFontFrac: number;
  lineMargin: number;
  hookMargin: number;
} {
  const caption = readFileSync(CAPTION_PY, 'utf8');
  const maker = readFileSync(SHORTMAKER_PY, 'utf8');
  const num = (re: RegExp, src: string): number => {
    const m = re.exec(src);
    return m === null ? Number.NaN : Number.parseFloat(m[1]);
  };
  return {
    outWidth: num(/^OUT_WIDTH\s*=\s*(\d+)/m, maker),
    aspectW: num(/^DEFAULT_ASPECT\s*=\s*"(\d+):\d+"/m, maker),
    aspectH: num(/^DEFAULT_ASPECT\s*=\s*"\d+:(\d+)"/m, maker),
    lineFontFrac: num(
      /font_size\s*=\s*max\(\d+,\s*int\(round\(play_y\s*\*\s*([\d.]+)\)\)\)/,
      caption,
    ),
    hookFontFrac: num(
      /title_size\s*=\s*max\(\d+,\s*int\(round\(play_y\s*\*\s*([\d.]+)\)\)\)/,
      caption,
    ),
    // The body caption's default style: `… = 2, 40, 40, default_margin_v`.
    lineMargin: num(
      /alignment,\s*margin_l,\s*margin_r,\s*margin_v\s*=\s*\d+,\s*(\d+),\s*\d+,/,
      caption,
    ),
    // The hook style line ends `…,8,60,60,{title_margin_v},1`.
    hookMargin: num(/"8,(\d+),\d+,\{title_margin_v\},1"/, caption),
  };
}

/** `[min, middle, max]` of the `clamp()` in a `font-size`, as authored. */
function clampTerms(body: string): readonly [string, string, string] | null {
  const m = /font-size:\s*clamp\(([^,]+),([^,]+),([^)]+)\)/.exec(body);
  return m === null ? null : [m[1].trim(), m[2].trim(), m[3].trim()];
}

/** A CSS length in px, resolving `rem` at this app's REAL 13px root. */
function toPx(term: string, rootPx = 13): number {
  const m = /(-?[\d.]+)(rem|px)/.exec(term);
  if (m === null) return Number.NaN;
  return Number.parseFloat(m[1]) * (m[2] === 'rem' ? rootPx : 1);
}

/** The numeric part of a `cqw` term. */
function toCqw(term: string): number {
  const m = /(-?[\d.]+)cqw/.exec(term);
  return m === null ? Number.NaN : Number.parseFloat(m[1]);
}

/** An inset (`left`/`right`) as a percentage of the containing block. */
function insetPct(body: string, side: 'left' | 'right'): number {
  const m = new RegExp(`(?:^|;)\\s*${side}\\s*:\\s*([\\d.]+)%`).exec(body);
  return m === null ? Number.NaN : Number.parseFloat(m[1]);
}

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

  it('pins the 13px root the clamp arithmetic above depends on', () => {
    // The px figures in this file's header are only true at a 13px root, and the
    // first version of them was wrong precisely because it assumed the 16px UA
    // default. This makes the assumption CHECKED rather than asserted in prose: if a
    // later lane retunes the body size or stops feeding it to `html`, this fails and
    // the numbers get re-derived instead of silently rotting.
    const tokens = stripComments(readFileSync(resolve(HERE, '..', 'styles', 'tokens.css'), 'utf8'));
    expect(/--type-body-size:\s*13px/.test(tokens)).toBe(true);
    // The rule is a GROUPED selector — `html, body, #root { … }` — so this looks for
    // `html` as a whole ENTRY of the selector list. A `html\s*\{` regex reports it
    // absent, which is what the first version of this test did. Only the root element
    // matters for `rem`; body/#root sharing the declaration is incidental.
    const shell = stripComments(readFileSync(resolve(HERE, 'shell.css'), 'utf8'));
    const rootRule = [...shell.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find((m) =>
      m[1]
        .split(',')
        .map((s) => s.trim())
        .includes('html'),
    );
    expect(rootRule, 'components/shell.css must still carry a rule for `html`').not.toBeUndefined();
    expect(rootRule?.[2]).toMatch(/font-size:\s*var\(--type-body-size\)/);
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

describe('the preview mirrors the burn it previews (W58 fidelity)', () => {
  const BURN = burnConstants();
  const CSS = stripComments(readFileSync(OVERLAY_CSS, 'utf8'));
  const LINE = /\.caption-overlay__line\s*\{([^}]*)\}/.exec(CSS)?.[1] ?? '';
  const HOOK = /\.caption-overlay__hook\s*\{([^}]*)\}/.exec(CSS)?.[1] ?? '';

  it('reads the burn constants out of the sidecar (the parse actually parsed)', () => {
    // Control every instrument BEFORE any assertion depends on it: a regex that
    // silently stopped matching would yield NaN and every comparison below would
    // read as "no constraint met" or, worse, as trivially satisfied.
    expect(BURN.outWidth).toBe(1080); // shortmaker.py OUT_WIDTH
    expect([BURN.aspectW, BURN.aspectH]).toEqual([9, 16]); // DEFAULT_ASPECT
    expect(BURN.lineFontFrac).toBeCloseTo(0.045, 5); // caption.py:416
    expect(BURN.hookFontFrac).toBeCloseTo(0.055, 5); // caption.py:351
    expect(BURN.lineMargin).toBe(40); // caption.py:427 MarginL
    expect(BURN.hookMargin).toBe(60); // caption.py:359 MarginL
    // …and the derived helpers see what is really authored, plus reject a look-alike.
    expect(clampTerms(LINE)).not.toBeNull();
    expect(clampTerms('font-size: 12px;')).toBeNull();
    expect(toPx('1.55rem')).toBeCloseTo(20.15, 5);
    expect(toPx('12px')).toBe(12);
    expect(Number.isNaN(toCqw('1.55rem'))).toBe(true);
  });

  it('the preview stage really is the burn aspect (the height premise)', () => {
    // `cqw` is 1% of the container's INLINE size, but both burn constants are
    // fractions of the frame HEIGHT. The conversion is only valid because the stage
    // carries the export's aspect — read from the sheet, not assumed.
    const maker = stripComments(readFileSync(SHORTMAKER_CSS, 'utf8'));
    const stage = /\.shortmaker\s+\.sm-phone\s*\{([^}]*)\}/.exec(maker)?.[1] ?? '';
    expect(stage).toMatch(/width:\s*min\(248px,\s*100%\)/);
    expect(maker).toMatch(new RegExp(`aspect-ratio:\\s*${BURN.aspectW}\\s*/\\s*${BURN.aspectH}`));
    // And the overlay is stretched over that whole box, so its inline size IS the
    // stage's — which is what makes `cqw` the stage's width.
    expect(/\.caption-overlay\s*\{([^}]*)\}/.exec(CSS)?.[1]).toMatch(/inset:\s*0/);
  });

  it('both cqw terms ARE the burn ratio, converted from height to width', () => {
    // f of the frame HEIGHT is f * (16/9) of the frame WIDTH, i.e. of the container
    // inline size `cqw` measures. Derived, so retuning caption.py fails here rather
    // than silently drifting the preview.
    const perWidth = (frac: number): number => frac * (BURN.aspectH / BURN.aspectW) * 100;
    expect(toCqw(clampTerms(LINE)?.[1] ?? '')).toBeCloseTo(perWidth(BURN.lineFontFrac), 2);
    expect(toCqw(clampTerms(HOOK)?.[1] ?? '')).toBeCloseTo(perWidth(BURN.hookFontFrac), 1);
  });

  it('the ratio term GOVERNS at the real stage width (neither clamp end binds)', () => {
    // The defect class this closes is a clamp end silently overriding the derived
    // term — which is exactly what shipped both before (ceiling) and after (floor,
    // 12.40px against a 12.35px min). A ratio that is authored but clamped away is
    // not a fix. 248px comes from `.sm-phone`; rem resolves at the 13px root pinned
    // by the test above.
    const stagePx = 248;
    for (const [name, body] of [
      ['line', LINE],
      ['hook', HOOK],
    ] as const) {
      const terms = clampTerms(body);
      expect(terms, `${name} must size itself with a clamp()`).not.toBeNull();
      const governing = (toCqw(terms?.[1] ?? '') / 100) * stagePx;
      expect(governing, `${name}: the clamp MIN binds at the stage width`).toBeGreaterThan(
        toPx(terms?.[0] ?? ''),
      );
      expect(governing, `${name}: the clamp MAX binds at the stage width`).toBeLessThan(
        toPx(terms?.[2] ?? ''),
      );
    }
  });

  it('both boxes wrap at the burn wrap width, not at shrink-to-fit', () => {
    // The other half of the fidelity fix, and the reason the font fix is safe: an
    // absolutely-positioned box with `left: 50%` and `right: auto` has an available
    // width of only 50% of the stage, so it wraps twice as often as the burn and the
    // caption grows upward into the hook. Insets are derived from the ASS margins.
    const inset = (margin: number): number => (margin / BURN.outWidth) * 100;
    for (const [name, body, margin] of [
      ['line', LINE, BURN.lineMargin],
      ['hook', HOOK, BURN.hookMargin],
    ] as const) {
      expect(insetPct(body, 'left'), `${name} left inset`).toBeCloseTo(inset(margin), 1);
      expect(insetPct(body, 'right'), `${name} right inset`).toBeCloseTo(inset(margin), 1);
      // A horizontal translate on a both-edges-anchored box would shift it off centre.
      expect(body, `${name} must not also translate horizontally`).not.toMatch(
        /transform:\s*translate(?:X)?\(\s*-?50%/,
      );
    }
  });

  it('names the fidelity gaps this file does NOT close', () => {
    // Stated as an executable reminder rather than prose that can rot: the VERTICAL
    // placement is not export-faithful and is not fixed here. The line's is an inline
    // style in CaptionOverlay.tsx (`positionStyle`, outside this sheet); the hook's
    // `top` is in this sheet but moving it alone would make the pair less coherent,
    // not more. Measured: preview line `bottom: 14%` vs the burn's 6%
    // (caption.py:418 `play_y * 0.06`), preview hook `top: 5%` vs 7% (:352
    // `play_y * 0.07`). Settling experiment for the whole surface: burn a clip and
    // diff the rendered frame against a screenshot of this overlay at the same scale.
    expect(HOOK).toMatch(/top:\s*5%/);
    expect(/play_y\s*\*\s*0\.07/.test(readFileSync(CAPTION_PY, 'utf8'))).toBe(true);
    // Nor does it apply the template's `sizeScale`: `previewSizeScale`
    // (lib/captionOverridePreview.ts:48-50) is consumed by the CaptionDesigner
    // sample, not by this overlay, while the burn multiplies the font by it
    // (caption.py:417). So the ratios above are faithful for sizeScale = 1 only.
    expect(readFileSync(resolve(HERE, 'CaptionOverlay.tsx'), 'utf8')).not.toContain(
      'previewSizeScale',
    );
  });
});
