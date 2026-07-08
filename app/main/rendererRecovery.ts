// rendererRecovery.ts — pure decision/log helpers for main-process renderer
// crash + load-failure recovery (WU2 resilience, defense-in-depth).
//
// The renderer's own <ErrorBoundary> catches errors thrown DURING React render,
// but it cannot recover a process-level failure: a crashed/OOM'd render process,
// a failed initial load of index.html, or an uncaught exception / unhandled
// rejection in the MAIN process. main.ts wires the Electron events
// (render-process-gone / did-fail-load) + process handlers to these helpers; the
// wiring is a thin IO seam (main/** is coverage-excluded), so every DECISION and
// log string lives HERE where it is unit-tested to 100%.

/** Recovery cap: reload a crashed/blank renderer at most this many times before
 *  giving up, so a persistently-broken bundle never becomes an infinite reload
 *  storm (the loud logs still tell the user what failed). */
export const MAX_RENDERER_RELOADS = 3;

/** Chromium's ERR_ABORTED — a benign superseded navigation, never a real failure. */
const ERR_ABORTED = -3;

/** The subset of Electron's RenderProcessGoneDetails we decide on. */
export interface RenderProcessGoneInfo {
  /** 'clean-exit' | 'crashed' | 'oom' | 'killed' | 'launch-failed' | 'integrity-failure' | 'abnormal-exit'. */
  reason: string;
  exitCode: number;
}

/** The subset of a did-fail-load event we decide on. */
export interface DidFailLoadInfo {
  errorCode: number;
  errorDescription: string;
  validatedURL: string;
  isMainFrame: boolean;
}

/** A recovery decision: whether to reload, plus the actionable log line. */
export interface RecoveryDecision {
  /** Reload the window to recover a blanked/crashed renderer. */
  reload: boolean;
  /** The log line (what happened + what we are doing about it). */
  log: string;
}

/**
 * Decide how to handle a gone render process. A clean, intentional exit needs no
 * recovery; any other reason (crashed/oom/killed/launch-failed/integrity-failure/
 * abnormal-exit) blanked the window, so reload it — but only up to
 * {@link MAX_RENDERER_RELOADS} to avoid a reload storm on a persistently-broken
 * bundle. `priorReloads` is the count of recovery reloads already performed.
 */
export function decideRenderProcessGone(
  info: RenderProcessGoneInfo,
  priorReloads: number,
): RecoveryDecision {
  if (info.reason === 'clean-exit') {
    return {
      reload: false,
      log: `[recover] render process exited cleanly (exitCode=${info.exitCode}) — no reload`,
    };
  }
  const where = `reason=${info.reason}, exitCode=${info.exitCode}`;
  if (priorReloads >= MAX_RENDERER_RELOADS) {
    return {
      reload: false,
      log: `[recover] render process gone (${where}) — reload limit (${MAX_RENDERER_RELOADS}) reached, not reloading`,
    };
  }
  return {
    reload: true,
    log: `[recover] render process gone (${where}) — reloading the window (attempt ${priorReloads + 1}/${MAX_RENDERER_RELOADS})`,
  };
}

/**
 * Decide how to handle a did-fail-load. A SUBFRAME failure, or the benign
 * ERR_ABORTED (-3, e.g. a superseded navigation), is ignored; a MAIN-frame
 * failure with a real error code blanked the app, so reload — capped at
 * {@link MAX_RENDERER_RELOADS} to avoid a reload storm.
 */
export function decideDidFailLoad(info: DidFailLoadInfo, priorReloads: number): RecoveryDecision {
  if (!info.isMainFrame || info.errorCode === ERR_ABORTED) {
    return {
      reload: false,
      log: `[recover] ignoring load failure (code=${info.errorCode} ${info.errorDescription}, mainFrame=${info.isMainFrame})`,
    };
  }
  const what = `code=${info.errorCode} ${info.errorDescription}`;
  if (priorReloads >= MAX_RENDERER_RELOADS) {
    return {
      reload: false,
      log: `[recover] main-frame load failed (${what}) — reload limit (${MAX_RENDERER_RELOADS}) reached, not reloading`,
    };
  }
  return {
    reload: true,
    log: `[recover] main-frame load failed (${what}, url=${info.validatedURL}) — reloading (attempt ${priorReloads + 1}/${MAX_RENDERER_RELOADS})`,
  };
}

/** Diagnostic detail for a thrown value (Error stack/message, else String()). */
function detail(value: unknown): string {
  return value instanceof Error ? (value.stack ?? value.message) : String(value);
}

/**
 * The log line for a main-process uncaughtException. main.ts logs this and keeps
 * the process ALIVE rather than letting Node's default handler exit — a single
 * stray throw (e.g. in an async callback) must not tear down the whole app.
 */
export function describeUncaughtException(err: unknown): string {
  return `[fatal] uncaughtException (kept alive): ${detail(err)}`;
}

/**
 * The log line for a main-process unhandledRejection. main.ts logs this and keeps
 * the process alive rather than crashing on an unobserved promise rejection.
 */
export function describeUnhandledRejection(reason: unknown): string {
  return `[fatal] unhandledRejection (kept alive): ${detail(reason)}`;
}
