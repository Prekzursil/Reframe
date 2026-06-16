// Unit tests for the pure helpers in the feature-panel shared module.
// Pure logic only — no React render, no window.api, no heavy imports.
import { describe, expect, it } from 'vitest';
import {
  type DoneEvent,
  type MediaStudioApi,
  type ProgressEvent,
  extractJobId,
  fmtSeconds,
  pickField,
  waitForJobDone,
} from './_api';

/** Build a fake bridge whose onJobDone fires the given done events synchronously. */
function fakeApi(opts: { withJobDone?: boolean } = {}): {
  api: MediaStudioApi;
  fire: (ev: DoneEvent) => void;
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
  return { api, fire: (ev) => listeners.slice().forEach((l) => l(ev)) };
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
    const { api, fire } = fakeApi();
    const promise = waitForJobDone(api, 'job-9', (r) => pickField<string[]>(r, 'paths'));
    fire({ jobId: 'job-9', result: { paths: ['/x'] } });
    await expect(promise).resolves.toEqual(['/x']);
    // A second fire after resolution must not throw (listener already removed).
    expect(() => fire({ jobId: 'job-9', result: { paths: ['/y'] } })).not.toThrow();
  });
});
