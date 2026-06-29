import { describe, expect, it } from 'vitest';
import {
  CURATED_CAPTION_FONTS,
  MAX_CPS_MAX,
  MAX_CPS_MIN,
  SIZE_SCALE_MAX,
  SIZE_SCALE_MIN,
  type CaptionOverride,
  sanitizeCaptionOverride,
} from './captionOverride';

describe('CURATED_CAPTION_FONTS', () => {
  it('is a non-empty allowlist that includes the guaranteed libass fallback', () => {
    expect(CURATED_CAPTION_FONTS.length).toBeGreaterThan(0);
    // DejaVu Sans is libass's always-present fallback — it must be selectable.
    expect(CURATED_CAPTION_FONTS).toContain('DejaVu Sans');
  });

  it('has no duplicate entries', () => {
    expect(new Set(CURATED_CAPTION_FONTS).size).toBe(CURATED_CAPTION_FONTS.length);
  });
});

describe('sanitizeCaptionOverride — empty / absent', () => {
  it('returns undefined for null / undefined (back-compat: no override)', () => {
    expect(sanitizeCaptionOverride(null)).toBeUndefined();
    expect(sanitizeCaptionOverride(undefined)).toBeUndefined();
  });

  it('returns undefined for an empty object (nothing to patch)', () => {
    expect(sanitizeCaptionOverride({})).toBeUndefined();
  });

  it('returns undefined when every field is invalid (field-by-field drop to empty)', () => {
    const raw = {
      fontFamily: 'Comic Sans MS',
      sizeScale: Number.NaN,
      textColor: 'red',
      activeColor: '#FFF',
      spokenColor: 123 as unknown as string,
      outline: 'yes' as unknown as boolean,
      box: 1 as unknown as boolean,
      uppercase: null as unknown as boolean,
      positionBand: 'middle' as unknown as CaptionOverride['positionBand'],
      maxLines: 3 as unknown as CaptionOverride['maxLines'],
      maxCps: Number.POSITIVE_INFINITY,
    };
    expect(sanitizeCaptionOverride(raw)).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — fontFamily allowlist', () => {
  it('keeps a font that is in the curated allowlist (after trimming)', () => {
    expect(sanitizeCaptionOverride({ fontFamily: '  Montserrat  ' })).toEqual({
      fontFamily: 'Montserrat',
    });
  });

  it('drops a font that is not in the allowlist', () => {
    expect(sanitizeCaptionOverride({ fontFamily: 'Comic Sans MS' })).toBeUndefined();
  });

  it('drops a non-string fontFamily', () => {
    expect(sanitizeCaptionOverride({ fontFamily: 42 as unknown as string })).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — sizeScale clamp', () => {
  it('keeps an in-range scale verbatim', () => {
    expect(sanitizeCaptionOverride({ sizeScale: 1.25 })).toEqual({ sizeScale: 1.25 });
  });

  it('clamps below the floor up to SIZE_SCALE_MIN', () => {
    expect(sanitizeCaptionOverride({ sizeScale: 0.1 })).toEqual({ sizeScale: SIZE_SCALE_MIN });
  });

  it('clamps above the ceiling down to SIZE_SCALE_MAX', () => {
    expect(sanitizeCaptionOverride({ sizeScale: 9 })).toEqual({ sizeScale: SIZE_SCALE_MAX });
  });

  it('keeps the exact boundary values', () => {
    expect(sanitizeCaptionOverride({ sizeScale: SIZE_SCALE_MIN })).toEqual({
      sizeScale: SIZE_SCALE_MIN,
    });
    expect(sanitizeCaptionOverride({ sizeScale: SIZE_SCALE_MAX })).toEqual({
      sizeScale: SIZE_SCALE_MAX,
    });
  });

  it('drops a non-finite / non-number scale', () => {
    expect(sanitizeCaptionOverride({ sizeScale: Number.NaN })).toBeUndefined();
    expect(sanitizeCaptionOverride({ sizeScale: '1.2' as unknown as number })).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — colours (#RRGGBB)', () => {
  it('keeps valid hex colours, normalised to uppercase', () => {
    expect(
      sanitizeCaptionOverride({
        textColor: '#ff0000',
        activeColor: '  #00FF00  ',
        spokenColor: '#AbCdEf',
      }),
    ).toEqual({ textColor: '#FF0000', activeColor: '#00FF00', spokenColor: '#ABCDEF' });
  });

  it('drops 3-digit shorthand and bad/non-string hex', () => {
    expect(sanitizeCaptionOverride({ textColor: '#FFF' })).toBeUndefined();
    expect(sanitizeCaptionOverride({ textColor: 'red' })).toBeUndefined();
    expect(sanitizeCaptionOverride({ textColor: 'FF0000' })).toBeUndefined();
    expect(sanitizeCaptionOverride({ textColor: '#GG0000' })).toBeUndefined();
    expect(sanitizeCaptionOverride({ textColor: 0xff0000 as unknown as string })).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — booleans', () => {
  it('keeps genuine booleans (true and false)', () => {
    expect(sanitizeCaptionOverride({ outline: true, box: false, uppercase: true })).toEqual({
      outline: true,
      box: false,
      uppercase: true,
    });
  });

  it('drops non-boolean toggle values', () => {
    expect(
      sanitizeCaptionOverride({
        outline: 'yes' as unknown as boolean,
        box: 1 as unknown as boolean,
        uppercase: null as unknown as boolean,
      }),
    ).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — positionBand', () => {
  it('keeps each valid band', () => {
    expect(sanitizeCaptionOverride({ positionBand: 'top' })).toEqual({ positionBand: 'top' });
    expect(sanitizeCaptionOverride({ positionBand: 'center' })).toEqual({
      positionBand: 'center',
    });
    expect(sanitizeCaptionOverride({ positionBand: 'bottom' })).toEqual({
      positionBand: 'bottom',
    });
  });

  it('drops an invalid string band', () => {
    expect(
      sanitizeCaptionOverride({
        positionBand: 'middle' as unknown as CaptionOverride['positionBand'],
      }),
    ).toBeUndefined();
  });

  it('drops a non-string band', () => {
    expect(
      sanitizeCaptionOverride({
        positionBand: 7 as unknown as CaptionOverride['positionBand'],
      }),
    ).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — maxLines', () => {
  it('keeps 1 and 2', () => {
    expect(sanitizeCaptionOverride({ maxLines: 1 })).toEqual({ maxLines: 1 });
    expect(sanitizeCaptionOverride({ maxLines: 2 })).toEqual({ maxLines: 2 });
  });

  it('drops any other line count', () => {
    expect(
      sanitizeCaptionOverride({ maxLines: 3 as unknown as CaptionOverride['maxLines'] }),
    ).toBeUndefined();
    expect(
      sanitizeCaptionOverride({ maxLines: 0 as unknown as CaptionOverride['maxLines'] }),
    ).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — maxCps clamp', () => {
  it('keeps an in-range reading-speed cap', () => {
    expect(sanitizeCaptionOverride({ maxCps: 17 })).toEqual({ maxCps: 17 });
  });

  it('clamps to the [MIN, MAX] reading-speed window', () => {
    expect(sanitizeCaptionOverride({ maxCps: 5 })).toEqual({ maxCps: MAX_CPS_MIN });
    expect(sanitizeCaptionOverride({ maxCps: 99 })).toEqual({ maxCps: MAX_CPS_MAX });
  });

  it('drops a non-finite / non-number cap', () => {
    expect(sanitizeCaptionOverride({ maxCps: Number.POSITIVE_INFINITY })).toBeUndefined();
    expect(sanitizeCaptionOverride({ maxCps: '20' as unknown as number })).toBeUndefined();
  });
});

describe('sanitizeCaptionOverride — full patch', () => {
  it('assembles a fully-specified, valid override', () => {
    const raw: CaptionOverride = {
      fontFamily: 'Anton',
      sizeScale: 1.4,
      textColor: '#ffffff',
      activeColor: '#ffd400',
      spokenColor: '#888888',
      outline: true,
      box: false,
      uppercase: true,
      positionBand: 'bottom',
      maxLines: 1,
      maxCps: 20,
    };
    expect(sanitizeCaptionOverride(raw)).toEqual({
      fontFamily: 'Anton',
      sizeScale: 1.4,
      textColor: '#FFFFFF',
      activeColor: '#FFD400',
      spokenColor: '#888888',
      outline: true,
      box: false,
      uppercase: true,
      positionBand: 'bottom',
      maxLines: 1,
      maxCps: 20,
    });
  });

  it('keeps only the valid fields when mixed with invalid ones', () => {
    expect(
      sanitizeCaptionOverride({
        fontFamily: 'NotAFont',
        sizeScale: 1.1,
        textColor: 'nope',
      }),
    ).toEqual({ sizeScale: 1.1 });
  });
});
