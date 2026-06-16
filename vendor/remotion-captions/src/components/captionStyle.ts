/**
 * Shared pure style helpers for the four caption-family components (P4 §4 / C2).
 *
 * Each family component (Bold/Bounce/Clean/Karaoke) now accepts a `theme`
 * override + layout `opts` (position/uppercase/box/outline/fontFamily) from the
 * template registry. These helpers turn those opts into concrete CSS so each
 * component stays small (<50-line functions) and the look logic is testable.
 */
import type { CaptionPosition } from "../templates";

/** Absolute anchor for the caption block by position. */
export const blockAnchor = (
  position?: CaptionPosition
): { bottom: number } | { top: string; transform: string } | { top: number } => {
  switch (position) {
    case "top":
      return { top: 220 };
    case "center":
      return { top: "50%", transform: "translateY(-50%)" };
    case "bottom":
    default:
      return { bottom: 350 };
  }
};

/** Resolve the font stack: template override wins, else the family default. */
export const lineFontFamily = (
  fontFamily: string | undefined,
  fallback: string
): string => {
  const f = (fontFamily ?? "").trim();
  return f.length > 0 ? f : fallback;
};

/**
 * Text shadow string. A plain drop shadow by default; a thick 4-corner outline
 * (the impact/meme look) when `outline` is on.
 */
export const outlineShadow = (
  shadowColor: string,
  outline: boolean | undefined,
  px: number
): string => {
  if (outline) {
    const d = px + 2;
    return [
      `${d}px ${d}px 0 ${shadowColor}`,
      `-${d}px -${d}px 0 ${shadowColor}`,
      `${d}px -${d}px 0 ${shadowColor}`,
      `-${d}px ${d}px 0 ${shadowColor}`,
      `0 0 ${d * 2}px ${shadowColor}`,
    ].join(", ");
  }
  return [
    `${px}px ${px}px 0 ${shadowColor}`,
    `-${px}px -${px}px 0 ${shadowColor}`,
    `${px}px -${px}px 0 ${shadowColor}`,
    `-${px}px ${px}px 0 ${shadowColor}`,
  ].join(", ");
};

/** Solid caption-card style when `box` is on (transparent otherwise). */
export const boxStyle = (
  box: boolean | undefined,
  backgroundColor: string | undefined
): { backgroundColor: string; borderRadius?: number; padding?: string } => {
  if (box) {
    return {
      backgroundColor: backgroundColor && backgroundColor !== "transparent"
        ? backgroundColor
        : "rgba(0, 0, 0, 0.85)",
      borderRadius: 14,
      padding: "10px 22px",
    };
  }
  return { backgroundColor: "transparent" };
};
