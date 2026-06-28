// hookCardPreset.ts — renderer mirror of the OpusClip-style HOOK-CARD overlay +
// virality-rank gating (V1.1 WU SP2). The export/burn authority is the sidecar
// `hook_card.py` (the libass Style line + the top-N gate + the rank-ordered
// filename prefix); this module is the renderer-side MIRROR of the shared
// constants + pure helpers so the LIVE PREVIEW and the controls can never
// silently drift from the burn.
//
// WHAT THE PREVIEW SHOWS (`hookCardOverlayStyle`): the white card box, the bold
// BLACK text, and the upper-third anchor — the OpusClip hook card (the inverse of
// the white-on-black caption box). The card is applied to the TOP-N clips by
// virality rank only and shown for the first ~5 s of each.
//
// The mirror is drift-guarded by `hookCardPreset.test.ts`, which reads the real
// sidecar source and asserts the shared constants match (the same defence the
// karaoke preset + the three-way template conformance test use).
//
// Everything here is PURE (no React, no DOM).

import type { Candidate } from '../features/shortMakerLogic';

/** White card box (#RRGGBB) — matches sidecar `HOOK_CARD_FILL_HEX`. */
export const HOOK_CARD_FILL_HEX = '#FFFFFF';
/** Bold black headline text (#RRGGBB) — matches sidecar `HOOK_CARD_TEXT_HEX`. */
export const HOOK_CARD_TEXT_HEX = '#000000';

/** OpusClip cards the top-10 ranked clips only — matches sidecar default. */
export const HOOK_CARD_DEFAULT_TOP_N = 10;
/** Cards show for the first ~5 s only — matches sidecar `HOOK_CARD_DEFAULT_SEC`. */
export const HOOK_CARD_DEFAULT_SEC = 5.0;
/** Lower clamp on the time-box window — matches sidecar `HOOK_CARD_MIN_SEC`. */
export const HOOK_CARD_MIN_SEC = 0.5;
/** Upper clamp on the time-box window — matches sidecar `HOOK_CARD_MAX_SEC`. */
export const HOOK_CARD_MAX_SEC = 30.0;
/** Upper-third vertical anchor (fraction of height) — matches sidecar. */
export const HOOK_CARD_TOP_FRACTION = 0.12;
/** Min zero-pad width for the rank-ordered prefix — matches sidecar. */
export const HOOK_CARD_MIN_ORDER_WIDTH = 2;

/** Resolved hook-card config (already clamped). */
export interface HookCardConfig {
  enabled: boolean;
  topN: number;
  durationSec: number;
}

/** Clamp a raw top-N into a positive integer count (default 10 for bad input). */
export function clampHookCardTopN(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return HOOK_CARD_DEFAULT_TOP_N;
  return Math.max(1, Math.round(value));
}

/** Clamp a raw seconds value into [MIN, MAX] (default 5 for non-positive/bad). */
export function clampHookCardSec(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return HOOK_CARD_DEFAULT_SEC;
  }
  return Math.min(Math.max(value, HOOK_CARD_MIN_SEC), HOOK_CARD_MAX_SEC);
}

/**
 * The set of `rank`s that get a hook card — the TOP-N by virality (rank 1 is the
 * best clip, so the N smallest ranks qualify). Disabled config or an empty batch
 * yields an empty set; a candidate missing a rank uses its 1-based position.
 */
export function selectHookCardRanks(
  candidates: readonly Candidate[],
  config: HookCardConfig,
): Set<number> {
  if (!config.enabled) return new Set();
  const ranks = candidates
    .map((c, i) => (Number.isFinite(c.rank) ? c.rank : i + 1))
    .sort((a, b) => a - b);
  return new Set(ranks.slice(0, config.topN));
}

/** Zero-padded rank-ordered filename prefix (`01`, `02` … `NN`), min width 2. */
export function orderPrefix(rank: number, maxRank: number): string {
  const width = Math.max(HOOK_CARD_MIN_ORDER_WIDTH, String(Math.max(1, Math.trunc(maxRank))).length);
  return String(Math.trunc(rank)).padStart(width, '0');
}

/** The rank-ordered output stem `<NN>-<base>` (sorts by virality rank). */
export function rankOrderedStem(base: string, rank: number, maxRank: number): string {
  return `${orderPrefix(rank, maxRank)}-${base}`;
}

/**
 * The card's end time: the first `durationSec` seconds, capped to the clip length
 * (`totalSec`) when known (> 0). A non-positive `durationSec` falls back to the
 * default window. Mirrors sidecar `hook_card_end_sec`.
 */
export function hookCardEndSec(durationSec: number, totalSec: number): number {
  const sec = durationSec > 0 ? durationSec : HOOK_CARD_DEFAULT_SEC;
  if (totalSec > 0) return Math.min(sec, totalSec);
  return sec;
}

/** The live-preview overlay style: white box, bold black text, upper-third. */
export interface HookCardOverlayStyle {
  background: string;
  color: string;
  fontWeight: number;
  topFraction: number;
}

export function hookCardOverlayStyle(): HookCardOverlayStyle {
  return {
    background: HOOK_CARD_FILL_HEX,
    color: HOOK_CARD_TEXT_HEX,
    fontWeight: 700,
    topFraction: HOOK_CARD_TOP_FRACTION,
  };
}
