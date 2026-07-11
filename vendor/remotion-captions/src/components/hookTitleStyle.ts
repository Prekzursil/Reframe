/**
 * Pure hook-title resolution for the CaptionedClip composition (P3-A).
 *
 * The sidecar (features/caption_remotion.py `build_job`) writes a `hookTitle`
 * string into the render job's inputProps whenever the moment has a hook. The
 * libass engine already burns it as a top-anchored headline (caption.py
 * `build_ass`), so the Remotion engine MUST too — otherwise a premium short
 * silently loses its hook depending on which caption engine ran.
 *
 * This resolves the headline's look from the SAME template registry the captions
 * use, so the hook matches the chosen style. Kept remotion-free (and zod-free,
 * `style` typed as `string`) so it stays unit-testable outside the Remotion
 * runtime — the React `HookTitle` wrapper adds the AbsoluteFill.
 */
import { TEMPLATES } from "../templates";
import { lineFontFamily } from "./captionStyle";

export interface HookTitleVisual {
  /** The trimmed headline text (never blank — `null` is returned for blanks). */
  title: string;
  textColor: string;
  shadowColor: string;
  fontFamily: string;
}

/** Fallback font when a template carries none (matches the Bold family base). */
const FALLBACK_FONT = "'Montserrat', sans-serif";

/**
 * Resolve the hook headline's visual for `style`, or `null` when `text` is blank
 * (blank ⇒ "no hook", mirroring the sidecar `build_job` which omits the key for
 * whitespace-only titles). An unknown style falls back to `bold` — the same
 * defensive idiom `Captions.tsx` uses for the body captions.
 */
export function hookTitleVisual(text: string, style: string): HookTitleVisual | null {
  const title = (text ?? "").trim();
  if (!title) return null;
  const def = TEMPLATES[style] ?? TEMPLATES.bold;
  return {
    title,
    textColor: def.theme.textColor ?? "#FFFFFF",
    shadowColor: def.theme.shadowColor ?? "#000000",
    fontFamily: lineFontFamily(def.fontFamily, FALLBACK_FONT),
  };
}
