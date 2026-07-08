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

/** Id linking the Auto segment to its inline helper (aria-describedby). */
const AUTO_HELP_ID = 'routing-auto-help';

export function RoutingToggle({ value, onChange, busy }: RoutingToggleProps): React.ReactElement {
  return (
    <div className="routing-toggle" role="group" aria-label="AI routing">
      <span className="routing-toggle__label">Where jobs run</span>
      {MODES.map(({ mode, label }) => (
        <button
          key={mode}
          type="button"
          data-mode={mode}
          className={`routing-toggle__btn${value === mode ? ' is-active' : ''}`}
          aria-pressed={value === mode}
          aria-describedby={mode === 'auto' ? AUTO_HELP_ID : undefined}
          disabled={Boolean(busy)}
          // No-op on the active mode so the toggle never re-writes the same value.
          onClick={() => value !== mode && onChange(mode)}
        >
          {label}
        </button>
      ))}
      {/* Cloud-capable modes (cloud/auto) get the tokenized egress-warning DOT:
          data could leave the machine. The accessible name carries the meaning;
          the dot itself is decorative colour. */}
      {value !== 'local' && (
        <span
          className="routing-toggle__egress"
          data-testid="routing-egress-hint"
          role="img"
          aria-label="Cloud routing can send data off this machine"
          title="Cloud routing can send data to a provider"
        />
      )}
      {/* One-line inline helper, revealed on hover/focus of the Auto segment
          (CSS-driven). Always in the DOM so it can describe the Auto button. */}
      <span id={AUTO_HELP_ID} className="routing-toggle__helper" role="note">
        Auto = fastest available, may use cloud
      </span>
    </div>
  );
}

export default RoutingToggle;
