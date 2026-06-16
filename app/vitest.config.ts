import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

// Vitest config for the app (renderer + main) gate (CONTRACTS.md gate:3).
//
// Per-test `// @vitest-environment jsdom` directives select the DOM env for
// renderer component tests; main-process tests run in the default node env.
//
// Coverage: v8 provider, 100% line + branch thresholds (the gate is clean-zero).
// Genuinely-untestable lines (Electron app bootstrap that needs a real BrowserWindow,
// IPC wiring exercised only at runtime) are marked inline with
// `/* v8 ignore … -- <reason> */` so the threshold stays honest, not blanket-ignored.
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
      thresholds: {
        lines: 100,
        branches: 100,
        functions: 100,
        statements: 100,
      },
    },
  },
});
