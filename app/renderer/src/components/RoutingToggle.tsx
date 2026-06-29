// RoutingToggle.tsx — the M3 header global AI-routing toggle (Local/Cloud/Auto).
//
// The single header control for the cross-cutting RoutingPolicy.global (DESIGN
// §2.1/§2.4, V1-GRILL §h E6): where AI work runs by default. `local` never
// egresses; `cloud` uses a provider key (shows an egress hint); `auto` prefers
// the device-appropriate path and degrades loudly to local. DECISION §4: the
// default is `local` and it NEVER auto-promotes — it only moves on an explicit
// click (re-clicking the active mode is a no-op, so there is no settings churn).
import React from 'react';
import type { RoutingMode } from '../lib/rpc';

const MODES: { mode: RoutingMode; label: string }[] = [
  { mode: 'local', label: 'Local' },
  { mode: 'cloud', label: 'Cloud' },
  { mode: 'auto', label: 'Auto' },
];

export interface RoutingToggleProps {
  /** The current RoutingPolicy.global mode. */
  value: RoutingMode;
  /** Called with the newly-selected mode (never with the already-active one). */
  onChange: (mode: RoutingMode) => void;
  /** Disable the control while a write is in flight. */
  busy?: boolean;
}

export function RoutingToggle({ value, onChange, busy }: RoutingToggleProps): React.ReactElement {
  return (
    <div className="routing-toggle" role="group" aria-label="AI routing">
      <span className="routing-toggle__label">Routing</span>
      {MODES.map(({ mode, label }) => (
        <button
          key={mode}
          type="button"
          data-mode={mode}
          className={`routing-toggle__btn${value === mode ? ' is-active' : ''}`}
          aria-pressed={value === mode}
          disabled={Boolean(busy)}
          // No-op on the active mode so the toggle never re-writes the same value.
          onClick={() => value !== mode && onChange(mode)}
        >
          {label}
        </button>
      ))}
      {value !== 'local' && (
        <span
          className="routing-toggle__egress"
          data-testid="routing-egress-hint"
          title="Cloud routing can send data to a provider"
        >
          may egress
        </span>
      )}
    </div>
  );
}

export default RoutingToggle;
