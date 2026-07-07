// ReadinessRollup.test.tsx — the unified readiness roll-up consumer (WU-14).
//
// Wires `readiness.summary` (WU-8) into a reusable section that renders one
// <ReadinessBadge /> (WU-9) per capability with its capability-tied action
// button. Pins the falsifiable WU-14 acceptance: N badges for N items, each with
// its action button; the reused in-flight skeleton shows before data resolves;
// actions forward to the parent; failures degrade to a quiet error (never crash).
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { ReadinessRollup } from './ReadinessRollup';
import { READINESS_LABEL } from './readinessMeta';
import type { ReadinessAction, ReadinessItem } from '../lib/rpc';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

/** A minimal typed client stub exposing only `readiness.summary`. */
function makeClient(summary: () => Promise<{ items: ReadinessItem[] }>) {
  return { readiness: { summary: vi.fn(summary) } } as unknown as Parameters<
    typeof ReadinessRollup
  >[0]['rpcClient'];
}

async function flush(turns = 4): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) await Promise.resolve();
  });
}

function makeItem(over: Partial<ReadinessItem> = {}): ReadinessItem {
  return {
    capability: 'tier1-multimodal',
    label: 'Tier 1 multimodal',
    status: 'ready',
    blockedBy: '',
    action: null,
    ...over,
  };
}

describe('<ReadinessRollup /> — WU-14 wiring', () => {
  it('renders one ReadinessBadge per readiness.summary item', async () => {
    const items = [
      makeItem({ capability: 'a', label: 'Captions', status: 'ready' }),
      makeItem({
        capability: 'b',
        label: 'Vision',
        status: 'needsDownload',
        blockedBy: 'saliency missing',
        action: { kind: 'assets.ensure', assets: ['saliency'] },
      }),
      makeItem({
        capability: 'c',
        label: 'Translation',
        status: 'needsKey',
        action: { kind: 'openProviders' },
      }),
    ];
    const rpcClient = makeClient(() => Promise.resolve({ items }));

    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();

    const badges = container.querySelectorAll('[role="status"]');
    expect(badges.length).toBe(3);
    expect(badges[0].textContent).toBe(READINESS_LABEL.ready);
    expect(badges[1].textContent).toBe(READINESS_LABEL.needsDownload);
    expect(badges[2].textContent).toBe(READINESS_LABEL.needsKey);
    // One row per item, labelled by the capability name.
    expect(container.textContent).toContain('Captions');
    expect(container.textContent).toContain('Vision');
    expect(container.textContent).toContain('Translation');
  });

  it('renders an action button only for items that carry a fix action', async () => {
    const items = [
      makeItem({ capability: 'ready', label: 'Ready cap', status: 'ready', action: null }),
      makeItem({
        capability: 'fix',
        label: 'Vision',
        status: 'needsDownload',
        action: { kind: 'assets.ensure', assets: ['saliency'] },
      }),
    ];
    const rpcClient = makeClient(() => Promise.resolve({ items }));

    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();

    const buttons = container.querySelectorAll('button.readiness-badge__action');
    expect(buttons.length).toBe(1);
    expect(buttons[0].getAttribute('aria-label')).toBe('Download Vision model');
  });

  it('shows the reused in-flight skeleton before the data resolves', async () => {
    let resolve: (v: { items: ReadinessItem[] }) => void = () => {};
    const rpcClient = makeClient(
      () =>
        new Promise<{ items: ReadinessItem[] }>((res) => {
          resolve = res;
        }),
    );

    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    // Mid-flight: the reused skeleton (jobqueue empty convention) is showing.
    expect(container.querySelector('.jobqueue__empty')).not.toBeNull();
    expect(container.querySelectorAll('[role="status"]').length).toBe(0);

    await act(async () => {
      resolve({ items: [makeItem({ label: 'Captions' })] });
    });
    await flush();

    expect(container.querySelector('.jobqueue__empty')).toBeNull();
    expect(container.querySelectorAll('[role="status"]').length).toBe(1);
  });

  it('forwards a badge action click to onAction', async () => {
    const action: ReadinessAction = { kind: 'openProviders' };
    const items = [makeItem({ label: 'Translation', status: 'needsKey', action })];
    const rpcClient = makeClient(() => Promise.resolve({ items }));
    let received: ReadinessAction | null = null;

    await act(async () => {
      root.render(
        <ReadinessRollup
          rpcClient={rpcClient}
          onAction={(a) => {
            received = a;
          }}
        />,
      );
    });
    await flush();

    const button = container.querySelector('button.readiness-badge__action') as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(received).toBe(action);
  });

  it('renders an empty-state line when there are no readiness items', async () => {
    const rpcClient = makeClient(() => Promise.resolve({ items: [] }));
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();
    expect(container.querySelector('.jobqueue__empty')).toBeNull();
    expect(container.querySelectorAll('[role="status"]').length).toBe(0);
    expect(container.textContent).toContain('Nothing to report');
  });

  it('tolerates a result with no items field (treats it as empty)', async () => {
    const rpcClient = makeClient(() => Promise.resolve({}) as Promise<{ items: ReadinessItem[] }>);
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();
    expect(container.querySelectorAll('[role="status"]').length).toBe(0);
    expect(container.textContent).toContain('Nothing to report');
  });

  it('surfaces a load error without crashing (Error instance)', async () => {
    const rpcClient = makeClient(() => Promise.reject(new Error('sidecar down')));
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar down');
    expect(container.querySelector('.jobqueue__empty')).toBeNull();
  });

  it('stringifies a non-Error load rejection', async () => {
    const rpcClient = makeClient(() => Promise.reject('plain failure'));
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain failure');
  });

  it('renders a custom title when provided', async () => {
    const rpcClient = makeClient(() => Promise.resolve({ items: [makeItem()] }));
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} title="What works right now" />);
    });
    await flush();
    expect(container.textContent).toContain('What works right now');
  });

  it('degrades to an inline error (no thrown-through blank) when window.api is missing', async () => {
    // WU2 resilience: with no injected rpcClient the component uses the real
    // `client`, whose bridge() throws SYNCHRONOUSLY when window.api is undefined.
    // That sync throw escapes the effect's `.catch()`; the sync-safe guard must
    // surface it inline instead of letting it unmount the tree.
    expect((globalThis as { window?: { api?: unknown } }).window?.api).toBeUndefined();
    await act(async () => {
      root.render(<ReadinessRollup />);
    });
    await flush();
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('window.api');
    expect(container.querySelector('.jobqueue__empty')).toBeNull();
  });

  it('ignores a late resolve after unmount (no state update warning)', async () => {
    let resolve: (v: { items: ReadinessItem[] }) => void = () => {};
    const rpcClient = makeClient(
      () =>
        new Promise<{ items: ReadinessItem[] }>((res) => {
          resolve = res;
        }),
    );
    await act(async () => {
      root.render(<ReadinessRollup rpcClient={rpcClient} />);
    });
    // Unmount before the summary resolves.
    await act(async () => {
      root.unmount();
    });
    // Resolving now must be a no-op (the alive guard drops the result).
    await act(async () => {
      resolve({ items: [makeItem()] });
    });
    expect(container.querySelectorAll('[role="status"]').length).toBe(0);
    // Re-create the root so afterEach's unmount is safe.
    root = createRoot(container);
  });
});
