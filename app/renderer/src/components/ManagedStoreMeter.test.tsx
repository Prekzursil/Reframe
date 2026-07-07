// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ManagedStoreMeter, type ManagedStoreRpc } from './ManagedStoreMeter';
import type { ManagedCopy, ManagedStatus } from '../lib/rpc';

const GB = 1024 ** 3;
const MB = 1024 ** 2;
const KB = 1024;

function row(over: Partial<ManagedCopy> = {}): ManagedCopy {
  return {
    entityId: 'v1',
    originalPath: '/movies/one.mp4',
    managedPath: '/data/managed-copies/abc.mp4',
    contentHash: 'blake3:abc',
    sizeBytes: 2 * GB,
    keptAt: '2026-07-07T00:00:00Z',
    lastAccess: '2026-07-07T00:00:00Z',
    ...over,
  };
}

function status(over: Partial<ManagedStatus> = {}): ManagedStatus {
  return { sizeBytes: 5 * GB, capBytes: 20 * GB, count: 2, entries: [], ...over };
}

const twoEntries: ManagedCopy[] = [
  row({ entityId: 'v1', originalPath: '/movies/one.mp4', sizeBytes: 2 * GB }),
  row({ entityId: 'v2', originalPath: '/movies/two.mp4', sizeBytes: 3 * GB }),
];

function makeRpc(over: Partial<ManagedStoreRpc> = {}): ManagedStoreRpc {
  return {
    managedStatus: vi.fn(async () => status({ count: 2, entries: twoEntries })),
    managedEvict: vi.fn(async () => ({ ok: true, entityId: 'v1' })),
    managedClear: vi.fn(async () => ({ ok: true, cleared: 2 })),
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

async function flush(turns = 10): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) await Promise.resolve();
  });
}

async function render(rpc: ManagedStoreRpc): Promise<void> {
  await act(async () => {
    root.render(<ManagedStoreMeter rpc={rpc} />);
  });
  await flush();
}

function readout(): string {
  return container.querySelector('.managed-meter__readout')?.textContent ?? '';
}

async function click(selector: string): Promise<void> {
  const el = container.querySelector(selector) as HTMLButtonElement;
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

describe('ManagedStoreMeter', () => {
  it('shows a loading line until the snapshot resolves', async () => {
    let resolve: (s: ManagedStatus) => void = () => {};
    const statusFn = vi.fn(() => new Promise<ManagedStatus>((res) => (resolve = res)));
    await act(async () => {
      root.render(<ManagedStoreMeter rpc={makeRpc({ managedStatus: statusFn })} />);
    });
    expect(container.querySelector('.managed-meter__loading')?.textContent).toContain(
      'Loading managed copies…',
    );
    await act(async () => resolve(status({ count: 0, entries: [] })));
    await flush();
    expect(container.querySelector('.managed-meter__loading')).toBeNull();
  });

  it('renders the used/cap gauge with the copy count and a proportional fill', async () => {
    await render(makeRpc());
    expect(readout()).toContain('5.0 GB');
    expect(readout()).toContain('20.0 GB');
    expect(readout()).toContain('2 copies');
    const fill = container.querySelector('.managed-meter__fill') as HTMLElement;
    expect(fill.style.width).toBe('25%'); // 5 / 20
  });

  it('caps the fill at 100% when the store is over cap', async () => {
    await render(makeRpc({ managedStatus: vi.fn(async () => status({ sizeBytes: 30 * GB, count: 0, entries: [] })) }));
    const fill = container.querySelector('.managed-meter__fill') as HTMLElement;
    expect(fill.style.width).toBe('100%');
  });

  it('reads 0% fill when the cap is zero (no divide-by-zero)', async () => {
    await render(makeRpc({ managedStatus: vi.fn(async () => status({ sizeBytes: 0, capBytes: 0, count: 0, entries: [] })) }));
    const fill = container.querySelector('.managed-meter__fill') as HTMLElement;
    expect(fill.style.width).toBe('0%');
    expect(readout()).toContain('0 B');
  });

  it('formats byte sizes across B / KB / MB units', async () => {
    await render(
      makeRpc({
        managedStatus: vi.fn(async () =>
          status({
            count: 3,
            entries: [
              row({ entityId: 'a', originalPath: '/x/a.mp4', sizeBytes: 512 }),
              row({ entityId: 'b', originalPath: '/x/b.mp4', sizeBytes: 3 * KB }),
              row({ entityId: 'c', originalPath: '/x/c.mp4', sizeBytes: 5 * MB }),
            ],
          }),
        ),
      }),
    );
    const sizes = [...container.querySelectorAll('.managed-meter__row-size')].map((e) => e.textContent);
    expect(sizes).toEqual(['512 B', '3.0 KB', '5.0 MB']);
  });

  it('falls back to the whole path for a name-less (trailing-slash) source', async () => {
    await render(
      makeRpc({
        managedStatus: vi.fn(async () =>
          status({ count: 1, entries: [row({ entityId: 'v1', originalPath: '/weird/dir/' })] }),
        ),
      }),
    );
    expect(container.querySelector('.managed-meter__row-name')?.textContent).toBe('/weird/dir/');
  });

  it('shows the empty state when no copies are kept', async () => {
    await render(makeRpc({ managedStatus: vi.fn(async () => status({ sizeBytes: 0, count: 0, entries: [] })) }));
    expect(container.querySelector('.managed-meter__empty')?.textContent).toContain(
      'No managed copies yet',
    );
    expect(container.querySelector('.managed-meter__list')).toBeNull();
  });

  it('uses the singular "1 copy" label + count in the clear-all confirm', async () => {
    const rpc = makeRpc({ managedStatus: vi.fn(async () => status({ count: 1, entries: [row()] })) });
    await render(rpc);
    expect(readout()).toContain('1 copy');
    await click('.managed-meter__btn--clear');
    expect(container.querySelector('.managed-meter__actions .managed-meter__confirm')?.textContent).toContain(
      'Remove all 1 managed copies?',
    );
  });

  it('surfaces a snapshot-read failure LOUDLY (and shows no gauge)', async () => {
    await render(makeRpc({ managedStatus: vi.fn(async () => Promise.reject(new Error('sidecar offline'))) }));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar offline');
    expect(container.querySelector('.managed-meter__gauge')).toBeNull();
    expect(container.querySelector('.managed-meter__loading')).toBeNull();
  });

  it('evicts one copy through a two-step confirm and refreshes the gauge', async () => {
    const statusFn = vi
      .fn<() => Promise<ManagedStatus>>()
      .mockResolvedValueOnce(status({ count: 2, entries: twoEntries }))
      .mockResolvedValue(status({ sizeBytes: 3 * GB, count: 1, entries: [twoEntries[1]] }));
    const rpc = makeRpc({ managedStatus: statusFn });
    await render(rpc);

    await click('.managed-meter__row .managed-meter__btn--evict');
    expect(container.querySelector('.managed-meter__row .managed-meter__confirm')?.textContent).toContain(
      'Remove copy?',
    );
    expect(rpc.managedEvict).not.toHaveBeenCalled();

    await click('.managed-meter__row .managed-meter__confirm .managed-meter__btn--danger');
    expect(rpc.managedEvict).toHaveBeenCalledWith('v1');
    // The gauge re-read reflects the freed copy.
    expect(readout()).toContain('1 copy');
  });

  it('cancels a per-copy evict confirm without removing anything', async () => {
    const rpc = makeRpc();
    await render(rpc);
    await click('.managed-meter__row .managed-meter__btn--evict');
    await click('.managed-meter__row .managed-meter__confirm .managed-meter__btn:not(.managed-meter__btn--danger)');
    expect(rpc.managedEvict).not.toHaveBeenCalled();
    expect(container.querySelector('.managed-meter__row .managed-meter__btn--evict')).not.toBeNull();
  });

  it('surfaces an evict failure LOUDLY', async () => {
    const rpc = makeRpc({ managedEvict: vi.fn(async () => Promise.reject('cannot evict')) });
    await render(rpc);
    await click('.managed-meter__row .managed-meter__btn--evict');
    await click('.managed-meter__row .managed-meter__confirm .managed-meter__btn--danger');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('cannot evict');
  });

  it('clears all copies through a confirm and refreshes to empty', async () => {
    const statusFn = vi
      .fn<() => Promise<ManagedStatus>>()
      .mockResolvedValueOnce(status({ count: 2, entries: twoEntries }))
      .mockResolvedValue(status({ sizeBytes: 0, count: 0, entries: [] }));
    const rpc = makeRpc({ managedStatus: statusFn });
    await render(rpc);

    await click('.managed-meter__btn--clear');
    await click('.managed-meter__actions .managed-meter__btn--danger');
    expect(rpc.managedClear).toHaveBeenCalled();
    expect(container.querySelector('.managed-meter__empty')).not.toBeNull();
  });

  it('cancels the clear-all confirm', async () => {
    const rpc = makeRpc();
    await render(rpc);
    await click('.managed-meter__btn--clear');
    await click('.managed-meter__actions .managed-meter__btn:not(.managed-meter__btn--danger)');
    expect(rpc.managedClear).not.toHaveBeenCalled();
    expect(container.querySelector('.managed-meter__btn--clear')).not.toBeNull();
  });

  it('surfaces a clear failure LOUDLY', async () => {
    const rpc = makeRpc({ managedClear: vi.fn(async () => Promise.reject(new Error('clear blew up'))) });
    await render(rpc);
    await click('.managed-meter__btn--clear');
    await click('.managed-meter__actions .managed-meter__btn--danger');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('clear blew up');
  });

  it('does not setState after the panel unmounts mid-load', async () => {
    let resolve: (s: ManagedStatus) => void = () => {};
    const statusFn = vi.fn(() => new Promise<ManagedStatus>((res) => (resolve = res)));
    await act(async () => {
      root.render(<ManagedStoreMeter rpc={makeRpc({ managedStatus: statusFn })} />);
    });
    await act(async () => root.unmount());
    await act(async () => resolve(status()));
    await flush();
    expect(container.querySelector('.managed-meter')).toBeNull();
  });
});
