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
 * WU-C4 `thumbnail.select` job result (the `job.done.result` payload, NOT the
 * immediate rpc resolution which is only `{jobId}`). Field names mirror the
 * sidecar `thumbnail_select` done payload (`handlers.py` WU-C3) EXACTLY.
 *
 * `degraded` is `true` when no consented cloud model + no local weights were
 * available, so the deterministic clip-midpoint frame was used (zero egress).
 * The renderer surfaces this as a visible + announced note rather than swapping
 * silently (DESIGN §3.6).
 */
export interface BestFrame {
  /** Source-absolute time (seconds) of the chosen thumbnail frame. */
  frameTimeSec: number;
  /** Absolute path of the written poster (inside the exports root). */
  thumbnailPath: string;
  /** The scorer's confidence for the picked frame (0.0 on the degrade path). */
  score: number;
  /** True when the midpoint fallback was used (no vision model available). */
  degraded: boolean;
}

/**
 * WU-A6 semantic-search result row (`index.search` → `{hits:[...]}`). Mirrors the
 * sidecar `semantic_index.Hit` TypedDict (`features/semantic_index.py:35`): the
 * source segment's index/span/text plus its cosine `score`.
 */
export interface IndexHit {
  segmentIndex: number;
  start: number;
  end: number;
  text: string;
  score: number;
}

/**
 * WU-A6 semantic-index status (`index.status` → this shape). An unbuilt video
 * reports `{built:false, segmentCount:0, model:null, builtAt:null, dim:0}`
 * (`handlers.py:1178`).
 */
export interface IndexStatus {
  built: boolean;
  segmentCount: number;
  model: string | null;
  builtAt: string | null;
  dim: number;
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

// ---- Phase-8 System Advisor ("Models & System" panel) --------------------
//
// Wire shapes for `system.advisor` / `system.probe` / `asr.engines`. Field
// names are FROZEN, identical to the sidecar `_advisor_report_to_wire` /
// `system_probe` / `asr_engines` payloads (camelCase on the wire already — no
// snake_case shim needed). Verdict semantics: `ok` -> "Will run" (green),
// `degraded` -> "Tight" (amber), `unavailable` -> "Won't run" (red).

/** A three-state capability verdict shared by components and tiers. */
export type AdvisorVerdict = 'ok' | 'degraded' | 'unavailable';

/** One model/component's quality-vs-cost verdict for the panel. */
export interface ComponentStatus {
  name: string;
  present: boolean;
  verdict: AdvisorVerdict;
  /** Resident VRAM @ infer in MB, or null for CPU/no-model floors. */
  vramMb: number | null;
  licenseCommercialOk: boolean;
  /** Grounded tooltip copy (improves / why-ok / why-blocked) from the manifest. */
  reason: string;
}

/** One tier's rolled-up verdict + the component names it bundles. */
export interface TierStatus {
  tier: number;
  label: string;
  verdict: AdvisorVerdict;
  components: string[];
}

/** The full `system.advisor` report — a JSON tree the panel renders 1:1. */
export interface AdvisorReport {
  components: ComponentStatus[];
  tiers: TierStatus[];
  recommendedPreset: string;
  vramBudgetMb: number;
  notes: string[];
}

/** Probed hardware facts (`system.probe`). Any field null when undetectable. */
export interface HardwareInfo {
  vramMb: number | null;
  ramMb: number | null;
  cpuCount: number | null;
  gpuPresent: boolean;
}

/** One selectable ASR engine row (`asr.engines`). */
export interface AsrEngine {
  id: string;
  label: string;
  installed: boolean;
}

/**
 * The resolved on-disk data layout (`paths.describe`, WU-1, read-only). Layout
 * only — no key/secret string ever appears here. `subDirs` names the per-feature
 * derivative folders the sidecar writes into.
 */
export interface PathsDescribe {
  dataDir: string;
  projectsDir: string;
  exportsDir: string;
  settingsPath: string;
  libraryPath: string;
  subDirs?: Record<string, string>;
}

/**
 * One capability's readiness state (`readiness.summary`, WU-8). The five states
 * are distinguished by TEXT (the badge label), never hue alone (WCAG 1.4.1):
 * `ready`, `needsDownload`, `needsKey`, `needsConsent`, `unavailable`.
 */
export type ReadinessStatus =
  | 'ready'
  | 'needsDownload'
  | 'needsKey'
  | 'needsConsent'
  | 'unavailable';

/** The actionable fix a not-ready capability offers (null when `ready`/blocked). */
export interface ReadinessAction {
  /** `assets.ensure` (download), `openProviders` (add a key), `setConsent`. */
  kind: 'assets.ensure' | 'openProviders' | 'setConsent';
  /** The asset names to ensure (only for `assets.ensure`). */
  assets?: string[];
  /** The provider id the action targets (key/consent actions). */
  provider?: string;
}

/** One rolled-up capability row from `readiness.summary` (WU-8). */
export interface ReadinessItem {
  /** Stable capability id, e.g. `tier1-multimodal` or `ai.select`. */
  capability: string;
  /** Human-friendly capability name. */
  label: string;
  status: ReadinessStatus;
  /** Plain-language reason it is not ready ("" when ready). */
  blockedBy: string;
  /** The fix action, or null when ready or blocked with no fix. */
  action: ReadinessAction | null;
}

/**
 * One per-key usage row from `providers.usage` (WU-usage-ui). The pool accounts
 * usage from optimistic decrement + parsed 429 / X-RateLimit-* headers (NOT a
 * poller). `key` is ALWAYS the REDACTED last-4 (no full key crosses RPC).
 * `unit` is "req" (request-limited) or "token" (token-limited) — the two are
 * NEVER summed. `stale`/`lastCheckedAt` come from the 10-min staleness flag.
 */
export interface UsageRow {
  provider: string;
  /** Redacted last-4 (e.g. "…WXYZ") — never a full key. */
  key: string;
  used: number;
  /** The quota ceiling, or null when unknown (no rate-limit header yet). */
  max: number | null;
  /** "req" | "token" — the limit dimension; req and token are never summed. */
  unit: string;
  /** Epoch seconds the window resets, or null. */
  resetAt: number | null;
  /** True once the cached row is older than the 10-min staleness threshold. */
  stale: boolean;
  /** Epoch seconds this row was last observed (drives "last checked Xm ago"). */
  lastCheckedAt: number | null;
}

/**
 * One configured provider entry as returned REDACTED by `providers.list` /
 * `providers.upsert` / `providers.remove` (WU-keys). The RPC NEVER returns a
 * full key: every `apiKeys` entry is already the redacted last-4 (e.g. "…WXYZ").
 * `id` is the stable provider slug (e.g. "groq"); `provider` is the display
 * name (e.g. "Groq") and is also the key consent is tracked under.
 */
export interface ProviderEntry {
  /** Stable provider slug used as the upsert/remove id (e.g. "groq"). */
  id: string;
  /** Display name (e.g. "Groq"); also the per-provider consent key. */
  provider?: string;
  /** OpenAI-compatible base URL the rotation pool calls. */
  baseUrl?: string;
  /** Default model id for this provider, when set. */
  model?: string;
  /** REDACTED keys (last-4 only) — never a full key over RPC. */
  apiKeys?: string[];
  /** Whether the provider participates in the rotation pool. */
  enabled?: boolean;
  /** What this provider can ingest ("text" / "vision"). */
  capabilities?: string[];
  /** The free-limit unit ("req" / "token"). */
  unit?: string;
}

/** The `providers.list` / `providers.upsert` / `providers.remove` payload (WU-keys). */
export interface ProvidersListResponse {
  providers: ProviderEntry[];
}

/**
 * `providers.testKey` result (WU-keys): a validation ping through the provider
 * seam. The key is NEVER echoed back — only `ok`, the declared `capabilities`,
 * and a SCRUBBED `error` string on failure (the live key is stripped at the
 * provider construction site, so a 4xx body never leaks it over RPC).
 */
export interface TestKeyResult {
  ok: boolean;
  capabilities?: string[];
  error?: string;
}

/**
 * One provider's per-data-type consent (`consent.perProvider[provider]`). TEXT
 * (transcripts) and FRAMES (vision) are SEPARATE, independently-revocable
 * opt-ins (SE1). Either may be absent (treated as not-yet-granted = false).
 */
export interface ProviderConsent {
  text?: boolean;
  frames?: boolean;
}

/** The full consent block returned by `providers.setConsent` (WU-keys / SE1). */
export interface ConsentBlock {
  perProvider?: Record<string, ProviderConsent>;
}

/** `providers.setConsent` response (WU-keys / SE1): the full consent block. */
export interface SetConsentResponse {
  consent: ConsentBlock;
}

/**
 * One curated model row from `providers.catalog` (WU-catalog). PURE metadata —
 * no keys/URLs. `perTaskTier` is keyed by the five task ids (moment_find /
 * caption / translation / vision / edit_plan) -> grade string (S/A/B/C/na).
 */
export interface CatalogEntry {
  id: string;
  provider: string;
  model: string;
  capabilities: string[];
  contextTokens: number;
  perTaskTier: Record<string, string>;
  costClass: string;
  freeLimits: string;
  freeLimitScore: number;
  unit: string;
  trainsOnInput: boolean | 'conditional';
  privacyTier: string;
  recommendedFor: string[];
  notes: string;
  asOfDate: string;
}

/** The `providers.catalog` payload (WU-catalog): dated curated catalog + picks. */
export interface CatalogResponse {
  asOfDate: string;
  unit: string[];
  tasks: string[];
  topPicks: Record<string, string>;
  providers: CatalogEntry[];
}

/** One per-function routing slot: the chosen provider id (or "local") + fallback. */
export interface RoutingSlot {
  provider: string;
  fallback: string[];
}

/** The resolved per-function routing (WU-presets). */
export interface RoutingBlock {
  perFunction: Record<string, RoutingSlot>;
}

/** `providers.applyPreset` / `setFunctionModel` response (WU-presets). */
export interface PresetResponse {
  activePreset: string;
  routing: RoutingBlock;
}

/**
 * WU-B3 one proposed (never auto-triggered) asset download inside a
 * {@link Recommendation}. Field names mirror the sidecar `recommender.DownloadItem`.
 */
export interface RecommendationDownload {
  assetName: string;
  label: string;
  sizeMb: number;
  reason: string;
}

/**
 * WU-B3 the device-aware auto-recommender's actionable plan
 * (`system.recommend` -> `{recommendation}`). PURE on the sidecar: composes the
 * advisor report + installed-state + detected local servers into a concrete
 * preset + per-function routing + ASR pick + proposed downloads + rationale.
 * Field names are FROZEN, identical to the sidecar `recommender.Recommendation`.
 * An EMPTY `routing.perFunction` signals the G-B1 "could not detect" fallback.
 */
export interface Recommendation {
  preset: string;
  routing: RoutingBlock;
  /** The recommended ASR engine id, or null when no engine is installed. */
  asrEngine: string | null;
  downloads: RecommendationDownload[];
  rationale: string[];
}

/** `system.recommend` response (WU-B3). */
export interface RecommendResponse {
  recommendation: Recommendation;
}

/** `providers.firstRun` response (WU-presets P1 #6 first-run chooser). */
export interface FirstRunResponse {
  firstRunChoiceMade: boolean;
  /** Present on a READ (no choice): the local-safe default preset name. */
  default?: string;
  /** Present once a choice applied: the resolved preset + routing. */
  activePreset?: string;
  routing?: RoutingBlock;
}

// ---------------------------------------------------------------------------
// UX / QoL bundle (WU-0): additive settings shapes downstream WUs consume.
// These mirror the sidecar DEFAULT_SETTINGS QoL keys (settings_store.py) and are
// purely additive — they never widen or break the existing settings surface.
// ---------------------------------------------------------------------------

/** Workspace autosave config (WU-11): the renderer debounces `project.save`. */
export interface AutosaveSettings {
  enabled: boolean;
  debounceMs: number;
}

/** Pre-selected export formats the export UI offers first (WU-11). */
export interface ExportDefaults {
  subtitleFormat: string;
  nleFormat: string;
  nleFps: number;
}

/**
 * One saved bundle (WU-10/WU-11): the autosave + export-default choices a named
 * preset carries. Both parts are `Partial` because the sidecar `upsert` stores
 * `{}` for an omitted part (the renderer fills the gaps from live settings).
 */
export interface SavePreset {
  autosave: Partial<AutosaveSettings>;
  exportDefaults: Partial<ExportDefaults>;
}

/**
 * Saved export/pipeline presets (WU-10/WU-11). `presets` is a name->preset map;
 * `active` is the last-applied preset name. NOTE: the sidecar `settings.set` is a
 * SHALLOW top-level merge — writing `savePresets` REPLACES the whole block, so a
 * partial update must read-modify-write the full block to preserve `presets`.
 */
export interface SavePresetsBlock {
  presets: Record<string, SavePreset>;
  active: string;
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

// ---- Repurpose bundle (WU11) — field names identical to the sidecar -------
//
// Wire schemas for the `exportPresets.*` / `templates.*` / `batch.*` groups
// (DESIGN §7 / §8). Field names are FROZEN and identical to the Python side
// (`export_presets.py`, `templates.py`, `batch.py`) — the §17 house rule.

/**
 * One server-persisted platform export preset (`export_presets.py`). `aspect` is
 * a ratio string ("9:16"); `minSec`/`maxSec` are clamped into the hard 20-60 s
 * window on save; `captionStyle`/`reframeEngine` are validated id sets.
 */
export interface ExportPreset {
  id: string;
  label: string;
  aspect: string;
  minSec: number;
  maxSec: number;
  count: number;
  captionStyle: string;
  reframeEngine: string;
}

/** One template step — a recipe step (`templates.py` reuses `normalize_recipe`). */
export interface TemplateStep {
  method: string;
  params: Record<string, unknown>;
  label: string;
}

/**
 * A reusable edit template (`templates.py`): a recipe (`{id, name, steps}`) plus
 * the additive `defaultControls` (shared knobs) and `exportTargets` (preset ids
 * the export step fans out to).
 */
export interface Template {
  id: string;
  name: string;
  steps: TemplateStep[];
  defaultControls: Record<string, unknown>;
  exportTargets: string[];
}

/** One source's terminal/transient status inside a batch (`batch.py`). */
export type BatchItemStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled' | 'skipped';

/**
 * One source row of a batch (`batch.py`). `skipReason` carries the visible-skip
 * contract (DESIGN §9.1) — a skipped source is attributed, never silently absent.
 */
export interface BatchItem {
  videoId: string;
  status: BatchItemStatus;
  jobId?: string;
  error?: string;
  skipReason?: string;
  results?: unknown;
}

/** Aggregate batch status (`batch.py` `derive_status`). */
export type BatchStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled' | 'partial';

/** A full durable batch record (`batch.py` `BatchState`). */
export interface BatchState {
  id: string;
  name: string;
  templateId: string;
  status: BatchStatus;
  createdAt: number;
  items: BatchItem[];
  /** Live-overlay `pct` while the parent job runs (`_merge_live_status`). */
  pct?: number;
}

/** Per-status counts in a `BatchSummary` (`batch.py` `_summarize`). */
export interface BatchCounts {
  total: number;
  done: number;
  error: number;
  skipped: number;
  queued: number;
  running: number;
  cancelled: number;
}

/** A lightweight batch summary (heavy per-item data omitted) — `batch.list`. */
export interface BatchSummary {
  id: string;
  name: string;
  templateId: string;
  status: BatchStatus;
  createdAt: number;
  counts: BatchCounts;
}

/** One per-source consent decision from `batch.start`'s `plan_consent` (§9.1). */
export interface BatchConsentDecision {
  videoId: string;
  action: 'run' | 'skip';
  skipReason: string | null;
  confirmBudget: string | null;
  willEgress: boolean;
  cacheHit: boolean;
}

/** The pre-run consent surface (`batch.py` `plan_consent`, DESIGN §9.1). */
export interface BatchConsent {
  decisions: BatchConsentDecision[];
  willRun: number;
  willSkip: number;
  costEst: Record<string, unknown>;
  budget: Record<string, unknown>;
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

// ---- Director (prompt-driven editing) wire shapes ------------------------
//
// Field names are FROZEN, identical to the sidecar `director_*` handler payloads
// (`handlers.py:1778+`) + the `edit_plan.py` canonical serializer + the
// `director_eval.evaluate` result. Spans are `[startMs, endMs]` integer pairs or
// null (whole-timeline ops); kind/status enumerate the frozen vocabularies.

/** The v1 op toolbox (DESIGN §2.2) — mirrors the sidecar `OpKind` Literal. */
export type DirectorOpKind =
  | 'trim'
  | 'cut'
  | 'removeSilence'
  | 'removeFillers'
  | 'reorder'
  | 'retime'
  | 'reframe'
  | 'zoomPan'
  | 'caption'
  | 'translateCaption'
  | 'overlayText'
  | 'lowerThird'
  | 'export'
  | 'stitchPanorama'
  | 'regenScroll'
  | 'ocrExtractList';

/** Per-op lifecycle — mirrors the sidecar `OpStatus` Literal. */
export type DirectorOpStatus = 'planned' | 'applied' | 'failed' | 'dropped';

/** One ordered, reversible operation (mirrors `edit_plan.EditOp` on the wire). */
export interface DirectorOp {
  id: string;
  kind: DirectorOpKind;
  /** Source range [startMs, endMs], or null for whole-timeline ops. */
  span: [number, number] | null;
  params: Record<string, unknown>;
  reversible: boolean;
  /** Model/engine text — rendered as PLAIN TEXT, NEVER trusted as instructions. */
  rationale: string;
  status: DirectorOpStatus;
  /** Typed reason a drop/fail carries (e.g. "span-exceeds-clip"), or null. */
  statusReason: string | null;
}

/** The typed, ordered edit document (mirrors `edit_plan.EditPlan` on the wire). */
export interface DirectorEditPlan {
  planId: string;
  videoId: string;
  goal: string;
  sourceHash: string;
  ops: DirectorOp[];
  /** The undo plan recorded at apply-time (empty until applied). */
  inverse: DirectorOp[];
}

/** `director.plan` job.done payload (`handlers.py:1816`). */
export interface DirectorPlanResult {
  planId: string;
  editPlan: DirectorEditPlan;
  /** Canonical JSON of the validated plan (cache/diff anchor). */
  preview: string;
}

/** `director.apply` / `director.undo` job.done payload (`handlers.py:1940`). */
export interface DirectorApplyResult {
  planId: string;
  /** Per-op status rows after the apply walk (serialized ops). */
  opsStatus: DirectorOp[];
  /** Present on apply (not undo): the recorded inverse plan. */
  inversePlan?: DirectorEditPlan;
  projectCopyPath: string;
}

/** One per-data-type cost/route row (`director.previewCost`, `handlers.py:1846`). */
export interface DirectorCostRow {
  /** The routed function id: "editPlan" (text) or "vision" (frames/OCR). */
  function: string;
  route: string;
  costEst: number;
  /** True when this data type would leave the machine (frames = heaviest privacy). */
  willEgress: boolean;
  cacheHit: boolean;
  /** The budget-ack token; echo as `confirmBudget` on apply. */
  cacheKey: string;
}

/** `director.previewCost` payload (`handlers.py:1856`). */
export interface DirectorPreview {
  perFunction: DirectorCostRow[];
}

/** The four objective metrics (`director_eval._LOWER_IS_BETTER` keys). */
export interface DirectorMetrics {
  jerk: number;
  cutRhythm: number;
  silenceRatio: number;
  ocrCoverage: number;
}

/** `director.evaluate` payload (`director_eval.evaluate`, `handlers.py:2062`). */
export interface DirectorEval {
  /** Single [0,1] summary derived ONLY from the objective deltas. */
  score: number;
  /** Signed improvement per metric (positive = better). */
  deltas: DirectorMetrics;
  beforeAfter: { before: DirectorMetrics; after: DirectorMetrics };
  /** Optional qualitative note — descriptive only, NEVER moves `score`. */
  judgeNote: string | null;
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
  status: 'queued' | 'running' | 'done' | 'error' | 'cancelled' | 'interrupted';
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
    /** `library.thumbnail {id}` — idempotent source-video poster extraction (WU-4). */
    thumbnail: (id: string): Promise<{ thumbnailPath: string }> => rpc('library.thumbnail', { id }),
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
  },

  /** `asr.engines` — selectable ASR engines (whisper / parakeet) + installed. */
  asr: {
    engines: (): Promise<{ engines: AsrEngine[] }> => rpc('asr.engines'),
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
   * sidecar `director_*` handlers (`handlers.py:1778+`).
   */
  director: {
    /** `director.plan {videoId, goal}` -> {jobId}; job.done = {planId, editPlan, preview}. */
    plan: (videoId: string, goal: string): Promise<JobHandle> =>
      rpc('director.plan', { videoId, goal }),
    /** `director.previewCost {planId}` -> per-data-type cost/route/egress (ZERO provider calls). */
    previewCost: (planId: string): Promise<DirectorPreview> =>
      rpc('director.previewCost', { planId }),
    /** `director.apply {planId, confirmBudget?}` -> {jobId}; job.done = DirectorApplyResult. */
    apply: (planId: string, confirmBudget?: string): Promise<JobHandle> =>
      rpc('director.apply', confirmBudget === undefined ? { planId } : { planId, confirmBudget }),
    /** `director.undo {planId}` -> {jobId}; re-applies the recorded inverse plan. */
    undo: (planId: string): Promise<JobHandle> => rpc('director.undo', { planId }),
    /** `director.evaluate {planId}` -> objective before/after metrics (synchronous). */
    evaluate: (planId: string): Promise<DirectorEval> => rpc('director.evaluate', { planId }),
  },
} as const;

export default client;
