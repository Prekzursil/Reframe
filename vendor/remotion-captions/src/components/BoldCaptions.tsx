import { useCurrentFrame, useVideoConfig, spring } from "remotion";
import { useCaptionPages } from "../hooks/useCaptionPages";
import { BOLD_THEME } from "../styles/theme";
import type { TemplateTheme, TemplateOpts } from "../templates";
import { blockAnchor, lineFontFamily, outlineShadow } from "./captionStyle";
import type { Caption } from "../types";

interface BoldCaptionsProps {
  captions: Caption[];
  /** Theme overrides merged onto BOLD_THEME (P4 §4 — data-driven templates). */
  theme?: TemplateTheme;
  /** Layout opts (position / uppercase / outline / fontFamily). */
  opts?: TemplateOpts;
}

/**
 * Bold-family captions: pop-in spring animation with a highlighted active word.
 * The base look is Montserrat ALL-CAPS, yellow active word; the `theme`/`opts`
 * props let the template registry retune it into the `neon` / `impact` /
 * `mrbeast` looks (different palette / position / outline) without new
 * components (P4 §4 / C2).
 *
 * Words per page: 2-3 (800ms combine window)
 * Animation: Pop-in spring {mass:1, damping:12, stiffness:200}
 */
export const BoldCaptions: React.FC<BoldCaptionsProps> = ({
  captions,
  theme,
  opts,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;

  const t = { ...BOLD_THEME, ...(theme ?? {}) };
  const o = opts ?? {};
  const uppercase = o.uppercase ?? true;

  const pages = useCaptionPages(captions, 800);

  // Find the current page
  const currentPage = pages.find(
    (p) =>
      currentTimeMs >= p.startMs &&
      currentTimeMs < p.startMs + p.durationMs
  );

  if (!currentPage) return null;

  const pageStartFrame = Math.floor((currentPage.startMs / 1000) * fps);
  const localFrame = frame - pageStartFrame;

  // Pop-in spring animation
  const scale = spring({
    frame: localFrame,
    fps,
    config: { mass: 1, damping: 12, stiffness: 200 },
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 40,
        right: 40,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 12,
        transform: `scale(${scale})`,
        ...blockAnchor(o.position),
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
              fontFamily: lineFontFamily(o.fontFamily, "'Montserrat', sans-serif"),
              fontWeight: 800,
              fontSize: 72,
              textTransform: uppercase ? "uppercase" : "none",
              color: isActive ? t.activeColor : t.textColor,
              textShadow: outlineShadow(t.shadowColor ?? "#000000", o.outline, 3),
              lineHeight: 1.1,
              textAlign: "center",
            }}
          >
            {uppercase ? text.toUpperCase() : text}
          </span>
        );
      })}
    </div>
  );
};
