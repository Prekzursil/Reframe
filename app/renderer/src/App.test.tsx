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
const setRoutingPolicyMock = vi.fn();
let hasApiReturn = true;

vi.mock('./lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => hasApiReturn,
  client: {
    library: { list: (...a: unknown[]) => libraryListMock(...a) },
    batch: { list: (...a: unknown[]) => batchListMock(...a) },
    models: { setRoutingPolicy: (...a: unknown[]) => setRoutingPolicyMock(...a) },
  },
}));

// The Library marker exposes onOpen + the v1.5 §4 P0 produced-shorts seams App
// wires (whether the `shorts` port is injected, and the edit-in-Studio callback).
vi.mock('./views/Library', () => ({
  Library: ({
    onOpen,
    shorts,
    onEditShort,
  }: {
    onOpen: (v: Video) => void;
    shorts?: unknown;
    onEditShort?: (short: { videoId: string }) => void;
  }) => (
    <div data-testid="library" data-has-shorts={shorts ? 'yes' : 'no'}>
      <button type="button" onClick={() => onOpen(makeVideo())}>
        open-video
      </button>
      <button type="button" onClick={() => onEditShort?.({ videoId: 'v1' })}>
        edit-short
      </button>
    </div>
  ),
}));

// Edit hosts the per-video surface; the marker exposes the open video + back, and
// the Task Hub section callbacks (WU-3a1: Make shorts / Director job cards).
vi.mock('./views/Edit', () => ({
  Edit: ({
    video,
    onBack,
    onMakeShorts,
    onMakeShortsForVideo,
    onDirector,
  }: {
    video: Video | null;
    onBack: () => void;
    onMakeShorts?: () => void;
    onMakeShortsForVideo?: (videoId: string) => void;
    onDirector?: () => void;
  }) => (
    <div data-testid="edit" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onBack}>
        back
      </button>
      <button type="button" onClick={() => onMakeShorts?.()}>
        hub-make-shorts
      </button>
      {/* WU-3a4: the Workspace Short-maker tab deep-links to Make Shorts with the
          open video pre-selected (the single ShortMaker owner). */}
      <button type="button" onClick={() => onMakeShortsForVideo?.('v1')}>
        workspace-shortmaker
      </button>
      <button type="button" onClick={() => onDirector?.()}>
        hub-director
      </button>
    </div>
  ),
}));

// Make Shorts marker exposes the batch resume id + the deep-linked videoId App
// wired (it owns its tests).
vi.mock('./views/MakeShorts', () => ({
  MakeShorts: ({ resumeId, videoId }: { resumeId?: string; videoId?: string }) => (
    <div data-testid="makeshorts" data-resume={resumeId ?? ''} data-video-id={videoId ?? ''} />
  ),
}));

// Stub the lazy AI Director panel (it owns its own tests). The marker echoes the
// threaded video id + exposes the empty-state CTA so App's WU-E1 wiring is testable.
vi.mock('./panels/DirectorPanel', () => ({
  default: ({ video, onChooseVideo }: { video: Video | null; onChooseVideo?: () => void }) => (
    <div data-testid="director" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onChooseVideo}>
        choose-video
      </button>
    </div>
  ),
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
  setRoutingPolicyMock.mockReset();
  setRoutingPolicyMock.mockResolvedValue({ routingPolicy: { global: 'local', overrides: {} } });
  hasApiReturn = true;
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

  it('WU-E1: threads the open video into the Director and the CTA routes to Library', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    // Open a video from the Library, then switch to the Director tab.
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    await act(async () => {
      tab('Director').click();
    });
    await flush();
    // The app-selected video id is threaded into the panel.
    const director = container.querySelector('[data-testid="director"]')!;
    expect(director.getAttribute('data-video-id')).toBe('v1');
    // The empty-state CTA is wired to route back to the Library (real selection).
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="director"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
  });

  it('WU-E1: opening the Director with no video threads a null video (empty id)', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Director').click();
    });
    await flush();
    const director = container.querySelector('[data-testid="director"]')!;
    expect(director.getAttribute('data-video-id')).toBe('');
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

  // WU-3a1: the Task Hub's section job cards route out of Edit to the top-level
  // surfaces. Drive the Edit mock's callbacks and assert the route switch.
  function hubButton(text: string): HTMLButtonElement {
    const btns = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-testid="edit"] button'),
    );
    const found = btns.find((b) => b.textContent === text);
    if (!found) throw new Error(`hub button "${text}" not found`);
    return found;
  }

  it('WU-3a1: the Make shorts job card routes to the Make Shorts section', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    await act(async () => {
      hubButton('hub-make-shorts').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="makeshorts"]')).not.toBeNull();
    expect(tab('Make Shorts').getAttribute('aria-selected')).toBe('true');
  });

  it('WU-3a4: the Workspace Short-maker deep-link routes to Make Shorts pre-selected to the video', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    await act(async () => {
      hubButton('workspace-shortmaker').click();
    });
    await flush();
    const view = container.querySelector('[data-testid="makeshorts"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-video-id')).toBe('v1');
    // No batch resume on this deep-link.
    expect(view!.getAttribute('data-resume')).toBe('');
    expect(tab('Make Shorts').getAttribute('aria-selected')).toBe('true');
  });

  it('v1.5 §4 P0: injects the produced-shorts port + routes edit-in-Studio to Make Shorts', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    // The dormant produced-shorts seam is now LIVE: the port is injected into the Library.
    expect(
      container.querySelector('[data-testid="library"]')!.getAttribute('data-has-shorts'),
    ).toBe('yes');
    // "Edit in Studio" for a produced short reopens Make Shorts pre-selected to its source video.
    const editBtn = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-testid="library"] button'),
    ).find((b) => b.textContent === 'edit-short');
    await act(async () => {
      editBtn!.click();
    });
    await flush();
    const view = container.querySelector('[data-testid="makeshorts"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-video-id')).toBe('v1');
    expect(view!.getAttribute('data-resume')).toBe('');
    expect(tab('Make Shorts').getAttribute('aria-selected')).toBe('true');
  });

  it('WU-3a1: the Director job card routes to the Director section', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    await act(async () => {
      hubButton('hub-director').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="director"]')).not.toBeNull();
    expect(tab('Director').getAttribute('aria-selected')).toBe('true');
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

describe('App M3 header routing toggle', () => {
  function routingBtn(mode: string): HTMLButtonElement {
    return container.querySelector(
      `.routing-toggle button[data-mode="${mode}"]`,
    ) as HTMLButtonElement;
  }

  it('defaults the routing toggle to Local when no policy is persisted', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(routingBtn('local').getAttribute('aria-pressed')).toBe('true');
    expect(routingBtn('cloud').getAttribute('aria-pressed')).toBe('false');
  });

  it('hydrates the toggle from a persisted routingPolicy.global', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ routingPolicy: { global: 'auto', overrides: {} } });
      }
      return Promise.resolve({});
    });
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(routingBtn('auto').getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps Local when the persisted global is out-of-enum/missing', async () => {
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ routingPolicy: { global: 'sneaky' } });
      }
      return Promise.resolve({});
    });
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(routingBtn('local').getAttribute('aria-pressed')).toBe('true');
  });

  it('persists a click via models.setRoutingPolicy and reflects it immediately', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      routingBtn('cloud').click();
    });
    await flush();
    expect(setRoutingPolicyMock).toHaveBeenCalledWith({ global: 'cloud' });
    expect(routingBtn('cloud').getAttribute('aria-pressed')).toBe('true');
  });

  it('updates the toggle in-memory but skips the RPC when no api bridge is present', async () => {
    hasApiReturn = false;
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      routingBtn('cloud').click();
    });
    await flush();
    expect(setRoutingPolicyMock).not.toHaveBeenCalled();
    expect(routingBtn('cloud').getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps the in-memory selection even if the write rejects', async () => {
    setRoutingPolicyMock.mockRejectedValue(new Error('offline'));
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      routingBtn('auto').click();
    });
    await flush();
    expect(setRoutingPolicyMock).toHaveBeenCalledWith({ global: 'auto' });
    expect(routingBtn('auto').getAttribute('aria-pressed')).toBe('true');
  });
});

// WU-1b: the AppGate renders the full-screen FirstRunSetup INSTEAD of the shell
// while first-run provisioning is in flight, so the Library (+ its mount-time
// RPCs) never mount against a dead sidecar.
describe('App first-run provisioning gate (WU-1b)', () => {
  let provisioningCb: ((state: { active: boolean }) => void) | null = null;

  function installGateBridge(initialActive: boolean): void {
    provisioningCb = null;
    (window as unknown as { api?: unknown }).api = {
      // The mount-time query decides the FIRST frame (push events miss it).
      getProvisioningState: () => Promise.resolve({ active: initialActive }),
      onProvisioningState: (cb: (state: { active: boolean }) => void) => {
        provisioningCb = cb;
        return () => {
          provisioningCb = null;
        };
      },
    };
  }

  afterEach(() => {
    delete (window as unknown as { api?: unknown }).api;
  });

  it('renders FirstRunSetup and blocks the Library while provisioning is active', async () => {
    installGateBridge(true);
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    // The full-screen gate replaces the shell — no Library, no tab strip.
    expect(container.querySelector('.first-run-setup')).not.toBeNull();
    expect(container.querySelector('[data-testid="library"]')).toBeNull();
    expect(container.querySelector('.toptab')).toBeNull();
    // The shell's mount-time RPCs never fired (blocked behind the gate).
    expect(libraryListMock).not.toHaveBeenCalled();
    expect(batchListMock).not.toHaveBeenCalled();
  });

  it('auto-transitions to the normal shell when provisioning clears', async () => {
    installGateBridge(true);
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(container.querySelector('.first-run-setup')).not.toBeNull();
    // Sidecar reached running → provisioning drops → the shell mounts.
    await act(async () => {
      provisioningCb?.({ active: false });
    });
    await flush();
    expect(container.querySelector('.first-run-setup')).toBeNull();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
  });
});
