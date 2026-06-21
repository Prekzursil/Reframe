import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { useCaptionPages } from "../hooks/useCaptionPages";
import { CLEAN_THEME } from "../styles/theme";
import type { TemplateTheme, TemplateOpts } from "../templates";
import { blockAnchor, boxStyle, lineFontFamily } from "./captionStyle";
import type { Caption } from "../types";

interface CleanCaptionsProps {
  captions: Caption[];
  /** Theme overrides merged onto CLEAN_THEME (P4 §4). */
  theme?: TemplateTheme;
  /** Layout opts (position / box / uppercase / fontFamily). */
  opts?: TemplateOpts;
}

/**
 * Clean-family captions: minimal fade-in, readable lines, 3-5 words per page.
 * The base is white Inter with a subtle shadow; the `theme`/`opts` props retune
 * it into the `tiktok` / `serif` / `subtitle` looks (card box / serif font /
 * translucent strip) (P4 §4 / C2).
 *
 * Words per page: 3-5 (1500ms combine window)
 * Animation: Fade-in opacity 0 → 1 over 6 frames
 */
export const CleanCaptions: React.FC<CleanCaptionsProps> = ({
  captions,
  theme,
  opts,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;

  const t = { ...CLEAN_THEME, ...(theme ?? {}) };
  const o = opts ?? {};
  const uppercase = o.uppercase ?? false;

  const pages = useCaptionPages(captions, 1500);

  const currentPage = pages.find(
    (p) =>
      currentTimeMs >= p.startMs &&
      currentTimeMs < p.startMs + p.durationMs
  );

  if (!currentPage) return null;

  const pageStartFrame = Math.floor((currentPage.startMs / 1000) * fps);
  const localFrame = frame - pageStartFrame;

  // Fade-in over 6 frames
  const opacity = interpolate(localFrame, [0, 6], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 60,
        right: 60,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flexWrap: "wrap",
        opacity,
        ...blockAnchor(o.position),
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          flexWrap: "wrap",
          ...boxStyle(o.box, t.backgroundColor),
        }}
      >
        {currentPage.tokens.map((token, i) => {
          const isActive =
            currentTimeMs >= token.fromMs && currentTimeMs < token.toMs;
          const text = token.text.trim();

          return (
            <span
              key={`${currentPage.startMs}-${i}`}
              style={{
                fontFamily: lineFontFamily(o.fontFamily, "'Inter', sans-serif"),
                fontWeight: 700,
                fontSize: 56,
                textTransform: uppercase ? "uppercase" : "none",
                color: isActive ? t.activeColor : t.textColor,
                textShadow: `2px 2px 8px ${t.shadowColor ?? "rgba(0, 0, 0, 0.6)"}`,
                lineHeight: 1.3,
                textAlign: "center",
                marginRight: 8,
              }}
            >
              {uppercase ? text.toUpperCase() : text}
            </span>
          );
        })}
      </div>
    </div>
  );
};
