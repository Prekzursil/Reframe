// Assets.test.tsx — tests for the Assets panel (unit: U4).
//
// Strategy mirrors ShortMaker.test.tsx: pure helpers tested with no render;
// component tests use React 18's react-dom/client + act under jsdom with the
// RPC bridge mocked (a fake `MediaStudioApi`) — no real sidecar, no network.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Assets, {
  type AssetInfo,
  doneErrorMessage,
  extractAssets,
  fmtSize,
  missingNames,
} from './Assets';
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

function makeFakeApi(
  listAssets: AssetInfo[],
  opts: { ensureJobId?: string } = {},
): FakeApi {
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

describe('doneErrorMessage', () => {
  it('extracts the §A3 error payload message', () => {
    const result = { error: { message: 'insufficient disk space', type: 'AssetError' } };
    expect(doneErrorMessage(result)).toBe('insufficient disk space');
  });
  it('returns null for success payloads', () => {
    expect(doneErrorMessage({ installed: [], assets: [] })).toBeNull();
    expect(doneErrorMessage(null)).toBeNull();
    expect(doneErrorMessage({ error: 'flat-string' })).toBeNull();
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

    const all = container.querySelector(
      'button[data-action="install-all"]',
    ) as HTMLButtonElement;
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
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string) => {
        if (method === 'assets.list') return { assets: TWO };
        throw new Error('sidecar gone');
      },
    );
    await mount(fake.api);

    const button = rowFor('whisper-large-v3-turbo')!.querySelector(
      'button[data-action="install"]',
    ) as HTMLButtonElement;
    await act(async () => {
      button.click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'sidecar gone',
    );
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
    const cancelBtn = container.querySelector(
      'button[data-action="cancel"]',
    ) as HTMLButtonElement;
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
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'list blew up',
    );
  });
});
