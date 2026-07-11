// captionStyleNames.ts — LOOK-based caption style naming for the Caption gallery.
//
// The redesign (§4 Caption) requires styles be named by their LOOK — "Word-by-word
// pop", "Keyword highlight", "Editorial serif" — with a live preview each, and it
// FORBIDS surfacing any font/codec/model/brand name in a user-visible string. The
// shipped catalog (`features/shortMakerLogic.ts` ALL_CAPTION_STYLES) still carries
// creator/tool brand labels ("Hormozi", "MrBeast", "TikTok", "OpusClip Karaoke")
// and engine jargon ("libass"). This pure module re-maps every catalog id to a
// jargon-free look name + a LAYOUT/BEHAVIOUR family, so the gallery differentiates
// styles by TYPE (how the caption behaves/sits), never by inventing a new accent
// hue — the guard the redesign calls out for exactly this surface.
//
// Everything here is PURE. The `captionStyleNames` conformance test asserts every
// selectable catalog id has an explicit look entry so a name can never silently
// go missing (the same drift defence the caption template mirror uses).

import { type CaptionEngineKind } from './captionTemplates';
import { ALL_CAPTION_STYLES, type CaptionStyleOption } from '../features/shortMakerLogic';

/**
 * The LAYOUT/BEHAVIOUR family a style belongs to. Used to GROUP the gallery so
 * styles are told apart by how they behave/sit, never by a decorative second hue.
 */
export type CaptionStyleFamily =
  | 'word-by-word'
  | 'keyword'
  | 'bold'
  | 'clean'
  | 'editorial'
  | 'none';

/** A style's jargon-free look identity. */
export interface CaptionStyleLook {
  /** Look-based display name (never a font/codec/model/brand name). */
  name: string;
  /** The layout/behaviour family used to group the gallery. */
  family: CaptionStyleFamily;
  /** A one-line plain-language description of the look. */
  blurb: string;
}

/**
 * Every selectable style id → its look identity. Keyed by the catalog ids in
 * `ALL_CAPTION_STYLES`. Names describe the LOOK/behaviour only.
 */
export const CAPTION_STYLE_LOOKS: Record<string, CaptionStyleLook> = {
  'opusclip-karaoke': {
    name: 'Word-by-word pop',
    family: 'word-by-word',
    blurb: 'Each word pops as it is spoken',
  },
  karaoke: {
    name: 'Karaoke fill',
    family: 'word-by-word',
    blurb: 'Words fill in as they are said',
  },
  bounce: { name: 'Bouncy words', family: 'word-by-word', blurb: 'Words spring in one at a time' },
  hormozi: {
    name: 'Keyword highlight',
    family: 'keyword',
    blurb: 'A boxed line with the key word emphasised',
  },
  mrbeast: { name: 'Top banner', family: 'keyword', blurb: 'A big emphasised line across the top' },
  bold: { name: 'Bold caps', family: 'bold', blurb: 'Loud, all-caps lines' },
  impact: { name: 'Heavy outline', family: 'bold', blurb: 'Thick outlined display type' },
  neon: { name: 'Neon glow', family: 'bold', blurb: 'Glowing outlined type' },
  gradient: { name: 'Sunset blend', family: 'bold', blurb: 'A warm multi-tone display look' },
  pop: { name: 'Playful pop', family: 'bold', blurb: 'Rounded, colourful display type' },
  fire: { name: 'Hot sweep', family: 'bold', blurb: 'A warm sweep across the line' },
  libass: { name: 'Clean classic', family: 'clean', blurb: 'Simple, fast, readable captions' },
  clean: { name: 'Minimal', family: 'clean', blurb: 'Quiet, unstyled lines' },
  subtitle: {
    name: 'Broadcast subtitle',
    family: 'clean',
    blurb: 'Boxed broadcast-style captions',
  },
  tiktok: { name: 'Caption card', family: 'clean', blurb: 'A solid card behind the line' },
  serif: { name: 'Editorial serif', family: 'editorial', blurb: 'A quiet pull-quote voice' },
  none: { name: 'No captions', family: 'none', blurb: 'Leave the video uncaptioned' },
};

/** Fallback look for an unknown id (never throws — the gallery stays populated). */
export const DEFAULT_STYLE_LOOK: CaptionStyleLook = {
  name: 'Custom style',
  family: 'clean',
  blurb: 'A custom caption look',
};

/** The look identity for a style id (falls back for unknown ids; never throws). */
export function styleLook(id: string): CaptionStyleLook {
  return CAPTION_STYLE_LOOKS[id] ?? DEFAULT_STYLE_LOOK;
}

/** The family display order for the gallery (headline behaviours first). */
export const CAPTION_FAMILY_ORDER: readonly CaptionStyleFamily[] = [
  'word-by-word',
  'keyword',
  'bold',
  'clean',
  'editorial',
  'none',
];

/** The section heading shown for each family. */
export const CAPTION_FAMILY_LABEL: Record<CaptionStyleFamily, string> = {
  'word-by-word': 'Word by word',
  keyword: 'Keyword emphasis',
  bold: 'Bold display',
  clean: 'Clean & minimal',
  editorial: 'Editorial',
  none: 'Off',
};

/** A catalog option re-labelled by its LOOK, carrying its family + blurb. */
export interface LookStyleOption {
  id: string;
  label: string;
  family: CaptionStyleFamily;
  blurb: string;
  engine: CaptionEngineKind;
}

/** Re-label a base catalog by look (defaults to the full selectable catalog). */
export function lookNamedCatalog(
  base: readonly CaptionStyleOption[] = ALL_CAPTION_STYLES,
): LookStyleOption[] {
  return base.map((option) => {
    const look = styleLook(option.id);
    return {
      id: option.id,
      label: look.name,
      family: look.family,
      blurb: look.blurb,
      engine: option.engine,
    };
  });
}

/** A gallery section: one family with its populated look options. */
export interface CaptionStyleGroup {
  family: CaptionStyleFamily;
  label: string;
  options: LookStyleOption[];
}

/** Group look options into ordered, non-empty family sections for the gallery. */
export function groupByFamily(options: readonly LookStyleOption[]): CaptionStyleGroup[] {
  return CAPTION_FAMILY_ORDER.map((family) => ({
    family,
    label: CAPTION_FAMILY_LABEL[family],
    options: options.filter((option) => option.family === family),
  })).filter((group) => group.options.length > 0);
}
