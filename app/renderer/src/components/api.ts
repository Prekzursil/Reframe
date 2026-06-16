// Thin typed access to the preload bridge (window.api), per CONTRACTS.md §1/§2/§3.
//
// CONTRACT-NOTE: app/renderer/src/lib/rpc.ts is owned by the foundation unit and is
// the canonical typed client, but its exact export shape is not frozen in the
// contract. To stay independent (and so this ui-shell unit typechecks/tests on its
// own), the components/views here talk to `window.api` directly through the small
// helpers below. The bridge surface used (`window.api.rpc`, `window.api.onProgress`)
// IS frozen in CONTRACTS.md §1, so this is safe.

// ---- Schemas (CONTRACTS.md §3) — field names identical to the Python side ----

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

export interface SubtitleTrack {
  id: string;
  lang: string;
  name: string;
  format: string;
  kind: 'soft' | 'hard';
  cues: Cue[];
}

export interface Candidate {
  rank: number;
  start: number;
  end: number;
  durationSec: number;
  hook: string;
  why: string;
  score: number;
  sourceStart: number;
}

export interface Video {
  id: string;
  path: string;
  title: string;
  addedAt: string;
  durationSec: number;
  hasTranscript: boolean;
}

export interface Project {
  id: string;
  video: Video;
  transcript?: Transcript;
  tracks: SubtitleTrack[];
  clips: { candidate: Candidate; path: string }[];
  settings: Record<string, unknown>;
}

// ---- Progress notification payload (CONTRACTS.md §2: job.progress) ----

export interface ProgressEvent {
  jobId: string;
  pct: number;
  message: string;
}

// ---- The preload bridge surface (CONTRACTS.md §1) ----

export interface MediaApi {
  rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
  onProgress(cb: (event: ProgressEvent) => void): () => void;
  /** Optional (U2) — native multi-select video picker ([] when cancelled). */
  openVideos?(): Promise<string[]>;
  /** Optional (U2) — dropped File -> absolute path (webUtils.getPathForFile). */
  pathForFile?(file: File): string;
  /** Optional (P4 §6) — reveal a path in the OS file explorer (true on success). */
  openInFolder?(path: string): Promise<boolean>;
  /** Optional (P4 8d) — native single-select brand-logo picker (null when cancelled). */
  pickLogoFile?(): Promise<string | null>;
}

declare global {
  interface Window {
    api: MediaApi;
  }
}

// Resolve the bridge lazily so importing this module never throws in a test/SSR
// context where window.api has not been injected by the preload.
function bridge(): MediaApi {
  const api = (globalThis as { window?: Window }).window?.api;
  if (!api) {
    throw new Error('window.api bridge is not available (preload not loaded)');
  }
  return api;
}

/** Invoke a sidecar JSON-RPC method through the preload bridge. */
export function rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
  return bridge().rpc<T>(method, params);
}

/** Subscribe to job.progress notifications. Returns an unsubscribe fn. */
export function onProgress(cb: (event: ProgressEvent) => void): () => void {
  return bridge().onProgress(cb);
}

/** True when the preload bridge is present (lets UI degrade gracefully). */
export function hasApi(): boolean {
  return Boolean((globalThis as { window?: Window }).window?.api);
}
