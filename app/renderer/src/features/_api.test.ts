// Unit tests for the pure helpers in the feature-panel shared module.
// Pure logic only — no React render, no window.api, no heavy imports.
import { describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_JOB_TIMEOUT_MS,
  type DoneEvent,
  JobAbortedError,
  type MediaStudioApi,
  type ProgressEvent,
  extractJobId,
  fmtSeconds,
  getApi,
  pickField,
  waitForJobDone,
} from './_api';

/** Build a fake bridge whose onJobDone fires the given done events synchronously. */
function fakeApi(opts: { withJobDone?: boolean } = {}): {
  api: MediaStudioApi;
  fire: (ev: DoneEvent) => void;
  /** Live subscriber count — 0 proves the wait cleaned up its subscription. */
  count: () => number;
} {
  const listeners: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: async <T>(): Promise<T> => ({}) as T,
    onProgress: (_cb: (ev: ProgressEvent) => void) => () => undefined,
  };
  if (opts.withJobDone !== false) {
    api.onJobDone = (cb: (ev: DoneEvent) => void) => {
      listeners.push(cb);
      return () => {
        const i = listeners.indexOf(cb);
        if (i >= 0) listeners.splice(i, 1);
      };
    };
  }
  return {
    api,
    fire: (ev) => listeners.slice().forEach((l) => l(ev)),
    count: () => listeners.length,
  };
}

describe('fmtSeconds', () => {
  it('formats whole minutes and seconds as M:SS', () => {
    expect(fmtSeconds(0)).toBe('0:00');
    expect(fmtSeconds(5)).toBe('0:05');
    expect(fmtSeconds(65)).toBe('1:05');
    expect(fmtSeconds(600)).toBe('10:00');
  });

  it('floors fractional seconds', () => {
    expect(fmtSeconds(9.9)).toBe('0:09');
    expect(fmtSeconds(125.4)).toBe('2:05');
  });

  it('guards against negatives and non-finite input', () => {
    expect(fmtSeconds(-1)).toBe('0:00');
    expect(fmtSeconds(Number.NaN)).toBe('0:00');
    expect(fmtSeconds(Number.POSITIVE_INFINITY)).toBe('0:00');
  });
});

describe('extractJobId', () => {
  it('returns a string jobId when present', () => {
    expect(extractJobId({ jobId: 'job-42' })).toBe('job-42');
    expect(extractJobId({ jobId: 'job-42', path: '/out.mp4' })).toBe('job-42');
  });

  it('returns undefined when jobId is absent or not a string', () => {
    expect(extractJobId({})).toBeUndefined();
    expect(extractJobId({ path: '/out.mp4' })).toBeUndefined();
    expect(extractJobId({ jobId: 7 })).toBeUndefined();
    expect(extractJobId(null)).toBeUndefined();
    expect(extractJobId(undefined)).toBeUndefined();
    expect(extractJobId('job-1')).toBeUndefined();
  });
});

describe('pickField', () => {
  it('pulls a present field off a job.done result', () => {
    expect(pickField<string>({ path: '/out.mp4' }, 'path')).toBe('/out.mp4');
    expect(pickField<string[]>({ paths: ['/a', '/b'] }, 'paths')).toEqual(['/a', '/b']);
    expect(
      pickField<{ language: string }>({ transcript: { language: 'en' } }, 'transcript'),
    ).toEqual({
      language: 'en',
    });
  });

  it('returns null when the field is absent or the result is not an object', () => {
    expect(pickField<string>({ other: 1 }, 'path')).toBeNull();
    expect(pickField<string>(null, 'path')).toBeNull();
    expect(pickField<string>('nope', 'path')).toBeNull();
  });

  it('coerces a present-but-nullish field value to null (?? branch)', () => {
    expect(pickField<string>({ path: null }, 'path')).toBeNull();
    expect(pickField<string>({ path: undefined }, 'path')).toBeNull();
  });
});

describe('getApi', () => {
  it('returns the window.api bridge installed on globalThis', () => {
    const fake = { rpc: async () => ({}), onProgress: () => () => undefined };
    (globalThis as { api?: unknown }).api = fake;
    try {
      expect(getApi()).toBe(fake);
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });
});

describe('waitForJobDone', () => {
  it('resolves with the extracted field when the matching job.done arrives', async () => {
    const { api, fire } = fakeApi();
    const promise = waitForJobDone(api, 'job-7', (r) => pickField<string>(r, 'path'));
    fire({ jobId: 'other', result: { path: '/wrong.mp4' } }); // ignored — wrong id
    fire({ jobId: 'job-7', result: { path: '/right.mp4' } });
    await expect(promise).resolves.toBe('/right.mp4');
  });

  it('resolves null when the bridge exposes no onJobDone hook', async () => {
    const { api } = fakeApi({ withJobDone: false });
    await expect(
      waitForJobDone(api, 'job-1', (r) => pickField<string>(r, 'path')),
    ).resolves.toBeNull();
  });

  it('unsubscribes after the first matching event (no leak)', async () => {
    const { api, fire, count } = fakeApi();
    const promise = waitForJobDone(api, 'job-9', (r) => pickField<string[]>(r, 'paths'));
    fire({ jobId: 'job-9', result: { paths: ['/x'] } });
    await expect(promise).resolves.toEqual(['/x']);
    expect(count()).toBe(0); // subscription cleaned up
    // A second fire after resolution must not throw (listener already removed).
    expect(() => fire({ jobId: 'job-9', result: { paths: ['/y'] } })).not.toThrow();
  });

  // ---- F1: surface the {error} job.done payload as a rejection --------------

  it('REJECTS with the message when job.done carries an {error} payload', async () => {
    const { api, fire, count } = fakeApi();
    const promise = waitForJobDone(api, 'job-e', (r) => pickField<string>(r, 'path'));
    const assertion = expect(promise).rejects.toThrow('disk full');
    fire({ jobId: 'job-e', result: { error: { message: 'disk full', type: 'RpcError' } } });
    await assertion;
    expect(count()).toBe(0); // subscription torn down on the error reject
  });

  it('treats a JobCancelled error payload as a clean finish (resolves null, no throw)', async () => {
    const { api, fire } = fakeApi();
    const promise = waitForJobDone(api, 'job-c', (r) => pickField<string>(r, 'path'));
    fire({ jobId: 'job-c', result: { error: { message: 'cancelled', type: 'JobCancelled' } } });
    await expect(promise).resolves.toBeNull();
  });

  it('resolves the extracted value (null) when job.done has neither result nor error', async () => {
    const { api, fire } = fakeApi();
    const promise = waitForJobDone(api, 'job-n', (r) => pickField<string>(r, 'path'));
    fire({ jobId: 'job-n', result: {} });
    await expect(promise).resolves.toBeNull();
  });

  // ---- F2: timeout ---------------------------------------------------------

  it('REJECTS with a user-facing message when the timeout elapses', async () => {
    vi.useFakeTimers();
    try {
      const { api, count } = fakeApi(); // job.done never fires (dead sidecar)
      const promise = waitForJobDone(api, 'job-t', (r) => pickField<string>(r, 'path'), 1000);
      const assertion = expect(promise).rejects.toThrow(/Timed out waiting for the job/);
      await vi.advanceTimersByTimeAsync(1000);
      await assertion;
      expect(count()).toBe(0); // subscription torn down on timeout
    } finally {
      vi.useRealTimers();
    }
  });

  it('applies the default timeout when none is given', async () => {
    vi.useFakeTimers();
    try {
      const { api } = fakeApi();
      const promise = waitForJobDone(api, 'job-d', (r) => pickField<string>(r, 'path'));
      const assertion = expect(promise).rejects.toThrow(/Timed out waiting for the job/);
      await vi.advanceTimersByTimeAsync(DEFAULT_JOB_TIMEOUT_MS);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it('clears the timer when the job resolves first (no late rejection)', async () => {
    vi.useFakeTimers();
    try {
      const { api, fire } = fakeApi();
      const promise = waitForJobDone(api, 'job-r', (r) => pickField<string>(r, 'path'), 1000);
      fire({ jobId: 'job-r', result: { path: '/ok.mp4' } });
      await expect(promise).resolves.toBe('/ok.mp4');
      await vi.advanceTimersByTimeAsync(1000); // must NOT produce a late rejection
    } finally {
      vi.useRealTimers();
    }
  });

  it('never times out when timeoutMs is 0 (disabled)', async () => {
    vi.useFakeTimers();
    try {
      const { api } = fakeApi();
      const promise = waitForJobDone(api, 'job-0', (r) => pickField<string>(r, 'path'), 0);
      let settled = false;
      void promise.then(
        () => {
          settled = true;
        },
        () => {
          settled = true;
        },
      );
      await vi.advanceTimersByTimeAsync(DEFAULT_JOB_TIMEOUT_MS * 2);
      expect(settled).toBe(false); // no timer armed — still pending
    } finally {
      vi.useRealTimers();
    }
  });

  // ---- F2: AbortSignal (cancel / unmount) ----------------------------------

  it('REJECTS with JobAbortedError when the signal aborts mid-wait', async () => {
    const { api, count } = fakeApi();
    const ctrl = new AbortController();
    const promise = waitForJobDone(
      api,
      'job-a',
      (r) => pickField<string>(r, 'path'),
      DEFAULT_JOB_TIMEOUT_MS,
      ctrl.signal,
    );
    const assertion = expect(promise).rejects.toBeInstanceOf(JobAbortedError);
    ctrl.abort();
    await assertion;
    expect(count()).toBe(0); // subscription + abort listener torn down
  });

  it('REJECTS immediately with JobAbortedError when the signal is already aborted', async () => {
    const { api, count } = fakeApi();
    const ctrl = new AbortController();
    ctrl.abort();
    await expect(
      waitForJobDone(
        api,
        'job-pre',
        (r) => pickField<string>(r, 'path'),
        DEFAULT_JOB_TIMEOUT_MS,
        ctrl.signal,
      ),
    ).rejects.toBeInstanceOf(JobAbortedError);
    expect(count()).toBe(0); // never left a dangling subscription
  });
});

describe('JobAbortedError', () => {
  it('carries a default message and the JobAbortedError name', () => {
    const err = new JobAbortedError();
    expect(err.name).toBe('JobAbortedError');
    expect(err.message).toContain('aborted');
    expect(err).toBeInstanceOf(Error);
  });
});
