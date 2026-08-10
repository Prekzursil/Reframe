// lib/rpc/client.ts - the canonical typed client over the preload bridge
// `window.api` (CONTRACTS.md section 1). Split out of the former monolithic
// lib/rpc.ts (F4b quality cleanup): the section 3 data schemas + bridge types live
// in ./schemas; this module owns the RUNTIME - the structural bridge accessor,
// `rpc`, `onProgress`/`onJobDone`, and the method-typed `client`. ./index
// re-exports both.
//
// CONTRACT-NOTE: the section 1 bridge surface is frozen as `window.api.rpc(method,
// params)` + `window.api.onProgress(cb)` (+ optional `onJobDone(cb)`). We do NOT
// `declare global { interface Window { api } }` because sibling units already do
// and a second merged augmentation with a different shape collides (TS2717); we
// read the bridge via a single structural accessor instead.

import type {
  AdvisorReport,
  AsrEngine,
  AssetInfo,
  AudioTrack,
  AutosaveSettings,
  BatchConsent,
  BatchState,
  BatchStatus,
  BatchSummary,
  BilingualOrder,
  Candidate,
  CatalogResponse,
  ConvertOptions,
  Cue,
  DirectorEval,
  DirectorOpStatus,
  DirectorPreview,
  DoneEvent,
  ExportDefaults,
  ExportPreset,
  ExportedClip,
  FeedbackAction,
  FeedbackStats,
  FirstRunResponse,
  HardwareInfo,
  HealthReport,
  IndexHit,
  IndexStatus,
  JobHandle,
  JobInfo,
  LineageResult,
  RegenerateResult,
  KeepCopyResult,
  ManagedClearResult,
  ManagedEvictResult,
  ManagedStatus,
  RelinkResult,
  RevealResult,
  LocalModelPlan,
  ConcreteRoute,
  MediaApi,
  MediaPlayableResult,
  ModelsOverview,
  NleFormat,
  NleFps,
  OpenRouterUsageRow,
  PathsDescribe,
  PresetResponse,
  ProgressEvent,
  Project,
  ProviderConsent,
  ProviderEntry,
  ProviderUsageAvailability,
  ProvidersListResponse,
  RevealKeyResult,
  ProxyStateEvent,
  ReadinessItem,
  RecommendResponse,
  RoutingMode,
  RoutingPolicy,
  SavePreset,
  SavePresetsBlock,
  SavedRecipe,
  SelfTestReport,
  SetConsentResponse,
  ShortInfo,
  ShortReexportHint,
  SocialCapability,
  SocialPublishJob,
  SocialQueueEntry,
  SocialSchedulePlan,
  SpendInfo,
  SubtitleFormat,
  SubtitleTrack,
  Template,
  TestKeyResult,
  Transcript,
  UploadManifest,
  UsageRow,
  Video,
  VoiceSample,
} from './schemas';
import type { ShotOverride, ShotPlan } from '../reframeOverride';

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

/**
 * WU B3: subscribe to playback-proxy build-state pushes (`proxy.state`). Returns
 * an unsubscribe fn (a no-op when the preload bridge predates the channel).
 */
export function onProxyState(cb: (event: ProxyStateEvent) => void): () => void {
  const api = bridge();
  if (typeof api.onProxyState !== 'function') return () => undefined;
  return api.onProxyState(cb);
}

// ---- Method-typed convenience surface (the canonical client) -------------
//
// Thin, named wrappers around `rpc(...)` for the §2 method registry. New code
// can import `client` instead of stringly-typed `rpc(...)`. These mirror the
// frozen method names + param/result shapes exactly.

export const client = {
  ping: (): Promise<{ pong: boolean; version: string }> => rpc('ping'),

  library: {
    list: (): Promise<{ videos: Video[] }> => rpc('library.list'),
    add: (path: string): Promise<{ video: Video }> => rpc('library.add', { path }),
    remove: (id: string): Promise<{ ok: boolean }> => rpc('library.remove', { id }),
    /** `library.thumbnail {id}` — idempotent source-video poster extraction (WU-4). */
    thumbnail: (id: string): Promise<{ thumbnailPath: string }> => rpc('library.thumbnail', { id }),
    /** `library.lineage {id}` — an asset's PROV ancestors/descendants + card data (L3/L4). */
    lineage: (id: string): Promise<LineageResult> => rpc('library.lineage', { id }),
    /** `library.reveal {id}` — resolve an asset to its by-path source file(s) to reveal (L5). */
    reveal: (id: string): Promise<RevealResult> => rpc('library.reveal', { id }),
    /** `library.regenerate {id}` — the replay descriptor (op + params) for an asset (L5). */
    regenerate: (id: string): Promise<RegenerateResult> => rpc('library.regenerate', { id }),
    /** `library.pinHash {id}` — record an asset's whole-file BLAKE3 hash baseline (L5). */
    pinHash: (id: string): Promise<RelinkResult> => rpc('library.pinHash', { id }),
    /** `library.relink {id, path}` — hash-verified re-point of a moved source (L5). */
    relink: (id: string, path: string): Promise<RelinkResult> =>
      rpc('library.relink', { id, path }),
    /** `library.keepCopy {id}` — OPT-IN: copy the source into the managed store (WU-3b1). */
    keepCopy: (id: string): Promise<KeepCopyResult> => rpc('library.keepCopy', { id }),
    /** `library.managedStatus` — the managed store's used/cap/count snapshot (WU-3b1). */
    managedStatus: (): Promise<ManagedStatus> => rpc('library.managedStatus'),
    /** `library.managedEvict {id}` — evict ONE managed copy back to its original (WU-3b1). */
    managedEvict: (id: string): Promise<ManagedEvictResult> => rpc('library.managedEvict', { id }),
    /** `library.managedClear` — evict EVERY managed copy (WU-3b1). */
    managedClear: (): Promise<ManagedClearResult> => rpc('library.managedClear'),
  },

  project: {
    open: (id: string): Promise<{ project: Project }> => rpc('project.open', { id }),
    save: (project: Project): Promise<{ ok: boolean }> => rpc('project.save', { project }),
    consolidate: (id: string): Promise<{ ok: boolean; folder: string }> =>
      rpc('project.consolidate', { id }),
  },

  transcribe: {
    // A karaoke-style caption export needs per-WORD timings; `alignWords` opts the
    // transcribe job into forced word alignment. Threaded only when true so
    // non-karaoke callers keep their exact `{videoId}`/`{videoId, language}` wire.
    start: (
      videoId: string,
      language?: string,
      alignWords?: boolean,
    ): Promise<JobHandle & { transcript?: Transcript }> =>
      rpc('transcribe.start', {
        videoId,
        ...(language ? { language } : {}),
        ...(alignWords ? { alignWords: true } : {}),
      }),
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
    // v1.5 escape hatch: bring a hand-corrected SRT/VTT/ASS back IN. `text` is the
    // file's CONTENT, not a path — the caller reads it with the standard File API,
    // so the sidecar never opens a renderer-supplied filesystem path. `format` is
    // passed raw (the sidecar folds '.SRT'/'ssa' and rejects anything else).
    import: (
      videoId: string,
      text: string,
      format: string,
      opts?: { name?: string; lang?: string },
    ): Promise<{ track: SubtitleTrack }> =>
      rpc('subtitles.import', { videoId, text, format, ...(opts ?? {}) }),
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
    /**
     * `convert.start({videoId|path, options, out?})`.
     *
     * `out` names the destination file explicitly. It is NOT new wire surface —
     * the sidecar has always read it (`convert.start_handler` builds its item
     * with `"out": params.get("out")`) and CONFINES it to the source's own
     * directory or the app data root (`convert._confined_output`), because
     * ffmpeg runs with `-y`. Only the renderer's type was narrower than the
     * handler. The aspect fan-out needs it: without a per-target name every
     * target derives the SAME `<stem>.mp4` and the files overwrite each other.
     */
    start: (
      target: { videoId?: string; path?: string; out?: string },
      options: ConvertOptions,
    ): Promise<JobHandle & { path?: string }> => rpc('convert.start', { ...target, options }),
    batch: (
      items: { videoId?: string; path?: string; options: ConvertOptions }[],
    ): Promise<JobHandle & { paths?: string[] }> => rpc('convert.batch', { items }),
  },

  /**
   * Playback speed. `factor` > 1 speeds up (shorter), < 1 slows down (longer);
   * the sidecar rejects a non-positive, out-of-window, or exactly-1.0 factor
   * (`features/speed.py` `resolve_factor`), so validate with `isRetimeFactor`
   * from `lib/speedPresets` before calling if the value came from a user.
   *
   * A job: this resolves with `{jobId}` only, and the terminal
   * `{path, factor, sourceDurationSec, durationSec}` arrives on `job.done`.
   *
   * CONSTANT factor over the whole clip — there is no keyframed ramp engine.
   */
  speed: {
    retime: (
      target: { videoId?: string; path?: string },
      factor: number,
    ): Promise<
      JobHandle & {
        path?: string;
        factor?: number;
        sourceDurationSec?: number;
        durationSec?: number;
      }
    > => rpc('speed.retime', { ...target, factor }),
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

  // ---- WU-C4 best-frame thumbnail picker (§3.5; AI job) -------------------

  thumbnail: {
    /**
     * `thumbnail.select {videoId?, candidateId?|path?, start?, end?}` (WU-C3) —
     * the AI best-frame picker. A long job: rpc resolves with `{jobId}` ONLY;
     * the terminal {@link BestFrame} arrives later via a `job.done` notification
     * (subscribe through `onJobDone`). Either a `candidateId` (resolved from the
     * selection cache) OR an explicit `{path,start,end}` span identifies the clip.
     */
    select: (params: {
      videoId?: string;
      candidateId?: string;
      path?: string;
      start?: number;
      end?: number;
    }): Promise<JobHandle> => rpc('thumbnail.select', { ...params }),
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
    // WU-A2: `consentAttested` is REQUIRED by the sidecar and must be `true`;
    // it is a positional argument here (not an options bag with a default) so
    // a caller cannot omit the attestation by accident.
    sampleAdd: (
      path: string,
      consentAttested: true,
      consentNote?: string,
    ): Promise<{ sample: VoiceSample }> =>
      rpc('tts.sample.add', {
        path,
        consentAttested,
        ...(consentNote ? { consentNote } : {}),
      }),
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

  /**
   * `audiomix.*` — the A/V mixer (`sidecar/media_studio/features/audiomix.py`).
   * `merge` lays a music bed / VO UNDER the clip's own audio with a
   * `sidechaincompress` auto-DUCK keyed off the speaker, then EBU R128
   * `loudnorm`; `normalize` runs the loudnorm alone (no bed). BOTH are LONG jobs:
   * the rpc resolves `{jobId}` only and the terminal `{path}` arrives on
   * `job.done`. The video stays under stream copy — the output is a NEW file
   * under `exports/audiomix`, the source is never rewritten.
   *
   * Prefer `platform` over a hard-coded `loudnessTarget`: the sidecar's
   * `PLATFORM_LOUDNESS` map is the single authority for the number, and it fails
   * LOUD (INVALID_PARAMS) on an unknown name rather than silently exporting at
   * the wrong loudness. An explicit `loudnessTarget` still overrides it.
   *
   * Both wrappers are deliberately branch-free: params are forwarded
   * unconditionally and `JSON.stringify` drops `undefined` keys on the wire, so
   * an omitted tunable reaches the sidecar as absent (its default applies).
   */
  audiomix: {
    /** `audiomix.merge {videoId|path, bgPath, ...}` -> {jobId} -> {path}. */
    merge: (params: {
      videoId?: string;
      path?: string;
      bgPath: string;
      bgGainDb?: number;
      duckThreshold?: number;
      duckRatio?: number;
      platform?: string;
      loudnessTarget?: number;
      loudnessTp?: number;
      loudnessLra?: number;
    }): Promise<JobHandle & { path?: string }> => rpc('audiomix.merge', { ...params }),
    /** `audiomix.normalize {videoId|path, ...}` -> {jobId} -> {path}. */
    normalize: (params: {
      videoId?: string;
      path?: string;
      platform?: string;
      loudnessTarget?: number;
      loudnessTp?: number;
      loudnessLra?: number;
    }): Promise<JobHandle & { path?: string }> => rpc('audiomix.normalize', { ...params }),
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

  /** `system.*` — health diagnostic + Phase-8 hardware/advisor probes (direct). */
  system: {
    health: (): Promise<HealthReport> => rpc('system.health'),
    /** `system.probe` — detected VRAM / RAM / CPU / GPU-present (cheap probe). */
    probe: (): Promise<HardwareInfo> => rpc('system.probe'),
    /**
     * `system.advisor {commercial?}` — per-model + per-tier quality-vs-cost
     * verdicts + recommended preset + VRAM budget + grounded notes. When
     * `commercial` is true, non-commercial-licensed models flip to unavailable.
     */
    advisor: (opts?: { commercial?: boolean }): Promise<AdvisorReport> =>
      rpc('system.advisor', opts?.commercial === undefined ? {} : { commercial: opts.commercial }),
    /**
     * `system.recommend {commercial?}` (WU-B3) — the device-aware auto-recommender:
     * composes the existing cheap probes into an actionable {@link Recommendation}
     * (preset + routing + ASR + proposed downloads + rationale). Direct-return; no
     * provider/LLM call. The "Apply" flow reuses the EXISTING mutation RPCs
     * (`providers.applyPreset` / `setFunctionModel` / `settings.set` / `assets.ensure`).
     */
    recommend: (opts?: { commercial?: boolean }): Promise<RecommendResponse> =>
      rpc(
        'system.recommend',
        opts?.commercial === undefined ? {} : { commercial: opts.commercial },
      ),
    /**
     * `system.selfTest` (WU-2) — the first-run self-diagnostic: validates the
     * install END-TO-END (writable data dir, device probe, reframe deps, ASR
     * backend, ffmpeg/ffprobe) and returns a structured pass/fail report with
     * fix hints. Direct-return; fail-open on the sidecar (a broken probe becomes
     * a reported problem, never an exception).
     */
    selfTest: (): Promise<SelfTestReport> => rpc('system.selfTest'),
  },

  /** `asr.engines` — selectable ASR engines (whisper / parakeet) + installed. */
  asr: {
    engines: (): Promise<{ engines: AsrEngine[] }> => rpc('asr.engines'),
  },

  /**
   * `models.*` (WU-models/device) — the local-model brain. `runners` composes the
   * cheap hardware probe + Ollama/LM Studio detect into a device-ranked whisper +
   * LLM recommendation and per-runner detect/pull/install advice. Direct-return;
   * NO provider/LLM call, and it NEVER triggers a pull (the pull hint is advice).
   */
  models: {
    runners: (): Promise<LocalModelPlan> => rpc('models.runners'),
    /**
     * `models.overview {commercial?}` (M1a) — the THIN Models&System compose: the
     * whole panel in ONE read (hardware + advisor tiers/preset + detected runners
     * + device-ranked plan + redacted providers + per-key pool + fail-closed
     * routing policy). Direct-return; the sidecar makes NO provider/LLM call and
     * NEVER mutates settings (a strictly read-only screen, no full key over RPC).
     */
    overview: (opts?: { commercial?: boolean }): Promise<ModelsOverview> =>
      rpc('models.overview', opts?.commercial === undefined ? {} : { commercial: opts.commercial }),
    /**
     * `models.setRoutingPolicy {global?, overrides?}` (M3) — the WRITE half of the
     * single `RoutingPolicy` store. The header toggle sends `{global}`; the
     * Advanced per-function table sends `{overrides}`. The sidecar sanitises the
     * body fail-CLOSED (an out-of-enum / corrupt mode -> `local`, a non-string
     * key dropped; never throws) and persists atomically, returning the policy
     * that actually landed on disk. The DECISION §4 default (`global:'local'`)
     * never auto-promotes — it only moves on an explicit write.
     */
    setRoutingPolicy: (policy: {
      global?: RoutingMode;
      overrides?: Record<string, RoutingMode>;
    }): Promise<{ routingPolicy: RoutingPolicy }> => rpc('models.setRoutingPolicy', policy),
    /**
     * `models.resolveRoute {fn?}` (M5) — the CONCRETE per-function route resolver
     * (DESIGN §2.3 step 4). With a non-empty `fn` it returns `{route}` for that
     * function; otherwise `{routes}` for every canonical AI function. A cloud/auto
     * route with no key on disk degrades LOUDLY to local (`degraded`+`notice`).
     * Read-only: the sidecar makes NO provider call and never mutates settings.
     */
    resolveRoute: (fn?: string): Promise<{ route?: ConcreteRoute; routes?: ConcreteRoute[] }> =>
      rpc('models.resolveRoute', fn ? { fn } : {}),
  },

  /**
   * `readiness.*` — the unified "what works right now" roll-up (WU-8). Strictly
   * read-only: it derives every row from the installed-weight map + redacted
   * settings view, so it triggers no download and opens no socket.
   */
  readiness: {
    /** `readiness.summary()` -> the per-capability readiness rows (WU-8). */
    summary: (): Promise<{ items: ReadinessItem[] }> => rpc('readiness.summary'),
  },

  /**
   * `paths.*` — the resolved on-disk data layout (WU-1). Read-only: a pure
   * path-join the renderer SHOWS so users know WHERE everything lives.
   */
  paths: {
    /** `paths.describe()` -> the resolved data layout (no I/O, no secrets). */
    describe: (): Promise<PathsDescribe> => rpc('paths.describe'),
  },

  /** `providers.*` — Hub key/usage reads (WU-usage-ui surfaces live usage here). */
  providers: {
    /**
     * `providers.list` — the configured provider pool, REDACTED (WU-keys). Every
     * `apiKeys` entry is the last-4 only; the RPC never returns a full key.
     */
    list: (): Promise<ProvidersListResponse> => rpc('providers.list'),
    /**
     * `providers.upsert` — insert or merge a provider entry (WU-keys). RAW keys
     * are stored server-side; the returned list is REDACTED. Pass the full entry
     * (`{id, provider?, baseUrl?, model?, apiKeys?, ...}`); merging into an
     * existing `id` preserves untouched fields.
     */
    upsert: (entry: ProviderEntry): Promise<ProvidersListResponse> =>
      rpc('providers.upsert', { provider: entry }),
    /** `providers.remove` — drop the provider with this id; returns the REDACTED list. */
    remove: (id: string): Promise<ProvidersListResponse> => rpc('providers.remove', { id }),
    /**
     * `providers.testKey` — validate a key with one minimal completion ping
     * (WU-keys). The key is never echoed back: only `ok` + declared
     * `capabilities` + a scrubbed `error` on failure.
     */
    testKey: (args: {
      baseUrl: string;
      apiKey: string;
      model?: string;
      capabilities?: string[];
    }): Promise<TestKeyResult> => rpc('providers.testKey', args),
    /**
     * `providers.revealKey` — the ONE sanctioned plaintext exception (WU-D3).
     * Returns exactly ONE raw key for a TRANSIENT, explicit-click, masked-by-default
     * display. SECURITY: callers MUST hold the returned `key` in a transient ref
     * only — never React state/store, logs, telemetry, or crash reports — and wipe
     * it on re-mask/blur/timeout. `index` (default 0) selects among a provider's
     * rotation-pool keys.
     */
    revealKey: (id: string, index = 0): Promise<RevealKeyResult> =>
      rpc('providers.revealKey', { id, index }),
    /**
     * `providers.setConsent` — set per-data-type egress consent for a provider
     * (WU-keys / SE1). TEXT and FRAMES are independent: only the keys present in
     * the patch change, so revoking `frames` leaves `text` intact. Returns the
     * full consent block.
     */
    setConsent: (provider: string, patch: ProviderConsent): Promise<SetConsentResponse> =>
      rpc('providers.setConsent', { provider, ...patch }),
    /**
     * `providers.usage` — per-key live usage (cached, persisted, stale-flagged;
     * NOT a poller). Keys are redacted; req/token units are returned distinctly.
     */
    usage: (): Promise<{ usage: UsageRow[] }> => rpc('providers.usage'),
    /**
     * `providers.openrouterUsage` (WU-models/device) — per-key OpenRouter COST
     * rows (cumulative credit usage USD): the cost axis alongside `usage`'s
     * calls/tokens. Best-effort; keys are redacted (no full key crosses RPC).
     */
    openrouterUsage: (): Promise<{ usage: OpenRouterUsageRow[] }> =>
      rpc('providers.openrouterUsage'),
    /**
     * `providers.usageAvailability` (WU-D4) — honest per-provider note on whether a
     * provider-side usage API exists (OpenRouter yes; OpenAI/Anthropic need an org
     * admin key; others publish nothing per-key). Never a fabricated number.
     */
    usageAvailability: (): Promise<{ availability: ProviderUsageAvailability[] }> =>
      rpc('providers.usageAvailability'),
    /**
     * `providers.spend` — month-to-date cumulative cloud spend + the configured
     * monthly caps (WU-spend-cap). Read-only; all money is integer cents.
     */
    spend: (): Promise<SpendInfo> => rpc('providers.spend'),
    /** `providers.catalog` — the static curated model catalog (WU-catalog). */
    catalog: (): Promise<CatalogResponse> => rpc('providers.catalog'),
    /** `providers.applyPreset` — resolve a smart preset into routing (WU-presets). */
    applyPreset: (name: string): Promise<PresetResponse> => rpc('providers.applyPreset', { name }),
    /** `providers.setFunctionModel` — override one function's routed provider. */
    setFunctionModel: (function_: string, provider: string): Promise<PresetResponse> =>
      rpc('providers.setFunctionModel', { function: function_, provider }),
    /**
     * `providers.firstRun` — the local-vs-cloud chooser. No arg = READ (returns
     * the local-safe default); a `choice` applies that preset + sets the flag.
     */
    firstRun: (choice?: string): Promise<FirstRunResponse> =>
      rpc('providers.firstRun', choice === undefined ? {} : { choice }),
  },

  /**
   * `savePresets.*` — named `{autosave, exportDefaults}` bundles (WU-10/WU-11).
   * The sidecar `settings.set` is a SHALLOW top-level merge, so every mutating
   * handler read-modify-writes the whole `savePresets` block server-side; the
   * client just mirrors the frozen method names + param/result shapes.
   */
  savePresets: {
    /** `savePresets.list()` -> the saved bundle map + last-applied name. */
    list: (): Promise<SavePresetsBlock> => rpc('savePresets.list'),
    /** `savePresets.apply({name})` -> the now-active name + its resolved bundle. */
    apply: (name: string): Promise<{ active: string; savePreset: SavePreset }> =>
      rpc('savePresets.apply', { name }),
    /**
     * `savePresets.upsert({name, autosave?, exportDefaults?})` -> the bundle map.
     * Omitted parts default to `{}` server-side (filled from live settings).
     */
    upsert: (
      name: string,
      bundle?: { autosave?: AutosaveSettings; exportDefaults?: ExportDefaults },
    ): Promise<{ presets: Record<string, SavePreset> }> =>
      rpc('savePresets.upsert', { name, ...(bundle ?? {}) }),
    /** `savePresets.remove({name})` -> the surviving bundle map + active name. */
    remove: (name: string): Promise<{ presets: Record<string, SavePreset>; active: string }> =>
      rpc('savePresets.remove', { name }),
  },

  /** `recipes.*` — saved multi-step pipelines run in one shot. */
  recipes: {
    list: (): Promise<{ recipes: SavedRecipe[] }> => rpc('recipes.list'),
    save: (recipe: SavedRecipe | Omit<SavedRecipe, 'id'>): Promise<{ recipe: SavedRecipe }> =>
      rpc('recipes.save', { recipe }),
    delete: (id: string): Promise<{ ok: boolean }> => rpc('recipes.delete', { id }),
    run: (id: string): Promise<JobHandle> => rpc('recipes.run', { id }),
  },

  /**
   * `social.*` — C14 direct publish / scheduling.
   *
   * Storage + honest decisions only. No token ever crosses this bridge: OAuth
   * tokens live in the main-process keystore and are injected there, so the
   * renderer never holds credential material for a platform.
   */
  social: {
    /** The per-platform capability matrix (what each platform actually permits). */
    capabilities: (): Promise<{ platforms: SocialCapability[] }> => rpc('social.capabilities'),
    /**
     * PREVIEW where a publish time would be held, WITHOUT committing anything —
     * so the "Reframe must be running then" disclosure can be shown while the user
     * is still choosing a time rather than after they have queued it.
     */
    plan: (platform: string, publishAt?: number | null): Promise<{ plan: SocialSchedulePlan }> =>
      rpc('social.plan', { platform, publishAt: publishAt ?? null }),
    enqueue: (job: SocialPublishJob): Promise<{ entry: SocialQueueEntry }> =>
      rpc('social.enqueue', { job }),
    queue: (): Promise<{ entries: SocialQueueEntry[] }> => rpc('social.queue'),
    cancel: (id: string): Promise<{ ok: boolean }> => rpc('social.cancel', { id }),
  },

  /** `exportPresets.*` — server-persisted platform export presets (WU11). */
  exportPresets: {
    list: (): Promise<{ presets: ExportPreset[] }> => rpc('exportPresets.list'),
    save: (preset: ExportPreset | Omit<ExportPreset, 'id'>): Promise<{ preset: ExportPreset }> =>
      rpc('exportPresets.save', { preset }),
    delete: (id: string): Promise<{ ok: boolean }> => rpc('exportPresets.delete', { id }),
    reset: (): Promise<{ presets: ExportPreset[] }> => rpc('exportPresets.reset'),
  },

  /** `templates.*` — reusable edit templates (recipe + controls + targets). */
  templates: {
    list: (): Promise<{ templates: Template[] }> => rpc('templates.list'),
    save: (template: Template | Omit<Template, 'id'>): Promise<{ template: Template }> =>
      rpc('templates.save', { template }),
    delete: (id: string): Promise<{ ok: boolean }> => rpc('templates.delete', { id }),
    apply: (templateId: string, videoId: string): Promise<JobHandle> =>
      rpc('templates.apply', { templateId, videoId }),
  },

  /** `batch.*` — durable, resumable many-source queue (WU11). */
  batch: {
    create: (
      name: string,
      templateId: string,
      sourceVideoIds: string[],
    ): Promise<{ batch: BatchState }> => rpc('batch.create', { name, templateId, sourceVideoIds }),
    /**
     * `batch.plan {id, confirmCloudBudget?, acknowledged?}` -> {consent} — the pure
     * pre-run consent surface (DESIGN §9.1) for a batch's still-pending sources
     * WITHOUT starting a job (zero provider calls). Unlike `start`, it ALWAYS returns
     * a fully-populated run/skip surface so the renderer can render the §9.1 card
     * before deciding whether to `start`.
     */
    plan: (
      id: string,
      opts?: { confirmCloudBudget?: boolean; acknowledged?: boolean },
    ): Promise<{ consent: BatchConsent }> => rpc('batch.plan', { id, ...(opts ?? {}) }),
    start: (
      id: string,
      opts?: { confirmCloudBudget?: boolean; acknowledged?: boolean },
    ): Promise<JobHandle> => rpc('batch.start', { id, ...(opts ?? {}) }),
    status: (id: string): Promise<{ batch: BatchState }> => rpc('batch.status', { id }),
    list: (): Promise<{ batches: BatchSummary[] }> => rpc('batch.list'),
    cancel: (id: string): Promise<{ ok: boolean }> => rpc('batch.cancel', { id }),
    resume: (id: string): Promise<JobHandle & { status?: BatchStatus }> =>
      rpc('batch.resume', { id }),
    delete: (id: string): Promise<{ ok: boolean }> => rpc('batch.delete', { id }),
  },

  /** `diarize.start` — token-free speaker labelling (long job -> {transcript}). */
  diarize: {
    start: (
      videoId: string,
      threshold?: number,
    ): Promise<JobHandle & { transcript?: Transcript }> =>
      rpc('diarize.start', threshold === undefined ? { videoId } : { videoId, threshold }),
  },

  /**
   * `index.*` (WU-A5/A6) — the per-video semantic transcript index. `build` is a
   * long job (embed every segment + persist vectors); `search` / `status` are
   * direct-return. Params are forwarded unconditionally — `toEqual` ignores
   * `undefined` keys, so a branch-free wrapper keeps the wire contract exact.
   */
  index: {
    /** `index.build {videoId}` -> {jobId} — embed + persist the segment vectors. */
    build: (videoId: string): Promise<JobHandle> => rpc('index.build', { videoId }),
    /** `index.status {videoId}` -> {built,...} — pure file read (no provider call). */
    status: (videoId: string): Promise<IndexStatus> => rpc('index.status', { videoId }),
    /** `index.search {videoId,query,topK?}` -> {hits} — one query embed + cosine. */
    search: (videoId: string, query: string, topK = 8): Promise<{ hits: IndexHit[] }> =>
      rpc('index.search', { videoId, query, topK }),
  },

  /**
   * `director.*` — the prompt-driven AI video editing spine (WU-plan-rpc /
   * WU-evaluate). `plan`/`apply`/`undo` are JOB-based (resolve `{jobId}`; the
   * typed result arrives on `job.done`); `previewCost`/`evaluate` are SYNCHRONOUS
   * (resolve their payload directly). Field names are FROZEN, identical to the
   * sidecar `director_*` handlers (`handlers/composition.py`).
   */
  director: {
    /** `director.plan {videoId, goal}` -> {jobId}; job.done = {planId, editPlan, preview}. */
    plan: (videoId: string, goal: string): Promise<JobHandle> =>
      rpc('director.plan', { videoId, goal }),
    /** `director.previewCost {planId}` -> per-data-type cost/route/egress (ZERO provider calls). */
    previewCost: (planId: string): Promise<DirectorPreview> =>
      rpc('director.previewCost', { planId }),
    /**
     * `director.apply {planId, confirmBudget?, opOverrides?, order?}` -> {jobId};
     * job.done = DirectorApplyResult. `review` carries the user-reviewed op statuses
     * (`opOverrides`: planned<->dropped edits) + `order` (the reordered op ids) so the
     * merged plan applies the user's edits; absent = apply the stored plan verbatim.
     */
    apply: (
      planId: string,
      confirmBudget?: string,
      review?: {
        opOverrides: readonly { id: string; status: DirectorOpStatus }[];
        order: readonly string[];
      },
    ): Promise<JobHandle> =>
      rpc('director.apply', {
        planId,
        ...(confirmBudget === undefined ? {} : { confirmBudget }),
        ...(review ? { opOverrides: review.opOverrides, order: review.order } : {}),
      }),
    /** `director.undo {planId}` -> {jobId}; re-applies the recorded inverse plan. */
    undo: (planId: string): Promise<JobHandle> => rpc('director.undo', { planId }),
    /** `director.evaluate {planId}` -> objective before/after metrics (synchronous). */
    evaluate: (planId: string): Promise<DirectorEval> => rpc('director.evaluate', { planId }),
  },

  /**
   * `reframe.*` (V1.1 Lane R) — the manual per-shot correction surface. All are a
   * PURE compose (no heavy engine): `shotPlan` derives an editable {@link ShotPlan}
   * from an already-computed reframe trace, `shotPlanFor` derives one from a
   * rendered clip's persisted decision sidecar, and `applyOverrides` resolves a
   * user's per-shot edits and returns the `affected` shot indices.
   *
   * HONEST LIMIT (measured 2026-08-09 against
   * `sidecar/tests/test_handlers_rpc_surface.py:118-121`): the whole registered
   * `reframe.*` surface is exactly these four names plus `reframe.eval`. There is
   * **no** `reframe.render` and **no** method that persists overrides, so
   * `affected` cannot be handed to anything that re-encodes. Any UI built on this
   * must say so rather than offer a re-render loop that cannot run.
   */
  reframe: {
    /** `reframe.shotPlan {trace, sourceWidth, sourceHeight, fps}` -> {plan}. */
    shotPlan: (args: {
      trace: unknown;
      sourceWidth: number;
      sourceHeight: number;
      fps: number;
    }): Promise<{ plan: ShotPlan }> => rpc('reframe.shotPlan', { ...args }),
    /**
     * `reframe.shotPlanFor {clip}` -> `{plan|null, engine, aspect}`.
     *
     * `plan: null` is the HONEST "this clip carries no per-shot decisions"
     * answer (the engine that rendered it dropped no `<clip>.reframe.json`
     * sidecar) — NOT an error. Callers must render that empty state rather than
     * a correction panel over invented data.
     */
    shotPlanFor: (
      clip: string,
    ): Promise<{ plan: ShotPlan | null; engine: string; aspect: string }> =>
      rpc('reframe.shotPlanFor', { clip }),
    /** `reframe.applyOverrides {plan, overrides}` -> {plan, affected}. */
    applyOverrides: (args: {
      plan: ShotPlan;
      overrides: readonly ShotOverride[];
    }): Promise<{ plan: ShotPlan; affected: number[] }> =>
      rpc('reframe.applyOverrides', { plan: args.plan, overrides: args.overrides }),
  },

  /**
   * v1.5 expose-engines: two-pass vidstab camera-shake removal.
   *
   * The engine (`features/stabilize.py`), the RPC registration (`:496`) and a
   * dedicated output directory (`handlers/library_ops.py:418` "stabilized") all
   * predate this wrapper — `stabilize.run` simply had no typed caller, so it
   * appeared ZERO times anywhere under `app/`. The Workspace "Stabilize" tab
   * (`features/Stabilize.tsx`) is the first consumer.
   */
  stabilize: {
    /**
     * `stabilize.run {videoId|path}` -> `{jobId}` -> job.done
     * `{path, stabilized[, notice]}`.
     *
     * A bare string is the common `videoId` case. `stabilized:false` with a
     * `notice` is the ffmpeg-has-no-libvidstab SKIP (the source path comes back
     * untouched) — it is REPORTED, never a silent success, so callers must not
     * treat `path` as a steadied result without checking `stabilized`.
     */
    run: (
      target: string | { videoId?: string; path?: string },
    ): Promise<
      JobHandle & {
        path?: string;
        stabilized?: boolean;
        notice?: { type: string; message: string };
      }
    > => rpc('stabilize.run', typeof target === 'string' ? { videoId: target } : { ...target }),
  },
} as const;

export default client;
