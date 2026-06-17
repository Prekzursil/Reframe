// ResourceBar.tsx — a labelled horizontal availability bar (used / total MB)
// for the hardware header (VRAM budget, system RAM). The fill tints amber once
// it crosses TIGHT_FRACTION so a near-full resource reads as "tight" at a
// glance. Pure presentational; all math lives in advisorMeta (fillPct/fillZone).
import React from 'react';
import { fillPct, fillZone, fmtMb, TIGHT_FRACTION } from './advisorMeta';

export interface ResourceBarProps {
  /** Caption (e.g. "VRAM budget", "System RAM"). */
  label: string;
  /** The filled portion in MB (e.g. the model VRAM budget), or null if unknown. */
  used: number | null;
  /** The total capacity in MB, or null if the probe found nothing. */
  total: number | null;
  /** Optional extra tooltip copy appended to the standard explanation. */
  hint?: string;
}

const BUDGET_NOTE =
  'Models load one at a time; this is the VRAM budget each heavy model must fit under.';

export function ResourceBar({ label, used, total, hint }: ResourceBarProps): React.ReactElement {
  const pct = fillPct(used, total);
  const zone = fillZone(used, total);
  const unknown = total === null || total === undefined || total <= 0;
  const valueText = unknown ? 'not detected' : `${fmtMb(used)} / ${fmtMb(total)}`;
  const tip = [BUDGET_NOTE, `Amber once over ${Math.round(TIGHT_FRACTION * 100)}% full.`, hint]
    .filter(Boolean)
    .join(' ');

  return (
    <div className="resource-bar" data-label={label} title={tip}>
      <div className="resource-bar__head">
        <span className="resource-bar__label">{label}</span>
        <span className="resource-bar__value">{valueText}</span>
      </div>
      <div
        className="resource-bar__track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={valueText}
      >
        <div
          className={`resource-bar__fill is-${zone}`}
          data-zone={zone}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default ResourceBar;
