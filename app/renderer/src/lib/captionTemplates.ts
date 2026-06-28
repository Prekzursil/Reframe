/**
 * Renderer-side mirror of the caption template visual params (P4 §4 / §5 / C3).
 *
 * The renderer cannot import the vendored Remotion package
 * (`vendor/remotion-captions`, a separate package with a zod dep not in app/),
 * so the visual parameters the live HTML/CSS caption overlay needs are MIRRORED
 * here. The mirror is conformance-tested against the vendor `TEMPLATES` + the
 * sidecar `STYLES` by `captionTemplates.conformance.test.ts`:
 *   remotion-template keys here  ==  vendor TEMPLATES keys  ==  sidecar STYLES.
 *
 * SUPERSET relation (C3): this map ALSO carries `libass` (the picker DEFAULT)
 * and `none`, which are NOT remotion templates. The overlay no-ops on `none`
 * and renders a sensible default look for `libass`. The conformance test
 * therefore checks the remotion subset equals TEMPLATES, and that the full set
 * here equals `keys(TEMPLATES) ∪ {libass, none}`.
 *
 * Keep ids + look in sync with `vendor/remotion-captions/src/templates.ts`.
 */

import {
  KARAOKE_ACTIVE_HEX,
  KARAOKE_FILL_HEX,
  KARAOKE_FONT,
  KARAOKE_OUTLINE_HEX,
  OPUSCLIP_KARAOKE_STYLE,
  isKaraokeStyle,
} from './captionKaraokePreset';

export type CaptionEngineKind = 'libass' | 'remotion';
export type CaptionPosition = 'bottom' | 'center' | 'top';

/** Visual params the HTML/CSS overlay applies for a template. */
export interface CaptionTemplateVisual {
  id: string;
  /** Which caption engine produces the EXPORT for this id. */
  engine: CaptionEngineKind;
  /** Base (inactive/upcoming) text colour. */
  textColor: string;
  /** Colour of the currently-spoken / highlighted word. */
  activeColor: string;
  /** Colour of already-spoken words (karaoke fill); falls back to textColor. */
  spokenColor: string;
  /** Caption-card background (or 'transparent'). */
  backgroundColor: string;
  /** Active-word pill background (karaoke), or 'transparent'. */
  activeBackground: string;
  /** Drop-shadow / outline colour. */
  shadowColor: string;
  fontFamily: string;
  position: CaptionPosition;
  uppercase: boolean;
  /** Solid caption card behind the line. */
  box: boolean;
  /** Thick text outline (impact look). */
  outline: boolean;
}

const DEFAULT_SHADOW = '#000000';

/**
 * The remotion templates (must mirror vendor TEMPLATES exactly by id). Each
 * carries the same palette/font/position/uppercase/box/outline the vendor
 * registry uses, expressed as concrete overlay values.
 */
export const REMOTION_CAPTION_TEMPLATES: Record<string, CaptionTemplateVisual> = {
  bold: {
    id: 'bold',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FFD700',
    spokenColor: '#FFFFFF',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#000000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'bottom',
    uppercase: true,
    box: false,
    outline: false,
  },
  karaoke: {
    id: 'karaoke',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FFD700',
    spokenColor: '#00E5FF',
    backgroundColor: 'transparent',
    activeBackground: 'rgba(0, 0, 0, 0.55)',
    shadowColor: '#000000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'bottom',
    uppercase: false,
    box: false,
    outline: false,
  },
  clean: {
    id: 'clean',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#E0E0E0',
    spokenColor: '#FFFFFF',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: 'rgba(0, 0, 0, 0.6)',
    fontFamily: "'Inter', sans-serif",
    position: 'bottom',
    uppercase: false,
    box: false,
    outline: false,
  },
  bounce: {
    id: 'bounce',
    engine: 'remotion',
    textColor: '#00FFFF',
    activeColor: '#FF00FF',
    spokenColor: '#00FFFF',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#000000',
    fontFamily: "'Bangers', cursive",
    position: 'bottom',
    uppercase: true,
    box: false,
    outline: false,
  },
  hormozi: {
    id: 'hormozi',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#22E84F',
    spokenColor: '#FFFFFF',
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
    activeBackground: 'rgba(0, 0, 0, 0.85)',
    shadowColor: '#000000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'center',
    uppercase: true,
    box: true,
    outline: false,
  },
  neon: {
    id: 'neon',
    engine: 'remotion',
    textColor: '#39FF14',
    activeColor: '#FF00E5',
    spokenColor: '#39FF14',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#0A0033',
    fontFamily: "'Montserrat', sans-serif",
    position: 'bottom',
    uppercase: true,
    box: false,
    outline: true,
  },
  tiktok: {
    id: 'tiktok',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FE2C55',
    spokenColor: '#FFFFFF',
    backgroundColor: '#000000',
    activeBackground: 'transparent',
    shadowColor: 'transparent',
    fontFamily: "'Inter', sans-serif",
    position: 'bottom',
    uppercase: false,
    box: true,
    outline: false,
  },
  gradient: {
    id: 'gradient',
    engine: 'remotion',
    textColor: '#FF6B6B',
    activeColor: '#C77DFF',
    spokenColor: '#FFD93D',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#1A0030',
    fontFamily: "'Montserrat', sans-serif",
    position: 'center',
    uppercase: true,
    box: false,
    outline: false,
  },
  impact: {
    id: 'impact',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FFEB3B',
    spokenColor: '#FFFFFF',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#000000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'center',
    uppercase: true,
    box: false,
    outline: true,
  },
  mrbeast: {
    id: 'mrbeast',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FFE000',
    spokenColor: '#FFFFFF',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#C20000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'top',
    uppercase: true,
    box: false,
    outline: true,
  },
  pop: {
    id: 'pop',
    engine: 'remotion',
    textColor: '#FF4D9D',
    activeColor: '#9B5DE5',
    spokenColor: '#36E2EC',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: '#2B0040',
    fontFamily: "'Bangers', cursive",
    position: 'center',
    uppercase: false,
    box: false,
    outline: false,
  },
  serif: {
    id: 'serif',
    engine: 'remotion',
    textColor: '#F5EFE0',
    activeColor: '#E8C547',
    spokenColor: '#F5EFE0',
    backgroundColor: 'transparent',
    activeBackground: 'transparent',
    shadowColor: 'rgba(0, 0, 0, 0.7)',
    fontFamily: "Georgia, 'Times New Roman', serif",
    position: 'bottom',
    uppercase: false,
    box: false,
    outline: false,
  },
  subtitle: {
    id: 'subtitle',
    engine: 'remotion',
    textColor: '#FFFFFF',
    activeColor: '#FFFFFF',
    spokenColor: '#FFFFFF',
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
    activeBackground: 'transparent',
    shadowColor: 'transparent',
    fontFamily: "'Inter', sans-serif",
    position: 'bottom',
    uppercase: false,
    box: true,
    outline: false,
  },
  fire: {
    id: 'fire',
    engine: 'remotion',
    textColor: '#FFE0B2',
    activeColor: '#FFEB3B',
    spokenColor: '#FF3D00',
    backgroundColor: 'transparent',
    activeBackground: 'rgba(60, 0, 0, 0.6)',
    shadowColor: '#3E0000',
    fontFamily: "'Montserrat', sans-serif",
    position: 'center',
    uppercase: true,
    box: false,
    outline: false,
  },
};

/** libass (the picker DEFAULT) — a sensible default look for the live overlay. */
const LIBASS_VISUAL: CaptionTemplateVisual = {
  id: 'libass',
  engine: 'libass',
  textColor: '#FFFFFF',
  activeColor: '#FFD700',
  spokenColor: '#FFFFFF',
  backgroundColor: 'transparent',
  activeBackground: 'transparent',
  shadowColor: DEFAULT_SHADOW,
  fontFamily: "'Inter', sans-serif",
  position: 'bottom',
  uppercase: false,
  box: false,
  outline: false,
};

/** none — overlay is a no-op (no captions); kept for completeness/superset. */
const NONE_VISUAL: CaptionTemplateVisual = {
  id: 'none',
  engine: 'libass',
  textColor: 'transparent',
  activeColor: 'transparent',
  spokenColor: 'transparent',
  backgroundColor: 'transparent',
  activeBackground: 'transparent',
  shadowColor: 'transparent',
  fontFamily: "'Inter', sans-serif",
  position: 'bottom',
  uppercase: false,
  box: false,
  outline: false,
};

/**
 * The FULL overlay map = remotion templates ∪ {libass, none} (C3 superset).
 * The live overlay looks up any picker id here; `none` produces no caption.
 *
 * NOTE: the libass-only `opusclip-karaoke` PRESET (V1.1 WU SP1) is deliberately
 * NOT a key here — it would widen the conformance-pinned map. Its live-preview
 * look is {@link KARAOKE_PRESET_VISUAL}, returned by {@link captionVisualFor}.
 */
export const CAPTION_TEMPLATE_VISUALS: Record<string, CaptionTemplateVisual> = {
  libass: LIBASS_VISUAL,
  ...REMOTION_CAPTION_TEMPLATES,
  none: NONE_VISUAL,
};

/**
 * Live-preview visual for the OpusClip KARAOKE libass preset (V1.1 WU SP1).
 *
 * This is the renderer overlay's MIRROR of the sidecar `caption_karaoke.py`
 * burn: white all-caps condensed fill (Anton), a thick dark outline, a yellow
 * active word (the burn alternates yellow/green per word — the overlay applies
 * that alternation per word via `karaokeActiveColor`), and a lower-mid (safe
 * area) position. Built from the SHARED `captionKaraokePreset` constants so the
 * preview can never silently drift from the burn palette/casing (the same
 * constants the drift-guard test pins against the sidecar source).
 *
 * It is kept out of {@link CAPTION_TEMPLATE_VISUALS} (which the conformance test
 * pins to `TEMPLATES ∪ {libass, none}`) and surfaced via {@link captionVisualFor}
 * so selecting `opusclip-karaoke` paints the karaoke look live in the picker
 * swatch, the on-video overlay, and the caption designer sample.
 */
export const KARAOKE_PRESET_VISUAL: CaptionTemplateVisual = {
  id: OPUSCLIP_KARAOKE_STYLE,
  engine: 'libass',
  textColor: KARAOKE_FILL_HEX,
  // Yellow is the first accent; the live overlay alternates yellow/green per
  // word via karaokeActiveColor (this is the swatch / fallback active colour).
  activeColor: KARAOKE_ACTIVE_HEX[0],
  // Already-spoken words reset to the white fill in the burn (no persistent
  // "spoken" colour), so the preview mirrors that.
  spokenColor: KARAOKE_FILL_HEX,
  backgroundColor: 'transparent',
  activeBackground: 'transparent',
  shadowColor: KARAOKE_OUTLINE_HEX,
  fontFamily: `'${KARAOKE_FONT}', sans-serif`,
  position: 'bottom',
  uppercase: true,
  box: false,
  outline: true,
};

/** Ids of the remotion templates only (must equal vendor TEMPLATES keys). */
export const REMOTION_TEMPLATE_IDS: readonly string[] = Object.keys(REMOTION_CAPTION_TEMPLATES);

/**
 * P4 §8a emphasis policy — RENDERER MIRROR of the sidecar's per-style default
 * (`features/emphasis.py` `CLEAN_STYLES` + `default_emphasis_for_style`). The
 * renderer cannot import the sidecar package, so the set is mirrored here and a
 * conformance test (`captionTemplates.conformance.test.ts`) asserts it equals
 * the sidecar `CLEAN_STYLES` so the two never drift.
 *
 * Caption styles for which keyword/emoji emphasis defaults OFF: the clean /
 * minimal looks (plus the no-caption + libass-default passes). EVERY other
 * (OpusClip-style) template defaults emphasis ON. Lower-case ids; matched
 * case-insensitively. The empty id ('' = no style chosen) is treated as clean.
 */
export const CLEAN_CAPTION_STYLES: ReadonlySet<string> = new Set([
  'clean',
  'subtitle',
  'none',
  'libass',
  '',
]);

/**
 * Whether emphasis defaults ON for caption `style` (P4 §8a) — the renderer
 * mirror of `emphasis.default_emphasis_for_style`. ON for the OpusClip-style
 * templates (bold/hormozi/neon/...); OFF for the clean/minimal looks + the
 * no-caption / libass passes (`CLEAN_CAPTION_STYLES`). Pure; never throws.
 */
export const defaultEmphasisForStyle = (style: string): boolean =>
  !CLEAN_CAPTION_STYLES.has((style ?? '').trim().toLowerCase());

/** True when the overlay should render nothing for this id. */
export const isNoCaption = (templateId: string): boolean => templateId === 'none';

/**
 * Look up the overlay visual for a picker id, falling back to the libass
 * default look for any unknown id (never throws — pure).
 *
 * The libass-only `opusclip-karaoke` preset (V1.1 WU SP1) is NOT in the visual
 * map (it would widen the conformance-pinned set), so it is resolved here to
 * {@link KARAOKE_PRESET_VISUAL} — making the karaoke look render live wherever
 * the overlay/picker/designer call this.
 */
export const captionVisualFor = (templateId: string): CaptionTemplateVisual =>
  isKaraokeStyle(templateId)
    ? KARAOKE_PRESET_VISUAL
    : CAPTION_TEMPLATE_VISUALS[templateId] ?? LIBASS_VISUAL;
