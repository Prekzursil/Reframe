// App.test.tsx — the renderer route switch (P4 §6 / C11).
//
// Verifies the 3-way route switch (library / workspace / shorts), the header
// nav controls, and that Re-export from the Shorts gallery resolves the source
// video and lands on its Workspace. The heavy child views are stubbed so the
// test exercises ONLY App's routing (the views own their own tests).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { Video, ShortReexportHint } from './lib/rpc';

// ---- mocks -----------------------------------------------------------------
// rpc/client come from lib/rpc; stub them so settings.get + library.list are
// controllable and no real bridge is needed.
const rpcMock = vi.fn();
const libraryListMock = vi.fn();

vi.mock('./lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => true,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
  },
}));

// Stub the three views: each renders a marker + exposes the callbacks App wires.
const openVideoSpy = vi.fn();
const reexportSpy = vi.fn();

vi.mock('./views/Library', () => ({
  Library: ({ onOpen }: { onOpen: (v: Video) => void }) => {
    openVideoSpy.mockImplementation(onOpen);
    return (
      <div data-testid="library">
        <button type="button" onClick={() => onOpen(makeVideo())}>
          open-video
        </button>
      </div>
    );
  },
}));

vi.mock('./views/Workspace', () => ({
  Workspace: ({ video, onBack }: { video: Video; onBack: () => void }) => (
    <div data-testid="workspace" data-video-id={video.id}>
      <button type="button" onClick={onBack}>
        back
      </button>
    </div>
  ),
}));

vi.mock('./views/Shorts', () => ({
  Shorts: ({ onReexport }: { onReexport?: (h: ShortReexportHint) => void }) => {
    if (onReexport) reexportSpy.mockImplementation(onReexport);
    return (
      <div data-testid="shorts">
        <button
          type="button"
          onClick={() =>
            onReexport?.({
              videoId: 'v1',
              candidate: { hook: 'h', template: 'neon', viralityPct: 70, durationSec: 30 },
            })
          }
        >
          reexport
        </button>
      </div>
    );
  },
}));

// Stub the always-mounted chrome so the test focuses on routing.
vi.mock('./components/JobQueue', () => ({ JobQueue: () => <div /> }));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));

import { App } from './App';

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/movies/talk.mp4',
    title: 'Talk',
    addedAt: '2026-06-11T00:00:00Z',
    durationSec: 600,
    hasTranscript: false,
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({}); // settings.get / settings.set
  libraryListMock.mockReset();
  openVideoSpy.mockReset();
  reexportSpy.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function nav(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.app__nav-btn'));
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`nav button "${label}" not found`);
  return found;
}

describe('App route switch', () => {
  it('mounts the Library by default', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="shorts"]')).toBeNull();
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
  });

  it('navigates to the Shorts gallery via the header nav', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();

    await act(async () => {
      nav('Shorts').click();
    });
    await flush();

    expect(container.querySelector('[data-testid="shorts"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="library"]')).toBeNull();
    // the Shorts nav button is marked active.
    expect(nav('Shorts').classList.contains('is-active')).toBe(true);
  });

  it('opens a video into the Workspace and back via nav', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="library"] button',
    );
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    const ws = container.querySelector('[data-testid="workspace"]');
    expect(ws).not.toBeNull();
    expect(ws!.getAttribute('data-video-id')).toBe('v1');

    // The Library nav returns home.
    await act(async () => {
      nav('Library').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
  });

  it('Re-export from Shorts resolves the source video and lands on its Workspace', async () => {
    libraryListMock.mockResolvedValue({ videos: [makeVideo({ id: 'v1', title: 'Source' })] });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    await act(async () => {
      nav('Shorts').click();
    });
    await flush();

    const reBtn = container.querySelector<HTMLButtonElement>('[data-testid="shorts"] button');
    await act(async () => {
      reBtn!.click();
    });
    await flush();

    expect(libraryListMock).toHaveBeenCalledTimes(1);
    const ws = container.querySelector('[data-testid="workspace"]');
    expect(ws).not.toBeNull();
    expect(ws!.getAttribute('data-video-id')).toBe('v1');
  });

  it('Re-export falls back to the Library when the source video is gone', async () => {
    libraryListMock.mockResolvedValue({ videos: [] });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    await act(async () => {
      nav('Shorts').click();
    });
    await flush();

    const reBtn = container.querySelector<HTMLButtonElement>('[data-testid="shorts"] button');
    await act(async () => {
      reBtn!.click();
    });
    await flush();

    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
  });
});
