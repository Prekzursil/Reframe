// e2e/visual/_visualSetup.ts — shared launch + determinism helpers for the
// Wave-2b VISUAL screenshot-diff and A11Y (axe) specs.
//
// These specs drive the SAME real built Electron app + live Python sidecar as
// e2e/preview.spec.ts (no stubs), reusing fixtures.seedEnvironment() so every
// run sees an identical seeded library. The difference is what they assert:
//   * VISUAL  — pixel-stable screenshots of each surface (toHaveScreenshot),
//   * A11Y    — zero serious/critical axe violations + keyboard-nav + focus.
//
// DETERMINISM CONTRACT (why these diffs are reproducible):
//   * the BrowserWindow is created at a fixed 1280x820 (main/main.ts), and we
//     re-assert that viewport on the page before snapping,
//   * reduced-motion is emulated so CSS transitions/animations are inert,
//     and toHaveScreenshot is called with `animations: 'disabled'`,
//   * live/non-deterministic regions (the moving <video> testsrc frame, the
//     CPU/RAM ResourceBar, provider usage numbers) are MASKED, never asserted,
//   * a settle wait lets the library/readiness RPCs to the live sidecar land
//     before the first snapshot (mirrors preview.spec's 1500ms settle).
//
// CROSS-OS NOTE: visual baselines are PLATFORM-SPECIFIC (Playwright names them
// `{name}-{platform}.png`). The dedicated `e2e-visual-a11y` CI job pins ONE OS
// (ubuntu, the Playwright-container render env) and baselines are committed for
// that OS only — so the 4-OS `e2e-gui` matrix is never burdened with missing
// snapshots. The a11y/keyboard assertions are DOM-based and OS-independent.

import { _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import type { AxeResults, RunOptions } from 'axe-core';
import { findBuiltApp, seedEnvironment, type SeededEnv } from '../fixtures';

// Resolve the axe-core BROWSER bundle (axe.min.js) from this ESM module.
const require = createRequire(import.meta.url);
const AXE_SOURCE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

/** The fixed renderer viewport — matches createWindow() in app/main/main.ts. */
export const WINDOW_WIDTH = 1280;
export const WINDOW_HEIGHT = 820;

/** A launched-app handle plus the seeded env it was given. */
export interface LaunchedApp {
  app: ElectronApplication;
  seeded: SeededEnv;
}

/**
 * Launch the real built Electron app with a fresh seeded data root, exactly like
 * preview.spec.ts. Prefers the shipped package, falls back to the dev build.
 */
export async function launchSeededApp(): Promise<LaunchedApp> {
  const built = findBuiltApp();
  const seeded = seedEnvironment();
  const app = await electron.launch({
    args: [
      built.main,
      // No user gesture in an automated launch; allow play() / autoplay paths.
      '--autoplay-policy=no-user-gesture-required',
      '--no-sandbox',
    ],
    ...(built.executablePath ? { executablePath: built.executablePath } : {}),
    env: seeded.appEnv,
  });
  return { app, seeded };
}

/**
 * Prepare the first window for deterministic visual capture: wait for the shell,
 * pin the viewport, emulate reduced motion, and let the initial sidecar RPCs
 * settle. Returns the ready Page.
 */
export async function prepareWindow(app: ElectronApplication): Promise<Page> {
  const win = await app.firstWindow();
  await win.waitForLoadState('domcontentloaded');
  // The brand text is the cheapest "renderer mounted" signal (also in preview.spec).
  await win.locator('.app__brand').waitFor({ state: 'visible' });
  // Pin the viewport so layout (and thus pixels) is reproducible run-to-run.
  await win.setViewportSize({ width: WINDOW_WIDTH, height: WINDOW_HEIGHT });
  // Inert CSS motion → no in-flight transitions when we snap.
  await win.emulateMedia({ reducedMotion: 'reduce' });
  // Let library.list + readiness rollup RPCs land (same budget preview.spec uses).
  await win.waitForTimeout(1500);
  return win;
}

/**
 * The non-deterministic regions to MASK in every screenshot. These render live,
 * machine-dependent, or time-dependent content (a moving video frame, CPU/RAM
 * gauges, per-key usage numbers) that can never be byte-stable, so they are
 * painted over with a flat box rather than asserted.
 */
export function liveRegionMasks(win: Page) {
  return [
    win.locator('.workspace__player video'),
    win.locator('.resource-bar'),
    win.locator('.usage-bar'),
    win.locator('.spend-cap__readout-value'),
  ];
}

/**
 * Standard screenshot options for a stable full-page diff: disabled animations,
 * hidden caret, the live-region masks, and a small per-pixel tolerance to absorb
 * sub-pixel anti-aliasing/font-hinting drift that is visually identical.
 */
export function shotOptions(win: Page) {
  return {
    animations: 'disabled' as const,
    caret: 'hide' as const,
    mask: liveRegionMasks(win),
    // Absorb AA/hinting noise; a real layout regression moves far more than this.
    maxDiffPixelRatio: 0.01,
  };
}

/** Click a top-level tab by its visible label and wait for it to be selected. */
export async function openTopTab(win: Page, label: string): Promise<void> {
  await win.locator('.toptab', { hasText: label }).click();
  await win
    .locator('.toptab[aria-selected="true"]', { hasText: label })
    .waitFor({ state: 'visible' });
}

/** Open the Library video named `title` into its Workspace. */
export async function openVideo(win: Page, title: string): Promise<void> {
  await win.locator('.library__item-title', { hasText: title }).click();
  // WU-3a1: opening a video lands on the per-video Task Hub; take the
  // "Advanced / all tools" escape into the full Workspace.
  await win.locator('button.task-hub__advanced').click();
  await win.locator('.workspace__title').waitFor({ state: 'visible' });
}

/** Open a Settings sub-section by its visible tab label (Settings tab first). */
export async function openSettingsSection(win: Page, label: string): Promise<void> {
  await openTopTab(win, 'Settings');
  await win.locator('.tabbar [role="tab"]', { hasText: label }).click();
  await win
    .locator('.tabbar [role="tab"][aria-selected="true"]', { hasText: label })
    .waitFor({ state: 'visible' });
}

/**
 * Run axe-core against `selector` INSIDE the Electron renderer page.
 *
 * Two Electron-specific obstacles are handled here:
 *   1. @axe-core/playwright's AxeBuilder.analyze() spins up a fresh page via
 *      browserContext.newPage() (CDP Target.createTarget), which the Electron
 *      embedder rejects ("Not supported").
 *   2. The renderer ships a strict CSP (`script-src 'self'`, renderer/index.html),
 *      so page.addScriptTag's INLINE injection is blocked by the page policy.
 * The fix used here is page.evaluate, which runs the source through the CDP
 * Runtime.evaluate channel (the debugger context) — that is NOT subject to the
 * page's CSP. We eval the axe bundle to attach window.axe, then call axe.run()
 * scoped to `selector`. No new page, CSP-safe, fully Electron-compatible.
 */
export async function runAxe(
  win: Page,
  selector: string,
  tags: readonly string[],
): Promise<AxeResults> {
  return win.evaluate(
    async ([axeSource, sel, runTags]) => {
      const w = window as unknown as {
        axe?: { run: (ctx: string, o: RunOptions) => Promise<AxeResults> };
      };
      // Idempotent: only eval the bundle the first time (one app, many panels).
      if (!w.axe) {
        // CDP-context eval bypasses the page CSP that blocks inline <script>.
        // eslint-disable-next-line no-eval
        (0, eval)(axeSource);
      }
      const opts: RunOptions = { runOnly: { type: 'tag', values: runTags as string[] } };
      return w.axe!.run(sel, opts);
    },
    [AXE_SOURCE, selector, tags] as const,
  );
}
