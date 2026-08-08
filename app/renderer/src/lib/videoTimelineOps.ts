// videoTimelineOps.ts — PURE video-lane operations for the direct-manipulation
// timeline editor. The CLIENT MIRROR of
// `sidecar/media_studio/features/video_tracks.py`.
//
// Division of labour, and why it is this way round:
//
//   * the SIDECAR is strict — an illegal edit RAISES, so a bad edit can never be
//     silently stored;
//   * the CLIENT here CLAMPS — a drag must feel continuous, so the handle stops
//     at the legal limit instead of the gesture failing.
//
// That only works if every clamped value the client produces is one the sidecar
// ACCEPTS. If the two disagree the user sees an edit that then fails to commit,
// which is precisely the "looks functional and silently drops edits" outcome the
// editor must not have. So the frame math here is an EXACT mirror, including
// Python's banker's rounding (see `secondsToFrames`), and the tests assert the
// sidecar's own invariant — `frameSpan === frameSourceSpan` — on every preview.
//
// The sidecar remains authoritative: a commit returns the stored clip and the
// caller replaces its lane state from that response. Ids minted here for a split
// are PROVISIONAL for exactly that reason (`provisionalClipId`).
//
// Cue-level subtitle editing is a DIFFERENT model and lives in `timelineOps.ts`
// (owned elsewhere); this module borrows only its pure `timeFromClientX` mapper.

import { timeFromClientX } from './timelineOps';

export { timeFromClientX };

/** The timeline frame rates the sidecar accepts (`nle_export.FPS_CHOICES`). */
export type Fps = 24 | 25 | 30 | 60;

/** The shortest clip any edit may produce — one frame (`MIN_CLIP_FRAMES`). */
export const MIN_CLIP_FRAMES = 1;

/** Maximum retained undo steps (mirrors `timelineOps.MAX_HISTORY`). */
export const MAX_HISTORY = 100;

/** A source window placed on a lane. Duration is DERIVED, never stored. */
export interface VideoClip {
  id: string;
  path: string;
  srcIn: number;
  srcOut: number;
  timelineStart: number;
}

/** A stacked video lane. */
export interface VideoLane {
  id: string;
  name: string;
  index: number;
  clips: VideoClip[];
}

/** Which trim handle is being dragged. */
export type ClipEdge = 'start' | 'end';

// ---------------------------------------------------------------------------
// the frame grid — an EXACT mirror of nle_export.seconds_to_frames
// ---------------------------------------------------------------------------

/**
 * Round half-to-EVEN, which is what Python's `round()` does.
 *
 * `Math.round` rounds half UP, so `Math.round(2.5) === 3` while Python's
 * `round(2.5) === 2`. On a tie (a time landing exactly on a half-frame) the two
 * would disagree by ONE FRAME, and the preview would jump when the sidecar
 * committed its own value. Ties are reachable in normal use — at 30fps any
 * multiple of 1/60 s is one — so this is a real divergence, not a theoretical
 * one, and the mirror matches Python instead of the platform.
 *
 * Only called with non-negative input (callers clamp first), which is why the
 * negative-tie direction is not handled.
 */
function roundHalfToEven(x: number): number {
  const floor = Math.floor(x);
  const frac = x - floor;
  if (frac > 0.5) return floor + 1;
  if (frac < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

/** Quantize seconds to a whole frame count at `fps` (negatives clamp to 0). */
export function secondsToFrames(seconds: number, fps: Fps): number {
  if (!Number.isFinite(seconds)) return Number.POSITIVE_INFINITY;
  return roundHalfToEven(Math.max(0, seconds) * fps);
}

/** `seconds` snapped onto the `fps` frame grid. */
export function snapToFrame(seconds: number, fps: Fps): number {
  return secondsToFrames(seconds, fps) / fps;
}

/** The clip's length — DERIVED from its source window. */
export function clipDuration(clip: VideoClip): number {
  return clip.srcOut - clip.srcIn;
}

/** Where the clip's tail sits on the program timeline. */
export function clipTimelineEnd(clip: VideoClip): number {
  return clip.timelineStart + clipDuration(clip);
}

/** The clip's TIMELINE length in whole frames. */
export function frameSpan(clip: VideoClip, fps: Fps): number {
  return secondsToFrames(clipTimelineEnd(clip), fps) - secondsToFrames(clip.timelineStart, fps);
}

/** The clip's SOURCE length in whole frames. Equal to {@link frameSpan} — the contract. */
export function frameSourceSpan(clip: VideoClip, fps: Fps): number {
  return secondsToFrames(clip.srcOut, fps) - secondsToFrames(clip.srcIn, fps);
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

// ---------------------------------------------------------------------------
// lookup + ordering
// ---------------------------------------------------------------------------

/** Where a clip lives, or null. */
export interface ClipLocation {
  lane: VideoLane;
  clip: VideoClip;
  laneIndex: number;
  clipIndex: number;
}

/** Locate `clipId` across every lane. */
export function findClip(lanes: readonly VideoLane[], clipId: string): ClipLocation | null {
  for (let laneIndex = 0; laneIndex < lanes.length; laneIndex += 1) {
    const lane = lanes[laneIndex];
    const clipIndex = lane.clips.findIndex((c) => c.id === clipId);
    if (clipIndex >= 0) return { lane, clip: lane.clips[clipIndex], laneIndex, clipIndex };
  }
  return null;
}

/** Lanes ordered top-to-bottom by `index` (a new array; input untouched). */
export function laneRows(lanes: readonly VideoLane[]): VideoLane[] {
  return [...lanes].sort((a, b) => a.index - b.index);
}

/** Clips in timeline order (a new array). */
function orderedClips(lane: VideoLane, fps: Fps): VideoClip[] {
  return [...lane.clips].sort(
    (a, b) => secondsToFrames(a.timelineStart, fps) - secondsToFrames(b.timelineStart, fps),
  );
}

/**
 * The furthest clip tail across every lane — the timeline's LENGTH.
 *
 * Note this is the authored length INCLUDING gaps, which is what the ruler must
 * show. It is deliberately NOT the rendered length: `concat` butts the kept
 * segments together, so a rendered file is shorter by the total gap (the same
 * semantics as the shipped cutter, documented in `video_tracks.timeline_duration`).
 */
export function timelineDuration(lanes: readonly VideoLane[]): number {
  let end = 0;
  for (const lane of lanes) {
    for (const clip of lane.clips) end = Math.max(end, clipTimelineEnd(clip));
  }
  return end;
}

/**
 * The free interval `[lo, hi]` a clip may occupy without crossing a lane
 * neighbour (`hi` is +Infinity for the last clip). Null when the clip is absent.
 */
export function neighborGap(
  lane: VideoLane,
  clipId: string,
  fps: Fps,
): { lo: number; hi: number } | null {
  const ordered = orderedClips(lane, fps);
  const pos = ordered.findIndex((c) => c.id === clipId);
  if (pos < 0) return null;
  return {
    lo: pos > 0 ? clipTimelineEnd(ordered[pos - 1]) : 0,
    hi: pos + 1 < ordered.length ? ordered[pos + 1].timelineStart : Number.POSITIVE_INFINITY,
  };
}

/**
 * The first pair of clips that OVERLAP in time on this lane, as `[idA, idB]`, or
 * null. Abutting (`a.end === b.start`) is legal — it is the normal result of a
 * razor cut — so only a strict crossing counts.
 */
export function overlapIn(lane: VideoLane, fps: Fps): [string, string] | null {
  const ordered = orderedClips(lane, fps);
  for (let i = 1; i < ordered.length; i += 1) {
    const prev = ordered[i - 1];
    const next = ordered[i];
    if (secondsToFrames(next.timelineStart, fps) < secondsToFrames(clipTimelineEnd(prev), fps)) {
      return [prev.id, next.id];
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// drag previews — CLAMP into the legal range (the sidecar refuses; we stop)
// ---------------------------------------------------------------------------

/**
 * Drag one trim HANDLE to timeline time `t`.
 *
 * `edge:'start'` moves the head with the TAIL PINNED; `edge:'end'` moves the
 * tail with the HEAD PINNED. Either way the source window follows by the same
 * delta, so the frames under the handle never shift and
 * `frameSpan === frameSourceSpan` still holds.
 *
 * Clamped on three limits, all of which the sidecar would otherwise refuse:
 * the lane neighbour, the clip's own opposite edge (>= 1 frame), and — for a
 * head trim — the source's own start (you cannot trim in to frame -1).
 *
 * Returns null when the clip is unknown, or when the lane gap is too small to
 * hold even a one-frame clip (nothing legal to propose).
 */
export function trimPreview(
  lane: VideoLane,
  clipId: string,
  edge: ClipEdge,
  t: number,
  fps: Fps,
): VideoClip | null {
  const found = lane.clips.find((c) => c.id === clipId);
  if (found === undefined) return null;
  // Non-null by construction: `found` proves the clip is on this lane, which is
  // the only condition under which neighborGap returns null. Asserted rather
  // than re-checked so there is no branch here that no input could ever take.
  const gap = neighborGap(lane, clipId, fps)!;

  const startF = secondsToFrames(found.timelineStart, fps);
  const endF = secondsToFrames(clipTimelineEnd(found), fps);
  const inF = secondsToFrames(found.srcIn, fps);
  const loF = secondsToFrames(gap.lo, fps);
  const hiF = secondsToFrames(gap.hi, fps);

  if (edge === 'start') {
    // the head may travel left only as far as the neighbour OR the source head
    const minF = Math.max(loF, startF - inF);
    const maxF = endF - MIN_CLIP_FRAMES;
    if (maxF < minF) return null;
    const atF = clamp(secondsToFrames(t, fps), minF, maxF);
    return { ...found, srcIn: (inF + (atF - startF)) / fps, timelineStart: atF / fps };
  }
  const minF = startF + MIN_CLIP_FRAMES;
  if (hiF < minF) return null;
  const atF = clamp(secondsToFrames(t, fps), minF, hiF);
  return { ...found, srcOut: (inF + (atF - startF)) / fps };
}

/**
 * SLIDE a clip to timeline time `t`, PRESERVING its duration exactly.
 *
 * Deliberately not "clamp both edges independently": that silently trades
 * duration for travel when a move meets an abutting neighbour. The clip moves as
 * far as it legally can and keeps every frame. Null when the clip is unknown or
 * the gap cannot hold it.
 */
export function movePreview(
  lane: VideoLane,
  clipId: string,
  t: number,
  fps: Fps,
): VideoClip | null {
  const found = lane.clips.find((c) => c.id === clipId);
  if (found === undefined) return null;
  const gap = neighborGap(lane, clipId, fps)!; // non-null by construction (see trimPreview)
  const spanF = frameSourceSpan(found, fps);
  const loF = secondsToFrames(gap.lo, fps);
  const hiF = secondsToFrames(gap.hi, fps);
  const maxF = hiF - spanF;
  if (maxF < loF) return null;
  const atF = clamp(secondsToFrames(t, fps), loF, maxF);
  return { ...found, timelineStart: atF / fps };
}

let provisionalCounter = 0;

/**
 * A PROVISIONAL id for the right half of a client-side razor cut.
 *
 * The sidecar's `split_clip` mints the authoritative id and the caller replaces
 * its lane state from the RPC response, so this id only has to be unique within
 * the current render — it is never persisted.
 */
export function provisionalClipId(): string {
  provisionalCounter += 1;
  return `pending-${provisionalCounter}`;
}

/**
 * RAZOR: cut `clip` at timeline time `t` into two abutting halves.
 *
 * Lossless — the halves tile the original exactly. Returns null when the cut
 * would not leave at least one frame on both sides (including a cut exactly on
 * either edge), matching the sidecar's refusal rather than clamping: a razor the
 * user aimed off the clip is a mis-aim, not a gesture to snap.
 */
export function splitPreview(clip: VideoClip, t: number, fps: Fps): [VideoClip, VideoClip] | null {
  const startF = secondsToFrames(clip.timelineStart, fps);
  const endF = secondsToFrames(clipTimelineEnd(clip), fps);
  const inF = secondsToFrames(clip.srcIn, fps);
  const atF = secondsToFrames(t, fps);
  if (atF - startF < MIN_CLIP_FRAMES || endF - atF < MIN_CLIP_FRAMES) return null;
  const cutF = inF + (atF - startF);
  return [
    { ...clip, srcOut: cutF / fps },
    { ...clip, id: provisionalClipId(), srcIn: cutF / fps, timelineStart: atF / fps },
  ];
}

/**
 * Replace `clipId` with `replacements` (immutably), preserving its position in
 * the lane so a re-render shows an in-place change rather than a re-append. An
 * empty `replacements` list REMOVES it. The input reference is returned
 * unchanged when `clipId` is not found, so callers can `===`-check.
 */
export function applyClips(
  lanes: readonly VideoLane[],
  clipId: string,
  replacements: readonly VideoClip[],
): VideoLane[] {
  const at = findClip(lanes, clipId);
  if (at === null) return lanes as VideoLane[];
  return lanes.map((lane, i) =>
    i === at.laneIndex
      ? {
          ...lane,
          clips: [
            ...lane.clips.slice(0, at.clipIndex),
            ...replacements,
            ...lane.clips.slice(at.clipIndex + 1),
          ],
        }
      : lane,
  );
}

// ---------------------------------------------------------------------------
// view helpers
// ---------------------------------------------------------------------------

/** A clip's left/width as percentages of the lane, for absolute positioning. */
export function clipRectStyle(
  clip: VideoClip,
  duration: number,
): { leftPct: number; widthPct: number } {
  if (duration <= 0) return { leftPct: 0, widthPct: 0 };
  const leftPct = clamp((clip.timelineStart / duration) * 100, 0, 100);
  const rightPct = clamp((clipTimelineEnd(clip) / duration) * 100, 0, 100);
  return { leftPct, widthPct: Math.max(rightPct - leftPct, 0) };
}

// ---------------------------------------------------------------------------
// undo/redo — one linear stack over the WHOLE lane set
// ---------------------------------------------------------------------------

export interface LaneHistory {
  past: VideoLane[][];
  present: VideoLane[];
  future: VideoLane[][];
}

/** A fresh history at `initial`. */
export function createHistory(initial: VideoLane[]): LaneHistory {
  return { past: [], present: initial, future: [] };
}

/**
 * Commit `next` as the new present, dropping the oldest entry past
 * {@link MAX_HISTORY} and clearing the redo branch. A `next` that is the SAME
 * reference as the present is a no-op, so a clamped op that changed nothing
 * cannot pollute the undo stack.
 */
export function pushHistory(h: LaneHistory, next: VideoLane[]): LaneHistory {
  if (next === h.present) return h;
  const past = [...h.past, h.present];
  while (past.length > MAX_HISTORY) past.shift();
  return { past, present: next, future: [] };
}

export function canUndo(h: LaneHistory): boolean {
  return h.past.length > 0;
}

export function canRedo(h: LaneHistory): boolean {
  return h.future.length > 0;
}

/** Step back one state (no-op at the floor). */
export function undo(h: LaneHistory): LaneHistory {
  if (!canUndo(h)) return h;
  return {
    past: h.past.slice(0, -1),
    present: h.past[h.past.length - 1],
    future: [...h.future, h.present],
  };
}

/** Step forward one undone state (no-op when nothing was undone). */
export function redo(h: LaneHistory): LaneHistory {
  if (!canRedo(h)) return h;
  return {
    past: [...h.past, h.present],
    present: h.future[h.future.length - 1],
    future: h.future.slice(0, -1),
  };
}
