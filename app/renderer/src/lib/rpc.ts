// lib/rpc.ts — the canonical typed client over the preload bridge `window.api`
// (CONTRACTS.md §1: renderer/src/lib/rpc.ts). This is the foundation unit's
// typed wrapper; the already-written UI improvised `components/api.ts` and
// `features/_api.ts` while this file was missing, so those keep their own
// thin helpers. This module does NOT replace them — it provides the canonical,
// fully-typed surface (method-typed `rpc`, `onProgress`, `onJobDone`) plus the
// §3 data schemas so new code can depend on one place.
//
// CONTRACT-NOTE: the §1 bridge surface is frozen as `window.api.rpc(method,
// params)` + `window.api.onProgress(cb)`. The preload also exposes the optional
// `onJobDone(cb)` (used by ShortMaker's deferred-job path). All three are typed
// here. We deliberately do NOT `declare global { interface Window { api } }`
// because sibling units (components/api.ts) already do, and a second merged
// augmentation with a different shape collides (TS2717). We read the bridge via
// a single structural accessor instead.

// ---- §3 data schemas (field names identical to the Python side) ----------

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

/** captions-export: which language sits on top in a stacked bilingual cue. */
export type BilingualOrder = 'original-first' | 'translation-first';

/** captions-export: NLE timeline export format + selectable frame rates. */
export type NleFormat = 'edl' | 'csv';
export type NleFps = 24 | 25 | 30 | 60;

/** captions-export: the `upload.json` manifest inside a package ZIP. */
export interface UploadManifest {
  title: string;
  description: string;
  tags: string[];
  source: {
    videoId: string;
    sourceTitle: string;
    template: string;
    viralityPct: number | null;
    durationSec: number;
    hook: string;
  };
}

export interface SubtitleTrack {
  id: string;
  lang: string;
  name: string;
  format: SubtitleFormat | string;
  kind: TrackKind;
  cues: Cue[];
}

/** P3-C virality factor scores (each 0-100) — wire field names FROZEN. */
export interface CandidateFactors {
  hookStrength: number;
  emotionalFlow: number;
  perceivedValue: number;
  shareability: number;
}

export interface Candidate {
  rank: number;
  start: number;
  end: number;
  durationSec: number;
  hook: string;
  why: string;
  score: number;
  /** clip's start in the ORIGINAL video (captions re-base by subtracting this). */
  sourceStart: number;
  /** P3-C: per-factor scores 0-100 (optional — pre-P3 payloads omit them). */
  factors?: CandidateFactors;
  /** P3-C: one-line rationale per factor. */
  factorNotes?: Partial<Record<keyof CandidateFactors, string>>;
  /** P3-C: batch-percentile-normalized virality 0-100 within the candidate set. */
  viralityPct?: number;
}

/** P3-D feedback flywheel — implicit-label actions (wire values FROZEN). */
export type FeedbackAction = 'approved' | 'discarded' | 'nudged' | 'exported';

/** `feedback.stats()` result. */
export interface FeedbackStats {
  labels: number;
  calibrated: boolean;
}

/** P3-B: one exported clip; filler-removal stats present when the pass ran. */
export interface ExportedClip {
  path: string;
  fillersRemoved?: number;
  fillerSeconds?: number;
}

/**
 * P4 §3 ShortInfo — one produced short clip surfaced by `shorts.list`. Field
 * names are FROZEN and identical to the sidecar `shorts.short_info` payload
 * (`sidecar/media_studio/features/shorts.py`). The sidecar reconstructs these
 * from each clip's `<clip>.json` metadata (export-time fields) plus on-disk
 * facts (id / path / createdAt / thumbnailPath); export-time fields default to
 * blank/`null` for clips produced before the metadata write existed.
 */
export interface ShortInfo {
  /** Stable hash of the path. */
  id: string;
  /** Absolute path to the exported mp4. */
  path: string;
  /** Source library video id ("" if unknown). */
  videoId: string;
  /** Source video title ("" if unknown). */
  sourceTitle: string;
  /** Caption template id used ("" if none). */
  template: string;
  /** The clip's virality score if known (null otherwise). */
  viralityPct: number | null;
  durationSec: number;
  width: number;
  height: number;
  /** mtime epoch seconds. */
  createdAt: number;
  /** "" until a poster frame is generated. */
  thumbnailPath: string;
  /** Hook / title text (""). */
  hook: string;
}

/**
 * P4 §2 `shorts.reexport` result — the "reopen in short-maker" hint: the source
 * `videoId` plus a candidate skeleton rebuilt from the clip's `.json` metadata,
 * so the UI can re-open Short-maker primed and replay `shortmaker.export`. Field
 * names mirror the sidecar `Shorts.reexport` payload.
 */
export interface ShortReexportHint {
  videoId: string;
  candidate: {
    hook: string;
    template: string;
    viralityPct: number | null;
    durationSec: number;
  };
}

export interface Video {
  id: string;
  path: string;
  title: string;
  addedAt: string;
  durationSec: number;
  hasTranscript: boolean;
}

/** A3 AudioTrack — one original/dub audio lane of a video. */
export interface AudioTrack {
  id: string;
  lang: string;
  name: string;
  kind: 'original' | 'dub';
  voice?: string;
  path: string;
}

/** A3 AssetInfo — one entry of `assets.list`'s {assets:[...]} payload. */
export interface AssetInfo {
  name: string;
  kind: 'model' | 'env' | 'tool';
  sizeMB: number;
  installed: boolean;
  dest: string;
}

/**
 * system-advanced `system.health` report — field names FROZEN, identical to the
 * sidecar `Health.report` payload (`sidecar/media_studio/features/health.py`).
 */
export interface HealthReport {
  ok: boolean;
  offline: boolean;
  platform: string;
  tools: { name: string; present: boolean; path: string; version: string; hint: string }[];
  backends: { label: string; module: string; installed: boolean; version: string }[];
  modelPaths: { label: string; path: string; exists: boolean }[];
  engines: { name: string; description: string; available: boolean; path: string }[];
}

/**
 * system-advanced saved pipeline recipe — field names FROZEN, identical to the
 * sidecar `recipes.normalize_recipe` shape. A `Step` names an existing RPC
 * method + its params; param values may use the `"$N.key"` prior-step reference
 * form the runner resolves.
 */
export interface RecipeStep {
  method: string;
  params: Record<string, unknown>;
  label: string;
}
export interface SavedRecipe {
  id: string;
  name: string;
  steps: RecipeStep[];
}

/** A3 VoiceSample — a stored voice-clone reference sample. */
export interface VoiceSample {
  id: string;
  name: string;
  path: string;
  durationSec: number;
}

/** A2 media.playable result (codec-driven: remux-safe vs proxy). */
export interface MediaPlayableResult {
  playable: boolean;
  reason?: string;
  proxyPath?: string;
}

export interface Project {
  id: string;
  video: Video;
  transcript?: Transcript;
  tracks: SubtitleTrack[];
  clips: { candidate: Candidate; path: string }[];
  /** A3: Project.audioTracks (optional here — older manifests omit it). */
  audioTracks?: AudioTrack[];
  settings: Record<string, unknown>;
}

// ---- Notification payloads (CONTRACTS.md §2) -----------------------------

/** `job.progress` params. */
export interface ProgressEvent {
  jobId: string;
  pct: number;
  message: string;
}

/** `job.done` params. */
export interface DoneEvent {
  jobId: string;
  result?: unknown;
}

/** A3 JobInfo — one entry of `job.list`'s {jobs:[...]} payload. */
export interface JobInfo {
  jobId: string;
  feature: string;
  label: string;
  videoId?: string;
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled';
  pct: number;
}

// ---- Convert options (CONTRACTS.md §2: convert.start options) ------------

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

// ---- The frozen preload bridge surface (CONTRACTS.md §1) -----------------

export interface MediaApi {
  rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
  onProgress(cb: (event: ProgressEvent) => void): () => void;
  /** Optional — present on the real preload; used for deferred {jobId} jobs. */
  onJobDone?(cb: (event: DoneEvent) => void): () => void;
  /** Optional (U2) — native multi-select video picker ([] when cancelled). */
  openVideos?(): Promise<string[]>;
  /** Optional (U2) — dropped File -> absolute path (webUtils.getPathForFile). */
  pathForFile?(file: File): string;
  /** Optional (P4 §6) — reveal a path in the OS file explorer (true on success). */
  openInFolder?(path: string): Promise<boolean>;
  /** Optional (P4 8d) — native single-select brand-logo picker (null when cancelled). */
  pickLogoFile?(): Promise<string | null>;
  /** Optional (DATA ROOT) — the data folder in use this session. */
  getDataFolder?(): Promise<string>;
  /** Optional (DATA ROOT) — native open-DIRECTORY picker (null when cancelled). */
  pickDataFolder?(): Promise<string | null>;
  /** Optional (DATA ROOT) — persist the chosen data folder (restart applies it). */
  setDataFolder?(path: string): Promise<{ ok: boolean }>;
}

/** Read the preload-injected bridge without a global Window augmentation. */
function bridge(): MediaApi {
  const api = (globalThis as { window?: { api?: MediaApi } }).window?.api;
  if (!api) {
    throw new Error('window.api bridge is not available (preload not loaded)');
  }
  return api;
}

/** True when the preload bridge is present (lets the UI degrade gracefully). */
export function hasApi(): boolean {
  return Boolean((globalThis as { window?: { api?: MediaApi } }).window?.api);
}

/** Invoke a sidecar JSON-RPC method through the preload bridge. */
export function rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
  return bridge().rpc<T>(method, params);
}

/** Subscribe to `job.progress`. Returns an unsubscribe fn. */
export function onProgress(cb: (event: ProgressEvent) => void): () => void {
  return bridge().onProgress(cb);
}

/** Subscribe to `job.done`. Returns an unsubscribe fn (no-op if unsupported). */
export function onJobDone(cb: (event: DoneEvent) => void): () => void {
  const api = bridge();
  if (typeof api.onJobDone !== 'function') return () => undefined;
  return api.onJobDone(cb);
}

// ---- Method-typed convenience surface (the canonical client) -------------
//
// Thin, named wrappers around `rpc(...)` for the §2 method registry. New code
// can import `client` instead of stringly-typed `rpc(...)`. These mirror the
// frozen method names + param/result shapes exactly.

export interface JobHandle {
  jobId: string;
}

export const client = {
  ping: (): Promise<{ pong: boolean; version: string }> => rpc('ping'),

  library: {
    list: (): Promise<{ videos: Video[] }> => rpc('library.list'),
    add: (path: string): Promise<{ video: Video }> => rpc('library.add', { path }),
    remove: (id: string): Promise<{ ok: boolean }> => rpc('library.remove', { id }),
  },

  project: {
    open: (id: string): Promise<{ project: Project }> => rpc('project.open', { id }),
    save: (project: Project): Promise<{ ok: boolean }> => rpc('project.save', { project }),
    consolidate: (id: string): Promise<{ ok: boolean; folder: string }> =>
      rpc('project.consolidate', { id }),
  },

  transcribe: {
    start: (videoId: string, language?: string): Promise<JobHandle & { transcript?: Transcript }> =>
      rpc('transcribe.start', language ? { videoId, language } : { videoId }),
  },

  subtitles: {
    generate: (videoId: string): Promise<{ track: SubtitleTrack }> =>
      rpc('subtitles.generate', { videoId }),
    edit: (trackId: string, cues: Cue[]): Promise<{ track: SubtitleTrack }> =>
      rpc('subtitles.edit', { trackId, cues }),
    translate: (
      trackId: string,
      targetLang: string,
      // captions-export: bilingual stacks original+translation into a NEW track.
      opts?: { bilingual?: boolean; order?: BilingualOrder },
    ): Promise<JobHandle & { track?: SubtitleTrack }> =>
      rpc('subtitles.translate', { trackId, targetLang, ...(opts ?? {}) }),
    export: (trackId: string, format: SubtitleFormat): Promise<{ path: string }> =>
      rpc('subtitles.export', { trackId, format }),
  },

  tracks: {
    list: (videoId: string): Promise<{ tracks: SubtitleTrack[] }> =>
      rpc('tracks.list', { videoId }),
    rename: (trackId: string, name: string): Promise<{ track: SubtitleTrack }> =>
      rpc('tracks.rename', { trackId, name }),
    relabel: (trackId: string, lang: string): Promise<{ track: SubtitleTrack }> =>
      rpc('tracks.relabel', { trackId, lang }),
    add: (videoId: string, trackId: string): Promise<{ ok: boolean }> =>
      rpc('tracks.add', { videoId, trackId }),
    remove: (videoId: string, trackId: string): Promise<{ ok: boolean }> =>
      rpc('tracks.remove', { videoId, trackId }),
    burn: (videoId: string, trackId: string): Promise<JobHandle & { path?: string }> =>
      rpc('tracks.burn', { videoId, trackId }),
    strip: (videoId: string, trackId: string): Promise<{ path: string }> =>
      rpc('tracks.strip', { videoId, trackId }),
  },

  convert: {
    start: (
      target: { videoId?: string; path?: string },
      options: ConvertOptions,
    ): Promise<JobHandle & { path?: string }> => rpc('convert.start', { ...target, options }),
    batch: (
      items: { videoId?: string; path?: string; options: ConvertOptions }[],
    ): Promise<JobHandle & { paths?: string[] }> => rpc('convert.batch', { items }),
  },

  shortmaker: {
    select: (
      videoId: string,
      prompt: string,
      controls: Record<string, unknown>,
    ): Promise<JobHandle & { candidates?: Candidate[] }> =>
      rpc('shortmaker.select', { videoId, prompt, controls }),
    export: (
      videoId: string,
      candidateIds: string[],
      // A2: optional audioTrackId; T4b: optional captionStyle/reframeEngine;
      // P3: optional hookTitle/removeFillers (mirror the select controls).
      opts?: {
        audioTrackId?: string;
        captionStyle?: string;
        reframeEngine?: string;
        hookTitle?: boolean;
        removeFillers?: boolean;
      },
    ): Promise<JobHandle & { clips?: ExportedClip[] }> =>
      rpc('shortmaker.export', { videoId, candidateIds, ...(opts ?? {}) }),
  },

  // ---- P4 shorts gallery (§2 / C6) ----------------------------------------

  shorts: {
    /** `shorts.list {videoId?}` — omitted videoId lists every source's clips. */
    list: (videoId?: string): Promise<{ shorts: ShortInfo[] }> =>
      rpc('shorts.list', videoId ? { videoId } : {}),
    /** `shorts.thumbnail {path}` — idempotent poster-frame extraction. */
    thumbnail: (path: string): Promise<{ thumbnailPath: string }> =>
      rpc('shorts.thumbnail', { path }),
    /** `shorts.delete {path}` — path-traversal guarded inside the output root. */
    delete: (path: string): Promise<{ ok: boolean }> => rpc('shorts.delete', { path }),
    /** `shorts.reexport {path}` — the reopen-in-short-maker hint (no job). */
    reexport: (path: string): Promise<ShortReexportHint> => rpc('shorts.reexport', { path }),
  },

  // ---- P4 captions (live preview overlay; §2 / C7) ------------------------

  captions: {
    /** `captions.cues {videoId}` — WORD-level cues (source-absolute seconds). */
    cues: (videoId: string): Promise<{ cues: Cue[] }> => rpc('captions.cues', { videoId }),
  },

  // ---- captions-export: NLE timeline export (EDL / CSV) -------------------

  nle: {
    /**
     * `nle.export {videoId, format?, fps?, title?, clips?}` — export the video's
     * approved clips as an editable timeline (CMX3600 EDL or CSV) for
     * Premiere / DaVinci Resolve. `clips` overrides the persisted project clips.
     */
    export: (
      videoId: string,
      opts?: { format?: NleFormat; fps?: NleFps; title?: string; clips?: unknown[] },
    ): Promise<{ path: string; clipCount: number }> =>
      rpc('nle.export', { videoId, ...(opts ?? {}) }),
  },

  // ---- captions-export: package-for-upload ZIP ---------------------------

  package: {
    /**
     * `package.export {path, suggestion?}` — bundle a produced short
     * (mp4 + thumbnail + suggested title/description/tags upload.json) into a
     * ZIP for manual posting. `path` is the exported clip (inside exports root).
     */
    export: (
      path: string,
      suggestion?: { title?: string; description?: string; tags?: string[] | string },
    ): Promise<{ path: string; manifest: UploadManifest }> =>
      rpc('package.export', suggestion ? { path, suggestion } : { path }),
  },

  // ---- P3-D feedback flywheel ---------------------------------------------

  feedback: {
    record: (p: {
      videoId: string;
      candidate: Candidate;
      action: FeedbackAction;
    }): Promise<{ ok: boolean }> => rpc('feedback.record', { ...p }),
    stats: (): Promise<FeedbackStats> => rpc('feedback.stats'),
  },

  // ---- A2 addendum methods (P2) ------------------------------------------

  media: {
    playable: (videoId: string): Promise<MediaPlayableResult> => rpc('media.playable', { videoId }),
    proxyStart: (videoId: string): Promise<JobHandle & { path?: string }> =>
      rpc('media.proxy.start', { videoId }),
  },

  timeline: {
    peaks: (videoId: string): Promise<{ sampleRate: number; peaks: number[] }> =>
      rpc('timeline.peaks', { videoId }),
  },

  tts: {
    voices: (): Promise<{
      voices: { id: string; engine: string; lang: string; name: string }[];
    }> => rpc('tts.voices'),
    sampleAdd: (path: string): Promise<{ sample: VoiceSample }> => rpc('tts.sample.add', { path }),
    dubStart: (p: {
      videoId: string;
      trackId: string;
      engine: string;
      voice?: string;
      sampleId?: string;
      targetLang?: string;
    }): Promise<JobHandle & { audioTrack?: AudioTrack; path?: string }> =>
      rpc('tts.dub.start', { ...p }),
  },

  tracksAudio: {
    list: (videoId: string): Promise<{ audioTracks: AudioTrack[] }> =>
      rpc('tracks.audio.list', { videoId }),
    mux: (p: {
      videoId: string;
      path: string;
      lang: string;
      name: string;
      kind: string;
    }): Promise<{ audioTrack: AudioTrack }> => rpc('tracks.audio.mux', { ...p }),
    replace: (p: {
      videoId: string;
      audioTrackId: string;
      path: string;
    }): Promise<{ audioTrack: AudioTrack }> => rpc('tracks.audio.replace', { ...p }),
    strip: (p: { videoId: string; audioTrackId: string }): Promise<{ path: string }> =>
      rpc('tracks.audio.strip', { ...p }),
  },

  assets: {
    list: (): Promise<{ assets: AssetInfo[] }> => rpc('assets.list'),
    ensure: (names: string[]): Promise<JobHandle> => rpc('assets.ensure', { names }),
    /** CONTRACT-NOTE (U4): thin alias over job.cancel (same params/semantics). */
    cancel: (jobId: string): Promise<{ ok: boolean }> => rpc('assets.cancel', { jobId }),
  },

  job: {
    cancel: (jobId: string): Promise<{ ok: boolean }> => rpc('job.cancel', { jobId }),
    status: (jobId: string): Promise<{ status: string; pct: number }> =>
      rpc('job.status', { jobId }),
    list: (): Promise<{ jobs: JobInfo[] }> => rpc('job.list'),
    retry: (jobId: string): Promise<{ jobId: string }> => rpc('job.retry', { jobId }),
  },

  settings: {
    get: (): Promise<Record<string, unknown>> => rpc('settings.get'),
    set: (values: Record<string, unknown>): Promise<Record<string, unknown>> =>
      rpc('settings.set', values),
  },

  // ---- system-advanced group ----------------------------------------------

  /** `system.health` — the "is my setup OK?" diagnostic (direct-return). */
  system: {
    health: (): Promise<HealthReport> => rpc('system.health'),
  },

  /** `recipes.*` — saved multi-step pipelines run in one shot. */
  recipes: {
    list: (): Promise<{ recipes: SavedRecipe[] }> => rpc('recipes.list'),
    save: (recipe: SavedRecipe | Omit<SavedRecipe, 'id'>): Promise<{ recipe: SavedRecipe }> =>
      rpc('recipes.save', { recipe }),
    delete: (id: string): Promise<{ ok: boolean }> => rpc('recipes.delete', { id }),
    run: (id: string): Promise<JobHandle> => rpc('recipes.run', { id }),
  },

  /** `diarize.start` — token-free speaker labelling (long job -> {transcript}). */
  diarize: {
    start: (
      videoId: string,
      threshold?: number,
    ): Promise<JobHandle & { transcript?: Transcript }> =>
      rpc('diarize.start', threshold === undefined ? { videoId } : { videoId, threshold }),
  },
} as const;

export default client;
