// LanguageSelect.tsx — the ONE reusable language dropdown (V1 IA §h).
//
// LANGUAGE is always a dropdown (never free-typed) so a user can't pick a
// wrong/nonexistent code. Auto-detect is offered as the first option, but when
// it is selected we surface a quality-advice note recommending an explicit
// language (auto-detect can transcribe/translate at lower quality). The
// vocabulary + labels come from lib/languages.ts (single source of truth, mirrored
// in the sidecar and pinned by languages.conformance.test.ts).
//
// v1.5: the list is now the full 102-language engine-derived inventory instead of
// 19 hand-picked codes. Two things follow from that size:
//
//   * The curated creator head (COMMON_CODES) goes in its own <optgroup> so the
//     common choices stay one glance away. A native <select> is kept deliberately:
//     it gives type-to-jump, keyboard and screen-reader behaviour for free, and it
//     cannot accept an unlisted value — which is the V1-GRILL §h guarantee. A
//     filtering combobox would be nicer to scan but has to re-implement all of
//     that by hand, so it is a separate, later change.
//   * Support is NOT uniform across 102 languages, so a picked language may carry
//     a caveat (no ASR engine covers it; the CHOSEN engine does not; translation
//     needs the hosted provider or the slow local model). `capabilityNote` renders
//     that inline rather than letting the job fail later with no warning.
import React, { useId } from 'react';
import {
  AUTO_DETECT,
  COMMON_CODES,
  LANGUAGES,
  capabilityNote,
  languageLabel,
} from '../lib/languages';
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
  /** Lock the control (callers disable it while a job is in flight). */
  disabled?: boolean;
  /**
   * The current `asrEngine` setting, when the caller has it. Supplying it turns on
   * the engine-specific half of the capability warning ("Parakeet cannot
   * transcribe Japanese — switch to Whisper"); omitting it leaves the
   * engine-independent caveats, which still fire.
   */
  engine?: string;
}

// Static partition of the inventory, rendered ONCE at module scope.
//
// These are the <option> ELEMENTS, not just the data: the list is 102 entries and
// this component appears on several surfaces, so building them per render made a
// measurable difference. Measured on renderer/src/App.director-state.test.tsx under
// v8 coverage (the heaviest mount in the suite, and already close to the 5s default
// timeout on main): 19 entries 3529ms -> 102 entries 7763ms, recovered by hoisting.
// React elements are immutable and safe to share, and the option lists never depend
// on props, so the reconciler can bail out on these subtrees instead of
// re-allocating ~250 nodes on every keystroke elsewhere in the form.
const COMMON_SET: ReadonlySet<string> = new Set(COMMON_CODES);

function optionsFor(predicate: (code: string) => boolean): React.ReactElement[] {
  return LANGUAGES.filter((l) => predicate(l.code)).map((l) => (
    <option key={l.code} value={l.code}>
      {l.label}
    </option>
  ));
}

const COMMON_OPTION_ELEMENTS = optionsFor((code) => COMMON_SET.has(code));
const OTHER_OPTION_ELEMENTS = optionsFor((code) => !COMMON_SET.has(code));

/** A dropdown over the full language inventory, with auto-detect + capability advice. */
export function LanguageSelect({
  value,
  onChange,
  id,
  label = 'Language',
  includeAuto = true,
  disabled = false,
  engine,
}: LanguageSelectProps): React.ReactElement {
  const generated = useId();
  const selectId = id ?? generated;
  // The value is selectable even if it is not in the inventory (e.g. a code
  // persisted by an older build) — add a fallback option so the <select> never
  // silently drops the current choice.
  //
  // The sentinel counts as "known" ONLY when the auto option is actually rendered.
  // Otherwise a target-language picker (includeAuto={false}) seeded with 'auto'
  // would have no matching option, and a <select> in that state silently displays
  // its FIRST option — reading "English" while its value, and the wire value, is
  // 'auto'. A control that lies about its own state is the worse failure.
  const known = value === AUTO_DETECT ? includeAuto : LANGUAGES.some((l) => l.code === value);
  const showAdvice = includeAuto && value === AUTO_DETECT;
  const caveat = capabilityNote(value, engine);
  return (
    <div className="lang-select">
      <select
        id={selectId}
        aria-label={label}
        className="lang-select__control"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {includeAuto ? <option value={AUTO_DETECT}>{languageLabel(AUTO_DETECT)}</option> : null}
        {known ? null : <option value={value}>{languageLabel(value)}</option>}
        <optgroup label="Common">{COMMON_OPTION_ELEMENTS}</optgroup>
        <optgroup label="All languages">{OTHER_OPTION_ELEMENTS}</optgroup>
      </select>
      {showAdvice ? (
        <p className="lang-select__advice" role="note">
          Auto-detect may produce lower-quality captions — pick the spoken language for the best
          result.
        </p>
      ) : null}
      {caveat === null ? null : (
        <p className="lang-select__capability" role="note">
          {caveat}
        </p>
      )}
    </div>
  );
}

export default LanguageSelect;
