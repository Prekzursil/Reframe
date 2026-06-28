// App.test.tsx — the renderer shell + top-level tab routing (V1 IA §h).
//
// Verifies the five-section surface switch (Library / Make Shorts / Edit /
// Director / Settings), that opening a video from the Library routes into the
// Edit section, the active-tab derivation + tabpanel a11y wiring, and the
// interrupted-batch badge/resume deep-link on the Make Shorts tab. The heavy
// child views are stubbed so the test exercises ONLY App's routing.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { Video } from './lib/rpc';

// ---- mocks -----------------------------------------------------------------
const rpcMock = vi.fn();
const libraryListMock = vi.fn();
const batchListMock = vi.fn();

vi.mock('./lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => true,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    batch: { list: (...a: unknown[]) => batchListMock(...a) },
  },
}));

vi.mock('./views/Library', () => ({
  Library: ({ onOpen }: { onOpen: (v: Video) => void }) => (
    <div data-testid="library">
      <button type="button" onClick={() => onOpen(makeVideo())}>
        open-video
      </button>
    </div>
  ),
}));

// Edit hosts the per-video surface; the marker exposes the open video + back.
vi.mock('./views/Edit', () => ({
  Edit: ({ video, onBack }: { video: Video | null; onBack: () => void }) => (
    <div data-testid="edit" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onBack}>
        back
      </button>
    </div>
  ),
}));

// Make Shorts marker exposes the batch resume id App wired (it owns its tests).
vi.mock('./views/MakeShorts', () => ({
  MakeShorts: ({ resumeId }: { resumeId?: string }) => (
    <div data-testid="makeshorts" data-resume={resumeId ?? ''} />
  ),
}));

// Stub the lazy AI Director panel (it owns its own tests).
vi.mock('./panels/DirectorPanel', () => ({
  default: () => <div data-testid="director" />,
}));

// Stub the Settings view; expose the initialSection App wired in (it owns tests).
vi.mock('./views/Settings', () => ({
  Settings: ({ initialSection }: { initialSection?: string }) => (
    <div data-testid="settings" data-section={initialSection ?? ''} />
  ),
}));

// Stub the always-mounted chrome so the test focuses on routing.
vi.mock('./components/JobQueue', () => ({
  JobQueue: () => <div />,
  JOBQUEUE_PANEL_ID: 'jobqueue-panel',
}));
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
  batchListMock.mockReset();
  batchListMock.mockResolvedValue({ batches: [] });
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

/** A top-level tab button by its visible label. */
function tab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.toptab'));
  const found = btns.find((b) => b.querySelector('.toptab__label')?.textContent === label);
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

describe('App top-level tabs', () => {
  it('mounts the Library by default with the Library tab selected', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="makeshorts"]')).toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
    expect(tab('Library').classList.contains('toptab--active')).toBe(true);
    const panel = container.querySelector<HTMLElement>('[role="tabpanel"]')!;
    expect(panel.id).toBe('toptabpanel-library');
    expect(panel.getAttribute('aria-labelledby')).toBe('toptab-library');
  });

  it('navigates to the Make Shorts section and marks its tab active', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Make Shorts').click();
    });
    await flush();
    const view = container.querySelector('[data-testid="makeshorts"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-resume')).toBe('');
    expect(container.querySelector('[data-testid="library"]')).toBeNull();
    expect(tab('Make Shorts').getAttribute('aria-selected')).toBe('true');
  });

  it('returns to the Library home via the Library tab', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Make Shorts').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).toBeNull();
    await act(async () => {
      tab('Library').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
  });

  it('navigates to (mounts) the AI Director panel and marks its tab active', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(container.querySelector('[data-testid="director"]')).toBeNull();
    await act(async () => {
      tab('Director').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="director"]')).not.toBeNull();
    expect(tab('Director').getAttribute('aria-selected')).toBe('true');
  });

  it('navigates to Settings (default section) via the tab', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Settings').click();
    });
    await flush();
    const settings = container.querySelector('[data-testid="settings"]');
    expect(settings).not.toBeNull();
    expect(settings!.getAttribute('data-section')).toBe('');
    expect(tab('Settings').getAttribute('aria-selected')).toBe('true');
  });

  it('opens a video from the Library into the Edit section, then back to Library', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>('[data-testid="library"] button');
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    const edit = container.querySelector('[data-testid="edit"]');
    expect(edit).not.toBeNull();
    expect(edit!.getAttribute('data-video-id')).toBe('v1');
    expect(tab('Edit').getAttribute('aria-selected')).toBe('true');

    // The Edit back button returns to the Library home.
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="edit"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="edit"]')).toBeNull();
  });

  it('shows the Edit empty state (no video) when the Edit tab is opened directly', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Edit').click();
    });
    await flush();
    const edit = container.querySelector('[data-testid="edit"]');
    expect(edit).not.toBeNull();
    // No video opened yet → the marker reports an empty video id.
    expect(edit!.getAttribute('data-video-id')).toBe('');
    expect(tab('Edit').getAttribute('aria-selected')).toBe('true');
  });

  it('keeps the opened Edit video when switching tabs and returning to Edit', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    // Switch away to Make Shorts, then back to Edit — the video persists.
    await act(async () => {
      tab('Make Shorts').click();
    });
    await flush();
    await act(async () => {
      tab('Edit').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="edit"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
  });

  it('navigates to the Make Shorts view (no badge when none incomplete)', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(tab('Make Shorts')).toBeTruthy();
    expect(tab('Make Shorts').querySelector('.toptab__badge')).toBeNull();
  });

  it('shows a (N) badge + a resume toast for an incomplete batch, deep-linking on Resume', async () => {
    batchListMock.mockResolvedValue({
      batches: [
        {
          id: 'b9',
          name: 'Season 3',
          templateId: 't1',
          status: 'partial',
          createdAt: 5,
          counts: {
            total: 30,
            done: 12,
            error: 0,
            skipped: 2,
            queued: 16,
            running: 0,
            cancelled: 0,
          },
        },
      ],
    });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(tab('Make Shorts').querySelector('.toptab__badge')!.textContent).toBe('1');
    expect(document.body.textContent).toContain("A batch ('Season 3') was interrupted");
    expect(document.body.textContent).toContain('16 of 30 sources left');

    const resumeBtn = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('.toast__action'),
    ).find((b) => b.textContent === 'Resume');
    expect(resumeBtn).toBeTruthy();
    await act(async () => {
      resumeBtn!.click();
    });
    await flush();

    const view = container.querySelector('[data-testid="makeshorts"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-resume')).toBe('b9');
  });

  it('ignores a late batch.list result after unmount (cancelled guard)', async () => {
    let resolveList: (v: { batches: never[] }) => void = () => {};
    batchListMock.mockReturnValue(
      new Promise((res) => {
        resolveList = res;
      }),
    );
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    act(() => root.unmount());
    await act(async () => {
      resolveList({ batches: [] });
      await Promise.resolve();
    });
    root = createRoot(container);
  });
});

// WU-13: persist `lastOpenedVideoId` on openVideo + restore it into Edit on launch.
describe('App lastOpenedVideoId persist + restore', () => {
  it('restores the Edit section for a valid persisted lastOpenedVideoId on launch', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') return Promise.resolve({ lastOpenedVideoId: 'v1' });
      return Promise.resolve({});
    });
    libraryListMock.mockResolvedValue({ videos: [makeVideo({ id: 'v1', title: 'Restored' })] });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(libraryListMock).toHaveBeenCalledTimes(1);
    const edit = container.querySelector('[data-testid="edit"]');
    expect(edit).not.toBeNull();
    expect(edit!.getAttribute('data-video-id')).toBe('v1');
    expect(tab('Edit').getAttribute('aria-selected')).toBe('true');
  });

  it('stays on the Library when the persisted id is absent from library.list', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') return Promise.resolve({ lastOpenedVideoId: 'gone' });
      return Promise.resolve({});
    });
    libraryListMock.mockResolvedValue({ videos: [makeVideo({ id: 'v1' })] });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(libraryListMock).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="edit"]')).toBeNull();
  });

  it('stays on the Library when no lastOpenedVideoId is persisted (empty key)', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') return Promise.resolve({ lastOpenedVideoId: '' });
      return Promise.resolve({});
    });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(libraryListMock).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="edit"]')).toBeNull();
  });

  it('stays on the Library when the restore path throws (best-effort)', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') return Promise.resolve({ lastOpenedVideoId: 'v1' });
      return Promise.resolve({});
    });
    libraryListMock.mockRejectedValue(new Error('boom'));

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="edit"]')).toBeNull();
  });

  it('persists lastOpenedVideoId via settings.set exactly once when a video is opened', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();

    const openBtn = container.querySelector<HTMLButtonElement>('[data-testid="library"] button');
    await act(async () => {
      openBtn!.click();
    });
    await flush();

    const setCalls = rpcMock.mock.calls.filter(([method]) => method === 'settings.set');
    expect(setCalls).toHaveLength(1);
    expect(setCalls[0][1]).toEqual({ lastOpenedVideoId: 'v1' });
  });
});
