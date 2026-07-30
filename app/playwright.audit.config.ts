import { defineConfig } from '@playwright/test';

// Playwright config for the ON-DEMAND functional audit sweep (e2e/audit/**).
//
// Deliberately SEPARATE from playwright.config.ts: the sweep clicks every
// interactive control on every surface with a per-control observation window, so
// it runs for many minutes. It is an investigation tool, not a PR gate, and the
// main 4-OS `e2e-gui` matrix must not inherit that cost. Run it explicitly:
//
//   npx playwright test --config playwright.audit.config.ts
//
// It drives the same real built Electron app + live sidecar as the other specs
// (via e2e/fixtures.ts), so its findings are about the shipped product.
export default defineConfig({
  testDir: './e2e',
  testMatch: 'audit/**/*.spec.ts',
  // The whole sweep is one test: cold start + N controls x (noise + click +
  // re-navigate). Generous, because a timeout here loses the entire report.
  timeout: 45 * 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { trace: 'off' },
});
