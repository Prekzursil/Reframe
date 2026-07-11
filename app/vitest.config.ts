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
    // The render-cli is a separate commonjs workspace, but it has no test runner
    // of its own; its pure-logic unit tests (e.g. the js/path-injection barrier in
    // jobPath.ts) live beside the code and run under THIS vitest. They default to
    // the node environment and are NOT part of the renderer's 100% coverage gate
    // (coverage.include below is renderer-only).
    include: [
      'main/**/*.test.{ts,tsx}',
      'renderer/src/**/*.test.{ts,tsx}',
      'render-cli/src/**/*.test.ts',
    ],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'text-summary'],
      // The renderer is fully gated. WU-U2 also promotes the P0 auto-update
      // AUTHENTICITY verifier + its wiring into the 100% bar: `main/**` otherwise
      // runs its tests but is NOT threshold-gated, and these two files are
      // security-critical and fully unit-testable via injected fakes, so they must
      // never silently regress below full branch coverage. The rest of `main/**`
      // (BrowserWindow/IPC bootstrap that needs a real runtime) stays ungated.
      include: [
        'renderer/src/**/*.{ts,tsx}',
        'main/updateVerify.ts',
        'main/updater.ts',
      ],
      exclude: [
        '**/*.test.{ts,tsx}',
        '**/*.d.ts',
        // Pure re-export barrels (no logic to cover).
        'renderer/src/components/index.ts',
        'renderer/src/lib/rpc/index.ts',
        // Generated contract artifacts (v1.5 schema-first RPC POC): verified by
        // regeneration + the parity tests, not by hand-written line coverage.
        // Regenerate via `python -m contract.generate` (see docs/rpc-contract-v2.md).
        'renderer/src/lib/rpc/generated/**',
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
