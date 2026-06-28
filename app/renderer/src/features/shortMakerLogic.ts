// shortMakerLogic.ts — the pure, render-free logic for the Short-maker (§2/§3
// contract types, control sanitation, the review reducer, the §7/§8 helpers, and
// the deferred-job RPC plumbing).
//
// Extracted from ShortMaker.tsx to keep that file under the 800-line budget and
// to isolate the pure logic the unit tests exercise directly. None of these
// functions touch React render output; the component (ShortMaker.tsx) wires them
// to state + window.api, and re-exports every symbol so existing importers
// (tests, shortMakerPresets.ts) keep ONE entry point.
//
// CONTRACT-NOTE: the wire field names here are FROZEN — identical to the
// Python/sidecar side (§3 Candidate / §2 controls). Do not rename.
import type { PlayerWindow } from '../components/Player';
import { logWarn } from '../lib/logger';
// F1+F2: the deferred-job wait is the SINGLE shared helper in ./_api (timeout +
// {error} reject + AbortSignal + leak-free cleanup). This module drops its old
// private copy and re-exports the shared one so existing importers/tests (which
// pull `waitForJobDone` through ShortMaker) keep ONE entry point.
import { DEFAULT_JOB_TIMEOUT_MS, waitForJobDone } from './_api';

export { waitForJobDone };

// ---------------------------------------------------------------------------
// Contract types (§3) — field names identical to the Python/wire side.
// ---------------------------------------------------------------------------

/** P3-C virality factor scores (each 0-100) — wire field names FROZEN. */
export interface CandidateFactors {
  hookStrength: number;
  emotionalFlow: number;
  perceivedValue: number;
  shareability: number;
}

/** §3 Candidate — keep field names identical both sides (+ P3-C additions). */
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

/** §2 shortmaker.select controls (+ T4b's reframe engine override).
 *
 * CONTRACT-NOTE (T4b): base §2 freezes {count,minSec,maxSec,aspect,language,
 * captionStyle}; the P2 T4b lane adds `reframeEngine` (auto|verthor|
 * claudeshorts) flowing through the same controls object into
 * `shortmaker.select`, and both `captionStyle` + `reframeEngine` are ALSO sent
 * as optional top-level `shortmaker.export` params (see WIRING-T4B.md for the
 * sidecar consumption patch).
 */
export interface ShortMakerControls {
  count: number;
  minSec: number;
  maxSec: number;
  aspect: string;
  language: string;
  captionStyle: string;
  reframeEngine: string;
  /** P3-A: render the candidate's hook as the headline overlay (default ON). */
  hookTitle: boolean;
  /** P3-B: filler-word removal cut pass (default OFF — experimental). */
  removeFillers: boolean;
  /**
   * P4 §8a: keyword/emoji emphasis. Tri-state so the sidecar's per-style default
   * (ON for OpusClip-style templates, OFF for clean/minimal) is preserved unless
   * the user overrides it:
   *   'default' -> omit from export; sidecar resolve_emphasis picks per-style;
   *   'on'/'off' -> explicit override sent as a bool.
   */
  emphasis: EmphasisChoice;
  /** P4 §8b: auto punch-in zoom on emphasis beats (default OFF). */
  autoZoom: boolean;
  /**
   * audio-stabilize group: dead-air removal pre-step (ffmpeg silencedetect ->
   * keep-span re-cut), default OFF. Mutually exclusive with removeFillers on the
   * sidecar (silence-trim wins — both edit the clip timeline).
   */
  silenceTrim: boolean;
  /**
   * audio-stabilize group: camera-shake stabilization pre-step (ffmpeg vidstab
   * 2-pass), default OFF. Warp-only, so it composes with every other stage; a
   * bundled ffmpeg without libvidstab reports the skip (never silent).
   */
  stabilize: boolean;
}

/** A3 AudioTrack (the subset the export picker needs — wire field names). */
export interface AudioTrackOption {
  id: string;
  lang: string;
  name: string;
  kind: 'original' | 'dub';
}

/** §2 progress notification params: {jobId, pct, message}. */
export interface JobProgress {
  jobId: string;
  pct: number;
  message: string;
}

/** §2 job.done notification params: {jobId, result}. */
export interface JobDone {
  jobId: string;
  result?: unknown;
}

/** Minimal window.api surface (real type owned by preload/lib units). */
export interface Api {
  rpc<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
  /** Subscribe to progress notifications; returns an unsubscribe fn. */
  onProgress(cb: (p: JobProgress) => void): () => void;
  /** Optional: subscribe to job.done; returns an unsubscribe fn. */
  onJobDone?(cb: (d: JobDone) => void): () => void;
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

// CONTRACT-NOTE: sibling units (components/api.ts, features/_api.ts) already
// add `declare global { interface Window { api } }`. Augmenting it again here
// with a different type would collide at typecheck (interface merging requires
// identical types). So this module does NOT augment Window; the component reads
// the bridge via a local structural cast instead. The frozen §1 surface
// (`rpc(method,params)` + `onProgress(cb)`) makes `Api` structurally
// compatible with whatever concrete `window.api` type the program resolves.
export function resolveWindowApi(): Api | undefined {
  const w = (globalThis as { window?: { api?: unknown } }).window;
  return (w?.api as Api | undefined) ?? undefined;
}

// ---------------------------------------------------------------------------
// Pure logic (exported so tests run with NO React render / NO heavy imports).
// ---------------------------------------------------------------------------

/** Hard duration window for clips/nudges (§5 "each 20-60s (hard)"). */
export const MIN_CLIP_SEC = 20;
export const MAX_CLIP_SEC = 60;

// ---------------------------------------------------------------------------
// Caption styles (T4b picker) + reframe engine override (A4 engines).
// ---------------------------------------------------------------------------

/** Which CaptionEngine (A4) renders a given style. */
export type CaptionEngineKind = 'libass' | 'remotion';

export interface CaptionStyleOption {
  id: string;
  engine: CaptionEngineKind;
  label: string;
}

/**
 * The caption style catalog: the **libass default** (A4: "libass (default,
 * fast styles)") + the ≥12 OpusClip-style premium templates (P4 §4) + "none".
 *
 * KEEP IN SYNC (P4 §4 three-way mirror — `vendor/remotion-captions/src/
 * templates.ts` `TEMPLATES`, `sidecar/.../caption_remotion.py` STYLES, and the
 * renderer mirror `lib/captionTemplates.ts`). The renderer cannot import the
 * vendor file directly (separate package; zod dep not in app/), so the ids are
 * mirrored here and conformance is enforced by
 * `lib/captionTemplates.conformance.test.ts` (C3 superset relation: the
 * remotion subset equals TEMPLATES; the full list = TEMPLATES ∪ {libass,none}).
 */
export const CAPTION_STYLES: CaptionStyleOption[] = [
  { id: 'libass', engine: 'libass', label: 'Classic (libass, fast)' },
  { id: 'bold', engine: 'remotion', label: 'Bold (animated)' },
  { id: 'karaoke', engine: 'remotion', label: 'Karaoke (animated)' },
  { id: 'clean', engine: 'remotion', label: 'Clean (animated)' },
  { id: 'bounce', engine: 'remotion', label: 'Bounce (animated)' },
  { id: 'hormozi', engine: 'remotion', label: 'Hormozi (green pop)' },
  { id: 'neon', engine: 'remotion', label: 'Neon (glow)' },
  { id: 'tiktok', engine: 'remotion', label: 'TikTok (card)' },
  { id: 'gradient', engine: 'remotion', label: 'Gradient (sunset)' },
  { id: 'impact', engine: 'remotion', label: 'Impact (outline)' },
  { id: 'mrbeast', engine: 'remotion', label: 'MrBeast (yellow pop)' },
  { id: 'pop', engine: 'remotion', label: 'Pop (playful)' },
  { id: 'serif', engine: 'remotion', label: 'Serif (editorial)' },
  { id: 'subtitle', engine: 'remotion', label: 'Subtitle (broadcast)' },
  { id: 'fire', engine: 'remotion', label: 'Fire (hot sweep)' },
  { id: 'none', engine: 'libass', label: 'No captions' },
];

/** A4: libass is the default caption engine/style. */
export const DEFAULT_CAPTION_STYLE = 'libass';

export const CAPTION_STYLE_OPTIONS: readonly string[] = CAPTION_STYLES.map((s) => s.id);

/** A4 reframe engines + the "auto" selector (verthor with claudeshorts fallback). */
export const REFRAME_ENGINE_OPTIONS = ['auto', 'verthor', 'claudeshorts'] as const;
export type ReframeEngineChoice = (typeof REFRAME_ENGINE_OPTIONS)[number];
export const DEFAULT_REFRAME_ENGINE: ReframeEngineChoice = 'auto';

export const REFRAME_ENGINE_LABELS: Record<ReframeEngineChoice, string> = {
  auto: 'Auto (verthor, falls back)',
  verthor: 'verthor (WSL)',
  claudeshorts: 'claude-shorts (in-app)',
};

/**
 * P4 §8a emphasis tri-state: 'default' defers to the sidecar's per-style default
 * (ON for OpusClip-style templates, OFF for clean/minimal); 'on'/'off' override.
 */
export const EMPHASIS_OPTIONS = ['default', 'on', 'off'] as const;
export type EmphasisChoice = (typeof EMPHASIS_OPTIONS)[number];
export const DEFAULT_EMPHASIS: EmphasisChoice = 'default';

export const EMPHASIS_LABELS: Record<EmphasisChoice, string> = {
  default: 'Auto (per template)',
  on: 'On (highlight + emoji)',
  off: 'Off (plain)',
};

export const DEFAULT_CONTROLS: ShortMakerControls = {
  count: 5,
  minSec: 20,
  maxSec: 60,
  aspect: '9:16',
  language: 'en',
  captionStyle: DEFAULT_CAPTION_STYLE,
  reframeEngine: DEFAULT_REFRAME_ENGINE,
  hookTitle: true,
  // V1 IA (GRILL G-4): quality features DEFAULT-ON to match the "all quality ON"
  // promise — removeFillers / autoZoom / silenceTrim / stabilize all start ON
  // (the novice front door ships its best output without touching Advanced).
  removeFillers: true,
  emphasis: DEFAULT_EMPHASIS,
  autoZoom: true,
  silenceTrim: true,
  stabilize: true,
};

export const ASPECT_OPTIONS = ['9:16', '1:1', '4:5', '16:9'] as const;

/** Clamp a number into [lo, hi]; returns lo if the range is inverted. */
export function clamp(n: number, lo: number, hi: number): number {
  if (hi < lo) return lo;
  if (n < lo) return lo;
  if (n > hi) return hi;
  return n;
}

/**
 * Sanitize raw controls into a valid set:
 * - count >= 1 (integer)
 * - 20 <= minSec <= maxSec <= 60 (hard window)
 * - non-empty aspect / language (fall back to defaults)
 * - captionStyle must be a known style id (else the libass default)
 * - reframeEngine must be auto|verthor|claudeshorts (else auto)
 * - hookTitle/removeFillers must be real booleans (else their defaults ON — G-4)
 * - emphasis must be 'default'|'on'|'off' (else the 'default' per-style mode)
 * - autoZoom must be a real boolean (else its default ON — G-4)
 * - silenceTrim/stabilize must be real booleans (else their defaults ON — G-4)
 */
export function sanitizeControls(raw: Partial<ShortMakerControls>): ShortMakerControls {
  const count = Math.max(1, Math.round(raw.count ?? DEFAULT_CONTROLS.count));
  let minSec = clamp(Math.round(raw.minSec ?? DEFAULT_CONTROLS.minSec), MIN_CLIP_SEC, MAX_CLIP_SEC);
  const maxSec0 = clamp(
    Math.round(raw.maxSec ?? DEFAULT_CONTROLS.maxSec),
    MIN_CLIP_SEC,
    MAX_CLIP_SEC,
  );
  let maxSec = maxSec0;
  if (minSec > maxSec) {
    // Keep the user's min, push max up to it (both already inside the window).
    maxSec = minSec;
  }
  const aspect = (raw.aspect ?? '').trim() || DEFAULT_CONTROLS.aspect;
  const language = (raw.language ?? '').trim() || DEFAULT_CONTROLS.language;
  const rawStyle = (raw.captionStyle ?? '').trim();
  const captionStyle = CAPTION_STYLE_OPTIONS.includes(rawStyle)
    ? rawStyle
    : DEFAULT_CONTROLS.captionStyle;
  const rawEngine = (raw.reframeEngine ?? '').trim().toLowerCase();
  const reframeEngine = (REFRAME_ENGINE_OPTIONS as readonly string[]).includes(rawEngine)
    ? rawEngine
    : DEFAULT_CONTROLS.reframeEngine;
  const hookTitle = typeof raw.hookTitle === 'boolean' ? raw.hookTitle : DEFAULT_CONTROLS.hookTitle;
  const removeFillers =
    typeof raw.removeFillers === 'boolean' ? raw.removeFillers : DEFAULT_CONTROLS.removeFillers;
  const rawEmphasis = (raw.emphasis ?? '').trim().toLowerCase();
  const emphasis = (EMPHASIS_OPTIONS as readonly string[]).includes(rawEmphasis)
    ? (rawEmphasis as EmphasisChoice)
    : DEFAULT_CONTROLS.emphasis;
  const autoZoom = typeof raw.autoZoom === 'boolean' ? raw.autoZoom : DEFAULT_CONTROLS.autoZoom;
  const silenceTrim =
    typeof raw.silenceTrim === 'boolean' ? raw.silenceTrim : DEFAULT_CONTROLS.silenceTrim;
  const stabilize = typeof raw.stabilize === 'boolean' ? raw.stabilize : DEFAULT_CONTROLS.stabilize;
  return {
    count,
    minSec,
    maxSec,
    aspect,
    language,
    captionStyle,
    reframeEngine,
    hookTitle,
    removeFillers,
    emphasis,
    autoZoom,
    silenceTrim,
    stabilize,
  };
}

/** Stable id for a candidate (rank + sourceStart) — used for selection/export. */
export function candidateId(c: Candidate): string {
  return `${c.rank}@${c.sourceStart}`;
}

/** Per-candidate review status in the loop. */
export type ReviewStatus = 'pending' | 'approved' | 'discarded';

/** A candidate plus its live (possibly nudged) review state. */
export interface ReviewItem {
  id: string;
  /** The original, untouched candidate (for non-destructive "reset"). */
  original: Candidate;
  /** The current (possibly nudged) candidate shown/exported. */
  current: Candidate;
  status: ReviewStatus;
}

/** Build review items from a fresh select result (all pending, sorted by rank). */
export function toReviewItems(candidates: Candidate[]): ReviewItem[] {
  return [...candidates]
    .sort((a, b) => a.rank - b.rank)
    .map((c) => ({
      id: candidateId(c),
      original: c,
      current: c,
      status: 'pending' as ReviewStatus,
    }));
}

/**
 * Nudge a candidate's boundaries by deltas (seconds) on start/end, NON-DESTRUCTIVELY:
 * - never goes before sourceStart-relative t=0 of the original video (start >= 0)
 * - stays within the 20-60s hard window (re-snap, not re-select)
 * - recomputes durationSec to match
 * The original is preserved by the caller (ReviewItem.original).
 */
export function nudgeCandidate(c: Candidate, deltaStart: number, deltaEnd: number): Candidate {
  const start = Math.max(0, c.start + deltaStart);
  let end = c.end + deltaEnd;
  // Enforce a positive duration first.
  if (end <= start) end = start + MIN_CLIP_SEC;
  let duration = end - start;
  // Clamp duration into the hard window by moving the END (keep the hook at start).
  if (duration < MIN_CLIP_SEC) {
    end = start + MIN_CLIP_SEC;
  } else if (duration > MAX_CLIP_SEC) {
    end = start + MAX_CLIP_SEC;
  }
  duration = end - start;
  return { ...c, start, end, durationSec: duration };
}

/** Reset a review item's boundaries back to the original candidate. */
export function resetItem(item: ReviewItem): ReviewItem {
  return { ...item, current: item.original };
}

/** Ids of the approved items (the only ones that ever export). */
export function approvedIds(items: ReviewItem[]): string[] {
  return items.filter((i) => i.status === 'approved').map((i) => i.id);
}

/** Map review-item ids back to the candidates the sidecar selected. */
export function approvedCandidates(items: ReviewItem[]): Candidate[] {
  return items.filter((i) => i.status === 'approved').map((i) => i.current);
}

/**
 * The preview window for a candidate: its `sourceStart`→`end` span in
 * SOURCE-absolute seconds — exactly what the export pipeline cuts (U1).
 */
export function previewWindow(c: Candidate): PlayerWindow {
  const start = c.sourceStart ?? c.start;
  return { start, end: Math.max(c.end, start) };
}

/** Shape of `media.playable` (mirrors lib/rpc MediaPlayableResult). */
export interface PlayableResult {
  playable: boolean;
  reason?: string;
  proxyPath?: string;
}

/**
 * Move the review selection by `delta` rows (J/K), clamped to the list.
 * An unknown/absent current id selects the first row; empty list -> null.
 */
export function moveSelection(
  items: ReviewItem[],
  currentId: string | null,
  delta: number,
): string | null {
  if (items.length === 0) return null;
  const idx = items.findIndex((i) => i.id === currentId);
  if (idx === -1) return items[0].id;
  return items[clamp(idx + delta, 0, items.length - 1)].id;
}

/** T6 keyboard nudge steps (seconds): plain arrows vs shift+arrows. */
export const NUDGE_COARSE_SEC = 1;
export const NUDGE_FINE_SEC = 0.2;

/** Clamp a progress pct into 0..100 for display. */
export function displayPct(pct: number | undefined): number {
  if (typeof pct !== 'number' || Number.isNaN(pct)) return 0;
  return clamp(Math.round(pct), 0, 100);
}

/** Format seconds as M:SS (UI only). */
export function fmtTime(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// P3-C virality factors (display helpers — pure, exported for tests).
// ---------------------------------------------------------------------------

/** Display order of the four FROZEN factor keys. */
export const FACTOR_KEYS = [
  'hookStrength',
  'emotionalFlow',
  'perceivedValue',
  'shareability',
] as const;
export type FactorKey = (typeof FACTOR_KEYS)[number];

export const FACTOR_LABELS: Record<FactorKey, string> = {
  hookStrength: 'Hook strength',
  emotionalFlow: 'Emotional flow',
  perceivedValue: 'Perceived value',
  shareability: 'Shareability',
};

export interface FactorEntry {
  key: FactorKey;
  label: string;
  /** Clamped to 0-100 for the bar width / numeral. */
  value: number;
  /** One-line rationale ('' when the payload has none). */
  note: string;
}

/** The four factor bars for a candidate ([] when factors are absent). */
export function factorEntries(c: Candidate): FactorEntry[] {
  const f = c.factors;
  if (!f) return [];
  return FACTOR_KEYS.map((key) => {
    const raw = Number(f[key]);
    return {
      key,
      label: FACTOR_LABELS[key],
      value: clamp(Math.round(Number.isFinite(raw) ? raw : 0), 0, 100),
      note: (c.factorNotes?.[key] ?? '').trim(),
    };
  });
}

/** viralityPct for display: clamped int 0-100, or null when absent/invalid. */
export function displayVirality(pct: unknown): number | null {
  if (typeof pct !== 'number' || Number.isNaN(pct)) return null;
  return clamp(Math.round(pct), 0, 100);
}

// ---------------------------------------------------------------------------
// P3-D feedback flywheel (fire-and-forget capture — never blocks the UI).
// ---------------------------------------------------------------------------

/** Implicit-label actions (wire values FROZEN — feedback.record). */
export type FeedbackAction = 'approved' | 'discarded' | 'nudged' | 'exported';

/** feedback.stats() result shape. */
export interface FeedbackStats {
  labels: number;
  calibrated: boolean;
}

/** Calibration kicks in at this many labels (P3-D; footer copy). */
export const CALIBRATION_LABELS = 50;

/**
 * Fire-and-forget `feedback.record` — review actions are implicit taste
 * labels. Errors are silent-logged; the review loop must NEVER block or
 * surface an error because feedback capture failed.
 */
export function recordFeedback(
  api: Api | undefined,
  videoId: string,
  candidate: Candidate,
  action: FeedbackAction,
): void {
  if (!api || typeof api.rpc !== 'function') return;
  try {
    Promise.resolve(api.rpc('feedback.record', { videoId, candidate, action })).catch((e) => {
      logWarn('feedback.record failed (ignored)', e);
    });
  } catch (e) {
    logWarn('feedback.record failed (ignored)', e);
  }
}

/** Footer line for feedback.stats (e.g. "Taste profile: 37 labels · calibration at 50"). */
export function tasteProfileLine(stats: FeedbackStats): string {
  const cal = stats.calibrated ? 'calibrated' : `calibration at ${CALIBRATION_LABELS}`;
  return `Taste profile: ${stats.labels} labels · ${cal}`;
}

// ---------------------------------------------------------------------------
// Review reducer (pure) — drives the non-destructive review list.
// ---------------------------------------------------------------------------

export type ReviewAction =
  | { type: 'load'; candidates: Candidate[] }
  | { type: 'approve'; id: string }
  | { type: 'discard'; id: string }
  | { type: 'pending'; id: string }
  | { type: 'nudge'; id: string; deltaStart: number; deltaEnd: number }
  | { type: 'reset'; id: string }
  | { type: 'clear' };

export function reviewReducer(state: ReviewItem[], action: ReviewAction): ReviewItem[] {
  switch (action.type) {
    case 'load':
      return toReviewItems(action.candidates);
    case 'clear':
      return [];
    case 'approve':
      return state.map((i) => (i.id === action.id ? { ...i, status: 'approved' } : i));
    case 'discard':
      return state.map((i) => (i.id === action.id ? { ...i, status: 'discarded' } : i));
    case 'pending':
      return state.map((i) => (i.id === action.id ? { ...i, status: 'pending' } : i));
    case 'nudge':
      return state.map((i) =>
        i.id === action.id
          ? { ...i, current: nudgeCandidate(i.current, action.deltaStart, action.deltaEnd) }
          : i,
      );
    case 'reset':
      return state.map((i) => (i.id === action.id ? resetItem(i) : i));
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// RPC helpers — long jobs return {jobId} immediately, progress streams, then
// either job.done(result) OR the promise resolves with the result (§2).
// ---------------------------------------------------------------------------

export interface SelectResult {
  candidates: Candidate[];
}

/** P3-B: one exported clip; filler-removal stats present when the pass ran. */
export interface ExportedClipInfo {
  path: string;
  fillersRemoved?: number;
  fillerSeconds?: number;
}

export interface ExportResult {
  clips: ExportedClipInfo[];
}
export interface JobHandle {
  jobId: string;
}

/** Extract candidates from either an immediate result or a job.done payload. */
export function extractCandidates(payload: unknown): Candidate[] | null {
  if (payload && typeof payload === 'object' && 'candidates' in payload) {
    const c = (payload as { candidates?: unknown }).candidates;
    if (Array.isArray(c)) return c as Candidate[];
  }
  return null;
}

/** Extract export clips from either an immediate result or a job.done payload. */
export function extractClips(payload: unknown): ExportedClipInfo[] | null {
  if (payload && typeof payload === 'object' && 'clips' in payload) {
    const c = (payload as { clips?: unknown }).clips;
    if (Array.isArray(c)) return c as ExportedClipInfo[];
  }
  return null;
}

/** True when an rpc resolution looks like a deferred job handle ({jobId} only). */
export function isJobHandle(payload: unknown): payload is JobHandle {
  return (
    !!payload &&
    typeof payload === 'object' &&
    'jobId' in payload &&
    extractCandidates(payload) === null &&
    extractClips(payload) === null
  );
}

// ---------------------------------------------------------------------------
// internals
// ---------------------------------------------------------------------------

export function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object' && 'message' in e) {
    return String((e as { message: unknown }).message);
  }
  return 'Unknown error';
}

/**
 * Default job.done wait timeout (F2): a dead/wedged sidecar must not hang the UI
 * forever. Exports take the longest of the short-maker jobs; the shared
 * {@link DEFAULT_JOB_TIMEOUT_MS} (15 min) is a generous ceiling — long enough
 * for a real batch export, short enough that a silent sidecar death surfaces a
 * user-facing error instead of a frozen UI. Aliased to the shared default so
 * there is ONE source of truth for the ceiling.
 */
export const EXPORT_JOB_TIMEOUT_MS = DEFAULT_JOB_TIMEOUT_MS;

/**
 * Resolve an rpc result into its terminal payload (P4 §8c batch reuse): try the
 * immediate `extract`; if it's only a deferred {jobId} handle, record it on
 * `jobRef` (for progress/cancel) and wait for `job.done`. Mirrors the inline
 * extract-or-wait pattern in runSelect/runExport so the batch flow stays small.
 *
 * `timeoutMs`/`signal` flow straight through to the shared {@link waitForJobDone}
 * (F2): omitting `timeoutMs` applies the shared default ceiling, and `signal`
 * lets a cancel/unmount tear the wait down.
 */
export async function resolveJobResult<T>(
  api: Api,
  res: unknown,
  extract: (payload: unknown) => T[] | null,
  jobRef: { current: string | null },
  timeoutMs?: number,
  signal?: AbortSignal,
): Promise<T[] | null> {
  const direct = extract(res);
  if (direct !== null) return direct;
  if (isJobHandle(res)) {
    jobRef.current = res.jobId;
    return waitForJobDone(api, res.jobId, extract, timeoutMs, signal);
  }
  return null;
}
