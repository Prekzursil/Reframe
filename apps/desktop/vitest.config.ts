import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov", "json-summary"],
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts"],
      // Strict 100% across all axes (matches the web app + Python coverage gate).
      // NOTE: branch was previously 0 (disabled); raising it to 100 surfaces the
      // Tauri IPC / updater platform branches in main.ts that are not yet exercised.
      thresholds: {
        lines: 100,
        functions: 100,
        branches: 100,
        statements: 100,
      },
    },
  },
});
