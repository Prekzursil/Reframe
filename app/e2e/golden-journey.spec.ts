// golden-journey.spec.ts — the KEYSTONE held-out acceptance test for Reframe.
//
// This is the single external "done-signal" that proves the app actually WORKS
// A→B→C — coverage + unit-green are necessary-but-not-sufficient; THIS drives the
// real "Make Shorts" user journey through the LIVE Electron GUI + the LIVE Python
// sidecar and asserts a REAL produced vertical short file exists on disk.
//
// The journey (everything against the live app + live sidecar — nothing stubbed):
//   launch built app
//     → the seeded 'sample' video is imported + listed in the Library
//     → navigate to the top-level "Make Shorts" tab (routes to makeshorts)
//     → select 'sample' in the Make-Shorts front-door picker (opens it for
//       short-making — this section owns its OWN picker; see MakeShorts.tsx §h)
//     → drive the MANUAL-interval path (add one 0:00→0:02 range, then
//       "Make shorts from ranges") — the deterministic path: it feeds inline
//       Candidates straight to shortmaker.export with NO ML moment-pick, NO
//       transcript, and (unlike select/boundary) is NOT re-clamped to the 20-60s
//       hard window, so the real 3s seeded sample can genuinely produce a clip
//       (AI moment-pick would emit "no candidates" on a 3s no-speech sample)
//     → the UI acknowledges the dispatched export (the "Exported N clip(s)" note)
//     → wait for the produced short to appear in the produced-shorts listing
//       (shorts.list — the exact RPC the gallery renders from), read the FINAL
//       clip's real output path, and assert that file EXISTS on disk + is
//       non-empty. Additionally assert it is a VERTICAL short (height > width,
//       from the sidecar's own ffprobe dims) with a real (>0) duration.
//
// DONE-SIGNAL note: the manual path fires the export as a background Job (the RPC
// resolves with {jobId} immediately — the note appears BEFORE render finishes),
// so completion is proven by polling shorts.list for the FINAL clip. Every
// exported clip writes a sidecar <clip>.json (videoId/durationSec/…) that
// shorts.list reconstructs ShortInfo from; the pipeline's INTERMEDIATES
// (*.cut.mp4 / *.reframed.mp4 / …) live in the same dir but carry NO .json, so
// they surface with videoId='' — we filter for `videoId === seeded.videoId`
// (metadata present ⇒ the FULL cut→reframe→caption→export pipeline finished),
// which uniquely identifies the finished vertical short.
//
// It is EXPECTED + CORRECT for this test to RED-REPRO if the export pipeline is
// broken ("shorts don't actually generate"): if the job errors mid-pipeline no
// metadata-bearing short is ever written, so the poll times out with a diagnostic
// snapshot of what DID land on disk (which intermediate stage was reached). A
// faithful red repro is a success here; a green fantasy is a failure.

import { test, expect, _electron as electron, type ElectronApplication, type Page } from '@playwright/test';
import { existsSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import { findBuiltApp, provisionAssets, seedEnvironment, type SeededEnv } from './fixtures';

let seeded: SeededEnv;
let app: ElectronApplication;
const consoleErrors: string[] = [];
const failedRequests: string[] = [];
// Buffer the packaged/dev MAIN process stdout+stderr — the spawned sidecar's
// export-job errors (e.g. a reframe ClaudeShortsBackendUnavailableError, a cv2
// FaceDetectorYN failure, a missing model) surface there, NOT in Playwright's
// error-context.md. We fold the tail into the done-signal failure message so a
// red repro names the stage that broke instead of only the on-disk snapshot.
const mainLog: string[] = [];

/** The subset of ShortInfo (§3, features/shorts.py) this test reads off shorts.list. */
interface BridgeShort {
  path: string;
  videoId: string;
  durationSec: number;
  width: number;
  height: number;
}

/**
 * Read `shorts.list {videoId}` through the LIVE preload bridge (window.api, the
 * same RPC the produced-shorts gallery renders from) so we observe the exact
 * sidecar the export job ran against. Returns [] on any bridge/RPC hiccup so the
 * caller's poll simply retries rather than throwing mid-render.
 */
async function listShortsViaBridge(win: Page, videoId: string): Promise<BridgeShort[]> {
  return win.evaluate(async (vid: string): Promise<BridgeShort[]> => {
    try {
      const api = (
        window as unknown as {
          api?: { rpc: (method: string, params?: unknown) => Promise<{ shorts?: BridgeShort[] }> };
        }
      ).api;
      if (!api) return [];
      const res = await api.rpc('shorts.list', { videoId: vid });
      const shorts = res?.shorts;
      return Array.isArray(shorts) ? shorts : [];
    } catch {
      return [];
    }
  }, videoId);
}

/**
 * Poll shorts.list until a FINISHED short for `videoId` appears (metadata-bearing
 * ⇒ the full pipeline completed) or the deadline passes. Returns the final clip
 * plus the last snapshot (the intermediates on disk) for a diagnostic red repro.
 */
async function pollForFinalShort(
  win: Page,
  videoId: string,
  deadlineMs: number,
): Promise<{ final: BridgeShort | null; snapshot: BridgeShort[] }> {
  let snapshot: BridgeShort[] = [];
  while (Date.now() < deadlineMs) {
    snapshot = await listShortsViaBridge(win, videoId);
    const final = snapshot.find((s) => s.videoId === videoId && s.durationSec > 0);
    if (final) return { final, snapshot };
    await new Promise((r) => setTimeout(r, 1500));
  }
  return { final: null, snapshot };
}

test.beforeAll(async () => {
  // Prefer the SHIPPED package (real .exe on Windows); fall back to the dev build
  // so this spec still gives local GUI coverage (see fixtures.findBuiltApp).
  const built = findBuiltApp();
  seeded = seedEnvironment();
  // Provision the core reframe model (YuNet) into the data root — the SAME step a
  // real first-run performs — so the default reframeEngine:"auto" (claudeshorts)
  // path can actually reframe. Without it, "auto" raises ClaudeShortsBackend-
  // UnavailableError and no short is ever produced (a provisioning gap, not a bug).
  await provisionAssets(seeded.python, seeded.dataRoot, ['yunet-face-detection']);
  app = await electron.launch({
    args: [
      built.main,
      // No user gesture exists in an automated launch; allow media to start.
      '--autoplay-policy=no-user-gesture-required',
      '--no-sandbox',
    ],
    ...(built.executablePath ? { executablePath: built.executablePath } : {}),
    env: seeded.appEnv,
  });

  // Capture the main process (and its spawned sidecar) stdout/stderr so a failed
  // export job's real error is recoverable in CI (see mainLog note above).
  const proc = app.process();
  proc.stdout?.on('data', (d: Buffer) => mainLog.push(d.toString()));
  proc.stderr?.on('data', (d: Buffer) => mainLog.push(d.toString()));

  // Bind the console/pageerror collectors from the very first frame so they cover
  // the WHOLE session (load + navigation + making the short).
  const win = await app.firstWindow();
  win.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  win.on('pageerror', (e) => consoleErrors.push(`PAGEERROR: ${e.message}`));
  // Chromium's "Failed to load resource: 404" console line omits the URL — capture
  // the failing response's URL + status here so a resource error is self-diagnosing
  // (which asset 404'd) instead of an anonymous console string.
  win.on('response', (r) => {
    const s = r.status();
    if (s >= 400) failedRequests.push(`${s} ${r.url()}`);
  });
  win.on('requestfailed', (req) => {
    failedRequests.push(`FAILED ${req.url()} (${req.failure()?.errorText ?? 'unknown'})`);
  });
  await win.waitForLoadState('domcontentloaded');
});

test.afterAll(async () => {
  await app?.close();
});

test('Make Shorts produces a real vertical short file on disk (golden journey)', async () => {
  // Rendering a short runs cut → reframe(1080x1920) → caption → export through
  // real ffmpeg; give the pipeline generous headroom over the 120s config default.
  test.setTimeout(240_000);
  const win = await app.firstWindow();

  // A — the shell is up and the seeded sample is imported + listed (openable).
  await expect(win.locator('.app__brand')).toHaveText('Reframe');
  await expect(win.locator('.library__item-title').first()).toHaveText('sample');

  // B — navigate to the top-level "Make Shorts" section (routes to makeshorts).
  // NOTE: the tab's real label is "Make Shorts" (App.tsx → TopTabBar renders
  // tab.label); preview.spec's `hasText: 'Create'` predates the relabel.
  await win.locator('.toptab', { hasText: 'Make Shorts' }).click();
  await expect(
    win.locator('.toptab[aria-selected="true"]', { hasText: 'Make Shorts' }),
  ).toBeVisible();
  await expect(win.locator('.make-shorts__make')).toBeVisible();

  // Select 'sample' in the Make-Shorts front-door picker. This section owns its
  // OWN video picker (novice front door, MakeShorts.tsx §h): selecting the video
  // here IS "opening" it for short-making — the top tab does not thread an open
  // Workspace video, and driving the picker keeps the journey deterministic
  // (no Workspace proxy-build side effects to race against the export).
  const picker = win.locator('select[aria-label="Source video"]');
  await expect(picker.locator('option', { hasText: 'sample' })).toBeAttached({ timeout: 15_000 });
  await picker.selectOption(seeded.videoId);

  // Selecting a video reveals the making surfaces, including manual intervals.
  const manual = win.locator('.make-shorts__manual');
  await expect(manual).toBeVisible();

  // C — MANUAL path: add one explicit 0:00 → 0:02 range (well inside the 3s
  // sample), then "Make shorts from ranges" to trigger the real shortmaker.export.
  await manual.locator('input[aria-label="Range start"]').fill('0:00');
  await manual.locator('input[aria-label="Range end"]').fill('0:02');
  await manual.locator('button', { hasText: 'Add range' }).click();
  await expect(manual.locator('.manual-interval__range')).toHaveCount(1);
  await manual.locator('.manual-interval__make', { hasText: 'Make shorts from ranges' }).click();

  // The UI acknowledges the DISPATCH (note appears once the export RPC returns a
  // jobId — the render then runs in the background). Surface a dispatch error
  // (invalid params / dead sidecar) as the failure instead of a silent timeout.
  await win
    .locator('.make-shorts__note, .make-shorts__error')
    .first()
    .waitFor({ state: 'visible', timeout: 30_000 });
  if (await win.locator('.make-shorts__error').isVisible()) {
    throw new Error(
      `manual export dispatch failed: ${(await win.locator('.make-shorts__error').textContent())?.trim()}`,
    );
  }
  await expect(win.locator('.make-shorts__note')).toContainText('Exported');

  // PRIMARY DONE-SIGNAL — wait for the FINISHED short, then assert the real file.
  const { final, snapshot } = await pollForFinalShort(win, seeded.videoId, Date.now() + 200_000);
  // On a red repro, surface the sidecar's own error tail (the export job's real
  // failure — reframe/cv2/model) alongside the on-disk snapshot so the failing
  // stage is named, not guessed.
  const sidecarErr = mainLog
    .join('')
    .split(/\r?\n/)
    .filter((l) =>
      /error|traceback|reframe|yunet|cv2|facedetector|claudeshorts|opencv|backend|provision|not provisioned/i.test(l),
    )
    .slice(-30)
    .join('\n');
  expect(
    final,
    `no finished short appeared for videoId=${seeded.videoId} within 200s — the export ` +
      `job never completed (shorts.list snapshot, incl. intermediates: ${JSON.stringify(snapshot)})` +
      (sidecarErr ? `\n--- sidecar error tail ---\n${sidecarErr}` : ''),
  ).not.toBeNull();

  const producedPath = resolve(final!.path);
  expect(existsSync(producedPath), `produced short exists on disk: ${producedPath}`).toBe(true);
  expect(
    statSync(producedPath).size,
    `produced short is a non-empty file: ${producedPath}`,
  ).toBeGreaterThan(0);

  // A real VERTICAL short with a real duration (dims from the sidecar's own
  // ffprobe on the finished mp4; the pipeline only writes metadata after a
  // successful 1080x1920 reframe, so a metadata-bearing clip is genuinely portrait).
  expect(
    final!.height,
    `portrait short (height > width) — got ${final!.width}x${final!.height}`,
  ).toBeGreaterThan(final!.width);
  expect(final!.width, 'produced short has real dimensions').toBeGreaterThan(0);
  expect(final!.durationSec, 'produced short has a real duration').toBeGreaterThan(0);
});

test('no console errors across the golden-journey session', async () => {
  // The console/pageerror listeners (bound in beforeAll) collected across load,
  // navigation, picker selection, and the whole make-a-short flow. Kept SEPARATE
  // from — and after — the file-on-disk done-signal so a renderer console error
  // never masks the primary "did a real short get produced?" verdict.
  expect(
    consoleErrors,
    `console errors across session: ${JSON.stringify(consoleErrors)}\n` +
      `failed requests (URLs behind any "Failed to load resource" line): ${JSON.stringify(failedRequests)}`,
  ).toEqual([]);
});
