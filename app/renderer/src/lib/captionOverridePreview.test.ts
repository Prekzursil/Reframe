import { describe, expect, it } from 'vitest';
import {
  NEUTRAL_SIZE_SCALE,
  captionSampleStyle,
  cssFontFamily,
  previewSizeScale,
  previewVisual,
} from './captionOverridePreview';
import { captionVisualFor } from './captionTemplates';
import type { CaptionOverride } from './captionOverride';

describe('cssFontFamily', () => {
  it('wraps a bare curated font name with a quoted family + sans-serif fallback', () => {
    expect(cssFontFamily('Inter')).toBe("'Inter', sans-serif");
    expect(cssFontFamily('Bebas Neue')).toBe("'Bebas Neue', sans-serif");
  });
});

describe('previewVisual', () => {
  it('returns the base template visual unchanged when there is no override', () => {
    expect(previewVisual('karaoke', undefined)).toEqual(captionVisualFor('karaoke'));
  });

  it('falls back to the libass default visual for an unknown style (no override)', () => {
    expect(previewVisual('does-not-exist')).toEqual(captionVisualFor('libass'));
  });

  it('merges every set override field onto the base visual', () => {
    const override: CaptionOverride = {
      fontFamily: 'Oswald',
      textColor: '#112233',
      activeColor: '#445566',
      spokenColor: '#778899',
      uppercase: true,
      box: true,
      outline: true,
    };
    const visual = previewVisual('clean', override);
    expect(visual.fontFamily).toBe("'Oswald', sans-serif");
    expect(visual.textColor).toBe('#112233');
    expect(visual.activeColor).toBe('#445566');
    expect(visual.spokenColor).toBe('#778899');
    expect(visual.uppercase).toBe(true);
    expect(visual.box).toBe(true);
    expect(visual.outline).toBe(true);
  });

  it('keeps the base value for each field the override leaves unset', () => {
    const base = captionVisualFor('hormozi');
    // Only textColor is set; every other field must keep the template value.
    const visual = previewVisual('hormozi', { textColor: '#0F0F0F' });
    expect(visual.textColor).toBe('#0F0F0F');
    expect(visual.fontFamily).toBe(base.fontFamily);
    expect(visual.activeColor).toBe(base.activeColor);
    expect(visual.spokenColor).toBe(base.spokenColor);
    expect(visual.uppercase).toBe(base.uppercase);
    expect(visual.box).toBe(base.box);
    expect(visual.outline).toBe(base.outline);
  });

  it('honours a false boolean override (does not fall back to the template value)', () => {
    // hormozi has box=true + uppercase=true in the template; the override forces them off.
    const visual = previewVisual('hormozi', { box: false, uppercase: false, outline: false });
    expect(visual.box).toBe(false);
    expect(visual.uppercase).toBe(false);
    expect(visual.outline).toBe(false);
  });
});

describe('previewSizeScale', () => {
  it('is the neutral identity scale when no override / no sizeScale is set', () => {
    expect(previewSizeScale(undefined)).toBe(NEUTRAL_SIZE_SCALE);
    expect(previewSizeScale({ textColor: '#FFFFFF' })).toBe(NEUTRAL_SIZE_SCALE);
    expect(NEUTRAL_SIZE_SCALE).toBe(1);
  });

  it('returns the override sizeScale when present', () => {
    expect(previewSizeScale({ sizeScale: 1.4 })).toBe(1.4);
  });
});

describe('captionSampleStyle', () => {
  it('applies the box background + a soft shadow when outline is off', () => {
    const visual = { ...captionVisualFor('subtitle'), box: true, outline: false };
    const style = captionSampleStyle(visual, 1.2);
    expect(style.fontSize).toBe('1.2em');
    expect(style.backgroundColor).toBe(visual.backgroundColor);
    expect(style.WebkitTextStroke).toBeUndefined();
    expect(style.textShadow).toBe(`0 1px 2px ${visual.shadowColor}`);
    expect(style.textTransform).toBe('none');
  });

  it('applies a text stroke (no shadow) + transparent background for an outline+no-box visual', () => {
    const visual = { ...captionVisualFor('neon'), box: false, outline: true, uppercase: true };
    const style = captionSampleStyle(visual, 1);
    expect(style.backgroundColor).toBe('transparent');
    expect(style.WebkitTextStroke).toBe(`0.6px ${visual.shadowColor}`);
    expect(style.textShadow).toBe('none');
    expect(style.textTransform).toBe('uppercase');
    expect(style.fontFamily).toBe(visual.fontFamily);
  });
});
