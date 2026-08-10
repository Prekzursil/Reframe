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
// ── HOW A TOAST-ABSENCE ASSERTION IS MADE FALSIFIABLE (refuted 2026-08-11) ────
// The paragraph above claimed the pair was "a real control rather than a
// green-everywhere probe". For the two ABSENCE assertions that was REFUTED, and
// the mechanism is arithmetic: `Library.tsx` `TOAST_TTL_MS = 6000` and a
// `setTimeout` that REMOVES the toast node at 6 s, against
// `playwright.config.ts`'s `expect: { timeout: 30_000 }`. `toHaveCount` is a
// retrying web-first assertion, so an unbounded `toHaveCount(0)` was satisfied by
// WAITING: any spurious toast is polled away at t≈6 s, well inside the 30 s budget.
//
// MEASURED, not reasoned. A throwaway probe broke ONE link in the very chain this
// file exists to cover — `ipcMain.removeHandler('dialog.openVideos')` against the
// running main process, so the preload's `invoke` rejects — and read all four arms
// in one run:
//   * the mutant is visible at t+789 ms as an error toast reading
//     "Error invoking remote method 'dialog.openVideos': Error: No handler
//     registered for 'dialog.openVideos'";
//   * the ORIGINAL unbounded `toHaveCount(0)` PASSED after 6103 ms — the 6000 ms
//     TTL, i.e. it survived by waiting, with the ipc link severed;
//   * the same assertion bounded at 1500 ms FAILED;
//   * the dialog-call counter arm FAILED with counter=0.
// So the absence assertions were a SURVIVING MUTANT and both remediations kill it.
// (The probe's first version put its 8 s counter poll BEFORE the toast snapshot and
// so reported "0 toasts" and "passed in 76 ms" — readings that cannot both be true
// if the toast existed. That was a detector fault in the probe, fixed by measuring
// the t≈0 observable first; recorded because the corrected numbers above are only
// trustworthy given the ordering.)
//
// Two independent fixes, because an absence assertion can be vacuous from EITHER
// side and bounding alone only closes one of them:
//   * TOO LATE — every absence assertion is now bounded by `TOAST_ABSENT_MS`,
//     which MUST stay below TOAST_TTL_MS, so a leaked toast is still on screen
//     when the window expires.
//   * TOO EARLY — a bounded `toHaveCount(0)` also passes instantly if it runs
//     BEFORE the toast would have rendered. So absence is only ever asserted
//     AFTER a positive signal that the path under test has already run: the
//     dialog-call counter below for CANCEL, the rendered error toast for the
//     failed add.
// The afterEach postcondition is likewise no longer swallowed.
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

// The window geometry the app actually creates — matches createWindow() in
// app/main/main.ts.
//
// Declared LOCALLY rather than imported from `./visual/_visualSetup` (refuted
// 2026-08-11). The import was justified as a "single source, shared with the
// visual suite", but `_visualSetup` restates the two numbers itself — its own
// comment says "matches createWindow() in app/main/main.ts" — so the import bought
// no de-duplication. What it DID buy was a dependency from the 3-OS GUI matrix
// onto the visual suite's toolchain: `_visualSetup` runs
// `readFileSync(require.resolve('axe-core/axe.min.js'))` at MODULE SCOPE, so
// merely COLLECTING this spec resolved and slurped the axe-core browser bundle.
// `playwright.config.ts` sets `testIgnore: ['visual/**', 'audit/**']` precisely to
// keep that suite out of this matrix, and the import re-introduced it — so an
// `axe-core` `exports`-map change, or moving it to the visual job's install, would
// have taken down a spec that has nothing to do with accessibility, at collection.
const WINDOW_WIDTH = 1280;
const WINDOW_HEIGHT = 820;

/** Basename (sans extension) the Library renders as a card title for our pick. */
const PICKED_STEM = 'picked-by-dialog';

/**
 * Budget for asserting a toast is ABSENT. MUST stay below `Library.tsx`'s
 * `TOAST_TTL_MS` (6000) — that is the entire point: above it, the assertion is
 * satisfied by the toast's own expiry rather than by the behaviour under test.
 * Deliberately NOT the config's 30 s `expect.timeout`, and deliberately not a
 * value derived from it.
 */
const TOAST_ABSENT_MS = 1_500;

/**
 * `Library.tsx`'s `TOAST_TTL_MS`, restated here because it is not exported.
 *
 * RESTATED, NOT IMPORTED, and that is a real weakness: raise the renderer's TTL
 * and `TOAST_ABSENT_MS` silently stops being the "below the TTL" bound that makes
 * every absence assertion in this file falsifiable. Guarded by the static
 * assertion below rather than left to a reader. Settling experiment for the
 * residual: export `TOAST_TTL_MS` from `Library.tsx` and import it, which is a
 * renderer change and therefore another lane's file.
 */
const TOAST_TTL_MS = 6_000;

// A leaked toast must still be ON SCREEN when an absence assertion expires. If
// this ever inverts, every `toHaveCount(0, { timeout: TOAST_ABSENT_MS })` below
// degenerates into "wait for the toast to expire" — the exact defect this file was
// refuted for. Failing at MODULE LOAD is deliberate: it takes the whole spec down
// loudly instead of reporting a meaningless green.
if (TOAST_ABSENT_MS >= TOAST_TTL_MS) {
  throw new Error(
    `TOAST_ABSENT_MS (${TOAST_ABSENT_MS}) must stay below Library.tsx TOAST_TTL_MS ` +
      `(${TOAST_TTL_MS}); otherwise every toast-absence assertion here is satisfied by ` +
      'the toast expiring rather than by the behaviour under test.',
  );
}

let seeded: SeededEnv;
let app: ElectronApplication;
/** A REAL H.264/AAC file that is deliberately NOT in the seeded library. */
let pickedPath: string;
const consoleErrors: string[] = [];

/** Where the in-main call counter parks itself (main-process global). */
const CALL_COUNTER = '__rfOpenVideosDialogCalls';

/**
 * Stub `dialog.showOpenDialog` AND wrap the stub with a call counter.
 *
 * The counter is the CANCEL case's positive signal, and it is the one observation
 * in this file that cannot be satisfied by waiting: it goes from 0 to 1 only if the
 * click actually traversed `.library__add-btn` onClick -> Library.handlePick ->
 * the preload `window.api.openVideos` -> `ipcMain.handle('dialog.openVideos')` ->
 * `dialog.showOpenDialog`. Break ANY link — the seam this spec exists for — and it
 * stays 0. `stubDialog` alone cannot provide this: it overwrites the method with a
 * plain `async () => value` that records nothing (node_modules/
 * electron-playwright-helpers/dist/dialog_helpers.js `stubMultipleDialogs`).
 *
 * Re-armed per case on purpose: each `stubDialog` REPLACES `dialog.showOpenDialog`
 * outright, so a wrapper installed once would be discarded by the next stub and the
 * counter would silently stop counting — a detector that quietly stops detecting is
 * the failure mode this whole file is about.
 */
async function stubOpenDialog(value: { canceled: boolean; filePaths: string[] }): Promise<void> {
  await stubDialog(app, 'showOpenDialog', value);
  await app.evaluate(({ dialog }, counterKey) => {
    const store = globalThis as unknown as Record<string, number>;
    store[counterKey] = 0;
    const stubbed = dialog.showOpenDialog.bind(dialog);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    dialog.showOpenDialog = ((...args: any[]) => {
      store[counterKey] = (store[counterKey] ?? 0) + 1;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return (stubbed as any)(...args);
    }) as typeof dialog.showOpenDialog;
  }, CALL_COUNTER);
}

/** How many times the app has reached `dialog.showOpenDialog` since the stub. */
async function openDialogCalls(): Promise<number> {
  return app.evaluate(
    (_electron, counterKey) => (globalThis as unknown as Record<string, number>)[counterKey] ?? 0,
    CALL_COUNTER,
  );
}

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
  // test. Three assertions below are about the ABSENCE of a toast, so leaving one
  // behind would make them pass or fail on wall-clock timing rather than on
  // behaviour.
  //
  // THIS USED TO CLICK `.library__toast-dismiss` in a loop, justified as "not a
  // state poke". Two things were wrong with it and both were MEASURED:
  //   1. Its postcondition sat INSIDE a `try { } catch { }`, so the one bounded
  //      check capable of observing a leaked toast had its failure discarded — the
  //      "settled, observed empty state" was asserted and then thrown away.
  //   2. The clicking itself is coordinate-racy against the card grid.
  //      `.library__toasts` is an IN-FLOW flex column (shell.css:993 — `margin`,
  //      no `position`), rendered ABOVE the grid in document order, so removing a
  //      toast REFLOWS every card upward. During this remediation a full run left
  //      the app on the Edit workspace for `picked-by-dialog` — i.e. a card had
  //      been opened — and the next case then timed out waiting 30 s for
  //      `.library__add-btn`, which no longer existed. That is the signature of a
  //      teardown click landing on a card that moved into the vacated space.
  //      UNVERIFIED which action navigated: the run was not traced, and it did not
  //      reproduce in the two runs after it (so: a load-sensitive race on a box
  //      with seven other lanes building). Settling experiment: `--trace on` and
  //      read the action that precedes the `onOpen`. The redesign below makes the
  //      question moot rather than answering it.
  //
  // So teardown now WAITS OUT the TTL instead of clicking: the app removes the
  // node itself (Library.tsx `setTimeout(..., TOAST_TTL_MS)`), which is still the
  // app's own behaviour rather than a state poke, and it cannot move the grid under
  // a queued click. No coverage is lost — the dismiss button is pinned by
  // `Library.test.tsx:745` ("dismisses a fallback toast when its × button is
  // clicked"), which is the right level for it.
  test.afterEach(async () => {
    const win = await app?.firstWindow();
    if (!win) return;
    // ASSERTED, not swallowed. Note the bound points the OPPOSITE way to
    // TOAST_ABSENT_MS on purpose: an in-test absence assertion must expire BELOW
    // the TTL so a leaked toast is still visible, whereas this one must sit ABOVE
    // it so the app has actually had time to clean up.
    await expect(
      win.locator('.library__toast'),
      'a toast outlived its TTL — the next case’s absence assertions would be ' +
        'measuring this toast’s expiry instead of their own behaviour',
    ).toHaveCount(0, { timeout: TOAST_TTL_MS + 3_000 });
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

  test('CANCEL — the click reaches the native dialog, and a cancel adds nothing', async () => {
    const win = await app.firstWindow();
    await stubOpenDialog({ canceled: true, filePaths: [] });
    expect(await openDialogCalls(), 'counter must start armed at zero').toBe(0);

    await win.locator('.library__add-btn').click();

    // (a) POSITIVE SIGNAL — the whole chain ran. This is the assertion that makes
    // the cancel case a real control: it cannot be satisfied by waiting, and it
    // goes red the moment any link between the button and `dialog.showOpenDialog`
    // is broken. Polled because the click returns before the IPC round trip lands.
    await expect
      .poll(openDialogCalls, { timeout: 10_000 })
      .toBe(1);

    // (b) The button is present and IDLE.
    //
    // SCOPE CORRECTION (refuted 2026-08-11): this line used to be commented "the
    // handler ran to completion (`adding` went true -> false) rather than never
    // having fired at all". On the CANCEL path `adding` is NEVER set true, so the
    // described transition cannot occur and the assertion held before, during and
    // after the click — including if the onClick were deleted outright, which is the
    // precise opposite of what it claimed to establish. `handlePick` never touches
    // `adding` (Library.tsx:286-304) and `addPaths` returns at Library.tsx:259
    // (`if (paths.length === 0) return;`) BEFORE `setAdding(true)` at :260, while the
    // label is `{adding ? 'Adding…' : 'Add videos'}` (:542). What it actually checks
    // is that the button is still rendered and not stuck in `Adding…` — worth
    // asserting (a hung `adding` would disable the control) but NOT evidence the
    // handler fired. That evidence is (a).
    await expect(win.locator('.library__add-btn')).toHaveText('Add videos');
    await expect(win.locator('.library__item-title')).toHaveCount(1);
    // (c) A cancel is not an error: `addPaths` returns early on an empty list, so no
    // toast of ANY kind should appear. Bounded BELOW TOAST_TTL_MS so a toast that
    // did appear is still on screen when the window closes, and asserted only after
    // (a) so it cannot pass by running before the render.
    await expect(
      win.locator('.library__toast'),
      'a cancelled pick must emit no toast — an error toast here is the ' +
        '"Native file picker unavailable" degradation, i.e. an unwired preload bridge',
    ).toHaveCount(0, { timeout: TOAST_ABSENT_MS });
  });

  test('PICK — the real button, bridge, ipc handler and RPC add the picked file', async () => {
    const win = await app.firstWindow();
    // Electron's showOpenDialog resolves absolute paths; hand back exactly what a
    // user picking this file would produce.
    await stubOpenDialog({ canceled: false, filePaths: [pickedPath] });

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
    await stubOpenDialog({ canceled: false, filePaths: [ghost] });

    await win.locator('.library__add-btn').click();

    const errorToast = win.locator('.library__toast--error .library__toast-msg');
    await expect(errorToast).toContainText('video not found');
    await expect(errorToast).toContainText(basename(ghost));
    // A failed add adds no card, and no success toast is emitted for zero adds.
    await expect(win.locator('.library__item-title')).toHaveCount(2);
    // Bounded below TOAST_TTL_MS for the same reason as the CANCEL case — an
    // unbounded `toHaveCount(0)` would be satisfied by the toast's own 6 s expiry
    // inside the 30 s budget. The "too early" direction is already closed here by
    // the two assertions above: the error toast is RENDERED before this runs, so
    // both toasts have had their chance to appear.
    await expect(
      win.locator('.library__toast--success'),
      'a failed add must emit no success toast — `addedCount` was 0',
    ).toHaveCount(0, { timeout: TOAST_ABSENT_MS });
  });

  test('no console errors across the whole add-videos session', () => {
    // The listener was bound in beforeAll, so this covers the cancel, the pick and
    // the failed add — including the rejected RPC, which must be HANDLED (a toast)
    // rather than surfacing as an unhandled rejection in the renderer console.
    expect(consoleErrors, `console errors: ${JSON.stringify(consoleErrors)}`).toEqual([]);
  });
});
