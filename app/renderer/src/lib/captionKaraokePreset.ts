// captionKaraokePreset.ts — renderer mirror of the OpusClip-style KARAOKE caption
// preset (V1.1 WU SP1). The export/burn authority is the sidecar libass builder
// `caption_karaoke.py` (`build_karaoke_ass`); this module is the renderer-side
// MIRROR so the live preview/overlay paints the SAME palette, casing, scale-pop,
// 1-4-word grouping, and 9:16 safe-area position the burn produces. The mirror is
// drift-guarded by `captionKaraokePreset.test.ts`, which reads the sidecar source
// and asserts the shared constants match (the same defence the three-way template
// conformance test uses).
//
// Everything here is PURE (no React, no DOM). This is a libass preset, NOT a
// Remotion template, so it deliberately stays OUT of the frozen three-way
// caption-template mirror (it never widens the template id set / picker list).

/** The caption-style id that selects the OpusClip karaoke preset (libass engine). */
export const OPUSCLIP_KARAOKE_STYLE = 'opusclip-karaoke';

/** White text fill (#RRGGBB) — matches sidecar `KARAOKE_FILL_HEX`. */
export const KARAOKE_FILL_HEX = '#FFFFFF';
/** Thick dark outline colour (#RRGGBB) — matches sidecar `KARAOKE_OUTLINE_HEX`. */
export const KARAOKE_OUTLINE_HEX = '#000000';
/** Alternating active-word accent: yellow, then green — matches sidecar `KARAOKE_ACTIVE_HEX`. */
export const KARAOKE_ACTIVE_HEX = ['#FFFF00', '#00FF00'] as const;

/** Condensed all-caps display font — matches sidecar `KARAOKE_FONT`. */
export const KARAOKE_FONT = 'Anton';
/** Thick-outline width (px at the ASS base) — matches sidecar `KARAOKE_OUTLINE_WIDTH`. */
export const KARAOKE_OUTLINE_WIDTH = 4;
/** Active-word scale-pop percentage (`\fscx`/`\fscy`) — matches sidecar `KARAOKE_POP_SCALE`. */
export const KARAOKE_POP_SCALE = 115;
/** Active-word scale-pop duration in ms (`\t`) — matches sidecar `KARAOKE_POP_MS`. */
export const KARAOKE_POP_MS = 120;
/** 1-4 words per caption line — matches sidecar `MAX_WORDS_PER_LINE`. */
export const MAX_WORDS_PER_LINE = 4;

/** 9:16 safe-area top clearance (fraction of height) — matches sidecar. */
export const SAFE_AREA_TOP_FRACTION = 0.1;
/** 9:16 safe-area bottom clearance (fraction of height) — matches sidecar. */
export const SAFE_AREA_BOTTOM_FRACTION = 0.18;

/** The coarse vertical safe-area band the karaoke line sits in. */
export type KaraokeBand = 'top' | 'center' | 'bottom';

/** True iff `style` selects the OpusClip karaoke preset (case/space-insensitive). */
export function isKaraokeStyle(style: unknown): boolean {
  return typeof style === 'string' && style.trim().toLowerCase() === OPUSCLIP_KARAOKE_STYLE;
}

/** The active-word accent hex for the word at absolute `index` (yellow/green alt). */
export function karaokeActiveColor(index: number): string {
  // Mirrors sidecar `active_color_for_index`; a non-finite index falls to 0 (yellow).
  const safe = Number.isFinite(index) ? Math.abs(Math.trunc(index)) : 0;
  return KARAOKE_ACTIVE_HEX[safe % 2];
}

/**
 * Vertical margin (px) that keeps the line inside the 9:16 safe area — the
 * renderer mirror of sidecar `safe_area_margin_v`. `top` clears the top ~10%;
 * `center` is centred (0); anything else (`bottom`, the default) clears the
 * bottom ~18% so the line sits in the lower-mid, off the platform UI.
 */
export function safeAreaMarginV(height: number, band: KaraokeBand | string): number {
  if (band === 'top') return Math.round(height * SAFE_AREA_TOP_FRACTION);
  if (band === 'center') return 0;
  return Math.round(height * SAFE_AREA_BOTTOM_FRACTION);
}
