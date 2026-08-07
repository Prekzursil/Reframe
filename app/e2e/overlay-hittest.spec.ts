// overlay-hittest.spec.ts — REAL-Chromium POINTER HIT-TEST gate for the caption
// overlay (audit F22).
//
// WHY THIS IS A PLAYWRIGHT SPEC AND NOT A VITEST TEST: the defect is purely a
// hit-testing fact. jsdom performs no layout and does not implement
// `pointer-events`, and the renderer's own CaptionBox unit suite dispatches
// MouseEvents straight AT `.caption-box-frame` (CaptionBox.test.tsx), so it can
// never observe that the frame is stealing the <video>'s clicks. Only a real
// Chromium `document.elementFromPoint` can answer "which element would actually
// receive a click here", which is exactly the question F22 asks.
//
// THE DEFECT: `.caption-box-frame` is `position:absolute; inset:0; z-index:3`
// over the plain in-flow `<video controls>` the Player emits, with no
// `pointer-events: none` (captionBox.css). It therefore swallows every pointer
// event inside the 9:16 stage — including the native control bar at its bottom —
// so a mouse-only user has no play/pause/seek on the Caption surface (which
// renders no transport of its own; CaptionClipLane's mouse path only selects a
// cue, CaptionClipLane.tsx). The same `<Player controls /> + <CaptionBox>`
// sibling pattern is also live in components/CaptionDesigner.tsx (mounted from
// views/MakeShorts.tsx), so ONE stylesheet governs two shipped surfaces.
//
// SPEC LOCATION IS LOAD-BEARING: this file sits at `e2e/` (NOT `e2e/audit/`),
// because playwright.config.ts `testIgnore: ['visual/**', 'audit/**']` would
// exclude an audit/** spec from every CI job, and there is no audit npm script.
// Here it is matched by `testMatch: '**/*.spec.ts'` and runs in the 4-OS
// `e2e-gui` matrix (`npm run test:e2e`), and is type-checked by
// `npm run typecheck:e2e` (tsconfig.e2e.json includes e2e/**). Importing the
// launch helpers from ./visual/_visualSetup.ts is safe — that file is a helper
// module, not a spec, so it is not itself collected here.

import { test, expect, type Page } from '@playwright/test';
import {
  launchSeededApp,
  prepareWindow,
  openTopTab,
  openVideo,
  type LaunchedApp,
} from './visual/_visualSetup';

let launched: LaunchedApp;
let win: Page;

test.beforeAll(async () => {
  launched = await launchSeededApp();
  win = await prepareWindow(launched.app);
});

test.afterAll(async () => {
  await launched?.app.close();
});

/** What `document.elementFromPoint` reports at a viewport point. */
interface HitInfo {
  tag: string;
  /** The raw class attribute — for diagnostics in failure messages only. */
  cls: string;
  /**
   * The class list as EXACT tokens. Every assertion below matches on these, never
   * on `cls` substrings: `'caption-box-frame'` CONTAINS the substring
   * `'caption-box'`, so a substring assertion could not tell the dead overlay from
   * the live draggable box and would pass spuriously.
   */
  classes: string[];
  /** Whether the sampled point was inside the viewport at all (see hitTest). */
  inView: boolean;
}

/**
 * Ask CHROMIUM ITSELF which element would receive a click at (x, y). This is the
 * oracle: it honours stacking order AND `pointer-events`, unlike a "what is
 * painted on top" heuristic. `className` is read defensively because it is an
 * SVGAnimatedString (not a string) on SVG elements.
 *
 * SELF-VALIDATING: `elementFromPoint` returns null for a point OUTSIDE the
 * viewport, and Playwright's `toBeVisible()` does NOT imply in-viewport (it only
 * requires a non-empty box), so a below-the-fold target silently yields `(none)`
 * in every state — a probe that is equally dead before and after a fix, i.e. one
 * that measures nothing. The `inView` assertion converts that into a named setup
 * failure instead of a mystery verdict. (Measured: the MakeShorts designer probe
 * did exactly this until `scrollIntoViewIfNeeded` was added.)
 */
async function hitTest(page: Page, x: number, y: number): Promise<HitInfo> {
  const hit = await page.evaluate(([px, py]) => {
    const el = document.elementFromPoint(px, py);
    const cls = typeof el?.className === 'string' ? el.className : '';
    return {
      tag: el?.tagName ?? '(none)',
      cls,
      classes: [...(el?.classList ?? [])],
      inView: px >= 0 && py >= 0 && px < window.innerWidth && py < window.innerHeight,
    };
  }, [x, y] as const);
  expect(
    hit.inView,
    `probe point (${Math.round(x)}, ${Math.round(y)}) is OUTSIDE the viewport — ` +
      'elementFromPoint cannot answer there, so this run measured nothing',
  ).toBe(true);
  return hit;
}

/** The laid-out box of `selector`, failing loudly rather than returning null. */
async function boxOf(
  page: Page,
  selector: string,
): Promise<{ x: number; y: number; width: number; height: number }> {
  const rect = await page.locator(selector).boundingBox();
  expect(rect, `boundingBox(${selector}) — element must be laid out`).not.toBeNull();
  return rect as { x: number; y: number; width: number; height: number };
}

/**
 * Hit-test the native control bar of the <video> at `videoSelector`.
 *
 * Samples 16px up from the video's bottom edge — inside Chromium's control bar —
 * in the LEFT third, near play/pause. The left-third x and the 16px depth both
 * keep the probe clear of the default caption box's s/sw/se resize handles, which
 * sit at `bottom: -12px` with a 24px hit area (captionBox.css) and so end
 * (0.08 * H - 12)px above the bottom edge for the default box (y+h = 0.92).
 *
 * NOTE this deliberately does NOT depend on the control bar being *visible*:
 * Chromium's media controls live in the <video>'s closed shadow DOM, so
 * `elementFromPoint` reports the <video> host either way. Reaching the host IS
 * the necessary and sufficient condition for those controls to be clickable —
 * which is exactly what the overlay was preventing.
 */
async function probeControlBar(page: Page, videoSelector: string): Promise<HitInfo> {
  // MANDATORY before measuring: `boundingBox()` does not scroll, and the
  // MakeShorts designer sits below the fold, so without this the probe point
  // lands outside the viewport and elementFromPoint returns null in EVERY state.
  //
  // `scrollIntoViewIfNeeded()` alone is NOT enough, and this cost a red Windows CI
  // leg: it scrolls the MINIMUM needed to make an element visible, so for an element
  // taller than the remaining space it can stop with the TOP in view and the BOTTOM
  // still below the fold. This probe samples the bottom edge, which is exactly the
  // edge that stayed off-screen. Measured on run 31222301375 (windows-latest): the
  // guard in `hitTest` fired with "probe point (641, 837) is OUTSIDE the viewport"
  // against an 820px-tall window — the video's bottom edge was at y=853.
  //
  // `scrollIntoView({ block: 'end' })` aligns the element's BOTTOM with the
  // scrollport's bottom, and acts on the nearest scrollable ANCESTOR rather than only
  // the window — which matters here because the app shell scrolls inner containers,
  // so a `window.scrollBy` would have been a no-op.
  await page.locator(videoSelector).scrollIntoViewIfNeeded();
  await page
    .locator(videoSelector)
    .evaluate((el) => el.scrollIntoView({ block: 'end', inline: 'nearest' }));
  const r = await boxOf(page, videoSelector);
  // The self-validating guard in `hitTest` stays the authority: if the point is STILL
  // outside after this, the run genuinely measured nothing and must fail loudly rather
  // than report a null hit as a passing "no interception".
  return hitTest(page, r.x + r.width * 0.15, r.y + r.height - 16);
}

/**
 * Drive the app to a mounted Caption stage, from ANY starting route.
 *
 * Every stage test calls this rather than relying on the previous test's route:
 * Playwright discards the worker process after a failed test and starts a fresh
 * one, which re-runs `beforeAll` and lands the app back on the Library. A test
 * that assumed the earlier navigation then fails with "element not found" — a
 * FIXTURE error that proves nothing about the defect.
 *
 * Caption.tsx renders an "Open a video to caption" EMPTY STATE (no stage, no
 * overlay) when `editVideo` is null, so the video must be opened first.
 */
async function openCaptionStage(page: Page): Promise<void> {
  await openTopTab(page, 'Caption');
  // Settle on ONE of Caption's two states before branching, so the count() below
  // cannot race the route's first render.
  await page
    .locator('.caption-stage__frame, .caption-view--empty')
    .first()
    .waitFor({ state: 'visible' });
  if ((await page.locator('.caption-stage__frame').count()) === 0) {
    // Empty state => no video open yet. Open one, then come back. This branch is
    // taken exactly once per launched app: `openVideo` is NOT idempotent (the
    // Task Hub's "Advanced" escape is a one-time step, so a second call would
    // hang on `button.task-hub__advanced`), which is why re-entry must go through
    // the tab switch above instead of re-opening the video.
    await openTopTab(page, 'Library');
    await openVideo(page, 'sample');
    await openTopTab(page, 'Caption');
  }
  await expect(page.locator('.caption-stage__frame')).toBeVisible();
}

// ---------------------------------------------------------------------------
// 1. DETECTOR CONTROL — run FIRST, so a broken oracle fails before any claim.
// ---------------------------------------------------------------------------
// A silence/verdict from `elementFromPoint` is only evidence if the oracle
// actually respects `pointer-events`. `.library__thumb-img` is an ALREADY-CORRECT
// site in this same app: a full-bleed <img> over the card poster that carries
// `pointer-events: none` precisely so "the click target is the card, never the
// media element" (library-cards.css `.library__thumb-img`). If the oracle still
// named the <img> here, then its "caption-box-frame" answer below would prove
// nothing about clicks — it would just be reporting the topmost painted box.
test('detector control — elementFromPoint sees THROUGH a pointer-events:none layer', async () => {
  await expect(win.locator('.library__title')).toBeVisible();
  const img = win.locator('.library__thumb-img').first();
  await expect(img).toBeVisible();
  await img.scrollIntoViewIfNeeded();
  const r = await boxOf(win, '.library__thumb-img');
  // Centre of the poster: clear of the bottom-right duration badge (z-index 1).
  const hit = await hitTest(win, r.x + r.width / 2, r.y + r.height / 2);
  expect(
    hit.classes,
    `oracle named the pointer-events:none <img> itself (${hit.tag}.${hit.cls}) — ` +
      'it is reporting paint order, not hit-testing; do not trust its verdicts below',
  ).not.toContain('library__thumb-img');
  expect(hit.tag, `hit at the poster centre: ${hit.tag}.${hit.cls}`).not.toBe('IMG');
});

// ---------------------------------------------------------------------------
// 2. THE DEFECT (F22) — the caption frame must not eat the video's controls.
// ---------------------------------------------------------------------------
test('the caption overlay does NOT swallow the video native controls', async () => {
  await openCaptionStage(win);
  const video = win.locator('.caption-stage__frame video');
  await expect(video).toHaveCount(1);

  const hit = await probeControlBar(win, '.caption-stage__frame video');

  expect(
    hit.classes,
    `the caption overlay is intercepting the control bar: elementFromPoint → ${hit.tag}.${hit.cls}`,
  ).not.toContain('caption-box-frame');
  expect(
    hit.tag,
    `a click on the native control bar must reach the <video>, got ${hit.tag}.${hit.cls}`,
  ).toBe('VIDEO');
});

// ---------------------------------------------------------------------------
// 3. OVER-CORRECTION GUARD — passes BEFORE and AFTER the fix.
// ---------------------------------------------------------------------------
// `pointer-events` INHERITS, so `pointer-events: none` on `.caption-box-frame`
// alone would also kill the draggable box and its resize handles — trading one
// broken control for another. This case pins that the box body still hit-tests
// to itself, which is what proves the companion `.caption-box { pointer-events:
// auto }` half of the fix was not forgotten.
test('the draggable caption box still receives its own pointer events', async () => {
  await openCaptionStage(win);
  await win.locator('.caption-stage__frame .caption-box').scrollIntoViewIfNeeded();
  const r = await boxOf(win, '.caption-stage__frame .caption-box');
  const hit = await hitTest(win, r.x + r.width / 2, r.y + r.height / 2);
  // EXACT token: `.caption-box`, not `.caption-box-frame` (which is now the dead
  // hit layer). A substring check would accept the frame and pass spuriously.
  expect(
    hit.classes,
    `the caption box must stay draggable; elementFromPoint → ${hit.tag}.${hit.cls}`,
  ).toContain('caption-box');
});

// ---------------------------------------------------------------------------
// 4. THE SECOND SHIPPED SURFACE — one stylesheet, two surfaces.
// ---------------------------------------------------------------------------
// `components/CaptionDesigner.tsx` renders the SAME `<Player controls />` +
// `<CaptionBox>` sibling pair inside `.caption-designer__phone` (also
// `position: relative`, also 9:16), and is mounted in the shipped app from
// `views/MakeShorts.tsx` once a source video is picked. MakeShorts likewise has
// no play/pause/seek of its own. This case MEASURES the second surface rather
// than inferring it from the shared stylesheet.
test('the same fix reaches the MakeShorts caption designer', async () => {
  await openTopTab(win, 'Make Shorts');
  await expect(win.locator('.make-shorts')).toBeVisible();
  // The designer only mounts once a source video is selected (MakeShorts.tsx).
  await win.locator('select[aria-label="Source video"]').selectOption({ label: 'sample' });
  await expect(win.locator('.caption-designer__phone')).toBeVisible();
  const video = win.locator('.caption-designer__phone video');
  await expect(video).toHaveCount(1);

  const hit = await probeControlBar(win, '.caption-designer__phone video');
  expect(
    hit.classes,
    `the designer overlay is intercepting the control bar: elementFromPoint → ${hit.tag}.${hit.cls}`,
  ).not.toContain('caption-box-frame');
  expect(
    hit.tag,
    `a click on the designer's control bar must reach the <video>, got ${hit.tag}.${hit.cls}`,
  ).toBe('VIDEO');
});
