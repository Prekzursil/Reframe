// RoutingOverrideTable.tsx — M5 Settings/Advanced per-function routing overrides.
//
// The per-function half of the single `RoutingPolicy` (DESIGN §2.1/§2.4): the
// header `RoutingToggle` sets `global`; this table sets `overrides[fn]`. Each row
// is a `<select>` of Global default / Local / Cloud / Auto. Choosing "Global
// default" REMOVES the override (the function inherits the global mode). On any
// change it persists the WHOLE policy ({global, overrides}) via `onApply` — the
// sidecar `setRoutingPolicy` write is a full replace, so we always send `global`
// too (never clobber it to the local default).
import React from 'react';
import type { RoutingMode, RoutingPolicy } from '../lib/rpc';
import {
  AI_FUNCTIONS,
  AI_FUNCTION_LABELS,
  OVERRIDE_CHOICES,
  OVERRIDE_LABELS,
  applyOverrideChoice,
  choiceFor,
  type AiFunction,
  type OverrideChoice,
} from './routingFunctions';

export interface RoutingOverrideTableProps {
  /** The current persisted policy (from `models.overview` -> routingPolicy). */
  policy: RoutingPolicy;
  /** Persist the FULL edited policy ({global, overrides}); the parent writes it. */
  onApply: (policy: RoutingPolicy) => void;
  /** Disable every control while a write is in flight. */
  busy?: boolean;
}

export function RoutingOverrideTable({
  policy,
  onApply,
  busy,
}: RoutingOverrideTableProps): React.ReactElement {
  const overrides: Record<string, RoutingMode> = policy.overrides ?? {};

  const change = (fn: AiFunction, choice: OverrideChoice): void => {
    onApply({ global: policy.global, overrides: applyOverrideChoice(overrides, fn, choice) });
  };

  return (
    <details className="routing-overrides">
      <summary>Per-function routing (Advanced)</summary>
      <p className="routing-overrides__intro">
        Override where each AI step runs. “Global default” follows the header
        Local/Cloud/Auto toggle ({OVERRIDE_LABELS[policy.global]}).
      </p>
      <ul className="routing-overrides__list" data-section="routing-overrides">
        {AI_FUNCTIONS.map((fn) => {
          const current = choiceFor(overrides, fn);
          return (
            <li key={fn} className="routing-overrides__row" data-fn={fn}>
              <label htmlFor={`route-${fn}`} className="routing-overrides__label">
                {AI_FUNCTION_LABELS[fn]}
              </label>
              <select
                id={`route-${fn}`}
                data-action={`route-${fn}`}
                value={current}
                disabled={Boolean(busy)}
                onChange={(e) => change(fn, e.target.value as OverrideChoice)}
              >
                {OVERRIDE_CHOICES.map((choice) => (
                  <option key={choice} value={choice}>
                    {OVERRIDE_LABELS[choice]}
                  </option>
                ))}
              </select>
              {(current === 'cloud' || current === 'auto') && (
                <span className="routing-overrides__egress" data-testid={`egress-${fn}`}>
                  may egress
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

export default RoutingOverrideTable;
