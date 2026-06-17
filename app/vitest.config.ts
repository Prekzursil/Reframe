import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

// Vitest config for the app (renderer + main) gate (CONTRACTS.md gate:3).
//
// Per-test `// @vitest-environment jsdom` directives select the DOM env for
// renderer component tests; main-process tests run in the default node env.
//
// Coverage: v8 provider, STRICT 100% line + branch + function + statement
// thresholds for the renderer (the gate is clean-zero everywhere — sidecar AND
// renderer; see QUALITY-CHARTER.md gate:3). The HYBRID/ratchet floor policy that
// briefly governed the UI has been retired: every renderer source file is held to
// 100%. Genuinely-untestable lines (the few runtime-only defensive guards) are
// marked inline with `/* v8 ignore … -- <reason> */` so the threshold stays
// honest, never blanket-ignored.
//
// Coverage scope is the renderer (`renderer/src/**`). The Electron MAIN process
// (`main/**`) is bootstrap/IPC wiring that only exercises against a real
// BrowserWindow at runtime; its unit tests still RUN (see test.include below) but
// it is not part of the renderer's 100% coverage gate.
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
      include: ['renderer/src/**/*.{ts,tsx}'],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.d.ts',
        // Pure re-export barrels (no logic to cover).
        'renderer/src/components/index.ts',
        // Browser entry point: mounts <App/> into the DOM via ReactDOM; runs only
        // in the packaged renderer, not under jsdom unit tests.
        'renderer/src/main.tsx',
      ],
      // STRICT 100% — the renderer is fully covered.
      thresholds: {
        lines: 100,
        branches: 100,
        functions: 100,
        statements: 100,
      },
    },
  },
});
