import { defineConfig } from '@playwright/test';

// Playwright config for the Reframe Electron GUI E2E (chore/e2e-gui).
//
// Single project: the spec launches the REAL built Electron app via
// playwright._electron.launch (no browser project / webServer needed). The
// build (npm run build, or `electron-vite build` for the preview-only path)
// must have run first so app/out/main/main.js exists.
export default defineConfig({
  testDir: './e2e',
  // Only Playwright specs. The e2e/*.test.tsx files are vitest DOM proofs
  // (run via vitest.e2e.config.ts), not Playwright tests.
  testMatch: '**/*.spec.ts',
  // Electron cold-start + sidecar boot + real video decode need headroom.
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    trace: 'off',
  },
});
