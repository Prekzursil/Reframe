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
  reporter: [['list']],
  use: {
    trace: 'off',
  },
});
