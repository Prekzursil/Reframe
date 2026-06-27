// captionPreferences.ts — persisted caption + output DEFAULTS (P4 §4 Preferences).
//
// The Preferences/Settings area lets a user set the defaults every new short
// starts from: the caption style + on-frame position, the subtitle delivery
// mode, and the default language. They are stored in the free-form settings
// store (C12: settings.get/set, like the brand kit) under four FROZEN keys, so
// the Make Shorts flow + the Output Tray seed from one place instead of every
// surface re-choosing. Pure read/write helpers only — unit-tested.

import { type CaptionDesign, DEFAULT_CAPTION_DESIGN, sanitizeCaptionDesign } from './captionDesign';
import { type SubtitleMode, DEFAULT_OUTPUT_OPTIONS, coerceSubtitleMode } from './outputOptions';
import { LANGUAGES } from './languages';

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
}

/** The out-of-box defaults (used before anything is persisted). */
export const DEFAULT_PREFERENCES: CaptionPreferences = {
  design: DEFAULT_CAPTION_DESIGN,
  subtitleMode: DEFAULT_OUTPUT_OPTIONS.subtitleMode,
  language: DEFAULT_LANGUAGE,
};

/** The four FROZEN settings-store keys these preferences live under. */
export const PREFERENCE_KEYS = {
  style: 'defaultCaptionStyle',
  box: 'defaultCaptionBox',
  subtitleMode: 'defaultSubtitleMode',
  language: 'defaultLanguage',
} as const;

/** A known language code, or the default (dropdown-only — never a free-typed id). */
export function coerceLanguage(raw: unknown): string {
  const v = typeof raw === 'string' ? raw.trim() : '';
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
  };
}

/** The `settings.set` patch for the preferences (only the four FROZEN keys). */
export function preferencesPatch(prefs: CaptionPreferences): Record<string, unknown> {
  return {
    [PREFERENCE_KEYS.style]: prefs.design.style,
    [PREFERENCE_KEYS.box]: prefs.design.box,
    [PREFERENCE_KEYS.subtitleMode]: prefs.subtitleMode,
    [PREFERENCE_KEYS.language]: prefs.language,
  };
}
