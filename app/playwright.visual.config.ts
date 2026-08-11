import { defineConfig } from '@playwright/test';

// Playwright config for the Wave-2b VISUAL screenshot-diff + A11Y (axe) suite.
//
// Kept SEPARATE from playwright.config.ts (the 4-OS e2e-gui matrix) on purpose:
// the visual specs commit platform-specific screenshot baselines, so they run in
// ONE dedicated single-OS job (windows-latest — where the baselines are
// generated and committed as `*-win32.png`). The a11y/keyboard specs are
// DOM-based and OS-independent, but ride this same config/job to reuse the build.
//
// Both suites drive the REAL built Electron app + live Python sidecar via
// playwright._electron.launch (see e2e/visual/_visualSetup.ts) — no stubs. The
// build (npm run build) must have run first so app/out/main/main.js exists.
export default defineConfig({
  testDir: './e2e/visual',
  testMatch: '**/*.{visual,a11y}.spec.ts',
  // Electron cold-start + sidecar boot need headroom (mirrors the GUI config).
  timeout: 120_000,
  expect: {
    timeout: 30_000,
    // Default tolerance for any toHaveScreenshot that does not pass its own
    // (per-spec opts override this); absorbs AA/font-hinting sub-pixel noise.
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  // Visual baselines are inherently OS-specific; never auto-broaden the suffix.
  // Single worker: the specs share one launched app per file and snapshot
  // sequentially, so parallelism would only add render jitter.
  fullyParallel: false,
  workers: 1,
  // ── WHY THIS SUITE DOES NOT USE THE DEFAULT `test-results/` ────────────────
  // A visual failure is only actionable if you can SEE the `-actual.png` /
  // `-diff.png` Playwright writes beside the baseline. Those land in `outputDir`,
  // which BOTH this config and playwright.config.ts previously left at the
  // Playwright default — resolving to the SAME `app/test-results/` for both.
  //
  // Playwright REMOVES outputDir at the start of every run. MEASURED locally
  // (planted two marker files under app/test-results/, ran a second Playwright
  // invocation whose outputDir pointed at the same directory, exit 0 / 1 passed):
  // marker present BEFORE = true, present AFTER = false — the whole subtree was
  // deleted. So any LATER Playwright step in the same CI job silently destroys
  // this suite's failure images before the upload at the end of the job.
  //
  // That is not hypothetical. Actions run 31445248586: step "E2E GUI — VISUAL
  // screenshot-diff + A11Y" went red (18 passed, 1 failed —
  // `workspace-preview-win32.png`), then the later `installed-app` step ran
  // (it carries `!cancelled()`, so an earlier red does not skip it) with
  // playwright.config.ts and wiped app/test-results/. The uploaded
  // `e2e-gui-playwright-report-windows-latest` artifact therefore contained ZERO
  // png files — only two `error-context.md`, both from `installed-app`. The
  // visual regression was undiagnosable without re-running it locally.
  //
  // A dedicated sibling directory is untouched by any OTHER config's cleanup.
  //
  // Scoped honestly: it is NOT untouched by THIS config. The REGEN step
  // (e2e.yml, "VISUAL baseline REGEN (--update-snapshots)") re-runs this very
  // config, so it removes this directory too. That costs nothing, because the
  // two steps are MUTUALLY EXCLUSIVE by their guards — the gate step requires
  // `update_visual_baselines != 'true'` and REGEN requires `== 'true'`, so on a
  // regen dispatch no diff has been produced for REGEN to destroy.
  outputDir: './test-results-visual',
  // The `list` reporter is what the CI log shows; the `html` reporter is what
  // makes a red diff DIAGNOSABLE — for a toHaveScreenshot failure it embeds the
  // expected/actual/diff triple as attachments COPIED into its own folder, so the
  // report stays complete even if outputDir is later removed.
  //
  // It is written INSIDE `app/playwright-report/` on purpose: e2e.yml's existing
  // "Upload Playwright report" step already uploads that whole tree with
  // `if: always()`, so this is diagnosable through that upload alone — and today
  // nothing else wipes it, because playwright.config.ts configures no html
  // reporter and a reporter only cleans its own outputFolder.
  //
  // ⚠ THAT LAST CLAUSE IS A TRAP FOR THE NEXT EDITOR. Playwright's html reporter
  // defaults its outputFolder to `playwright-report` — the PARENT of this one. So
  // adding a bare `['html']` to playwright.config.ts would clean
  // `app/playwright-report/` wholesale and take `visual/` with it, on steps that
  // run AFTER the visual gate. MEASURED: a second config whose html outputFolder
  // was the parent left `report/visual/index.html` absent and `data/` empty.
  // A GUI report may only sit beside this one as an EXPLICIT sibling —
  // `['html', { outputFolder: 'playwright-report/gui' }]` — never a bare `['html']`.
  // `open: 'never'` so a local red run does not try to spawn a browser.
  reporter: [['list'], ['html', { outputFolder: 'playwright-report/visual', open: 'never' }]],
  use: {
    trace: 'off',
  },
});
