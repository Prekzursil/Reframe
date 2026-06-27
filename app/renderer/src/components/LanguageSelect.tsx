// LanguageSelect.tsx — the ONE reusable language dropdown (V1 IA §h).
//
// LANGUAGE is always a dropdown (never free-typed) so a user can't pick a
// wrong/nonexistent code. Auto-detect is offered as the first option, but when
// it is selected we surface a quality-advice note recommending an explicit
// language (auto-detect can transcribe/translate at lower quality). The curated
// vocabulary + labels come from lib/languages.ts (single source of truth).
import React, { useId } from 'react';
import { AUTO_DETECT, LANGUAGES, languageLabel } from '../lib/languages';
import './languageSelect.css';

export interface LanguageSelectProps {
  /** The selected code: a language code, or the AUTO_DETECT sentinel. */
  value: string;
  /** Called with the chosen code on change. */
  onChange: (code: string) => void;
  /** DOM id for label association (defaults to a generated id). */
  id?: string;
  /** Accessible label / visible caption (defaults to "Language"). */
  label?: string;
  /** Offer the Auto-detect option (defaults to true). */
  includeAuto?: boolean;
}

/** A dropdown over the curated language list, with optional auto-detect advice. */
export function LanguageSelect({
  value,
  onChange,
  id,
  label = 'Language',
  includeAuto = true,
}: LanguageSelectProps): React.ReactElement {
  const generated = useId();
  const selectId = id ?? generated;
  // The value is selectable even if it is not in the curated list (e.g. a code
  // persisted by an older build) — add a fallback option so the <select> never
  // silently drops the current choice.
  const known = value === AUTO_DETECT || LANGUAGES.some((l) => l.code === value);
  const showAdvice = includeAuto && value === AUTO_DETECT;
  return (
    <div className="lang-select">
      <select
        id={selectId}
        aria-label={label}
        className="lang-select__control"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {includeAuto ? <option value={AUTO_DETECT}>{languageLabel(AUTO_DETECT)}</option> : null}
        {known ? null : <option value={value}>{value}</option>}
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
      {showAdvice ? (
        <p className="lang-select__advice" role="note">
          Auto-detect may produce lower-quality captions — pick the spoken language for the best
          result.
        </p>
      ) : null}
    </div>
  );
}

export default LanguageSelect;
