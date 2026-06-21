import type { Caption, CaptionStyleType } from "../types";
import { TEMPLATES, optsForTemplate } from "../templates";
import type { TemplateDef } from "../templates";
import { BoldCaptions } from "./BoldCaptions";
import { BounceCaptions } from "./BounceCaptions";
import { CleanCaptions } from "./CleanCaptions";
import { KaraokeCaptions } from "./KaraokeCaptions";

interface CaptionsProps {
  captions: Caption[];
  style: CaptionStyleType;
}

/**
 * Style dispatcher — routes to the correct caption FAMILY component, passing the
 * template's `theme` overrides + layout `opts` (P4 §4 / C2). The template
 * registry (../templates.ts) is the single source of truth for which family
 * animates a style and how it looks; this dispatcher stays data-driven so new
 * looks are added by editing the registry, not this switch.
 */
export const Captions: React.FC<CaptionsProps> = ({ captions, style }) => {
  if (!captions || captions.length === 0) return null;

  const def: TemplateDef = TEMPLATES[style] ?? TEMPLATES.bold;
  const theme = def.theme;
  const opts = optsForTemplate(def);

  switch (def.family) {
    case "bold":
      return <BoldCaptions captions={captions} theme={theme} opts={opts} />;
    case "bounce":
      return <BounceCaptions captions={captions} theme={theme} opts={opts} />;
    case "clean":
      return <CleanCaptions captions={captions} theme={theme} opts={opts} />;
    case "karaoke":
      return <KaraokeCaptions captions={captions} theme={theme} opts={opts} />;
    default:
      return <BoldCaptions captions={captions} theme={theme} opts={opts} />;
  }
};
