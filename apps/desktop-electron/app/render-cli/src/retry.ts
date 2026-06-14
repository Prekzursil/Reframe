/**
 * Transient-failure retry helper for the render CLI (robustness under batch load).
 *
 * Headless Chromium dies under sustained/parallel load — rendering N clips in a
 * row crashed mid-batch with "Could not extract frame from compositor" /
 * "Error: Request closed" (the compositor/browser process exiting from resource
 * exhaustion). These are TRANSIENT: a fresh browser + compositor on the next
 * attempt usually succeeds. This module isolates (a) the signature matcher and
 * (b) the retry loop as pure, unit-testable functions so render.ts stays a thin
 * orchestrator.
 *
 * Pairs with the belt-and-suspenders subprocess-level retry in the Python
 * sidecar (features/caption_remotion.py): render.ts retries the renderMedia call
 * in-process; the sidecar retries the whole CLI process once if it still exits
 * non-zero with a transient signature.
 */

/**
 * stderr/error substrings that signal a transient headless-Chromium / compositor
 * death — recoverable by re-running with a fresh browser. Matched
 * case-insensitively against the error message. Keep in sync with
 * TRANSIENT_SIGNATURES in sidecar/media_studio/features/caption_remotion.py.
 */
export const TRANSIENT_SIGNATURES: readonly string[] = [
  "Request closed",
  "Could not extract frame from compositor",
  "Target closed",
  "Navigation failed",
  "Session closed",
  "Protocol error",
  "WebSocket is not open",
];

/** Default number of render attempts (1 initial + up to 2 retries). */
export const MAX_RENDER_ATTEMPTS = 3;

/** Base backoff in ms between attempts (multiplied by the attempt number). */
export const RETRY_BACKOFF_MS = 750;

/** Extract a readable message from an unknown thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof Error) {
    // Include the stack when present — the compositor signature sometimes lives
    // in the stack rather than the top-line message.
    return `${err.message}\n${err.stack ?? ""}`;
  }
  return String(err);
}

/**
 * True when the error message contains a known transient-compositor signature
 * (so a fresh-browser retry is worth attempting). Case-insensitive.
 */
export function isTransientCompositorError(err: unknown): boolean {
  const haystack = errorMessage(err).toLowerCase();
  return TRANSIENT_SIGNATURES.some((sig) => haystack.includes(sig.toLowerCase()));
}

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

export interface RetryOptions {
  maxAttempts?: number;
  backoffMs?: number;
  /** Injected for tests; defaults to real setTimeout-backed sleep. */
  delay?: (ms: number) => Promise<void>;
  /** Called once per failed-but-retryable attempt (e.g. to log). */
  onRetry?: (attempt: number, err: unknown) => void;
}

/**
 * Run `fn` up to `maxAttempts` times. Retries ONLY transient compositor errors
 * (per {@link isTransientCompositorError}); any other error is re-thrown
 * immediately. A short, attempt-scaled backoff separates attempts. `fn` receives
 * the 1-based attempt number so callers can build a fresh browser/compositor per
 * attempt. On exhaustion the last error is re-thrown so the caller exits
 * non-zero with the captured message (the Python side then surfaces it).
 */
export async function withCompositorRetry<T>(
  fn: (attempt: number) => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const maxAttempts = options.maxAttempts ?? MAX_RENDER_ATTEMPTS;
  const backoffMs = options.backoffMs ?? RETRY_BACKOFF_MS;
  const delay = options.delay ?? sleep;

  let lastErr: unknown;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (err: unknown) {
      lastErr = err;
      const retryable = isTransientCompositorError(err);
      if (!retryable || attempt >= maxAttempts) {
        throw err;
      }
      if (options.onRetry) {
        options.onRetry(attempt, err);
      }
      await delay(backoffMs * attempt);
    }
  }
  // Unreachable (the loop either returns or throws), but satisfies the compiler.
  throw lastErr;
}
