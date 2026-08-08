// PresetMatrix.tsx — the per-platform destination matrix (v1.5 §4 Export).
//
// A REAL fieldset/checkbox-group (role="group" of role="checkbox" options with
// aria-checked + roving tabindex + arrow-key navigation), NOT a grid of equal-weight
// tiles. Every option is a recognizable DESTINATION (TikTok / Reels / Shorts…)
// showing its TARGET aspect + length — never codec/bitrate jargon. Options carry
// three states: SELECTED (the amber ring), AVAILABLE (selectable), and UNAVAILABLE
// (the clip is longer than the platform's cap — blocked with a stated reason).
// While the export is confirming/running the whole group is disabled so the choice
// is locked.
//
// MULTI-SELECT (v1.5 aspect-matrix lane). This used to be a single-selection
// radiogroup whose hint read "aspect is set upstream in Reframe (Export keeps the
// current framing)" — which made the per-destination aspect badge decorative and
// made a multi-aspect fan-out impossible anywhere but the batch surface. The group
// now takes a SET, so one source can target several aspects in one action, and the
// hint states the real rule: one file per DISTINCT aspect (three vertical
// destinations are one 9:16 render, not three). The ≥1 invariant lives in the pure
// `togglePresetId`, so un-checking the last box is a no-op rather than a state the
// guarded commit would have to defend against.
//
// Keyboard follows the WAI-ARIA CHECKBOX-group pattern, which differs from the
// radiogroup one this replaced: arrows/Home/End move FOCUS only, and Space/Enter
// toggle (handled natively by the <button>). Selecting on arrow — correct for a
// radiogroup — would silently check destinations as the user browsed.
//
// Controlled + presentational: the parent owns `values` and gets `onChange(ids)`.
// The keyboard math (skip-unavailable, wrap) is the pure `rovingIndex` helper.

import React, { useRef, useState } from 'react';
import { PLATFORM_PRESETS, presetAvailability, rovingIndex, togglePresetId } from './exportModel';
import './export.css';

export interface PresetMatrixProps {
  /** The selected destination ids (parent-owned; always at least one). */
  values: readonly string[];
  /** Called with the NEXT full selection whenever a destination is toggled. */
  onChange: (ids: string[]) => void;
  /** The clip length (seconds) — drives per-destination availability. */
  durationSec: number;
  /** Locks the whole group while the export is confirming/running. */
  disabled?: boolean;
}

export function PresetMatrix({
  values,
  onChange,
  durationSec,
  disabled = false,
}: PresetMatrixProps): React.ReactElement {
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  // Where the roving tabindex sits. `null` until the user navigates, so the tab
  // stop starts on the first CHECKED destination (what a returning user expects)
  // and then follows their arrow keys.
  const [focusIndex, setFocusIndex] = useState<number | null>(null);

  const selectable = PLATFORM_PRESETS.map(
    (preset) => presetAvailability(preset, durationSec).status === 'available',
  );
  const firstChecked = PLATFORM_PRESETS.findIndex((preset) => values.includes(preset.id));
  const anchor = focusIndex ?? Math.max(0, firstChecked);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    if (disabled) return;
    const next = rovingIndex(event.key, anchor, selectable);
    if (next === anchor) return;
    event.preventDefault();
    setFocusIndex(next);
    buttons.current[next]?.focus();
  };

  return (
    <fieldset className="preset-matrix">
      <legend className="preset-matrix__legend">Deliver to</legend>
      <p className="preset-matrix__hint">
        Pick every destination you need — one file is rendered per distinct aspect.
      </p>
      <div
        className="preset-matrix__grid"
        role="group"
        aria-label="Delivery destinations"
        onKeyDown={onKeyDown}
      >
        {PLATFORM_PRESETS.map((preset, index) => {
          const availability = presetAvailability(preset, durationSec);
          const unavailable = availability.status === 'unavailable';
          const selected = values.includes(preset.id);
          return (
            <button
              key={preset.id}
              ref={(el) => {
                buttons.current[index] = el;
              }}
              type="button"
              role="checkbox"
              aria-checked={selected}
              tabIndex={index === anchor ? 0 : -1}
              disabled={disabled || unavailable}
              className={`preset-option${selected ? ' is-selected' : ''}${unavailable ? ' is-unavailable' : ''}`}
              data-preset={preset.id}
              onClick={() => onChange(togglePresetId(values, preset.id))}
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
