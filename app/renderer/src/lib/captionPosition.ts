// captionPosition.ts — pure geometry for the caption POSITION editor (P4 §4).
//
// The caption editor lets the user drag/resize a caption box over a real video
// frame so the on-export caption lands exactly where they place it. The box is
// stored NORMALISED (fractions of the frame, 0..1) so it is resolution- and
// aspect-independent — the same box applies to the 1080x1920 export and to the
// live preview at any size.
//
// Everything here is pure (no React, no DOM): the component (CaptionBox.tsx)
// converts pointer pixels to fractional deltas and calls these helpers; the
// sidecar receives the normalised box and converts it to ASS margins/alignment.
// Exhaustively unit-tested in captionPosition.test.ts.

/** A normalised caption region: top-left (x,y) + size (w,h), all fractions 0..1. */
export interface CaptionBox {
  /** Left edge as a fraction of frame width (0 = left, 1 = right). */
  x: number;
  /** Top edge as a fraction of frame height (0 = top, 1 = bottom). */
  y: number;
  /** Width as a fraction of frame width. */
  w: number;
  /** Height as a fraction of frame height. */
  h: number;
}

/** Minimum box size (fraction) so a caption region never collapses to nothing. */
export const MIN_BOX_W = 0.1;
export const MIN_BOX_H = 0.05;

/** The eight resize handles + the body (drag-to-move). */
export type ResizeHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
export const RESIZE_HANDLES: readonly ResizeHandle[] = ['nw', 'n', 'ne', 'w', 'e', 'sw', 's', 'se'];

/** The three vertical position bands a style template can seed the box from. */
export type CaptionBand = 'top' | 'center' | 'bottom';

/** Clamp a number into [lo, hi] (callers only ever pass lo <= hi). */
function clamp(n: number, lo: number, hi: number): number {
  if (n < lo) return lo;
  if (n > hi) return hi;
  return n;
}

/**
 * Normalise any box into a valid one: size clamped to [min, 1], then the
 * top-left clamped so the whole box stays inside the [0,1] frame. NaN/missing
 * fields fall back to the default box's value for that field (never throws).
 */
export function clampBox(box: Partial<CaptionBox>): CaptionBox {
  const w = clamp(numOr(box.w, DEFAULT_CAPTION_BOX.w), MIN_BOX_W, 1);
  const h = clamp(numOr(box.h, DEFAULT_CAPTION_BOX.h), MIN_BOX_H, 1);
  const x = clamp(numOr(box.x, DEFAULT_CAPTION_BOX.x), 0, 1 - w);
  const y = clamp(numOr(box.y, DEFAULT_CAPTION_BOX.y), 0, 1 - h);
  return { x, y, w, h };
}

/** A finite number, or `fallback` for NaN/Infinity/non-number. */
function numOr(v: unknown, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

/** Default caption box: a wide bottom-centred band (the short-form norm). */
export const DEFAULT_CAPTION_BOX: CaptionBox = { x: 0.1, y: 0.76, w: 0.8, h: 0.16 };

/** Seed a box for a vertical band, preserving the default width/height. */
export function bandBox(band: CaptionBand): CaptionBox {
  const { w, h } = DEFAULT_CAPTION_BOX;
  const x = (1 - w) / 2;
  if (band === 'top') return { x, y: 0.06, w, h };
  if (band === 'center') return { x, y: (1 - h) / 2, w, h };
  return { x, y: 1 - h - 0.06, w, h };
}

/** Move the box by fractional deltas, clamped inside the frame. */
export function moveBox(box: CaptionBox, dx: number, dy: number): CaptionBox {
  return clampBox({ ...box, x: box.x + dx, y: box.y + dy });
}

/**
 * Resize the box by dragging `handle` by fractional deltas. Each edge the
 * handle controls moves; the opposite edge is pinned. The moving edge is capped
 * against BOTH the minimum size AND the frame edge before re-clamping, so an
 * overshoot stops at the frame instead of sliding the pinned opposite edge.
 */
export function resizeBox(
  box: CaptionBox,
  handle: ResizeHandle,
  dx: number,
  dy: number,
): CaptionBox {
  let { x, y, w, h } = box;
  if (handle.includes('e')) {
    w = clamp(w + dx, MIN_BOX_W, 1 - x);
  }
  if (handle.includes('s')) {
    h = clamp(h + dy, MIN_BOX_H, 1 - y);
  }
  if (handle.includes('w')) {
    const right = x + w;
    x = clamp(x + dx, 0, right - MIN_BOX_W);
    w = right - x;
  }
  if (handle.includes('n')) {
    const bottom = y + h;
    y = clamp(y + dy, 0, bottom - MIN_BOX_H);
    h = bottom - y;
  }
  return clampBox({ x, y, w, h });
}

/** CSS placement (percent strings) for absolutely positioning the box. */
export interface BoxCss {
  left: string;
  top: string;
  width: string;
  height: string;
}

/** Convert a normalised box to CSS percent placement. */
export function boxToCss(box: CaptionBox): BoxCss {
  const pct = (n: number): string => `${(n * 100).toFixed(4)}%`;
  return { left: pct(box.x), top: pct(box.y), width: pct(box.w), height: pct(box.h) };
}

/** Round a box to a stable wire precision (4 decimals) for the export payload. */
export function boxToWire(box: CaptionBox): CaptionBox {
  const r = (n: number): number => Math.round(n * 1e4) / 1e4;
  const c = clampBox(box);
  return { x: r(c.x), y: r(c.y), w: r(c.w), h: r(c.h) };
}

/** The vertical band a box's CENTRE falls into (top < 1/3 <= center < 2/3 <= bottom). */
export function boxBand(box: CaptionBox): CaptionBand {
  const cy = box.y + box.h / 2;
  if (cy < 1 / 3) return 'top';
  if (cy < 2 / 3) return 'center';
  return 'bottom';
}
