// lib/rpc/schemas.ts - the section 3 data schemas + the frozen section 1 bridge
// surface types (CONTRACTS.md section 1). Split out of the former monolithic
// lib/rpc.ts (F4b quality cleanup): every later lane touches this surface, so the
// type declarations live here, the runtime client lives in ./client, and ./index
// re-exports both so existing `from '../lib/rpc'` importers keep ONE entry point.
// Field names are identical to the Python/sidecar side - do NOT rename.

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
  /**
   * v1.2.0 WU3: unified-scorer HIGHLIGHT score — a 0..1 fusion of the legacy LLM
   * score with the present-weighted multimodal signal boost. Stamped ONLY by the
   * sidecar's `select_unified` path (absent on the frozen transcript path); the
   * renderer normalizes it to a 0-100 badge. Distinct from `viralityPct` (a
   * within-batch percentile) — surfacing only, never used for selection/ranking.
   */
  signalScore?: number;
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

/**
 * L3/L4 lineage node — a full PROV entity row (`lineage._row_to_entity`). Richer
 * than {@link Video} (carries `kind`/`role`/`contentHash`) because a node can be
 * a source, a derived output or an export. Field names mirror the sidecar EXACTLY.
 */
export interface LineageEntity {
  id: string;
  kind: string;
  role: string;
  path: string;
  title: string;
  addedAt: string;
  durationSec: number;
  contentHash: string | null;
  hasTranscript: boolean;
  thumbnailPath: string;
}

/**
 * L3 loud stub for a `derived_from` endpoint with no `entity` row (an input
 * referenced by id but never added as a library source). Surfaced — never
 * silently dropped — so the card can show "source no longer in library".
 */
export interface LineageMissing {
  id: string;
  missing: true;
}

/** One ancestor/descendant: a resolved entity OR a loud missing stub. */
export type LineageNode = LineageEntity | LineageMissing;

/**
 * L4 provenance card data — the producing activity + agent of an asset
 * (`lineage._load_provenance`). `null` for a raw imported source. `route` is the
 * resolved M3 RoutingPolicy the job took; `params` is the redacted job params.
 * Field names mirror the sidecar EXACTLY.
 */
export interface LineageProvenance {
  op: string;
  status: string;
  startedAt: string;
  endedAt: string;
  params: Record<string, unknown> | null;
  appVersion: string | null;
  preset: string | null;
  route: Record<string, unknown> | null;
}

/**
 * L3/L4 `library.lineage {id}` result — the queried node plus its ancestors
 * (what it was made from), descendants (what was made from it) and provenance
 * card data. `entity` is `null` when the id is unknown.
 */
export interface LineageResult {
  id: string;
  entity: LineageEntity | null;
  ancestors: LineageNode[];
  descendants: LineageNode[];
  provenance: LineageProvenance | null;
}

/**
 * L5 `library.reveal {id}` source row — one by-path source the asset derives from,
 * plus whether its file is still on disk. Field names mirror the sidecar EXACTLY.
 */
export interface RevealSource {
  id: string;
  path: string;
  title: string;
  exists: boolean;
}

/**
 * L5 `library.reveal {id}` result — the by-path source file(s) to reveal in the OS
 * file explorer. `missing` lists the source paths no longer on disk (loud — the
 * UI offers a hash-verified relink rather than silently skipping).
 */
export interface RevealResult {
  id: string;
  sources: RevealSource[];
  missing: string[];
}

/**
 * L5 `library.regenerate {id}` result — the replay descriptor for an asset: the
 * producing `op` + its redacted `params`. `ready` is `false` (and `missing` is
 * populated) when any source file is gone; the caller must relink before re-running.
 */
export interface RegenerateResult {
  id: string;
  op: string;
  params: Record<string, unknown> | null;
  missing: string[];
  ready: boolean;
}

/** L5 `library.relink {id, path}` / `library.pinHash {id}` result — the updated entity row. */
export interface RelinkResult {
  entity: LineageEntity;
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
  /** FREE disk space (MB) on the data drive, or null when undetectable. */
  diskFreeMb?: number | null;
}

/**
 * WU-models/device: a device-ranked model pick + the "X because RAM/VRAM Y"
 * reason (`models.runners` -> `whisper` / `llm`). Field names mirror the sidecar
 * `model_recommend.ModelReco`.
 */
export interface ModelReco {
  model: string;
  label: string;
  reason: string;
}

/** A runner's pull recommendation: a {@link ModelReco} + a copy-able pull hint. */
export interface RunnerModelReco extends ModelReco {
  pull: string;
}

/**
 * WU-models/device: per-runner (Ollama / LM Studio) detect + recommend + install
 * advice (`models.runners` -> `runners[]`). Mirrors `model_recommend.RunnerAdvice`.
 */
export interface RunnerAdvice {
  kind: string;
  label: string;
  present: boolean;
  baseUrl: string;
  installUrl: string;
  installHint: string;
  installedModels: string[];
  recommendedModel: RunnerModelReco;
}

/** The full `models.runners` payload: device whisper + LLM + per-runner advice. */
export interface LocalModelPlan {
  whisper: ModelReco;
  llm: ModelReco;
  runners: RunnerAdvice[];
}

/**
 * M1a (V1.1 Lane 2): one REDACTED key-pool row (`models.overview` -> `keyPool`).
 * `redactedKey` is the last-4 redaction only (never a full key); `status` starts
 * `"active"` (M4 flips it to `"cooldown"` on a 402/429). Mirrors the sidecar
 * `key_pool.KeyPoolEntry`.
 */
export interface KeyPoolEntry {
  /** Stable `"<providerId>#<index>"` slug. */
  id: string;
  providerId: string;
  /** REDACTED last-4 only (e.g. "…WXYZ") — never a full key over RPC. */
  redactedKey: string;
  /** Rate-limit unit ("req" / "token"). */
  unit: string;
  /** "active" | "cooldown" — M4 surfaces cooldown on a 402/429. */
  status: string;
}

/**
 * M1a (V1.1 Lane 2): the single routing policy (`models.overview` ->
 * `routingPolicy`; M3 owns the WRITE). `global` is the header toggle mode;
 * `overrides` maps a function name to a per-function mode. A corrupt/missing
 * policy is read FAIL-CLOSED to `{ global: 'local', overrides: {} }` (GATE-2,
 * zero egress). Mirrors the sidecar `routing_policy` shape.
 */
export type RoutingMode = 'local' | 'cloud' | 'auto';
export interface RoutingPolicy {
  global: RoutingMode;
  overrides: Record<string, RoutingMode>;
}

/**
 * M5 (V1.1 Lane 2): one CONCRETE resolved route from `models.resolveRoute`
 * (DESIGN §2.3 step 4). `mode` is the resolved mode; `requestedMode` is what the
 * user asked for (differs when a cloud/auto route degraded). `runner` is the
 * local-runner kind (xor `provider`, the cloud provider id). `degraded`+`notice`
 * carry the LOUD "fell back to local" signal when no cloud key was on disk.
 */
export interface ConcreteRoute {
  fn: string;
  mode: RoutingMode;
  requestedMode: RoutingMode;
  model: string;
  runner: string | null;
  provider: string | null;
  degraded: boolean;
  notice: string | null;
}

/**
 * M1a (V1.1 Lane 2): one detected local OpenAI-compatible server
 * (`models.overview` -> `runners[]`). Emitted verbatim by the sidecar
 * `local_detect.detect_local_servers` probe, so the field names are snake_case
 * (`base_url`) — this is the raw detection row, not a wire-adapted view.
 */
export interface PoolEntry {
  id: string;
  /** Server family: "ollama" | "lmstudio". */
  kind: string;
  base_url: string;
  /** The first model id the server reports serving. */
  model: string;
  capabilities: string[];
  /** Rate-limit unit (local servers are request-bounded -> "req"). */
  unit: string;
}

/**
 * M1b/M2 (V1.1 Lane 2): one deduped, metadata-enriched installed Ollama model +
 * its VRAM-fit verdict (`models.overview` -> `eligibility.models[]`). Mirrors the
 * sidecar `ollama_meta.ModelMeta`. `quantBits` is the resolved quant width
 * (4 = Q4, 16 = FP16…); `vramEstimateGb` is the field VRAM fit formula's resident
 * estimate (null when params/quant are unknown -> the model can't be asserted to
 * fit and is excluded). M2's reason strip names the real `quantBits` +
 * `vramEstimateGb` ("7B-Q4 ≈ 4.0 GB, fits your 8 GB GPU").
 */
export interface ModelMeta {
  model: string;
  digest: string;
  sizeBytes: number | null;
  /** Parameter count in BILLIONS (7.6 = 7.6B), or null when unparseable. */
  paramsB: number | null;
  /** Quant width in bits (4 = Q4, 8 = Q8, 16 = FP16…), or null when unknown. */
  quantBits: number | null;
  /** Resident VRAM estimate (GB) from params × quant + overhead + KV cache. */
  vramEstimateGb: number | null;
  capabilities: string[];
  aliases: string[];
  fits: boolean;
}

/**
 * M1b/M2 (V1.1 Lane 2): the metadata-driven LLM eligibility (`models.overview` ->
 * `eligibility`). Mirrors the sidecar `ollama_meta.Eligibility`. `source` is
 * `"metadata"` when ≥1 detected Ollama model is capability-eligible AND fits the
 * device; `"ladder"` otherwise (no runner / no metadata / nothing fits).
 * `fallback` is ALWAYS the device-fit static-ladder pick, so a usable pick exists
 * regardless of `source` (the reason strip uses it when no real metadata applies).
 */
export interface Eligibility {
  source: string;
  models: ModelMeta[];
  fallback: ModelReco;
}

/**
 * M1a (V1.1 Lane 2): the THIN `models.overview` compose — the whole "Models &
 * System" screen in ONE read (DESIGN §2.3 step 2). Stitches the cheap probes
 * (hardware + advisor tiers/preset + local runner detect + device-ranked plan)
 * with the redacted providers + per-key pool + fail-closed routing policy. The
 * sidecar makes ZERO provider/LLM calls and NEVER mutates settings.
 */
export interface ModelsOverview {
  hardware: HardwareInfo;
  tiers: TierStatus[];
  recommendedPreset: string;
  /** Detected local OpenAI-compatible servers (Ollama / LM Studio). */
  runners: PoolEntry[];
  localPlan: LocalModelPlan;
  /** REDACTED provider entries (last-4 keys only). */
  providers: ProviderEntry[];
  keyPool: KeyPoolEntry[];
  routingPolicy: RoutingPolicy;
  /** M2: metadata-driven LLM eligibility (real quant + VRAM est, or ladder). */
  eligibility: Eligibility;
}

/** One OpenRouter key-pool row's status: serving, or parked (NOT deleted). */
export type KeyPoolStatus = 'active' | 'cooldown';

/**
 * WU-models/device + M4: one OpenRouter key's COST + status row
 * (`providers.openrouterUsage`). `key` is the REDACTED last-4 only (no full key
 * crosses RPC). Money is USD. `status` is `active`/`cooldown` — a parked key is
 * NEVER deleted (cooldown-not-delete) and carries `cooldownReason` (402/429, or
 * the free-tier <10-credit cap). Mirrors the sidecar
 * `openrouter_usage.OpenRouterUsageRow`.
 */
export interface OpenRouterUsageRow {
  provider: string;
  key: string;
  costUsd: number | null;
  limitUsd: number | null;
  remainingUsd: number | null;
  isFreeTier: boolean;
  status: KeyPoolStatus;
  cooldownReason: string | null;
}

/** One selectable ASR engine row (`asr.engines`). */
export interface AsrEngine {
  id: string;
  label: string;
  installed: boolean;
}

// ---- First-run self-diagnostic (`system.selfTest`, WU-2) ------------------
//
// Field names are FROZEN, identical to the sidecar `_self_test_report_to_wire`
// payload (camelCase on the wire already). Each check validates one slice of a
// fresh install (data dir / device / reframe deps / ASR / ffmpeg); a `required`
// check whose `ok` is false blocks a working render, an informational one
// (`device`) is surfaced but does not flip the overall `ok`.

/** One self-diagnostic check row (`system.selfTest`, WU-2). */
export interface SelfTestCheck {
  /** Stable id the panel keys on: `data` | `device` | `cv2` | `asr` | `ffmpeg`. */
  id: string;
  label: string;
  ok: boolean;
  /** A failure of a required check blocks a working render (informational ones do not). */
  required: boolean;
  /** What was probed / what failed (human one-line). */
  detail: string;
  /** Actionable remedy, populated only when the check failed (empty on success). */
  fixHint: string;
}

/** The full first-run self-diagnostic report (`system.selfTest`, WU-2). */
export interface SelfTestReport {
  /** True iff every REQUIRED check passed (a broken install is loudly false). */
  ok: boolean;
  checks: SelfTestCheck[];
  /** Human problem lines (one per failing check, each with its fix hint). */
  problems: string[];
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
 * `providers.spend` payload (WU-spend-cap): the persisted monthly cumulative
 * spend ledger plus the configured caps, for the Monthly spend-cap control.
 * ALL money is integer CENTS (the UI converts to dollars). `month` is the
 * current UTC month key ("YYYY-MM"). With the default off/0 settings every cap
 * reads zero/false (a benign "no cap" view). Read-only: it never mutates state.
 */
export interface SpendInfo {
  /** The current UTC month the ledger is keyed by, e.g. "2026-06". */
  month: string;
  /** Cumulative cloud spend this month, in integer cents. */
  monthToDateCents: number;
  /** The non-blocking warning ceiling (cents); 0 = not set. */
  softLimitCents: number;
  /** The blocking ceiling (cents); 0 = not set. */
  hardLimitCents: number;
  /** Master switch: only when true does an over-hard-cap run get refused. */
  enforceHardLimit: boolean;
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
  | 'join'
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

// ---- Method-typed client handle (shared with ./client) -------------------

export interface JobHandle {
  jobId: string;
}
