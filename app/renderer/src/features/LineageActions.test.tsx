// LineageActions.test.tsx — the L5 reveal / regenerate / relink action row.
// Covers: reveal (no source / missing-source / open-ok / open-failed / reveal
// unavailable), regenerate (ready -> re-dispatch / not-ready -> relink offered),
// relink (unavailable / cancelled / verified), the LOUD error path (Error +
// non-Error throws, role="alert"), and the idle/status render branches.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LineageActions, type LineageActionHandlers } from './LineageActions';
import type { RegenerateResult, RevealResult } from '../lib/rpc';

const ASSET = { id: 'clip1', title: 'My clip' };

function revealResult(over: Partial<RevealResult> = {}): RevealResult {
  return {
    id: 'clip1',
    sources: [{ id: 'src1', path: '/movies/talk.mp4', title: 'Talk', exists: true }],
    missing: [],
    ...over,
  };
}

function regenResult(over: Partial<RegenerateResult> = {}): RegenerateResult {
  return {
    id: 'clip1',
    op: 'shorts.select',
    params: { preset: 'punchy' },
    missing: [],
    ready: true,
    ...over,
  };
}

function handlers(over: Partial<LineageActionHandlers> = {}): LineageActionHandlers {
  return {
    reveal: vi.fn(async () => revealResult()),
    regenerate: vi.fn(async () => regenResult()),
    runRegenerate: vi.fn(async () => undefined),
    relink: vi.fn(async () => undefined),
    openInFolder: vi.fn(async () => true),
    pickRelinkTarget: vi.fn(async () => '/new/talk.mp4'),
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

async function flush(turns = 4): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) {
      await Promise.resolve();
    }
  });
}

function mount(actions: LineageActionHandlers): void {
  act(() => {
    root.render(<LineageActions asset={ASSET} actions={actions} />);
  });
}

function btn(label: string): HTMLButtonElement {
  const found = Array.from(container.querySelectorAll('button')).find(
    (b) => b.textContent === label,
  );
  if (!found) throw new Error(`button not found: ${label}`);
  return found as HTMLButtonElement;
}

function relinkBtn(): HTMLButtonElement | null {
  return container.querySelector('.lineage-actions__btn--relink');
}

function statusEl(): HTMLElement | null {
  return container.querySelector('.lineage-actions__status');
}

async function click(el: HTMLElement): Promise<void> {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

describe('<LineageActions />', () => {
  it('renders the two action buttons and no status initially', () => {
    mount(handlers());
    expect(btn('Reveal source')).not.toBeNull();
    expect(btn('Regenerate')).not.toBeNull();
    expect(relinkBtn()).toBeNull();
    expect(statusEl()).toBeNull();
  });

  // ---- reveal -------------------------------------------------------------
  it('reveal opens the present source in the OS file explorer', async () => {
    const h = handlers();
    mount(h);
    await click(btn('Reveal source'));
    expect(h.reveal).toHaveBeenCalledWith('clip1');
    expect(h.openInFolder).toHaveBeenCalledWith('/movies/talk.mp4');
    expect(statusEl()?.textContent).toBe('Opened the source location.');
    expect(statusEl()?.getAttribute('role')).toBe('status');
  });

  it('reveal reports when the OS reveal fails', async () => {
    const h = handlers({ openInFolder: vi.fn(async () => false) });
    mount(h);
    await click(btn('Reveal source'));
    expect(statusEl()?.textContent).toBe('Could not reveal the source location.');
    expect(statusEl()?.getAttribute('role')).toBe('alert');
  });

  it('reveal reports when revealing is unavailable in this build', async () => {
    const h = handlers({ openInFolder: undefined });
    mount(h);
    await click(btn('Reveal source'));
    expect(statusEl()?.textContent).toBe('Revealing files is not available in this build.');
  });

  it('reveal reports an item with no source on record', async () => {
    const h = handlers({ reveal: vi.fn(async () => revealResult({ sources: [] })) });
    mount(h);
    await click(btn('Reveal source'));
    expect(statusEl()?.textContent).toBe('This item has no source file on record.');
    expect(relinkBtn()).toBeNull();
  });

  it('reveal surfaces a missing source loudly and offers Relink…', async () => {
    const h = handlers({
      reveal: vi.fn(async () =>
        revealResult({
          sources: [{ id: 'src1', path: '/gone/talk.mp4', title: 'Talk', exists: false }],
          missing: ['/gone/talk.mp4'],
        }),
      ),
    });
    mount(h);
    await click(btn('Reveal source'));
    expect(statusEl()?.getAttribute('role')).toBe('alert');
    expect(statusEl()?.textContent).toContain('/gone/talk.mp4');
    expect(relinkBtn()).not.toBeNull();
  });

  // ---- regenerate ---------------------------------------------------------
  it('regenerate re-dispatches the producing op when the source is present', async () => {
    const h = handlers();
    mount(h);
    await click(btn('Regenerate'));
    expect(h.regenerate).toHaveBeenCalledWith('clip1');
    expect(h.runRegenerate).toHaveBeenCalledWith(regenResult());
    expect(statusEl()?.textContent).toBe('Regenerating from the original source…');
  });

  it('regenerate refuses and offers Relink… when the source is missing', async () => {
    const h = handlers({
      regenerate: vi.fn(async () => regenResult({ ready: false, missing: ['/gone/talk.mp4'] })),
    });
    mount(h);
    await click(btn('Regenerate'));
    expect(h.runRegenerate).not.toHaveBeenCalled();
    expect(statusEl()?.getAttribute('role')).toBe('alert');
    expect(relinkBtn()).not.toBeNull();
  });

  // ---- relink -------------------------------------------------------------
  it('relink verifies and re-points the chosen file', async () => {
    const h = handlers({
      regenerate: vi.fn(async () => regenResult({ ready: false, missing: ['/gone/talk.mp4'] })),
    });
    mount(h);
    await click(btn('Regenerate')); // surfaces Relink…
    const relink = relinkBtn();
    expect(relink).not.toBeNull();
    await click(relink as HTMLButtonElement);
    expect(h.pickRelinkTarget).toHaveBeenCalled();
    expect(h.relink).toHaveBeenCalledWith('clip1', '/new/talk.mp4');
    expect(statusEl()?.textContent).toBe('Relinked and verified the source file.');
    expect(relinkBtn()).toBeNull(); // cleared after a successful relink
  });

  it('relink is a no-op when the picker is cancelled', async () => {
    const h = handlers({
      regenerate: vi.fn(async () => regenResult({ ready: false, missing: ['/gone/talk.mp4'] })),
      pickRelinkTarget: vi.fn(async () => null),
    });
    mount(h);
    await click(btn('Regenerate'));
    await click(relinkBtn() as HTMLButtonElement);
    expect(h.relink).not.toHaveBeenCalled();
    // The relink button stays (the missing source is still unresolved).
    expect(relinkBtn()).not.toBeNull();
  });

  it('relink reports when relinking is unavailable in this build', async () => {
    const h = handlers({
      regenerate: vi.fn(async () => regenResult({ ready: false, missing: ['/gone/talk.mp4'] })),
      pickRelinkTarget: undefined,
    });
    mount(h);
    await click(btn('Regenerate'));
    await click(relinkBtn() as HTMLButtonElement);
    expect(statusEl()?.textContent).toBe('Relinking is not available in this build.');
  });

  // ---- loud error path ----------------------------------------------------
  it('surfaces an Error throw loudly (role=alert)', async () => {
    const h = handlers({
      reveal: vi.fn(async () => {
        throw new Error('boom');
      }),
    });
    mount(h);
    await click(btn('Reveal source'));
    expect(statusEl()?.getAttribute('role')).toBe('alert');
    expect(statusEl()?.textContent).toBe('boom');
  });

  it('surfaces a non-Error throw via String()', async () => {
    const h = handlers({
      regenerate: vi.fn(async () => {
        throw 'plain string';
      }),
    });
    mount(h);
    await click(btn('Regenerate'));
    expect(statusEl()?.textContent).toBe('plain string');
  });
});
