// Diarize.test.tsx — tests for the Speaker Diarization panel (system-advanced).

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Diarize, { extractSpeakers } from './Diarize';
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

  it('surfaces a non-Error rejection via String(err)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain diarize error');
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain diarize error');
  });

  it('ignores progress notifications for a different job', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-d', pct: 30, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
    expect(container.querySelector('.progress')?.textContent).toContain('30%');
  });

  it('cancel calls job.cancel for the active job and shows Cancelling…', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    expect(cancelBtn).toBeTruthy();
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-d' });
    expect(container.querySelector('.progress-message')?.textContent).toContain('Cancelling…');
  });

  it('cancel swallows a job.cancel rejection (best-effort)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    const cancelBtn = container.querySelector('button[data-action="cancel"]') as HTMLButtonElement;
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('handles a start response with no jobId (no job.done wait, stays idle of results)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({}); // no jobId
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    // No roster (result was null) and no error.
    expect(container.querySelector('[data-section="speakers"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('handles a job.done whose result is null (extract ?? null fallback)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-d', result: undefined });
      await Promise.resolve();
    });
    // No error, no roster — a null terminal payload yields an empty result.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-section="speakers"]')).toBeNull();
  });

  it('handles a null start response (optional-chaining fallback to no jobId)', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[data-section="speakers"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('ignores a second click while already busy (re-entrancy guard)', async () => {
    const fake = makeFakeApi();
    // Hang the first start so the panel stays busy.
    let release: (v: { jobId: string }) => void = () => undefined;
    const rpcMock = fake.api.rpc as ReturnType<typeof vi.fn>;
    rpcMock.mockImplementationOnce(
      () => new Promise((res) => (release = res as (v: { jobId: string }) => void)),
    );
    await mount(fake.api);
    const btn = container.querySelector('button[data-action="diarize"]') as HTMLButtonElement;
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    // A second invocation while busy returns early (no second diarize.start rpc).
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    expect(rpcMock.mock.calls.filter((c) => c[0] === 'diarize.start').length).toBe(1);
    await act(async () => {
      release({ jobId: 'job-d' });
      await Promise.resolve();
    });
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<Diarize videoId="v1" />);
      });
      await act(async () => {
        (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
        await Promise.resolve();
      });
      expect(fake.calls.find((c) => c.method === 'diarize.start')?.params).toEqual({
        videoId: 'v1',
      });
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });

  // --- WU-7: per-speaker rename block ---------------------------------------
  /** Set a controlled input's value via React's tracked native setter. */
  function typeInto(input: HTMLInputElement, value: string): void {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }

  /** Run a diarize so the roster is populated, then return the two-speaker fake. */
  async function diarizeTwoSpeakers(): Promise<FakeApi> {
    const fake = makeFakeApi();
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
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
    return fake;
  }

  it('renders one rename input per speaker in the roster', async () => {
    await diarizeTwoSpeakers();
    const inputs = container.querySelectorAll('input[data-rename-for]');
    expect(inputs.length).toBe(2);
    expect(container.querySelector('input[data-rename-for="SPEAKER_00"]')).toBeTruthy();
    expect(container.querySelector('input[data-rename-for="SPEAKER_01"]')).toBeTruthy();
  });

  it('does not render a rename block when the roster is empty', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(container.querySelector('[data-section="rename"]')).toBeNull();
  });

  it('renaming a speaker submits diarize.rename and refreshes the labels', async () => {
    const fake = makeFakeApi();
    // diarize.rename returns the renamed transcript directly (not a job).
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        fake.calls.push({ method, params });
        if (method === 'diarize.start') return { jobId: 'job-d' };
        if (method === 'diarize.rename') {
          return {
            transcript: {
              language: 'en',
              segments: [],
              durationSec: 0,
              speakers: ['Alex', 'SPEAKER_01'],
            },
          };
        }
        return {};
      },
    );
    await mount(fake.api);
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
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

    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, 'Alex');
    });
    const applyBtn = container.querySelector('button[data-action="rename"]') as HTMLButtonElement;
    await act(async () => {
      applyBtn.click();
      await Promise.resolve();
    });

    expect(fake.calls.find((c) => c.method === 'diarize.rename')?.params).toEqual({
      videoId: 'v1',
      mapping: { SPEAKER_00: 'Alex' },
    });
    // The displayed roster now shows the renamed label.
    expect(container.querySelector('li[data-speaker="Alex"]')).toBeTruthy();
    expect(container.querySelector('li[data-speaker="SPEAKER_00"]')).toBeNull();
  });

  it('submits only the speakers whose names actually changed', async () => {
    const fake = await diarizeTwoSpeakers();
    // Edit one input back to its original label, edit the other to a new name.
    const input1 = container.querySelector(
      'input[data-rename-for="SPEAKER_01"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input1, 'Sam');
    });
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'diarize.rename')?.params).toEqual({
      videoId: 'v1',
      mapping: { SPEAKER_01: 'Sam' },
    });
  });

  it('does not call diarize.rename when no name changed', async () => {
    const fake = await diarizeTwoSpeakers();
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'diarize.rename')).toBeUndefined();
  });

  it('treats a whitespace-only rename as unchanged (trim guard)', async () => {
    const fake = await diarizeTwoSpeakers();
    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, '   ');
    });
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'diarize.rename')).toBeUndefined();
  });

  it('surfaces a diarize.rename rejection', async () => {
    const fake = await diarizeTwoSpeakers();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('rename failed'));
    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, 'Alex');
    });
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('rename failed');
  });

  it('surfaces a non-Error diarize.rename rejection via String(err)', async () => {
    const fake = await diarizeTwoSpeakers();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain rename error');
    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, 'Alex');
    });
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain rename error');
  });

  it('keeps existing labels when diarize.rename returns no roster', async () => {
    const fake = await diarizeTwoSpeakers();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ transcript: {} });
    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, 'Alex');
    });
    await act(async () => {
      (container.querySelector('button[data-action="rename"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    // No roster came back -> labels unchanged, no error.
    expect(container.querySelector('li[data-speaker="SPEAKER_00"]')).toBeTruthy();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('clears the draft inputs after a re-diarize repopulates the roster', async () => {
    const fake = await diarizeTwoSpeakers();
    const input = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    await act(async () => {
      typeInto(input, 'Alex');
    });
    // Re-run diarize -> roster (and drafts) reset.
    await act(async () => {
      (container.querySelector('button[data-action="diarize"]') as HTMLButtonElement).click();
    });
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
    const fresh = container.querySelector(
      'input[data-rename-for="SPEAKER_00"]',
    ) as HTMLInputElement;
    expect(fresh.value).toBe('');
  });
});
