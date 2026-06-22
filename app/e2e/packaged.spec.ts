// packaged.spec.ts — "the SHIPPED binary works" E2E (WU-A part 2).
//
// Unlike preview.spec.ts (which falls back to the dev build for local coverage),
// this spec is HARD-GATED to a real electron-builder package: it sets
// RF_E2E_REQUIRE_PACKAGED so the absence of a packaged artifact is a failure, not
// a silent dev-build fallback. It launches that package via
// electron-playwright-helpers (findLatestBuild + parseElectronApp -> the real
// executable, e.g. the Windows .exe) and asserts the things that ONLY hold for a
// genuine production package:
//   - app.isPackaged === true            (read in the MAIN process via evaluate)
//   - app.getAppPath() points INSIDE the packaged resources (the asar)
//   - the renderer boots from the packaged bundle with NO console errors and
//     shows the live UI driven by the bundled Python sidecar.
//
// CI runs this on the leg that actually produced a package (windows-latest builds
// the real .exe; see .github/workflows/e2e.yml). On legs without a package the
// suite fails fast with a clear message rather than pretending to test the dev
// build.

import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { findBuiltApp, seedEnvironment, type SeededEnv } from './fixtures';

// The packaged artifact is ONLY produced on the Windows leg (electron-builder.yml
// has a win: target; the embeddable CPython + ffmpeg staging is Windows-only —
// build/python-embed-setup.ps1). On macOS/Linux there is no package to launch, so
// this whole suite SKIPS there rather than erroring; preview.spec.ts still gives
// those legs GUI coverage against the dev build. See .github/workflows/e2e.yml.
test.describe('packaged (shipped binary) E2E', () => {
  test.skip(process.platform !== 'win32', 'packaged artifact is only built on Windows');

  let seeded: SeededEnv;
  let app: ElectronApplication;
  const consoleErrors: string[] = [];

  test.beforeAll(async () => {
    // HARD requirement: a real package must exist (no dev fallback here).
    process.env.RF_E2E_REQUIRE_PACKAGED = '1';
    const built = findBuiltApp();
    expect(built.packaged, 'packaged.spec must launch a real electron-builder artifact').toBe(true);
    expect(built.executablePath, 'a packaged artifact must expose an executable path').toBeTruthy();

    seeded = seedEnvironment();
    app = await electron.launch({
      args: [built.main, '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
      ...(built.executablePath ? { executablePath: built.executablePath } : {}),
      env: seeded.appEnv,
    });
  });

  test.afterAll(async () => {
    await app?.close();
  });

  test('the shipped package reports app.isPackaged === true', async () => {
    const isPackaged = await app.evaluate(({ app: electronApp }) => electronApp.isPackaged);
    expect(isPackaged, 'a genuine electron-builder package must be isPackaged').toBe(true);
  });

  test('the shipped package runs from the packaged app path (asar)', async () => {
    const appPath = await app.evaluate(({ app: electronApp }) => electronApp.getAppPath());
    // A packaged Electron app runs out of resources/app.asar (or the resources
    // dir), never from a loose dev `out/` tree.
    expect(appPath.replace(/\\/g, '/').toLowerCase()).toContain('resources');
  });

  test('the packaged renderer boots with no console errors and shows the live UI', async () => {
    const win = await app.firstWindow();
    win.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
    await win.waitForLoadState('domcontentloaded');
    // The brand renders from the PACKAGED renderer bundle, driven by the bundled
    // Python sidecar (library + readiness rollup settle after the boot RPCs).
    await expect(win.locator('.app__brand')).toHaveText('Reframe - Media Studio');
    await expect(win.locator('.library__title')).toHaveText('Library');
    await win.waitForTimeout(1500);
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
  });
});
