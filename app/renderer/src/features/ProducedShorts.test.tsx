// ProducedShorts.test.tsx — behavioral tests for the per-video produced-shorts
// gallery (presentational). Mounts directly (real Player + ShortClipActions
// under jsdom) and covers: the empty-list null render, the card grid (title
// fallbacks, virality + template chips), inline-play swap (thumb button -> the
// inline <video> Player), and every card-action callback.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ProducedShorts } from './ProducedShorts';
import type { BestFrame, DoneEvent, ProgressEvent, ShortInfo } from '../lib/rpc';

/** A controllable `window.api` stub: drives the job done/progress channels. */
interface ApiStub {
  rpc: ReturnType<typeof vi.fn>;
  onProgress: ReturnType<typeof vi.fn>;
  onJobDone: ReturnType<typeof vi.fn>;
  /** Fire the `job.done` notification the component subscribed to. */
  fireDone: (ev: DoneEvent) => void;
  /** Fire a `job.progress` notification. */
  fireProgress: (ev: ProgressEvent) => void;
  /** True once the component unsubscribed from `job.done`. */
  doneUnsubscribed: () => boolean;
}

function installApi(over: { rpc?: ReturnType<typeof vi.fn> } = {}): ApiStub {
  const doneCbs = new Set<(ev: DoneEvent) => void>();
  const progressCbs = new Set<(ev: ProgressEvent) => void>();
  const rpc = over.rpc ?? vi.fn(async () => ({ jobId: 'job-1' }));
  const onJobDone = vi.fn((cb: (ev: DoneEvent) => void) => {
    doneCbs.add(cb);
    return () => doneCbs.delete(cb);
  });
  const onProgress = vi.fn((cb: (ev: ProgressEvent) => void) => {
    progressCbs.add(cb);
    return () => progressCbs.delete(cb);
  });
  const api = { rpc, onProgress, onJobDone };
  (globalThis as unknown as { api?: unknown }).api = api;
  return {
    rpc,
    onProgress,
    onJobDone,
    fireDone: (ev) => act(() => doneCbs.forEach((cb) => cb(ev))),
    fireProgress: (ev) => act(() => progressCbs.forEach((cb) => cb(ev))),
    doneUnsubscribed: () => doneCbs.size === 0,
  };
}

function bestFrame(over: Partial<BestFrame> = {}): BestFrame {
  return {
    frameTimeSec: 7,
    thumbnailPath: '/out/clip-1.thumb.jpg',
    score: 0.91,
    degraded: false,
    ...over,
  };
}

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn(() => Promise.resolve()),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  });
});

function short(over: Partial<ShortInfo> = {}): ShortInfo {
  return {
    id: 'sid-1',
    path: '/out/clip-1.mp4',
    videoId: 'v1',
    sourceTitle: 'My talk',
    template: 'hormozi',
    viralityPct: 73,
    durationSec: 30,
    width: 1080,
    height: 1920,
    createdAt: 1700000000,
    thumbnailPath: '',
    hook: 'A hook',
    ...over,
  };
}

describe('<ProducedShorts />', () => {
  let container: HTMLDivElement;
  let root: Root;
  let s: {
    onPlay: ReturnType<typeof vi.fn>;
    onOpenFolder: ReturnType<typeof vi.fn>;
    onReexport: ReturnType<typeof vi.fn>;
    onDelete: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    s = { onPlay: vi.fn(), onOpenFolder: vi.fn(), onReexport: vi.fn(), onDelete: vi.fn() };
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete (globalThis as unknown as { api?: unknown }).api;
  });

  function mount(shorts: ShortInfo[], playingShortPath = '') {
    act(() => {
      root.render(
        <ProducedShorts
          shorts={shorts}
          playingShortPath={playingShortPath}
          onPlay={s.onPlay}
          onOpenFolder={s.onOpenFolder}
          onReexport={s.onReexport}
          onDelete={s.onDelete}
        />,
      );
    });
  }

  it('renders nothing for an empty list', () => {
    mount([]);
    expect(container.querySelector('.sm-video-shorts')).toBeNull();
  });

  it('renders a card per short with virality + template chips', () => {
    mount([short(), short({ id: 'sid-2', path: '/out/clip-2.mp4' })]);
    const cards = container.querySelectorAll('.shorts__card');
    expect(cards.length).toBe(2);
    expect(container.querySelector('.shorts__virality')?.textContent).toContain('73');
    expect(container.querySelector('.shorts__template')?.textContent).toBe('hormozi');
  });

  it('omits the virality + template chips when those fields are absent', () => {
    mount([short({ viralityPct: null, template: '' })]);
    expect(container.querySelector('.shorts__virality')).toBeNull();
    expect(container.querySelector('.shorts__template')).toBeNull();
  });

  it('falls back from sourceTitle to hook to path for the thumb label', () => {
    mount([short({ sourceTitle: '', hook: 'Hook only' })]);
    expect(container.querySelector('[aria-label="Play preview of Hook only"]')).toBeTruthy();
    mount([short({ sourceTitle: '', hook: '' })]);
    expect(container.querySelector('[aria-label="Play preview of /out/clip-1.mp4"]')).toBeTruthy();
  });

  it('clicking the thumb preview button fires onPlay with the path', () => {
    mount([short()]);
    const thumb = container.querySelector('.shorts__thumb-btn') as HTMLButtonElement;
    act(() => thumb.click());
    expect(s.onPlay).toHaveBeenCalledWith('/out/clip-1.mp4');
  });

  it('swaps the thumb button for an inline <video> Player when this clip is playing', () => {
    mount([short()], '/out/clip-1.mp4');
    expect(container.querySelector('.shorts__thumb-btn')).toBeNull();
    expect(container.querySelector('.shorts__player')).toBeTruthy();
    expect(container.querySelector('video')).toBeTruthy();
  });

  it('forwards each action-row button to its callback', () => {
    mount([short()]);
    const click = (label: string) =>
      act(() => (container.querySelector(`[aria-label="${label}"]`) as HTMLButtonElement).click());
    click('Open folder for My talk');
    expect(s.onOpenFolder).toHaveBeenCalledWith('/out/clip-1.mp4');
    click('Re-export My talk');
    expect(s.onReexport).toHaveBeenCalledWith('/out/clip-1.mp4');
    click('Delete My talk');
    expect(s.onDelete).toHaveBeenCalledWith('/out/clip-1.mp4');
    click('Play My talk');
    expect(s.onPlay).toHaveBeenCalledWith('/out/clip-1.mp4');
  });

  // ---- WU-C4: "Pick best frame" action + thumbnail swap -------------------

  const pickBtn = (title = 'My talk') =>
    container.querySelector(
      `[aria-label="Pick the best thumbnail frame for ${title}"]`,
    ) as HTMLButtonElement;

  it('renders a per-clip "Pick best frame" button with the title in its name (AC a)', () => {
    installApi();
    mount([short()]);
    expect(pickBtn()).toBeTruthy();
    expect(pickBtn().type).toBe('button');
    // Falls back through the same title chain as the play control.
    mount([short({ sourceTitle: '', hook: 'Hook only' })]);
    expect(pickBtn('Hook only')).toBeTruthy();
  });

  it('marks the button aria-busy + disabled while the job runs (AC running)', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    expect(pickBtn().getAttribute('aria-busy')).toBe('true');
    expect(pickBtn().disabled).toBe(true);
    expect(api.rpc).toHaveBeenCalledWith('thumbnail.select', { path: '/out/clip-1.mp4' });
  });

  it('announces progress in a polite live region while running', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    api.fireProgress({ jobId: 'job-1', pct: 42, message: 'Scoring frames…' });
    const live = container.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain('Scoring frames…');
  });

  it('swaps the thumbnail img src+alt and announces the new frame time on done (AC b)', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    api.fireDone({ jobId: 'job-1', result: bestFrame({ frameTimeSec: 7 }) });
    const img = container.querySelector('.shorts__thumb-img') as HTMLImageElement;
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toContain(encodeURIComponent('short:/out/clip-1.thumb.jpg'));
    expect(img.alt).toContain('0:07');
    const live = container.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain('Thumbnail updated to the frame at 0:07');
    // Job complete -> control re-enabled and unsubscribed.
    expect(pickBtn().getAttribute('aria-busy')).toBe('false');
    expect(api.doneUnsubscribed()).toBe(true);
  });

  it('renders the visible + announced midpoint note on a degraded done (AC c)', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    api.fireDone({ jobId: 'job-1', result: bestFrame({ degraded: true, score: 0 }) });
    const note = container.querySelector('.shorts__degrade-note');
    expect(note?.textContent).toContain('No vision model available — used the middle frame');
    const live = container.querySelector('[aria-live="polite"]');
    expect(live?.textContent).toContain('No vision model available — used the middle frame');
    // Still a real swap (img updated), just flagged as degraded.
    const img = container.querySelector('.shorts__thumb-img') as HTMLImageElement;
    expect(img.getAttribute('src')).toContain(encodeURIComponent('short:/out/clip-1.thumb.jpg'));
  });

  it('surfaces a role="alert" when the job fails (AC error)', async () => {
    const rpc = vi.fn(async () => {
      throw new Error('vision backend exploded');
    });
    installApi({ rpc });
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('vision backend exploded');
    // Failure re-enables the control.
    expect(pickBtn().getAttribute('aria-busy')).toBe('false');
  });

  it('reports a non-Error rejection as a string', async () => {
    const rpc = vi.fn(async () => {
      throw 'plain string failure';
    });
    installApi({ rpc });
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'plain string failure',
    );
  });

  it('ignores progress/done notifications for a different jobId', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    api.fireProgress({ jobId: 'other', pct: 99, message: 'not mine' });
    api.fireDone({ jobId: 'other', result: bestFrame() });
    // Still running: no swap, no note, button stays busy.
    expect(container.querySelector('.shorts__thumb-img')).toBeNull();
    expect(pickBtn().getAttribute('aria-busy')).toBe('true');
  });

  it('renders an existing poster thumbnail before any pick, then swaps on done', async () => {
    const api = installApi();
    mount([short({ thumbnailPath: '/out/clip-1.thumb.jpg' })]);
    const img0 = container.querySelector('.shorts__thumb-img') as HTMLImageElement;
    expect(img0.getAttribute('src')).toContain(encodeURIComponent('short:/out/clip-1.thumb.jpg'));
    await act(async () => {
      pickBtn().click();
    });
    api.fireDone({ jobId: 'job-1', result: bestFrame({ thumbnailPath: '/out/clip-1.thumb.jpg' }) });
    const img1 = container.querySelector('.shorts__thumb-img') as HTMLImageElement;
    expect(img1.alt).toContain('0:07');
  });

  it('does nothing when the rpc returns no jobId (no subscription)', async () => {
    const rpc = vi.fn(async () => ({}));
    const api = installApi({ rpc });
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    // No jobId -> we never subscribed to done; control returns to idle.
    expect(api.onJobDone).not.toHaveBeenCalled();
    expect(pickBtn().getAttribute('aria-busy')).toBe('false');
  });

  it('fails loud (role="alert") on a malformed done payload (AC b guard)', async () => {
    const api = installApi();
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    // Missing frameTimeSec/thumbnailPath -> unreadable result.
    api.fireDone({ jobId: 'job-1', result: { score: 1 } });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('unreadable result');
    expect(container.querySelector('.shorts__thumb-img')).toBeNull();
    expect(api.doneUnsubscribed()).toBe(true);
  });

  it('stays running when the bridge exposes no onJobDone channel', async () => {
    // A preload without the deferred-job hook: the job can't complete client-side.
    const rpc = vi.fn(async () => ({ jobId: 'job-1' }));
    (globalThis as unknown as { api?: unknown }).api = {
      rpc,
      onProgress: vi.fn(() => () => undefined),
      // onJobDone intentionally absent.
    };
    mount([short()]);
    await act(async () => {
      pickBtn().click();
    });
    expect(pickBtn().getAttribute('aria-busy')).toBe('true');
    expect(container.querySelector('.shorts__thumb-img')).toBeNull();
  });
});
