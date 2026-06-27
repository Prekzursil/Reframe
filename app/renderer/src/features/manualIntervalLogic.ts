// manualInterval.ts — pure logic for MANUAL interval shorts (V1 IA §h).
//
// The Make Shorts section offers two modes: AI moment-pick (shortmaker.select)
// and MANUAL intervals — the user gives explicit ranges (e.g. 1:23 -> 4:10) and
// each becomes an inline export candidate fed straight to shortmaker.export
// (the same inline-candidates path the AI flow uses). This module owns the
// timecode parsing + range -> Candidate conversion so the component stays thin
// and the hard logic is unit-tested to 100%.
import type { Candidate } from '../lib/rpc';

/** A validated manual time range, in SOURCE-absolute seconds. */
export interface ManualRange {
  start: number;
  end: number;
}

/**
 * Parse a timecode string into SOURCE-absolute seconds, or `null` if invalid.
 * Accepts plain seconds ("90"), "mm:ss" ("1:23"), or "h:mm:ss" ("1:02:03").
 * The lower fields (minutes, seconds) must be in [0, 60); all parts must be
 * non-negative finite numbers. Anything else returns `null` (no silent guess).
 */
export function parseTimecode(input: string): number | null {
  const text = input.trim();
  if (!text) return null;
  const parts = text.split(':');
  if (parts.length > 3) return null;
  const nums = parts.map((p) => Number(p));
  if (nums.some((n) => !Number.isFinite(n) || n < 0)) return null;
  if (parts.length === 1) return nums[0];
  // The trailing field(s) below the largest unit must be < 60.
  const lower = nums.slice(1);
  if (lower.some((n) => n >= 60)) return null;
  return nums.reduce((acc, n) => acc * 60 + n, 0);
}

/** Format SOURCE-absolute seconds as "m:ss" (or "h:mm:ss" past an hour). */
export function formatTimecode(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) return '0:00';
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, '0');
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${ss}`;
  return `${m}:${ss}`;
}

/** Build one export Candidate for a manual range (source-anchored, given rank). */
export function intervalToCandidate(start: number, end: number, rank: number): Candidate {
  return {
    rank,
    start,
    end,
    durationSec: end - start,
    sourceStart: start,
    hook: `Manual clip ${rank}`,
    why: 'Manual interval',
    score: 0,
  };
}

/** Convert validated ranges into ranked inline export candidates (rank 1..n). */
export function buildManualCandidates(ranges: readonly ManualRange[]): Candidate[] {
  return ranges.map((r, i) => intervalToCandidate(r.start, r.end, i + 1));
}
