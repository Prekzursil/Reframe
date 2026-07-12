// App.export.test.tsx — the v1.5 §4 Export + Deliver rail routing.
//
// Verifies the new top-level "Export" (Phase-5 guarded commit for the open video)
// and "Deliver" (batch / cross-video publish) tabs, that finishing an Export links
// INTO Deliver (the Export/Deliver split), the open video is threaded into both,
// and their back controls return to the Library. The views themselves are stubbed
// (they own their tests) so this exercises ONLY App's routing wiring.

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { Video } from './lib/rpc';

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

vi.mock('./views/Library', () => ({
  Library: ({ onOpen }: { onOpen: (v: Video) => void }) => (
    <div data-testid="library">
      <button type="button" onClick={() => onOpen(makeVideo())}>
        open-video
      </button>
    </div>
  ),
}));
vi.mock('./views/Edit', () => ({ Edit: () => <div data-testid="edit" /> }));
vi.mock('./views/Caption', () => ({ Caption: () => <div data-testid="caption" /> }));
vi.mock('./views/MakeShorts', () => ({ MakeShorts: () => <div data-testid="makeshorts" /> }));
vi.mock('./views/Settings', () => ({ Settings: () => <div data-testid="settings" /> }));
vi.mock('./panels/DirectorPanel', () => ({ default: () => <div data-testid="director" /> }));
vi.mock('./components/JobQueue', () => ({
  JobQueue: () => <div />,
  JOBQUEUE_PANEL_ID: 'jobqueue-panel',
}));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));

// The Export stub echoes the threaded video id and exposes its back + "continue to
// Deliver" controls so App's route wiring (incl. the Export→Deliver link) is testable.
vi.mock('./views/Export', () => ({
  Export: ({
    video,
    onBack,
    onDeliver,
  }: {
    video: Video | null;
    onBack: () => void;
    onDeliver: () => void;
  }) => (
    <div data-testid="export" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onBack}>
        export-back
      </button>
      <button type="button" onClick={onDeliver}>
        export-deliver
      </button>
    </div>
  ),
}));
vi.mock('./views/Deliver', () => ({
  Deliver: ({ video, onBack }: { video: Video | null; onBack: () => void }) => (
    <div data-testid="deliver" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onBack}>
        deliver-back
      </button>
    </div>
  ),
}));

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
  rpcMock.mockResolvedValue({});
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

async function mount(): Promise<void> {
  await act(async () => {
    root.render(<App />);
  });
  await flush();
}

function tab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.toptab'));
  const found = btns.find((b) => b.querySelector('.toptab__label')?.textContent === label);
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

async function clickTab(label: string): Promise<void> {
  await act(async () => {
    tab(label).click();
  });
  await flush();
}

async function openVideo(): Promise<void> {
  await act(async () => {
    container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
  });
  await flush();
}

describe('App Export rail destination', () => {
  it('mounts the Export phase with an empty video when opened directly', async () => {
    await mount();
    expect(container.querySelector('[data-testid="export"]')).toBeNull();
    await clickTab('Export');
    const view = container.querySelector('[data-testid="export"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-video-id')).toBe('');
    expect(tab('Export').getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector<HTMLElement>('[role="tabpanel"]')!.id).toBe(
      'toptabpanel-export',
    );
  });

  it('threads the open video into the Export phase', async () => {
    await mount();
    await openVideo();
    await clickTab('Export');
    expect(container.querySelector('[data-testid="export"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
  });

  it('routes back to the Library from the Export phase', async () => {
    await mount();
    await clickTab('Export');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="export"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
  });

  it('links a finished Export INTO the Deliver rail (with the video threaded)', async () => {
    await mount();
    await openVideo();
    await clickTab('Export');
    // "Continue to Deliver" from the finished export.
    const deliverBtn = Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-testid="export"] button'),
    ).find((b) => b.textContent === 'export-deliver')!;
    await act(async () => {
      deliverBtn.click();
    });
    await flush();
    const deliver = container.querySelector('[data-testid="deliver"]');
    expect(deliver).not.toBeNull();
    expect(deliver!.getAttribute('data-video-id')).toBe('v1');
    expect(tab('Deliver').getAttribute('aria-selected')).toBe('true');
  });
});

describe('App Deliver rail destination', () => {
  it('mounts the Deliver rail directly from its tab', async () => {
    await mount();
    await clickTab('Deliver');
    const view = container.querySelector('[data-testid="deliver"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-video-id')).toBe('');
    expect(tab('Deliver').getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector<HTMLElement>('[role="tabpanel"]')!.id).toBe(
      'toptabpanel-deliver',
    );
  });

  it('routes back to the Library from the Deliver rail', async () => {
    await mount();
    await clickTab('Deliver');
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="deliver"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
  });
});
