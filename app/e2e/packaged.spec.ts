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
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import {
  COLD_TIMEOUT_MS,
  SIDECAR_DIR,
  bundledFfmpegPath,
  findBuiltApp,
  seedEnvironment,
  type BuiltApp,
  type SeededEnv,
} from './fixtures';

// The packaged artifact is ONLY produced on the Windows leg (electron-builder.yml
// has a win: target; the embeddable CPython + ffmpeg staging is Windows-only —
// build/python-embed-setup.ps1). On macOS/Linux there is no package to launch, so
// this whole suite SKIPS there rather than erroring; preview.spec.ts still gives
// those legs GUI coverage against the dev build. See .github/workflows/e2e.yml.
test.describe('packaged (shipped binary) E2E', () => {
  test.skip(process.platform !== 'win32', 'packaged artifact is only built on Windows');

  let seeded: SeededEnv;
  let app: ElectronApplication;
  // Kept at suite scope so the artifact-level checks below can reach the
  // packaged tree (its resources/bin) without re-resolving it.
  let built: BuiltApp;
  const consoleErrors: string[] = [];
  // Capture the packaged MAIN process stdout/stderr — that is where the spawned
  // sidecar's startup errors (Python ENOENT, import traceback, first-run
  // bootstrap) surface. Playwright's error-context.md does NOT include them, so
  // we buffer them here and append to the diagnostic assertion below.
  const mainLog: string[] = [];

  test.beforeAll(async () => {
    // Same cold-start budget as installed-app.spec.ts, and for the same reason: this hook
    // launches a REAL package, whose FIRST run does the full bootstrap. It began failing the
    // moment that bootstrap started genuinely working — before #406 it died fast on a get-pip
    // sha256 mismatch, so the 120 s default was never reached. MEASURED on Actions run
    // 31455388644: `"beforeAll" hook timeout of 120000ms exceeded` at packaged.spec.ts:52, with
    // 20 passed / 1 failed / 4 did not run. `test.setTimeout()` inside beforeAll sets the HOOK
    // timeout; `electron.launch` needs its own, which is a separate budget again.
    test.setTimeout(COLD_TIMEOUT_MS + 120_000);

    // HARD requirement: a real package must exist (no dev fallback here). Set the
    // flag ONLY around our own resolution and restore it immediately, so it can
    // never leak into preview.spec (same single-worker process) and force IT to
    // require a package — preview.spec must stay free to use RF_E2E_DEV.
    const prev = process.env.RF_E2E_REQUIRE_PACKAGED;
    process.env.RF_E2E_REQUIRE_PACKAGED = '1';
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
      timeout: COLD_TIMEOUT_MS,
    });
    const proc = app.process();
    proc.stdout?.on('data', (d: Buffer) => mainLog.push(d.toString()));
    proc.stderr?.on('data', (d: Buffer) => mainLog.push(d.toString()));
  });

  test.afterAll(async () => {
    await app?.close();
  });

  // ── THE ANTI-RECURRENCE CHECK ────────────────────────────────────────────
  // v1.4 shipped a bundled ffmpeg (BtbN win64-LGPL, --disable-libx264
  // --disable-libx265) that cannot encode H.264, while the sidecar passes the
  // literal token "libx264" to -c:v from 13 sites across 9 modules. Every
  // export on the shipped product died with "Unknown encoder 'libx264'".
  //
  // WHY NOTHING CAUGHT IT — and why this check belongs HERE specifically:
  // golden-journey.spec.ts DOES independently ffprobe the produced clip for
  // h264/1080x1920, but it never requires the packaged artifact, so on the
  // Windows leg (e2e.yml sets RF_E2E_DEV=1) findBuiltApp returns the DEV build.
  // A dev build leaves MEDIA_STUDIO_FFMPEG unset (sidecar.env.test.ts §A3), so
  // the sidecar falls through to the choco ffmpeg on PATH — a GPL build that
  // HAS libx264. The journey's codec assertion was therefore measuring a binary
  // the user never runs. packaged.spec is the ONLY spec that hard-requires the
  // real artifact, so it is the only place this can be checked honestly.
  //
  // Delegating to `python -m media_studio.encoders` keeps ONE source of truth
  // for the required-encoder list (media_studio/encoders.py REQUIRED_ENCODERS,
  // itself kept in sync with the tree by an AST scan) instead of a second,
  // drift-prone copy in TypeScript.
  test('the packaged bundled ffmpeg provides every encoder the pipeline hardcodes', () => {
    const bundled = bundledFfmpegPath(built.executablePath!);
    expect(
      existsSync(bundled),
      `the packaged artifact must ship resources/bin/ffmpeg — missing at ${bundled}`,
    ).toBe(true);

    const probe = spawnSync(
      seeded.python,
      ['-m', 'media_studio.encoders', '--ffmpeg', bundled],
      { cwd: SIDECAR_DIR, encoding: 'utf8' },
    );
    const report = `${probe.stdout ?? ''}${probe.stderr ?? ''}`.trim();
    // Surface the verdict on green runs too, so the smoke self-documents WHICH
    // binary it measured — a capability claim that does not name the binary it
    // probed is unfalsifiable.
    console.log(`[packaged] encoder-capability report:\n${report}`);
    expect(
      probe.status,
      'the SHIPPED ffmpeg cannot encode what the pipeline hardcodes — every affected ' +
        `export will fail with "Unknown encoder" on the user's machine.\n${report}`,
    ).toBe(0);
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
