// Refine.test.tsx — tests for the "Tighten the edit" panel (system-advanced).
//
// The panel drives the WU-5 RPCs:
//   refine.preview({videoId, removeFillers, removeSilence, ...}) -> {plan}   (DIRECT)
//   refine.apply({videoId, ...})  -> {jobId} -> job.done {path, removedSec, stats, plan}
// preview is a fast/direct RPC (result on the rpc promise); apply is a job
// (the terminal payload arrives via the job.done notification). A fake `api`
// bridge is injected via the `api?` prop, mirroring Diarize.test.tsx.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Refine, { extractPlan, applyResultPath } from './Refine';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

const PLAN = {
  keeps: [
    [0, 2],
    [2.4, 10],
  ],
  stats: { fillersRemoved: 1, fillerSeconds: 0.4, silenceRemovedSec: 2, keptSec: 7.6 },
};

function makeFakeApi(): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'refine.preview') return { plan: PLAN } as T;
      if (method === 'refine.apply') return { jobId: 'job-r' } as T;
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

describe('extractPlan', () => {
  it('pulls the plan from a preview result', () => {
    expect(extractPlan({ plan: PLAN })).toEqual(PLAN);
  });
  it('null when absent or shapeless', () => {
    expect(extractPlan({})).toBeNull();
    expect(extractPlan(null)).toBeNull();
    expect(extractPlan({ plan: { keeps: [], stats: null } })).toBeNull();
  });
});

describe('applyResultPath', () => {
  it('reads the result path', () => {
    expect(applyResultPath({ path: '/out/clip.refined.mp4' })).toBe('/out/clip.refined.mp4');
  });
  it('null when missing', () => {
    expect(applyResultPath({})).toBeNull();
    expect(applyResultPath(null)).toBeNull();
  });
});

describe('<Refine />', () => {
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
      root.render(<Refine videoId="v1" api={api} />);
    });
  }

  async function clickPreview(): Promise<void> {
    await act(async () => {
      (container.querySelector('button[data-action="preview"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
  }

  it('previews and renders the proposed saved-seconds + per-category stats', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    const call = fake.calls.find((c) => c.method === 'refine.preview');
    expect(call?.params).toEqual({
      videoId: 'v1',
      removeFillers: true,
      removeSilence: true,
      noiseDb: -30,
      minSilenceSec: 0.6,
      mergeGapMs: 200,
    });
    const stats = container.querySelector('[data-section="stats"]');
    expect(stats?.textContent).toContain('1'); // fillersRemoved
    expect(container.querySelector('[data-stat="keptSec"]')?.textContent).toContain('7.6');
    expect(container.querySelector('[data-stat="silenceRemovedSec"]')?.textContent).toContain('2');
    // the keep/cut list renders one row per keep span
    expect(container.querySelectorAll('[data-section="keeps"] li').length).toBe(2);
  });

  it('toggling "Remove silence" off re-issues preview with removeSilence:false', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const toggle = container.querySelector(
      'input[data-toggle="removeSilence"]',
    ) as HTMLInputElement;
    await act(async () => {
      toggle.click();
      await Promise.resolve();
    });
    await clickPreview();
    const call = fake.calls.find((c) => c.method === 'refine.preview');
    expect(call?.params?.removeSilence).toBe(false);
    expect(call?.params?.removeFillers).toBe(true);
  });

  it('toggling "Remove fillers" off threads removeFillers:false', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const toggle = container.querySelector(
      'input[data-toggle="removeFillers"]',
    ) as HTMLInputElement;
    await act(async () => {
      toggle.click();
      await Promise.resolve();
    });
    await clickPreview();
    expect(fake.calls.find((c) => c.method === 'refine.preview')?.params?.removeFillers).toBe(
      false,
    );
  });

  it('editing tunables (noiseDb/minSilenceSec/mergeGapMs) threads them into preview', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const setNum = (key: string, value: string): void => {
      const input = container.querySelector(`input[data-tune="${key}"]`) as HTMLInputElement;
      // React tracks the input value internally; the native setter + an input
      // event is what makes a controlled <input> see a real change in jsdom.
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value',
      )?.set;
      setter?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    await act(async () => {
      setNum('noiseDb', '-24');
      setNum('minSilenceSec', '0.9');
      setNum('mergeGapMs', '350');
      await Promise.resolve();
    });
    await clickPreview();
    const params = fake.calls.find((c) => c.method === 'refine.preview')?.params;
    expect(params?.noiseDb).toBe(-24);
    expect(params?.minSilenceSec).toBe(0.9);
    expect(params?.mergeGapMs).toBe(350);
  });

  it('surfaces a preview rpc rejection', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('preview boom'));
    await mount(fake.api);
    await clickPreview();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('preview boom');
  });

  it('surfaces a non-Error preview rejection via String(err)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain preview error');
    await mount(fake.api);
    await clickPreview();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain preview error');
  });

  it('a null preview result shows no stats and no error (defensive ?? null)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    await mount(fake.api);
    await clickPreview();
    expect(container.querySelector('[data-section="stats"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('ignores a second preview click while busy (re-entrancy guard)', async () => {
    const fake = makeFakeApi();
    let release: (v: { plan: typeof PLAN }) => void = () => undefined;
    const rpcMock = fake.api.rpc as ReturnType<typeof vi.fn>;
    rpcMock.mockImplementationOnce(
      () => new Promise((res) => (release = res as (v: { plan: typeof PLAN }) => void)),
    );
    await mount(fake.api);
    const btn = container.querySelector('button[data-action="preview"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    expect(rpcMock.mock.calls.filter((c) => c[0] === 'refine.preview').length).toBe(1);
    await act(async () => {
      release({ plan: PLAN });
      await Promise.resolve();
    });
  });

  it('Apply dispatches refine.apply, processes progress, and shows the result path on done', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview(); // a plan must exist to apply
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'refine.apply')?.params).toMatchObject({
      videoId: 'v1',
      removeFillers: true,
      removeSilence: true,
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-r', pct: 40, message: 're-cutting' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('40%');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-r',
        result: { path: '/out/v1.refined.mp4', removedSec: 2.4, stats: PLAN.stats, plan: PLAN },
      });
    });
    expect(container.querySelector('[data-section="result"]')?.textContent).toContain(
      '/out/v1.refined.mp4',
    );
  });

  it('Apply surfaces a job.done error payload', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-r',
        result: { error: { message: 'refine re-cut failed', type: 'InternalError' } },
      });
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'refine re-cut failed',
    );
  });

  it('Apply surfaces an rpc rejection', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('apply boom'));
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('apply boom');
  });

  it('Apply surfaces a non-Error rejection via String(err)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain apply error');
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain apply error');
  });

  it('Apply with a null jobId stays idle of results (no job.done wait)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({}); // no jobId
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('Apply with a null result on done surfaces neither path nor error', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-r', result: undefined });
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('ignores a second apply click while busy (re-entrancy guard)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    let release: (v: { jobId: string }) => void = () => undefined;
    const rpcMock = fake.api.rpc as ReturnType<typeof vi.fn>;
    rpcMock.mockImplementationOnce(
      () => new Promise((res) => (release = res as (v: { jobId: string }) => void)),
    );
    const btn = container.querySelector('button[data-action="apply"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    expect(rpcMock.mock.calls.filter((c) => c[0] === 'refine.apply').length).toBe(1);
    await act(async () => {
      release({ jobId: 'job-r' });
      await Promise.resolve();
    });
  });

  it('Apply is disabled until a preview plan exists', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const apply = container.querySelector('button[data-action="apply"]') as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    await clickPreview();
    expect(
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it('a knob change after Preview invalidates the plan — Apply re-disables, stats vanish', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    // Preview succeeded: Apply enabled + stats shown.
    expect(
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(container.querySelector('[data-section="stats"]')).not.toBeNull();
    // Tweak a checkbox knob -> the shown plan is now stale and must be dropped.
    const toggle = container.querySelector(
      'input[data-toggle="removeSilence"]',
    ) as HTMLInputElement;
    await act(async () => {
      toggle.click();
      await Promise.resolve();
    });
    expect(
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(container.querySelector('[data-section="stats"]')).toBeNull();
  });

  it('a tunable change after Preview also invalidates the plan (Apply re-disables)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    expect(
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).disabled,
    ).toBe(false);
    const input = container.querySelector('input[data-tune="noiseDb"]') as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set;
    await act(async () => {
      setter?.call(input, '-24');
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await Promise.resolve();
    });
    expect(
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(container.querySelector('[data-section="stats"]')).toBeNull();
  });

  it('cancel calls job.cancel for the active apply job and shows Cancelling…', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    expect(cancelBtn).toBeTruthy();
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-r' });
    expect(container.querySelector('.progress-message')?.textContent).toContain('Cancelling…');
  });

  it('cancel swallows a job.cancel rejection (best-effort)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('ignores progress notifications for a different job', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickPreview();
    await act(async () => {
      (container.querySelector('button[data-action="apply"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-r', pct: 30, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
    expect(container.querySelector('.progress')?.textContent).toContain('30%');
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<Refine videoId="v1" />);
      });
      await act(async () => {
        (container.querySelector('button[data-action="preview"]') as HTMLButtonElement).click();
        await Promise.resolve();
      });
      expect(fake.calls.find((c) => c.method === 'refine.preview')?.params).toMatchObject({
        videoId: 'v1',
      });
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });
});
