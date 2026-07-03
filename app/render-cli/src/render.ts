/**
 * RUNTIME render CLI (T4a).
 *
 * Spawned by the Python sidecar (features/caption_remotion.py) as:
 *
 *     [<node-runner exe>, render.js, <job.json>]      (argv list, no shell)
 *
 * with ELECTRON_RUN_AS_NODE=1 in the environment, so the packaged Electron
 * exe behaves as plain Node (per CONTRACTS.md A4). The job file:
 *
 *     {
 *       "bundleDir": "<path to the pre-built remotion bundle>",
 *       "composition": "CaptionedClip",
 *       "inputProps": { videoSrc, cues, style, width, height, durationInSeconds },
 *       "outPath": "<output .mp4>",
 *       "chromiumExecutable": "<optional Chrome Headless Shell path>"
 *     }
 *
 * Protocol on stdout (parsed by the sidecar):
 *   RENDER_PROGRESS <0-100>   — streamed while rendering
 *   RENDER_OK <outPath>       — printed exactly once on success
 * Failures print RENDER_FAIL <message> to stderr and exit non-zero.
 *
 * NOTE: this module must NEVER import @remotion/bundler — bundling happens at
 * app-build time only (see bundle.ts). The bundle/render separation is
 * structural, not conventional.
 */
import * as fs from 'fs';
import * as http from 'http';
import * as path from 'path';
import type { AddressInfo } from 'net';
import type { ChromiumOptions } from '@remotion/renderer';
import { renderMedia, selectComposition } from '@remotion/renderer';
import { ensureWithinBase } from './jobPath';
import { errorMessage, withCompositorRetry } from './retry';

export interface RenderJob {
  bundleDir: string;
  composition: string;
  inputProps: Record<string, unknown>;
  outPath: string;
  chromiumExecutable?: string | null;
}

/** Read + validate the job file. Throws with a precise message on bad shape. */
export function readJob(jobPath: string): RenderJob {
  if (!jobPath) {
    throw new Error('usage: render.js <job.json>');
  }
  // Path-injection barrier (CodeQL js/path-injection), two layers, defence in
  // depth. Layer 1 (fast structural reject): a NUL-poisoned path or any explicit
  // parent-directory (`..`) segment is refused up front.
  if (jobPath.includes('\0') || jobPath.split(/[\\/]+/).includes('..')) {
    throw new Error('job path must not contain a NUL byte or parent-directory traversal');
  }
  // Layer 2 (confine-to-base sanitizer, the TS analog of the sidecar's
  // pathsafe.ensure_within): canonicalise the path and PROVE it stays inside
  // os.tmpdir() — where the Python side writes it via tempfile.mkstemp (see
  // caption_remotion.py). CodeQL recognises this `path.resolve` + `startsWith`
  // barrier, so `safePath` (the resolved return value) is a sanitised source for
  // the readFileSync sink below.
  const safePath = ensureWithinBase(jobPath);
  const raw = fs.readFileSync(safePath, 'utf-8');
  const parsed: unknown = JSON.parse(raw);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error('job file must contain a JSON object');
  }
  const job = parsed as Record<string, unknown>;
  for (const key of ['bundleDir', 'composition', 'outPath'] as const) {
    if (typeof job[key] !== 'string' || job[key] === '') {
      throw new Error(`job.${key} (non-empty string) is required`);
    }
  }
  const inputProps = job.inputProps;
  if (typeof inputProps !== 'object' || inputProps === null || Array.isArray(inputProps)) {
    throw new Error('job.inputProps (object) is required');
  }
  const chromiumExecutable = job.chromiumExecutable;
  if (
    chromiumExecutable !== undefined &&
    chromiumExecutable !== null &&
    typeof chromiumExecutable !== 'string'
  ) {
    throw new Error('job.chromiumExecutable must be a string when present');
  }
  return {
    bundleDir: job.bundleDir as string,
    composition: job.composition as string,
    inputProps: inputProps as Record<string, unknown>,
    outPath: job.outPath as string,
    chromiumExecutable: (chromiumExecutable as string | null | undefined) ?? null,
  };
}

const isHttpUrl = (value: string): boolean => /^https?:\/\//i.test(value);

/**
 * Serve ONE local file over loopback HTTP. Remotion's renderer proxy does not
 * support file:// URLs (proven upstream gotcha), so a local-path videoSrc is
 * rewritten to http://127.0.0.1:<port>/<basename> before rendering.
 */
export function serveLocalFile(filePath: string): Promise<{ url: string; close: () => void }> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      // Single-file server: every request streams the one file.
      if (!fs.existsSync(filePath)) {
        res.writeHead(404);
        res.end('Not found');
        return;
      }
      res.writeHead(200, { 'Content-Type': 'video/mp4' });
      fs.createReadStream(filePath).pipe(res);
    });
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      const name = encodeURIComponent(path.basename(filePath));
      resolve({
        url: `http://127.0.0.1:${port}/${name}`,
        close: () => server.close(),
      });
    });
  });
}

async function main(): Promise<void> {
  const job = readJob(process.argv[2]);

  let closeServer: (() => void) | null = null;
  try {
    // Rewrite a local-path videoSrc to a loopback HTTP URL.
    const inputProps: Record<string, unknown> = { ...job.inputProps };
    const videoSrc = inputProps.videoSrc;
    if (typeof videoSrc === 'string' && videoSrc !== '' && !isHttpUrl(videoSrc)) {
      if (!fs.existsSync(videoSrc)) {
        throw new Error(`videoSrc file not found: ${videoSrc}`);
      }
      const served = await serveLocalFile(videoSrc);
      closeServer = served.close;
      inputProps.videoSrc = served.url;
    }

    // Explicit Chrome Headless Shell when the job provides one; otherwise let
    // @remotion/renderer resolve its own browser.
    const browserExecutable = job.chromiumExecutable ?? null;

    // Conservative Chromium settings for sustained/batch load. The mid-batch
    // crash ("Could not extract frame from compositor" / "Request closed") is
    // headless Chromium dying from resource exhaustion. Software GL ("angle")
    // avoids GPU/driver contention that bites under repeated headless renders.
    const chromiumOptions: ChromiumOptions = { gl: 'angle' };

    fs.mkdirSync(path.dirname(path.resolve(job.outPath)), { recursive: true });

    // Retry the WHOLE render (fresh selectComposition + renderMedia => fresh
    // browser + compositor each attempt) on transient compositor deaths. A
    // non-transient error (bad bundle, missing composition, etc.) is re-thrown
    // immediately. On exhaustion the last error propagates -> non-zero exit.
    await withCompositorRetry(
      async (attempt) => {
        if (attempt > 1) {
          process.stderr.write(`RENDER_RETRY attempt ${attempt} (fresh browser)\n`);
        }

        // selectComposition resolves calculateMetadata (duration/size from
        // props) and opens its own browser — done inside the retry so a
        // compositor death here is also recovered with a fresh browser.
        const composition = await selectComposition({
          serveUrl: job.bundleDir,
          id: job.composition,
          inputProps,
          browserExecutable,
          chromiumOptions,
        });

        let lastPct = -1;
        await renderMedia({
          composition,
          serveUrl: job.bundleDir,
          codec: 'h264',
          crf: 18,
          outputLocation: job.outPath,
          inputProps,
          browserExecutable,
          chromiumOptions,
          // One tab only: the crash is resource exhaustion from parallel tabs.
          concurrency: 1,
          onProgress: ({ progress }) => {
            const pct = Math.floor(progress * 100);
            if (pct > lastPct) {
              lastPct = pct;
              process.stdout.write(`RENDER_PROGRESS ${pct}\n`);
            }
          },
        });
      },
      {
        onRetry: (attempt, err) => {
          process.stderr.write(
            `RENDER_TRANSIENT attempt ${attempt} failed: ${errorMessage(err)}\n`,
          );
        },
      },
    );

    process.stdout.write(`RENDER_OK ${job.outPath}\n`);
  } finally {
    if (closeServer) {
      closeServer();
    }
  }
}

main()
  .then(() => {
    process.exit(0);
  })
  .catch((err: unknown) => {
    const message = err instanceof Error ? err.message : String(err);
    process.stderr.write(`RENDER_FAIL ${message}\n`);
    process.exit(1);
  });
