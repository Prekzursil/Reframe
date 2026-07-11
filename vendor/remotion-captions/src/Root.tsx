import { Composition } from "remotion";
import { CaptionedClip } from "./CaptionedClip";
import { CaptionedClipPropsSchema } from "./types";

/** Frame rate of the rendered short (fixed; duration comes from inputProps). */
export const FPS = 30;

/** Composition id — features/caption_remotion.py writes this into render jobs. */
export const COMPOSITION_ID = "CaptionedClip";

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id={COMPOSITION_ID}
        component={CaptionedClip}
        width={1080}
        height={1920}
        fps={FPS}
        durationInFrames={FPS * 30}
        schema={CaptionedClipPropsSchema}
        defaultProps={{
          videoSrc: "",
          cues: [],
          style: "bold" as const,
          width: 1080,
          height: 1920,
          durationInSeconds: 30,
          hookTitle: "",
        }}
        calculateMetadata={({ props }) => {
          // selectComposition() resolves this from the job's inputProps, so the
          // render is sized exactly to the clip — no probing inside the page.
          return {
            durationInFrames: Math.max(1, Math.ceil(props.durationInSeconds * FPS)),
            fps: FPS,
            width: props.width,
            height: props.height,
          };
        }}
      />
    </>
  );
};
