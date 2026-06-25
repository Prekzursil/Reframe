// library.visual.spec.ts — VISUAL screenshot-diff spike for the Library tab.
//
// The FIRST visual surface (the spike): proves toHaveScreenshot() produces a
// pixel-stable diff against a real `_electron.launch` window with the seeded
// library. See _visualSetup.ts for the determinism contract (fixed viewport,
// reduced-motion, masked live regions, settle wait).

import { test, expect } from '@playwright/test';
import {
  launchSeededApp,
  prepareWindow,
  shotOptions,
  type LaunchedApp,
} from './_visualSetup';

let launched: LaunchedApp;

test.beforeAll(async () => {
  launched = await launchSeededApp();
});

test.afterAll(async () => {
  await launched?.app.close();
});

test('Library tab — full-page visual baseline', async () => {
  const win = await prepareWindow(launched.app);
  // Land on the Library home (the default route) and confirm it mounted.
  await expect(win.locator('.library__title')).toHaveText('Library');
  await expect(win.locator('.library__item-title').first()).toHaveText('sample');
  await expect(win).toHaveScreenshot('library.png', shotOptions(win));
});
