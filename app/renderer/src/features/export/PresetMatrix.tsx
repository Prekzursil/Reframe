// PresetMatrix.tsx — the per-platform destination matrix (v1.5 §4 Export).
//
// A REAL fieldset/radiogroup (role="radiogroup" of role="radio" options with
// aria-checked + roving tabindex + arrow-key selection), NOT a grid of equal-weight
// tiles. Every option is a recognizable DESTINATION (TikTok / Reels / Shorts…)
// showing its TARGET aspect + length — never codec/bitrate jargon. A hint states
// that aspect is set upstream in Reframe (Export keeps the current framing), so the
// per-destination badge never implies Export re-crops the frame. Options carry three
// states: SELECTED (the amber ring), AVAILABLE (selectable), and UNAVAILABLE (the
// clip is longer than the platform's cap — blocked with a stated reason). While the
// export is confirming/running the whole group is disabled so the choice is locked.
//
// Controlled + presentational: the parent owns `value` and gets `onChange(id)`.
// The keyboard math (skip-unavailable, wrap) is the pure `rovingIndex` helper.

import React, { useRef } from 'react';
import { PLATFORM_PRESETS, presetAvailability, rovingIndex } from './exportModel';
import './export.css';

export interface PresetMatrixProps {
  /** The selected destination id (parent-owned). */
  value: string;
  /** Called with the chosen destination id. */
  onChange: (id: string) => void;
  /** The clip length (seconds) — drives per-destination availability. */
  durationSec: number;
  /** Locks the whole group while the export is confirming/running. */
  disabled?: boolean;
}

export function PresetMatrix({
  value,
  onChange,
  durationSec,
  disabled = false,
}: PresetMatrixProps): React.ReactElement {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const selectable = PLATFORM_PRESETS.map(
    (preset) => presetAvailability(preset, durationSec).status === 'available',
  );
  const current = PLATFORM_PRESETS.findIndex((preset) => preset.id === value);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (disabled) return;
    const next = rovingIndex(event.key, current, selectable);
    if (next === current) return;
    event.preventDefault();
    onChange(PLATFORM_PRESETS[next].id);
    buttons.current[next]?.focus();
  };

  return (
    <fieldset className="preset-matrix">
      <legend className="preset-matrix__legend">Deliver to</legend>
      <p className="preset-matrix__hint">
        Aspect is set in Reframe — Export keeps your current framing.
      </p>
      <div
        className="preset-matrix__grid"
        role="radiogroup"
        aria-label="Delivery destination"
        onKeyDown={onKeyDown}
      >
        {PLATFORM_PRESETS.map((preset, index) => {
          const availability = presetAvailability(preset, durationSec);
          const unavailable = availability.status === 'unavailable';
          const selected = preset.id === value;
          return (
            <button
              key={preset.id}
              ref={(el) => {
                buttons.current[index] = el;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              disabled={disabled || unavailable}
              className={`preset-option${selected ? ' is-selected' : ''}${unavailable ? ' is-unavailable' : ''}`}
              data-preset={preset.id}
              onClick={() => onChange(preset.id)}
            >
              <span className="preset-option__head">
                <span className="preset-option__name">{preset.name}</span>
                <span className="preset-option__aspect">{preset.aspect}</span>
              </span>
              <span className="preset-option__blurb">{preset.blurb}</span>
              <span className="preset-option__length">{preset.lengthHint}</span>
              {unavailable ? (
                <span className="preset-option__reason">{availability.reason}</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export default PresetMatrix;
