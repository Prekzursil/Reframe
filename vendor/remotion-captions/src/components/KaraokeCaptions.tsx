import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { useCaptionPages } from "../hooks/useCaptionPages";
import { KARAOKE_THEME } from "../styles/theme";
import type { TemplateTheme, TemplateOpts } from "../templates";
import { blockAnchor, lineFontFamily, outlineShadow } from "./captionStyle";
import type { Caption } from "../types";

interface KaraokeCaptionsProps {
  captions: Caption[];
  /** Theme overrides merged onto KARAOKE_THEME (P4 §4). */
  theme?: TemplateTheme;
  /** Layout opts (position / uppercase / box / fontFamily). */
  opts?: TemplateOpts;
}

/**
 * Karaoke-family captions: the whole page stays visible while words "light up"
 * progressively as they are spoken — classic karaoke fill. The `theme`/`opts`
 * props retune it into the `hormozi` (green pop card) / `fire` (hot sweep)
 * looks (P4 §4 / C2).
 *
 * Words per page: 3-5 (1200ms combine window)
 * Animation: Fade-in page; per-word color sweep upcoming → active → spoken,
 * with a pill behind the active word.
 */
export const KaraokeCaptions: React.FC<KaraokeCaptionsProps> = ({
  captions,
  theme,
  opts,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTimeMs = (frame / fps) * 1000;

  const t = { ...KARAOKE_THEME, ...(theme ?? {}) };
  const o = opts ?? {};
  const uppercase = o.uppercase ?? false;

  const pages = useCaptionPages(captions, 1200);

  const currentPage = pages.find(
    (p) =>
      currentTimeMs >= p.startMs &&
      currentTimeMs < p.startMs + p.durationMs
  );

  if (!currentPage) return null;

  const pageStartFrame = Math.floor((currentPage.startMs / 1000) * fps);
  const localFrame = frame - pageStartFrame;

  // Quick fade-in so page swaps don't pop harshly
  const opacity = interpolate(localFrame, [0, 4], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        position: "absolute",
        left: 50,
        right: 50,
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 10,
        opacity,
        ...blockAnchor(o.position),
      }}
    >
      {currentPage.tokens.map((token, i) => {
        const isActive =
          currentTimeMs >= token.fromMs && currentTimeMs < token.toMs;
        const isSpoken = currentTimeMs >= token.toMs;
        const text = token.text.trim();

        const color = isActive
          ? t.activeColor
          : isSpoken
            ? t.spokenColor
            : t.textColor;

        return (
          <span
            key={`${currentPage.startMs}-${i}`}
            style={{
              fontFamily: lineFontFamily(o.fontFamily, "'Montserrat', sans-serif"),
              fontWeight: 800,
              fontSize: 64,
              textTransform: uppercase ? "uppercase" : "none",
              color,
              backgroundColor: isActive
                ? t.activeBackground ?? "rgba(0, 0, 0, 0.55)"
                : "transparent",
              borderRadius: 12,
              padding: "2px 10px",
              textShadow: outlineShadow(t.shadowColor ?? "#000000", o.outline, 3),
              lineHeight: 1.15,
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
