/**
 * BUILD-TIME ONLY: bundle the vendored Remotion compositions.
 *
 * Invoked by the `bundle` package script (`npm run bundle` inside
 * app/render-cli) as part of the APP build — NEVER at runtime. render.ts
 * deliberately does not import @remotion/bundler; the bundle/render
 * separation is structural.
 *
 * Output: app/render-cli/out/remotion-bundle (the `bundleDir` the sidecar
 * writes into render job files).
 */
import * as path from 'path';
import { bundle } from '@remotion/bundler';
import type { WebpackOverrideFn } from '@remotion/bundler';

// dist/bundle.js lives in app/render-cli/dist -> one level up is the package.
const RENDER_CLI_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(RENDER_CLI_DIR, '..', '..');

const VENDOR_DIR = path.join(REPO_ROOT, 'vendor', 'remotion-captions');
const ENTRY_POINT = path.join(VENDOR_DIR, 'src', 'index.ts');
const PUBLIC_DIR = path.join(VENDOR_DIR, 'public');
const OUT_DIR = path.join(RENDER_CLI_DIR, 'out', 'remotion-bundle');

/**
 * The vendored sources live OUTSIDE this package (vendor/remotion-captions),
 * so webpack's default node_modules walk-up from the vendor dir would miss
 * app/render-cli/node_modules where remotion/react actually live. Prepend it.
 */
const withRenderCliModules: WebpackOverrideFn = (config) => ({
  ...config,
  resolve: {
    ...config.resolve,
    modules: [
      path.join(RENDER_CLI_DIR, 'node_modules'),
      'node_modules',
      ...(config.resolve?.modules ?? []),
    ],
  },
});

async function main(): Promise<void> {
  process.stdout.write(`BUNDLE_START ${ENTRY_POINT}\n`);
  const serveUrl = await bundle({
    entryPoint: ENTRY_POINT,
    outDir: OUT_DIR,
    publicDir: PUBLIC_DIR,
    webpackOverride: withRenderCliModules,
    onProgress: (progress: number) => {
      process.stdout.write(`BUNDLE_PROGRESS ${progress}\n`);
    },
  });
  process.stdout.write(`BUNDLE_OK ${serveUrl}\n`);
}

main().catch((err: unknown) => {
  const message = err instanceof Error ? err.message : String(err);
  process.stderr.write(`BUNDLE_FAIL ${message}\n`);
  process.exit(1);
});
