/**
 * Caption template registry — the SINGLE SOURCE OF TRUTH for the visual look of
 * every premium (Remotion) caption style (P4 §4, the keystone).
 *
 * A `TemplateDef` is a small, data-only description of an OpusClip-style look:
 * which family component animates it (`bold` / `bounce` / `clean` / `karaoke`),
 * plus theme colour overrides + layout opts (position / uppercase / box /
 * outline / fontFamily). `Captions.tsx` dispatches on `family` and passes the
 * merged `theme` + `opts` into the family component — so new looks are added by
 * editing THIS table, not by writing new components.
 *
 * THREE-WAY MIRROR (conformance-tested by
 * app/renderer/src/lib/captionTemplates.conformance.test.ts):
 *   1. THIS file's `TEMPLATES` keys      (visual source of truth)
 *   2. sidecar caption_remotion.py `STYLES`
 *   3. app/renderer/src/lib/captionTemplates.ts (remotion-engine keys)
 * The renderer's full picker list additionally carries `libass` + `none` which
 * are NOT remotion templates (see C3 — superset relation, not full equality).
 *
 * Backward compat (P4 §4): the four original ids `bold/bounce/clean/karaoke`
 * MUST remain valid template ids.
 */

/** Which family component animates the template. */
export type Family = "bold" | "bounce" | "clean" | "karaoke";

/** Where the caption block sits in the 9:16 frame. */
export type CaptionPosition = "bottom" | "center" | "top";

/**
 * Theme overrides merged onto the family's base theme. Every field is optional;
 * an absent field falls back to the family base (styles/theme.ts).
 */
export interface TemplateTheme {
  textColor?: string;
  activeColor?: string;
  spokenColor?: string;
  shadowColor?: string;
  backgroundColor?: string;
  activeBackground?: string;
  rotatingColors?: string[];
}

/** Layout / typography opts threaded into the family component. */
export interface TemplateOpts {
  fontFamily?: string;
  position?: CaptionPosition;
  uppercase?: boolean;
  /** Solid caption card behind the line. */
  box?: boolean;
  /** Thick text outline (impact / meme look). */
  outline?: boolean;
}

/** One OpusClip-style caption template. */
export interface TemplateDef {
  id: string;
  label: string;
  family: Family;
  theme: TemplateTheme;
  fontFamily?: string;
  position?: CaptionPosition;
  uppercase?: boolean;
  box?: boolean;
  outline?: boolean;
}

/**
 * The ≥12 template registry. Ids are STABLE (never rename — the sidecar gate +
 * the renderer mirror + persisted clip metadata reference them by id). Palettes
 * are tuned per template for genuinely distinct OpusClip-style looks.
 */
export const TEMPLATES: Record<string, TemplateDef> = {
  // -- the four originals (backward compat — ids frozen) --------------------
  bold: {
    id: "bold",
    label: "Bold",
    family: "bold",
    theme: { textColor: "#FFFFFF", activeColor: "#FFD700", shadowColor: "#000000" },
    fontFamily: "'Montserrat', sans-serif",
    position: "bottom",
    uppercase: true,
  },
  karaoke: {
    id: "karaoke",
    label: "Karaoke",
    family: "karaoke",
    theme: {
      textColor: "#FFFFFF",
      spokenColor: "#00E5FF",
      activeColor: "#FFD700",
      activeBackground: "rgba(0, 0, 0, 0.55)",
      shadowColor: "#000000",
    },
    fontFamily: "'Montserrat', sans-serif",
    position: "bottom",
  },
  clean: {
    id: "clean",
    label: "Clean",
    family: "clean",
    theme: { textColor: "#FFFFFF", activeColor: "#E0E0E0", shadowColor: "rgba(0, 0, 0, 0.6)" },
    fontFamily: "'Inter', sans-serif",
    position: "bottom",
  },
  bounce: {
    id: "bounce",
    label: "Bounce",
    family: "bounce",
    theme: {
      textColor: "#FFFFFF",
      shadowColor: "#000000",
      rotatingColors: ["#00FFFF", "#FF00FF", "#00FF00", "#FFFF00", "#FF6600", "#FF0066"],
    },
    fontFamily: "'Bangers', cursive",
    position: "bottom",
    uppercase: true,
  },

  // -- the OpusClip-style additions ----------------------------------------
  /** Alex-Hormozi green pop word on a black card — the signature money look. */
  hormozi: {
    id: "hormozi",
    label: "Hormozi",
    family: "karaoke",
    theme: {
      textColor: "#FFFFFF",
      spokenColor: "#FFFFFF",
      activeColor: "#22E84F",
      activeBackground: "rgba(0, 0, 0, 0.85)",
      shadowColor: "#000000",
    },
    fontFamily: "'Montserrat', sans-serif",
    position: "center",
    uppercase: true,
    box: true,
  },
  /** Electric neon: cyan text, magenta active glow, top placement. */
  neon: {
    id: "neon",
    label: "Neon",
    family: "bold",
    theme: { textColor: "#39FF14", activeColor: "#FF00E5", shadowColor: "#0A0033" },
    fontFamily: "'Montserrat', sans-serif",
    position: "bottom",
    uppercase: true,
    outline: true,
  },
  /** TikTok caption card: white text on a solid black pill, bottom. */
  tiktok: {
    id: "tiktok",
    label: "TikTok",
    family: "clean",
    theme: { textColor: "#FFFFFF", activeColor: "#FE2C55", backgroundColor: "#000000", shadowColor: "transparent" },
    fontFamily: "'Inter', sans-serif",
    position: "bottom",
    box: true,
  },
  /** Sunset gradient look: warm rotating colours, centred. */
  gradient: {
    id: "gradient",
    label: "Gradient",
    family: "bounce",
    theme: {
      textColor: "#FFFFFF",
      shadowColor: "#1A0030",
      rotatingColors: ["#FF6B6B", "#FFD93D", "#6BCB77", "#4D96FF", "#C77DFF"],
    },
    fontFamily: "'Montserrat', sans-serif",
    position: "center",
    uppercase: true,
  },
  /** Movie-impact: huge uppercase white with a heavy black outline. */
  impact: {
    id: "impact",
    label: "Impact",
    family: "bold",
    theme: { textColor: "#FFFFFF", activeColor: "#FFEB3B", shadowColor: "#000000" },
    fontFamily: "'Montserrat', sans-serif",
    position: "center",
    uppercase: true,
    outline: true,
  },
  /** MrBeast energy: bold yellow word pop, top, outline. */
  mrbeast: {
    id: "mrbeast",
    label: "MrBeast",
    family: "bold",
    theme: { textColor: "#FFFFFF", activeColor: "#FFE000", shadowColor: "#C20000" },
    fontFamily: "'Montserrat', sans-serif",
    position: "top",
    uppercase: true,
    outline: true,
  },
  /** Playful pop: bouncy hot-pink/teal rotation, lowercase-friendly. */
  pop: {
    id: "pop",
    label: "Pop",
    family: "bounce",
    theme: {
      textColor: "#FFFFFF",
      shadowColor: "#2B0040",
      rotatingColors: ["#FF4D9D", "#36E2EC", "#FFD166", "#9B5DE5"],
    },
    fontFamily: "'Bangers', cursive",
    position: "center",
  },
  /** Editorial serif: elegant cream text, clean fade, bottom. */
  serif: {
    id: "serif",
    label: "Serif",
    family: "clean",
    theme: { textColor: "#F5EFE0", activeColor: "#E8C547", shadowColor: "rgba(0, 0, 0, 0.7)" },
    fontFamily: "Georgia, 'Times New Roman', serif",
    position: "bottom",
  },
  /** Broadcast subtitle: plain white on a translucent strip, bottom. */
  subtitle: {
    id: "subtitle",
    label: "Subtitle",
    family: "clean",
    theme: { textColor: "#FFFFFF", activeColor: "#FFFFFF", backgroundColor: "rgba(0, 0, 0, 0.6)", shadowColor: "transparent" },
    fontFamily: "'Inter', sans-serif",
    position: "bottom",
    box: true,
  },
  /** Fire: hot orange→red active sweep, karaoke fill, centred. */
  fire: {
    id: "fire",
    label: "Fire",
    family: "karaoke",
    theme: {
      textColor: "#FFE0B2",
      spokenColor: "#FF3D00",
      activeColor: "#FFEB3B",
      activeBackground: "rgba(60, 0, 0, 0.6)",
      shadowColor: "#3E0000",
    },
    fontFamily: "'Montserrat', sans-serif",
    position: "center",
    uppercase: true,
  },
};

/**
 * The explicit ordered id list. KEEP THIS A LITERAL TUPLE — `types.ts` builds a
 * `z.enum` from it (C1: z.enum needs a readonly tuple literal, NOT
 * `Object.keys`). A conformance test asserts `new Set(CAPTION_STYLES)` equals
 * `new Set(Object.keys(TEMPLATES))`.
 */
export const CAPTION_STYLES = [
  "bold",
  "karaoke",
  "clean",
  "bounce",
  "hormozi",
  "neon",
  "tiktok",
  "gradient",
  "impact",
  "mrbeast",
  "pop",
  "serif",
  "subtitle",
  "fire",
] as const;

/** Merged opts for a template (used by Captions.tsx dispatch). */
export const optsForTemplate = (def: TemplateDef): Required<TemplateOpts> => ({
  fontFamily: def.fontFamily ?? "",
  position: def.position ?? "bottom",
  uppercase: def.uppercase ?? false,
  box: def.box ?? false,
  outline: def.outline ?? false,
});
