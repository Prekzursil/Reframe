// captionPreferences.ts — persisted caption + output DEFAULTS (P4 §4 Preferences).
//
// The Preferences/Settings area lets a user set two DIFFERENT-SCOPED groups of
// defaults, stored together in the free-form settings store (C12:
// settings.get/set, like the brand kit) under FROZEN keys so no surface
// re-chooses them. Pure read/write helpers only — unit-tested.
//
//  1. Seeds every NEW SHORT (read by the Make Shorts flow + the Output Tray):
//     the caption style + on-frame position, the subtitle delivery mode, and the
//     default language.
//  2. Applies to GENERATED CAPTIONS only (read by the sidecar's
//     subtitles.generate, i.e. the Caption / Subtitles / Recipes surfaces —
//     NOT the shorts export): the two caption-quality toggles, transcript
//     polish + speaker labels.
//
// Do not describe group 2 as seeding shorts: the shorts export path never reads
// those two keys, so a panel-wide "seeds every new short" promise is false for
// them (see CaptionPreferences.tsx, which discloses the split in the UI).
//
// CONTRACT-NOTE: `captionPolish` + `captionSpeakerLabels` are the EXACT keys the
// sidecar reads in handlers/media_ops.py subtitles_generate (settings.get). This
// panel is the writer half of that contract — without it those backend gates are
// unreachable dead config. Keep the key strings byte-identical to the sidecar.

import { type CaptionDesign, DEFAULT_CAPTION_DESIGN, sanitizeCaptionDesign } from './captionDesign';
import { type SubtitleMode, DEFAULT_OUTPUT_OPTIONS, coerceSubtitleMode } from './outputOptions';
import { AUTO_DETECT, LANGUAGES, normalizeCode } from './languages';

/** The default language id when none is persisted (most common creator lang). */
export const DEFAULT_LANGUAGE = 'en';

/** The persisted caption + output defaults. */
export interface CaptionPreferences {
  /** Default caption style + position. */
  design: CaptionDesign;
  /** Default subtitle delivery mode. */
  subtitleMode: SubtitleMode;
  /** Default language code (an ISO code from lib/languages). */
  language: string;
  /**
   * Run the Netflix CPS/CPL + punctuation/casing/emphasis polish over generated
   * cues (sidecar `captionPolish` gate). Off by default — the plain generate.
   */
  captionPolish: boolean;
  /**
   * Prefix each diarized cue with its speaker label (sidecar
   * `captionSpeakerLabels` gate). Off by default; a no-op on non-diarized cues.
   */
  captionSpeakerLabels: boolean;
}

/** The out-of-box defaults (used before anything is persisted). */
export const DEFAULT_PREFERENCES: CaptionPreferences = {
  design: DEFAULT_CAPTION_DESIGN,
  subtitleMode: DEFAULT_OUTPUT_OPTIONS.subtitleMode,
  language: DEFAULT_LANGUAGE,
  captionPolish: false,
  captionSpeakerLabels: false,
};

/** The FROZEN settings-store keys these preferences live under. */
export const PREFERENCE_KEYS = {
  style: 'defaultCaptionStyle',
  box: 'defaultCaptionBox',
  subtitleMode: 'defaultSubtitleMode',
  language: 'defaultLanguage',
  // These two MUST match the sidecar's settings.get() keys byte-for-byte.
  captionPolish: 'captionPolish',
  captionSpeakerLabels: 'captionSpeakerLabels',
} as const;

/**
 * A known language code, the auto-detect sentinel, or the default (dropdown-only —
 * never a free-typed id).
 *
 * AUTO_DETECT is accepted deliberately. The default caption language is a
 * transcription SOURCE hint, where "let the model detect it" is a meaningful
 * choice — but `LANGUAGES` excludes the sentinel, so this used to rewrite `'auto'`
 * to English on save. Offering the option in the dropdown WITHOUT this would have
 * shipped a control that appears to work and does not (audit §2.1): fix both or
 * neither.
 *
 * The value is also NORMALIZED rather than exact-matched, so a region-tagged code
 * (`pt-BR`) resolves to `pt` instead of silently falling back to English.
 */
export function coerceLanguage(raw: unknown): string {
  const v = normalizeCode(raw);
  if (v === AUTO_DETECT) return AUTO_DETECT;
  return LANGUAGES.some((l) => l.code === v) ? v : DEFAULT_LANGUAGE;
}

/**
 * Read preferences out of a raw `settings.get` result, tolerating absent keys
 * (the keys may not be in DEFAULT_SETTINGS yet). A non-object input yields the
 * out-of-box defaults; each field is independently validated.
 */
export function readPreferences(raw: unknown): CaptionPreferences {
  if (!raw || typeof raw !== 'object') return DEFAULT_PREFERENCES;
  const r = raw as Record<string, unknown>;
  return {
    design: sanitizeCaptionDesign({
      style: r[PREFERENCE_KEYS.style] as string | undefined,
      box: r[PREFERENCE_KEYS.box] as CaptionDesign['box'] | undefined,
    }),
    subtitleMode: coerceSubtitleMode(r[PREFERENCE_KEYS.subtitleMode]),
    language: coerceLanguage(r[PREFERENCE_KEYS.language]),
    // Strict boolean coercion — any non-`true` persisted value reads as off.
    captionPolish: r[PREFERENCE_KEYS.captionPolish] === true,
    captionSpeakerLabels: r[PREFERENCE_KEYS.captionSpeakerLabels] === true,
  };
}

/** The `settings.set` patch for the preferences (only the FROZEN keys). */
export function preferencesPatch(prefs: CaptionPreferences): Record<string, unknown> {
  return {
    [PREFERENCE_KEYS.style]: prefs.design.style,
    [PREFERENCE_KEYS.box]: prefs.design.box,
    [PREFERENCE_KEYS.subtitleMode]: prefs.subtitleMode,
    [PREFERENCE_KEYS.language]: prefs.language,
    [PREFERENCE_KEYS.captionPolish]: prefs.captionPolish,
    [PREFERENCE_KEYS.captionSpeakerLabels]: prefs.captionSpeakerLabels,
  };
}
