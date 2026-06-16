import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

// Vitest config for the app (renderer + main) gate (CONTRACTS.md gate:3).
//
// Per-test `// @vitest-environment jsdom` directives select the DOM env for
// renderer component tests; main-process tests run in the default node env.
//
// Coverage: v8 provider. Per the HYBRID coverage policy (2026-06-16): the sidecar
// ENGINE is held to 100% (the logic that matters), while the Electron/renderer UI
// uses a RATCHET floor — these thresholds are the current measured coverage, so the
// gate can never REGRESS and every change must hold or raise the bar (new UI code
// must be tested), without forcing low-value 100% on runtime-only view glue.
// Raise these floors whenever UI test coverage climbs. Genuinely-untestable lines
// (Electron app bootstrap needing a real BrowserWindow, runtime-only IPC wiring) are
// still marked inline with `/* v8 ignore … -- <reason> */`, not blanket-ignored.
export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'renderer/src'),
    },
  },
  test: {
    globals: true,
    include: ['main/**/*.test.{ts,tsx}', 'renderer/src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary'],
      include: ['main/**/*.{ts,tsx}', 'renderer/src/**/*.{ts,tsx}'],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.d.ts',
        // Pure re-export barrels (no logic to cover).
        'renderer/src/components/index.ts',
        // Browser entry point: mounts <App/> into the DOM via ReactDOM; runs only
        // in the packaged renderer, not under jsdom unit tests.
        'renderer/src/main.tsx',
      ],
      // RATCHET floors (current measured UI coverage; raise as tests are added).
      thresholds: {
        lines: 78,
        branches: 84,
        functions: 70,
        statements: 78,
      },
    },
  },
});
