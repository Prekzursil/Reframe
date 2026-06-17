// ConsentToggle.tsx — per-data-type consent (TEXT vs FRAMES) for one provider.
//
// WU-keys / SE1 (PLAN §WU-keys): sending TEXT (transcripts) and FRAMES (vision)
// are SEPARATE, independently-revocable opt-ins. This component renders two
// distinct toggles plus the provider's train-on-input disclosure so the user
// sees the privacy posture BEFORE granting consent. Each toggle calls onChange
// with the data type and the new boolean; the panel forwards to
// providers.setConsent (which changes only the toggled type, leaving the other
// intact). Pure presentational — no rpc, no state.
import React from 'react';

/** The two egress data types consent is tracked for, independently. */
export type ConsentType = 'text' | 'frames';

export interface ConsentToggleProps {
  /** The provider these toggles govern. */
  providerId: string;
  /** Current TEXT-egress consent (transcripts). */
  text: boolean;
  /** Current FRAMES-egress consent (vision). */
  frames: boolean;
  /**
   * The provider's train-on-input disclosure shown before first use:
   * true / false / "conditional" (trains unless an opt-out is flipped).
   */
  trainsOnInput: boolean | 'conditional';
  /** Toggle one data type's consent (provider id + type + the new value). */
  onChange: (providerId: string, type: ConsentType, value: boolean) => void;
}

/** Human-readable train-on-input disclosure for the warning line. */
export function disclosureText(trainsOnInput: boolean | 'conditional'): string {
  if (trainsOnInput === true) {
    return 'This provider trains on your input — avoid sending private or PII data.';
  }
  if (trainsOnInput === 'conditional') {
    return 'This provider may train on your input unless you flip its opt-out/ZDR setting first.';
  }
  return 'This provider does not train on your input (no-retention).';
}

export function ConsentToggle({
  providerId,
  text,
  frames,
  trainsOnInput,
  onChange,
}: ConsentToggleProps): React.ReactElement {
  return (
    <fieldset className="consent-toggle" data-provider={providerId}>
      <legend className="consent-toggle__legend">Data sharing consent</legend>
      <p
        className="consent-toggle__disclosure"
        data-trains={String(trainsOnInput)}
        role="note"
      >
        {disclosureText(trainsOnInput)}
      </p>
      <label className="consent-toggle__option" data-consent="text">
        <input
          type="checkbox"
          aria-label={`Allow sending transcript text to ${providerId}`}
          checked={text}
          onChange={(e) => onChange(providerId, 'text', e.target.checked)}
        />
        <span>Send transcript text</span>
      </label>
      <label className="consent-toggle__option" data-consent="frames">
        <input
          type="checkbox"
          aria-label={`Allow sending video frames to ${providerId}`}
          checked={frames}
          onChange={(e) => onChange(providerId, 'frames', e.target.checked)}
        />
        <span>Send video frames (vision)</span>
      </label>
    </fieldset>
  );
}

export default ConsentToggle;
