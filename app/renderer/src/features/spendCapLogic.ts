// spendCapLogic.ts — pure helpers for the Monthly spend-cap control (WU-spend-cap).
//
// The sidecar `providers.spend` RPC + the `monthly*Cents` settings keys speak
// integer CENTS; the UI speaks DOLLARS. All cents<->dollars conversion, the
// spend-zone classification (the visible near/over-cap warning state), and the
// progress-fraction math live here as small, independently unit-tested pure
// functions — so the React component (SpendCap.tsx) stays thin presentation and
// the gate's 100% branch coverage is reachable without DOM gymnastics.
//
// Design invariants honored by the consumer (SpendCap.tsx):
//   * the spend STATE is conveyed by TEXT + ICON, never hue alone (WCAG 1.4.1);
//   * a fully-unconfigured install (both caps 0) reads as a benign "no cap" —
//     the backend explicitly returns zero/false there.

import type { SpendInfo } from '../lib/rpc';

/** The visible month-to-date spend state, ordered low->high severity. */
export type SpendZone =
  | 'no-cap' // no soft AND no hard cap configured — informational only
  | 'ok' // under the soft cap (or under hard when only hard is set)
  | 'near' // at/over the soft cap but under the hard cap (warning)
  | 'blocked'; // at/over the hard cap (over-limit; new cloud runs refused if enforced)

/** Cents -> a fixed 2-dp dollar STRING for an input value ("12.5" cents=1250 -> "12.50"). */
export function centsToDollars(cents: number): string {
  if (!Number.isFinite(cents) || cents <= 0) return '0.00';
  return (Math.round(cents) / 100).toFixed(2);
}

/** Cents -> a "$12.50" display string (compact, no thousands grouping). */
export function formatDollars(cents: number): string {
  return `$${centsToDollars(cents)}`;
}

/**
 * A dollar input STRING -> integer cents. Blank / non-numeric / negative all
 * coerce to 0 (a defensive, never-throws boundary), and fractional cents round
 * to the nearest cent ("12.005" -> 1201 is intentionally avoided: 12.005*100 =
 * 1200.4999.. so Math.round gives 1200; we round the cents, not the dollars).
 */
export function dollarsToCents(value: string): number {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.round(n * 100);
}

/**
 * Classify the month-to-date spend against the configured caps. A cap of 0 (or
 * absent) means "not set" for that tier. Precedence: hard (blocked) wins over
 * soft (near); with neither set, the view is informational ("no-cap").
 */
export function spendZone(info: SpendInfo): SpendZone {
  const soft = info.softLimitCents > 0 ? info.softLimitCents : 0;
  const hard = info.hardLimitCents > 0 ? info.hardLimitCents : 0;
  const mtd = Math.max(0, info.monthToDateCents);
  if (soft === 0 && hard === 0) return 'no-cap';
  if (hard > 0 && mtd >= hard) return 'blocked';
  if (soft > 0 && mtd >= soft) return 'near';
  return 'ok';
}

/**
 * The progress denominator (cents): the hard cap when set, else the soft cap.
 * Returns 0 when neither is configured (the caller then renders an MTD-only view
 * with no bounded bar).
 */
export function progressCeilingCents(info: SpendInfo): number {
  if (info.hardLimitCents > 0) return info.hardLimitCents;
  if (info.softLimitCents > 0) return info.softLimitCents;
  return 0;
}

/**
 * Bar fill fraction (0..1), clamped. Zero ceiling -> 0 (no bounded bar). An MTD
 * over the ceiling clamps to a full bar (the over-limit state carries its own
 * text/icon signal, so the bar never reads >100%).
 */
export function progressFraction(info: SpendInfo): number {
  const ceiling = progressCeilingCents(info);
  if (ceiling <= 0) return 0;
  const frac = Math.max(0, info.monthToDateCents) / ceiling;
  return Math.min(1, frac);
}

/** Whole-number progress percent (0..100) for aria-valuenow + width. */
export function progressPercent(info: SpendInfo): number {
  return Math.round(progressFraction(info) * 100);
}

/** The non-color glyph per zone (so the state is never signalled by hue alone). */
export function zoneGlyph(zone: SpendZone): string {
  switch (zone) {
    case 'blocked':
      return '⛔';
    case 'near':
      return '⚠';
    case 'ok':
      return '✓';
    default:
      return 'ℹ';
  }
}

/**
 * Plain-language status line for the current zone. `enforceHardLimit` only
 * changes the BLOCKED copy: enforced -> new cloud runs are refused; not enforced
 * -> over the cap, but runs are still allowed (the user set a soft ceiling only,
 * or left enforcement off).
 */
export function zoneMessage(zone: SpendZone, enforceHardLimit: boolean): string {
  switch (zone) {
    case 'blocked':
      return enforceHardLimit
        ? 'Hard cap reached — new cloud runs are blocked until next month or a higher cap.'
        : 'Over the hard cap — not enforced, so cloud runs still proceed. Turn on enforcement to block them.';
    case 'near':
      return 'Near the soft cap — approaching your monthly budget.';
    case 'ok':
      return 'Within budget this month.';
    default:
      return 'No spend cap set — cloud spend is unlimited. Set a cap to stay on budget.';
  }
}
