// installed-app.spec.ts — the INSTALLED build, driven end to end (W-A + W41).
//
// ── THE TWO HOLES THIS ADDRESSES ─────────────────────────────────────────────
//
// W-A · THE INSTALLED BUILD IS NEVER DRIVEN. `packaged.spec.ts` is the only spec
// that hard-requires a real package, and it resolves it from `dist/win-unpacked`
// — the electron-builder OUTPUT tree. `findBuiltApp()` had no override, so an app
// laid down by the NSIS installer could not be reached at all. `RF_E2E_APP_EXE`
// (fixtures.ts) is that override and this spec is its consumer.
//   Risk already NARROWED, and deliberately not overstated: `bundledFfmpegPath()`
//   is purely relative to the executable, and an installed tree has been verified
//   by hand to contain that exact path — so NSIS is believed to lay resources out
//   identically to `win-unpacked` (likely, 80%: one hand inspection, no automated
//   check). The encoder test below is what converts that belief into a
//   measurement, because it probes `<install dir>/resources/bin/ffmpeg.exe`
//   rather than the one in `dist/`.
//
// W41 · THE COLD PACKAGED DATA PIPELINE IS UNTESTED BY DESIGN. A cold packaged
// launch `pip install`s the heavy sidecar runtime into `<configDir>/envs/sidecar`
// before the sidecar can answer any RPC (electron-builder ships only the sidecar
// SOURCE plus the embeds), which is multi-minute and network-bound. So even the
// Windows packaged leg runs the pipeline with `RF_E2E_DEV=1`, and `packaged.spec`
// stops at "the bootstrap FIRED" rather than "the bootstrap COMPLETED and the
// pipeline works". A first-run bootstrap failure on a real machine is the class no
// leg observes. This spec waits for that bootstrap to FINISH (default 15 min,
// `RF_E2E_COLD_TIMEOUT_MS`) and then drives the pipeline through the app's OWN
// bundled runtime.
//
// ── HOW IT ISOLATES THE PACKAGED RUNTIME ─────────────────────────────────────
// `seedEnvironment()` returns an `appEnv` carrying MEDIA_STUDIO_PYTHON and
// MEDIA_STUDIO_SIDECAR_DIR pointed at the REPO (host interpreter + `sidecar/`),
// which is right for the dev build and WRONG here: it would make the installed app
// run the repo's sidecar under the host python, so a green would say nothing about
// the packaged runtime. Both keys are therefore DELETED from the env handed to the
// launch. `definedEnv` (fixtures.ts) copies the ENTIRE ambient `process.env` and
// then layers the three seeded keys on top, so deleting has to cover a developer
// who exported them too — and this box really does carry an ambient
// MEDIA_STUDIO_PYTHON, so that is not a hypothetical.
//   REFUTED AND WIDENED (2026-08-11). This block used to delete exactly two keys
//   and then claim "Only MEDIA_STUDIO_CONFIG_DIR travels". The claim was right
//   about what SHOULD happen and the code did not do it, and the gap was not
//   cosmetic: `buildSidecarEnv` (app/main/sidecar.ts:168-197) starts from
//   `{ ...process.env }` and assigns every packaged default as
//   `env.X = env.X ?? <resources path>` — its own header says "Pre-set env vars
//   always win (never clobber a user override)". So an ambient MEDIA_STUDIO_FFMPEG
//   / _FFPROBE / _NODE_EXE / _RENDER_JS / _REMOTION_BUNDLE ALSO wins over the
//   shipped resource, which would have let this spec assert that the INSTALLED
//   tree carries `resources/bin/ffmpeg` (it does, below) while the app under test
//   ran the host one — a self-inconsistent green.
//   Rather than narrow the sentence to match two deletions, the deletion is now
//   the whole ambient `MEDIA_STUDIO_*` set except CONFIG_DIR (the one key that
//   MUST travel: it is the seeded data root). Non-`MEDIA_STUDIO_` variables are
//   deliberately left alone — PATH is needed to launch at all, and
//   PIP_EXTRA_INDEX_URL is a real bootstrap input.
//   Still UNVERIFIED and inline: no run has confirmed the app then resolves the
//   packaged ffmpeg, because the sidecar's chosen binary is not read back here.
//   Settling experiment: assert `media.capabilities`/the sidecar's reported ffmpeg
//   path equals `bundledFfmpegPath(built.executablePath)` once this leg is green
//   once — deliberately not asserted now, from a leg that has never run.
//   The SEEDING itself still runs under the host python against `sidecar/` — the
//   same thing every other spec does — because it only has to write a library row
//   the app then reads. UNVERIFIED and inline: if the installed build is OLDER than
//   this checkout, its bundled sidecar could read that data root differently; this
//   spec asserts nothing about version parity. Settling experiment: install the
//   artifact built from THIS commit, which is what the CI step does.
//
// WHY PRE-SEEDING DOES NOT SHORT-CIRCUIT THE COLD RUN — the obvious way this spec
// could be vacuous is if handing the app a data root that already has `library.db`
// made it decide no first run was needed, so it would sail past a bootstrap that
// never happened. It does not: `classifyFirstRun` (app/main/firstRunGate.ts:225)
// keys ONLY on `isPackaged` plus the presence of the `.first-run-complete.json`
// marker AT THE DATA ROOT (`FIRST_RUN_COMPLETE_MARKER`, firstRunGate.ts:21), which
// `bootstrap.py` writes and `seedEnvironment` does not — so a fresh `mkdtemp` root
// with a library in it still classifies as `first-ever`. That is a code-reading of
// a pure, unit-tested decision function (firstRunGate.test.ts), not a measurement
// of this spec; the measurement is the bootstrap actually being observed to run,
// which is what the COLD FIRST RUN test below asserts.
//
// ── SCOPE ────────────────────────────────────────────────────────────────────
// `e2e.yml` is `workflow_dispatch` + nightly `cron` only and this spec is gated on
// an env var that only its own dedicated step sets, so it gates NOTHING — it
// proves a capability on demand and cannot prevent a regression from merging. It
// self-skips (loudly) whenever `RF_E2E_APP_EXE` is unset, which is why it can sit
// in the same `testMatch` as the proven `golden-journey` without touching it: a
// skipped spec cannot go red, and a red step suppresses every later step in the
// job (measured on run 30612141716).
//
// ── HONESTY: WHAT HAS AND HAS NOT BEEN OBSERVED ──────────────────────────────
// The DETERMINISTIC half of the escape hatch — that `RF_E2E_APP_EXE` resolves an
// installed tree, beats RF_E2E_DEV, and fails loud on a bad path — is measured by
// `findBuiltApp.test.ts` (7/7, every OS leg). The LAUNCH half in THIS file is
// UNVERIFIED by its author: producing an installed app needs the full staging
// pipeline (`build/python-embed-setup.ps1`, the render-cli remotion bundle,
// electron-builder, then a silent NSIS install), which was not run here. If these
// tests have never been seen green, no verdict in this file may be cited. The
// settling experiment is the `drive_installed_build` dispatch input in e2e.yml,
// which builds, installs silently, runs exactly this spec, and uninstalls.

import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  APP_EXE_ENV,
  COLD_TIMEOUT_MS,
  DIST_DIR,
  REPO_ROOT,
  SIDECAR_DIR,
  bundledFfmpegPath,
  findBuiltApp,
  probePlayable,
  seedEnvironment,
  type BuiltApp,
  type SeededEnv,
} from './fixtures';

/** The installed app to drive; empty means "skip this whole suite". */
const INSTALLED = process.env[APP_EXE_ENV]?.trim() ?? '';

// COLD_TIMEOUT_MS moved to fixtures.ts (2026-08-11) so packaged.spec.ts shares one value: it
// launches a real package too and was silently using Playwright's defaults. Still env-tunable
// via RF_E2E_COLD_TIMEOUT_MS. The window remains UNVERIFIED on a CI runner — the settling
// experiment is a dispatch that gets all the way through a cold first run.

const SKIP_REASON =
  `${APP_EXE_ENV} is not set, so there is no installed app to drive. Set it to the ` +
  'INSTALLED executable (Windows: "<install dir>\\Reframe.exe"; macOS: the ' +
  '"<Product>.app" bundle) — NOT dist/win-unpacked, which packaged.spec.ts already ' +
  'covers. Producing one: build/python-embed-setup.ps1 -WithFfmpeg, then the app + ' +
  'render-cli builds, then electron-builder --win, then run the NSIS installer with ' +
  '/S /D=<dir>.';

if (INSTALLED === '') {
  // Print as well as skip: a `-` in the list reporter is easy to miss, and a
  // silently-skipped installed-build leg reads exactly like a passing one.
  console.log(`[installed-app] SKIPPED — ${SKIP_REASON}`);
}

let built: BuiltApp;
let seeded: SeededEnv;
let app: ElectronApplication;
const consoleErrors: string[] = [];
const pageErrors: string[] = [];
/** Packaged main-process stdout/stderr — where the bootstrap narrates itself. */
const mainLog: string[] = [];

/** The last few KB of the packaged main log, for a diagnosable failure message. */
function mainTail(): string {
  return `\n--- installed main/sidecar log (tail) ---\n${mainLog.join('').slice(-6000)}`;
}

/**
 * Drive the first-run gate the way a USER would, until the app hands off to the
 * normal shell — or fail LOUD with the gate's own words.
 *
 * Three interactive states are possible and each is handled by clicking the same
 * control a user would click, never by poking state:
 *   * the install-profile PICKER (`profile-picker`) — confirms whatever profile is
 *     preselected. On a real install it should not appear at all: `installer.nsh`
 *     writes `$INSTDIR/.first-run-profile.json` and `main/installerSeed.ts` adopts
 *     it, so provisioning runs UNATTENDED (electron-builder.yml says so in the
 *     `nsis.include` comment). Handled anyway because "should not appear" is a
 *     code-reading, and a hang here would be indistinguishable from a slow install.
 *   * the AI-routing CHOOSER (`first-run-chooser`) — picks `privacy` (Local only),
 *     the recommended default. `useFirstRunSetup` only shows it when the picker was
 *     seen this session, so it is transitively unlikely for the same reason.
 *   * a bootstrap ERROR (`first-run-setup__error`) — the failure class W41 exists
 *     to surface. Throws immediately with the rendered message; waiting out the
 *     full timeout would bury the one thing worth reporting.
 */
async function driveFirstRunToShell(win: Page, deadlineMs: number): Promise<void> {
  const deadline = Date.now() + deadlineMs;
  const brand = win.locator('.app__brand');
  const errorBody = win.locator('.first-run-setup__error-message');
  const confirmProfile = win.locator('.profile-picker button[data-action="confirm-profile"]');
  const chooseLocal = win.locator('.first-run-chooser button[data-choice="privacy"]');

  while (Date.now() < deadline) {
    if ((await brand.count()) > 0) return;
    if ((await errorBody.count()) > 0) {
      const message = (await errorBody.first().textContent())?.trim() ?? '(empty)';
      throw new Error(
        `the installed app's FIRST-RUN BOOTSTRAP FAILED — this is the W41 failure ` +
          `class, reported rather than timed out. Gate message: ${message}${mainTail()}`,
      );
    }
    if ((await confirmProfile.count()) > 0 && (await confirmProfile.first().isEnabled())) {
      await confirmProfile.first().click();
    } else if ((await chooseLocal.count()) > 0 && (await chooseLocal.first().isEnabled())) {
      await chooseLocal.first().click();
    }
    await win.waitForTimeout(2_000);
  }
  const phase = (await win.locator('.first-run-setup__phase').count())
    ? await win.locator('.first-run-setup__phase').first().textContent()
    : '(no first-run gate on screen)';
  const detail = (await win.locator('.first-run-setup__detail').count())
    ? await win.locator('.first-run-setup__detail').first().textContent()
    : '';
  throw new Error(
    `the installed app never reached the post-provisioning shell within ` +
      `${deadlineMs} ms (RF_E2E_COLD_TIMEOUT_MS). Last gate phase: ${phase?.trim()} ` +
      `${detail?.trim() ?? ''}${mainTail()}`,
  );
}

test.describe('INSTALLED build — first run to working pipeline (W-A + W41)', () => {
  test.skip(INSTALLED === '', SKIP_REASON);

  test.beforeAll(async () => {
    // THE HOOK'S OWN TIMEOUT, not the test's. Without this the suite could never go green on a
    // COLD install: this file defines COLD_TIMEOUT_MS (default 900 s, and e2e.yml passes
    // RF_E2E_COLD_TIMEOUT_MS=1200000) for exactly this wait, but Playwright bounds a beforeAll
    // hook at its own 120 s default and that fires FIRST. `test.setTimeout()` inside beforeAll
    // sets the HOOK timeout.
    //
    // MEASURED, not guessed: Actions run 31451957732 step 28, on `main`, with the installed
    // build. The hook aborted at 02:33:32 -> 02:35:33 with `"beforeAll" hook timeout of
    // 120000ms exceeded`, and all FOUR real tests below reported `-` (skipped). That is why the
    // installed-build arm had never been observed green — the launch never got to run.
    //
    // The slack is for the launch + firstWindow() round trip on top of the bootstrap wait; the
    // cold budget itself stays env-tunable so a slow runner is a config change, not an edit.
    test.setTimeout(COLD_TIMEOUT_MS + 120_000);

    built = findBuiltApp();
    // findBuiltApp fails loud on a bad path, so reaching here means the tree
    // parsed. Re-assert the two properties the rest of the suite depends on.
    expect(built.packaged, 'an installed app must resolve as a packaged artifact').toBe(true);
    expect(built.executablePath, 'an installed app must expose an executable path').toBeTruthy();

    seeded = seedEnvironment();
    // ISOLATE THE PACKAGED RUNTIME — see the header. Without this the installed
    // .exe would run the repo's sidecar under the host interpreter, and any
    // ambient MEDIA_STUDIO_* override would beat the shipped resource because
    // buildSidecarEnv resolves each packaged default as `env.X ?? <resources>`.
    const appEnv = { ...seeded.appEnv };
    for (const key of Object.keys(appEnv)) {
      if (key.startsWith('MEDIA_STUDIO_') && key !== 'MEDIA_STUDIO_CONFIG_DIR') delete appEnv[key];
    }
    // Postcondition, asserted rather than assumed: the loop above is the only
    // thing standing between this spec and a green that measured the dev runtime,
    // so a typo'd prefix must fail HERE and not silently downgrade the isolation.
    expect(
      Object.keys(appEnv).filter((k) => k.startsWith('MEDIA_STUDIO_')),
      'exactly one MEDIA_STUDIO_* key may reach the installed app: the seeded data root',
    ).toEqual(['MEDIA_STUDIO_CONFIG_DIR']);

    // THE THIRD TIMEOUT ON THIS PATH, and each one only became visible after the previous was
    // removed. `electron.launch` has its OWN budget, separate from the test timeout and from the
    // beforeAll hook timeout above; at its default it aborted with `electron.launch: Timeout
    // 180000ms exceeded` while the app was still bootstrapping. MEASURED on Actions run
    // 31455388644: the captured stderr shows `[bootstrap] adopted the installer's default
    // profile` and the asset manifest registering assets — i.e. the run was PROGRESSING, and
    // there was no sha256 mismatch, so #406 held. A cold first run genuinely exceeds 3 minutes
    // because it builds the env and installs packages.
    app = await electron.launch({
      args: [built.main, '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
      ...(built.executablePath ? { executablePath: built.executablePath } : {}),
      env: appEnv,
      timeout: COLD_TIMEOUT_MS,
    });
    const proc = app.process();
    proc.stdout?.on('data', (d: Buffer) => mainLog.push(d.toString()));
    proc.stderr?.on('data', (d: Buffer) => mainLog.push(d.toString()));

    const win = await app.firstWindow();
    win.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    win.on('pageerror', (e) => pageErrors.push(e.message));
  });

  test.afterAll(async () => {
    await app?.close();
  });

  test('the running process is a PACKAGED binary from OUTSIDE the repo (not dist/, not dev)', async () => {
    // ── SCOPE CORRECTION (refuted 2026-08-11) ────────────────────────────────
    // This test was titled "the running process IS the installed executable" and
    // its comment called `process.execPath` "the strongest available statement
    // about WHICH binary is running". Both were wider than the evidence, and the
    // REFUTATION is exact: for a `.exe`, `resolveInstalledApp` returns the caller's
    // path verbatim (fixtures.ts) and Playwright launches precisely that via
    // `executablePath`, so `resolve(execPath) === resolve(built.executablePath)`
    // reduces to `resolve($RF_E2E_APP_EXE) === resolve($RF_E2E_APP_EXE)`. It can
    // only fail if Electron re-execs, and beforeAll has already asserted the value
    // is truthy. The two supporting assertions are equally insensitive: the old
    // comment itself conceded `dist/win-unpacked` satisfies `isPackaged`, and its
    // `getAppPath()` also contains `resources`. So pointing the variable at
    // `dist/win-unpacked/Reframe.exe` — the exact misuse SKIP_REASON warns against
    // — passed this test in full, in the test named for excluding it.
    //
    // WHAT EACH LINE NOW CLAIMS, scoped to what it can observe:
    //   (a) Playwright honoured `executablePath` (a tautology unless Electron
    //       re-execs; kept because a re-exec IS worth catching, not as proof of
    //       WHICH tree),
    //   (b) the tree resolved as a packaged artifact,
    //   (c) — the one that actually discriminates — the running binary is OUTSIDE
    //       the repo, so it is neither `dist/` nor `out/main/main.js`.
    const execPath = await app.evaluate(() => process.execPath);
    expect(resolve(execPath)).toBe(resolve(built.executablePath!));

    const isPackaged = await app.evaluate(({ app: electronApp }) => electronApp.isPackaged);
    expect(isPackaged, 'an installed app must report isPackaged').toBe(true);

    const appPath = await app.evaluate(({ app: electronApp }) => electronApp.getAppPath());
    expect(appPath.replace(/\\/g, '/').toLowerCase()).toContain('resources');

    // (c) THE DISTINGUISHING CHECK. `DIST_DIR` and `REPO_ROOT` are the two trees
    // this spec exists NOT to be driving; an app installed by NSIS lives outside
    // both (the CI step installs into RUNNER_TEMP). Compared on `resolve()`d,
    // separator-normalised, case-folded prefixes — case-folding is correct here
    // because the question is "is this the same Windows path", and the ONE OS this
    // leg runs on is case-insensitive; a Linux/macOS caller is unaffected because
    // an install there simply is not under the repo either way.
    const norm = (p: string): string => resolve(p).replace(/\\/g, '/').toLowerCase();
    for (const [label, root] of [
      ['the electron-builder output tree (packaged.spec.ts already covers it)', DIST_DIR],
      ['the repo checkout (that would be the dev build)', REPO_ROOT],
    ] as const) {
      expect(
        norm(execPath).startsWith(`${norm(root)}/`),
        `${APP_EXE_ENV} must name an INSTALLED app, but the running binary is inside ` +
          `${label}: ${execPath}`,
      ).toBe(false);
    }
  });

  test('the INSTALLED tree ships an ffmpeg with every encoder the pipeline hardcodes', () => {
    // This is the NSIS-LAYOUT PARITY measurement. `packaged.spec.ts` runs the same
    // probe against `dist/win-unpacked`; running it against the INSTALL directory
    // is what turns "NSIS lays resources out identically" from a hand inspection
    // into a check. `bundledFfmpegPath` is purely relative to the executable, so if
    // the installer moved `resources/bin` this fails on the existsSync below.
    //
    // Delegating to `python -m media_studio.encoders` keeps ONE source of truth for
    // the required-encoder list (media_studio/encoders.py REQUIRED_ENCODERS). The
    // interpreter is the HOST one on purpose: the question is what the shipped
    // FFMPEG BINARY can do, and any python that can import the module may ask it.
    const bundled = bundledFfmpegPath(built.executablePath!);
    expect(
      existsSync(bundled),
      `the INSTALLED tree must carry resources/bin/ffmpeg — missing at ${bundled}. ` +
        'If dist/win-unpacked has it and this does not, NSIS is NOT laying resources ' +
        'out identically and every packaged-ffmpeg claim needs re-scoping.',
    ).toBe(true);

    const probe = spawnSync(seeded.python, ['-m', 'media_studio.encoders', '--ffmpeg', bundled], {
      cwd: SIDECAR_DIR,
      encoding: 'utf8',
    });
    const report = `${probe.stdout ?? ''}${probe.stderr ?? ''}`.trim();
    // Print on green too: a capability claim that does not name the binary it
    // probed is unfalsifiable.
    console.log(`[installed-app] encoder-capability report for ${bundled}:\n${report}`);
    expect(
      probe.status,
      `the INSTALLED ffmpeg cannot encode what the pipeline hardcodes — every affected ` +
        `export will fail with "Unknown encoder" on the user's machine.\n${report}`,
    ).toBe(0);
  });

  test('COLD FIRST RUN completes and the installed app lists the seeded video (W41)', async () => {
    // The bootstrap is minutes long by design, so this one test owns a much larger
    // budget than playwright.config.ts's 120 s. Not a loosened assertion: the
    // assertions are unchanged, only the patience is.
    test.setTimeout(COLD_TIMEOUT_MS + 180_000);
    const win = await app.firstWindow();
    await win.waitForLoadState('domcontentloaded');

    // (a) the gate runs to completion — bootstrap DONE, not merely FIRED. This is
    // the whole of W41: `packaged.spec` proves the gate appears, nothing until now
    // proved it ever finishes.
    await driveFirstRunToShell(win, COLD_TIMEOUT_MS);
    await expect(win.locator('.app__brand')).toHaveText('Reframe');

    // (b) the pipeline answers: the seeded row came back from `library.list`
    // through the app's OWN bundled sidecar, running under its OWN interpreter.
    await expect(
      win.locator('.library__item-title'),
      `the installed app's own sidecar must answer library.list after provisioning${mainTail()}`,
    ).toHaveCount(1, { timeout: 120_000 });
    await expect(win.locator('.library__item-title').first()).toHaveText('sample');
  });

  test('the installed app PLAYS the seeded video (real decode through the packaged runtime)', async () => {
    const win = await app.firstWindow();

    // Honest label, same as preview.spec: confirm the sidecar resolves the source
    // as directly playable. Read out of band through the host interpreter — a
    // second, independent statement about the same data root.
    const verdict = probePlayable(seeded.python, seeded.dataRoot, seeded.videoId);
    expect(verdict.playable, 'media.playable should report the H.264 source playable').toBe(true);

    // Opening a video lands directly on the Workspace (owner-locked G-7 invariant
    // 2); the Task Hub "Advanced / all tools" escape this used to click is gone.
    await win.locator('.library__item-title', { hasText: 'sample' }).click();
    await expect(win.locator('.workspace__title')).toHaveText('sample');

    const video = win.locator('.workspace__player video');
    await expect(video).toHaveCount(1);
    const src = await video.getAttribute('src');
    expect(src, 'video src').toContain('mstream://media/');
    expect(src).toContain(seeded.videoId);

    // currentTime ADVANCES after play() — real decode in the INSTALLED renderer,
    // streaming real bytes through the installed main process's mstream handler.
    const advanced = await video.evaluate(async (el: HTMLVideoElement) => {
      el.muted = true;
      el.load();
      const t0 = el.currentTime;
      await el.play().catch(() => undefined);
      const deadline = Date.now() + 10_000;
      while (Date.now() < deadline) {
        if (el.currentTime > t0 + 0.2 && !el.paused) return el.currentTime;
        await new Promise((r) => setTimeout(r, 150));
      }
      return el.currentTime;
    });
    expect(advanced, 'currentTime after play()').toBeGreaterThan(0.2);
  });

  test('no uncaught renderer exceptions across the installed session', () => {
    // ASSERTED: uncaught exceptions (`pageerror`). Those are unambiguous defects
    // whatever the environment.
    expect(pageErrors, `page errors: ${JSON.stringify(pageErrors)}`).toEqual([]);
    // REPORTED, NOT ASSERTED: console errors. preview.spec pins these to `[]`, but
    // it starts from an already-provisioned data root. A cold first run crosses the
    // gate->shell handoff while the sidecar has only just come up, and this arm has
    // NEVER been observed green, so pinning `[]` here would be an assertion made
    // from a code-reading rather than a measurement — and a false red on a 15-minute
    // leg is expensive. The settling experiment is the first green run: promote this
    // to an assertion once the printed list is known to be empty.
    console.log(`[installed-app] console errors (reported, not asserted): ${JSON.stringify(consoleErrors)}`);
  });
});
