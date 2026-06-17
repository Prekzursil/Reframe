// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const rpcMock = vi.fn();
let progressCb: ((e: { jobId: string; pct: number; message: string }) => void) | null = null;

vi.mock('./api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: (cb: (e: { jobId: string; pct: number; message: string }) => void) => {
    progressCb = cb;
    return () => {
      progressCb = null;
    };
  },
  hasApi: () => true,
}));

import { type AiPlan, useAiJob } from './useAiJob';

// useJob (which this hook wraps) reads the job.done relay off the window.api
// bridge; install a no-op onJobDone so its effect subscribes without crashing.
type DoneCb = (e: { jobId: string; result?: unknown }) => void;

function installBridge(): void {
  (window as unknown as { api?: unknown }).api = {
    onJobDone: (_cb: DoneCb) => () => undefined,
  };
}

let api: ReturnType<typeof useAiJob> | null = null;
function Harness(): React.ReactElement {
  api = useAiJob();
  const p = api.preview;
  return React.createElement(
    'div',
    null,
    `${api.state.running}|${api.state.jobId ?? ''}|${p.preview ?? ''}|${p.cacheHit}|${p.willEgress}|${p.route?.providers.join(',') ?? ''}|${p.costEst?.requests ?? ''}`,
  );
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  progressCb = null;
  api = null;
  installBridge();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as unknown as { api?: unknown }).api;
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function aPlan(overrides?: Partial<AiPlan>): AiPlan {
  return {
    route: {
      providers: ['Groq'],
      degradeChain: ['Groq', 'local'],
      cacheHit: false,
      willEgress: true,
    },
    costEst: {
      requests: 1,
      providers: ['Groq'],
      egressBytes: 100,
      egressKinds: { text: 100, frames: 0 },
      withinFreeLimits: true,
    },
    cacheHit: false,
    willEgress: true,
    budget: {
      requests: 1,
      providers: ['Groq'],
      egressBytes: 100,
      egressKinds: { text: 100, frames: 0 },
      withinFreeLimits: true,
    },
    preview: '~1 request(s) across Groq; sends ~0.1 KB (100 text / 0 frame bytes).',
    cacheKey: 'abc123',
    ...overrides,
  };
}

async function mount(): Promise<void> {
  await act(async () => {
    root.render(React.createElement(Harness));
  });
}

describe('useAiJob', () => {
  it('starts empty with no preview', async () => {
    await mount();
    expect(api!.preview.route).toBeNull();
    expect(api!.preview.costEst).toBeNull();
    expect(api!.preview.preview).toBeNull();
    expect(api!.preview.cacheHit).toBe(false);
    expect(api!.preview.willEgress).toBe(false);
  });

  it('plan() calls ai.planJob and surfaces cost/route/preview', async () => {
    rpcMock.mockResolvedValueOnce(aPlan());
    await mount();

    let result: AiPlan | null = null;
    await act(async () => {
      result = await api!.plan({ messages: [{ role: 'user', content: 'q' }], model: 'm' });
    });
    await flush();

    expect(rpcMock).toHaveBeenCalledWith('ai.planJob', {
      messages: [{ role: 'user', content: 'q' }],
      model: 'm',
    });
    expect(result!.cacheKey).toBe('abc123');
    expect(api!.preview.route?.providers).toEqual(['Groq']);
    expect(api!.preview.costEst?.requests).toBe(1);
    expect(api!.preview.preview).toContain('Groq');
    expect(api!.preview.willEgress).toBe(true);
  });

  it('plan() with no request sends an empty params object', async () => {
    rpcMock.mockResolvedValueOnce(aPlan());
    await mount();
    await act(async () => {
      await api!.plan();
    });
    expect(rpcMock).toHaveBeenCalledWith('ai.planJob', {});
  });

  it('plan() surfaces a cache-hit preview (no egress)', async () => {
    rpcMock.mockResolvedValueOnce(
      aPlan({
        cacheHit: true,
        willEgress: false,
        route: {
          providers: ['Groq'],
          degradeChain: ['Groq', 'local'],
          cacheHit: true,
          willEgress: false,
        },
        preview: 'Cached — returns instantly, sends nothing.',
      }),
    );
    await mount();
    await act(async () => {
      await api!.plan({ messages: [{ role: 'user', content: 'seen' }] });
    });
    expect(api!.preview.cacheHit).toBe(true);
    expect(api!.preview.willEgress).toBe(false);
    expect(api!.preview.preview).toContain('Cached');
  });

  it('start() runs the job and tracks progress (delegates to useJob)', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'aj1' });
    await mount();
    await act(async () => {
      await api!.start('phase8.select', { videoId: 'v1' });
    });
    await flush();
    expect(rpcMock).toHaveBeenCalledWith('phase8.select', { videoId: 'v1' });
    expect(api!.state.jobId).toBe('aj1');
    expect(api!.state.running).toBe(true);

    await act(async () => {
      progressCb!({ jobId: 'aj1', pct: 55, message: 'selecting' });
    });
    expect(api!.state.pct).toBe(55);
    expect(api!.state.message).toBe('selecting');
  });

  it('cancel() delegates to useJob.cancel', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'aj2' });
    await mount();
    await act(async () => {
      await api!.start('subtitles.translate', { trackId: 't1', targetLang: 'es' });
    });
    rpcMock.mockResolvedValueOnce({ ok: true });
    await act(async () => {
      await api!.cancel();
    });
    expect(rpcMock).toHaveBeenCalledWith('job.cancel', { jobId: 'aj2' });
    expect(api!.state.running).toBe(false);
  });

  it('finish() ends the active job at 100%', async () => {
    rpcMock.mockResolvedValueOnce({ jobId: 'aj3' });
    await mount();
    await act(async () => {
      await api!.start('phase8.select', { videoId: 'v1' });
    });
    await act(() => {
      api!.finish();
    });
    expect(api!.state.running).toBe(false);
    expect(api!.state.pct).toBe(100);
  });

  it('reset() clears both the preview and the job state', async () => {
    rpcMock.mockResolvedValueOnce(aPlan());
    await mount();
    await act(async () => {
      await api!.plan({ messages: [{ role: 'user', content: 'q' }] });
    });
    expect(api!.preview.route).not.toBeNull();

    rpcMock.mockResolvedValueOnce({ jobId: 'aj4' });
    await act(async () => {
      await api!.start('phase8.select', { videoId: 'v1' });
    });
    await act(() => {
      api!.reset();
    });
    expect(api!.preview.route).toBeNull();
    expect(api!.preview.preview).toBeNull();
    expect(api!.state.jobId).toBeNull();
    expect(api!.state.running).toBe(false);
  });
});
