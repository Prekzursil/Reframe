// Stabilize.test.tsx — tests for the "Steady the shot" panel.
//
// MEASURED GAP (see the header of Stabilize.tsx): `stabilize.run` is registered
// in the sidecar (features/stabilize.py:496) and has its own output directory
// (handlers/library_ops.py:418 "stabilized"), but before this panel the literal
// appeared ZERO times anywhere under app/ — stabilization was reachable only as
// an all-or-nothing pre-step inside a ShortMaker export.
//
// The panel drives ONE RPC:
//   stabilize.run({videoId}) -> {jobId} -> job.done {path, stabilized[, notice]}
// It is a deferred job, so the terminal payload arrives on the job.done
// notification, never on the rpc promise (see `_api.ts` CONTRACT-NOTE). A fake
// `api` bridge is injected via the `api?` prop, mirroring Refine.test.tsx.
//
// The `stabilized:false` + `notice` branch is NOT an error: the sidecar reports
// a missing libvidstab explicitly rather than silently passing the clip through
// (stabilize.py:450-453), and the panel must surface that distinctly.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Stabilize, { stabilizeOutcome } from './Stabilize';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

const NOTICE = {
  type: 'stabilize.unavailable',
  message: 'stabilize: the bundled ffmpeg has no libvidstab — stabilization was skipped',
};

function makeFakeApi(overrides: { runError?: Error } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'stabilize.run') {
        if (overrides.runError) throw overrides.runError;
        return { jobId: 'job-s' } as T;
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

describe('stabilizeOutcome', () => {
  it('reads a successful steadied result', () => {
    expect(stabilizeOutcome({ path: '/out/clip.stabilized.mp4', stabilized: true })).toEqual({
      path: '/out/clip.stabilized.mp4',
      stabilized: true,
      notice: null,
    });
  });

  it('reads the libvidstab-unavailable passthrough WITH its notice', () => {
    expect(stabilizeOutcome({ path: '/in/clip.mp4', stabilized: false, notice: NOTICE })).toEqual({
      path: '/in/clip.mp4',
      stabilized: false,
      notice: NOTICE,
    });
  });

  it('null when there is no usable path', () => {
    expect(stabilizeOutcome({})).toBeNull();
    expect(stabilizeOutcome(null)).toBeNull();
    expect(stabilizeOutcome({ stabilized: true })).toBeNull();
    expect(stabilizeOutcome({ path: 42 })).toBeNull();
  });

  it('treats a missing/!==true stabilized flag as not stabilized', () => {
    expect(stabilizeOutcome({ path: '/p.mp4' })?.stabilized).toBe(false);
  });

  it('ignores a shapeless notice rather than rendering junk', () => {
    expect(stabilizeOutcome({ path: '/p.mp4', stabilized: false, notice: 'nope' })?.notice).toBeNull();
  });
});

describe('<Stabilize />', () => {
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
      root.render(<Stabilize videoId="v1" api={api} />);
    });
  }

  async function clickRun(): Promise<void> {
    await act(async () => {
      (container.querySelector('button[data-action="run"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
  }

  it('sends stabilize.run for the open video', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    const call = fake.calls.find((c) => c.method === 'stabilize.run');
    expect(call?.params).toEqual({ videoId: 'v1' });
  });

  it('streams progress while the job runs', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      fake.fireProgress({ jobId: 'job-s', pct: 40, message: 'analysing shake' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).toContain('40');
    expect(container.querySelector('.progress-message')?.textContent).toContain('analysing shake');
  });

  it('ignores progress for a DIFFERENT job', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      fake.fireProgress({ jobId: 'someone-else', pct: 99, message: 'not mine' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).not.toContain('99');
  });

  it('renders the steadied output path on job.done', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      fake.fireDone({
        jobId: 'job-s',
        result: { path: '/out/stabilized/clip.stabilized.mp4', stabilized: true },
      });
      await Promise.resolve();
    });
    const out = container.querySelector('[data-section="result"]');
    expect(out?.textContent).toContain('/out/stabilized/clip.stabilized.mp4');
    expect(container.querySelector('[data-section="notice"]')).toBeNull();
  });

  it('surfaces the libvidstab-unavailable notice INSTEAD of a silent success', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      fake.fireDone({
        jobId: 'job-s',
        result: { path: '/in/clip.mp4', stabilized: false, notice: NOTICE },
      });
      await Promise.resolve();
    });
    const notice = container.querySelector('[data-section="notice"]');
    expect(notice?.textContent).toContain('libvidstab');
    // The passthrough path is NOT presented as a steadied result.
    expect(container.querySelector('[data-section="result"]')).toBeNull();
  });

  it('surfaces an rpc failure as an error', async () => {
    const fake = makeFakeApi({ runError: new Error('sidecar exploded') });
    await mount(fake.api);
    await clickRun();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar exploded');
  });

  it('surfaces a non-Error rejection as a string', async () => {
    const calls: FakeApi['calls'] = [];
    const api: MediaStudioApi = {
      rpc: vi.fn(async (method: string) => {
        calls.push({ method });
        throw 'plain string boom';
      }) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(api);
    await clickRun();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string boom');
  });

  it('cancels the in-flight job via job.cancel', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      (container.querySelector('button[data-action="cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.some((c) => c.method === 'job.cancel')).toBe(true);
  });

  it('keeps the panel usable when job.cancel itself fails', async () => {
    const calls: FakeApi['calls'] = [];
    let doneCbs: Array<(ev: DoneEvent) => void> = [];
    const api: MediaStudioApi = {
      rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
        calls.push({ method, params });
        if (method === 'job.cancel') throw new Error('cancel failed');
        return { jobId: 'job-s' } as T;
      }) as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: (cb) => {
        doneCbs.push(cb);
        return () => {
          doneCbs = doneCbs.filter((c) => c !== cb);
        };
      },
    };
    await mount(api);
    await clickRun();
    await act(async () => {
      (container.querySelector('button[data-action="cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    // The swallowed cancel failure must NOT surface as a panel error.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('resolves with no bridge job.done channel without hanging', async () => {
    const api: MediaStudioApi = {
      rpc: vi.fn(async () => ({ jobId: 'job-s' })) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      // no onJobDone — waitForJobDone resolves null
    };
    await mount(api);
    await clickRun();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('falls back to no job when the rpc returns no jobId', async () => {
    const api: MediaStudioApi = {
      rpc: vi.fn(async () => ({})) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(api);
    await clickRun();
    expect(container.querySelector('[data-section="result"]')).toBeNull();
  });

  it('ignores a job.done that carries no usable outcome', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await clickRun();
    await act(async () => {
      fake.fireDone({ jobId: 'job-s', result: {} });
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="result"]')).toBeNull();
    expect(container.querySelector('[data-section="notice"]')).toBeNull();
  });
});
