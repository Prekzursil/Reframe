// videoTimelineClient.ts — the typed `tracks.video.*` client for the video
// timeline editor.
//
// Every mutating call returns nothing useful on purpose: the caller RE-READS the
// lanes with `fetchLanes` afterwards. That is deliberate, not lazy. The sidecar
// is the authority on what an edit became (it snaps to the frame grid, refuses
// what it cannot represent, and may hold concurrent changes from another panel),
// so re-reading is the only way the on-screen lanes are guaranteed to equal the
// stored lanes. Patching local state from a single method's response would drift
// silently — the exact failure this editor must not have.
//
// Every response is VALIDATED before it reaches React. A malformed payload
// throws with a named reason instead of rendering `undefined` as a clip at time
// NaN.

import type { Fps, VideoClip, VideoLane } from '../lib/videoTimelineOps';
import type { MediaStudioApi } from './_api';

/** The `tracks.video.list` result: the lanes plus the timeline frame rate. */
export interface LaneState {
  lanes: VideoLane[];
  fps: Fps;
}

const FPS_CHOICES: readonly number[] = [24, 25, 30, 60];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function num(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`the sidecar returned a non-numeric ${what}`);
  }
  return value;
}

function str(value: unknown, what: string): string {
  if (typeof value !== 'string' || value === '') {
    throw new Error(`the sidecar returned an empty ${what}`);
  }
  return value;
}

/** Validate one wire clip into a {@link VideoClip}. */
export function parseClip(raw: unknown): VideoClip {
  if (!isRecord(raw)) throw new Error('the sidecar returned a clip that is not an object');
  return {
    id: str(raw.id, 'clip id'),
    path: str(raw.path, 'clip path'),
    srcIn: num(raw.srcIn, 'clip srcIn'),
    srcOut: num(raw.srcOut, 'clip srcOut'),
    timelineStart: num(raw.timelineStart, 'clip timelineStart'),
  };
}

/** Validate one wire lane into a {@link VideoLane}. */
export function parseLane(raw: unknown): VideoLane {
  if (!isRecord(raw)) throw new Error('the sidecar returned a lane that is not an object');
  const clips = Array.isArray(raw.clips) ? raw.clips : [];
  return {
    id: str(raw.id, 'lane id'),
    name: str(raw.name, 'lane name'),
    index: num(raw.index, 'lane index'),
    clips: clips.map(parseClip),
  };
}

/** Validate a `tracks.video.list` payload. */
export function parseLaneState(raw: unknown): LaneState {
  if (!isRecord(raw)) throw new Error('tracks.video.list returned no payload');
  const lanes = Array.isArray(raw.videoTracks) ? raw.videoTracks : [];
  const fps = num(raw.fps, 'fps');
  if (!FPS_CHOICES.includes(fps)) {
    throw new Error(`the sidecar returned an unsupported timeline fps: ${fps}`);
  }
  return { lanes: lanes.map(parseLane), fps: fps as Fps };
}

/** `tracks.video.list` — the authoritative lane state. */
export async function fetchLanes(api: MediaStudioApi, videoId: string): Promise<LaneState> {
  return parseLaneState(await api.rpc<unknown>('tracks.video.list', { videoId }));
}

/** `tracks.video.addLane` — a new empty lane above the existing ones. */
export async function addLane(api: MediaStudioApi, videoId: string, name?: string): Promise<void> {
  await api.rpc('tracks.video.addLane', name ? { videoId, name } : { videoId });
}

/** `tracks.video.removeLane` — drops the lane AND every clip on it. */
export async function removeLane(
  api: MediaStudioApi,
  videoId: string,
  videoTrackId: string,
): Promise<void> {
  await api.rpc('tracks.video.removeLane', { videoId, videoTrackId });
}

/** `tracks.video.trimClip` — commit a drag of one trim handle. */
export async function trimClip(
  api: MediaStudioApi,
  videoId: string,
  clipId: string,
  edge: 'start' | 'end',
  timelineTime: number,
): Promise<void> {
  await api.rpc('tracks.video.trimClip', { videoId, clipId, edge, timelineTime });
}

/** `tracks.video.splitClip` — the razor. */
export async function splitClip(
  api: MediaStudioApi,
  videoId: string,
  clipId: string,
  atTimeline: number,
): Promise<void> {
  await api.rpc('tracks.video.splitClip', { videoId, clipId, atTimeline });
}

/** `tracks.video.moveClip` — commit a slide, optionally onto another lane. */
export async function moveClip(
  api: MediaStudioApi,
  videoId: string,
  clipId: string,
  timelineStart: number,
  videoTrackId?: string,
): Promise<void> {
  await api.rpc('tracks.video.moveClip', {
    videoId,
    clipId,
    timelineStart,
    ...(videoTrackId === undefined ? {} : { videoTrackId }),
  });
}

/** `tracks.video.removeClip`. */
export async function removeClip(
  api: MediaStudioApi,
  videoId: string,
  clipId: string,
): Promise<void> {
  await api.rpc('tracks.video.removeClip', { videoId, clipId });
}

/**
 * `tracks.video.render` — a long JOB. Resolves with the jobId only; the terminal
 * `{path, segments, durationSec}` arrives later on `job.done` (see
 * `_api.waitForJobDone`).
 */
export async function startRender(api: MediaStudioApi, videoId: string): Promise<string> {
  const res = await api.rpc<unknown>('tracks.video.render', { videoId });
  if (!isRecord(res)) throw new Error('tracks.video.render returned no payload');
  return str(res.jobId, 'jobId');
}
