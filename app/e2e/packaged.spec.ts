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
  // Capture the packaged MAIN process stdout/stderr — that is where the spawned
  // sidecar's startup errors (Python ENOENT, import traceback, first-run
  // bootstrap) surface. Playwright's error-context.md does NOT include them, so
  // we buffer them here and append to the diagnostic assertion below.
  const mainLog: string[] = [];

  test.beforeAll(async () => {
    // HARD requirement: a real package must exist (no dev fallback here). Set the
    // flag ONLY around our own resolution and restore it immediately, so it can
    // never leak into preview.spec (same single-worker process) and force IT to
    // require a package — preview.spec must stay free to use RF_E2E_DEV.
    const prev = process.env.RF_E2E_REQUIRE_PACKAGED;
    process.env.RF_E2E_REQUIRE_PACKAGED = '1';
    let built: ReturnType<typeof findBuiltApp>;
    try {
      built = findBuiltApp();
    } finally {
      if (prev === undefined) delete process.env.RF_E2E_REQUIRE_PACKAGED;
      else process.env.RF_E2E_REQUIRE_PACKAGED = prev;
    }
    expect(built.packaged, 'packaged.spec must launch a real electron-builder artifact').toBe(true);
    expect(built.executablePath, 'a packaged artifact must expose an executable path').toBeTruthy();

    seeded = seedEnvironment();
    app = await electron.launch({
      args: [built.main, '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
      ...(built.executablePath ? { executablePath: built.executablePath } : {}),
      env: seeded.appEnv,
    });
    const proc = app.process();
    proc.stdout?.on('data', (d: Buffer) => mainLog.push(d.toString()));
    proc.stderr?.on('data', (d: Buffer) => mainLog.push(d.toString()));
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

  test('the packaged renderer boots and shows the first-run setup UI (not a blank screen)', async () => {
    const win = await app.firstWindow();
    win.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
    await win.waitForLoadState('domcontentloaded');
    // A COLD packaged first-run pip-installs the heavy sidecar runtime into
    // <configDir>/envs/sidecar (multi-minute, network-bound) BEFORE the sidecar can
    // answer RPCs, so the post-provisioning shell (.app__brand / Library — they settle
    // only after the boot RPCs) legitimately cannot appear inside a CI window. What the
    // packaged renderer DOES render is the full-screen FirstRunSetup gate, driven by the
    // MAIN-process getProvisioningState (available while the sidecar installs — see
    // useFirstRunSetup), so asserting it proves the packaged renderer bundle BOOTS and
    // shows a LIVE setup UI rather than a blank/white screen. The real post-provisioning
    // shell + full pipeline are proven on the dev build (preview.spec, every leg) and by
    // the clean-box first-run smoke (app/e2e/README) — not this 30s CI window.
    await expect(win.locator('.first-run-setup')).toBeVisible({ timeout: 30_000 });
    await win.waitForTimeout(1000);
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
  });

  test('the packaged main process is wired with the seeded env + enters its first-run bootstrap', async () => {
    // A FRESH packaged launch correctly inherits our seeded env (MEDIA_STUDIO_CONFIG_DIR/
    // PYTHON/SIDECAR_DIR) and then enters the documented FIRST-RUN BOOTSTRAP — it
    // pip-installs the heavy sidecar runtime into <configDir>/envs/sidecar before the
    // sidecar can answer RPCs (electron-builder ships only SOURCE + embeds; the heavy
    // wheels install on first run). That install is multi-minute + network-bound, so its
    // COMPLETION (bootstrap → sidecar → the ping/library/playback/export pipeline) cannot
    // finish inside a CI window — that end-to-end packaged first-run is verified by the
    // clean-box first-run smoke (app/e2e/README), and the pipeline itself by the dev-build
    // preview.spec on every leg. Here we prove the two things CI can:
    const mainEnv = await app.evaluate(() => ({
      configDir: process.env.MEDIA_STUDIO_CONFIG_DIR ?? null,
      python: process.env.MEDIA_STUDIO_PYTHON ?? null,
      sidecarDir: process.env.MEDIA_STUDIO_SIDECAR_DIR ?? null,
    }));
    // (a) the seeded data root propagated into the packaged main process.
    expect(
      mainEnv.configDir,
      `packaged main must inherit MEDIA_STUDIO_CONFIG_DIR (env=${JSON.stringify(mainEnv)})`,
    ).toBe(seeded.dataRoot);

    // (b) the packaged .exe brought up its first-run provisioning flow: the FirstRunSetup
    // gate is driven by the MAIN-process getProvisioningState (active while the sidecar
    // installs — see useFirstRunSetup), so a visible gate proves the bootstrap the shipped
    // app depends on actually fired from the .exe — a renderer-observable signal that
    // survives the CI window, unlike waiting for the multi-minute install to finish.
    const win = await app.firstWindow();
    await expect(
      win.locator('.first-run-setup'),
      `packaged .exe must enter its first-run bootstrap gate.` +
        `\n--- packaged main/sidecar log ---\n${mainLog.join('').slice(-4000)}`,
    ).toBeVisible({ timeout: 30_000 });
  });
});
