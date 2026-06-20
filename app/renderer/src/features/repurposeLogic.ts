// repurposeLogic.ts — pure, framework-free logic for the Repurpose bundle (WU11).
//
// Keeps the testable decisions out of the React panels (mirrors
// `shortMakerLogic.ts`): per-source status tokens (text, never color-only,
// §7.1), the announce-granularity rule (announce on source-transition +
// terminal-state only, NOT on every percent tick, F-a11y-announce-granularity),
// the edit-time caption-style/aspect/duration constraints for ExportPresetsPanel
// (§7/§10.5), and the resume-surface predicate (which batches are incomplete,
// §7.2). All inputs are plain data so each branch is unit-testable to 100%.

import type {
  BatchItem,
  BatchItemStatus,
  BatchState,
  BatchStatus,
  BatchSummary,
  ExportPreset,
  ProgressEvent,
} from '../lib/rpc';

// ---- caption-style + reframe-engine constraints (§7 / §10.5) --------------
//
// The edit-time controls are CLOSED selects of valid ids only, so an invalid id
// is unselectable and the sidecar save-time validation is a defense-in-depth
// backstop. Single-sourced here so the conformance with the sidecar
// `caption_remotion.STYLES` set is one list to keep in sync.

/** The remotion caption styles (mirrors sidecar `caption_remotion.STYLES`). */
export const CAPTION_STYLE_OPTIONS: readonly string[] = [
  'bold',
  'karaoke',
  'clean',
  'bounce',
  'hormozi',
  'neon',
  'tiktok',
  'gradient',
  'impact',
  'mrbeast',
  'pop',
  'serif',
  'fire',
  'subtitle',
  // the two libass sentinels the sidecar guard also allows.
  'libass',
  'none',
] as const;

/** The reframe engine ids (mirrors sidecar `export_presets.REFRAME_ENGINES`). */
export const REFRAME_ENGINE_OPTIONS: readonly string[] = [
  'auto',
  'verthor',
  'claudeshorts',
] as const;

/** The hard duration window the pipeline enforces (§5.3): 20-60 s. */
export const MIN_WINDOW_SEC = 20;
export const MAX_WINDOW_SEC = 60;

/**
 * Clamp a duration into the hard [20, 60] window so the UI cannot author a
 * preset the pipeline would silently correct (the save-time clamp's UI mirror).
 */
export function clampWindowSec(sec: number): number {
  if (Number.isNaN(sec)) return MIN_WINDOW_SEC;
  if (sec < MIN_WINDOW_SEC) return MIN_WINDOW_SEC;
  if (sec > MAX_WINDOW_SEC) return MAX_WINDOW_SEC;
  return sec;
}

/** True when `id` is a selectable caption style (closed-set guard). */
export function isValidCaptionStyle(id: string): boolean {
  return CAPTION_STYLE_OPTIONS.includes(id);
}

// ---- per-source status tokens (text, not color-only, §7.1) ----------------

/** Human, SR-readable status token for one source row (never color alone). */
export function statusToken(status: BatchItemStatus): string {
  switch (status) {
    case 'done':
      return 'Done';
    case 'error':
      return 'Failed';
    case 'cancelled':
      return 'Cancelled';
    case 'skipped':
      return 'Skipped';
    case 'running':
      return 'Running';
    case 'queued':
    default:
      return 'Queued';
  }
}

/** The terminal item statuses (no further transitions). */
const TERMINAL: ReadonlySet<BatchItemStatus> = new Set(['done', 'error', 'cancelled', 'skipped']);

/** True when an item has reached a terminal state. */
export function isTerminalItem(status: BatchItemStatus): boolean {
  return TERMINAL.has(status);
}

// ---- announce-granularity rule (§7.1, F-a11y-announce-granularity) ---------
//
// Politeness levels: a terminal flip to `error` is assertive (a failed source
// must interrupt and not be missed); every other announcement is polite. Queued
// -> running transitions are NEVER announced (too noisy). The aggregate progress
// region re-announces ONLY when the `source k/N` token changes, not on every pct
// tick — so SR users hear "source 4 of 30 …", not 100 announcements per source.

/** A discrete announcement to push to a live region. */
export interface Announcement {
  text: string;
  assertive: boolean;
}

/**
 * Decide the per-source terminal announcement when an item flips state. Returns
 * `null` for non-terminal transitions (queued/running) so they are not spoken.
 */
export function terminalAnnouncement(
  title: string,
  item: Pick<BatchItem, 'status' | 'error' | 'skipReason'>,
): Announcement | null {
  switch (item.status) {
    case 'done':
      return { text: `${title} — done`, assertive: false };
    case 'error':
      return {
        text: `${title} — failed: ${item.error ?? 'unknown error'}`,
        assertive: true,
      };
    case 'cancelled':
      return { text: `${title} — cancelled`, assertive: false };
    case 'skipped':
      return {
        text: `${title} — skipped: ${item.skipReason ?? 'unknown reason'}`,
        assertive: false,
      };
    default:
      return null;
  }
}

/**
 * Extract the stable `source k/N` token from an aggregate progress message
 * (`"source k/N · <title> · step j/M · <label>"`, §7). The aggregate region
 * re-renders ONLY when this token changes, debouncing per-pct chatter. Returns
 * the empty string when the message has no `source k/N` prefix.
 */
export function sourceToken(message: string): string {
  const match = /source\s+\d+\/\d+/i.exec(message);
  return match ? match[0] : '';
}

/**
 * The polite aggregate text to show, debounced by `sourceToken`. Returns the new
 * message when its source token differs from `prev`, else `null` (no re-announce
 * — the prior text stays so the SR isn't spammed on pct-only updates).
 */
export function aggregateUpdate(prevMessage: string, event: ProgressEvent): string | null {
  if (sourceToken(event.message) === sourceToken(prevMessage)) return null;
  return event.message;
}

// ---- resume-surface predicate (§7.2) --------------------------------------

/** Aggregate statuses that mean a batch still has work left (resumable). */
const INCOMPLETE: ReadonlySet<BatchStatus> = new Set(['queued', 'running', 'partial']);

/** True when a batch is incomplete (drives the tab badge + launch toast, §7.2). */
export function isIncomplete(status: BatchStatus): boolean {
  return INCOMPLETE.has(status);
}

/** The incomplete batches of a `batch.list` result, sorted newest-first. */
export function incompleteBatches(batches: readonly BatchSummary[]): BatchSummary[] {
  return batches
    .filter((b) => isIncomplete(b.status))
    .slice()
    .sort((a, b) => b.createdAt - a.createdAt);
}

/** The remaining (not-yet-done) source count for a summary (toast copy). */
export function remainingCount(counts: BatchSummary['counts']): number {
  return counts.total - counts.done - counts.skipped;
}

// ---- merged item view for the queue (store + nothing else) -----------------

/** True when every item of a loaded `BatchState` is terminal (run is over). */
export function batchSettled(state: Pick<BatchState, 'items'>): boolean {
  return state.items.every((item) => isTerminalItem(item.status));
}

// ---- preset defaults (a new-preset row seed for ExportPresetsPanel) --------

/** A blank, valid-by-construction export preset for the "new preset" row. */
export function blankPreset(): Omit<ExportPreset, 'id'> {
  return {
    label: 'New preset',
    aspect: '9:16',
    minSec: MIN_WINDOW_SEC,
    maxSec: MAX_WINDOW_SEC,
    count: 5,
    captionStyle: CAPTION_STYLE_OPTIONS[0],
    reframeEngine: REFRAME_ENGINE_OPTIONS[0],
  };
}
