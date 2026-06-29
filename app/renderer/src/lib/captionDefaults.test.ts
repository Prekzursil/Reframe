import { describe, expect, it } from 'vitest';
import {
  MAX_CPL,
  MAX_CPS,
  MAX_CPS_CHILDREN,
  MAX_CPS_ENGLISH,
  MAX_LINES,
  type CaptionContentContext,
  defaultMaxCps,
  isEnglishLanguage,
  resolveMaxCps,
  resolveMaxLines,
  resolveReadability,
} from './captionDefaults';
import { MAX_CPS_MAX, MAX_CPS_MIN } from './captionOverride';

describe('Netflix readability constants', () => {
  it('mirror the sidecar caption_polish values exactly (single source of truth)', () => {
    // These MUST equal the sidecar MAX_CPS / MAX_CPS_ENGLISH / MAX_CPS_CHILDREN /
    // MAX_CPL / MAX_LINES so the preview shows what burns (§1.5).
    expect(MAX_CPS).toBe(17);
    expect(MAX_CPS_ENGLISH).toBe(20);
    expect(MAX_CPS_CHILDREN).toBe(13);
    expect(MAX_CPL).toBe(42);
    expect(MAX_LINES).toBe(2);
  });
});

describe('isEnglishLanguage', () => {
  it('is true for English BCP-47 / ISO codes (case + whitespace tolerant)', () => {
    expect(isEnglishLanguage('en')).toBe(true);
    expect(isEnglishLanguage('en-US')).toBe(true);
    expect(isEnglishLanguage('  EN  ')).toBe(true);
    expect(isEnglishLanguage('eng')).toBe(true);
  });

  it('is false for non-English and non-string inputs', () => {
    expect(isEnglishLanguage('ro')).toBe(false);
    expect(isEnglishLanguage('fr-FR')).toBe(false);
    expect(isEnglishLanguage('')).toBe(false);
    expect(isEnglishLanguage(undefined)).toBe(false);
  });
});

describe('defaultMaxCps — per-language / per-content novice default (§1.5)', () => {
  it.each<{ name: string; content: CaptionContentContext | undefined; expected: number }>([
    { name: 'no context => conservative cross-language 17', content: undefined, expected: MAX_CPS },
    { name: 'empty context => cross-language 17', content: {}, expected: MAX_CPS },
    { name: 'non-English language => 17', content: { language: 'ro' }, expected: MAX_CPS },
    { name: 'English language => 20', content: { language: 'en' }, expected: MAX_CPS_ENGLISH },
    { name: 'English regional => 20', content: { language: 'en-GB' }, expected: MAX_CPS_ENGLISH },
    {
      name: "children's content => 13 (wins over language)",
      content: { children: true, language: 'en' },
      expected: MAX_CPS_CHILDREN,
    },
    {
      name: 'children flag false => language path',
      content: { children: false, language: 'en' },
      expected: MAX_CPS_ENGLISH,
    },
  ])('$name', ({ content, expected }) => {
    expect(defaultMaxCps(content)).toBe(expected);
  });
});

describe('resolveMaxCps — explicit override wins (clamped 10..30), else the default', () => {
  it('uses the per-language default when the override sets no maxCps', () => {
    expect(resolveMaxCps(undefined, { language: 'en' })).toBe(MAX_CPS_ENGLISH);
    expect(resolveMaxCps({}, { language: 'ro' })).toBe(MAX_CPS);
    expect(resolveMaxCps({ textColor: '#FFFFFF' }, { children: true })).toBe(MAX_CPS_CHILDREN);
  });

  it('honours an explicit in-range maxCps over the default', () => {
    expect(resolveMaxCps({ maxCps: 24 }, { language: 'en' })).toBe(24);
  });

  it('clamps an explicit maxCps into the 10..30 window (both edges)', () => {
    expect(resolveMaxCps({ maxCps: 5 }, { language: 'en' })).toBe(MAX_CPS_MIN);
    expect(resolveMaxCps({ maxCps: 99 }, { language: 'ro' })).toBe(MAX_CPS_MAX);
    expect(resolveMaxCps({ maxCps: MAX_CPS_MIN })).toBe(MAX_CPS_MIN);
    expect(resolveMaxCps({ maxCps: MAX_CPS_MAX })).toBe(MAX_CPS_MAX);
  });

  it('falls back to the default for a non-finite maxCps', () => {
    expect(resolveMaxCps({ maxCps: Number.NaN }, { language: 'en' })).toBe(MAX_CPS_ENGLISH);
    expect(resolveMaxCps({ maxCps: Number.POSITIVE_INFINITY })).toBe(MAX_CPS);
  });
});

describe('resolveMaxLines — explicit 1/2 wins, else the 2-line default', () => {
  it('returns the override line count when it is 1 or 2', () => {
    expect(resolveMaxLines({ maxLines: 1 })).toBe(1);
    expect(resolveMaxLines({ maxLines: 2 })).toBe(2);
  });

  it('defaults to MAX_LINES when unset', () => {
    expect(resolveMaxLines(undefined)).toBe(MAX_LINES);
    expect(resolveMaxLines({})).toBe(MAX_LINES);
  });
});

describe('resolveReadability — the full novice readability bundle (preview parity)', () => {
  it('bundles the resolved cps + line count + the fixed CPL ceiling', () => {
    expect(resolveReadability(undefined, { language: 'en' })).toEqual({
      maxCps: MAX_CPS_ENGLISH,
      maxLines: MAX_LINES,
      maxCpl: MAX_CPL,
    });
    expect(resolveReadability({ maxCps: 12, maxLines: 1 }, { children: true })).toEqual({
      maxCps: 12,
      maxLines: 1,
      maxCpl: MAX_CPL,
    });
  });
});
