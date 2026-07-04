// ProviderUsageAvailability.tsx — honest per-provider "is there a provider-side
// usage API?" notes (WU-D4). The LOCAL request/token counters live in <UsageBars/>
// and OpenRouter's live COST in <OpenRouterUsage/>; this states the truth for every
// OTHER configured cloud provider: OpenAI/Anthropic gate usage behind an org admin
// key and others publish nothing per-key, so we show "Usage API not available for
// <provider>" instead of a fabricated number. Pure presentation (no RPC).
import React from 'react';
import type { ProviderUsageAvailability as UsageAvailabilityRow } from '../lib/rpc';

export interface ProviderUsageAvailabilityProps {
  /** Per-provider availability rows from providers.usageAvailability. */
  rows: UsageAvailabilityRow[];
}

export function ProviderUsageAvailability({
  rows,
}: ProviderUsageAvailabilityProps): React.ReactElement | null {
  // Nothing configured yet → render nothing (the surrounding usage section already
  // shows its own empty state); an empty note list would just be visual noise.
  if (rows.length === 0) return null;
  return (
    <ul
      className="usage-availability"
      data-usage-availability="rows"
      data-row-count={rows.length}
      aria-label="Provider usage API availability"
    >
      {rows.map((row) => (
        <li
          className={`usage-availability__row${row.hasUsageApi ? ' is-available' : ' is-unavailable'}`}
          key={row.provider}
          data-provider={row.provider}
          data-available={row.hasUsageApi ? 'true' : 'false'}
        >
          <span className="usage-availability__glyph" aria-hidden="true">
            {row.hasUsageApi ? '✓' : 'ⓘ'}
          </span>
          <span className="usage-availability__message">{row.message}</span>
        </li>
      ))}
    </ul>
  );
}

export default ProviderUsageAvailability;
