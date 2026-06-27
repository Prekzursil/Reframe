// captionDesign.ts — the combined caption STYLE + POSITION the editor produces (P4 §4).
//
// A CaptionDesign bundles the chosen style template id with the normalised
// caption box. It is what the caption editor (CaptionDesigner) emits, what the
// Preferences area persists as a default, and what the export payload carries to
// the sidecar (which converts the box to ASS margins/alignment and the style to
// the caption engine). Pure helpers only — unit-tested in captionDesign.test.ts.

import { type CaptionBox, DEFAULT_CAPTION_BOX, boxToWire, clampBox } from './captionPosition';
import { CAPTION_STYLE_OPTIONS, DEFAULT_CAPTION_STYLE } from '../features/shortMakerLogic';
import type { Cue } from './rpc';

/** A caption style template + its on-frame position box. */
export interface CaptionDesign {
  /** A known caption style id (see CAPTION_STYLES). */
  style: string;
  /** The normalised caption region. */
  box: CaptionBox;
}

/** The default design: the libass classic style in the default bottom band. */
export const DEFAULT_CAPTION_DESIGN: CaptionDesign = {
  style: DEFAULT_CAPTION_STYLE,
  box: DEFAULT_CAPTION_BOX,
};

/** Validate a raw (persisted/untrusted) design into a clean CaptionDesign. */
export function sanitizeCaptionDesign(
  raw: Partial<CaptionDesign> | null | undefined,
): CaptionDesign {
  const r = raw ?? {};
  const rawStyle = typeof r.style === 'string' ? r.style.trim() : '';
  const style = CAPTION_STYLE_OPTIONS.includes(rawStyle) ? rawStyle : DEFAULT_CAPTION_STYLE;
  return { style, box: clampBox(r.box ?? {}) };
}

/** The export-payload slice for a caption design (style id + wire-rounded box). */
export interface CaptionDesignWire {
  captionStyle: string;
  captionPosition: CaptionBox;
}

/** Convert a design to the frozen export payload fields the sidecar reads. */
export function captionDesignWire(design: CaptionDesign): CaptionDesignWire {
  return { captionStyle: design.style, captionPosition: boxToWire(design.box) };
}

/** The placeholder phrase the editor animates when there is no real transcript. */
export const SAMPLE_CAPTION_PHRASE = ['Your', 'captions', 'look', 'like', 'this'];

/**
 * Build word-level SAMPLE cues spread across a preview window so the caption
 * editor can animate the chosen style live before a transcript exists. Pure;
 * the words are evenly sliced (capped at 0.6s each) inside the window.
 */
export function sampleCaptionCues(
  window: { start: number; end: number },
  words: readonly string[] = SAMPLE_CAPTION_PHRASE,
): Cue[] {
  const span = Math.max(0.1, window.end - window.start);
  const per = Math.min(0.6, span / Math.max(1, words.length));
  return words.map((text, i) => ({
    index: i,
    start: window.start + i * per,
    end: window.start + (i + 1) * per,
    text,
  }));
}
