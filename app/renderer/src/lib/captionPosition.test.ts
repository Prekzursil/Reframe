import { describe, expect, it } from 'vitest';
import {
  type CaptionBox,
  DEFAULT_CAPTION_BOX,
  MIN_BOX_H,
  MIN_BOX_W,
  RESIZE_HANDLES,
  bandBox,
  boxBand,
  boxToCss,
  boxToWire,
  clampBox,
  moveBox,
  resizeBox,
} from './captionPosition';

describe('clampBox', () => {
  it('passes a valid box through unchanged', () => {
    const box: CaptionBox = { x: 0.2, y: 0.3, w: 0.5, h: 0.2 };
    expect(clampBox(box)).toEqual(box);
  });

  it('clamps width/height into [min, 1]', () => {
    expect(clampBox({ x: 0, y: 0, w: 0.01, h: 0.01 })).toEqual({
      x: 0,
      y: 0,
      w: MIN_BOX_W,
      h: MIN_BOX_H,
    });
    expect(clampBox({ x: 0, y: 0, w: 5, h: 5 })).toEqual({ x: 0, y: 0, w: 1, h: 1 });
  });

  it('clamps the top-left so the box stays inside the frame', () => {
    // x too negative -> 0; y past the bottom -> 1-h.
    expect(clampBox({ x: -1, y: 9, w: 0.4, h: 0.2 })).toEqual({ x: 0, y: 0.8, w: 0.4, h: 0.2 });
    // x past the right edge -> 1-w.
    expect(clampBox({ x: 9, y: 0, w: 0.4, h: 0.2 })).toEqual({ x: 0.6, y: 0, w: 0.4, h: 0.2 });
  });

  it('falls back to default fields for missing or non-finite values', () => {
    expect(clampBox({})).toEqual(DEFAULT_CAPTION_BOX);
    expect(clampBox({ x: NaN, y: Infinity, w: NaN, h: NaN })).toEqual(DEFAULT_CAPTION_BOX);
    // A non-number field also falls back.
    expect(clampBox({ w: 'wide' as unknown as number })).toEqual(DEFAULT_CAPTION_BOX);
  });
});

describe('bandBox', () => {
  it('seeds top/center/bottom bands centred horizontally', () => {
    const { w, h } = DEFAULT_CAPTION_BOX;
    const x = (1 - w) / 2;
    expect(bandBox('top')).toEqual({ x, y: 0.06, w, h });
    expect(bandBox('center')).toEqual({ x, y: (1 - h) / 2, w, h });
    expect(bandBox('bottom')).toEqual({ x, y: 1 - h - 0.06, w, h });
  });
});

describe('moveBox', () => {
  it('translates by fractional deltas', () => {
    expect(moveBox({ x: 0.2, y: 0.2, w: 0.4, h: 0.2 }, 0.1, -0.05)).toEqual({
      x: 0.30000000000000004,
      y: 0.15000000000000002,
      w: 0.4,
      h: 0.2,
    });
  });

  it('clamps at the frame edge', () => {
    expect(moveBox({ x: 0.5, y: 0.5, w: 0.4, h: 0.2 }, 1, 1)).toEqual({
      x: 0.6,
      y: 0.8,
      w: 0.4,
      h: 0.2,
    });
  });
});

describe('resizeBox', () => {
  const base: CaptionBox = { x: 0.3, y: 0.3, w: 0.4, h: 0.4 };

  it('grows the east edge and caps width at the minimum', () => {
    expect(resizeBox(base, 'e', 0.1, 0)).toEqual({ ...base, w: 0.5 });
    expect(resizeBox(base, 'e', -1, 0)).toEqual({ ...base, w: MIN_BOX_W });
  });

  it('grows the south edge and caps height at the minimum', () => {
    expect(resizeBox(base, 's', 0.1, 0.1)).toEqual({ ...base, h: 0.5 });
    expect(resizeBox(base, 's', 0, -1)).toEqual({ ...base, h: MIN_BOX_H });
  });

  const closeBox = (got: CaptionBox, want: CaptionBox): void => {
    expect(got.x).toBeCloseTo(want.x, 10);
    expect(got.y).toBeCloseTo(want.y, 10);
    expect(got.w).toBeCloseTo(want.w, 10);
    expect(got.h).toBeCloseTo(want.h, 10);
  };

  it('moves the west edge (negative dx grows leftward) and caps it', () => {
    // dx negative -> x decreases, width grows.
    closeBox(resizeBox(base, 'w', -0.1, 0), { ...base, x: 0.2, w: 0.5 });
    // dx large positive -> x capped so width stays >= MIN.
    const capped = resizeBox(base, 'w', 1, 0);
    expect(capped.w).toBeCloseTo(MIN_BOX_W, 10);
    expect(capped.x).toBeCloseTo(0.7 - MIN_BOX_W, 10);
  });

  it('moves the north edge and caps it', () => {
    closeBox(resizeBox(base, 'n', 0, -0.1), { ...base, y: 0.2, h: 0.5 });
    const capped = resizeBox(base, 'n', 0, 1);
    expect(capped.h).toBeCloseTo(MIN_BOX_H, 10);
    expect(capped.y).toBeCloseTo(0.7 - MIN_BOX_H, 10);
  });

  it('handles a corner (south-east grows both)', () => {
    closeBox(resizeBox(base, 'se', 0.1, 0.1), { ...base, w: 0.5, h: 0.5 });
  });

  it('handles a corner (north-west moves origin and grows both)', () => {
    closeBox(resizeBox(base, 'nw', -0.1, -0.1), { x: 0.2, y: 0.2, w: 0.5, h: 0.5 });
  });

  it('re-clamps a resize that overflows the frame', () => {
    const big = resizeBox({ x: 0.8, y: 0.8, w: 0.15, h: 0.15 }, 'se', 0.5, 0.5);
    expect(big.x + big.w).toBeLessThanOrEqual(1.0000001);
    expect(big.y + big.h).toBeLessThanOrEqual(1.0000001);
    // The pinned NW corner must NOT move; the moving edges cap at the frame.
    closeBox(big, { x: 0.8, y: 0.8, w: 0.2, h: 0.2 });
  });

  it('pins the opposite edge when a grow handle overshoots the frame', () => {
    // 'e' overshoot: NW corner stays put, width caps at 1 - x.
    closeBox(resizeBox({ x: 0.7, y: 0.3, w: 0.2, h: 0.2 }, 'e', 0.9, 0), {
      x: 0.7,
      y: 0.3,
      w: 0.3,
      h: 0.2,
    });
    // 's' overshoot: top edge pinned, height caps at 1 - y.
    closeBox(resizeBox({ x: 0.3, y: 0.7, w: 0.2, h: 0.2 }, 's', 0, 0.9), {
      x: 0.3,
      y: 0.7,
      w: 0.2,
      h: 0.3,
    });
  });

  it('pins the anchored edge when a west/north drag overshoots past the frame', () => {
    // 'w' overshoot: the right edge (x+w) stays pinned, x clamps to 0.
    closeBox(resizeBox({ x: 0.5, y: 0.5, w: 0.3, h: 0.3 }, 'w', -0.6, 0), {
      x: 0,
      y: 0.5,
      w: 0.8,
      h: 0.3,
    });
    // 'n' overshoot: the bottom edge (y+h) stays pinned, y clamps to 0.
    closeBox(resizeBox({ x: 0.5, y: 0.5, w: 0.3, h: 0.3 }, 'n', 0, -0.6), {
      x: 0.5,
      y: 0,
      w: 0.3,
      h: 0.8,
    });
  });

  it('exposes the eight handles in render order', () => {
    expect(RESIZE_HANDLES).toEqual(['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se']);
  });
});

describe('boxToCss', () => {
  it('formats percent placement', () => {
    expect(boxToCss({ x: 0.1, y: 0.25, w: 0.8, h: 0.16 })).toEqual({
      left: '10.0000%',
      top: '25.0000%',
      width: '80.0000%',
      height: '16.0000%',
    });
  });
});

describe('boxToWire', () => {
  it('rounds to 4 decimals after clamping', () => {
    expect(boxToWire({ x: 0.123456, y: 0.654321, w: 0.5, h: 0.2 })).toEqual({
      x: 0.1235,
      y: 0.6543,
      w: 0.5,
      h: 0.2,
    });
  });
});

describe('boxBand', () => {
  it('classifies by the box centre', () => {
    expect(boxBand({ x: 0, y: 0, w: 1, h: 0.1 })).toBe('top');
    expect(boxBand({ x: 0, y: 0.45, w: 1, h: 0.1 })).toBe('center');
    expect(boxBand({ x: 0, y: 0.9, w: 1, h: 0.1 })).toBe('bottom');
  });
});
