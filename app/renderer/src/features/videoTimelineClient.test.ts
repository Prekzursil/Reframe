// videoTimelineClient.test.ts — the `tracks.video.*` client.
//
// Two things are worth testing here and they are both about NOT trusting the
// wire: the parameter shape each method sends (a wrong param name is a silent
// no-op the sidecar rejects), and the validation of what comes back (a malformed
// payload must throw with a named reason, never render as a clip at time NaN).

import { describe, expect, it, vi } from 'vitest';

import type { MediaStudioApi } from './_api';
import {
  addLane,
  fetchLanes,
  moveClip,
  parseClip,
  parseLane,
  parseLaneState,
  removeClip,
  removeLane,
  splitClip,
  startRender,
  trimClip,
} from './videoTimelineClient';

interface Recorded {
  method: string;
  params?: Record<string, unknown>;
}

function fakeApi(reply: unknown = {}): { api: MediaStudioApi; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      return reply as T;
    }) as MediaStudioApi['rpc'],
    onProgress: () => () => undefined,
  };
  return { api, calls };
}

const CLIP = { id: 'c1', path: 'a.mp4', srcIn: 0, srcOut: 2, timelineStart: 0 };
const LANE = { id: 'vt1', name: 'Video 1', index: 0, clips: [CLIP] };

describe('response validation fails closed', () => {
  it('accepts a well-formed payload', () => {
    const state = parseLaneState({ videoTracks: [LANE], fps: 30 });
    expect(state.fps).toBe(30);
    expect(state.lanes[0].clips[0]).toEqual(CLIP);
  });

  it('tolerates a lane with no clips array', () => {
    expect(parseLane({ id: 'vt1', name: 'V', index: 0 }).clips).toEqual([]);
  });

  it('tolerates a payload with no videoTracks array', () => {
    expect(parseLaneState({ fps: 24 }).lanes).toEqual([]);
  });

  it.each([
    ['no payload at all', null, 'no payload'],
    ['a non-object payload', 42, 'no payload'],
    ['a missing fps', { videoTracks: [] }, 'non-numeric fps'],
    ['an unsupported fps', { videoTracks: [], fps: 29.97 }, 'unsupported timeline fps'],
  ])('rejects %s', (_label, raw, message) => {
    expect(() => parseLaneState(raw)).toThrow(new RegExp(message));
  });

  it.each([
    ['a non-object clip', 'nope', 'not an object'],
    ['a missing id', { path: 'a.mp4', srcIn: 0, srcOut: 1, timelineStart: 0 }, 'empty clip id'],
    ['a missing path', { id: 'c1', srcIn: 0, srcOut: 1, timelineStart: 0 }, 'empty clip path'],
    [
      'a NaN srcIn',
      { id: 'c1', path: 'a', srcIn: Number.NaN, srcOut: 1, timelineStart: 0 },
      'clip srcIn',
    ],
    [
      'a string srcOut',
      { id: 'c1', path: 'a', srcIn: 0, srcOut: '1', timelineStart: 0 },
      'clip srcOut',
    ],
    ['a missing timelineStart', { id: 'c1', path: 'a', srcIn: 0, srcOut: 1 }, 'clip timelineStart'],
  ])('rejects %s', (_label, raw, message) => {
    expect(() => parseClip(raw)).toThrow(new RegExp(message));
  });

  it.each([
    ['a non-object lane', 7, 'not an object'],
    ['a missing lane id', { name: 'V', index: 0 }, 'empty lane id'],
    ['a missing lane name', { id: 'vt1', index: 0 }, 'empty lane name'],
    ['a missing lane index', { id: 'vt1', name: 'V' }, 'lane index'],
  ])('rejects %s', (_label, raw, message) => {
    expect(() => parseLane(raw)).toThrow(new RegExp(message));
  });
});

describe('each method sends the exact param shape the sidecar requires', () => {
  it('fetchLanes reads and validates', async () => {
    const { api, calls } = fakeApi({ videoTracks: [LANE], fps: 25 });
    const state = await fetchLanes(api, 'v1');
    expect(calls).toEqual([{ method: 'tracks.video.list', params: { videoId: 'v1' } }]);
    expect(state.fps).toBe(25);
  });

  it('addLane omits an empty name rather than sending one', async () => {
    const { api, calls } = fakeApi();
    await addLane(api, 'v1');
    await addLane(api, 'v1', 'B-roll');
    expect(calls[0].params).toEqual({ videoId: 'v1' });
    expect(calls[1].params).toEqual({ videoId: 'v1', name: 'B-roll' });
  });

  it('removeLane / removeClip / trim / split send their ids', async () => {
    const { api, calls } = fakeApi();
    await removeLane(api, 'v1', 'vt1');
    await removeClip(api, 'v1', 'c1');
    await trimClip(api, 'v1', 'c1', 'end', 4.5);
    await splitClip(api, 'v1', 'c1', 2.25);
    expect(calls.map((c) => c.method)).toEqual([
      'tracks.video.removeLane',
      'tracks.video.removeClip',
      'tracks.video.trimClip',
      'tracks.video.splitClip',
    ]);
    expect(calls[2].params).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      edge: 'end',
      timelineTime: 4.5,
    });
    expect(calls[3].params).toEqual({ videoId: 'v1', clipId: 'c1', atTimeline: 2.25 });
  });

  it('moveClip includes videoTrackId ONLY for a cross-lane move', async () => {
    const { api, calls } = fakeApi();
    await moveClip(api, 'v1', 'c1', 3);
    await moveClip(api, 'v1', 'c1', 3, 'vt2');
    // an absent key means "same lane"; sending videoTrackId:undefined would
    // reparent to a lane whose id is the string "undefined"
    expect(calls[0].params).toEqual({ videoId: 'v1', clipId: 'c1', timelineStart: 3 });
    expect(calls[1].params).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      timelineStart: 3,
      videoTrackId: 'vt2',
    });
  });

  it('startRender returns the jobId and rejects a payload without one', async () => {
    expect(await startRender(fakeApi({ jobId: 'job-7' }).api, 'v1')).toBe('job-7');
    await expect(startRender(fakeApi({}).api, 'v1')).rejects.toThrow(/empty jobId/);
    await expect(startRender(fakeApi(null).api, 'v1')).rejects.toThrow(/no payload/);
  });
});
