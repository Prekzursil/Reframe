import { staticFile } from "remotion";

/**
 * Font declarations for caption styles.
 *
 * Fonts are loaded from public/fonts/ directory:
 * - Montserrat Bold (Bold + Karaoke styles) — Google Fonts, OFL
 * - Bangers (Bounce style) — Google Fonts, OFL
 * - Inter Bold (Clean style) — Google Fonts, OFL
 *
 * The .ttf binaries are NOT vendored (see ../../LICENSE-NOTES.md). When a font
 * file is absent from public/fonts/ the @font-face fails to load and the
 * component's CSS font stack falls back to a system font.
 */
export const FONTS = {
  montserrat: {
    family: "Montserrat",
    src: staticFile("fonts/Montserrat-Bold.ttf"),
    weight: "800",
  },
  bangers: {
    family: "Bangers",
    src: staticFile("fonts/Bangers-Regular.ttf"),
    weight: "400",
  },
  inter: {
    family: "Inter",
    src: staticFile("fonts/Inter-Bold.ttf"),
    weight: "700",
  },
} as const;

/**
 * CSS @font-face declarations for all caption fonts.
 * Injected into the composition via a <style> tag.
 */
export const fontFaceCSS = Object.values(FONTS)
  .map(
    (f) => `
@font-face {
  font-family: '${f.family}';
  src: url('${f.src}') format('truetype');
  font-weight: ${f.weight};
  font-display: block;
}
`
  )
  .join("\n");
