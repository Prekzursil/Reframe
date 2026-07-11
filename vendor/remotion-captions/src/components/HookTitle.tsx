import { AbsoluteFill } from "remotion";
import type { CaptionStyleType } from "../types";
import { outlineShadow } from "./captionStyle";
import { hookTitleVisual } from "./hookTitleStyle";

interface HookTitleProps {
  text: string;
  style: CaptionStyleType;
}

/**
 * Top-anchored hook headline (P3-A) for the Remotion caption render — the
 * counterpart to the libass hook burn (caption.py `build_ass`, ASS \an8) and the
 * live CaptionOverlay hook slot. Renders nothing when `text` is blank, so the
 * default (hook-less) composition is unchanged. Font + colours come from the
 * template registry so the headline matches the chosen caption style.
 */
export const HookTitle: React.FC<HookTitleProps> = ({ text, style }) => {
  const visual = hookTitleVisual(text, style);
  if (!visual) return null;

  return (
    <AbsoluteFill
      style={{ alignItems: "center", justifyContent: "flex-start", pointerEvents: "none" }}
    >
      <div
        data-hook-title="true"
        style={{
          marginTop: 120,
          maxWidth: "88%",
          textAlign: "center",
          fontFamily: visual.fontFamily,
          fontWeight: 800,
          fontSize: 64,
          lineHeight: 1.12,
          color: visual.textColor,
          textShadow: outlineShadow(visual.shadowColor, true, 3),
        }}
      >
        {visual.title}
      </div>
    </AbsoluteFill>
  );
};
