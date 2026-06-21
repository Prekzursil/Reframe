import { useMemo } from "react";
import { AbsoluteFill, OffthreadVideo } from "remotion";
import { Captions } from "./components/Captions";
import { fontFaceCSS } from "./styles/fonts";
import { cuesToCaptions } from "./types";
import type { CaptionedClipProps } from "./types";

/**
 * The clean caption-burn composition (T4a).
 *
 * Receives an ALREADY-REFRAMED 1080x1920 clip (pipeline: cut -> reframe ->
 * captions) plus contract Cues (seconds, clip-local — the sidecar re-bases by
 * sourceStart before writing the job) and burns the chosen animated caption
 * style over the video.
 *
 * `videoSrc` must be an http(s) URL when rendering headless — Remotion's
 * renderer proxy does not support file:// (proven upstream gotcha). The
 * render CLI serves local files over a loopback HTTP server and rewrites
 * videoSrc before invoking renderMedia.
 */
export const CaptionedClip: React.FC<CaptionedClipProps> = ({
  videoSrc,
  cues,
  style,
}) => {
  const captions = useMemo(() => cuesToCaptions(cues), [cues]);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      {/* Load custom fonts for captions (graceful fallback when absent) */}
      <style dangerouslySetInnerHTML={{ __html: fontFaceCSS }} />

      {/* The pre-reframed clip, filling the canvas */}
      {videoSrc ? (
        <OffthreadVideo
          src={videoSrc}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      ) : null}

      {/* Animated captions */}
      <Captions captions={captions} style={style} />
    </AbsoluteFill>
  );
};
