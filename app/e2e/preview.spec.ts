// preview.spec.ts — REAL Electron GUI end-to-end for the Reframe preview.
//
// Launches the actual built app via playwright._electron.launch, opens a real
// imported sample video, and asserts the things a real user experiences:
//   - the renderer loads with NO console errors,
//   - the preview <video> gets a src, reaches readyState>=2, and currentTime
//     ADVANCES after play() (real decode + playback, not just element present),
//   - the key panels mount (Library, Workspace + its tabs incl. SemanticSearch,
//     Shorts),
//   - an export action (NLE timeline) yields a real file on disk.
//
// Every assertion here runs against the LIVE app + LIVE Python sidecar — nothing
// is stubbed. Caption-over-video is verified separately (e2e/caption.dom.test.tsx
// + the renderer's CaptionOverlay.test.tsx) because the live overlay sits behind
// ML candidate generation; see the final report for the GUI-vs-data-path label.

import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { MAIN_ENTRY, probePlayable, seedEnvironment, type SeededEnv } from './fixtures';

let seeded: SeededEnv;
let app: ElectronApplication;
const consoleErrors: string[] = [];

test.beforeAll(async () => {
  if (!existsSync(MAIN_ENTRY)) {
    throw new Error(`built main entry missing: ${MAIN_ENTRY} — run \`npm run build\` first`);
  }
  seeded = seedEnvironment();
  app = await electron.launch({
    args: [
      MAIN_ENTRY,
      // No user gesture exists in an automated launch; allow play() to start.
      '--autoplay-policy=no-user-gesture-required',
      '--no-sandbox',
    ],
    env: seeded.appEnv,
  });
});

test.afterAll(async () => {
  await app?.close();
});

test('renderer loads with no console errors', async () => {
  const win = await app.firstWindow();
  win.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
  await win.waitForLoadState('domcontentloaded');
  await expect(win.locator('.app__brand')).toHaveText('Reframe - Media Studio');
  // Let the library list + readiness rollup settle (RPCs to the live sidecar).
  await win.waitForTimeout(1500);
  expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
});

test('Library panel mounts and shows the imported sample', async () => {
  const win = await app.firstWindow();
  await expect(win.locator('.library__title')).toHaveText('Library');
  await expect(win.locator('.library__item-title').first()).toHaveText('sample');
});

test('Shorts panel mounts via top nav', async () => {
  const win = await app.firstWindow();
  await win.locator('.app__nav-btn', { hasText: 'Shorts' }).click();
  // Shorts view renders its own surface; the nav button becomes active.
  await expect(win.locator('.app__nav-btn.is-active', { hasText: 'Shorts' })).toBeVisible();
  // Return to Library for the Workspace test.
  await win.locator('.app__nav-btn', { hasText: 'Library' }).click();
  await expect(win.locator('.library__title')).toBeVisible();
});

test('preview <video> PLAYS the imported sample (real playback)', async () => {
  const win = await app.firstWindow();

  // Honest label: confirm the sidecar resolves the source as directly playable
  // (no proxy build needed) — the same verdict the app's mstream resolver uses.
  const verdict = probePlayable(seeded.python, seeded.dataRoot, seeded.videoId);
  expect(verdict.playable, 'media.playable should report the H.264 source playable').toBe(true);

  // Open the sample into the Workspace.
  await win.locator('.library__item-title', { hasText: 'sample' }).click();
  await expect(win.locator('.workspace__title')).toHaveText('sample');

  const video = win.locator('.workspace__player video');
  await expect(video).toHaveCount(1);

  // (a) the <video> got a real mstream:// src for our videoId.
  const src = await video.getAttribute('src');
  expect(src, 'video src').toContain('mstream://media/');
  expect(src).toContain(seeded.videoId);

  // (b) it loads real bytes -> readyState >= 2 (HAVE_CURRENT_DATA). Force a
  // load() so preload="metadata" does not hold playback off, and mute so the
  // autoplay policy lets play() proceed.
  const readyState = await video.evaluate(async (el: HTMLVideoElement) => {
    el.muted = true;
    el.load();
    await new Promise<void>((res) => {
      if (el.readyState >= 2) return res();
      const onReady = (): void => {
        el.removeEventListener('canplay', onReady);
        el.removeEventListener('loadeddata', onReady);
        res();
      };
      el.addEventListener('canplay', onReady);
      el.addEventListener('loadeddata', onReady);
    });
    return el.readyState;
  });
  expect(readyState, 'video.readyState').toBeGreaterThanOrEqual(2);

  // (c) currentTime ADVANCES after play() — proves real decode/playback, not a
  // static element. Poll up to ~6s for the playhead to cross a threshold.
  const advanced = await video.evaluate(async (el: HTMLVideoElement) => {
    el.muted = true;
    const t0 = el.currentTime;
    await el.play().catch(() => undefined);
    const deadline = Date.now() + 6000;
    while (Date.now() < deadline) {
      if (el.currentTime > t0 + 0.2 && !el.paused) return el.currentTime;
      await new Promise((r) => setTimeout(r, 150));
    }
    return el.currentTime;
  });
  expect(advanced, 'currentTime after play()').toBeGreaterThan(0.2);
});

test('Workspace tabs mount, including SemanticSearch', async () => {
  const win = await app.firstWindow();
  // Workspace is already open from the playback test. Verify the tab bar + a
  // representative set of panels mount without error.
  await expect(win.locator('.workspace')).toBeVisible();

  // Switch to the Search tab (SemanticSearch panel).
  await win.locator('button', { hasText: 'Search' }).first().click();
  await expect(win.locator('[role="tabpanel"]')).toBeVisible();

  // Switch to Timeline export (NleExport) to confirm a second panel mounts.
  await win.locator('button', { hasText: 'Timeline export' }).first().click();
  await expect(win.locator('[role="tabpanel"]')).toBeVisible();
});

test('export action yields a real file (NLE timeline export)', async () => {
  const win = await app.firstWindow();
  // Drive the real nle.export RPC through the live preload bridge — exactly what
  // the NleExport "Export" button calls — and verify the returned path exists.
  const result = await win.evaluate(async (videoId: string) => {
    // window.api is the frozen preload bridge (see app/main/preload.ts).
    const api = (
      window as unknown as {
        api: { rpc<T>(m: string, p?: Record<string, unknown>): Promise<T> };
      }
    ).api;
    return api.rpc<{ path: string; clipCount: number }>('nle.export', {
      videoId,
      format: 'edl',
      fps: 30,
    });
  }, seeded.videoId);

  expect(result.path, 'export path').toMatch(/\.edl$/);
  const abs = resolve(result.path);
  expect(existsSync(abs), `exported file exists: ${abs}`).toBe(true);
});
