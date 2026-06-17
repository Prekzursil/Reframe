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
import type { ShortInfo } from '../lib/rpc';

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
});
