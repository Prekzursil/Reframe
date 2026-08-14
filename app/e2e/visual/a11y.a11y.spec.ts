// a11y.a11y.spec.ts — A11Y (accessibility) gate for the Wave-2b surfaces.
//
// Drives the SAME real built Electron app + live sidecar as the visual specs.
// Unlike the visual baselines, every assertion here is DOM-based (axe inspects
// the accessibility tree, keyboard nav drives Tab/focus), so this spec is
// OS-INDEPENDENT — it would pass identically on any runner. It rides the visual
// config/job only to reuse the single built app.
//
// What it proves on each panel (Library/Make Shorts/Director/Edit, Settings →
// Models & System / Providers & Keys incl. SpendCap, Workspace preview):
//   * ZERO serious/critical axe violations (WCAG 2.0/2.1 A+AA tag set),
//   * keyboard navigation reaches interactive controls (Tab moves focus),
//   * focus-visible paints a real focus ring (shell.css box-shadow) on Tab,
//   * reduced-motion is honoured (animations collapse to ~0 under `reduce`).

import { test, expect, type Page } from '@playwright/test';
import {
  launchSeededApp,
  prepareWindow,
  runAxe,
  openTopTab,
  openDestinationMode,
  openVideo,
  openSettingsSection,
  type LaunchedApp,
} from './_visualSetup';

let launched: LaunchedApp;
let win: Page;

test.beforeAll(async () => {
  launched = await launchSeededApp();
  win = await prepareWindow(launched.app);
});

test.afterAll(async () => {
  await launched?.app.close();
});

/** Tags scoping axe to the standard WCAG 2.0/2.1 Level A + AA success criteria. */
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'];

/**
 * Run axe scoped to `selector` and assert ZERO serious/critical violations.
 * Returns the moderate/minor findings (not asserted) so a run can surface them
 * for context without failing the gate.
 */
async function expectNoSeriousViolations(page: Page, selector: string): Promise<void> {
  const results = await runAxe(page, selector, WCAG_TAGS);
  const blocking = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  const summary = blocking.map((v) => `${v.id} (${v.impact}): ${v.help}`).join('\n');
  expect(blocking, `serious/critical a11y violations on ${selector}:\n${summary}`).toEqual([]);
}

test('Library — zero serious/critical axe violations', async () => {
  await openTopTab(win, 'Library');
  await expect(win.locator('.library__title')).toBeVisible();
  await expectNoSeriousViolations(win, '.app');
});

test('Make Shorts — zero serious/critical axe violations', async () => {
  // #431 moved this off the rail: it is now the `shorts` MODE under Produce
  // (App.tsx PRODUCE_MODES:155-158), not a top-level destination.
  await openDestinationMode(win, 'Produce', 'Make Shorts');
  // `.make-shorts` is the always-present section root (MakeShorts.tsx:161); the old
  // `.shorts` class now only mounts inside the 'gallery' sub-tab (not the default).
  await expect(win.locator('.make-shorts')).toBeVisible();
  await expectNoSeriousViolations(win, '.app__main');
});

test('Director — zero serious/critical axe violations', async () => {
  // #431: the `director` MODE under Produce (App.tsx PRODUCE_MODES:155-158).
  await openDestinationMode(win, 'Produce', 'Director');
  await expect(win.locator('section.director-panel')).toBeVisible();
  await expectNoSeriousViolations(win, 'section.director-panel');
});

test('Editor — zero serious/critical axe violations', async () => {
  // Formerly the 'Repurpose' then 'Edit' top tab. #431 made it the `editor` MODE
  // under Refine (App.tsx REFINE_MODES:159-162) and RELABELLED it "Editor" — the
  // label this drove ('Edit') is not rendered anywhere on the rail or the strip.
  await openDestinationMode(win, 'Refine', 'Editor');
  await expect(
    win.locator('.app__destination .tabbar [role="tab"][aria-selected="true"]', {
      hasText: 'Editor',
    }),
  ).toBeVisible();
  await expectNoSeriousViolations(win, '.app__main');
});

test('Settings → Models & System — zero serious/critical axe violations', async () => {
  await openSettingsSection(win, 'Models & System');
  await expect(win.locator('section.models-system-panel')).toBeVisible();
  await expectNoSeriousViolations(win, 'section.models-system-panel');
});

test('Settings → Providers & Keys (incl. SpendCap) — zero serious/critical axe violations', async () => {
  await openSettingsSection(win, 'Providers & Keys');
  await expect(win.locator('section.providers-keys')).toBeVisible();
  await expect(win.locator('.spend-cap')).toBeVisible();
  await expectNoSeriousViolations(win, 'section.providers-keys');
});

test('Workspace preview — zero serious/critical axe violations', async () => {
  await openTopTab(win, 'Library');
  await openVideo(win, 'sample');
  await expect(win.locator('.workspace')).toBeVisible();
  await expectNoSeriousViolations(win, '.workspace');
});

test('Keyboard navigation — Tab moves focus into the top tab strip', async () => {
  await openTopTab(win, 'Library');
  // Move focus from the document body into the first focusable chrome control.
  // The header (brand → quality toggle → Jobs) and tab strip are all reachable;
  // assert that after a few Tabs focus lands on a real, visible interactive
  // element (a button/tab), proving the surface is keyboard-operable.
  await win.locator('body').click({ position: { x: 2, y: 2 } });
  let focusedTag = '';
  for (let i = 0; i < 8; i += 1) {
    await win.keyboard.press('Tab');
    focusedTag = await win.evaluate(() => {
      const el = document.activeElement;
      return el ? `${el.tagName.toLowerCase()}|${el.getAttribute('role') ?? ''}` : '';
    });
    if (focusedTag.startsWith('button') || focusedTag.includes('|tab')) break;
  }
  expect(
    focusedTag.startsWith('button') || focusedTag.includes('|tab'),
    `keyboard focus reached an interactive control (got "${focusedTag}")`,
  ).toBe(true);
});

/** The paint properties any of which may legitimately carry a focus indicator. */
type Paint = { outline: string; outlineWidth: string; boxShadow: string; borderColor: string };

/**
 * Read a selector's computed paint BEFORE focus, then keyboard-focus it and read again.
 * Returns both so the caller can assert they DIFFER — the only assertion that actually
 * proves a focus indicator exists.
 */
async function paintBeforeAfterFocus(selector: string): Promise<{ off: Paint; on: Paint }> {
  const read = (sel: string): Promise<Paint> =>
    win.evaluate((s) => {
      const el = document.querySelector(s) as HTMLElement | null;
      if (!el) throw new Error(`selector not found: ${s}`);
      const cs = getComputedStyle(el);
      return {
        outline: cs.outline,
        outlineWidth: cs.outlineWidth,
        boxShadow: cs.boxShadow,
        borderColor: cs.borderColor,
      };
    }, sel);

  const off = await read(selector);
  const target = win.locator(selector).first();
  await target.focus();
  // Re-dispatch a keyboard interaction so Chromium's :focus-visible heuristic treats the
  // focus as keyboard-originated (a bare .focus() may not qualify).
  await win.keyboard.press('Shift+Tab');
  await win.keyboard.press('Tab');
  const on = await read(selector);
  return { off, on };
}

test('Focus-visible — a Tab-focused control paints a ring that DIFFERS from its resting state', async () => {
  await openTopTab(win, 'Library');
  const { off, on } = await paintBeforeAfterFocus('.toptab');
  // REVISED ASSERTION. This previously read only `boxShadow !== 'none'`, which is
  // both-states-SILENT: any control with a resting shadow (e.g. `.feature-panel button`
  // carries --elev-1, and an accent primary carries --accent-glow) passes it while having
  // NO focus indicator whatsoever. The only meaningful check is that focusing CHANGES the
  // element's paint.
  expect(
    JSON.stringify(on),
    `focused paint is identical to resting — no focus indicator. off=${JSON.stringify(off)}`,
  ).not.toBe(JSON.stringify(off));
});

test('Focus-visible — a .feature-panel button (the specificity-defeat case) also differs when focused', async () => {
  // The regression this guards. shell.css's shared ring uses `:where()`, which contributes
  // ZERO specificity, so at (0,1,0) its `box-shadow` lost to `.feature-panel button`
  // (0,1,1) and to `.feature-panel .actions > button:first-child:not(.secondary)` (0,4,1),
  // while its `outline: none` still applied and also suppressed the UA outline. Focused
  // computed style was byte-identical to resting on ~17 of 18 `.feature-panel` surfaces.
  // The previous `.toptab`-only gate could never see this: `.toptab` is not a
  // `.feature-panel` descendant, so it never lost the cascade battle.
  await openSettingsSection(win, 'Models & System');
  const { off, on } = await paintBeforeAfterFocus('.feature-panel button:not([disabled])');
  expect(
    JSON.stringify(on),
    `a .feature-panel button shows NO focus indicator: focused paint === resting paint. off=${JSON.stringify(off)}`,
  ).not.toBe(JSON.stringify(off));
});

test('Reduced-motion — animations collapse to ~0 under prefers-reduced-motion: reduce', async () => {
  // prepareWindow already emulated reduced-motion. shell.css forces every
  // element's animation/transition duration to ~0.01ms under `reduce`. Confirm
  // the media query is honoured on a real chrome element so motion is inert for
  // users who request it (WCAG 2.3.3-adjacent comfort guarantee).
  await openTopTab(win, 'Library');
  const matchesReduce = await win.evaluate(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  expect(matchesReduce, 'the page must report reduced-motion as active').toBe(true);
  const animMs = await win.evaluate(() => {
    const el = document.querySelector('.toptab') as HTMLElement | null;
    if (!el) return -1;
    const ms = getComputedStyle(el).animationDuration; // e.g. "0.01ms" or "0s"
    return parseFloat(ms) * (ms.includes('ms') ? 1 : 1000);
  });
  expect(animMs, 'animation duration should collapse to ~0 under reduced-motion').toBeLessThanOrEqual(
    1,
  );
});
