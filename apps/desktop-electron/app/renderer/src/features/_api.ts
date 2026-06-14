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

/**
 * Wait for the `job.done` notification matching `jobId` and pull the terminal
 * payload out of `result` with `extract`. Mirrors ShortMaker.tsx's working
 * pattern. Resolves `null` if the bridge exposes no `onJobDone` hook (then the
 * rpc promise was the only channel and only carried the `{jobId}` handle).
 */
export function waitForJobDone<T>(
  api: MediaStudioApi,
  jobId: string,
  extract: (result: unknown) => T | null,
): Promise<T | null> {
  if (typeof api.onJobDone !== 'function') return Promise.resolve(null);
  return new Promise<T | null>((resolve) => {
    const off = api.onJobDone!((d) => {
      if (d.jobId !== jobId) return;
      off();
      resolve(extract(d.result));
    });
  });
}

/** Pull a typed field off a job.done `result` (e.g. `transcript`/`track`/`path`/`paths`). */
export function pickField<T>(result: unknown, key: string): T | null {
  if (result && typeof result === 'object' && key in result) {
    return (result as Record<string, T>)[key] ?? null;
  }
  return null;
}
