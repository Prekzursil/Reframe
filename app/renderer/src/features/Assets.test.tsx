// Assets.test.tsx — tests for the Assets panel (unit: U4).
//
// Strategy mirrors ShortMaker.test.tsx: pure helpers tested with no render;
// component tests use React 18's react-dom/client + act under jsdom with the
// RPC bridge mocked (a fake `MediaStudioApi`) — no real sidecar, no network.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Assets, { type AssetInfo, extractAssets, fmtSize, missingNames } from './Assets';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function asset(over: Partial<AssetInfo> = {}): AssetInfo {
  return {
    name: 'whisper-large-v3-turbo',
    kind: 'model',
    sizeMB: 1600,
    installed: false,
    dest: 'C:/data/models/whisper',
    ...over,
  };
}

const TWO: AssetInfo[] = [
  asset(),
  asset({ name: 'qwen3-4b-gguf', sizeMB: 2500, installed: true, dest: 'C:/m/q.gguf' }),
];

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(listAssets: AssetInfo[], opts: { ensureJobId?: string } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'assets.list') return { assets: listAssets } as T;
      if (method === 'assets.ensure') {
        return { jobId: opts.ensureJobId ?? 'job-1' } as T;
      }
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb) => {
      progressCbs.push(cb);
      return () => {
        progressCbs = progressCbs.filter((c) => c !== cb);
      };
    },
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return {
    api,
    calls,
    fireProgress: (ev) => progressCbs.slice().forEach((cb) => cb(ev)),
    fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)),
  };
}

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------

describe('fmtSize', () => {
  it('formats GB with one decimal at >= 1024 MB', () => {
    expect(fmtSize(1600)).toBe('1.6 GB');
    expect(fmtSize(2500)).toBe('2.4 GB');
  });
  it('formats whole MB below 1024', () => {
    expect(fmtSize(350)).toBe('350 MB');
  });
  it('handles sub-MB and invalid sizes', () => {
    expect(fmtSize(0.5)).toBe('<1 MB');
    expect(fmtSize(0)).toBe('—');
    expect(fmtSize(Number.NaN)).toBe('—');
  });
});

describe('missingNames', () => {
  it('returns only not-installed names, in order', () => {
    expect(missingNames(TWO)).toEqual(['whisper-large-v3-turbo']);
  });
  it('is empty when everything is installed', () => {
    expect(missingNames([asset({ installed: true })])).toEqual([]);
  });
});

describe('extractAssets', () => {
  it('pulls the assets array out of a done payload', () => {
    expect(extractAssets({ installed: ['a'], assets: TWO })).toEqual(TWO);
  });
  it('returns null for malformed payloads', () => {
    expect(extractAssets(null)).toBeNull();
    expect(extractAssets({})).toBeNull();
    expect(extractAssets({ assets: 'nope' })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------

describe('<Assets />', () => {
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

  async function mount(api: MediaStudioApi): Promise<void> {
    await act(async () => {
      root.render(<Assets api={api} />);
    });
  }

  function rowFor(name: string): HTMLElement | null {
    return container.querySelector(`li[data-asset="${name}"]`);
  }

  it('lists assets from assets.list with install state and size', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);

    expect(fake.calls[0]).toEqual({ method: 'assets.list', params: undefined });
    const whisper = rowFor('whisper-large-v3-turbo');
    const qwen = rowFor('qwen3-4b-gguf');
    expect(whisper?.textContent).toContain('Not installed');
    expect(whisper?.textContent).toContain('1.6 GB');
    expect(qwen?.textContent).toContain('Installed');
    // Only the missing asset gets an Install button.
    expect(whisper?.querySelector('button[data-action="install"]')).toBeTruthy();
    expect(qwen?.querySelector('button[data-action="install"]')).toBeNull();
  });

  it('install button starts assets.ensure for that one asset and applies the done payload', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);

    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });

    const ensureCall = fake.calls.find((c) => c.method === 'assets.ensure');
    expect(ensureCall?.params).toEqual({ names: ['whisper-large-v3-turbo'] });

    // Progress for the active job renders.
    await act(async () => {
      fake.fireProgress({ jobId: 'job-1', pct: 42, message: 'whisper: 600/1600 MB' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('42%');

    // The done payload's asset list replaces the panel state.
    const updated = TWO.map((a) => ({ ...a, installed: true }));
    await act(async () => {
      fake.fireDone({
        jobId: 'job-1',
        result: { installed: ['whisper-large-v3-turbo'], assets: updated },
      });
    });
    expect(rowFor('whisper-large-v3-turbo')?.textContent).toContain('Installed');
    expect(container.querySelector('.progress')).toBeNull(); // busy cleared
  });

  it('install-all sends every missing name', async () => {
    const both: AssetInfo[] = [
      asset({ name: 'a-model', installed: false }),
      asset({ name: 'b-tool', kind: 'tool', installed: false }),
      asset({ name: 'c-done', installed: true }),
    ];
    const fake = makeFakeApi(both);
    await mount(fake.api);

    const all = container.querySelector('button[data-action="install-all"]') as HTMLButtonElement;
    expect(all.textContent).toContain('2');
    await act(async () => {
      all.click();
    });
    const ensureCall = fake.calls.find((c) => c.method === 'assets.ensure');
    expect(ensureCall?.params).toEqual({ names: ['a-model', 'b-tool'] });
  });

  it('surfaces the job.done error payload as an alert', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);

    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-1',
        result: { error: { message: 'insufficient disk space at C:', type: 'AssetError' } },
      });
    });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('insufficient disk space');
    // The failed asset stays not-installed.
    expect(rowFor('whisper-large-v3-turbo')?.textContent).toContain('Not installed');
  });

  it('surfaces an rpc rejection from assets.ensure', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'assets.list') return { assets: TWO };
      throw new Error('sidecar gone');
    });
    await mount(fake.api);

    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar gone');
  });

  it('cancel button calls assets.cancel with the active jobId', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);

    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    expect(cancelBtn).toBeTruthy();
    await act(async () => {
      cancelBtn.click();
    });
    const cancelCall = fake.calls.find((c) => c.method === 'assets.cancel');
    expect(cancelCall?.params).toEqual({ jobId: 'job-1' });
  });

  it('shows the list error when assets.list rejects', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      throw new Error('list blew up');
    });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('list blew up');
  });

  it('shows a non-Error list rejection via String(err)', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async () => {
      throw 'plain list error';
    });
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain list error');
  });

  it('coerces a non-array assets payload to an empty list', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ assets: 'nope' });
    await mount(fake.api);
    expect(container.querySelector('.asset-empty')).toBeTruthy();
  });

  it('refreshes from assets.list when the ensure job.done carries no asset list', async () => {
    const fake = makeFakeApi(TWO);
    let listCall = 0;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'assets.list') {
        listCall += 1;
        // First list: original; after ensure, the refreshed list marks installed.
        return { assets: listCall === 1 ? TWO : TWO.map((a) => ({ ...a, installed: true })) };
      }
      if (method === 'assets.ensure') return { jobId: 'job-1' };
      return {};
    });
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    // job.done with NO assets list -> the panel calls refresh() to re-list.
    await act(async () => {
      fake.fireDone({ jobId: 'job-1', result: { installed: ['whisper-large-v3-turbo'] } });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(listCall).toBeGreaterThanOrEqual(2);
    expect(rowFor('whisper-large-v3-turbo')?.textContent).toContain('Installed');
  });

  it('shows a non-Error ensure rejection via String(err)', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'assets.list') return { assets: TWO };
      throw 'plain ensure error';
    });
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain ensure error');
  });

  it('ignores progress notifications for a different job', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-1', pct: 25, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
    expect(container.querySelector('.progress')?.textContent).toContain('25%');
  });

  it('handles an ensure response with no jobId (no job.done wait)', async () => {
    const fake = makeFakeApi(TWO);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'assets.list') return { assets: TWO };
      if (method === 'assets.ensure') return {}; // no jobId
      return {};
    });
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
      await Promise.resolve();
    });
    // No crash, no error; result was null so nothing changed.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('treats a null ensure job.done payload as a no-op (extract ?? null)', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    let listCallsBefore = 0;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mock.calls.forEach((c) => {
      if (c[0] === 'assets.list') listCallsBefore += 1;
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-1', result: undefined });
      await Promise.resolve();
      await Promise.resolve();
    });
    // A null payload -> refresh() re-lists (extractAssets null -> refresh branch).
    let listCallsAfter = 0;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mock.calls.forEach((c) => {
      if (c[0] === 'assets.list') listCallsAfter += 1;
    });
    expect(listCallsAfter).toBeGreaterThan(listCallsBefore);
  });

  it('cancel swallows an assets.cancel rejection (best-effort) and shows Cancelling…', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);
    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.progress-message')?.textContent).toContain('Cancelling…');
  });

  it('the Refresh button re-lists the assets', async () => {
    const fake = makeFakeApi(TWO);
    await mount(fake.api);
    const before = fake.calls.filter((c) => c.method === 'assets.list').length;
    const refresh = container.querySelector('button[data-action="refresh"]') as HTMLButtonElement;
    await act(async () => {
      refresh.click();
      await Promise.resolve();
    });
    expect(fake.calls.filter((c) => c.method === 'assets.list').length).toBe(before + 1);
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi(TWO);
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<Assets />);
      });
      expect(rowFor('whisper-large-v3-turbo')).toBeTruthy();
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });
});
