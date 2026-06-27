// languages.ts — the curated language vocabulary for the V1 IA.
//
// V1 IA decision (V1-GRILL-DECISIONS §h): LANGUAGE is a DROPDOWN, never
// free-typed — typing invites wrong/nonexistent language codes. Auto-detect is
// also offered, but the UI advises picking a specific language upfront because
// auto-detect can yield lower-quality transcription/translation than an explicit
// choice. This module is the SINGLE source of truth for the option list + labels
// so every surface (ShortMaker controls, the Output Tray, captions) reads one
// vocabulary.

/** A selectable language: an ISO-639-1 code + a human label. */
export interface LanguageOption {
  code: string;
  label: string;
}

/** The sentinel "let the model detect the language" choice (not a real code). */
export const AUTO_DETECT = 'auto';

/**
 * The curated set of languages offered in dropdowns (the auto sentinel is NOT
 * included here — surfaces prepend it when they offer auto-detect). Ordered with
 * the most common creator languages first.
 */
export const LANGUAGES: readonly LanguageOption[] = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'it', label: 'Italian' },
  { code: 'nl', label: 'Dutch' },
  { code: 'pl', label: 'Polish' },
  { code: 'ru', label: 'Russian' },
  { code: 'uk', label: 'Ukrainian' },
  { code: 'tr', label: 'Turkish' },
  { code: 'ar', label: 'Arabic' },
  { code: 'hi', label: 'Hindi' },
  { code: 'id', label: 'Indonesian' },
  { code: 'vi', label: 'Vietnamese' },
  { code: 'th', label: 'Thai' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'zh', label: 'Chinese' },
] as const;

/** Map a code to its label, including the auto sentinel; unknown codes echo back. */
export function languageLabel(code: string): string {
  if (code === AUTO_DETECT) return 'Auto-detect';
  return LANGUAGES.find((l) => l.code === code)?.label ?? code;
}
