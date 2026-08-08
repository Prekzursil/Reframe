// speedPresets.ts — the pure model behind the Speed panel (slow motion / speed-up).
//
// The re-time ENGINE has existed for a while (`setpts` + a legal `atempo` chain,
// `retime` in the Director's WIRED_KINDS) but nothing in the renderer could reach
// it: no speed RPC, no speed control in any panel. The only path was an
// LLM-planned Director op, so a user had to phrase a prompt and hope the planner
// emitted one. This module is the pure half of the control that fixes that —
// kept render-free so every branch is exhaustively unit tested.
//
// SCOPE — the presets are deliberately all CONSTANT factors. A keyframed speed
// RAMP (piecewise `setpts` with segment-wise audio resampling) is a DIFFERENT
// engine that does not exist in this tree; `speedPresets.test.ts` asserts no
// preset advertises one, so the UI can never promise a capability the sidecar
// cannot deliver.
//
// AUTHORITY: `sidecar/media_studio/features/speed.py` is the validator of record
// (`resolve_factor` REJECTS out-of-window). This module MIRRORS its window so the
// UI can pre-empt a round trip with a friendly clamp. The renderer cannot read
// Python, so the two constants are stated twice on purpose and pinned by a test
// on each side — change one, change both.

/** Slowest playback factor the sidecar accepts (0.1x = ten times longer). */
export const SPEED_MIN = 0.1;
/** Fastest playback factor the sidecar accepts (10x = a tenth as long). */
export const SPEED_MAX = 10;

/** One offered speed. `factor` > 1 speeds up (shorter), < 1 slows down (longer). */
export interface SpeedPreset {
  /** Stable id (a radio value / test handle) — never shown to the user. */
  readonly id: string;
  /** The button copy. */
  readonly label: string;
  /** The playback factor sent as `speed.retime({factor})`. */
  readonly factor: number;
}

/**
 * The offered speeds, slowest first. Two slow-motion steps and three speed-ups,
 * spanning the range people actually reach for: 0.5x for a highlight beat, 1.5x
 * for a talking-head that drags, 2x/4x for screen-recording filler.
 */
export const SPEED_PRESETS: readonly SpeedPreset[] = [
  { id: 'slowmo-quarter', label: '0.25x slow motion', factor: 0.25 },
  { id: 'slowmo-half', label: '0.5x slow motion', factor: 0.5 },
  { id: 'faster-1p5', label: '1.5x faster', factor: 1.5 },
  { id: 'faster-2', label: '2x faster', factor: 2 },
  { id: 'faster-4', label: '4x faster', factor: 4 },
];

/**
 * Clamp a factor into [SPEED_MIN, SPEED_MAX] for the slider. A non-finite input
 * (a slider mid-drag can emit NaN) falls back to 1x — the neutral "no change"
 * position, never a silent extreme.
 *
 * Clamping here is a UI affordance only. The SIDECAR rejects rather than clamps,
 * deliberately: a user who asks for 100x and is quietly given 10x has been lied
 * to. The slider simply cannot express 100x in the first place.
 */
export function clampFactor(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(SPEED_MAX, Math.max(SPEED_MIN, value));
}

/**
 * True when `value` is a factor `speed.retime` will accept: a finite number,
 * inside the window, and not exactly 1 (which the sidecar refuses as a no-op).
 * The Apply control is gated on this, so a rejected request never leaves the UI.
 */
export function isRetimeFactor(value: unknown): value is number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return false;
  if (value === 1) return false;
  return value >= SPEED_MIN && value <= SPEED_MAX;
}

/**
 * The output duration a re-time produces (`source / factor`). Returns 0 for an
 * unknown source duration or a non-positive factor — "unknown" is not a number
 * to do arithmetic on, and the panel renders it as a dash rather than "0:00".
 */
export function retimedDuration(sourceSec: number, factor: number): number {
  if (!Number.isFinite(sourceSec) || sourceSec <= 0) return 0;
  if (!Number.isFinite(factor) || factor <= 0) return 0;
  return sourceSec / factor;
}

/**
 * A factor as human copy — `2x (faster)` / `0.5x (slower)`. The DIRECTION is
 * spelled out because a bare "0.5x" reads as "half the time" to as many people
 * as read it "half the speed", and those are opposite edits.
 */
export function speedLabel(factor: number): string {
  // `parseFloat(toFixed(2))` drops trailing zeros: 2.00 -> 2, 1.50 -> 1.5.
  const n = parseFloat(factor.toFixed(2));
  if (n === 1) return '1x (no change)';
  return `${n}x (${n > 1 ? 'faster' : 'slower'})`;
}
