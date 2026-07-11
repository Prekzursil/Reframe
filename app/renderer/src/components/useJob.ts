import { useCallback, useEffect, useRef, useState } from 'react';
import { onProgress, rpc, type ProgressEvent } from './api';
import { useToastOptional } from './toast/useToast';

export interface JobState {
  jobId: string | null;
  running: boolean;
  pct: number;
  message: string;
  error: string | null;
}

const IDLE: JobState = {
  jobId: null,
  running: false,
  pct: 0,
  message: '',
  error: null,
};

// ---- job.done plumbing (P2 U3) ----------------------------------------------

/** `job.done` notification params (CONTRACTS.md §2: `{jobId, result}`). */
export interface JobDoneEvent {
  jobId: string;
  result?: unknown;
}

/** The A3-frozen job.done error payload body: `{error:{message,type}}`. */
export interface JobErrorPayload {
  message: string;
  type?: string;
}

/** Everything an onError hook (and the toast surface) gets about a failure. */
export interface JobError {
  jobId: string | null;
  method: string | null;
  feature: string;
  label: string;
  message: string;
  type?: string;
}

export interface UseJobOptions {
  /** Human-readable feature label for error surfaces; derived from the rpc
   *  method when omitted (e.g. "transcribe.start" -> "Transcribe"). */
  label?: string;
  /** Called whenever this hook surfaces a job failure (start rejection or a
   *  job.done error payload). */
  onError?: (error: JobError) => void;
}

// CONTRACT-NOTE: the frozen §1 bridge is window.api.{rpc,onProgress}; the real
// preload ALSO exposes onJobDone (the job.done relay) which sibling features
// already consume. components/api.ts (another unit's file) does not export it,
// so we read the bridge structurally here — graceful no-op when it's absent
// (tests/early boot), so existing useJob behavior is unchanged in that case.
function onJobDoneBridge(cb: (event: JobDoneEvent) => void): () => void {
  const api = (
    globalThis as {
      window?: {
        api?: { onJobDone?: (cb: (event: JobDoneEvent) => void) => () => void };
      };
    }
  ).window?.api;
  if (!api || typeof api.onJobDone !== 'function') return () => undefined;
  return api.onJobDone(cb);
}

// ---- sidecar-status plumbing (v1.5 crash fix) -------------------------------

/** Self-healing supervisor lifecycle states (mirrors preload's SidecarStatus). */
export type SidecarStatus = 'running' | 'restarting' | 'down';

// CONTRACT-NOTE: like onJobDone, the preload exposes `onSidecarStatus` (the
// `sidecar.status` relay) but components/api.ts doesn't re-export it, so read it
// structurally off the frozen §1 bridge — graceful no-op when absent (tests/early
// boot), so existing useJob behavior is unchanged in that case.
function onSidecarStatusBridge(cb: (status: SidecarStatus) => void): () => void {
  const api = (
    globalThis as {
      window?: {
        api?: { onSidecarStatus?: (cb: (status: SidecarStatus) => void) => () => void };
      };
    }
  ).window?.api;
  if (!api || typeof api.onSidecarStatus !== 'function') return () => undefined;
  return api.onSidecarStatus(cb);
}

/**
 * Pull the A3 error payload out of a job.done `result`, if present.
 * (Verified against the sidecar: a failed job emits
 * `job.done {jobId, result:{error:{message,type}}}` — jobs.py `_finish_error`.)
 */
export function extractJobError(value: unknown): JobErrorPayload | null {
  if (!value || typeof value !== 'object') return null;
  const error = (value as { error?: unknown }).error;
  if (!error || typeof error !== 'object') return null;
  const message = (error as { message?: unknown }).message;
  const type = (error as { type?: unknown }).type;
  if (typeof message !== 'string') return null;
  return { message, type: typeof type === 'string' ? type : undefined };
}

// ---- feature labels -----------------------------------------------------------

// Labels match the Workspace tab names where one exists (WORKSPACE_TABS).
const FEATURE_LABELS: Record<string, string> = {
  transcribe: 'Transcribe',
  subtitles: 'Subtitles',
  tracks: 'Tracks',
  convert: 'Convert',
  shortmaker: 'Short-maker',
  media: 'Media',
  timeline: 'Timeline',
  tts: 'Dub',
  assets: 'Assets',
  project: 'Project',
  library: 'Library',
  job: 'Job',
};

/** Derive `{feature, label}` from an rpc method name (e.g. "convert.start"). */
export function featureLabel(method: string | null | undefined): {
  feature: string;
  label: string;
} {
  const feature = (method ?? '').split('.')[0] || 'job';
  const label = FEATURE_LABELS[feature] ?? feature.charAt(0).toUpperCase() + feature.slice(1);
  return { feature, label };
}

// ---- job.retry feature detection (loose wiring for U5) -------------------------

export type JobRetryFn = (jobId: string) => Promise<{ jobId: string }>;

let registeredJobRetry: JobRetryFn | null = null;

/**
 * Loose wiring for U5's `job.retry` RPC (A2): the Retry button on error toasts
 * appears ONLY when a retry callable exists. Once the sidecar method ships,
 * the wiring agent registers one — e.g.
 * `registerJobRetry((jobId) => rpc('job.retry', { jobId }))` — see WIRING-U3.md.
 * Pass null to unregister. Until registration, no Retry button is offered.
 */
export function registerJobRetry(fn: JobRetryFn | null): void {
  registeredJobRetry = fn;
}

/** Resolve the retry callable: the registered seam first, then a bridge-level one. */
export function resolveJobRetry(): JobRetryFn | null {
  if (registeredJobRetry) return registeredJobRetry;
  const api = (globalThis as { window?: { api?: { jobRetry?: unknown } } }).window?.api;
  if (api && typeof api.jobRetry === 'function') {
    return (jobId: string) =>
      (api.jobRetry as (jobId: string) => Promise<{ jobId: string }>)(jobId);
  }
  return null;
}

/**
 * Drives a long-running sidecar job (CONTRACTS.md §2): call a method that
 * returns `{jobId}`, then track `job.progress` notifications until `job.cancel`
 * or completion. Returns the live state plus `start`/`cancel`.
 *
 * The caller supplies the rpc method + params; `start` resolves with whatever
 * the method returns (commonly `{jobId}`), and progress for that jobId is
 * tracked automatically.
 *
 * P2 U3 upgrade: the hook also subscribes to the terminal `job.done`
 * notification. A success payload finishes the job; the A3 error payload
 * (`{error:{message,type}}`) surfaces as an error toast labeled with the
 * failing feature (when a <ToastProvider> is mounted) and through the
 * `onError` hook. The toast carries a "Retry" action ONLY when a `job.retry`
 * callable has been detected/registered (U5 ships the RPC; see
 * `registerJobRetry`).
 */
export function useJob(options?: UseJobOptions) {
  const [state, setState] = useState<JobState>(IDLE);
  const activeJobId = useRef<string | null>(null);
  const activeMethod = useRef<string | null>(null);
  const toast = useToastOptional();

  // "Latest" refs so the once-mounted subscriptions see the current toast api
  // and options without re-subscribing every render.
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    // Subscribe once; filter to the currently-active jobId.
    const unsubscribe = onProgress((event: ProgressEvent) => {
      if (activeJobId.current && event.jobId === activeJobId.current) {
        setState((prev) => ({
          ...prev,
          pct: event.pct,
          message: event.message,
        }));
      }
    });
    return unsubscribe;
  }, []);

  /** Surface a failure: state + onError hook + (when mounted) an error toast. */
  const surfaceError = useCallback((payload: JobErrorPayload): void => {
    const method = activeMethod.current;
    const jobId = activeJobId.current;
    activeJobId.current = null; // terminal — stop tracking progress
    const derived = featureLabel(method);
    const label = optionsRef.current?.label ?? derived.label;
    setState((prev) => ({ ...prev, running: false, error: payload.message }));

    const jobError: JobError = {
      jobId,
      method,
      feature: derived.feature,
      label,
      message: payload.message,
      type: payload.type,
    };
    optionsRef.current?.onError?.(jobError);

    const toastApi = toastRef.current;
    if (!toastApi) return;
    const retry = resolveJobRetry();
    const action =
      retry && jobId
        ? {
            label: 'Retry',
            onClick: (): void => {
              setState({ ...IDLE, running: true });
              retry(jobId)
                .then((result) => {
                  const newJobId = (result as { jobId?: string } | null)?.jobId ?? null;
                  activeJobId.current = newJobId;
                  setState((prev) => ({ ...prev, jobId: newJobId, running: true }));
                })
                .catch((err: unknown) => {
                  const message = err instanceof Error ? err.message : String(err);
                  setState((prev) => ({ ...prev, running: false, error: message }));
                });
            },
          }
        : undefined;
    toastApi.error(`${label} failed: ${payload.message}`, action ? { action } : undefined);
  }, []);

  useEffect(() => {
    // Terminal job.done for the active job: error payload -> surface; success
    // -> finish. Notifications for other jobs are ignored (feature panels that
    // await their own jobs via onJobDone keep working unchanged).
    const unsubscribe = onJobDoneBridge((event) => {
      if (!activeJobId.current || event.jobId !== activeJobId.current) return;
      // A3: failures arrive as result = {error:{message,type}}. Also accept a
      // sibling-level error defensively in case U5's jobs/protocol refactor
      // lifts it onto the params object.
      const failure = extractJobError(event.result) ?? extractJobError(event);
      if (failure) {
        // CONTRACT-NOTE: cancelled jobs emit no job.done today (jobs.py). If a
        // future registry version emits one, a user-initiated cancel is not a
        // failure — finish quietly instead of toasting.
        if (failure.type === 'JobCancelled') {
          activeJobId.current = null;
          setState((prev) => ({ ...prev, running: false }));
          return;
        }
        surfaceError(failure);
        return;
      }
      activeJobId.current = null;
      setState((prev) => ({ ...prev, running: false, pct: 100 }));
    });
    return unsubscribe;
  }, [surfaceError]);

  useEffect(() => {
    // v1.5 crash fix: a sidecar crash/restart is surfaced to the renderer as a
    // NON-running lifecycle status ('restarting' | 'down'; ipc.ts also relays the
    // raw process 'exit' onto this channel). The dead process can never emit the
    // active job's terminal job.done, so fail the job instead of leaving the panel
    // spinning forever — mirroring sidecar.ts buildProxyJob's exit->reject. A
    // 'running' push (initial spawn / recovery) is not a failure, and with no
    // active job there is nothing to fail.
    const unsubscribe = onSidecarStatusBridge((status) => {
      if (status === 'running' || !activeJobId.current) return;
      surfaceError({
        message: 'Sidecar stopped — the job was interrupted',
        type: 'JobInterrupted',
      });
    });
    return unsubscribe;
  }, [surfaceError]);

  const start = useCallback(
    async <T = { jobId: string }>(method: string, params?: Record<string, unknown>): Promise<T> => {
      activeMethod.current = method;
      activeJobId.current = null;
      setState({ ...IDLE, running: true });
      try {
        const result = await rpc<T>(method, params);
        const jobId = (result as { jobId?: string } | null)?.jobId ?? null;
        activeJobId.current = jobId;
        setState((prev) => ({ ...prev, jobId, running: true }));
        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        surfaceError({
          message,
          type: err instanceof Error ? err.name : undefined,
        });
        throw err;
      }
    },
    [surfaceError],
  );

  const finish = useCallback(() => {
    activeJobId.current = null;
    setState((prev) => ({ ...prev, running: false, pct: 100 }));
  }, []);

  const cancel = useCallback(async (): Promise<void> => {
    const jobId = activeJobId.current;
    if (!jobId) return;
    try {
      await rpc('job.cancel', { jobId });
    } finally {
      activeJobId.current = null;
      setState((prev) => ({ ...prev, running: false }));
    }
  }, []);

  const reset = useCallback(() => {
    activeJobId.current = null;
    setState(IDLE);
  }, []);

  return { state, start, finish, cancel, reset };
}

export default useJob;
