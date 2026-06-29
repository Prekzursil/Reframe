// LineagePanel.test.tsx — the L4 asset-detail lineage drawer.
// Covers: the loading -> loaded transition (card + "Made from"/"Used to make"
// expanders with counts), missing/titled/untitled node text, empty relations,
// the LOUD error path (Error + non-Error rejections, role="alert"), the close
// button, and the unmount-before-settle guard (no setState after unmount) for
// both the resolve and reject branches.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LineagePanel } from './LineagePanel';
import type { LineageEntity, LineageNode, LineageResult } from '../lib/rpc';

function entity(over: Partial<LineageEntity> = {}): LineageEntity {
  return {
    id: 'clip1',
    kind: 'short',
    role: 'output',
    path: '/x/clip.mp4',
    title: 'My clip',
    addedAt: '2026-06-29T12:00:00Z',
    durationSec: 30,
    contentHash: null,
    hasTranscript: false,
    thumbnailPath: '',
    ...over,
  };
}

function result(over: Partial<LineageResult> = {}): LineageResult {
  return {
    id: 'clip1',
    entity: entity(),
    ancestors: [],
    descendants: [],
    provenance: null,
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

const ASSET = { id: 'clip1', title: 'My clip' };

async function flush(turns = 4): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) {
      await Promise.resolve();
    }
  });
}

function mount(loadLineage: (id: string) => Promise<LineageResult>, onClose = vi.fn()): void {
  act(() => {
    root.render(<LineagePanel asset={ASSET} loadLineage={loadLineage} onClose={onClose} />);
  });
}

describe('<LineagePanel />', () => {
  it('shows the loading note before the lineage resolves', () => {
    mount(() => new Promise<LineageResult>(() => {}));
    expect(container.querySelector('.lineage-panel__loading')?.textContent).toContain(
      'Loading history…',
    );
    expect(container.querySelector('.lineage-panel')?.getAttribute('aria-label')).toBe(
      'Lineage of My clip',
    );
  });

  it('renders the card plus "Made from" / "Used to make" expanders once loaded', async () => {
    const ancestors: LineageNode[] = [
      entity({ id: 'src', title: 'Source talk' }),
      { id: 'ghost', missing: true },
      entity({ id: 'untitled', title: '' }),
    ];
    const descendants: LineageNode[] = [];
    mount(() => Promise.resolve(result({ ancestors, descendants, provenance: null })));
    await flush();

    // The card rendered (raw source note, since provenance is null).
    expect(container.querySelector('.lineage-card')).not.toBeNull();

    const rels = container.querySelectorAll('.lineage-panel__rel');
    expect(rels.length).toBe(2);
    // "Made from (3)" — a resolved-titled node, a missing stub, an untitled node.
    const madeFrom = rels[0];
    expect(madeFrom.querySelector('.lineage-panel__rel-summary')?.textContent).toContain(
      'Made from (3)',
    );
    const items = madeFrom.querySelectorAll('.lineage-panel__rel-item');
    expect(items[0].textContent).toBe('Source talk');
    expect(items[1].textContent).toContain('ghost — no longer in your library');
    expect(items[1].className).toContain('lineage-panel__rel-item--missing');
    // Untitled node falls back to its id.
    expect(items[2].textContent).toBe('untitled');

    // "Used to make (0)" — empty -> the "Nothing yet" note, no list.
    const usedToMake = rels[1];
    expect(usedToMake.querySelector('.lineage-panel__rel-summary')?.textContent).toContain(
      'Used to make (0)',
    );
    expect(usedToMake.querySelector('.lineage-panel__rel-empty')?.textContent).toBe('Nothing yet.');
    expect(usedToMake.querySelector('.lineage-panel__rel-list')).toBeNull();
  });

  it('surfaces an Error rejection loudly (role="alert")', async () => {
    mount(() => Promise.reject(new Error('sidecar down')));
    await flush();
    const alert = container.querySelector('.lineage-panel__error');
    expect(alert?.getAttribute('role')).toBe('alert');
    expect(alert?.textContent).toContain('Could not load history: sidecar down');
  });

  it('stringifies a non-Error rejection', async () => {
    mount(() => Promise.reject('plain failure'));
    await flush();
    expect(container.querySelector('.lineage-panel__error')?.textContent).toContain(
      'plain failure',
    );
  });

  it('calls onClose when the × button is clicked', async () => {
    const onClose = vi.fn();
    mount(() => Promise.resolve(result()), onClose);
    await flush();
    const close = container.querySelector('.lineage-panel__close') as HTMLButtonElement;
    await act(async () => {
      close.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not setState after unmount when the load resolves late', async () => {
    let resolveLate: (r: LineageResult) => void = () => {};
    mount(() => new Promise<LineageResult>((res) => (resolveLate = res)));
    // Unmount while the fetch is still pending -> the effect cleanup sets live=false.
    act(() => root.unmount());
    // Resolving now hits the `if (live)` false arm; must not throw / warn.
    await act(async () => {
      resolveLate(result());
      await Promise.resolve();
    });
    // Re-create a root so afterEach's unmount is a no-op-safe call.
    root = createRoot(container);
  });

  it('does not setState after unmount when the load rejects late', async () => {
    let rejectLate: (e: unknown) => void = () => {};
    mount(() => new Promise<LineageResult>((_res, rej) => (rejectLate = rej)));
    act(() => root.unmount());
    await act(async () => {
      rejectLate(new Error('too late'));
      await Promise.resolve();
    });
    root = createRoot(container);
  });
});
