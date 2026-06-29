// captionOverridePreview.ts — pure helpers that fold a validated CaptionOverride
// (V1.1 Lane 1, WU S1) onto a template visual for the LIVE PREVIEW (WU S3).
//
// The T2 "Customize…" disclosure (CaptionCustomizer) edits a CaptionOverride; the
// CaptionDesigner preview must reflect every change immediately. The sidecar's
// `apply_override()` (WU S2) is the authority for the EXPORT; this module is the
// renderer-side MIRROR for the on-screen preview only — it never crosses RPC.
//
// Everything here is PURE (no React state, no DOM). The override is already
// validated/clamped by `sanitizeCaptionOverride`, so a present field is trusted;
// an ABSENT field falls back to the chosen template's value (so an override is a
// delta, never a blank slate). `??` (not `||`) is used so a deliberate `false`
// boolean override is honoured rather than treated as "unset".

import type { CSSProperties } from 'react';
import { type CaptionTemplateVisual, captionVisualFor } from './captionTemplates';
import type { CaptionOverride } from './captionOverride';

/** The identity font-size multiplier used when the override sets no `sizeScale`. */
export const NEUTRAL_SIZE_SCALE = 1;

/** Wrap a bare curated font name into a CSS font-family with a safe fallback. */
export function cssFontFamily(name: string): string {
  return `'${name}', sans-serif`;
}

/**
 * Merge a validated override onto the resolved template visual for the live
 * preview. An absent override (or absent field) keeps the template's value.
 */
export function previewVisual(style: string, override?: CaptionOverride): CaptionTemplateVisual {
  const base = captionVisualFor(style);
  if (override === undefined) return base;
  return {
    ...base,
    fontFamily:
      override.fontFamily !== undefined ? cssFontFamily(override.fontFamily) : base.fontFamily,
    textColor: override.textColor ?? base.textColor,
    activeColor: override.activeColor ?? base.activeColor,
    spokenColor: override.spokenColor ?? base.spokenColor,
    uppercase: override.uppercase ?? base.uppercase,
    box: override.box ?? base.box,
    outline: override.outline ?? base.outline,
  };
}

/** The font-size multiplier the preview applies (identity when the field is unset). */
export function previewSizeScale(override?: CaptionOverride): number {
  return override?.sizeScale ?? NEUTRAL_SIZE_SCALE;
}

/**
 * Inline CSS for the sample caption LINE: font + scale + box card + outline,
 * mirroring the export look. Per-word COLOUR is applied by the caller (the
 * designer paints each karaoke word individually), so colour is intentionally
 * omitted here.
 */
export function captionSampleStyle(visual: CaptionTemplateVisual, scale: number): CSSProperties {
  return {
    fontFamily: visual.fontFamily,
    fontSize: `${scale}em`,
    textTransform: visual.uppercase ? 'uppercase' : 'none',
    backgroundColor: visual.box ? visual.backgroundColor : 'transparent',
    WebkitTextStroke: visual.outline ? `0.6px ${visual.shadowColor}` : undefined,
    textShadow: visual.outline ? 'none' : `0 1px 2px ${visual.shadowColor}`,
  };
}
