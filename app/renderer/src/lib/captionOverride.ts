// captionOverride.ts — the additive, within-template caption TUNING patch (V1.1 Lane 1, WU S1).
//
// V1 treats a "caption style" as a whole-template atomic pick (`CaptionDesign.style`).
// V1.1 adds a SEPARATE, additive `CaptionOverride` patch that tweaks ~8 primitive
// controls (font/size/colours/outline/card/casing/position-band/line-count/reading-speed)
// ON TOP of the chosen template — without touching the frozen three-way caption mirror
// (the conformance test still guards the base CAPTION_STYLES ↔ TEMPLATES ↔ sidecar STYLES
// relation; overrides are validated independently and never widen the template id set).
//
// Everything here is PURE (no React, no DOM). The sidecar `apply_override()` (WU S2) merges
// the validated patch onto the resolved template visual before `build_ass` emits Style lines.
// Validation mirrors `sanitizeCaptionDesign`: unknown font => drop, bad hex => drop,
// out-of-range number => clamp. No silent crash — a malformed field degrades to the template
// default (i.e. is omitted) rather than throwing. Unit-tested in captionOverride.test.ts.

/** The coarse vertical band the caption sits in (fine offset stays in CaptionBox). */
export type CaptionPositionBand = 'top' | 'center' | 'bottom';

/** The wrap target: prefer 1 line unless the cue exceeds the CPL limit. */
export type CaptionMaxLines = 1 | 2;

/**
 * A bounded, additive patch applied on top of a resolved caption template.
 * Every field is OPTIONAL: an absent field => the template's value is used. A
 * present-but-invalid field is dropped during validation (never overrides with junk).
 */
export interface CaptionOverride {
  /** Font family — must be one of CURATED_CAPTION_FONTS (allowlist); else dropped. */
  fontFamily?: string;
  /** Multiplier on the template/auto font size; clamped to [SIZE_SCALE_MIN, SIZE_SCALE_MAX]. */
  sizeScale?: number;
  /** Primary text colour as #RRGGBB (validated, normalised uppercase); else dropped. */
  textColor?: string;
  /** Karaoke active (currently-lit) word colour, #RRGGBB. */
  activeColor?: string;
  /** Karaoke already-spoken word colour, #RRGGBB. */
  spokenColor?: string;
  /** Outline/stroke on the glyphs. */
  outline?: boolean;
  /** Solid caption card (opaque box) behind the text. */
  box?: boolean;
  /** Upper-case the cue text. */
  uppercase?: boolean;
  /** Coarse vertical band; fine offset stays in the CaptionBox. */
  positionBand?: CaptionPositionBand;
  /** Wrap target (1 or 2 lines). */
  maxLines?: CaptionMaxLines;
  /** Reading-speed cap (chars/sec); clamped to [MAX_CPS_MIN, MAX_CPS_MAX]. */
  maxCps?: number;
}

/**
 * The bundled, curated caption-font allowlist (DECISIONS §3: a fixed list, no
 * system-font detection). WU S2 wires these into the burn-in fontconfig set so a
 * selected font actually renders. `DejaVu Sans` is libass's always-present fallback.
 */
export const CURATED_CAPTION_FONTS: readonly string[] = [
  'Inter',
  'Roboto',
  'Open Sans',
  'Noto Sans',
  'Lato',
  'Nunito',
  'Montserrat',
  'Poppins',
  'Oswald',
  'Anton',
  'Bebas Neue',
  'Archivo Black',
  'DejaVu Sans',
];

/** Font-size multiplier clamp bounds (§1.2). */
export const SIZE_SCALE_MIN = 0.6;
export const SIZE_SCALE_MAX = 1.8;

/** Reading-speed (CPS) clamp window (§1.5: default 17, move within 10..30). */
export const MAX_CPS_MIN = 10;
export const MAX_CPS_MAX = 30;

/** #RRGGBB only — 3-digit shorthand and alpha forms are deliberately rejected. */
const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

const POSITION_BANDS: readonly string[] = ['top', 'center', 'bottom'];

/** A finite number clamped into [lo, hi], or undefined for a non-finite/non-number. */
function clampNumber(value: unknown, lo: number, hi: number): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  if (value < lo) return lo;
  if (value > hi) return hi;
  return value;
}

/** A trimmed, uppercase-normalised #RRGGBB string, or undefined when invalid. */
function normalizeHexColor(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return HEX_COLOR.test(trimmed) ? trimmed.toUpperCase() : undefined;
}

/** A boolean assigned onto `out[key]` only when `value` is a genuine boolean. */
function assignBoolean(out: CaptionOverride, key: 'outline' | 'box' | 'uppercase', value: unknown): void {
  if (typeof value === 'boolean') out[key] = value;
}

/**
 * Validate a raw (persisted/untrusted) override into a clean CaptionOverride.
 * Each field is checked independently; invalid fields are dropped (fonts/colours/
 * enums) or clamped (numbers). Returns `undefined` when nothing valid remains, so
 * an absent/empty override is back-compatible with V1's no-override behaviour.
 */
export function sanitizeCaptionOverride(
  raw: Partial<CaptionOverride> | null | undefined,
): CaptionOverride | undefined {
  const r = raw ?? {};
  const out: CaptionOverride = {};

  const fontFamily = typeof r.fontFamily === 'string' ? r.fontFamily.trim() : '';
  if (CURATED_CAPTION_FONTS.includes(fontFamily)) out.fontFamily = fontFamily;

  const sizeScale = clampNumber(r.sizeScale, SIZE_SCALE_MIN, SIZE_SCALE_MAX);
  if (sizeScale !== undefined) out.sizeScale = sizeScale;

  const textColor = normalizeHexColor(r.textColor);
  if (textColor !== undefined) out.textColor = textColor;

  const activeColor = normalizeHexColor(r.activeColor);
  if (activeColor !== undefined) out.activeColor = activeColor;

  const spokenColor = normalizeHexColor(r.spokenColor);
  if (spokenColor !== undefined) out.spokenColor = spokenColor;

  assignBoolean(out, 'outline', r.outline);
  assignBoolean(out, 'box', r.box);
  assignBoolean(out, 'uppercase', r.uppercase);

  if (typeof r.positionBand === 'string' && POSITION_BANDS.includes(r.positionBand)) {
    out.positionBand = r.positionBand;
  }

  if (r.maxLines === 1 || r.maxLines === 2) out.maxLines = r.maxLines;

  const maxCps = clampNumber(r.maxCps, MAX_CPS_MIN, MAX_CPS_MAX);
  if (maxCps !== undefined) out.maxCps = maxCps;

  return Object.keys(out).length > 0 ? out : undefined;
}
