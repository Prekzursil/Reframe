// AlignModelSelect.tsx — word-timing alignment model picker + the WU-T0 licence gate.
//
// The picker exposes the overrides the sidecar `ctc_align._resolve_model_id`
// understands via `settings['ctcModelId']`. Since WU-T0/B1 the PACKAGED default
// is the Apache-2.0 English wav2vec2 (`facebook/wav2vec2-large-960h-lv60-self`),
// NOT the CC-BY-NC-4.0 MMS model it used to be, and MMS is reachable only when
// `settings['allowNonCommercialAligner']` is on. Selecting the default persists
// an EMPTY `ctcModelId` so the package default applies (no silent override).
//
// The MMS row is rendered but DISABLED until the opt-in is on: the sidecar
// silently downgrades an MMS request when the flag is off, and an option whose
// effect the backend discards is worse than one that visibly cannot be chosen.
// Licence facts: HF Hub metadata probe, 2026-08-09 (the previous "MIT" label on
// the wav2vec2 row was wrong — the Hub reports apache-2.0).
import React from 'react';

/** One selectable alignment model. `id` is the `ctcModelId` value ('' = default). */
export interface AlignModelChoice {
  id: string;
  label: string;
  /** True when picking it requires the non-commercial opt-in (CC-BY-NC weights). */
  nonCommercial?: boolean;
}

/** The `ctcModelId` alias for the CC-BY-NC MMS aligner (sidecar `_MODEL_ALIASES`). */
export const MMS_ALIGNER_ALIAS = 'mms-300m';
/** Its full HF id — a hand-typed `ctcModelId` can carry this instead of the alias. */
export const MMS_ALIGNER_MODEL_ID = 'MahmoudAshraf/mms-300m-1130-forced-aligner';

/** The permissive default + the opt-ins (aliases the sidecar resolves). */
export const ALIGN_MODEL_CHOICES: AlignModelChoice[] = [
  { id: '', label: 'English wav2vec2 — default (Apache-2.0, commercial-safe)' },
  { id: 'romanian-wav2vec2', label: 'Romanian — gigant/romanian-wav2vec2 (Apache-2.0)' },
  { id: 'wav2vec2-960h-lv60', label: 'English wav2vec2 lv60-self (Apache-2.0)' },
  { id: 'hubert-large', label: 'English HuBERT-Large (Apache-2.0)' },
  {
    id: MMS_ALIGNER_ALIAS,
    label: 'MMS-300M — 158 languages (CC-BY-NC-4.0, non-commercial)',
    nonCommercial: true,
  },
];

export interface AlignModelSelectProps {
  /** Current persisted `ctcModelId` ('' / undefined = the packaged default). */
  value: string;
  /** Persist the chosen alignment model id (the parent writes `ctcModelId`). */
  onChange: (ctcModelId: string) => void;
  /** Current persisted `allowNonCommercialAligner`. */
  allowNonCommercial: boolean;
  /** Persist the opt-in (the parent writes `allowNonCommercialAligner`). */
  onAllowNonCommercialChange: (allow: boolean) => void;
  /** Disable the control while a write is in flight. */
  busy?: boolean;
}

export function AlignModelSelect({
  value,
  onChange,
  allowNonCommercial,
  onAllowNonCommercialChange,
  busy,
}: AlignModelSelectProps): React.ReactElement {
  // An unknown persisted id (e.g. a hand-typed full HF id) shows as the default
  // row visually but is NOT lost — we only overwrite it when the user picks a row.
  const known = ALIGN_MODEL_CHOICES.some((c) => c.id === value);
  const disabled = Boolean(busy);
  const mmsSelected = value === MMS_ALIGNER_ALIAS || value === MMS_ALIGNER_MODEL_ID;

  function handleAllowChange(next: boolean): void {
    onAllowNonCommercialChange(next);
    // Withdrawing the opt-in must also drop an MMS selection: the sidecar would
    // refuse it and silently align with the permissive default, so leaving it
    // persisted would leave the UI stating something untrue about the next job.
    if (!next && mmsSelected) onChange('');
  }

  return (
    <div className="align-model" data-section="align-model">
      <label htmlFor="align-model-select">Word-timing alignment model</label>
      <select
        id="align-model-select"
        data-action="align-model"
        value={known ? value : ''}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {ALIGN_MODEL_CHOICES.map((choice) => (
          <option
            key={choice.id || 'default'}
            value={choice.id}
            disabled={Boolean(choice.nonCommercial) && !allowNonCommercial}
          >
            {choice.label}
          </option>
        ))}
      </select>
      {!known && value && (
        <span className="align-model__custom" data-testid="align-model-custom">
          custom: {value}
        </span>
      )}
      <label className="align-model__nc" htmlFor="align-model-allow-nc">
        <input
          id="align-model-allow-nc"
          type="checkbox"
          data-action="allow-non-commercial-aligner"
          checked={allowNonCommercial}
          disabled={disabled}
          onChange={(e) => handleAllowChange(e.target.checked)}
        />
        <span>
          Allow non-commercial alignment models (CC-BY-NC-4.0). Off by default. Turning this on
          unlocks MMS-300M and its 158 languages, and makes anything you align with it
          non-commercial.
        </span>
      </label>
    </div>
  );
}

export default AlignModelSelect;
