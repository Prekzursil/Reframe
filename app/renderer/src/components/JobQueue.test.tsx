// JobQueue.test.tsx — tests for the global job-queue slide-over (T6).
//
// Strategy mirrors Library.test.tsx: React 18 createRoot + act under jsdom
// with the lib/rpc bridge mocked — no real sidecar. Poll lifecycle is driven
// with vi.useFakeTimers.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Mock the canonical rpc client so the panel's calls are controllable.
const rpcMock = vi.fn();
let progressCbs: Array<(ev: { jobId: string; pct: number; message: string }) => void> = [];
vi.mock('../lib/rpc', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: (cb: (ev: { jobId: string; pct: number; message: string }) => void) => {
    progressCbs.push(cb);
    return () => {
      progressCbs = progressCbs.filter((c) => c !== cb);
    };
  },
}));

import {
  JobQueue,
  JOB_POLL_INTERVAL_MS,
  RESUME_TITLE,
  applyProgress,
  canCancel,
  canResume,
  canRetry,
  clampPct,
} from './JobQueue';
import type { JobInfo } from '../lib/rpc';

function makeJob(over: Partial<JobInfo> = {}): JobInfo {
  return {
    jobId: 'j1',
    feature: 'transcribe',
    label: 'Transcribe talk.mp4',
    videoId: 'v1',
    status: 'running',
    pct: 40,
    ...over,
  };
}

/** rpc impl serving job.list with the given jobs; records all other calls. */
function serveJobs(jobs: JobInfo[]): void {
  rpcMock.mockImplementation(async (method: string) => {
    if (method === 'job.list') return { jobs };
    if (method === 'job.cancel') return { ok: true };
    if (method === 'job.retry') return { jobId: 'j-retry' };
    return {};
  });
}

function listCalls(): number {
  return rpcMock.mock.calls.filter((c) => c[0] === 'job.list').length;
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  progressCbs = [];
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

async function flush(turns = 6): Promise<void> {
  await act(async () => {
    for (let i = 0; i < turns; i += 1) {
      await Promise.resolve();
    }
  });
}

async function renderQueue(open: boolean, onClose: () => void = () => {}): Promise<void> {
  await act(async () => {
    root.render(<JobQueue open={open} onClose={onClose} />);
  });
  await flush();
}

async function click(selector: string): Promise<void> {
  const btn = container.querySelector(selector) as HTMLButtonElement;
  expect(btn).not.toBeNull();
  await act(async () => {
    btn.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------

describe('canCancel / canRetry', () => {
  it('cancel applies to queued and running only', () => {
    expect(canCancel(makeJob({ status: 'queued' }))).toBe(true);
    expect(canCancel(makeJob({ status: 'running' }))).toBe(true);
    expect(canCancel(makeJob({ status: 'done' }))).toBe(false);
    expect(canCancel(makeJob({ status: 'error' }))).toBe(false);
    expect(canCancel(makeJob({ status: 'cancelled' }))).toBe(false);
  });

  it('retry applies to error only', () => {
    expect(canRetry(makeJob({ status: 'error' }))).toBe(true);
    expect(canRetry(makeJob({ status: 'running' }))).toBe(false);
    expect(canRetry(makeJob({ status: 'done' }))).toBe(false);
    expect(canRetry(makeJob({ status: 'interrupted' }))).toBe(false);
  });

  it('resume applies to interrupted only (table-test all six statuses)', () => {
    expect(canResume(makeJob({ status: 'interrupted' }))).toBe(true);
    expect(canResume(makeJob({ status: 'queued' }))).toBe(false);
    expect(canResume(makeJob({ status: 'running' }))).toBe(false);
    expect(canResume(makeJob({ status: 'done' }))).toBe(false);
    expect(canResume(makeJob({ status: 'error' }))).toBe(false);
    expect(canResume(makeJob({ status: 'cancelled' }))).toBe(false);
  });
});

describe('clampPct', () => {
  it('clamps into 0..100 and zeroes NaN', () => {
    expect(clampPct(-5)).toBe(0);
    expect(clampPct(42.5)).toBe(42.5);
    expect(clampPct(180)).toBe(100);
    expect(clampPct(Number.NaN)).toBe(0);
  });
});

describe('applyProgress', () => {
  it('updates the matching job pct and promotes queued to running', () => {
    const jobs = [makeJob({ jobId: 'a', status: 'queued', pct: 0 }), makeJob({ jobId: 'b' })];
    const next = applyProgress(jobs, { jobId: 'a', pct: 25 });
    expect(next[0]).toMatchObject({ jobId: 'a', status: 'running', pct: 25 });
    expect(next[1]).toBe(jobs[1]); // untouched entry is the same reference
  });

  it('keeps a non-queued status as-is', () => {
    const jobs = [makeJob({ jobId: 'a', status: 'running', pct: 10 })];
    expect(applyProgress(jobs, { jobId: 'a', pct: 90 })[0].status).toBe('running');
  });

  it('returns the SAME array when no entry matches', () => {
    const jobs = [makeJob({ jobId: 'a' })];
    expect(applyProgress(jobs, { jobId: 'zzz', pct: 50 })).toBe(jobs);
  });
});

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------

describe('JobQueue', () => {
  it('renders nothing and calls no rpc while closed', async () => {
    serveJobs([]);
    await renderQueue(false);
    expect(container.querySelector('.jobqueue')).toBeNull();
    expect(rpcMock).not.toHaveBeenCalled();
    expect(progressCbs.length).toBe(0); // no progress subscription either
  });

  it('lists jobs from job.list with feature/label/status/pct', async () => {
    serveJobs([
      makeJob(),
      makeJob({
        jobId: 'j2',
        feature: 'convert',
        label: 'Convert clip.mkv',
        status: 'error',
        pct: 0,
      }),
    ]);
    await renderQueue(true);

    expect(rpcMock).toHaveBeenCalledWith('job.list');
    const text = container.textContent ?? '';
    expect(text).toContain('transcribe');
    expect(text).toContain('Transcribe talk.mp4');
    expect(text).toContain('running');
    expect(text).toContain('40%');
    expect(text).toContain('convert');
    expect(text).toContain('Convert clip.mkv');
    expect(text).toContain('error');
    expect(container.querySelectorAll('li.jobqueue__item').length).toBe(2);
  });

  it('shows the empty state when there are no jobs', async () => {
    serveJobs([]);
    await renderQueue(true);
    expect(container.textContent).toContain('No jobs yet');
  });

  it('treats a job.list result without a jobs array as empty (JobQueue.tsx:72)', async () => {
    // result is non-null but has no `jobs` key -> the `?? []` fallback applies.
    rpcMock.mockResolvedValue({});
    await renderQueue(true);
    expect(container.textContent).toContain('No jobs yet');
    expect(container.querySelectorAll('li.jobqueue__item').length).toBe(0);
  });

  it('stringifies a non-Error rejection from job.list (errText else, JobQueue.tsx:55)', async () => {
    rpcMock.mockRejectedValue('plain string failure');
    await renderQueue(true);
    expect(container.textContent).toContain('plain string failure');
  });

  it('surfaces a job.list failure', async () => {
    rpcMock.mockRejectedValue(new Error('sidecar down'));
    await renderQueue(true);
    expect(container.textContent).toContain('sidecar down');
  });

  it('Cancel shows for running/queued only and fires job.cancel + a refresh', async () => {
    serveJobs([
      makeJob({ jobId: 'run-1', status: 'running' }),
      makeJob({ jobId: 'done-1', status: 'done' }),
    ]);
    await renderQueue(true);

    // One cancellable entry -> exactly one Cancel button, no Retry buttons.
    expect(container.querySelectorAll('.jobqueue__cancel').length).toBe(1);
    expect(container.querySelectorAll('.jobqueue__retry').length).toBe(0);

    const before = listCalls();
    await click('.jobqueue__cancel');

    expect(rpcMock).toHaveBeenCalledWith('job.cancel', { jobId: 'run-1' });
    expect(listCalls()).toBe(before + 1); // refreshed after the action
  });

  it('Retry shows for error entries only and fires job.retry + a refresh', async () => {
    serveJobs([makeJob({ jobId: 'err-1', status: 'error', pct: 0 })]);
    await renderQueue(true);

    expect(container.querySelectorAll('.jobqueue__retry').length).toBe(1);
    expect(container.querySelectorAll('.jobqueue__cancel').length).toBe(0);

    const before = listCalls();
    await click('.jobqueue__retry');

    expect(rpcMock).toHaveBeenCalledWith('job.retry', { jobId: 'err-1' });
    expect(listCalls()).toBe(before + 1);
  });

  it('Resume shows for interrupted only, fires job.retry, and excludes Retry/Cancel', async () => {
    serveJobs([makeJob({ jobId: 'int-1', status: 'interrupted', pct: 0 })]);
    await renderQueue(true);

    // Exactly one Resume button; no Retry, no Cancel (the §3.2 a11y bug — an
    // interrupted job would otherwise render zero action buttons).
    expect(container.querySelectorAll('.jobqueue__resume').length).toBe(1);
    expect(container.querySelectorAll('.jobqueue__retry').length).toBe(0);
    expect(container.querySelectorAll('.jobqueue__cancel').length).toBe(0);

    const resume = container.querySelector('.jobqueue__resume') as HTMLButtonElement;
    expect(resume.getAttribute('aria-label')).toBe('Resume Transcribe talk.mp4');
    expect(resume.getAttribute('title')).toBe(RESUME_TITLE);
    expect(resume.textContent).toBe('Resume');
    // The status pill renders the interrupted label as text (not color-only).
    expect(container.textContent).toContain('interrupted');
    expect(container.querySelector('.jobqueue__status--interrupted')).not.toBeNull();

    const before = listCalls();
    await click('.jobqueue__resume');

    // Resume re-dispatches via the existing job.retry re-dispatch.
    expect(rpcMock).toHaveBeenCalledWith('job.retry', { jobId: 'int-1' });
    expect(listCalls()).toBe(before + 1);
  });

  it('gives Resume and Retry distinct accessible names', async () => {
    serveJobs([
      makeJob({ jobId: 'int-1', label: 'Dub clip.mp4', status: 'interrupted', pct: 0 }),
      makeJob({ jobId: 'err-1', label: 'Dub clip.mp4', status: 'error', pct: 0 }),
    ]);
    await renderQueue(true);

    const resume = container.querySelector('.jobqueue__resume') as HTMLButtonElement;
    const retry = container.querySelector('.jobqueue__retry') as HTMLButtonElement;
    expect(resume.getAttribute('aria-label')).toBe('Resume Dub clip.mp4');
    expect(retry.getAttribute('aria-label')).toBe('Retry Dub clip.mp4');
    expect(resume.getAttribute('aria-label')).not.toBe(retry.getAttribute('aria-label'));
  });

  it('surfaces a job.cancel failure and still refreshes (JobQueue.tsx:100-103)', async () => {
    // Initial list serves one cancellable job; once Cancel is clicked, BOTH
    // job.cancel and the following refresh fail — so the catch-set error persists
    // (refresh's success would otherwise clear it) and the alert stays visible.
    let cancelled = false;
    rpcMock.mockImplementation(async (method: string) => {
      if (method === 'job.cancel') {
        cancelled = true;
        throw new Error('cancel blew up');
      }
      if (method === 'job.list') {
        if (cancelled) throw new Error('list down after cancel');
        return { jobs: [makeJob({ jobId: 'run-1', status: 'running' })] };
      }
      return {};
    });
    await renderQueue(true);

    const before = listCalls();
    await click('.jobqueue__cancel');

    // The catch ran (cancel was attempted) and a refresh still followed it.
    expect(rpcMock).toHaveBeenCalledWith('job.cancel', { jobId: 'run-1' });
    expect(listCalls()).toBe(before + 1);
    // An error alert is shown (the failure was surfaced, never swallowed).
    expect(container.querySelector('.jobqueue__error')).not.toBeNull();
  });

  it('surfaces a job.retry failure and still refreshes (JobQueue.tsx:112-115)', async () => {
    let retried = false;
    rpcMock.mockImplementation(async (method: string) => {
      if (method === 'job.retry') {
        retried = true;
        throw new Error('retry blew up');
      }
      if (method === 'job.list') {
        if (retried) throw new Error('list down after retry');
        return { jobs: [makeJob({ jobId: 'err-1', status: 'error', pct: 0 })] };
      }
      return {};
    });
    await renderQueue(true);

    const before = listCalls();
    await click('.jobqueue__retry');

    expect(rpcMock).toHaveBeenCalledWith('job.retry', { jobId: 'err-1' });
    expect(listCalls()).toBe(before + 1);
    expect(container.querySelector('.jobqueue__error')).not.toBeNull();
  });

  it('live-updates pct from job.progress while open', async () => {
    serveJobs([makeJob({ jobId: 'live-1', status: 'queued', pct: 0 })]);
    await renderQueue(true);
    expect(container.textContent).toContain('0%');
    expect(progressCbs.length).toBe(1);

    await act(async () => {
      progressCbs.slice().forEach((cb) => cb({ jobId: 'live-1', pct: 55, message: 'working' }));
    });

    expect(container.textContent).toContain('55%');
    expect(container.textContent).toContain('running'); // queued promoted
  });

  it('polls job.list every 2s while open and stops when closed', async () => {
    vi.useFakeTimers();
    serveJobs([]);

    await renderQueue(true);
    expect(listCalls()).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS);
    });
    expect(listCalls()).toBe(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_POLL_INTERVAL_MS);
    });
    expect(listCalls()).toBe(3);

    // Close -> the interval and the progress subscription are torn down.
    await act(async () => {
      root.render(<JobQueue open={false} onClose={() => {}} />);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * JOB_POLL_INTERVAL_MS);
    });
    expect(listCalls()).toBe(3);
    expect(progressCbs.length).toBe(0);
  });

  it('stops polling on unmount', async () => {
    vi.useFakeTimers();
    serveJobs([]);

    await renderQueue(true);
    expect(listCalls()).toBe(1);

    act(() => root.unmount());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * JOB_POLL_INTERVAL_MS);
    });
    expect(listCalls()).toBe(1);

    // afterEach unmounts again — give it a fresh root so that stays a no-op.
    root = createRoot(container);
  });

  it('fires onClose from the close button', async () => {
    serveJobs([]);
    const onClose = vi.fn();
    await renderQueue(true, onClose);

    await click('.jobqueue__close');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
