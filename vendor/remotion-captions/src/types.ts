import { z } from "zod";

import { CAPTION_STYLES } from "./templates";

export { CAPTION_STYLES };

/**
 * Wire types for the CaptionedClip composition.
 *
 * `Cue` matches CONTRACTS.md §3 EXACTLY (field names frozen, times in SECONDS):
 *   Cue {index:int, start:float, end:float, text:str}
 *
 * The sidecar (features/caption_remotion.py) writes contract Cues into the
 * render job's inputProps; this module converts them to the millisecond
 * `Caption` shape the vendored caption components consume.
 */
export const CueSchema = z.object({
  index: z.number(),
  start: z.number(), // seconds, already re-based to clip-local t=0 by the sidecar
  end: z.number(), // seconds
  text: z.string(),
});

export type Cue = z.infer<typeof CueSchema>;

/** Internal caption shape (milliseconds) used by the vendored components. */
export const CaptionSchema = z.object({
  text: z.string(),
  startMs: z.number(),
  endMs: z.number(),
});

export type Caption = z.infer<typeof CaptionSchema>;

/**
 * The premium caption style registry. `CAPTION_STYLES` is re-exported from
 * `./templates` (the visual source of truth — P4 §4) and is an explicit
 * readonly tuple literal (C1: `z.enum` needs a tuple, NOT `Object.keys`).
 * Mirrors STYLES in sidecar/media_studio/features/caption_remotion.py — kept in
 * sync by app/renderer/src/lib/captionTemplates.conformance.test.ts.
 * (ShortMaker's style picker consumes this list.)
 */
export const CaptionStyle = z.enum(CAPTION_STYLES);
export type CaptionStyleType = z.infer<typeof CaptionStyle>;

/**
 * inputProps for the CaptionedClip composition (T4a unit contract):
 *   {videoSrc, cues, style, width:1080, height:1920}
 * plus durationInSeconds so calculateMetadata can size the render without
 * probing the video from inside the page.
 *
 * `hookTitle` (P3-A, optional) is the top-anchored headline the sidecar
 * `build_job` forwards when a moment has a hook — the Remotion counterpart to
 * the libass hook burn. Absent/blank ⇒ no headline (default composition
 * unchanged), matching the sidecar which omits the key for whitespace-only text.
 */
export const CaptionedClipPropsSchema = z.object({
  videoSrc: z.string(),
  cues: z.array(CueSchema),
  style: CaptionStyle,
  width: z.number().int().default(1080),
  height: z.number().int().default(1920),
  durationInSeconds: z.number(),
  hookTitle: z.string().optional(),
});

export type CaptionedClipProps = z.infer<typeof CaptionedClipPropsSchema>;

/** Convert contract Cues (seconds) to component Captions (milliseconds). */
export const cuesToCaptions = (cues: Cue[]): Caption[] =>
  (cues ?? [])
    .filter((c) => c.end > c.start)
    .map((c) => ({
      text: c.text,
      startMs: c.start * 1000,
      endMs: c.end * 1000,
    }));
