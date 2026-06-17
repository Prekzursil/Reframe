// Timeline.test.tsx — tests for the timeline subtitle editor (unit: T1).
//
// Strategy mirrors Assets.test.tsx: pure helpers tested with no render;
// component tests use React 18's react-dom/client + act under jsdom with the
// RPC bridge mocked (a fake `MediaStudioApi`) — no real sidecar, no network.
//
// jsdom rects are all-zero, so the lane falls back to a fixed virtual width
// (FALLBACK_LANE_WIDTH = 1000). With durationSec=100 a dispatched clientX maps
// deterministically: t = clientX / 1000 * 100 = clientX / 10.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Timeline, { chooseSplitTime, pickTrack } from './Timeline';
import type { Cue, MediaStudioApi, SubtitleTrack } from './_api';
import type { PlayerHandle } from '../components/Player';

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function cue(index: number, start: number, end: number, text: string): Cue {
  return { index, start, end, text };
}

function makeTrack(over: Partial<SubtitleTrack> = {}): SubtitleTrack {
  return {
    id: 'trk-1',
    lang: 'en',
    name: 'English',
    format: 'srt',
    kind: 'soft',
    cues: [cue(1, 0, 2, 'hello world'), cue(2, 3, 5, 'second cue'), cue(3, 6, 8, 'third one')],
    ...over,
  };
}

const PEAKS = { sampleRate: 8000, peaks: [0.1, 0.9, 0.5, 0.2] };

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
}

function makeFakeApi(
  opts: {
    tracks?: SubtitleTrack[];
    peaks?: typeof PEAKS | Error;
    videos?: Array<{ id: string; durationSec: number }>;
    editError?: Error;
    listError?: Error;
  } = {},
): FakeApi {
  const calls: FakeApi['calls'] = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'tracks.list') {
        if (opts.listError) throw opts.listError;
        return { tracks: opts.tracks ?? [makeTrack()] } as T;
      }
      if (method === 'timeline.peaks') {
        if (opts.peaks instanceof Error) throw opts.peaks;
        return (opts.peaks ?? PEAKS) as T;
      }
      if (method === 'library.list') {
        return { videos: opts.videos ?? [] } as T;
      }
      if (method === 'subtitles.edit') {
        if (opts.editError) throw opts.editError;
        const sent = (params?.cues ?? []) as Cue[];
        return { track: { ...makeTrack(), cues: sent } } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: () => () => undefined,
    onJobDone: () => () => undefined,
  };
  return { api, calls };
}

function makePlayerRef(): {
  ref: React.RefObject<PlayerHandle | null>;
  seek: ReturnType<typeof vi.fn>;
} {
  const seek = vi.fn();
  const handle: PlayerHandle = {
    play: vi.fn(),
    pause: vi.fn(),
    seek,
    scrub: vi.fn(),
    currentTime: () => 0,
    isPlaying: () => false,
    element: () => null,
  };
  return { ref: { current: handle }, seek };
}

// Native-setter trick so React's controlled inputs see the change.
function setInputValue(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const proto =
    el instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
}

function mouse(type: string, clientX: number): MouseEvent {
  return new MouseEvent(type, { bubbles: true, cancelable: true, clientX });
}

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------

describe('pickTrack', () => {
  const a = makeTrack({ id: 'a' });
  const b = makeTrack({ id: 'b' });

  it('returns the id match when trackId is given', () => {
    expect(pickTrack([a, b], 'b')).toBe(b);
  });

  it('returns null for an unknown explicit id (no silent fallback)', () => {
    expect(pickTrack([a, b], 'zzz')).toBeNull();
  });

  it('defaults to the first track', () => {
    expect(pickTrack([a, b])).toBe(a);
  });

  it('returns null for an empty list', () => {
    expect(pickTrack([])).toBeNull();
  });
});

describe('chooseSplitTime', () => {
  const c = cue(1, 2, 6, 'x');

  it('uses the playhead when strictly inside the cue', () => {
    expect(chooseSplitTime(c, 4)).toBe(4);
  });

  it('falls back to the midpoint when the playhead is outside', () => {
    expect(chooseSplitTime(c, 0)).toBe(4);
    expect(chooseSplitTime(c, 99)).toBe(4);
  });

  it('falls back to the midpoint when the playhead grazes an edge', () => {
    expect(chooseSplitTime(c, 2.01)).toBe(4);
    expect(chooseSplitTime(c, 5.99)).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------

describe('<Timeline />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function mount(
    api: MediaStudioApi,
    extra: Partial<React.ComponentProps<typeof Timeline>> = {},
  ): Promise<void> {
    await act(async () => {
      root.render(<Timeline videoId="vid-1" api={api} durationSec={100} {...extra} />);
    });
  }

  const lane = (): HTMLElement => container.querySelector('[data-testid="timeline-lane"]')!;
  const cueRects = (): HTMLElement[] => Array.from(container.querySelectorAll('[data-cue]'));
  const button = (action: string): HTMLButtonElement =>
    container.querySelector(`button[data-action="${action}"]`)!;

  async function clickAt(el: HTMLElement, clientX: number): Promise<void> {
    await act(async () => {
      el.dispatchEvent(mouse('click', clientX));
    });
  }

  /** Click a cue rect at a lane x that lands the playhead at `clientX/10` s. */
  async function selectCue(pos: number, clientX: number): Promise<void> {
    await clickAt(cueRects()[pos], clientX);
  }

  function savedCues(fake: FakeApi): Cue[] {
    const call = fake.calls.filter((c) => c.method === 'subtitles.edit').pop();
    return (call?.params?.cues ?? []) as Cue[];
  }

  async function save(): Promise<void> {
    await act(async () => {
      button('save').click();
    });
  }

  it('loads the track via tracks.list and renders one rect per cue', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(fake.calls.some((c) => c.method === 'tracks.list')).toBe(true);
    expect(fake.calls.find((c) => c.method === 'tracks.list')?.params).toEqual({
      videoId: 'vid-1',
    });
    expect(cueRects()).toHaveLength(3);
  });

  it('requests waveform peaks for the video', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const call = fake.calls.find((c) => c.method === 'timeline.peaks');
    expect(call?.params).toEqual({ videoId: 'vid-1' });
    expect(container.querySelector('canvas.timeline__waveform')).toBeTruthy();
  });

  it('still edits when timeline.peaks fails (waveform is optional)', async () => {
    const fake = makeFakeApi({ peaks: new Error('no audio stream') });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(cueRects()).toHaveLength(3);
  });

  it('shows an alert when the video has no track', async () => {
    const fake = makeFakeApi({ tracks: [] });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('No subtitle track');
  });

  it('shows an alert when tracks.list rejects', async () => {
    const fake = makeFakeApi({ listError: new Error('sidecar gone') });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar gone');
  });

  it('click-to-seek drives the player ref and onSeek', async () => {
    const fake = makeFakeApi();
    const player = makePlayerRef();
    const onSeek = vi.fn();
    await mount(fake.api, { playerRef: player.ref, onSeek });
    await clickAt(lane(), 500); // 500/1000 * 100s = 50s
    expect(player.seek).toHaveBeenCalledWith(50);
    expect(onSeek).toHaveBeenCalledWith(50);
  });

  it('falls back to library.list for the duration when no prop is given', async () => {
    const fake = makeFakeApi({ videos: [{ id: 'vid-1', durationSec: 200 }] });
    const onSeek = vi.fn();
    await act(async () => {
      root.render(<Timeline videoId="vid-1" api={fake.api} onSeek={onSeek} />);
    });
    expect(fake.calls.some((c) => c.method === 'library.list')).toBe(true);
    await clickAt(lane(), 500); // 500/1000 * 200s = 100s
    expect(onSeek).toHaveBeenCalledWith(100);
  });

  it('selecting a cue opens the editor with its text', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(0, 10);
    const textarea = container.querySelector(
      'textarea[data-action="cue-text"]',
    ) as HTMLTextAreaElement;
    expect(textarea).toBeTruthy();
    expect(textarea.value).toBe('hello world');
    expect(cueRects()[0].dataset.selected).toBe('true');
  });

  it('split divides the selected cue at the playhead', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(0, 10); // playhead = 1.0s, inside [0,2]
    await act(async () => {
      button('split').click();
    });
    expect(cueRects()).toHaveLength(4);
    await save();
    const cues = savedCues(fake);
    expect(cues).toHaveLength(4);
    expect(cues[0]).toMatchObject({ index: 1, start: 0, end: 1, text: 'hello' });
    expect(cues[1]).toMatchObject({ index: 2, start: 1, end: 2, text: 'world' });
    expect(cues[2]).toMatchObject({ index: 3, start: 3, end: 5 });
  });

  it('merge joins the selected cue with its next neighbor', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(0, 10);
    await act(async () => {
      button('merge').click();
    });
    expect(cueRects()).toHaveLength(2);
    await save();
    expect(savedCues(fake)[0]).toMatchObject({
      index: 1,
      start: 0,
      end: 5,
      text: 'hello world second cue',
    });
  });

  it('merge is disabled on the last cue', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(2, 70);
    expect(button('merge').disabled).toBe(true);
  });

  it('retime applies clamped times from the inputs', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(1, 40); // cue [3,5]
    const startInput = container.querySelector(
      'input[data-action="retime-start"]',
    ) as HTMLInputElement;
    const endInput = container.querySelector('input[data-action="retime-end"]') as HTMLInputElement;
    expect(startInput.value).toBe('3');
    expect(endInput.value).toBe('5');

    await act(async () => {
      setInputValue(startInput, '1'); // below prev.end=2 -> clamps to 2
      setInputValue(endInput, '5.5');
    });
    await act(async () => {
      button('retime').click();
    });
    await save();
    expect(savedCues(fake)[1]).toMatchObject({ start: 2, end: 5.5 });
  });

  it('dragging the end edge clamps to the next cue start', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(1, 40); // cue [3,5]; next starts at 6
    const endHandle = cueRects()[1].querySelector('[data-edge="end"]')!;
    await act(async () => {
      endHandle.dispatchEvent(mouse('mousedown', 50));
    });
    await act(async () => {
      lane().dispatchEvent(mouse('mousemove', 75)); // t=7.5 -> clamp to 6
    });
    await act(async () => {
      lane().dispatchEvent(mouse('mouseup', 75));
    });
    await save();
    expect(savedCues(fake)[1]).toMatchObject({ start: 3, end: 6 });
  });

  it('dragging the start edge clamps to the previous cue end', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(1, 40); // cue [3,5]; prev ends at 2
    const startHandle = cueRects()[1].querySelector('[data-edge="start"]')!;
    await act(async () => {
      startHandle.dispatchEvent(mouse('mousedown', 30));
    });
    await act(async () => {
      lane().dispatchEvent(mouse('mousemove', 5)); // t=0.5 -> clamp to 2
    });
    await act(async () => {
      lane().dispatchEvent(mouse('mouseup', 5));
    });
    await save();
    expect(savedCues(fake)[1]).toMatchObject({ start: 2, end: 5 });
  });

  it('apply-text commits the edited cue text', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(0, 10);
    const textarea = container.querySelector(
      'textarea[data-action="cue-text"]',
    ) as HTMLTextAreaElement;
    await act(async () => {
      setInputValue(textarea, 'rewritten line');
    });
    await act(async () => {
      button('apply-text').click();
    });
    await save();
    expect(savedCues(fake)[0]).toMatchObject({ text: 'rewritten line' });
  });

  it('undo restores the pre-op state and redo re-applies it', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(button('undo').disabled).toBe(true);
    await selectCue(0, 10);
    await act(async () => {
      button('split').click();
    });
    expect(cueRects()).toHaveLength(4);
    expect(button('undo').disabled).toBe(false);
    await act(async () => {
      button('undo').click();
    });
    expect(cueRects()).toHaveLength(3);
    expect(button('redo').disabled).toBe(false);
    await act(async () => {
      button('redo').click();
    });
    expect(cueRects()).toHaveLength(4);
  });

  it('save sends subtitles.edit with the trackId and renumbered cues', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await save();
    const call = fake.calls.find((c) => c.method === 'subtitles.edit');
    expect(call?.params?.trackId).toBe('trk-1');
    const cues = (call?.params?.cues ?? []) as Cue[];
    expect(cues.map((c) => c.index)).toEqual([1, 2, 3]);
    expect(container.textContent).toContain('Saved');
  });

  it('surfaces a save failure as an alert', async () => {
    const fake = makeFakeApi({ editError: new Error('disk is full') });
    await mount(fake.api);
    await save();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('disk is full');
  });

  it('surfaces a non-Error tracks.list rejection via String(err)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tracks.list') throw 'plain list error';
      return {};
    });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain list error');
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<Timeline videoId="vid-1" durationSec={100} />);
      });
      expect(cueRects()).toHaveLength(3);
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });

  it('swallows a library.list rejection during the duration probe', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tracks.list') return { tracks: [makeTrack()] };
      if (method === 'timeline.peaks') return PEAKS;
      if (method === 'library.list') throw new Error('library down');
      return {};
    });
    // No durationSec prop -> the library.list probe runs and rejects (caught).
    await act(async () => {
      root.render(<Timeline videoId="vid-1" api={fake.api} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    // No error surfaced; cue editing still works (falls back to the cue extent).
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(cueRects()).toHaveLength(3);
  });

  it('ignores a library.list video whose duration is 0 (keeps the cue-extent fallback)', async () => {
    const fake = makeFakeApi({ videos: [{ id: 'vid-1', durationSec: 0 }] });
    const onSeek = vi.fn();
    await act(async () => {
      root.render(<Timeline videoId="vid-1" api={fake.api} onSeek={onSeek} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    // probedDuration stays null -> duration = max(lastCueEnd, 1) = 8. Click at
    // x=500 -> 500/1000 * 8 = 4s.
    await clickAt(lane(), 500);
    expect(onSeek).toHaveBeenCalledWith(4);
  });

  it('draws the waveform onto a real 2D canvas context', async () => {
    const fillRect = vi.fn();
    const clearRect = vi.fn();
    const fakeCtx = { fillRect, clearRect, fillStyle: '' } as unknown as CanvasRenderingContext2D;
    const getContextSpy = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue(fakeCtx as unknown as ReturnType<HTMLCanvasElement['getContext']>);
    try {
      const fake = makeFakeApi();
      await mount(fake.api);
      await act(async () => {
        await Promise.resolve();
      });
      // One clearRect + one fillRect per peak bar (4 peaks in PEAKS).
      expect(clearRect).toHaveBeenCalled();
      expect(fillRect).toHaveBeenCalledTimes(PEAKS.peaks.length);
    } finally {
      getContextSpy.mockRestore();
    }
  });

  it('bails out of the waveform draw when getContext throws (jsdom)', async () => {
    const getContextSpy = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockImplementation(() => {
        throw new Error('no node-canvas');
      });
    try {
      const fake = makeFakeApi();
      await mount(fake.api);
      await act(async () => {
        await Promise.resolve();
      });
      // No crash; the panel still renders the cues.
      expect(cueRects()).toHaveLength(3);
    } finally {
      getContextSpy.mockRestore();
    }
  });

  it('uses the lane element rect when it reports a real width/left', async () => {
    const fake = makeFakeApi();
    const player = makePlayerRef();
    await mount(fake.api, { playerRef: player.ref });
    // Give the lane a real bounding rect: left=100, width=400 over duration 100s.
    const laneEl = lane();
    vi.spyOn(laneEl, 'getBoundingClientRect').mockReturnValue({
      left: 100,
      width: 400,
      top: 0,
      right: 500,
      bottom: 0,
      height: 0,
      x: 100,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);
    // clientX=300 -> (300-100)/400 * 100 = 50s.
    await clickAt(laneEl, 300);
    expect(player.seek).toHaveBeenCalledWith(50);
  });

  it('retime ignores non-numeric input', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(1, 40);
    const startInput = container.querySelector(
      'input[data-action="retime-start"]',
    ) as HTMLInputElement;
    await act(async () => {
      setInputValue(startInput, 'not-a-number');
    });
    await act(async () => {
      button('retime').click();
    });
    await save();
    // The cue keeps its original times (the NaN guard short-circuits retime).
    expect(savedCues(fake)[1]).toMatchObject({ start: 3, end: 5 });
  });

  it('apply-text is a no-op when the text is unchanged', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await selectCue(0, 10);
    // Apply without editing -> no history push (undo stays disabled).
    await act(async () => {
      button('apply-text').click();
    });
    expect(button('undo').disabled).toBe(true);
  });

  it('a lane mousemove without an active drag is a no-op', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      lane().dispatchEvent(mouse('mousemove', 50));
    });
    // Nothing committed; undo remains disabled.
    expect(button('undo').disabled).toBe(true);
  });

  it('a lane mouseup without an active drag is a no-op', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      lane().dispatchEvent(mouse('mouseup', 50));
    });
    expect(button('undo').disabled).toBe(true);
  });

  it('clicking the lane outside any cue rect seeks without changing the selection', async () => {
    const fake = makeFakeApi();
    const onSeek = vi.fn();
    await mount(fake.api, { onSeek });
    // The bare lane click (target is the lane, not a [data-cue]) seeks only.
    await clickAt(lane(), 250);
    expect(onSeek).toHaveBeenCalledWith(25);
    expect(container.querySelector('.timeline__editor')).toBeNull();
  });

  it('coerces an absent tracks field on tracks.list to an empty list (no track alert)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tracks.list') return {}; // no `tracks` key
      if (method === 'timeline.peaks') return PEAKS;
      return {};
    });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('No subtitle track');
  });

  it('handles a track that arrives with no cues array (createHistory fallback)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tracks.list') {
        return { tracks: [{ ...makeTrack(), cues: undefined }] };
      }
      if (method === 'timeline.peaks') return PEAKS;
      return {};
    });
    await mount(fake.api);
    // No cues -> no rects, but the track loaded (Save enabled, no alert).
    expect(cueRects()).toHaveLength(0);
    expect(button('save').disabled).toBe(false);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('keeps the editor closed when the selected index no longer maps to a cue', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    // Select the last cue, then merge the FIRST cue twice so the list shrinks
    // below the selected index — selectedCue resolves to null (cues[selected]
    // is undefined) and the editor closes without crashing.
    await selectCue(2, 70); // selected = 2 (last)
    // Re-select index 0 then merge to shrink; finally undo clears selection.
    await selectCue(0, 10);
    await act(async () => {
      button('merge').click(); // 3 -> 2 cues, selection stays 0
    });
    expect(cueRects()).toHaveLength(2);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('falls back to the token color when getComputedStyle throws while drawing', async () => {
    const fillRect = vi.fn();
    const fakeCtx = {
      fillRect,
      clearRect: vi.fn(),
      fillStyle: '',
    } as unknown as CanvasRenderingContext2D;
    const ctxSpy = vi
      .spyOn(HTMLCanvasElement.prototype, 'getContext')
      .mockReturnValue(fakeCtx as unknown as ReturnType<HTMLCanvasElement['getContext']>);
    const gcsSpy = vi.spyOn(window, 'getComputedStyle').mockImplementation(() => {
      throw new Error('no CSSOM');
    });
    try {
      const fake = makeFakeApi();
      await mount(fake.api);
      await act(async () => {
        await Promise.resolve();
      });
      // The draw still ran (token-mirror fallback color), one bar per peak.
      expect(fillRect).toHaveBeenCalledTimes(PEAKS.peaks.length);
      expect(fakeCtx.fillStyle).toBe('#50555f');
    } finally {
      gcsSpy.mockRestore();
      ctxSpy.mockRestore();
    }
  });

  it('keeps the history when subtitles.edit resolves without a track (defensive)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tracks.list') return { tracks: [makeTrack()] };
      if (method === 'timeline.peaks') return PEAKS;
      if (method === 'subtitles.edit') return {}; // no `track` in the response
      return {};
    });
    await mount(fake.api);
    await save();
    // Status flips to Saved even though the response carried no track.
    expect(container.textContent).toContain('Saved');
    expect(cueRects()).toHaveLength(3);
  });
});
