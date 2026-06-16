import { useCurrentFrame, useVideoConfig, spring } from "remotion";
import { useCaptionPages } from "../hooks/useCaptionPages";
import { BOUNCE_THEME } from "../styles/theme";
import type { TemplateTheme, TemplateOpts } from "../templates";
import { blockAnchor, boxStyle, lineFontFamily, outlineShadow } from "./captionStyle";
import type { Caption } from "../types";

interface BounceCaptionsProps {
  captions: Caption[];
  /** Theme overrides merged onto BOUNCE_THEME (P4 §4). */
  theme?: TemplateTheme;
  /** Layout opts (position / uppercase / box / fontFamily). */
  opts?: TemplateOpts;
}

/**
 * Bounce-family captions: bouncy scale spring, rotating bright colours, 1-2
 * words per page for maximum impact. The `theme`/`opts` props let the registry
 * retune it into the `gradient` / `pop` looks (palette / position) (P4 §4 / C2).
 *
 * Words per page: 1-2 (600ms combine window)
 * Animation: Scale spring 70% → 120% → 100% {mass:1, damping:8}
 */
export const BounceCaptions: React.FC<BounceCaptionsProps> = ({
  captions,
  theme,
  opts,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;

  const t = { ...BOUNCE_THEME, ...(theme ?? {}) };
  const o = opts ?? {};
  const uppercase = o.uppercase ?? true;
  const rotating =
    t.rotatingColors && t.rotatingColors.length > 0
      ? t.rotatingColors
      : BOUNCE_THEME.rotatingColors;

  const pages = useCaptionPages(captions, 600);

  const currentPage = pages.find(
    (p) =>
      currentTimeMs >= p.startMs &&
      currentTimeMs < p.startMs + p.durationMs
  );

  if (!currentPage) return null;

  const pageStartFrame = Math.floor((currentPage.startMs / 1000) * fps);
  const localFrame = frame - pageStartFrame;
  const pageIndex = pages.indexOf(currentPage);

  // Bouncy scale spring: starts at 0.7, overshoots to ~1.2, settles at 1.0
  const rawScale = spring({
    frame: localFrame,
    fps,
    config: { mass: 1, damping: 8, stiffness: 180 },
  });
  const scale = 0.7 + rawScale * 0.3;

  // Rotating color per page
  const color = rotating[pageIndex % rotating.length];
  const text = currentPage.text.trim();

  return (
    <div
      style={{
        position: "absolute",
        left: 40,
        right: 40,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        transform: `scale(${scale})`,
        ...blockAnchor(o.position),
      }}
    >
      <span
        style={{
          fontFamily: lineFontFamily(o.fontFamily, "'Bangers', cursive"),
          fontSize: 84,
          color,
          textShadow: outlineShadow(t.shadowColor ?? "#000000", o.outline, 4),
          textAlign: "center",
          lineHeight: 1.0,
          textTransform: uppercase ? "uppercase" : "none",
          ...boxStyle(o.box, t.backgroundColor),
        }}
      >
        {uppercase ? text.toUpperCase() : text}
      </span>
    </div>
  );
};
