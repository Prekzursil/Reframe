// App.caption.test.tsx — the v1.5 Caption rail destination routing.
//
// Verifies the new top-level "Caption" tab: selecting it routes into the Caption
// phase for the currently-open video (threaded from shell state), empty-states
// when none is open, and its back control returns to the Library. The Caption
// view itself is stubbed (it owns its own tests) so this exercises ONLY App's
// routing wiring.

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
vi.mock('./views/MakeShorts', () => ({ MakeShorts: () => <div data-testid="makeshorts" /> }));
vi.mock('./views/Settings', () => ({ Settings: () => <div data-testid="settings" /> }));
vi.mock('./panels/DirectorPanel', () => ({ default: () => <div data-testid="director" /> }));
vi.mock('./components/JobQueue', () => ({
  JobQueue: () => <div />,
  JOBQUEUE_PANEL_ID: 'jobqueue-panel',
}));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));

// The Caption view is stubbed: it echoes the threaded video id and exposes its
// back control so App's route wiring is testable without the real view's RPC.
vi.mock('./views/Caption', () => ({
  Caption: ({ video, onBack }: { video: Video | null; onBack: () => void }) => (
    <div data-testid="caption" data-video-id={video?.id ?? ''}>
      <button type="button" onClick={onBack}>
        caption-back
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

function tab(label: string): HTMLButtonElement {
  const btns = Array.from(container.querySelectorAll<HTMLButtonElement>('.toptab'));
  const found = btns.find((b) => b.querySelector('.toptab__label')?.textContent === label);
  if (!found) throw new Error(`tab "${label}" not found`);
  return found;
}

describe('App Caption rail destination', () => {
  it('mounts the Caption phase with an empty video when opened directly', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    expect(container.querySelector('[data-testid="caption"]')).toBeNull();
    await act(async () => {
      tab('Caption').click();
    });
    await flush();
    const view = container.querySelector('[data-testid="caption"]');
    expect(view).not.toBeNull();
    expect(view!.getAttribute('data-video-id')).toBe('');
    expect(tab('Caption').getAttribute('aria-selected')).toBe('true');
    const panel = container.querySelector<HTMLElement>('[role="tabpanel"]')!;
    expect(panel.id).toBe('toptabpanel-caption');
  });

  it('threads the open video into the Caption phase', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="library"] button')!.click();
    });
    await flush();
    await act(async () => {
      tab('Caption').click();
    });
    await flush();
    expect(container.querySelector('[data-testid="caption"]')!.getAttribute('data-video-id')).toBe(
      'v1',
    );
  });

  it('routes back to the Library from the Caption phase', async () => {
    await act(async () => {
      root.render(<App />);
    });
    await flush();
    await act(async () => {
      tab('Caption').click();
    });
    await flush();
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="caption"] button')!.click();
    });
    await flush();
    expect(container.querySelector('[data-testid="library"]')).not.toBeNull();
    expect(tab('Library').getAttribute('aria-selected')).toBe('true');
  });
});
