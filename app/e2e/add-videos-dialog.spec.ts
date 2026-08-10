// add-videos-dialog.spec.ts — the button a real user clicks to add a video (W40).
//
// ── THE HOLE THIS CLOSES ─────────────────────────────────────────────────────
// EVERY other spec in this harness seeds the library OUT OF BAND, through the
// `library.add` JSON-RPC (`fixtures.seedEnvironment`), because the in-app route
// goes through a NATIVE OS file dialog. `fixtures.ts` said so in its own header —
// "the add path goes through a NATIVE OS file dialog (dialog.openVideos), which
// Playwright cannot drive headlessly" — and concluded that seeding is
// "equivalent". It is equivalent for everything DOWNSTREAM of the add (the app
// lists, opens and plays the same record), and it is not equivalent for the add
// itself: the chain
//
//   `.library__add-btn` onClick
//     -> Library.handlePick -> window.api.openVideos()            (renderer)
//     -> ipcRenderer.invoke('dialog.openVideos')                  (preload.ts)
//     -> ipcMain.handle('dialog.openVideos') -> openVideosDialog  (dialogIpc.ts)
//     -> dialog.showOpenDialog
//     -> Library.addPaths -> rpc('library.add')                   (renderer)
//
// had ZERO end-to-end coverage. `Library.test.tsx` covers `handlePick` against a
// jsdom `window.api` stub (so the preload bridge and the ipc handler are absent),
// and `dialogIpc.test.ts` covers the registration against a fake `ipcMain` (so the
// renderer and the RPC are absent). Nothing joined the two halves, so a broken
// preload wiring — exactly the `WIRING-U2` seam `Library.tsx` degrades gracefully
// around — would have shipped green: the renderer would emit "Native file picker
// unavailable" and no test would notice.
//
// ── THE SEAM, AND WHY IT NEEDS NO PRODUCTION CHANGE ──────────────────────────
// The un-drivable part is ONLY the OS widget. `electron-playwright-helpers`
// `stubDialog` replaces `dialog.showOpenDialog` INSIDE the running main process
// (via `electronApp.evaluate`), so every link in the chain above is the real one
// and only the OS window is substituted. No env-gated test hook was added to
// `app/main/dialogIpc.ts`: a production seam that a user could trip is a worse
// trade than leaving the OS widget itself unobserved, and it would not have proven
// any more of the chain.
//
// HONESTLY SCOPED — what is NOT proven here: that Electron's own
// `dialog.showOpenDialog` renders, filters by `VIDEO_FILE_FILTERS`, honours
// `properties: ['openFile','multiSelections']`, or starts in `app.getPath('videos')`.
// Those are properties of the OS dialog and of the options object; the options are
// pinned by `dialogIpc.test.ts` at the unit level. The settling experiment for the
// widget itself is a human clicking it.
//
// ── BOTH-STATES BY CONSTRUCTION ──────────────────────────────────────────────
// The CANCEL case and the PICK case drive the IDENTICAL click on the IDENTICAL
// wiring; the ONLY difference is the value injected at the dialog. So the pair is
// a real control rather than a green-everywhere probe: cancel must add nothing,
// a pick must add exactly that file. A third case injects a path that does not
// exist and requires the SIDECAR's own words ("video not found") to reach the
// toast — text the renderer cannot author, so it proves the click really travelled
// all the way to Python.
//
// It gates nothing: `e2e.yml` is `workflow_dispatch` + nightly `cron` only, so
// this proves the capability nightly and on demand; it cannot stop an "Add videos"
// regression from merging.

import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { stubDialog } from 'electron-playwright-helpers';
import { basename, join } from 'node:path';
import {
  findBuiltApp,
  generateSample,
  listLibraryVideos,
  seedEnvironment,
  type SeededEnv,
} from './fixtures';
// The window geometry the app actually creates (main/main.ts) — single source,
// shared with the visual suite so the number is not restated per spec.
import { WINDOW_HEIGHT, WINDOW_WIDTH } from './visual/_visualSetup';

/** Basename (sans extension) the Library renders as a card title for our pick. */
const PICKED_STEM = 'picked-by-dialog';

let seeded: SeededEnv;
let app: ElectronApplication;
/** A REAL H.264/AAC file that is deliberately NOT in the seeded library. */
let pickedPath: string;
const consoleErrors: string[] = [];

test.describe('native "Add videos" dialog drives the real add path (W40)', () => {
  test.beforeAll(async () => {
    const built = findBuiltApp();
    seeded = seedEnvironment();
    // Lives INSIDE the per-run data root so it is thrown away with it, but it is
    // never registered — `seedEnvironment` only adds `sample.mp4`.
    pickedPath = join(seeded.dataRoot, `${PICKED_STEM}.mp4`);
    generateSample(pickedPath);

    app = await electron.launch({
      args: [built.main, '--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
      ...(built.executablePath ? { executablePath: built.executablePath } : {}),
      env: seeded.appEnv,
    });
    const win = await app.firstWindow();
    win.on('console', (m) => {
      if (m.type() === 'error') consoleErrors.push(m.text());
    });
    win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
    await win.setViewportSize({ width: WINDOW_WIDTH, height: WINDOW_HEIGHT });
    await win.waitForLoadState('domcontentloaded');
    // Wait for the seeded row to render, so "one card" is a settled state and not
    // a race against the boot-time `library.list`.
    //
    // EXPLICIT 60s, above the config's 30s `expect.timeout`, and it is NOT a
    // loosened assertion — the value asserted is unchanged (exactly one card) and
    // only the patience is. This is a COLD sidecar spawn (a fresh Python process
    // per launch) and it MEASURABLY exceeded 30s once on a loaded box: the run
    // failed here with the renderer still showing `status "Loading your videos"`
    // and `Capabilities: checking…`, i.e. the boot RPCs had not answered yet
    // rather than the library being wrong. The failure message names that state so
    // a future red is diagnosable instead of just "expected 1 received 0".
    await expect(
      win.locator('.library__item-title'),
      'the seeded library row must render before the add path is driven — a red here with ' +
        '0 cards and a "Loading your videos" status means the sidecar had not answered ' +
        'library.list yet, which is a boot-time symptom, not an add-path defect',
    ).toHaveCount(1, { timeout: 60_000 });
  });

  test.afterAll(async () => {
    await app?.close();
  });

  // TOAST STATE CONTAINMENT. `playwright.config.ts` runs `fullyParallel: false,
  // workers: 1` against the ONE app launched above, and `Library.tsx`'s local
  // toasts live for `TOAST_TTL_MS = 6000` — long enough to survive into the next
  // test. Two of the assertions below are about the ABSENCE of a toast, so leaving
  // one behind would make them pass or fail on wall-clock timing rather than on
  // behaviour. Dismissing through the real `.library__toast-dismiss` button (not a
  // state poke) keeps every case starting from a settled, observed empty state.
  test.afterEach(async () => {
    const win = await app?.firstWindow();
    if (!win) return;
    try {
      const dismissers = win.locator('.library__toast-dismiss');
      // Always click the FIRST one: each click removes a node, so a cached index
      // would go stale. Bounded by the count read before the loop.
      for (let i = await dismissers.count(); i > 0; i -= 1) {
        await dismissers.first().click({ timeout: 5_000 });
      }
      await expect(win.locator('.library__toast')).toHaveCount(0, { timeout: 5_000 });
    } catch {
      // Best-effort cleanup: never mask the real failure with a teardown error.
    }
  });

  test('PRECONDITION — the file the dialog will return is not in the library yet', async () => {
    const win = await app.firstWindow();
    // Detector control for every negative assertion below: the title we are about
    // to look for is genuinely absent NOW, so a later `toHaveCount(0)` cannot be
    // passing because the selector is wrong.
    await expect(win.locator('.library__item-title', { hasText: PICKED_STEM })).toHaveCount(0);
    // ...and the sidecar agrees, from its own persisted state.
    const titles = listLibraryVideos(seeded.python, seeded.dataRoot).map((v) => v.title);
    expect(titles).toEqual(['sample']);
  });

  test('CANCEL — clicking Add videos with a cancelled dialog adds nothing', async () => {
    const win = await app.firstWindow();
    await stubDialog(app, 'showOpenDialog', { canceled: true, filePaths: [] });

    await win.locator('.library__add-btn').click();

    // The button returns to its idle label, i.e. the handler ran to completion
    // (`adding` went true -> false) rather than never having fired at all.
    await expect(win.locator('.library__add-btn')).toHaveText('Add videos');
    await expect(win.locator('.library__item-title')).toHaveCount(1);
    // A cancel is not an error: `addPaths` returns early on an empty list, so no
    // toast of ANY kind should appear.
    await expect(win.locator('.library__toast')).toHaveCount(0);
  });

  test('PICK — the real button, bridge, ipc handler and RPC add the picked file', async () => {
    const win = await app.firstWindow();
    // Electron's showOpenDialog resolves absolute paths; hand back exactly what a
    // user picking this file would produce.
    await stubDialog(app, 'showOpenDialog', { canceled: false, filePaths: [pickedPath] });

    await win.locator('.library__add-btn').click();

    // (a) the user SEES the new card, titled from the file the dialog returned.
    await expect(win.locator('.library__item-title', { hasText: PICKED_STEM })).toHaveCount(1);
    await expect(win.locator('.library__item-title')).toHaveCount(2);
    // (b) and the success toast the add path emits for exactly one file.
    await expect(win.locator('.library__toast--success .library__toast-msg')).toHaveText(
      'Added 1 video',
    );

    // (c) SECOND, INDEPENDENT SIGNAL — the sidecar persisted a row for that file.
    // The DOM alone cannot distinguish "library.add succeeded" from "the renderer
    // optimistically painted a card"; this reads the data root the sidecar owns.
    const rows = listLibraryVideos(seeded.python, seeded.dataRoot);
    expect(rows.map((v) => v.title).sort()).toEqual([PICKED_STEM, 'sample']);
    expect(rows.map((v) => v.path)).toContain(pickedPath);
  });

  test('a path that does not exist surfaces the SIDECAR’s own error in the GUI', async () => {
    const win = await app.firstWindow();
    // `library.add` raises FileNotFoundError("video not found: <path>") which the
    // handler maps to an RPC error (sidecar/media_studio/library.py add(); the
    // handler at handlers/library_ops.py library_add()). That wording exists ONLY
    // in Python — the renderer builds its toast as `${basename}: ${err.message}`
    // and has no such string — so seeing it on screen proves the click reached the
    // sidecar rather than being short-circuited anywhere in the chain.
    const ghost = join(seeded.dataRoot, 'no-such-clip.mp4');
    await stubDialog(app, 'showOpenDialog', { canceled: false, filePaths: [ghost] });

    await win.locator('.library__add-btn').click();

    const errorToast = win.locator('.library__toast--error .library__toast-msg');
    await expect(errorToast).toContainText('video not found');
    await expect(errorToast).toContainText(basename(ghost));
    // A failed add adds no card, and no success toast is emitted for zero adds.
    await expect(win.locator('.library__item-title')).toHaveCount(2);
    await expect(win.locator('.library__toast--success')).toHaveCount(0);
  });

  test('no console errors across the whole add-videos session', () => {
    // The listener was bound in beforeAll, so this covers the cancel, the pick and
    // the failed add — including the rejected RPC, which must be HANDLED (a toast)
    // rather than surfacing as an unhandled rejection in the renderer console.
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
  });
});
