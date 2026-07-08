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
import { findBuiltApp, probePlayable, seedEnvironment, type SeededEnv } from './fixtures';

let seeded: SeededEnv;
let app: ElectronApplication;
let underTestIsPackaged = false;
const consoleErrors: string[] = [];

test.beforeAll(async () => {
  // Prefer the SHIPPED package (real .exe on Windows); fall back to the dev
  // build so this spec still gives local GUI coverage (see fixtures.findBuiltApp).
  const built = findBuiltApp();
  underTestIsPackaged = built.packaged;
  seeded = seedEnvironment();
  app = await electron.launch({
    args: [
      built.main,
      // No user gesture exists in an automated launch; allow play() to start.
      '--autoplay-policy=no-user-gesture-required',
      '--no-sandbox',
    ],
    ...(built.executablePath ? { executablePath: built.executablePath } : {}),
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
  await expect(win.locator('.app__brand')).toHaveText('Reframe');
  // Let the library list + readiness rollup settle (RPCs to the live sidecar).
  await win.waitForTimeout(1500);
  expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
});

test('app.isPackaged reflects whether we drove the shipped package', async () => {
  // electronApp.evaluate runs in the MAIN process, so app.isPackaged is the real
  // Electron verdict — true ONLY when we launched the electron-builder artifact
  // (the shipped binary), false for the dev out/main build. Asserting they agree
  // proves "the shipped binary works" when CI runs the packaged leg, and keeps
  // the dev-build path honest locally.
  const isPackaged = await app.evaluate(({ app: electronApp }) => electronApp.isPackaged);
  expect(isPackaged).toBe(underTestIsPackaged);
});

test('Library panel mounts and shows the imported sample', async () => {
  const win = await app.firstWindow();
  await expect(win.locator('.library__title')).toHaveText('Library');
  await expect(win.locator('.library__item-title').first()).toHaveText('sample');
});

test('Make Shorts panel mounts via the top-level tabs', async () => {
  const win = await app.firstWindow();
  // v1.4 renamed the shorts-making top tab "Create" -> "Make Shorts" (App.tsx
  // makeshorts nav label). Drive the current label so this stops timing out.
  await win.locator('.toptab', { hasText: 'Make Shorts' }).click();
  // The Make Shorts tab becomes the selected top-level tab.
  await expect(
    win.locator('.toptab[aria-selected="true"]', { hasText: 'Make Shorts' }),
  ).toBeVisible();
  // Return to Library for the Workspace test.
  await win.locator('.toptab', { hasText: 'Library' }).click();
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
  // Workspace is already open from the playback test.
  await expect(win.locator('.workspace')).toBeVisible();

  // Switch to the Search tab and assert the SemanticSearch panel ITSELF mounted
  // (panel-specific selectors, not the always-present tabpanel container): its
  // section, heading, and the search input the user types into.
  await win.locator('button', { hasText: 'Search' }).first().click();
  await expect(win.locator('section.semantic-search-panel')).toBeVisible();
  await expect(win.locator('section.semantic-search-panel h2')).toHaveText('Search the transcript');
  await expect(win.locator('input[aria-label="Search the transcript"]')).toBeVisible();

  // Switch to Timeline export and assert the NleExport panel ITSELF mounted.
  await win.locator('button', { hasText: 'Timeline export' }).first().click();
  await expect(win.locator('section.nle-panel')).toBeVisible();
  await expect(
    win.locator('section.nle-panel button', { hasText: 'Export timeline' }),
  ).toBeVisible();
});

test('export action yields a real file (NLE timeline export, real button)', async () => {
  const win = await app.firstWindow();
  // Drive the REAL "Export timeline" button in the mounted NleExport panel (it
  // calls nle.export through the live preload bridge -> live sidecar). Then read
  // the saved path the panel renders and assert the file exists on disk.
  await win.locator('button', { hasText: 'Timeline export' }).first().click();
  await expect(win.locator('section.nle-panel')).toBeVisible();
  await win.locator('section.nle-panel button', { hasText: 'Export timeline' }).click();

  // The panel renders "Saved … to <code>{path}</code>" on success.
  const code = win.locator('.export-path code');
  await expect(code).toBeVisible();
  const savedPath = (await code.textContent())?.trim() ?? '';
  expect(savedPath, 'exported path text').not.toBe('');
  const abs = resolve(savedPath);
  expect(existsSync(abs), `exported file exists: ${abs}`).toBe(true);
});

test('no console errors across the whole session', async () => {
  // The console/pageerror listener (bound in test 1) collected for the entire
  // run, including the Workspace open, panel switches, playback, and export. A
  // single early assertion would miss interaction-time errors, so re-assert here
  // after all UI flows have exercised.
  expect(consoleErrors, `console errors across session: ${JSON.stringify(consoleErrors)}`).toEqual(
    [],
  );
});
