// App.test.tsx — the renderer shell + top-level tab routing (V1 IA §h).
//
// Verifies the L5 rail (Library / Produce / Refine / Deliver / Settings), the
// mode sub-navigation inside each destination that hosts more than one surface,
// that opening a video from the Library routes into Refine, the active-destination
// derivation + tabpanel a11y wiring at BOTH levels, and the interrupted-batch
// badge/resume deep-link on the Produce tab. The heavy child views are stubbed so
// the test exercises ONLY App's routing.

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

// Stub the lazy Director rail destination (it owns its own tests). The marker
// echoes the threaded video id + exposes the empty-state CTA so App's WU-E1 wiring
// is testable (the view forwards both straight to the composed DirectorPanel).
vi.mock('./views/Director', () => ({
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

// L5: Caption / Export / Deliver stopped being rail destinations and became MODES
// of Refine and Deliver, so this suite now navigates to them and needs markers.
// Each echoes the video App threaded in; Export also exposes the onDeliver link
// that carries a finished render into the Publish mode.
vi.mock('./views/Caption', () => ({
  Caption: ({ video }: { video: Video | null }) => (
    <div data-testid="caption" data-video-id={video?.id ?? ''} />
  ),
}));
vi.mock('./views/Export', () => ({
  Export: ({ video, onDeliver }: { video: Video | null; onDeliver?: () => void }) => (
    <div data-testid="export" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onDeliver}>
        to-deliver
      </button>
    </div>
  ),
}));
vi.mock('./views/Deliver', () => ({
  // FIDELITY: the real view renders its own `components/TabBar`, unconditionally,
  // and one of its tabs is literally `publish` (views/Deliver.tsx:21-28, :68). Those
  // ids come from the SAME flat global namespace the mode nav uses, so a stub that
  // omits them cannot reproduce a nesting id collision — which is how one shipped.
  Deliver: ({ video }: { video: Video | null }) => (
    <div data-testid="deliver" data-video-id={video?.id ?? ''}>
      <button type="button" role="tab" id="tab-publish" aria-selected="false">
        Publish
      </button>
    </div>
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

/**
 * A MODE tab inside the active destination (L5: the rail is 4 + Settings, and
 * each destination that hosts more than one surface exposes them as modes).
 */
function modeTab(label: string): HTMLButtonElement {
  // Scoped to the destination's OWN TabBar (`.app__destination > .tabbar`), not to
  // any descendant with role=tab: a nested view has its own tablist, and one of
  // Deliver's tabs is also labelled "Publish". If TabBar's root class ever changes
  // this selector finds nothing and every mode test fails loudly, which is the
  // behaviour we want from a helper this many tests lean on.
  const btns = Array.from(
    container.querySelectorAll<HTMLButtonElement>('.app__destination > .tabbar [role="tab"]'),
  );
  const found = btns.find((b) => b.textContent === label);
  if (!found) throw new Error(`mode tab "${label}" not found`);
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
      tab('Produce').click();
    });
    await flush();
    const view = container.querySelector('[data-testid="makeshorts"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-resume')).toBe('');
    expect(container.querySelector('[data-testid="library"]')).toBeNull();
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
  });

  it('returns to the Library home via the Library tab', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Produce').click();
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
      tab('Produce').click();
    });
    await flush();
    await act(async () => {
      modeTab('Director').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="director"]')).not.toBeNull();
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
    expect(modeTab('Director').getAttribute('aria-selected')).toBe('true');
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
      tab('Produce').click();
    });
    await flush();
    await act(async () => {
      modeTab('Director').click();
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
      tab('Produce').click();
    });
    await flush();
    await act(async () => {
      modeTab('Director').click();
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
    expect(tab('Refine').getAttribute('aria-selected')).toBe('true');

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
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
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
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
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
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
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
    expect(tab('Produce').getAttribute('aria-selected')).toBe('true');
    expect(modeTab('Director').getAttribute('aria-selected')).toBe('true');
  });

  it('shows the Edit empty state (no video) when the Edit tab is opened directly', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Refine').click();
    });
    await flush();
    const edit = container.querySelector('[data-testid="edit"]');
    expect(edit).not.toBeNull();
    // No video opened yet → the marker reports an empty video id.
    expect(edit!.getAttribute('data-video-id')).toBe('');
    expect(tab('Refine').getAttribute('aria-selected')).toBe('true');
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
    // Switch away to Produce, then back to Refine — the video persists.
    await act(async () => {
      tab('Produce').click();
    });
    await flush();
    await act(async () => {
      tab('Refine').click();
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
    expect(tab('Produce')).toBeTruthy();
    expect(tab('Produce').querySelector('.toptab__badge')).toBeNull();
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

    expect(tab('Produce').querySelector('.toptab__badge')!.textContent).toBe('1');
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
    expect(tab('Refine').getAttribute('aria-selected')).toBe('true');
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

// ---------------------------------------------------------------------------
// L5 G-7 INVARIANT 3, and the "nothing was dropped" half that goes with it.
//
// The rail shipped EIGHT destinations. Four of them answered the same two
// questions twice ("where do I make a short?" — Make Shorts or Director; "where
// do I finish?" — Export or Deliver). L5 locked it at 4 + Settings, with each old
// destination re-homed as a MODE of the destination that owns its job.
// ---------------------------------------------------------------------------
describe('L5 rail: exactly four destinations plus Settings', () => {
  async function mount(): Promise<void> {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
  }

  function railLabels(): string[] {
    return Array.from(container.querySelectorAll('.toptab')).map(
      (b) => b.querySelector('.toptab__label')?.textContent ?? '',
    );
  }

  // The literal that regressed before. A count assertion is the only thing that
  // catches "each addition was individually defensible" growth — the exact defect
  // class that took the workspace tab strip from 12 painted to 16.
  it('renders EXACTLY five rail entries, in the locked order', async () => {
    await mount();
    expect(railLabels()).toEqual(['Library', 'Produce', 'Refine', 'Deliver', 'Settings']);
    expect(railLabels()).toHaveLength(5);
  });

  it('hosts BOTH AI paths under Produce, so "where do I make a short?" has one answer', async () => {
    await mount();
    await act(async () => {
      tab('Produce').click();
    });
    await flush();
    expect(
      Array.from(container.querySelectorAll('.app__destination [role="tab"]')).map(
        (t) => t.textContent,
      ),
    ).toEqual(['Make Shorts', 'Director']);
    // lands on the candidate-driven path
    expect(container.querySelector('[data-testid="makeshorts"]')).not.toBeNull();
    await act(async () => {
      modeTab('Director').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="director"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="makeshorts"]')).toBeNull();
  });

  // L5 G-6 CARRIED RISK, verified real by the owner against director-win32.png:
  // Director is the app's one editorial, low-density screen, and folding it into
  // Produce could flatten it. The mechanical half of that check is that Produce
  // adds NOTHING around it — the view is a direct child of the mode panel, with no
  // wrapper card, grid cell or shared Produce chrome between them. (The visual
  // half — that the serif display voice and the content column survive — is the
  // owner's baseline review; a unit test cannot see pixels.)
  it('mounts Director unchanged inside Produce, with no wrapper chrome around it', async () => {
    await mount();
    await act(async () => {
      tab('Produce').click();
    });
    await flush();
    await act(async () => {
      modeTab('Director').click();
    });
    await flush();
    const director = container.querySelector('[data-testid="director"]')!;
    expect(director.parentElement?.className).toBe('app__mode-panel');
    // and the mode panel holds exactly the view (plus nothing else)
    expect(director.parentElement?.children).toHaveLength(1);
  });

  it('hosts the editor and the caption pilot under Refine', async () => {
    await mount();
    await act(async () => {
      tab('Refine').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="edit"]')).not.toBeNull();
    await act(async () => {
      modeTab('Caption design').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="caption"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="edit"]')).toBeNull();
    expect(tab('Refine').getAttribute('aria-selected')).toBe('true');
  });

  // CROSS-SURFACE GUARD — GRIND round 3, closing a half-built one.
  //
  // The composite `app/e2e/preview.spec.ts` counts on the Refine/editor route is
  // 14 `.tab` elements = |REFINE_MODES| (2) + 3 dock lanes + 9 project sections.
  // `Workspace.test.tsx` ("pins the painted tab set that the nightly e2e spec
  // counts") pins the last two terms (12). The FIRST term was pinned by NOTHING:
  // `rg REFINE_MODES app/` returned only the declaration (App.tsx:141-144), its
  // single use in `renderDestination`, and a comment — no assertion anywhere. And
  // `modeTab()` above is find-by-label, so it throws on a REMOVAL and is blind to
  // an ADDITION. Adding a third Refine mode moved the e2e's true count 14 -> 15
  // with zero unit tests going red: the same staleness class the deleted "pins the
  // strip counts that the nightly e2e spec hardcodes" test used to prevent, and
  // the mode-list ratchet the PRODUCE/REFINE/DELIVER note warns about one level
  // down ("a destination whose mode list starts growing is the tab-strip ratchet
  // reappearing").
  //
  // This is NOT a red-first test — it pins present, correct behaviour. Its
  // detector strength was checked by MUTATION (both-states): adding a third
  // REFINE_MODES entry makes it fail on the id list; the run is quoted in the PR.
  it('pins the painted Refine mode tabs that the nightly e2e route counts', async () => {
    await mount();
    await act(async () => {
      tab('Refine').click();
    });
    await flush();
    // Scoped to the destination's OWN TabBar, like `modeTab()`: the mounted view
    // may carry its own tablist and must not be counted as a mode.
    expect(
      Array.from(container.querySelectorAll('.app__destination > .tabbar [role="tab"]')).map(
        (t) => t.textContent,
      ),
    ).toEqual(['Editor', 'Caption design']);
  });

  it('hosts finish and publish under Deliver', async () => {
    await mount();
    await act(async () => {
      tab('Deliver').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="export"]')).not.toBeNull();
    await act(async () => {
      modeTab('Publish').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="deliver"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="export"]')).toBeNull();
  });

  it('lets the mode panel STRETCH its view, the way .app__main did before the nesting', async () => {
    // G-6 CARRIED RISK, the half a "mounted unchanged" claim does not cover: the
    // COMPONENT is unchanged, its layout CONTEXT is not. `components/shell.css:376`
    // gives `.app__main > * { flex: 1; min-height: 0 }`, and every mode-hosted view
    // used to be that direct child. Nested inside `.app__mode-panel` it is an
    // ordinary flex item — `flex: 0 1 auto`, i.e. CONTENT height — and
    // `views/director.css:9` declares neither a height nor a flex-grow of its own,
    // so Director stopped filling its destination. On the app's one deliberately
    // low-density editorial screen, content-height and full-height look nothing
    // alike. A single `1fr` row hands the height back without a third wrapper div.
    //
    // SCOPE: jsdom performs no layout, so this asserts the DECLARATION, not pixels.
    // The rendered check at 1280x820 stays the owner's baseline review.
    await mount();
    await act(async () => {
      tab('Produce').click();
    });
    await flush();
    const panel = container.querySelector<HTMLElement>('.app__mode-panel')!;
    expect(panel.style.display).toBe('grid');
    expect(panel.style.gridTemplateRows).toBe('1fr');
    // `min-height: 0` is what lets the row shrink below its content instead of
    // pushing the destination past the 820px window (jsdom keeps it unitless).
    expect(panel.style.minHeight).toBe('0');
    // Exactly one child, which is what makes one 1fr row the whole story — but this
    // file mocks all eight views, so what is asserted HERE is a stub. RESCOPED: the
    // fact was verified separately by inspection of the six real mode-hosted views
    // (Edit, Caption, Deliver, Export, MakeShorts, Director) — each has a
    // single-element root, MakeShorts' fragment being nested at MakeShorts.tsx:347
    // inside a conditional rather than at its root. A fragment root there would land
    // extra children in implicit auto rows, which is the one way `1fr` regresses.
    expect(panel.children).toHaveLength(1);
  });

  it('does not mint a duplicate DOM id by nesting the mode nav around a view', async () => {
    // `components/TabBar` mints ids from ONE flat namespace (`tab-<id>` /
    // `tabpanel-<id>`), so wrapping a TabBar-based mode nav around a view that also
    // uses TabBar collides whenever a mode id equals one of that view's tab ids.
    // It did: DELIVER_MODES 'publish' vs views/Deliver.tsx's 'publish' tab put TWO
    // elements with id="tab-publish" on the {deliver, publish} route — and that id
    // is the target of the mode panel's aria-labelledby, i.e. an ARIA IDREF
    // resolving to whichever element document order happens to hand it.
    await mount();
    await act(async () => {
      tab('Deliver').click();
    });
    await flush();
    await act(async () => {
      modeTab('Publish').click();
    });
    await flush();
    // CONTROL: the nested view's own `tab-publish` must really be in the document,
    // or the scan below would pass while measuring nothing.
    expect(container.querySelector('[data-testid="deliver"] #tab-publish')).not.toBeNull();

    const ids = Array.from(container.querySelectorAll('[id]')).map((el) => el.id);
    expect(ids.filter((id, i) => ids.indexOf(id) !== i)).toEqual([]);
    // and the mode nav is namespaced, so no view nested under it can collide later.
    expect(modeTab('Publish').id).toBe('tab-mode-publish');
    const panel = container.querySelector('.app__mode-panel');
    expect(panel?.id).toBe('tabpanel-mode-publish');
    expect(panel?.getAttribute('aria-labelledby')).toBe('tab-mode-publish');
  });

  it('carries a finished render from Finish into Publish (the Export/Deliver split)', async () => {
    await mount();
    await act(async () => {
      tab('Deliver').click();
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="export"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="deliver"]')).not.toBeNull();
    expect(modeTab('Publish').getAttribute('aria-selected')).toBe('true');
  });

  it('threads the open video through every mode of a destination', async () => {
    await mount();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    // opening a video lands in Refine → Editor
    expect(tab('Refine').getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('[data-testid="edit"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
    await act(async () => {
      modeTab('Caption design').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="caption"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
    await act(async () => {
      tab('Deliver').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="export"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
  });

  it('gives the single-surface destinations no mode navigation at all', async () => {
    await mount();
    // Library
    expect(container.querySelector('.app__destination')).toBeNull();
    // Settings does its own sub-navigation inside the view, so the shell adds none
    await act(async () => {
      tab('Settings').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="settings"]')).not.toBeNull();
    expect(container.querySelector('.app__destination')).toBeNull();
  });

  // ORPHANED BY THIS CHANGE, disclosed rather than papered over. Shrinking the
  // rail from 8 to 5 left `DirectorIcon`, `CaptionIcon` and `ExportIcon` in
  // components/navIcons.tsx with NO production caller — the destinations they
  // labelled are modes now, and TabBar (which renders the mode switch) takes no
  // icon. Deleting them is the right end state, but navIcons.tsx is outside this
  // lane's file scope, so they are RETAINED and covered here instead of silently
  // dropping the renderer's 100% bar on someone else's file.
  //
  // This is a smoke render, and I am not claiming it is more: it proves each
  // component still returns an <svg>, nothing about placement. FOLLOW-UP for the
  // owner of navIcons.tsx: delete the three, or give the mode switch icons.
  it('keeps the three rail icons the L5 shrink orphaned renderable', async () => {
    const { CaptionIcon, DirectorIcon, ExportIcon } = await import('./components/navIcons');
    await act(async () => {
      root.render(
        <div data-testid="orphaned-icons">
          <DirectorIcon />
          <CaptionIcon />
          <ExportIcon />
        </div>,
      );
    });
    await flush();
    expect(container.querySelectorAll('[data-testid="orphaned-icons"] svg')).toHaveLength(3);
  });

  // TabBar puts `aria-controls` on the SELECTED tab only, so the mode panel must
  // carry the matching id — a dangling IDREF is the CRITICAL axe
  // `aria-valid-attr-value` violation TabBar's own comment records from a real CI run.
  it('wires the mode tab to a real panel id (no dangling aria-controls)', async () => {
    await mount();
    await act(async () => {
      tab('Produce').click();
    });
    await flush();
    const selected = container.querySelector(
      '.app__destination [role="tab"][aria-selected="true"]',
    );
    const controls = selected!.getAttribute('aria-controls');
    // NAMESPACED (`mode-`), which is the fix for the nesting collision asserted by
    // "does not mint a duplicate DOM id …" above: the IDREF still has to resolve,
    // it just resolves inside the mode nav's own namespace now.
    expect(controls).toBe('tabpanel-mode-shorts');
    expect(container.querySelector(`#${controls}`)).not.toBeNull();
    expect(container.querySelector(`#${controls}`)?.getAttribute('aria-labelledby')).toBe(
      selected!.getAttribute('id'),
    );
    // the rail's own panel wiring is untouched by the nesting
    const main = container.querySelector('main.app__main')!;
    expect(main.id).toBe('toptabpanel-produce');
    expect(main.getAttribute('aria-labelledby')).toBe('toptab-produce');
  });
});
