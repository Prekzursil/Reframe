// CaptionDelivery.tsx — the burn reversibility signal as a GUARDED choice (§4).
//
// Captions ship one of two ways, and the difference is irreversible-vs-reversible:
//   * SOFT track  — muxed as a selectable subtitle stream: viewers can toggle it,
//                   and you can restyle or remove it anytime (lossless, reversible).
//   * BURN IN     — hardsub: the pixels are baked into the frames permanently.
//
// The redesign requires the reversibility be surfaced as a GUARDED choice, not a
// silent toggle, so a permanent bake is never a surprise. Choosing "Burn in"
// raises an assertive, amber-flagged permanence warning. Controlled + presentational.

import React from 'react';
import './captionDelivery.css';

/** How the captions are delivered: a toggleable soft track or a permanent burn. */
export type CaptionDeliveryMode = 'soft' | 'hard';

const OPTIONS: readonly { id: CaptionDeliveryMode; label: string }[] = [
  { id: 'soft', label: 'Soft track' },
  { id: 'hard', label: 'Burn in' },
];

export interface CaptionDeliveryProps {
  value: CaptionDeliveryMode;
  onChange: (mode: CaptionDeliveryMode) => void;
}

export function CaptionDelivery({ value, onChange }: CaptionDeliveryProps): React.ReactElement {
  const permanent = value === 'hard';
  return (
    <div className="caption-delivery" role="group" aria-label="Caption delivery">
      <span className="caption-delivery__label">Delivery</span>
      <div
        className="caption-delivery__options"
        role="radiogroup"
        aria-label="Caption delivery mode"
      >
        {OPTIONS.map((option) => {
          const selected = value === option.id;
          return (
            <button
              key={option.id}
              type="button"
              role="radio"
              aria-checked={selected}
              className={`caption-delivery__option${selected ? ' is-active' : ''}`}
              onClick={() => onChange(option.id)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      <p
        className={`caption-delivery__note${permanent ? ' is-warning' : ''}`}
        role={permanent ? 'alert' : undefined}
      >
        {permanent
          ? 'Burned-in captions are permanent — they cannot be turned off later. Re-export from source to change them.'
          : 'A soft track — viewers can toggle captions on or off, and you can restyle or remove them anytime.'}
      </p>
    </div>
  );
}

export default CaptionDelivery;
