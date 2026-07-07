// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LibraryProvenance, type ProvenanceHandlers } from './LibraryProvenance';
import type { RevealResult, RevealSource } from '../lib/rpc';

const VIDEO = { id: 'v1', path: '/movies/talk.mp4', title: 'Talk' };

function source(over: Partial<RevealSource> = {}): RevealSource {
  return { id: 'v1', path: '/movies/talk.mp4', title: 'Talk', exists: true, relinkable: false, ...over };
}

function revealResult(over: Partial<RevealResult> = {}): RevealResult {
  return { id: 'v1', sources: [source()], missing: [], ...over };
}

function makeHandlers(over: Partial<ProvenanceHandlers> = {}): ProvenanceHandlers {
  return {
    reveal: vi.fn(async () => revealResult()),
    pinHash: vi.fn(async () => ({})),
    relink: vi.fn(async () => {}),
    openInFolder: vi.fn(async () => true),
    pickRelinkTarget: vi.fn(async () => '/moved/talk.mp4'),
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

async function render(handlers: ProvenanceHandlers): Promise<void> {
  await act(async () => {
    root.render(<LibraryProvenance video={VIDEO} handlers={handlers} />);
  });
  await flush();
}

function badge(): string {
  return container.querySelector('.library-provenance__badge')?.textContent ?? '';
}

function statusText(): string {
  return container.querySelector('.library-provenance__status')?.textContent ?? '';
}

async function click(selector: string): Promise<void> {
  const el = container.querySelector(selector) as HTMLButtonElement;
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

describe('LibraryProvenance', () => {
  it('always shows the full source path', async () => {
    await render(makeHandlers());
    expect(container.querySelector('.library-provenance__path')?.textContent).toBe('/movies/talk.mp4');
  });

  it('shows a Checking… badge until the reveal resolves', async () => {
    let resolveReveal: (r: RevealResult) => void = () => {};
    const reveal = vi.fn(() => new Promise<RevealResult>((res) => (resolveReveal = res)));
    await act(async () => {
      root.render(<LibraryProvenance video={VIDEO} handlers={makeHandlers({ reveal })} />);
    });
    expect(badge()).toContain('Checking…');

    await act(async () => resolveReveal(revealResult()));
    await flush();
    expect(badge()).toContain('On disk');
  });

  it('surfaces a reveal failure loudly (Error message)', async () => {
    await render(makeHandlers({ reveal: vi.fn(async () => Promise.reject(new Error('sidecar down'))) }));
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Could not check the source file');
    expect(alert?.textContent).toContain('sidecar down');
  });

  it('stringifies a non-Error reveal rejection', async () => {
    await render(makeHandlers({ reveal: vi.fn(async () => Promise.reject('boom-string')) }));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('boom-string');
  });

  it('shows "Source details unavailable" when the reveal has no source rows', async () => {
    await render(makeHandlers({ reveal: vi.fn(async () => revealResult({ sources: [] })) }));
    expect(badge()).toContain('Source details unavailable');
  });

  // ---- on-disk source -------------------------------------------------------

  it('shows On disk + Show in folder for a present source and does NOT re-pin when already relinkable', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
    });
    await render(handlers);
    expect(badge()).toContain('On disk');
    expect(container.querySelector('.library-provenance__btn')?.textContent).toContain('Show in folder');
    expect(handlers.pinHash).not.toHaveBeenCalled();
  });

  it('lazily pins the hash of a present, not-yet-relinkable source (pin-on-view back-fill)', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: false })] })),
    });
    await render(handlers);
    expect(handlers.pinHash).toHaveBeenCalledWith('v1');
    // The badge stays "On disk" through the pin.
    expect(badge()).toContain('On disk');
  });

  it('tolerates a pin-on-view failure (best-effort baseline, no crash)', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: false })] })),
      pinHash: vi.fn(async () => Promise.reject(new Error('hash read failed'))),
    });
    await render(handlers);
    expect(handlers.pinHash).toHaveBeenCalledWith('v1');
    expect(badge()).toContain('On disk');
    // The failure is swallowed as best-effort — no alert.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('opens the source location on Show in folder (success)', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
    });
    await render(handlers);
    await click('.library-provenance__btn');
    expect(handlers.openInFolder).toHaveBeenCalledWith('/movies/talk.mp4');
    expect(statusText()).toContain('Opened the source location');
  });

  it('reports a failed Show in folder (bridge returned false)', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
      openInFolder: vi.fn(async () => false),
    });
    await render(handlers);
    await click('.library-provenance__btn');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'Could not reveal the source location',
    );
  });

  it('says revealing is unavailable when the openInFolder bridge is absent', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
      openInFolder: undefined,
    });
    await render(handlers);
    await click('.library-provenance__btn');
    expect(statusText()).toContain('Revealing files is not available in this build');
  });

  // ---- missing source -------------------------------------------------------

  it('offers Relink… for a missing but relinkable source', async () => {
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: false, relinkable: true })], missing: ['/movies/talk.mp4'] })),
    });
    await render(handlers);
    expect(badge()).toContain('Missing');
    expect(container.querySelector('.library-provenance__btn--relink')?.textContent).toContain('Relink…');
    // A missing source is never pinned (nothing to hash).
    expect(handlers.pinHash).not.toHaveBeenCalled();
  });

  it('shows "relink unavailable" for a missing source with no pinned hash', async () => {
    await render(
      makeHandlers({
        reveal: vi.fn(async () => revealResult({ sources: [source({ exists: false, relinkable: false })], missing: ['/movies/talk.mp4'] })),
      }),
    );
    expect(badge()).toContain('Missing');
    expect(container.querySelector('.library-provenance__note')?.textContent).toContain(
      'Relink unavailable',
    );
    expect(container.querySelector('.library-provenance__btn--relink')).toBeNull();
  });

  function missingRelinkable(over: Partial<ProvenanceHandlers> = {}): ProvenanceHandlers {
    return makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: false, relinkable: true })], missing: ['/movies/talk.mp4'] })),
      ...over,
    });
  }

  it('relinks a moved source and flips the badge back to On disk', async () => {
    const handlers = missingRelinkable();
    await render(handlers);
    await click('.library-provenance__btn--relink');
    expect(handlers.pickRelinkTarget).toHaveBeenCalled();
    expect(handlers.relink).toHaveBeenCalledWith('v1', '/moved/talk.mp4');
    expect(badge()).toContain('On disk');
    expect(statusText()).toContain('Relinked and verified the source file');
    expect(container.querySelector('.library-provenance__path')?.textContent).toBe('/moved/talk.mp4');
  });

  it('surfaces a hash-mismatch relink refusal loudly', async () => {
    const handlers = missingRelinkable({
      relink: vi.fn(async () => Promise.reject(new Error('does not match the recorded content hash'))),
    });
    await render(handlers);
    await click('.library-provenance__btn--relink');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'does not match the recorded content hash',
    );
    // Still missing after a refused relink.
    expect(badge()).toContain('Missing');
  });

  it('does nothing when the relink picker is cancelled (null)', async () => {
    const handlers = missingRelinkable({ pickRelinkTarget: vi.fn(async () => null) });
    await render(handlers);
    await click('.library-provenance__btn--relink');
    expect(handlers.relink).not.toHaveBeenCalled();
    expect(container.querySelector('.library-provenance__status')).toBeNull();
    expect(badge()).toContain('Missing');
  });

  it('says relinking is unavailable when the picker bridge is absent', async () => {
    const handlers = missingRelinkable({ pickRelinkTarget: undefined });
    await render(handlers);
    await click('.library-provenance__btn--relink');
    expect(statusText()).toContain('Relinking is not available in this build');
    expect(handlers.relink).not.toHaveBeenCalled();
  });

  // ---- WU-3b2: the opt-in keep-a-copy control ------------------------------

  it('renders the keep-a-copy control when the managed handlers are wired', async () => {
    const managed = {
      status: vi.fn(async () => ({ sizeBytes: 0, capBytes: 1, count: 0, entries: [] })),
      keep: vi.fn(),
      evict: vi.fn(),
    };
    const handlers = makeHandlers({
      reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
      managed,
    });
    await render(handlers);
    expect(container.querySelector('.keep-copy')).not.toBeNull();
    // The control reads the store snapshot to learn this video's managed state.
    expect(managed.status).toHaveBeenCalled();
    // An on-disk, un-managed source offers the opt-in.
    expect(container.querySelector('.keep-copy__btn--keep')).not.toBeNull();
  });

  it('omits the keep-a-copy control when no managed handlers are wired', async () => {
    await render(
      makeHandlers({
        reveal: vi.fn(async () => revealResult({ sources: [source({ exists: true, relinkable: true })] })),
      }),
    );
    expect(container.querySelector('.keep-copy')).toBeNull();
  });

  it('does not setState after the card unmounts mid-reveal', async () => {
    let resolveReveal: (r: RevealResult) => void = () => {};
    const reveal = vi.fn(() => new Promise<RevealResult>((res) => (resolveReveal = res)));
    await act(async () => {
      root.render(<LibraryProvenance video={VIDEO} handlers={makeHandlers({ reveal })} />);
    });
    // Unmount before the reveal resolves, then resolve — applyPhase must no-op.
    await act(async () => root.unmount());
    await act(async () => resolveReveal(revealResult()));
    await flush();
    // Nothing rendered (unmounted) and no crash.
    expect(container.querySelector('.library-provenance')).toBeNull();
  });
});
