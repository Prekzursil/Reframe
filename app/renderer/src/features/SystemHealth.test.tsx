// SystemHealth.test.tsx — tests for the System Health panel (system-advanced).
//
// Mirrors Assets.test.tsx: pure helpers tested without render; component tests
// use react-dom/client + act under jsdom with the RPC bridge mocked.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import SystemHealth, { type HealthReport, backendSummary, overallVerdict } from './SystemHealth';
import type { MediaStudioApi } from './_api';

function report(over: Partial<HealthReport> = {}): HealthReport {
  return {
    ok: true,
    offline: false,
    platform: 'nt',
    tools: [
      { name: 'ffmpeg', present: true, path: '/bin/ffmpeg', version: '6.1', hint: '' },
      { name: 'ffprobe', present: true, path: '/bin/ffprobe', version: '6.1', hint: '' },
    ],
    backends: [
      { label: 'faster-whisper', module: 'faster_whisper', installed: true, version: '1.0' },
      { label: 'torch', module: 'torch', installed: false, version: '' },
    ],
    modelPaths: [{ label: 'Data root', path: 'C:/data', exists: true }],
    engines: [{ name: 'llama-server', description: 'LLM', available: false, path: '' }],
    ...over,
  };
}

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
}

function makeFakeApi(initial: HealthReport, opts: { afterToggle?: HealthReport } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let healthCount = 0;
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'system.health') {
        healthCount += 1;
        const r = healthCount > 1 && opts.afterToggle ? opts.afterToggle : initial;
        return r as T;
      }
      if (method === 'settings.set') return {} as T;
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: () => () => undefined,
    onJobDone: () => () => undefined,
  };
  return { api, calls };
}

describe('backendSummary', () => {
  it('counts installed over total', () => {
    expect(backendSummary(report().backends)).toEqual({ installed: 1, total: 2 });
  });
});

describe('overallVerdict', () => {
  it('checking when null', () => {
    expect(overallVerdict(null)).toBe('Checking…');
  });
  it('flags missing tools', () => {
    expect(overallVerdict(report({ ok: false }))).toContain('needs attention');
  });
  it('notes offline when on', () => {
    expect(overallVerdict(report({ offline: true }))).toContain('Offline mode ON');
  });
  it('plain OK otherwise', () => {
    expect(overallVerdict(report())).toBe('Setup OK');
  });
});

describe('<SystemHealth />', () => {
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
      root.render(<SystemHealth api={api} />);
    });
  }

  it('renders tools, backends, engines and paths from system.health', async () => {
    const fake = makeFakeApi(report());
    await mount(fake.api);

    expect(fake.calls[0]).toEqual({ method: 'system.health', params: undefined });
    expect(container.querySelector('li[data-tool="ffmpeg"]')?.textContent).toContain('6.1');
    expect(container.querySelector('li[data-backend="torch"]')?.textContent).toContain(
      'not installed',
    );
    expect(container.querySelector('li[data-backend="faster_whisper"]')?.textContent).toContain(
      '1.0',
    );
    expect(container.querySelector('li[data-engine="llama-server"]')?.textContent).toContain(
      'not found',
    );
    expect(container.querySelector('li[data-path="Data root"]')?.textContent).toContain('exists');
  });

  it('shows the verdict', async () => {
    await mount(makeFakeApi(report()).api);
    expect(container.querySelector('.health-verdict')?.textContent).toBe('Setup OK');
  });

  it('toggles offline mode via settings.set then re-checks', async () => {
    const fake = makeFakeApi(report({ offline: false }), {
      afterToggle: report({ offline: true }),
    });
    await mount(fake.api);

    const toggle = container.querySelector(
      'button[data-action="toggle-offline"]',
    ) as HTMLButtonElement;
    expect(toggle.textContent).toContain('OFF');
    await act(async () => {
      toggle.click();
    });

    const setCall = fake.calls.find((c) => c.method === 'settings.set');
    expect(setCall?.params).toEqual({ offline: true });
    // re-checked: a second system.health call happened, and the button flipped.
    expect(fake.calls.filter((c) => c.method === 'system.health').length).toBe(2);
    expect(
      (container.querySelector('button[data-action="toggle-offline"]') as HTMLButtonElement)
        .textContent,
    ).toContain('ON');
  });

  it('surfaces an rpc rejection', async () => {
    const fake = makeFakeApi(report());
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('sidecar gone'));
    await mount(fake.api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar gone');
  });
});
