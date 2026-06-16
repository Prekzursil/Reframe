// Diarize.test.tsx — tests for the Speaker Diarization panel (system-advanced).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Diarize, { doneErrorMessage, extractSpeakers } from './Diarize';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'diarize.start') return { jobId: 'job-d' } as T;
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

describe('extractSpeakers', () => {
  it('pulls the roster from a done transcript', () => {
    const result = {
      transcript: {
        language: 'en',
        segments: [],
        durationSec: 0,
        speakers: ['SPEAKER_00', 'SPEAKER_01'],
      },
    };
    expect(extractSpeakers(result)).toEqual(['SPEAKER_00', 'SPEAKER_01']);
  });
  it('empty when absent', () => {
    expect(
      extractSpeakers({ transcript: { language: 'en', segments: [], durationSec: 0 } }),
    ).toEqual([]);
    expect(extractSpeakers(null)).toEqual([]);
  });
});

describe('doneErrorMessage', () => {
  it('extracts the error message', () => {
    expect(doneErrorMessage({ error: { message: 'no transcript', type: 'RpcError' } })).toBe(
      'no transcript',
    );
  });
  it('null for success', () => {
    expect(doneErrorMessage({ transcript: {} })).toBeNull();
  });
});

describe('<Diarize />', () => {
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
      root.render(<Diarize videoId="v1" api={api} />);
    });
  }

  it('starts diarize.start, shows progress, then the speaker roster', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const btn = container.querySelector('button[data-action="diarize"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    expect(fake.calls.find((c) => c.method === 'diarize.start')?.params).toEqual({ videoId: 'v1' });

    await act(async () => {
      fake.fireProgress({ jobId: 'job-d', pct: 60, message: 'clustering speakers' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('60%');

    await act(async () => {
      fake.fireDone({
        jobId: 'job-d',
        result: {
          transcript: {
            language: 'en',
            segments: [],
            durationSec: 0,
            speakers: ['SPEAKER_00', 'SPEAKER_01'],
          },
        },
      });
    });
    const list = container.querySelector('ul[data-section="speakers"]');
    expect(list?.querySelectorAll('li').length).toBe(2);
    expect(container.querySelector('li[data-speaker="SPEAKER_00"]')).toBeTruthy();
  });

  it('surfaces a job.done error (e.g. offline-refuses-gated-models)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const btn = container.querySelector('button[data-action="diarize"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-d',
        result: {
          error: {
            message: 'Offline mode is on — downloading the SpeechBrain diarization models',
            type: 'OfflineError',
          },
        },
      });
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('Offline mode is on');
  });

  it('surfaces an rpc rejection', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('sidecar gone'));
    await mount(fake.api);
    const btn = container.querySelector('button[data-action="diarize"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('sidecar gone');
  });
});
