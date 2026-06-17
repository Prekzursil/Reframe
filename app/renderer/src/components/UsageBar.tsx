// UsageBar.tsx — data-driven per-key usage bars (PLAN §WU-usage-ui).
//
// The rotation pool accounts per-key usage from optimistic decrement + parsed
// 429 / X-RateLimit-* headers (NOT a poller); providers.usage surfaces it as
// rows {provider, key, used, max, unit, resetAt, stale, lastCheckedAt}. This
// component renders that, honoring the gate-2 Designer invariants:
//
//   * color is NEVER the only signal — every band carries a non-color GLYPH +
//     a numeric label ("820 / 1000 req" or "1.2M / 4M tok"), WCAG-safe;
//   * fill = REMAINING / max (green >= 60% / yellow 30-60% / red < 30%);
//   * REQ-limited and TOKEN-limited keys are NEVER summed — a mixed pool renders
//     TWO SEPARATE grouped bars (a positively-tested path, not a dead branch);
//   * same-unit stacking across DISTINCT providers; the "superpowered" purple
//     state fires at >= 3 same-unit HEALTHY keys across DISTINCT providers, with
//     an ALWAYS-present text label + tooltip;
//   * prefers-reduced-motion disables the fill transition;
//   * stale (>10 min) rows desaturate + show "last checked Xm ago".
//
// Pure presentation + small exported helpers; owns NO rpc (the panel feeds rows).
import React, { useMemo } from 'react';
import './usageBar.css';
import type { UsageRow } from '../lib/rpc';

/** A usage row's color band from how much quota REMAINS (DESIGN §G3 thresholds). */
export type UsageZone = 'healthy' | 'warn' | 'critical';

/** The "superpowered" threshold: >= this many same-unit healthy DISTINCT providers. */
export const SUPERPOWERED_MIN = 3;
/** A key is "healthy" (counts toward superpowered) at >= this remaining fraction. */
export const HEALTHY_FRACTION = 0.6;

/** Remaining fraction (0..1) for a row; an unknown/zero max reads as fully healthy. */
export function remainingFraction(row: UsageRow): number {
  if (row.max === null || row.max === undefined || row.max <= 0) return 1;
  const used = Math.max(0, Math.min(row.used, row.max));
  return (row.max - used) / row.max;
}

/** Color zone from the remaining fraction (green >= 60 / yellow 30-60 / red < 30). */
export function usageZone(fraction: number): UsageZone {
  if (fraction >= HEALTHY_FRACTION) return 'healthy';
  if (fraction >= 0.3) return 'warn';
  return 'critical';
}

/** The non-color glyph per zone (so color is never the sole signal — WCAG). */
export function zoneGlyph(zone: UsageZone): string {
  if (zone === 'healthy') return '●';
  if (zone === 'warn') return '◐';
  return '○';
}

/** A human label for the unit ("req" -> "req", "token" -> "tok"). */
export function unitLabel(unit: string): string {
  return unit === 'token' ? 'tok' : 'req';
}

/** Compact a count: 1_200_000 -> "1.2M", 4_000 -> "4K", 820 -> "820". */
export function compactCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

/**
 * The numeric label for a row ("820 / 1000 req" or "1.2M / 4M tok"). Token counts
 * are compacted (they run to millions); request counts stay raw integers (they
 * are small and the exact ceiling matters), per the PLAN's example labels.
 */
export function numericLabel(row: UsageRow): string {
  const u = unitLabel(row.unit);
  const fmt = (n: number): string => (row.unit === 'token' ? compactCount(n) : String(n));
  if (row.max === null || row.max === undefined || row.max <= 0) {
    return `${fmt(row.used)} ${u}`;
  }
  return `${fmt(row.used)} / ${fmt(row.max)} ${u}`;
}

/** "last checked Xm ago" from the row's lastCheckedAt + now (seconds). */
export function staleAgeLabel(lastCheckedAt: number, nowSec: number): string {
  const mins = Math.max(0, Math.round((nowSec - lastCheckedAt) / 60));
  return `last checked ${mins}m ago`;
}

/** Group rows by unit, preserving first-seen order (REQ + TOKEN never merge). */
export function groupByUnit(rows: UsageRow[]): { unit: string; rows: UsageRow[] }[] {
  const groups: { unit: string; rows: UsageRow[] }[] = [];
  const byUnit = new Map<string, { unit: string; rows: UsageRow[] }>();
  for (const row of rows) {
    const existing = byUnit.get(row.unit);
    if (existing) {
      existing.rows.push(row);
    } else {
      const group = { unit: row.unit, rows: [row] };
      byUnit.set(row.unit, group);
      groups.push(group);
    }
  }
  return groups;
}

/**
 * Whether a same-unit group is "superpowered": >= SUPERPOWERED_MIN HEALTHY keys
 * across DISTINCT providers. Two healthy keys, or three keys spanning only two
 * providers, do NOT qualify (DESIGN §14).
 */
export function isSuperpowered(rows: UsageRow[]): boolean {
  const healthyProviders = new Set<string>();
  for (const row of rows) {
    if (remainingFraction(row) >= HEALTHY_FRACTION) healthyProviders.add(row.provider);
  }
  return healthyProviders.size >= SUPERPOWERED_MIN;
}

/** Detect prefers-reduced-motion (testable via window.matchMedia). */
export function prefersReducedMotion(): boolean {
  /* v8 ignore next -- jsdom always defines matchMedia in tests; the typeof guard only matters in a non-DOM host. */
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

interface SingleBarProps {
  row: UsageRow;
  reducedMotion: boolean;
  nowSec: number;
}

/** One key's bar: fill = remaining, glyph + numeric label, stale desaturation. */
function SingleBar({ row, reducedMotion, nowSec }: SingleBarProps): React.ReactElement {
  const fraction = remainingFraction(row);
  const zone = usageZone(fraction);
  const pct = Math.round(fraction * 100);
  const glyph = zoneGlyph(zone);
  const numeric = numericLabel(row);
  const title = `${row.provider} key ${row.key}: ${numeric} remaining (${pct}%)`;
  const classNames = [
    'usage-bar',
    `is-${zone}`,
    row.stale ? 'is-stale' : '',
    reducedMotion ? 'is-reduced-motion' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      className={classNames}
      data-provider={row.provider}
      data-zone={zone}
      data-stale={row.stale ? 'true' : 'false'}
      title={title}
    >
      <div className="usage-bar__head">
        <span className="usage-bar__glyph" aria-hidden="true" data-glyph={glyph}>
          {glyph}
        </span>
        <span className="usage-bar__provider">{row.provider}</span>
        <span className="usage-bar__value">{numeric}</span>
      </div>
      <div
        className="usage-bar__track"
        role="meter"
        aria-label={`${row.provider} usage (key ${row.key})`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={`${numeric} remaining`}
      >
        <div className="usage-bar__fill" data-zone={zone} style={{ width: `${pct}%` }} />
      </div>
      {row.stale && (
        <span className="usage-bar__stale" data-stale-note="true">
          {staleAgeLabel(row.lastCheckedAt ?? nowSec, nowSec)}
        </span>
      )}
    </div>
  );
}

export interface UsageBarsProps {
  /** Per-key usage rows from providers.usage (already redacted + stale-flagged). */
  rows: UsageRow[];
  /** Inject "now" (seconds) for deterministic stale-age labels in tests. */
  nowSec?: number;
}

/**
 * The full loaded-providers usage section: rows grouped by unit (REQ + TOKEN
 * never summed -> >=2 separate grouped bars on a mixed pool), each group flagged
 * superpowered when >= 3 healthy keys span distinct providers.
 */
export function UsageBars({ rows, nowSec }: UsageBarsProps): React.ReactElement {
  const reducedMotion = useMemo(() => prefersReducedMotion(), []);
  const now = nowSec ?? Date.now() / 1000;
  const groups = groupByUnit(rows);

  if (groups.length === 0) {
    return (
      <p className="usage-empty" data-usage="empty">
        No provider keys yet — add a key to see live usage here.
      </p>
    );
  }

  return (
    <div className="usage-groups" data-usage="groups" data-group-count={groups.length}>
      {groups.map((group) => {
        const superpowered = isSuperpowered(group.rows);
        return (
          <section
            key={group.unit}
            className={`usage-group${superpowered ? ' is-superpowered' : ''}`}
            data-unit={group.unit}
            data-superpowered={superpowered ? 'true' : 'false'}
            aria-label={`${unitLabel(group.unit)} usage`}
          >
            <header className="usage-group__head">
              <span className="usage-group__unit">{unitLabel(group.unit)} limits</span>
              {superpowered && (
                <span
                  className="usage-group__superpowered"
                  data-label="superpowered"
                  title={`Superpowered: ${SUPERPOWERED_MIN}+ healthy keys across distinct providers rotate this unit — high headroom.`}
                >
                  ⚡ Superpowered
                </span>
              )}
            </header>
            <div className="usage-group__bars">
              {group.rows.map((row, i) => (
                <SingleBar
                  key={`${row.provider}:${row.key}:${i}`}
                  row={row}
                  reducedMotion={reducedMotion}
                  nowSec={now}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export default UsageBars;
