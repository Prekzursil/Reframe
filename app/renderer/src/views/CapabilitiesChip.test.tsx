// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { CapabilitiesChip } from './CapabilitiesChip';
import type { ReadinessItem } from '../lib/rpc';

function items(): ReadinessItem[] {
  return [
    { capability: 'a', label: 'Transcribe speech', status: 'ready', blockedBy: '', action: null },
    { capability: 'b', label: 'Follow the speaker', status: 'ready', blockedBy: '', action: null },
    {
      capability: 'c',
      label: 'Translate captions',
      status: 'needsKey',
      blockedBy: 'no key',
      action: { kind: 'openProviders' },
    },
  ];
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
  delete (window as { api?: unknown }).api;
});

async function flush(turns = 6): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) await Promise.resolve();
  });
}

function toggle(): HTMLButtonElement {
  return container.querySelector('.capabilities-chip__toggle') as HTMLButtonElement;
}

function stubClient(summary: () => Promise<{ items: ReadinessItem[] }>) {
  return { readiness: { summary } };
}

describe('CapabilitiesChip', () => {
  it('binds the noun + a ready/total count separate from the card count', async () => {
    await act(async () => {
      root.render(<CapabilitiesChip rpcClient={stubClient(async () => ({ items: items() }))} />);
    });
    await flush();
    // 2 of 3 ready — the plumbing count, not the visible-card count.
    expect(toggle().textContent).toContain('Capabilities: 2 of 3 installed');
    expect(toggle().getAttribute('aria-expanded')).toBe('false');
    expect(toggle().disabled).toBe(false);
    // Collapsed by default — no rows yet.
    expect(container.querySelector('.capabilities-chip__list')).toBeNull();
  });

  it('discloses the readiness rows on expand and forwards a fix action', async () => {
    const onAction = vi.fn();
    await act(async () => {
      root.render(
        <CapabilitiesChip
          rpcClient={stubClient(async () => ({ items: items() }))}
          onAction={onAction}
        />,
      );
    });
    await flush();

    await act(async () => {
      toggle().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(toggle().getAttribute('aria-expanded')).toBe('true');
    const rows = container.querySelectorAll('.capabilities-chip__row');
    expect(rows.length).toBe(3);
    expect(container.textContent).toContain('Follow the speaker');

    const fix = container.querySelector('button.readiness-badge__action') as HTMLButtonElement;
    await act(async () => {
      fix.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onAction).toHaveBeenCalledWith({ kind: 'openProviders' });

    // Collapses again.
    await act(async () => {
      toggle().dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.querySelector('.capabilities-chip__list')).toBeNull();
  });

  it('reports "none" and disables the toggle when no capabilities exist', async () => {
    await act(async () => {
      root.render(<CapabilitiesChip rpcClient={stubClient(async () => ({ items: [] }))} />);
    });
    await flush();
    expect(toggle().textContent).toContain('Capabilities: none reported');
    expect(toggle().disabled).toBe(true);
  });

  it('treats a summary without an items array as empty', async () => {
    await act(async () => {
      root.render(
        <CapabilitiesChip rpcClient={stubClient(async () => ({}) as { items: ReadinessItem[] })} />,
      );
    });
    await flush();
    expect(toggle().textContent).toContain('none reported');
  });

  it('shows a checking… busy state while the summary is in flight', async () => {
    let resolve: (v: { items: ReadinessItem[] }) => void = () => {};
    await act(async () => {
      root.render(
        <CapabilitiesChip
          rpcClient={stubClient(
            () =>
              new Promise((r) => {
                resolve = r;
              }),
          )}
        />,
      );
    });
    // Pending: checking + aria-busy + disabled.
    expect(toggle().textContent).toContain('Capabilities: checking…');
    expect(toggle().getAttribute('aria-busy')).toBe('true');
    expect(toggle().disabled).toBe(true);
    await act(async () => {
      resolve({ items: items() });
    });
    await flush();
    expect(toggle().textContent).toContain('2 of 3 installed');
  });

  it('degrades to an inline alert when the summary rejects', async () => {
    await act(async () => {
      root.render(
        <CapabilitiesChip
          rpcClient={stubClient(async () => {
            throw new Error('summary boom');
          })}
        />,
      );
    });
    await flush();
    expect(toggle().textContent).toContain('Capabilities: unavailable');
    expect(container.querySelector('.capabilities-chip__error')?.textContent).toContain(
      'summary boom',
    );
  });

  it('catches a SYNCHRONOUS bridge throw (missing preload) without a blank screen', async () => {
    await act(async () => {
      root.render(
        <CapabilitiesChip
          rpcClient={stubClient(() => {
            throw new Error('window.api bridge is not available');
          })}
        />,
      );
    });
    await flush();
    expect(container.querySelector('.capabilities-chip__error')?.textContent).toContain(
      'bridge is not available',
    );
    expect(toggle().getAttribute('aria-busy')).toBe('false');
  });

  it('defaults to the real lib/rpc client when none is injected', async () => {
    // No rpcClient -> the `?? client` default runs; stub window.api so the real
    // client.readiness.summary() resolves through the bridge.
    (window as { api?: unknown }).api = {
      rpc: async (method: string) => (method === 'readiness.summary' ? { items: items() } : {}),
    };
    await act(async () => {
      root.render(<CapabilitiesChip />);
    });
    await flush();
    expect(toggle().textContent).toContain('2 of 3 installed');
  });

  it('stringifies a non-Error rejection', async () => {
    await act(async () => {
      root.render(
        <CapabilitiesChip
          rpcClient={stubClient(async () => {
            throw 'plain failure';
          })}
        />,
      );
    });
    await flush();
    expect(container.querySelector('.capabilities-chip__error')?.textContent).toContain(
      'plain failure',
    );
  });
});
