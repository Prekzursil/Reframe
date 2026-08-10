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
// The window geometry the app actually creates (main/main.ts) — single source, shared
// with the visual suite so the number is not restated per spec.
import { WINDOW_HEIGHT, WINDOW_WIDTH } from './visual/_visualSetup';

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

  // PIN THE VIEWPORT. This spec makes GEOMETRY assertions (`toBeInViewport` on the
  // Advanced toggle) and did not pin the renderer viewport, so it inherited whatever
  // the CI display/window-manager handed the BrowserWindow. `main.ts` creates the
  // window at 1280x820, but the measured innerWidth the assertion was written against
  // (1264) is a LOCAL observation — on CI the toggle came back "viewport ratio 0", i.e.
  // entirely off-screen, on BOTH windows-latest and macos-latest.
  //
  // The visual suite already solved exactly this and says why: "Pin the viewport so
  // layout (and thus pixels) is reproducible run-to-run" (`_visualSetup.ts`). Reusing
  // its exported constants rather than restating 1280x820 a third time.
  const win0 = await app.firstWindow();
  await win0.setViewportSize({ width: WINDOW_WIDTH, height: WINDOW_HEIGHT });
});

test.afterAll(async () => {
  await app?.close();
});

// STATE CONTAINMENT. `playwright.config.ts` runs `fullyParallel: false, workers: 1`
// against the ONE app launched above, so every test shares live renderer state. The
// Advanced-disclosure test restored `advancedOpen = false` at the END of its body —
// which does not run when an assertion earlier in the body fails. Measured on CI run
// 30677298418: one geometry failure at `preview.spec.ts:188` left the cluster OPEN and
// took the next two tests down with it (3 failures, 1 cause).
//
// Collapsing here instead makes the restore unconditional, so a red test reports one
// defect rather than three. Idempotent: a no-op when the cluster is already collapsed.
test.afterEach(async () => {
  const win = await app?.firstWindow();
  if (!win) return;
  const toggle = win.locator('.tabbar__advanced-toggle');
  try {
    if ((await toggle.count()) === 0) return;
    if ((await toggle.getAttribute('aria-expanded')) === 'true') {
      await toggle.click({ timeout: 5_000 });
    }
  } catch {
    // Best-effort cleanup: never mask the real failure with a teardown error.
  }
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

  // Open the sample into the Workspace. Opening a video now lands on the
  // per-video Task Hub (WU-3a1); take the "Advanced / all tools" escape button
  // into the full Workspace, where <h1 class="workspace__title"> lives.
  await win.locator('.library__item-title', { hasText: 'sample' }).click();
  await win.locator('button.task-hub__advanced').click();
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

test('Advanced disclosure actually COLLAPSES the Deliver cluster (F17)', async () => {
  const win = await app.firstWindow();
  // Workspace is already open from the playback test, in its DEFAULT view:
  // Workspace.tsx seeds `advancedOpen = false`, and nothing on the route in
  // (library card -> task-hub "Advanced / all tools") ever opens the cluster.
  await expect(win.locator('.workspace')).toBeVisible();

  const toggle = win.locator('.tabbar__advanced-toggle');
  const panel = win.locator('.tabbar__advanced-panel');
  const deliverTab = win.locator('.tab[data-tab-id="tracks"]');

  // DETECTOR CONTROL (same element, mechanically independent of layout): the
  // panel EXISTS and React really wrote the `hidden` attribute onto it. So a
  // failure of the layout assertions below cannot come from a typo'd selector,
  // an unmounted panel, or React skipping `hidden` — the only remaining cause
  // is the CSS cascade. This is what makes the red below name the defect.
  await expect(panel).toHaveCount(1);
  await expect(panel).toHaveAttribute('hidden', '');

  // The disclosure REPORTS collapsed...
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  // ...so the cluster it owns must not paint. It does today: the author-origin
  // `display: flex` on `.tabbar--grouped .tabbar__advanced-panel` outranks the
  // UA `[hidden] { display: none }`, and no `[hidden]` selector anywhere under
  // app/ restores it — so all 21 tabs paint instead of 16 and `aria-expanded`
  // lies about what is on screen.
  await expect(panel).toBeHidden();
  await expect(deliverTab).toBeHidden();
  // The user-visible consequence: the default view paints the 16 primary tabs,
  // not all 21. (`.tab` is exclusive to this strip.)
  //
  // These two numbers are DERIVED, not observed — they are `WORKSPACE_TABS.length`
  // and that minus the `advanced: true` group's `tabIds.length`
  // (`Workspace.tsx`): 21 tabs total; Deliver holds 5 (convert, nle, recipes,
  // assets, tracks), so 16 paint while it is collapsed. They were 13/8 until the
  // v1.5 wave added `transcriptEdit`, `timeline`, `speed` and `audiomix`; e2e is
  // opt-in and nightly, so it never gated those PRs and the stale pair merged
  // four times over. It went 17/12 -> 19/14 when W17/W18 mounted `reframeFix`
  // and `videoTimeline` into the visible "Frame & Cut" cluster, updated here in
  // the SAME commit as `Workspace.test.tsx`'s "pins the strip counts" test —
  // that PR-gating test is the only reason this nightly pair is not stale again.
  // W19 took it 19/14 -> 20/15 by mounting `gaze` into that same visible cluster,
  // and W16-UI took it 20/15 -> 21/16 by mounting `broll` into it as well.
  // Re-derive from the source when the tab list changes — do NOT read a number
  // off a failing run and paste it back.
  await expect(win.locator('.tab')).toHaveCount(21);
  await expect(win.locator('.tab:visible')).toHaveCount(16);
  // ...and the disclosure's own toggle is reachable WITHOUT horizontally
  // scrolling `.workspace .tabbar` (workspace.css `overflow-x: auto`). With the
  // cluster always painted the strip overflowed its 1064px track by 587px and
  // pushed the toggle out of the window entirely, so the only control that could
  // collapse the cluster was itself off-screen.
  await expect(toggle).toBeInViewport();
  // NOW ASSERTED (v1.5 W17/W18). This used to read "deliberately NOT asserted:
  // `.tabbar__export` in-viewport", recording that at the default window
  // (innerWidth 1264) collapsing the cluster cut the strip's overflow from 587px
  // to 94px — restoring the toggle (x 1175..1268) but leaving Export starting at
  // x=1268, 4px past the right edge. Sticky only ever pinned the toggle.
  //
  // W17/W18 added two painted tabs, which would have pushed Export further out,
  // so the layout change that comment called for landed with them: the scrollport
  // moved from `.tabbar--grouped` onto `.tabbar__tablist` (workspace.css), which
  // puts BOTH right-hand controls outside the scrolling region at any tab count.
  // This assertion is the pin for that. It is RED in the pre-fix state by the
  // measurement quoted above (x=1268 > 1264).
  //
  // UNVERIFIED by the author of this change: e2e is nightly and needs a packaged
  // Electron build, which was not run here. Settling experiment: this test.
  await expect(win.locator('.tabbar__export')).toBeInViewport();

  // The disclosure still REVEALS when asked — pins that the fix scopes the rule
  // rather than deleting the cluster (passes before AND after the fix).
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(panel).toBeVisible();
  await expect(deliverTab).toBeVisible();

  // RESTORE the collapsed default. playwright.config.ts runs `fullyParallel:
  // false, workers: 1` against ONE app launched in `beforeAll`, so leaving the
  // cluster open would leak `advancedOpen === true` into the tests below and
  // hide whether THEY reveal it themselves.
  //
  // NOT redundant with the `afterEach` above, despite the overlap — keep both. This
  // pair ASSERTS that collapsing works; the afterEach only GUARANTEES the state is
  // restored even when an assertion above fails. Deleting either loses something.
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
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

  // "NLE export" (tab id `nle`, relabelled from "Timeline export" by the v1.5
  // timeline-naming lane) lives in the Deliver cluster, which is collapsed by
  // default — so REVEAL it first or Playwright's actionability gate cannot click
  // a `display:none` button. Use `.tabbar__export` (Workspace handleExport →
  // `setAdvancedOpen(true)`), which is IDEMPOTENT; the `.tabbar__advanced-toggle`
  // would flip the cluster shut on a second caller.
  await win.locator('.tabbar__export').click();
  // Switch to NLE export and assert the NleExport panel ITSELF mounted.
  await win.locator('button', { hasText: 'NLE export' }).first().click();
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
  // Reveal the Deliver cluster first (see the note above): this test must not
  // depend on a sibling test having left it open.
  await win.locator('.tabbar__export').click();
  await win.locator('button', { hasText: 'NLE export' }).first().click();
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
