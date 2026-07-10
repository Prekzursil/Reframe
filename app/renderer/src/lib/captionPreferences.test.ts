import { describe, expect, it } from 'vitest';
import {
  DEFAULT_LANGUAGE,
  DEFAULT_PREFERENCES,
  PREFERENCE_KEYS,
  coerceLanguage,
  preferencesPatch,
  readPreferences,
} from './captionPreferences';
import { DEFAULT_CAPTION_DESIGN } from './captionDesign';

describe('coerceLanguage', () => {
  it('accepts a known code', () => {
    expect(coerceLanguage('es')).toBe('es');
  });
  it('falls back for unknown / non-string', () => {
    expect(coerceLanguage('zz')).toBe(DEFAULT_LANGUAGE);
    expect(coerceLanguage(5)).toBe(DEFAULT_LANGUAGE);
  });
});

describe('readPreferences', () => {
  it('returns defaults for a non-object', () => {
    expect(readPreferences(null)).toEqual(DEFAULT_PREFERENCES);
    expect(readPreferences('x')).toEqual(DEFAULT_PREFERENCES);
  });

  it('reads each persisted field', () => {
    const prefs = readPreferences({
      [PREFERENCE_KEYS.style]: 'karaoke',
      [PREFERENCE_KEYS.box]: { x: 0.1, y: 0.2, w: 0.5, h: 0.2 },
      [PREFERENCE_KEYS.subtitleMode]: 'sidecar',
      [PREFERENCE_KEYS.language]: 'pt',
      [PREFERENCE_KEYS.captionPolish]: true,
      [PREFERENCE_KEYS.captionSpeakerLabels]: true,
    });
    expect(prefs).toEqual({
      design: { style: 'karaoke', box: { x: 0.1, y: 0.2, w: 0.5, h: 0.2 } },
      subtitleMode: 'sidecar',
      language: 'pt',
      captionPolish: true,
      captionSpeakerLabels: true,
    });
  });

  it('validates/falls back per field for partial data', () => {
    const prefs = readPreferences({ [PREFERENCE_KEYS.style]: 'bogus' });
    expect(prefs.design).toEqual(DEFAULT_CAPTION_DESIGN);
    expect(prefs.subtitleMode).toBe('burn');
    expect(prefs.language).toBe(DEFAULT_LANGUAGE);
    // The two quality toggles default OFF when absent (back-compat).
    expect(prefs.captionPolish).toBe(false);
    expect(prefs.captionSpeakerLabels).toBe(false);
  });

  it('coerces non-boolean toggle values to false (strict === true)', () => {
    const prefs = readPreferences({
      [PREFERENCE_KEYS.captionPolish]: 'true',
      [PREFERENCE_KEYS.captionSpeakerLabels]: 1,
    });
    expect(prefs.captionPolish).toBe(false);
    expect(prefs.captionSpeakerLabels).toBe(false);
  });
});

describe('preferencesPatch', () => {
  it('round-trips through readPreferences', () => {
    const prefs = {
      design: { style: 'neon', box: { x: 0.2, y: 0.7, w: 0.6, h: 0.15 } },
      subtitleMode: 'softmux' as const,
      language: 'fr',
      captionPolish: true,
      captionSpeakerLabels: false,
    };
    expect(readPreferences(preferencesPatch(prefs))).toEqual(prefs);
  });
});
