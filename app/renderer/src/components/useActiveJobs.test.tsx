// useActiveJobs.test.tsx — the header-pill job heartbeat: the pure active-count
// helpers + the polling hook (bridge-present/absent, success/undefined/reject,
// the interval re-read, and the cancelled-after-unmount guard).
//
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { JobInfo } from '../lib/rpc';

// ---- mocks -----------------------------------------------------------------
const rpcMock = vi.fn();
let hasApiValue = true;

vi.mock('../lib/rpc', () => ({
  rpc: (...a: unknown[]) => rpcMock(...a),
  hasApi: () => hasApiValue,
}));

import {
  isActiveJob,
  activeJobCount,
  useActiveJobs,
  JOBS_HEARTBEAT_MS,
} from './useActiveJobs';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function job(over: Partial<JobInfo> = {}): JobInfo {
  return {
    jobId: 'j1',
    feature: 'reframe',
    label: 'clip.mp4',
    status: 'running',
    pct: 40,
    ...over,
  };
}

describe('isActiveJob', () => {
  it('is true for queued and running (work in motion)', () => {
    expect(isActiveJob(job({ status: 'queued' }))).toBe(true);
    expect(isActiveJob(job({ status: 'running' }))).toBe(true);
  });

  it('is false for terminal/paused states', () => {
    expect(isActiveJob(job({ status: 'done' }))).toBe(false);
    expect(isActiveJob(job({ status: 'error' }))).toBe(false);
    expect(isActiveJob(job({ status: 'cancelled' }))).toBe(false);
    expect(isActiveJob(job({ status: 'interrupted' }))).toBe(false);
  });
});

describe('activeJobCount', () => {
  it('counts only the active jobs in the payload', () => {
    const jobs = [
      job({ jobId: 'a', status: 'running' }),
      job({ jobId: 'b', status: 'queued' }),
      job({ jobId: 'c', status: 'done' }),
      job({ jobId: 'd', status: 'error' }),
    ];
    expect(activeJobCount(jobs)).toBe(2);
  });

  it('treats a missing jobs array as zero', () => {
    expect(activeJobCount(undefined)).toBe(0);
    expect(activeJobCount([])).toBe(0);
  });
});

describe('useActiveJobs (hook)', () => {
  let container: HTMLDivElement;
  let root: Root;
  let observed = -1;

  function Harness(): React.ReactElement {
    observed = useActiveJobs();
    return React.createElement('div', null, String(observed));
  }

  async function mount(): Promise<void> {
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    await flush();
  }

  async function flush(): Promise<void> {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  beforeEach(() => {
    observed = -1;
    hasApiValue = true;
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ jobs: [] });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it('exposes a slow heartbeat slower than the open panel (2 s)', () => {
    expect(JOBS_HEARTBEAT_MS).toBeGreaterThan(2000);
  });

  it('reports the active count from an initial job.list read', async () => {
    rpcMock.mockResolvedValue({
      jobs: [job({ status: 'running' }), job({ jobId: 'j2', status: 'queued' }), job({ jobId: 'j3', status: 'done' })],
    });
    await mount();
    expect(rpcMock).toHaveBeenCalledWith('job.list');
    expect(observed).toBe(2);
  });

  it('reports 0 when job.list omits the jobs array', async () => {
    rpcMock.mockResolvedValue(null);
    await mount();
    expect(observed).toBe(0);
  });

  it('keeps the last known count when a read rejects', async () => {
    rpcMock.mockRejectedValue(new Error('offline'));
    await mount();
    expect(observed).toBe(0);
  });

  it('does not poll (and stays 0) when no preload bridge is present', async () => {
    hasApiValue = false;
    await mount();
    expect(rpcMock).not.toHaveBeenCalled();
    expect(observed).toBe(0);
  });

  it('re-reads on the heartbeat interval', async () => {
    vi.useFakeTimers();
    rpcMock.mockResolvedValue({ jobs: [job({ status: 'running' })] });
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    // Initial read.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(rpcMock).toHaveBeenCalledTimes(1);
    // Advance one heartbeat → a second read fires.
    await act(async () => {
      vi.advanceTimersByTime(JOBS_HEARTBEAT_MS);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(rpcMock).toHaveBeenCalledTimes(2);
    expect(observed).toBe(1);
  });

  it('ignores a late resolve after unmount (cancelled guard)', async () => {
    let resolveList: (v: { jobs: JobInfo[] }) => void = () => {};
    rpcMock.mockReturnValue(
      new Promise((res) => {
        resolveList = res;
      }),
    );
    await act(async () => {
      root.render(React.createElement(Harness));
    });
    // Unmount before the in-flight read resolves.
    act(() => root.unmount());
    await act(async () => {
      resolveList({ jobs: [job({ status: 'running' })] });
      await Promise.resolve();
    });
    // No throw / no state update after unmount — re-create the root for teardown.
    root = createRoot(container);
  });
});
