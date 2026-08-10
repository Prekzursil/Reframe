// VideoTimeline.test.tsx — the direct-manipulation multi-lane video editor.
//
// Strategy mirrors Timeline.test.tsx: React 18 `react-dom/client` + `act` under
// jsdom with the RPC bridge faked. No sidecar, no ffmpeg, no network.
//
// jsdom reports all-zero rects, and this component deliberately has NO virtual
// width fallback (in the packaged renderer the rect is always real), so every
// drag test SPIES the track's getBoundingClientRect with left=0/width=600 over a
// 60s timeline. That makes the mapping exact and readable: t = clientX / 10.
//
// The assertions are about the ONE rule the panel exists to enforce — what is on
// screen equals what is stored:
//   * a gesture commits the value the preview showed, in frame-snapped seconds;
//   * a gesture that changed nothing spends NO rpc and leaves no undo entry;
//   * a FAILED commit shows the error AND re-reads, so no phantom edit survives;
//   * Undo is enabled only when a real single-call inverse exists.

// @vitest-environment jsdom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';
import { MAX_UNDO, VideoTimeline } from './VideoTimeline';

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

interface WireClip {
  id: string;
  path: string;
  srcIn: number;
  srcOut: number;
  timelineStart: number;
}

function wireLane(clips: WireClip[], over: Record<string, unknown> = {}): Record<string, unknown> {
  return { id: 'vt1', name: 'Video 1', index: 0, clips, ...over };
}

/** One 60s clip filling the timeline — the state `tracks.video.list` seeds. */
const FULL: WireClip = { id: 'c1', path: 'C:/vids/a.mp4', srcIn: 0, srcOut: 60, timelineStart: 0 };
/** A clip that starts at 30s, so time 0 is OUTSIDE it (for the razor refusal). */
const LATE: WireClip = { id: 'c1', path: 'C:/vids/a.mp4', srcIn: 0, srcOut: 30, timelineStart: 30 };

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  emitProgress: (ev: ProgressEvent) => void;
  emitDone: (ev: DoneEvent) => void;
}

function makeFakeApi(
  opts: {
    lanes?: Array<Record<string, unknown>>;
    fps?: number;
    listError?: Error;
    listPayload?: unknown;
    failMethod?: string;
    renderError?: Error;
  } = {},
): FakeApi {
  const calls: FakeApi['calls'] = [];
  const progress: Array<(ev: ProgressEvent) => void> = [];
  const done: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (opts.failMethod === method) throw new Error(`${method} refused: overlap`);
      if (method === 'tracks.video.list') {
        if (opts.listError) throw opts.listError;
        if (opts.listPayload !== undefined) return opts.listPayload as T;
        return { videoTracks: opts.lanes ?? [wireLane([FULL])], fps: opts.fps ?? 30 } as T;
      }
      if (method === 'tracks.video.render') {
        if (opts.renderError) throw opts.renderError;
        return { jobId: 'job-1' } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progress.push(cb);
      return () => {
        progress.splice(progress.indexOf(cb), 1);
      };
    },
    onJobDone: (cb) => {
      done.push(cb);
      return () => {
        done.splice(done.indexOf(cb), 1);
      };
    },
  };
  return {
    api,
    calls,
    emitProgress: (ev) => {
      for (const cb of [...progress]) cb(ev);
    },
    emitDone: (ev) => {
      for (const cb of [...done]) cb(ev);
    },
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  delete (globalThis as { api?: unknown }).api;
});

async function mount(api: MediaStudioApi, onRendered?: (p: string) => void): Promise<void> {
  (globalThis as { api?: unknown }).api = api;
  await act(async () => {
    root.render(<VideoTimeline videoId="v1" onRendered={onRendered} />);
  });
}

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

const track = (): HTMLDivElement => container.querySelector('[data-role="track"]')!;
const clipEl = (id = 'c1'): HTMLElement => container.querySelector(`[data-clip-id="${id}"]`)!;
const edge = (which: 'start' | 'end', id = 'c1'): HTMLElement =>
  container.querySelector(`[data-edge="${which}"][data-clip="${id}"]`)!;
const button = (action: string): HTMLButtonElement =>
  container.querySelector(`button[data-action="${action}"]`)!;
const text = (role: string): string =>
  container.querySelector(`[data-role="${role}"]`)?.textContent ?? '';
const methods = (fake: FakeApi): string[] => fake.calls.map((c) => c.method);
const paramsOf = (fake: FakeApi, method: string): Record<string, unknown> | undefined =>
  fake.calls.filter((c) => c.method === method).at(-1)?.params;

function mouse(type: string, clientX: number): MouseEvent {
  return new MouseEvent(type, { bubbles: true, cancelable: true, clientX });
}

/** Give the track a real rect: 600px wide at left 0. Over 60s, t = clientX / 10. */
function pinRect(width = 600): void {
  vi.spyOn(track(), 'getBoundingClientRect').mockReturnValue({
    left: 0,
    width,
    top: 0,
    right: width,
    bottom: 0,
    height: 0,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect);
}

async function drag(target: HTMLElement, toClientX: number): Promise<void> {
  pinRect();
  await act(async () => {
    target.dispatchEvent(mouse('mousedown', 0));
  });
  await act(async () => {
    track().dispatchEvent(mouse('mousemove', toClientX));
  });
  await act(async () => {
    track().dispatchEvent(mouse('mouseup', toClientX));
  });
}

async function click(el: HTMLElement, clientX = 0): Promise<void> {
  await act(async () => {
    el.dispatchEvent(mouse('click', clientX));
  });
}

// ---------------------------------------------------------------------------
// load + render
// ---------------------------------------------------------------------------

describe('loading the lanes', () => {
  it('reads tracks.video.list and draws a clip per lane row', async () => {
    const fake = makeFakeApi({
      lanes: [wireLane([FULL]), wireLane([], { id: 'vt2', name: 'B-roll', index: 1 })],
    });
    await mount(fake.api);
    expect(paramsOf(fake, 'tracks.video.list')).toEqual({ videoId: 'v1' });
    expect(container.querySelectorAll('[data-lane-id]')).toHaveLength(2);
    expect(clipEl().textContent).toContain('a.mp4 0.00-60.00');
    expect(text('playhead')).toBe('0.00s / 60.00s @ 30fps');
  });

  it('orders the lanes by index, not by arrival', async () => {
    const fake = makeFakeApi({
      lanes: [
        wireLane([], { id: 'second', name: 'B', index: 1 }),
        wireLane([], { id: 'first', name: 'A', index: 0 }),
      ],
    });
    await mount(fake.api);
    const ids = [...container.querySelectorAll('[data-lane-id]')].map((el) =>
      el.getAttribute('data-lane-id'),
    );
    expect(ids).toEqual(['first', 'second']);
  });

  it('says so when there are no lanes at all', async () => {
    await mount(makeFakeApi({ lanes: [] }).api);
    expect(text('empty')).toContain('No video lanes yet');
  });

  it('surfaces a list failure instead of rendering an empty editor silently', async () => {
    await mount(makeFakeApi({ listError: new Error('sidecar down') }).api);
    expect(text('error')).toContain('sidecar down');
  });

  it('surfaces a MALFORMED payload rather than drawing a clip at NaN', async () => {
    await mount(makeFakeApi({ listPayload: { videoTracks: [{ id: 'vt1' }], fps: 30 } }).api);
    expect(text('error')).toContain('empty lane name');
    expect(container.querySelector('[data-clip-id]')).toBeNull();
  });

  it('reports the sidecar fps, not a hardcoded 30', async () => {
    await mount(makeFakeApi({ fps: 25 }).api);
    expect(text('playhead')).toContain('@ 25fps');
  });

  it('makes no call at all without a videoId', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    await act(async () => {
      root.render(<VideoTimeline videoId="" />);
    });
    expect(fake.calls).toEqual([]);
    expect(text('empty')).toContain('No video lanes yet');
  });

  it('renders a thrown non-Error as a readable message', async () => {
    const api: MediaStudioApi = {
      // a rejection that is not an Error instance (a stringly-thrown bridge fault)
      rpc: vi.fn(async () => {
        throw 'bridge exploded';
      }) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => undefined,
    };
    await mount(api);
    expect(text('error')).toBe('bridge exploded');
  });
});

// ---------------------------------------------------------------------------
// drag-to-trim
// ---------------------------------------------------------------------------

describe('drag-to-trim commits the value the preview showed', () => {
  it('dragging the END handle trims the tail and pins the head', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await drag(edge('end'), 300); // clientX 300 -> t = 30s
    expect(paramsOf(fake, 'tracks.video.trimClip')).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      edge: 'end',
      timelineTime: 30,
    });
    expect(text('status')).toBe('Trimmed');
    // ... and the lanes were RE-READ so the screen shows the stored result
    expect(methods(fake).filter((m) => m === 'tracks.video.list')).toHaveLength(2);
  });

  it('dragging the START handle trims the head', async () => {
    // srcIn 10 gives the head 10s of handle to trim into
    const fake = makeFakeApi({
      lanes: [wireLane([{ ...FULL, srcIn: 10, srcOut: 60, timelineStart: 10 }])],
    });
    await mount(fake.api);
    await drag(edge('start'), 200); // t = 20s (duration is 60: 10 + 50)
    expect(paramsOf(fake, 'tracks.video.trimClip')).toMatchObject({
      edge: 'start',
      timelineTime: 20,
    });
  });

  it('a drag that ends where it started spends NO rpc', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const before = fake.calls.length;
    await drag(edge('end'), 600); // t = 60s == the clip's existing end
    expect(fake.calls.length).toBe(before);
    expect(button('undo').disabled).toBe(true);
  });

  it('a mouseup with no drag in flight is inert', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const before = fake.calls.length;
    pinRect();
    await act(async () => {
      track().dispatchEvent(mouse('mouseup', 100));
      track().dispatchEvent(mouse('mousemove', 100));
    });
    expect(fake.calls.length).toBe(before);
  });

  it('a FAILED commit shows the error and re-reads (no phantom edit)', async () => {
    const fake = makeFakeApi({ failMethod: 'tracks.video.trimClip' });
    await mount(fake.api);
    await drag(edge('end'), 300);
    expect(text('error')).toContain('refused: overlap');
    expect(text('status')).toBe('');
    // rolled back to the STORED clip, not the previewed 30s one
    expect(clipEl().textContent).toContain('0.00-60.00');
    expect(methods(fake).filter((m) => m === 'tracks.video.list')).toHaveLength(2);
    // a failed edit must not become an undo entry
    expect(button('undo').disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// drag-to-reorder
// ---------------------------------------------------------------------------

describe('drag-to-reorder', () => {
  it('dragging the clip body slides it, preserving its duration', async () => {
    // room to move: the clip is 10s long on a 60s timeline
    const fake = makeFakeApi({
      lanes: [
        wireLane([
          { ...FULL, srcOut: 10 },
          { ...FULL, id: 'c2', srcOut: 10, timelineStart: 50 },
        ]),
      ],
    });
    await mount(fake.api);
    await drag(clipEl('c1'), 200); // t = 20s
    expect(paramsOf(fake, 'tracks.video.moveClip')).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      timelineStart: 20,
    });
    expect(text('status')).toBe('Moved');
  });

  it('a slide with no room reports nothing changed', async () => {
    const fake = makeFakeApi({
      lanes: [
        wireLane([
          { ...FULL, srcOut: 10 },
          { ...FULL, id: 'c2', srcOut: 10, timelineStart: 10 },
        ]),
      ],
    });
    await mount(fake.api);
    const before = fake.calls.length;
    await drag(clipEl('c1'), 300); // boxed in by c2 at 10s -> clamps back to 0
    expect(fake.calls.length).toBe(before);
  });

  it('a move on a lane that already overlaps proposes nothing', async () => {
    // Two clips at the SAME start — a state this panel cannot create but a
    // hand-edited manifest can. Every preview returns null, so the draft is kept
    // and the release finds no change to commit.
    const fake = makeFakeApi({
      lanes: [
        wireLane([
          { ...FULL, srcOut: 10 },
          { ...FULL, id: 'c2', srcOut: 10 },
        ]),
      ],
    });
    await mount(fake.api);
    const before = fake.calls.length;
    await drag(clipEl('c1'), 300);
    expect(fake.calls.length).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// razor
// ---------------------------------------------------------------------------

describe('the razor', () => {
  it('splits the selected clip at the playhead', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pinRect();
    await click(track(), 100); // playhead -> 10s
    expect(text('playhead')).toContain('10.00s');
    await click(clipEl());
    await click(button('split'));
    expect(paramsOf(fake, 'tracks.video.splitClip')).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      atTimeline: 10,
    });
  });

  it('refuses locally, with a reason, when the playhead is outside the clip', async () => {
    const fake = makeFakeApi({ lanes: [wireLane([LATE])] });
    await mount(fake.api);
    await click(clipEl()); // playhead is still 0; the clip starts at 30s
    await click(button('split'));
    expect(text('error')).toContain('Put the playhead inside the selected clip');
    expect(methods(fake)).not.toContain('tracks.video.splitClip');
  });

  it('is disabled until a clip is selected', async () => {
    await mount(makeFakeApi().api);
    expect(button('split').disabled).toBe(true);
    expect(button('remove-clip').disabled).toBe(true);
    await click(clipEl());
    expect(button('split').disabled).toBe(false);
  });

  it('snaps the playhead onto the frame grid', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pinRect();
    await click(track(), 101); // 10.1s -> 303 frames at 30fps -> 10.1s exactly
    expect(text('playhead')).toContain('10.10s');
    await click(track(), 7); // 0.7s -> 21 frames -> 0.70s
    expect(text('playhead')).toContain('0.70s');
  });
});

// ---------------------------------------------------------------------------
// keyboard
// ---------------------------------------------------------------------------

describe('keyboard editing', () => {
  async function key(el: HTMLElement, k: string, shiftKey = false): Promise<void> {
    await act(async () => {
      el.dispatchEvent(new KeyboardEvent('keydown', { key: k, shiftKey, bubbles: true }));
    });
  }

  it('arrow keys nudge by one frame, shift by ten', async () => {
    const fake = makeFakeApi({ lanes: [wireLane([{ ...FULL, srcOut: 10, timelineStart: 20 }])] });
    await mount(fake.api);
    await key(clipEl(), 'ArrowRight');
    expect(paramsOf(fake, 'tracks.video.moveClip')).toMatchObject({
      timelineStart: 20 + 1 / 30,
    });
    await key(clipEl(), 'ArrowLeft', true);
    expect(paramsOf(fake, 'tracks.video.moveClip')).toMatchObject({
      timelineStart: 20 - 10 / 30,
    });
  });

  it('a nudge with no room is a no-op, not a failed call', async () => {
    const fake = makeFakeApi({ lanes: [wireLane([{ ...FULL, srcOut: 10, timelineStart: 0 }])] });
    await mount(fake.api);
    const before = fake.calls.length;
    await key(clipEl(), 'ArrowLeft'); // already at 0
    expect(fake.calls.length).toBe(before);
  });

  // A head trim INWARD (to the right, discarding leading frames) is always legal;
  // it is trimming OUTWARD that srcIn=0 blocks. An earlier version of these tests
  // conflated the two and was REFUTED by the implementation — the code was right.
  it('] trims the tail to the playhead and [ trims the head INWARD', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pinRect();
    await click(track(), 300); // playhead -> 30s
    await key(clipEl(), ']');
    expect(paramsOf(fake, 'tracks.video.trimClip')).toMatchObject({
      edge: 'end',
      timelineTime: 30,
    });
    await key(clipEl(), '[');
    // srcIn is 0, but trimming the head IN (discarding the first 30s) needs no
    // handle at all, so this is a legal edit and does fire.
    expect(paramsOf(fake, 'tracks.video.trimClip')).toMatchObject({
      edge: 'start',
      timelineTime: 30,
    });
  });

  it('a head trim OUTWARD stops at the media limit', async () => {
    // srcIn 20 / srcOut 80 -> a 60s clip at 0, so t = clientX / 10 as elsewhere
    const fake = makeFakeApi({
      lanes: [wireLane([{ ...FULL, srcIn: 20, srcOut: 80, timelineStart: 0 }])],
    });
    await mount(fake.api);
    pinRect();
    await click(track(), 100); // playhead -> 10s
    await key(clipEl(), '[');
    expect(paramsOf(fake, 'tracks.video.trimClip')).toMatchObject({
      edge: 'start',
      timelineTime: 10,
    });
  });

  it('a keyboard trim proposes nothing on an already-overlapping lane', async () => {
    // Two clips at the SAME start: every preview is null, so the key is inert
    // rather than committing a value the sidecar would refuse.
    const fake = makeFakeApi({
      lanes: [
        wireLane([
          { ...FULL, srcOut: 10 },
          { ...FULL, id: 'c2', srcOut: 10 },
        ]),
      ],
    });
    await mount(fake.api);
    const before = fake.calls.length;
    await key(clipEl('c1'), ']');
    expect(fake.calls.length).toBe(before);
  });

  it('a trim to the edge the clip already has is inert', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    pinRect();
    await click(track(), 600); // playhead -> 60s == the clip's existing tail
    const before = fake.calls.length;
    await key(clipEl(), ']');
    expect(fake.calls.length).toBe(before);
  });

  it('a tail trim boxed in by the next clip clamps to one frame', async () => {
    // c1 abuts c2 at 10s, so ] toward the playhead at 0 collapses c1 to its
    // minimum rather than crossing its own head — a REAL edit, clamped.
    const fake = makeFakeApi({
      lanes: [
        wireLane([
          { ...FULL, srcOut: 10 },
          { ...FULL, id: 'c2', srcOut: 10, timelineStart: 10 },
        ]),
      ],
    });
    await mount(fake.api);
    await key(clipEl('c1'), ']'); // playhead is 0
    expect(paramsOf(fake, 'tracks.video.trimClip')).toMatchObject({ timelineTime: 1 / 30 });
  });

  it('Delete and Backspace remove the clip', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await key(clipEl(), 'Delete');
    expect(paramsOf(fake, 'tracks.video.removeClip')).toEqual({ videoId: 'v1', clipId: 'c1' });
    await key(clipEl(), 'Backspace');
    expect(methods(fake).filter((m) => m === 'tracks.video.removeClip')).toHaveLength(2);
  });

  it('ignores keys it does not own', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const before = fake.calls.length;
    await key(clipEl(), 'x');
    expect(fake.calls.length).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// lanes + toolbar
// ---------------------------------------------------------------------------

describe('lane management', () => {
  it('adds and removes lanes', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(button('add-lane'));
    expect(paramsOf(fake, 'tracks.video.addLane')).toEqual({ videoId: 'v1' });
    await click(button('remove-lane'));
    expect(paramsOf(fake, 'tracks.video.removeLane')).toEqual({
      videoId: 'v1',
      videoTrackId: 'vt1',
    });
  });

  it('removes the selected clip from the toolbar', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(clipEl());
    await click(button('remove-clip'));
    expect(paramsOf(fake, 'tracks.video.removeClip')).toEqual({ videoId: 'v1', clipId: 'c1' });
    // the selection is cleared, so the button disables itself again
    expect(button('remove-clip').disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// undo — an INVERSE-CALL stack, enabled only when a real inverse exists
// ---------------------------------------------------------------------------

describe('undo', () => {
  const twoClips = [
    wireLane([
      { ...FULL, srcOut: 10 },
      { ...FULL, id: 'c2', srcOut: 10, timelineStart: 50 },
    ]),
  ];

  it('is disabled until a reversible edit happens', async () => {
    await mount(makeFakeApi().api);
    expect(button('undo').disabled).toBe(true);
  });

  it('reverses a move by re-issuing it at the original position', async () => {
    const fake = makeFakeApi({ lanes: twoClips });
    await mount(fake.api);
    await drag(clipEl('c1'), 200); // 0s -> 20s
    expect(button('undo').disabled).toBe(false);
    await click(button('undo'));
    expect(paramsOf(fake, 'tracks.video.moveClip')).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      timelineStart: 0,
    });
    expect(text('status')).toBe('Undid: move');
    // one step only — the stack is now empty again
    expect(button('undo').disabled).toBe(true);
  });

  it('reverses a trim back to the original edge', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await drag(edge('end'), 300);
    await click(button('undo'));
    expect(paramsOf(fake, 'tracks.video.trimClip')).toEqual({
      videoId: 'v1',
      clipId: 'c1',
      edge: 'end',
      timelineTime: 60,
    });
    expect(text('status')).toBe('Undid: trim');
  });

  it('is CLEARED by an edit with no single-call inverse', async () => {
    const fake = makeFakeApi({ lanes: twoClips });
    await mount(fake.api);
    await drag(clipEl('c1'), 200);
    expect(button('undo').disabled).toBe(false);
    await click(button('add-lane')); // no inverse -> the stack is dropped
    expect(button('undo').disabled).toBe(true);
  });

  it('surfaces a failure of the inverse call itself', async () => {
    const fake = makeFakeApi({ lanes: twoClips });
    await mount(fake.api);
    await drag(clipEl('c1'), 200);
    // make the reversal fail
    (
      fake.api.rpc as unknown as { mockImplementationOnce: (f: unknown) => void }
    ).mockImplementationOnce(async () => {
      throw new Error('inverse refused');
    });
    await click(button('undo'));
    expect(text('error')).toContain('inverse refused');
  });

  it('is bounded so a long session cannot grow it forever', async () => {
    expect(MAX_UNDO).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// render (a long job)
// ---------------------------------------------------------------------------

describe('rendering the timeline', () => {
  it('starts the job, shows progress, and reports the output path', async () => {
    const fake = makeFakeApi();
    const onRendered = vi.fn();
    await mount(fake.api, onRendered);
    await click(button('render'));
    expect(paramsOf(fake, 'tracks.video.render')).toEqual({ videoId: 'v1' });
    const bar = container.querySelector('progress[data-role="render-progress"]');
    expect(bar).not.toBeNull();
    await act(async () => {
      fake.emitProgress({ jobId: 'other', pct: 99, message: 'not mine' });
      fake.emitProgress({ jobId: 'job-1', pct: 40, message: 'encoding' });
    });
    expect(text('status')).toBe('encoding');
    await act(async () => {
      fake.emitDone({ jobId: 'other', result: { path: 'wrong.mp4' } });
      fake.emitDone({ jobId: 'job-1', result: { path: 'C:/out/timeline.mp4' } });
    });
    expect(text('status')).toContain('Rendered C:/out/timeline.mp4');
    expect(onRendered).toHaveBeenCalledWith('C:/out/timeline.mp4');
    expect(container.querySelector('progress[data-role="render-progress"]')).toBeNull();
  });

  it('works without an onRendered callback', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(button('render'));
    await act(async () => {
      fake.emitDone({ jobId: 'job-1', result: { path: 'out.mp4' } });
    });
    expect(text('status')).toContain('Rendered out.mp4');
  });

  it('surfaces a refusal to START (an empty or overlapping timeline)', async () => {
    const fake = makeFakeApi({
      renderError: new Error('timeline render requires at least one clip'),
    });
    await mount(fake.api);
    await click(button('render'));
    expect(text('error')).toContain('at least one clip');
    expect(container.querySelector('progress[data-role="render-progress"]')).toBeNull();
  });

  it('surfaces a job FAILURE rather than a silent success', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(button('render'));
    await act(async () => {
      fake.emitDone({
        jobId: 'job-1',
        result: { error: { message: 'ffmpeg exit 3', type: 'RpcError' } },
      });
    });
    expect(text('error')).toContain('ffmpeg exit 3');
  });

  it('rejects a done payload with no output path', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await click(button('render'));
    await act(async () => {
      fake.emitDone({ jobId: 'job-1', result: {} });
    });
    expect(text('error')).toContain('without reporting an output file');
  });
});

// ---------------------------------------------------------------------------
// W18: putting a clip INTO a lane
// ---------------------------------------------------------------------------

// `tracks.video.addClip` is the ONLY sidecar path that can place an ARBITRARY
// clip on a lane (`sidecar/media_studio/features/video_tracks.py:294,692-716,883`).
//
// CORRECTED 2026-08-10 -- this used to say the client's omission left a mounted
// timeline working "against lanes that were permanently EMPTY". False:
// `tracks.video.list` auto-seeds lane 0 with the whole source on first contact
// (`video_tracks.py:595-612,653`), so trim/split/move/undo/render always had one
// real clip to act on. The hole was one-way editing -- a lane created by
// `addLane` could never be filled and a remove/razor could never be reversed by
// putting material back. These tests are about that one hole: the button exists,
// it sends the right window, and it refuses honestly when the source geometry it
// would send is unknown.
describe('adding the source clip to a lane (W18)', () => {
  const SOURCE = 'C:/vids/talk.mp4';

  async function mountWithSource(
    fake: FakeApi,
    props: { sourcePath?: string; sourceDurationSec?: number } = {},
  ): Promise<void> {
    (globalThis as { api?: unknown }).api = fake.api;
    await act(async () => {
      root.render(<VideoTimeline videoId="v1" {...props} />);
    });
  }

  it('appends the whole source after the last clip on THAT lane', async () => {
    // lane vt1 already holds 0..60; lane vt2 is empty. Adding to each must land
    // at that lane's own tail (60 and 0), never at the global timeline end.
    const fake = makeFakeApi({
      lanes: [wireLane([FULL]), wireLane([], { id: 'vt2', name: 'B-roll', index: 1 })],
    });
    await mountWithSource(fake, { sourcePath: SOURCE, sourceDurationSec: 12.5 });

    const add = (laneId: string): HTMLButtonElement =>
      container.querySelector(`button[data-action="add-clip"][data-lane="${laneId}"]`)!;
    expect(add('vt1').disabled).toBe(false);

    await click(add('vt1'));
    expect(paramsOf(fake, 'tracks.video.addClip')).toEqual({
      videoId: 'v1',
      videoTrackId: 'vt1',
      path: SOURCE,
      srcIn: 0,
      srcOut: 12.5,
      timelineStart: 60,
    });
    expect(text('status')).toBe('Clip added');
    // the lanes were RE-READ, so what is on screen is what the sidecar stored
    expect(methods(fake).filter((m) => m === 'tracks.video.list')).toHaveLength(2);

    await click(add('vt2'));
    expect(paramsOf(fake, 'tracks.video.addClip')).toMatchObject({
      videoTrackId: 'vt2',
      timelineStart: 0,
    });
  });

  it('cannot be undone by one call, so it CLEARS the undo stack', async () => {
    const fake = makeFakeApi();
    await mountWithSource(fake, { sourcePath: SOURCE, sourceDurationSec: 12.5 });
    // bank a real inverse first (a trim), then add -> the inverse must be gone.
    await drag(edge('end'), 300);
    expect(button('undo').disabled).toBe(false);
    await click(container.querySelector('button[data-action="add-clip"]')!);
    expect(button('undo').disabled).toBe(true);
  });

  it('surfaces a REFUSED add instead of leaving a phantom clip', async () => {
    const fake = makeFakeApi({ failMethod: 'tracks.video.addClip' });
    await mountWithSource(fake, { sourcePath: SOURCE, sourceDurationSec: 12.5 });
    await click(container.querySelector('button[data-action="add-clip"]')!);
    expect(text('error')).toContain('refused: overlap');
    expect(text('status')).toBe('');
  });

  it('is disabled with a stated reason when no source path was passed', async () => {
    const fake = makeFakeApi();
    await mountWithSource(fake);
    const add = container.querySelector('button[data-action="add-clip"]') as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    expect(add.title).toContain('source file');
    await click(add);
    expect(methods(fake)).not.toContain('tracks.video.addClip');
  });

  it('is disabled when the source duration is unknown (never sends srcOut 0)', async () => {
    const fake = makeFakeApi();
    await mountWithSource(fake, { sourcePath: SOURCE, sourceDurationSec: 0 });
    const add = container.querySelector('button[data-action="add-clip"]') as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    expect(add.title).toContain('source file');
  });
});
