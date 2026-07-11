// App.wf-other-0.test.tsx — regression guard for useRepurposeBadge's mount-time
// contract (App.tsx §166-209).
//
// The badge hook documents "Reads batch.list once on mount". Before the ref-mirror
// fix it depended on the unstable ToastApi (useToast() returns a NEW object on every
// toast push/dismiss app-wide — ToastProvider memoizes its value over [toasts,…]),
// so its own pushed interrupted-batch toast — and any later dismiss of it — each
// re-ran the effect and re-fired a hidden client.batch.list() IPC round-trip. These
// tests pin the read count to exactly one across those toast-state churns and cover
// the incomplete / empty / rejected branches of the single mount effect.

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

// The heavy child views are stubbed so the tree focuses on the badge hook and its
// single ToastProvider — nothing else pushes toasts or fires batch.list.
vi.mock('./views/Library', () => ({ Library: () => <div data-testid="library" /> }));
vi.mock('./views/Edit', () => ({ Edit: () => <div data-testid="edit" /> }));
vi.mock('./views/MakeShorts', () => ({ MakeShorts: () => <div data-testid="makeshorts" /> }));
vi.mock('./views/Settings', () => ({ Settings: () => <div data-testid="settings" /> }));
vi.mock('./panels/DirectorPanel', () => ({ default: () => <div data-testid="director" /> }));
vi.mock('./components/JobQueue', () => ({
  JobQueue: () => <div />,
  JOBQUEUE_PANEL_ID: 'jobqueue-panel',
}));
vi.mock('./components/SidecarBanner', () => ({ SidecarBanner: () => <div /> }));

import { App } from './App';

const INCOMPLETE_BATCH = {
  batches: [
    {
      id: 'b9',
      name: 'Season 3',
      templateId: 't1',
      status: 'partial',
      createdAt: 5,
      counts: { total: 30, done: 12, error: 0, skipped: 2, queued: 16, running: 0, cancelled: 0 },
    },
  ],
};

function toastCount(): number {
  return document.body.querySelectorAll('.toast').length;
}

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
  libraryListMock.mockResolvedValue({ videos: [makeVideo()] });
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

/** The interrupted-batch badge on the Make Shorts tab, or null when absent. */
function badgeEl(): Element | null {
  return container.querySelector('.toptab__badge');
}

describe('useRepurposeBadge reads batch.list once on mount (App.tsx §166-209)', () => {
  it('does NOT re-fetch batch.list when its own interrupted-batch toast is pushed', async () => {
    batchListMock.mockResolvedValue(INCOMPLETE_BATCH);

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    // The interrupted-batch toast fired (proving the hook ran to the push branch)
    // and the (N) badge rendered — yet pushing the toast changed the ToastApi
    // identity, which the old [toast,…] deps let re-run the effect and re-fire
    // batch.list. The ref-mirror keeps it at exactly one read.
    expect(document.body.textContent).toContain("A batch ('Season 3') was interrupted");
    expect(badgeEl()!.textContent).toBe('1');
    expect(batchListMock).toHaveBeenCalledTimes(1);
  });

  it('still reads batch.list only once when the toast is dismissed (a later toast-state churn)', async () => {
    batchListMock.mockResolvedValue(INCOMPLETE_BATCH);

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(toastCount()).toBe(1);
    expect(batchListMock).toHaveBeenCalledTimes(1);

    // Dismissing the toast mutates the provider's `toasts` state (a new ToastApi
    // identity) — under the old [toast,…] deps this re-fired batch.list; the fix
    // leaves the count untouched.
    const close = document.body.querySelector<HTMLButtonElement>('.toast__close')!;
    await act(async () => {
      close.click();
    });
    await flush();

    expect(toastCount()).toBe(0);
    expect(batchListMock).toHaveBeenCalledTimes(1);
  });

  it('emits no toast/badge and reads batch.list once when there are no incomplete batches', async () => {
    batchListMock.mockResolvedValue({ batches: [] });

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(toastCount()).toBe(0);
    expect(badgeEl()).toBeNull();
    expect(batchListMock).toHaveBeenCalledTimes(1);
  });

  it('swallows a batch.list rejection (best-effort): no toast, no badge, read once', async () => {
    batchListMock.mockRejectedValue(new Error('offline'));

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(toastCount()).toBe(0);
    expect(badgeEl()).toBeNull();
    expect(batchListMock).toHaveBeenCalledTimes(1);
  });

  it('makes no batch.list read at all when the preload bridge is absent', async () => {
    hasApiReturn = false;

    await act(async () => {
      root.render(<App />);
    });
    await flush();

    expect(batchListMock).not.toHaveBeenCalled();
    expect(badgeEl()).toBeNull();
  });
});
