// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { KeepCopyControl, type ManagedCopyHandlers } from './KeepCopyControl';
import type { ManagedCopy, ManagedStatus } from '../lib/rpc';

const GB = 1024 ** 3;

function managedRow(over: Partial<ManagedCopy> = {}): ManagedCopy {
  return {
    entityId: 'v1',
    originalPath: '/movies/talk.mp4',
    managedPath: '/data/managed-copies/abc.mp4',
    contentHash: 'blake3:abc',
    sizeBytes: 2 * GB,
    keptAt: '2026-07-07T00:00:00Z',
    lastAccess: '2026-07-07T00:00:00Z',
    ...over,
  };
}

function status(over: Partial<ManagedStatus> = {}): ManagedStatus {
  return { sizeBytes: 0, capBytes: 20 * GB, count: 0, entries: [], ...over };
}

function makeHandlers(over: Partial<ManagedCopyHandlers> = {}): ManagedCopyHandlers {
  return {
    status: vi.fn(async () => status()),
    keep: vi.fn(async () => managedRow()),
    evict: vi.fn(async () => {}),
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(turns = 8): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) await Promise.resolve();
  });
}

async function render(
  handlers: ManagedCopyHandlers,
  props: { sourceExists?: boolean } = {},
): Promise<void> {
  await act(async () => {
    root.render(
      <KeepCopyControl
        videoId="v1"
        sourceExists={props.sourceExists ?? true}
        handlers={handlers}
      />,
    );
  });
  await flush();
}

function badge(): string {
  return container.querySelector('.keep-copy__badge')?.textContent ?? '';
}

function statusText(): string {
  return container.querySelector('.keep-copy__status')?.textContent ?? '';
}

async function click(selector: string): Promise<void> {
  const el = container.querySelector(selector) as HTMLButtonElement;
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

describe('KeepCopyControl', () => {
  it('shows a loading line until the store snapshot resolves', async () => {
    let resolveStatus: (s: ManagedStatus) => void = () => {};
    const statusFn = vi.fn(() => new Promise<ManagedStatus>((res) => (resolveStatus = res)));
    await act(async () => {
      root.render(
        <KeepCopyControl videoId="v1" sourceExists handlers={makeHandlers({ status: statusFn })} />,
      );
    });
    expect(container.querySelector('.keep-copy__loading')?.textContent).toContain(
      'Checking managed copy…',
    );
    await act(async () => resolveStatus(status()));
    await flush();
    expect(badge()).toContain('Linked (original only)');
  });

  it('renders the "Managed copy" chip + honest copy when this video is already managed', async () => {
    const handlers = makeHandlers({
      status: vi.fn(async () => status({ count: 1, entries: [managedRow()] })),
    });
    await render(handlers);
    expect(badge()).toContain('Managed copy');
    expect(container.querySelector('.keep-copy__note')?.textContent).toContain(
      'A copy is kept, so this survives the original being moved or deleted.',
    );
    // The keep affordance is NOT offered when already managed.
    expect(container.querySelector('.keep-copy__btn--keep')).toBeNull();
  });

  it('offers "Keep a copy" for an un-managed source that is on disk', async () => {
    const handlers = makeHandlers();
    await render(handlers, { sourceExists: true });
    expect(badge()).toContain('Linked (original only)');
    expect(container.querySelector('.keep-copy__btn--keep')?.textContent).toContain('Keep a copy');
  });

  it('does NOT offer keep for an un-managed but MISSING source (loud unavailable note)', async () => {
    await render(makeHandlers(), { sourceExists: false });
    expect(badge()).toContain('Linked (original only)');
    expect(container.querySelector('.keep-copy__btn--keep')).toBeNull();
    expect(container.querySelector('.keep-copy__note--warn')?.textContent).toContain(
      'Keep a copy is unavailable while the source file is missing',
    );
  });

  it('surfaces a store-read failure LOUDLY and still offers the opt-in', async () => {
    const handlers = makeHandlers({
      status: vi.fn(async () => Promise.reject(new Error('store db locked'))),
    });
    await render(handlers);
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Could not read the managed-copy store');
    expect(alert?.textContent).toContain('store db locked');
    // Falls back to the not-managed view (keep still offered).
    expect(container.querySelector('.keep-copy__btn--keep')).not.toBeNull();
  });

  it('keeps a copy and flips to the Managed chip + success message', async () => {
    const handlers = makeHandlers();
    await render(handlers);
    await click('.keep-copy__btn--keep');
    expect(handlers.keep).toHaveBeenCalledWith('v1');
    expect(badge()).toContain('Managed copy');
    expect(statusText()).toContain('Kept a managed copy');
  });

  it('shows the in-flight "Keeping a copy…" progress while the copy runs', async () => {
    let resolveKeep: (r: ManagedCopy) => void = () => {};
    const keep = vi.fn(() => new Promise<ManagedCopy>((res) => (resolveKeep = res)));
    const handlers = makeHandlers({ keep });
    await render(handlers);
    await act(async () => {
      (container.querySelector('.keep-copy__btn--keep') as HTMLButtonElement).dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    // Progress is announced (role=status), and the button is disabled mid-flight.
    expect(statusText()).toContain('Keeping a copy…');
    expect((container.querySelector('.keep-copy__btn--keep') as HTMLButtonElement).disabled).toBe(
      true,
    );
    await act(async () => resolveKeep(managedRow()));
    await flush();
    expect(badge()).toContain('Managed copy');
  });

  it('handles a store-FULL keep failure LOUDLY', async () => {
    const handlers = makeHandlers({
      keep: vi.fn(async () =>
        Promise.reject(new Error('cannot keep a copy: the file exceeds the managed-store cap')),
      ),
    });
    await render(handlers);
    await click('.keep-copy__btn--keep');
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Could not keep a copy');
    expect(alert?.textContent).toContain('exceeds the managed-store cap');
    // Still linked-only after a refused keep.
    expect(badge()).toContain('Linked (original only)');
  });

  it('stringifies a non-Error keep rejection (copy-failed path)', async () => {
    const handlers = makeHandlers({ keep: vi.fn(async () => Promise.reject('disk write failed')) });
    await render(handlers);
    await click('.keep-copy__btn--keep');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('disk write failed');
  });

  it('evicts a managed copy through a two-step confirm', async () => {
    const handlers = makeHandlers({
      status: vi.fn(async () => status({ count: 1, entries: [managedRow()] })),
    });
    await render(handlers);
    await click('.keep-copy__btn--evict');
    // Confirm step appears before anything is removed.
    expect(container.querySelector('.keep-copy__confirm')?.textContent).toContain(
      'Remove the managed copy?',
    );
    expect(handlers.evict).not.toHaveBeenCalled();
    await click('.keep-copy__btn--danger');
    expect(handlers.evict).toHaveBeenCalledWith('v1');
    expect(badge()).toContain('Linked (original only)');
    expect(statusText()).toContain('Removed the managed copy');
  });

  it('cancels the evict confirm without removing anything', async () => {
    const handlers = makeHandlers({
      status: vi.fn(async () => status({ count: 1, entries: [managedRow()] })),
    });
    await render(handlers);
    await click('.keep-copy__btn--evict');
    // The Cancel button is the plain (non-danger) confirm button.
    await click('.keep-copy__confirm .keep-copy__btn:not(.keep-copy__btn--danger)');
    expect(handlers.evict).not.toHaveBeenCalled();
    expect(badge()).toContain('Managed copy');
    expect(container.querySelector('.keep-copy__btn--evict')).not.toBeNull();
  });

  it('surfaces an evict failure LOUDLY', async () => {
    const handlers = makeHandlers({
      status: vi.fn(async () => status({ count: 1, entries: [managedRow()] })),
      evict: vi.fn(async () => Promise.reject(new Error('no managed copy to evict'))),
    });
    await render(handlers);
    await click('.keep-copy__btn--evict');
    await click('.keep-copy__btn--danger');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'Could not remove the managed copy',
    );
  });

  it('does not setState after the control unmounts mid-status', async () => {
    let resolveStatus: (s: ManagedStatus) => void = () => {};
    const statusFn = vi.fn(() => new Promise<ManagedStatus>((res) => (resolveStatus = res)));
    await act(async () => {
      root.render(
        <KeepCopyControl videoId="v1" sourceExists handlers={makeHandlers({ status: statusFn })} />,
      );
    });
    await act(async () => root.unmount());
    await act(async () => resolveStatus(status()));
    await flush();
    expect(container.querySelector('.keep-copy')).toBeNull();
  });
});
