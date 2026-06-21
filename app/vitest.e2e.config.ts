import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

// Separate vitest config for the DOM-level E2E complement (e2e/*.test.tsx).
//
// Kept OUT of the main vitest.config.ts (which enforces strict 100% coverage on
// renderer/src/**) so these E2E-labelled component+DOM checks do not perturb the
// renderer coverage gate. No coverage thresholds here — these are E2E proofs,
// not unit coverage.
export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'renderer/src'),
    },
  },
  test: {
    globals: true,
    include: ['e2e/**/*.test.{ts,tsx}'],
  },
});
