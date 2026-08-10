// confirm-scrim.hittest.spec.ts — REAL-Chromium POINTER HIT-TEST gate for the
// themed destructive-confirm gate's scrim (W04 remediation).
//
// WHY THIS IS A PLAYWRIGHT SPEC AND NOT A VITEST TEST: `aria-modal="true"` on
// components/ConfirmDialog.tsx asserts that everything outside the dialog is
// inert. The keyboard half of that is pinned in jsdom (ConfirmDialog.test.tsx
// cages Tab). The POINTER half is a hit-testing fact — "would a click at this
// point reach the page behind the dialog?" — and jsdom performs no layout and no
// hit-testing, so nothing in the vitest suite can observe it. Only a real
// Chromium `document.elementFromPoint` can answer it.
//
// THE DEFECT (shipped once, found by adversarial review). The scrim was
// `.confirm-dialog::before { position: fixed; inset: 0 }` on a card that was
// itself `position: fixed` + `transform: translate(-50%,-50%)`. Per CSS Transforms
// Level 1 §3 a non-`none` `transform` makes the element a containing block for its
// fixed-position descendants, so `inset: 0` resolved against the CARD: the scrim
// was card-sized, painted behind the card, dimmed nothing and intercepted nothing,
// while the ARIA claimed the page was inert. Case 2 below reproduces exactly that
// stylesheet and REQUIRES it to fail — a probe that is silent in the broken state
// measures nothing.
//
// WHY IT DRIVES A PLAIN PAGE AND NOT THE ELECTRON APP: the question is a property
// of ONE stylesheet, and this spec loads THAT FILE off disk (renderer/src/
// components/confirmDialog.css + styles/tokens.css for its variables) rather than
// a hand-copy — a hand-copied stylesheet is the weakness that makes a CSS probe
// arguable. Building and booting the app would add minutes and a sidecar
// dependency without making the hit-test any more real. The DOM shape is the one
// ConfirmDialog.tsx emits, and its class contract (`{block}-scrim` wrapping
// `{block}[role=alertdialog]`) is independently pinned in ConfirmDialog.test.tsx,
// so a rename cannot leave this spec quietly testing nothing.
//
// SPEC LOCATION IS LOAD-BEARING: `e2e/` (NOT `e2e/audit/` or `e2e/visual/`), which
// playwright.config.ts collects via `testMatch: '**/*.spec.ts'` into the 4-OS
// `e2e-gui` matrix (`npm run test:e2e`); that job runs
// `npx playwright install --with-deps chromium`, so the browser this spec needs is
// already provisioned there. It is type-checked by `npm run typecheck:e2e`.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { test, expect, type Page } from '@playwright/test';

const HERE = dirname(fileURLToPath(import.meta.url));
const RENDERER = resolve(HERE, '..', 'renderer', 'src');
const TOKENS_CSS = readFileSync(resolve(RENDERER, 'styles', 'tokens.css'), 'utf8');
const CONFIRM_CSS = readFileSync(resolve(RENDERER, 'components', 'confirmDialog.css'), 'utf8');

/**
 * The stylesheet as it shipped BEFORE the fix, for the both-states control.
 *
 * Deliberately hand-written and deliberately small: it is not a claim about the
 * current file, it is the historical defect frozen so the oracle can be shown to
 * fire against it. Only the two properties that matter are reproduced — the card
 * is a `transform`-centred fixed box and the scrim is its `::before`.
 */
const BROKEN_CONFIRM_CSS = `
.confirm-dialog-scrim { display: contents; }
.confirm-dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  z-index: 200;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 28rem;
  padding: 20px;
  background: #1b212e;
}
.confirm-dialog::before {
  content: "";
  position: fixed;
  inset: 0;
  z-index: -1;
  background: var(--overlay-scrim);
}
`;

/**
 * The markup ConfirmDialog.tsx emits for `modal` + `block="confirm-dialog"`,
 * over a full-viewport background control that stands in for the app behind it.
 */
const PAGE_BODY = `
<style>
  html, body { margin: 0; padding: 0; height: 100%; }
  /* The page behind the gate: one full-viewport click target. If a click can
     reach THIS, the dialog is not modal, whatever its ARIA says. */
  #behind {
    position: absolute; inset: 0; width: 100%; height: 100%;
    border: 0; background: #101418;
  }
</style>
<button type="button" id="behind">the app behind the question</button>
<div class="confirm-dialog-scrim">
  <div class="confirm-dialog" role="alertdialog" aria-modal="true"
       aria-labelledby="t" aria-describedby="b">
    <h3 id="t" class="confirm-dialog-title">Delete this short?</h3>
    <p id="b" class="confirm-dialog-blurb">This removes the exported file.</p>
    <div class="confirm-dialog-actions">
      <button type="button" class="confirm-dialog-approve">Delete short</button>
      <button type="button" class="confirm-dialog-cancel">Keep it</button>
    </div>
  </div>
</div>
`;

/**
 * What `document.elementFromPoint` reports at a viewport point.
 *
 * Deliberately local rather than imported from e2e/overlay-hittest.spec.ts, which
 * carries a near-identical shape: that file is a SPEC, not a helper module, so
 * importing it here would make Playwright collect its four Electron-app tests a
 * second time as a dependency of this browser-only spec. The shapes also differ
 * (that one keeps a raw `cls` string for diagnostics; this one keys on `id`).
 */
interface HitTarget {
  tag: string;
  id: string;
  /** Exact class tokens — never substring-matched (`confirm-dialog` is a prefix
   *  of `confirm-dialog-scrim`, so a substring check could not tell them apart). */
  classes: string[];
  inView: boolean;
}

/**
 * Ask CHROMIUM ITSELF which element would receive a click at (x, y). It honours
 * stacking order AND `pointer-events`, unlike a "what is painted on top" guess.
 *
 * SELF-VALIDATING: `elementFromPoint` returns null outside the viewport, which
 * would read as "nothing intercepted" in EVERY state — a probe that measures
 * nothing. The `inView` assertion turns that into a named setup failure.
 */
async function hitTest(page: Page, x: number, y: number): Promise<HitTarget> {
  const hit = await page.evaluate(([px, py]) => {
    const el = document.elementFromPoint(px, py);
    return {
      tag: el?.tagName ?? '(none)',
      id: el?.id ?? '',
      classes: [...(el?.classList ?? [])],
      inView: px >= 0 && py >= 0 && px < window.innerWidth && py < window.innerHeight,
    };
  }, [x, y] as const);
  expect(
    hit.inView,
    `probe point (${x}, ${y}) is OUTSIDE the viewport — elementFromPoint cannot ` +
      'answer there, so this run measured nothing',
  ).toBe(true);
  return hit;
}

/** Mount the gate with `confirmCss` as the component stylesheet. */
async function mount(page: Page, confirmCss: string): Promise<void> {
  await page.setContent(
    `<!doctype html><html><head><style>${TOKENS_CSS}</style>` +
      `<style>${confirmCss}</style></head><body>${PAGE_BODY}</body></html>`,
  );
  await expect(page.locator('.confirm-dialog')).toBeVisible();
}

/** A point in the far top-left — unambiguously "the page behind the card". */
const BEHIND_POINT = { x: 10, y: 10 } as const;

// ---------------------------------------------------------------------------
// 1. DETECTOR CONTROL — the oracle must SEE the background when nothing covers it.
// ---------------------------------------------------------------------------
test('detector control — with no gate mounted, (10,10) hits the page behind', async ({ page }) => {
  await page.setContent(
    `<!doctype html><html><head><style>${TOKENS_CSS}</style></head><body>` +
      '<style>html,body{margin:0;height:100%}' +
      '#behind{position:absolute;inset:0;width:100%;height:100%;border:0}</style>' +
      '<button type="button" id="behind">the app</button></body></html>',
  );
  const hit = await hitTest(page, BEHIND_POINT.x, BEHIND_POINT.y);
  expect(hit.id, `oracle named ${hit.tag}#${hit.id} instead of the background button`).toBe(
    'behind',
  );
});

// ---------------------------------------------------------------------------
// 2. THE BOTH-STATES CONTROL — the probe must FIRE against the shipped defect.
// ---------------------------------------------------------------------------
// Without this, a green case 3 would be indistinguishable from a probe that is
// silent everywhere. Here the OLD stylesheet is mounted and the background MUST
// still be reachable: that is the bug, reproduced.
test('the pre-fix ::before scrim on a transform-centred card does NOT intercept', async ({
  page,
}) => {
  await mount(page, BROKEN_CONFIRM_CSS);
  const hit = await hitTest(page, BEHIND_POINT.x, BEHIND_POINT.y);
  expect(
    hit.id,
    'the broken stylesheet was expected to leave the page clickable; it did not, ' +
      'so this control no longer distinguishes the two states and case 3 proves nothing',
  ).toBe('behind');
  // And the reason: the "full-viewport" scrim is clipped to the card's own box.
  const scrimWidth = await page.evaluate(() => {
    const card = document.querySelector('.confirm-dialog') as HTMLElement;
    return {
      before: Number.parseFloat(getComputedStyle(card, '::before').width),
      viewport: window.innerWidth,
    };
  });
  expect(scrimWidth.before).toBeLessThan(scrimWidth.viewport);
});

// ---------------------------------------------------------------------------
// 3. THE FIX — the shipped stylesheet must swallow the click.
// ---------------------------------------------------------------------------
test('the shipped scrim intercepts pointer input aimed at the page behind', async ({ page }) => {
  await mount(page, CONFIRM_CSS);
  const hit = await hitTest(page, BEHIND_POINT.x, BEHIND_POINT.y);
  expect(
    hit.classes,
    `a click behind the gate reached ${hit.tag}#${hit.id}.${hit.classes.join('.')} — ` +
      'aria-modal="true" is a false claim to assistive tech while this is true',
  ).toContain('confirm-dialog-scrim');
  expect(hit.id).not.toBe('behind');
});

test('the shipped scrim covers the whole viewport and actually dims it', async ({ page }) => {
  await mount(page, CONFIRM_CSS);
  const geometry = await page.evaluate(() => {
    const scrim = document.querySelector('.confirm-dialog-scrim') as HTMLElement;
    const r = scrim.getBoundingClientRect();
    const cs = getComputedStyle(scrim);
    return {
      x: r.x,
      y: r.y,
      width: r.width,
      height: r.height,
      vw: window.innerWidth,
      vh: window.innerHeight,
      background: cs.backgroundColor,
      pointerEvents: cs.pointerEvents,
    };
  });
  expect({ x: geometry.x, y: geometry.y }).toEqual({ x: 0, y: 0 });
  expect(geometry.width).toBe(geometry.vw);
  expect(geometry.height).toBe(geometry.vh);
  // A VISIBLE dim, not a transparent hit-catcher: the user must see the page
  // recede behind the question.
  expect(geometry.background).not.toBe('rgba(0, 0, 0, 0)');
  expect(geometry.background).toMatch(/^rgba?\(/);
  expect(geometry.pointerEvents).toBe('auto');
});

// ---------------------------------------------------------------------------
// 4. OVER-CORRECTION GUARD — the card's own controls must still be clickable.
// ---------------------------------------------------------------------------
// A scrim that also eats the dialog's buttons would trade one broken surface for
// another (and there would be no way to answer the question at all).
test('the gate’s own approve button still receives its clicks', async ({ page }) => {
  await mount(page, CONFIRM_CSS);
  const box = await page.locator('.confirm-dialog-approve').boundingBox();
  expect(box, 'the approve button must be laid out').not.toBeNull();
  const r = box as { x: number; y: number; width: number; height: number };
  const hit = await hitTest(page, r.x + r.width / 2, r.y + r.height / 2);
  expect(
    hit.classes,
    `the approve button is unreachable; elementFromPoint → ${hit.tag}.${hit.classes.join('.')}`,
  ).toContain('confirm-dialog-approve');
});
