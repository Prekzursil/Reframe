// OpenRouterUsage.tsx — per-key OpenRouter COST rows (WU-models/device,
// deliverable G-2: per-key usage/consumption shows cost). The calls/tokens axes
// live in <UsageBars/>; this adds the spend axis OpenRouter uniquely exposes
// (cumulative credit usage in USD + limit + remaining). Keys are the REDACTED
// last-4 only — a live key never reaches the renderer. Pure presentation.
import React from 'react';
import type { OpenRouterUsageRow } from '../lib/rpc';

/** Format a USD amount as "$1.50", or "—" for an unknown/absent value. */
export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return `$${value.toFixed(2)}`;
}

export interface OpenRouterUsageProps {
  /** Per-key OpenRouter cost rows (already redacted) from providers.openrouterUsage. */
  rows: OpenRouterUsageRow[];
}

export function OpenRouterUsage({ rows }: OpenRouterUsageProps): React.ReactElement {
  if (rows.length === 0) {
    return (
      <p className="openrouter-usage-empty" data-openrouter="empty">
        No OpenRouter cost data — add an OpenRouter key (or check your connection) to see spend
        here.
      </p>
    );
  }
  return (
    <div className="openrouter-usage" data-openrouter="rows" data-row-count={rows.length}>
      {rows.map((row, i) => {
        const cooldown = row.status === 'cooldown';
        return (
          <div
            className={`openrouter-usage__row${cooldown ? ' is-cooldown' : ''}`}
            key={`${row.provider}:${row.key}:${i}`}
            data-provider={row.provider}
            data-free={row.isFreeTier ? 'true' : 'false'}
            data-status={row.status}
          >
            <span className="openrouter-usage__key">
              {row.provider} key {row.key}
            </span>
            <span
              className="openrouter-usage__cost"
              data-field="cost"
              title="Cumulative credit spend"
            >
              {formatUsd(row.costUsd)} spent
            </span>
            <span className="openrouter-usage__remaining" data-field="remaining">
              {row.limitUsd === null
                ? 'no credit limit'
                : `${formatUsd(row.remainingUsd)} of ${formatUsd(row.limitUsd)} left`}
            </span>
            {row.isFreeTier && (
              <span className="openrouter-usage__free" data-field="free-tier">
                free tier
              </span>
            )}
            {/* M4: a parked key stays in the pool (cooldown-not-delete) and shows
                WHY it stopped serving (402/429 or the free-tier credit cap). */}
            <span
              className={`openrouter-usage__status openrouter-usage__status--${row.status}`}
              data-field="status"
              role={cooldown ? 'status' : undefined}
            >
              {cooldown ? 'on cooldown' : 'active'}
            </span>
            {cooldown && row.cooldownReason !== null && (
              <span className="openrouter-usage__cooldown-reason" data-field="cooldown-reason">
                {row.cooldownReason}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default OpenRouterUsage;
