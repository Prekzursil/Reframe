import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CAPTION_DESIGN,
  SAMPLE_CAPTION_PHRASE,
  captionDesignWire,
  sampleCaptionCues,
  sanitizeCaptionDesign,
} from './captionDesign';
import { DEFAULT_CAPTION_BOX, boxToWire } from './captionPosition';
import { DEFAULT_CAPTION_STYLE } from '../features/shortMakerLogic';

describe('sanitizeCaptionDesign', () => {
  it('keeps a valid style + clamps the box', () => {
    const d = sanitizeCaptionDesign({ style: 'karaoke', box: { x: 0.1, y: 0.2, w: 0.5, h: 0.2 } });
    expect(d.style).toBe('karaoke');
    expect(d.box).toEqual({ x: 0.1, y: 0.2, w: 0.5, h: 0.2 });
  });

  it('falls back to the default style for an unknown id', () => {
    expect(sanitizeCaptionDesign({ style: 'bogus' }).style).toBe(DEFAULT_CAPTION_STYLE);
  });

  it('preserves the opusclip-karaoke libass preset (V1.1 WU SP1 BLOCKER fix)', () => {
    // Before the fix the preset was absent from CAPTION_STYLE_OPTIONS, so this
    // sanitizer reset it to the libass default and the karaoke burn was
    // unreachable end-to-end. It must now survive sanitization to route to the
    // sidecar with karaoke=True.
    expect(sanitizeCaptionDesign({ style: 'opusclip-karaoke' }).style).toBe('opusclip-karaoke');
  });

  it('defaults the whole design for null / non-string style / missing box', () => {
    expect(sanitizeCaptionDesign(null)).toEqual(DEFAULT_CAPTION_DESIGN);
    expect(sanitizeCaptionDesign(undefined)).toEqual(DEFAULT_CAPTION_DESIGN);
    expect(sanitizeCaptionDesign({ style: 42 as unknown as string })).toEqual(
      DEFAULT_CAPTION_DESIGN,
    );
  });

  it('attaches a validated override when present', () => {
    const d = sanitizeCaptionDesign({
      style: 'karaoke',
      box: { x: 0.1, y: 0.2, w: 0.5, h: 0.2 },
      override: { fontFamily: 'Anton', sizeScale: 9, textColor: '#ff0000' },
    });
    expect(d.override).toEqual({ fontFamily: 'Anton', sizeScale: 1.8, textColor: '#FF0000' });
  });

  it('omits the override key entirely when it sanitises to nothing (back-compat)', () => {
    const d = sanitizeCaptionDesign({
      style: 'karaoke',
      override: { fontFamily: 'NotAFont' },
    });
    expect(d).not.toHaveProperty('override');
  });
});

describe('captionDesignWire', () => {
  it('emits the style id + a wire-rounded box', () => {
    const wire = captionDesignWire({ style: 'neon', box: { x: 0.123456, y: 0.2, w: 0.5, h: 0.2 } });
    expect(wire).toEqual({
      captionStyle: 'neon',
      captionPosition: boxToWire({ x: 0.123456, y: 0.2, w: 0.5, h: 0.2 }),
    });
  });

  it('round-trips the default design', () => {
    expect(captionDesignWire(DEFAULT_CAPTION_DESIGN)).toEqual({
      captionStyle: DEFAULT_CAPTION_STYLE,
      captionPosition: boxToWire(DEFAULT_CAPTION_BOX),
    });
  });

  it('carries the override onto the wire when present', () => {
    const wire = captionDesignWire({
      style: 'karaoke',
      box: DEFAULT_CAPTION_BOX,
      override: { uppercase: true, maxLines: 1 },
    });
    expect(wire.captionOverride).toEqual({ uppercase: true, maxLines: 1 });
  });

  it('omits captionOverride when the design has no override', () => {
    const wire = captionDesignWire({ style: 'neon', box: DEFAULT_CAPTION_BOX });
    expect(wire).not.toHaveProperty('captionOverride');
  });
});

describe('sampleCaptionCues', () => {
  it('spreads the default phrase across the window (capped at 0.6s/word)', () => {
    const cues = sampleCaptionCues({ start: 0, end: 6 });
    expect(cues).toHaveLength(SAMPLE_CAPTION_PHRASE.length);
    expect(cues[0]).toEqual({ index: 0, start: 0, end: 0.6, text: 'Your' });
    // Evenly stepped at the 0.6s cap.
    expect(cues[1].start).toBe(0.6);
  });

  it('compresses into a short window and honours a custom phrase + start offset', () => {
    const cues = sampleCaptionCues({ start: 10, end: 10.5 }, ['a', 'b']);
    expect(cues).toHaveLength(2);
    expect(cues[0].start).toBe(10);
    expect(cues[1].start).toBeCloseTo(10.25, 5);
    expect(cues[1].end).toBeCloseTo(10.5, 5);
  });

  it('tolerates a degenerate (zero-length) window', () => {
    const cues = sampleCaptionCues({ start: 5, end: 5 });
    expect(cues[0].start).toBe(5);
    expect(cues[cues.length - 1].end).toBeGreaterThan(5);
  });
});
