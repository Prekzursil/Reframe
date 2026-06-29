// AlignModelSelect.tsx — M5 word-timing alignment model opt-in (incl. Romanian).
//
// The CTC forced-aligner default is MMS-300M (CC-BY-NC, 158 languages); this
// control exposes the opt-in overrides the sidecar `ctc_align._resolve_model_id`
// understands via `settings['ctcModelId']`: the Romanian wav2vec2
// (gigant/romanian-wav2vec2) for RO-language alignment, plus the MIT English
// wav2vec2 for a commercial build. Selecting the default persists an EMPTY
// `ctcModelId` so the package default applies (no silent override).
import React from 'react';

/** One selectable alignment model. `id` is the `ctcModelId` value ('' = default). */
export interface AlignModelChoice {
  id: string;
  label: string;
}

/** The default MMS pick + the M5 opt-ins (aliases the sidecar resolves). */
export const ALIGN_MODEL_CHOICES: AlignModelChoice[] = [
  { id: '', label: 'MMS-300M — default (158 languages)' },
  { id: 'romanian-wav2vec2', label: 'Romanian — gigant/romanian-wav2vec2' },
  { id: 'wav2vec2-960h-lv60', label: 'English wav2vec2 (MIT, commercial)' },
];

export interface AlignModelSelectProps {
  /** Current persisted `ctcModelId` ('' / undefined = the MMS default). */
  value: string;
  /** Persist the chosen alignment model id (the parent writes `ctcModelId`). */
  onChange: (ctcModelId: string) => void;
  /** Disable the control while a write is in flight. */
  busy?: boolean;
}

export function AlignModelSelect({
  value,
  onChange,
  busy,
}: AlignModelSelectProps): React.ReactElement {
  // An unknown persisted id (e.g. a hand-typed full HF id) shows as the default
  // row visually but is NOT lost — we only overwrite it when the user picks a row.
  const known = ALIGN_MODEL_CHOICES.some((c) => c.id === value);
  return (
    <div className="align-model" data-section="align-model">
      <label htmlFor="align-model-select">Word-timing alignment model</label>
      <select
        id="align-model-select"
        data-action="align-model"
        value={known ? value : ''}
        disabled={Boolean(busy)}
        onChange={(e) => onChange(e.target.value)}
      >
        {ALIGN_MODEL_CHOICES.map((choice) => (
          <option key={choice.id || 'default'} value={choice.id}>
            {choice.label}
          </option>
        ))}
      </select>
      {!known && value && (
        <span className="align-model__custom" data-testid="align-model-custom">
          custom: {value}
        </span>
      )}
    </div>
  );
}

export default AlignModelSelect;
