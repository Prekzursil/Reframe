// Shared local view of the FROZEN IPC surface + data schemas for the feature
// panels (Transcribe / Subtitles / Tracks / Convert).
//
// CONTRACT-NOTE: `lib/rpc.ts` (the typed client over window.api) and a shared
// renderer types module are owned by OTHER units and do not exist yet at
// authoring time. The feature panels are self-contained and consume the FROZEN
// `window.api` surface directly (CONTRACTS.md §1/§2:
// `window.api.rpc(method, params)` + `window.api.onProgress(cb)`). This file
// re-declares only the minimal types they need, matching the field names in
// CONTRACTS.md §3 EXACTLY.
//
// CONTRACT-NOTE: this module deliberately does NOT `declare global { interface
// Window { api } }`. A sibling unit (ShortMaker.tsx) augments `Window.api` with
// its own structurally-different shape (its progress `message` is optional),
// and TWO differing `interface Window` augmentations in one compilation collide
// (TS2717 "Subsequent property declarations must have the same type"). Since we
// must not edit another unit's file, the panels reach the bridge through the
// `getApi()` accessor below, which casts `window.api` to our local interface in
// one place. No global merge => no cross-unit collision, panels stay typed.

// F1: the shared job wait reuses the SINGLE A3 error-payload reader so error
// detection stays identical everywhere (no per-panel `doneErrorMessage` copies).
import { extractJobError } from '../components/useJob';

// --- Frozen IPC surface (CONTRACTS.md §1/§2) -----------------------------
// §2 progress notification params are `{jobId, pct, message}`.
export interface ProgressEvent {
  jobId: string;
  pct: number;
  message: string;
}

// §2 job.done notification params are `{jobId, result}`.
export interface DoneEvent {
  jobId: string;
  result?: unknown;
}

/**
 * Default `job.done` wait timeout (F2). A dead/wedged sidecar must NOT hang a
 * panel forever — every job wait is raced against this ceiling. 15 minutes is
 * long enough for the longest real job (a batch export) yet short enough that a
 * silent sidecar death surfaces a user-facing error instead of a frozen UI.
 */
export const DEFAULT_JOB_TIMEOUT_MS = 15 * 60 * 1000;

/**
 * Rejection raised when a `waitForJobDone` wait is torn down via its
 * `AbortSignal` (the caller cancelled the job or the panel unmounted, F2). It is
 * NOT a job failure — callers detect it and reset to idle WITHOUT surfacing an
 * error toast/banner (a cancel is a clean escape, not an error).
 */
export class JobAbortedError extends Error {
  constructor(message = 'Job wait aborted (cancelled or unmounted).') {
    super(message);
    this.name = 'JobAbortedError';
  }
}

export interface MediaStudioApi {
  /** Forward a JSON-RPC request to the sidecar; resolves with the result. */
  rpc: <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>;
  /** Subscribe to `job.progress` notifications; returns an unsubscribe fn. */
  onProgress: (cb: (ev: ProgressEvent) => void) => () => void;
  /**
   * Subscribe to `job.done` notifications; returns an unsubscribe fn. Present on
   * the real preload bridge (preload.ts exposes it). Optional here so a test
   * stub that omits it still satisfies the type.
   */
  onJobDone?: (cb: (ev: DoneEvent) => void) => () => void;
  /** Optional (P4 §6) — reveal a path in the OS file explorer (true on success). */
  openInFolder?: (path: string) => Promise<boolean>;
  /** Optional (P4 8d) — native single-select brand-logo picker (null when cancelled). */
  pickLogoFile?: () => Promise<string | null>;
}

/**
 * Typed accessor for the preload-exposed bridge. The single cast lives here so
 * the panels never touch `window` directly and we avoid a global `Window.api`
 * augmentation that would clash with the parallel ShortMaker unit's own.
 */
export function getApi(): MediaStudioApi {
  const api = (globalThis as unknown as { api?: unknown }).api;
  return api as MediaStudioApi;
}

// --- Frozen data schemas (CONTRACTS.md §3) -------------------------------
export interface Word {
  text: string;
  start: number;
  end: number;
}
export interface Segment {
  start: number;
  end: number;
  text: string;
  words: Word[];
}
export interface Transcript {
  language: string;
  segments: Segment[];
  durationSec: number;
}

export interface Cue {
  index: number;
  start: number;
  end: number;
  text: string;
}

export type SubtitleFormat = 'srt' | 'ass' | 'vtt';
export type TrackKind = 'soft' | 'hard';

export interface SubtitleTrack {
  id: string;
  lang: string;
  name: string;
  format: SubtitleFormat;
  kind: TrackKind;
  cues: Cue[];
}

// --- Convert options (CONTRACTS.md §2: convert.start options) ------------
export interface ConvertOptions {
  container: string;
  vcodec: string;
  acodec: string;
  scale: string;
  fps: string;
  crf: string;
  audioOnly: boolean;
  audioFormat: string;
}

export interface ConvertBatchItem {
  videoId?: string;
  path?: string;
  options: ConvertOptions;
}

/** Format seconds as M:SS for compact progress/label display. */
export function fmtSeconds(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

// CONTRACT-NOTE: long-job transport (CONTRACTS.md §2). A long job resolves the
// rpc `id` IMMEDIATELY with `{jobId}` only (sidecar.ts resolves on the id
// response, rpc.py:122); the terminal payload arrives later as a separate
// `job.done` notification (`{method:"job.done",params:{jobId,result}}`). So for
// the job-based methods (transcribe.start, subtitles.translate, tracks.burn,
// convert.start/batch) a panel MUST subscribe to `job.done` (via `onJobDone`)
// to read the result — reading it off the immediate rpc resolution always yields
// `undefined`. `waitForJobDone` below implements that wait (copied from the
// working ShortMaker.tsx pattern). The fast/direct methods (library.*, project.*,
// subtitles.generate/edit/export, tracks.list/rename/relabel/add/remove/strip,
// settings.*) resolve their full result on the rpc promise — no job, read it
// directly. `extractJobId` pulls the still-running jobId for progress/cancel.
export function extractJobId(res: unknown): string | undefined {
  if (res && typeof res === 'object' && 'jobId' in res) {
    const id = (res as { jobId?: unknown }).jobId;
    if (typeof id === 'string') return id;
  }
  return undefined;
}

/** Minimal bridge surface `waitForJobDone` needs — any `window.api` shape satisfies it. */
export interface JobDoneCapable {
  onJobDone?: (cb: (ev: DoneEvent) => void) => () => void;
}

/**
 * Wait for the `job.done` notification matching `jobId` and pull the terminal
 * payload out of `result` with `extract`. Resolves `null` if the bridge exposes
 * no `onJobDone` hook (then the rpc promise was the only channel and only
 * carried the `{jobId}` handle).
 *
 * Hardened for Lane 0 F1+F2 — the ONE shared wait for all deferred-job panels:
 *  - **F1 error surfacing:** a failed job arrives as `result:{error:{message,
 *    type}}` (jobs.py `_finish_error`). We REJECT with that message so the
 *    caller's `catch` shows a real error — never a silent empty "success".
 *    Reuses {@link extractJobError}. A `type==='JobCancelled'` payload is a
 *    clean cancel, NOT a failure, so it resolves `null` (no error surfaced).
 *  - **F1 neither-result-nor-error:** a success payload with neither a matching
 *    field nor an error resolves whatever `extract` returns (commonly `null`) —
 *    the original behaviour is preserved.
 *  - **F2 timeout:** the wait is raced against `timeoutMs` (default
 *    {@link DEFAULT_JOB_TIMEOUT_MS}); on expiry it REJECTS with a user-facing
 *    message so a dead sidecar can't hang the UI. Pass `0` to disable.
 *  - **F2 abort:** an optional `signal` tears the wait down (cancel/unmount) and
 *    rejects with {@link JobAbortedError}; callers treat that as a clean idle
 *    reset, not an error.
 *  - **No leaks:** the `onJobDone` subscription, the timer, and the abort
 *    listener are ALWAYS cleaned up on whichever settle path wins.
 */
export function waitForJobDone<T>(
  api: JobDoneCapable,
  jobId: string,
  extract: (result: unknown) => T | null,
  timeoutMs: number = DEFAULT_JOB_TIMEOUT_MS,
  signal?: AbortSignal,
): Promise<T | null> {
  if (typeof api.onJobDone !== 'function') return Promise.resolve(null);
  return new Promise<T | null>((resolve, reject) => {
    let off: (() => void) | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // Idempotent teardown — `resolve`/`reject` themselves are single-shot, and
    // every channel is removed here, so the FIRST settle wins and no other can
    // fire (no `settled` flag needed).
    const cleanup = (): void => {
      off?.();
      if (timer !== undefined) clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    };
    const settleResolve = (value: T | null): void => {
      cleanup();
      resolve(value);
    };
    const settleReject = (err: Error): void => {
      cleanup();
      reject(err);
    };
    function onAbort(): void {
      settleReject(new JobAbortedError());
    }

    if (signal?.aborted) {
      settleReject(new JobAbortedError());
      return;
    }

    off = api.onJobDone!((d) => {
      if (d.jobId !== jobId) return;
      const failure = extractJobError(d.result);
      if (failure) {
        // A user-initiated cancel is a clean finish, not an error to surface.
        if (failure.type === 'JobCancelled') {
          settleResolve(null);
          return;
        }
        settleReject(new Error(failure.message));
        return;
      }
      settleResolve(extract(d.result));
    });
    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        settleReject(
          new Error(
            'Timed out waiting for the job to finish — the sidecar may have ' +
              'stopped responding. Please try again.',
          ),
        );
      }, timeoutMs);
    }
    signal?.addEventListener('abort', onAbort);
  });
}

/** Pull a typed field off a job.done `result` (e.g. `transcript`/`track`/`path`/`paths`). */
export function pickField<T>(result: unknown, key: string): T | null {
  if (result && typeof result === 'object' && key in result) {
    return (result as Record<string, T>)[key] ?? null;
  }
  return null;
}
