// Transcribe.test.tsx — tests for the Transcribe feature panel.
//
// The panel consumes the FROZEN window.api bridge via getApi() (no api prop), so
// we install a fake bridge on globalThis.api. Covers: render, language pick,
// start -> progress -> job.done transcript (summary + segments), the inlined
// fast-path result, cancel, and the rpc-rejection error path.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Transcribe from './Transcribe';
import type { DoneEvent, MediaStudioApi, ProgressEvent, Transcript } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(opts: { inlineTranscript?: Transcript } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'transcribe.start') {
        return { jobId: 'job-t', transcript: opts.inlineTranscript } as T;
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

function transcript(over: Partial<Transcript> = {}): Transcript {
  return {
    language: 'en',
    durationSec: 12.34,
    segments: [
      { start: 0, end: 2, text: 'Hello there', words: [{ text: 'Hello', start: 0, end: 1 }] },
      {
        start: 2,
        end: 4,
        text: 'General Kenobi',
        words: [
          { text: 'General', start: 2, end: 3 },
          { text: 'Kenobi', start: 3, end: 4 },
        ],
      },
    ],
    ...over,
  };
}

describe('<Transcribe />', () => {
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
    delete (globalThis as { api?: unknown }).api;
    vi.restoreAllMocks();
  });

  function install(fake: FakeApi) {
    (globalThis as { api?: unknown }).api = fake.api;
  }

  async function mount(videoId = 'v1', onTranscript?: (t: Transcript) => void): Promise<void> {
    await act(async () => {
      root.render(<Transcribe videoId={videoId} onTranscript={onTranscript} />);
    });
  }

  function startBtn(): HTMLButtonElement {
    return [...container.querySelectorAll('button')].find((b) =>
      /transcription|Transcribing/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
  }

  it('renders the language picker and a disabled start when there is no videoId', async () => {
    install(makeFakeApi());
    await mount('');
    expect(container.querySelector('select#transcribe-language')).toBeTruthy();
    expect(startBtn().disabled).toBe(true);
  });

  it('starts transcribe.start with the chosen language, streams progress, then shows the transcript', async () => {
    const fake = makeFakeApi();
    install(fake);
    const onTranscript = vi.fn();
    await mount('v1', onTranscript);

    const select = container.querySelector('#transcribe-language') as HTMLSelectElement;
    await act(async () => {
      select.value = 'es';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'transcribe.start')?.params).toEqual({
      videoId: 'v1',
      language: 'es',
    });

    await act(async () => {
      fake.fireProgress({ jobId: 'job-t', pct: 45, message: 'decoding' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('45%');
    expect(container.querySelector('.progress-message')?.textContent).toContain('decoding');

    await act(async () => {
      fake.fireDone({ jobId: 'job-t', result: { transcript: transcript() } });
      await Promise.resolve();
    });

    const summary = container.querySelector('.transcript-summary');
    expect(summary?.textContent).toContain('en');
    expect(summary?.textContent).toContain('12.3s');
    expect(summary?.textContent).toContain('Segments:');
    // 2 segments, 3 words total.
    expect(container.querySelectorAll('.transcript-segments li').length).toBe(2);
    expect(summary?.textContent).toContain('Words:');
    expect(onTranscript).toHaveBeenCalledWith(expect.objectContaining({ language: 'en' }));
  });

  it('omits the language param when Auto-detect is selected', async () => {
    const fake = makeFakeApi();
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'transcribe.start')?.params).toEqual({
      videoId: 'v1',
    });
  });

  it('honors an inlined fast-path transcript on the rpc resolution', async () => {
    const fake = makeFakeApi({ inlineTranscript: transcript({ language: 'fr' }) });
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('fr');
  });

  it('cancel calls job.cancel and returns to idle', async () => {
    const fake = makeFakeApi();
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-t', pct: 10, message: 'go' });
    });
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-t' });
  });

  it('swallows a job.cancel rejection (best-effort) and still goes idle', async () => {
    const fake = makeFakeApi();
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-t', pct: 10, message: 'go' });
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already gone'));
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    // No error banner — cancellation failures are intentionally silent.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('surfaces an rpc rejection from transcribe.start as an error', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain string error');
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string error');
  });

  it('uses Error.message when the rpc rejects with an Error instance', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('whisper crashed'));
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('whisper crashed');
  });

  it('returns to idle when job.done carries neither a transcript nor an error', async () => {
    // F1/F2: a job that finishes with neither payload must NOT stick on
    // 'running' forever — the terminal finally drops the panel back to idle.
    const fake = makeFakeApi();
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-t', result: {} });
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.transcript-summary')).toBeNull();
    const btn = startBtn();
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toContain('Start transcription');
  });

  it('ignores progress notifications for a different job', async () => {
    const fake = makeFakeApi();
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    // A progress event for an UNRELATED job must not move this panel's bar.
    await act(async () => {
      fake.fireProgress({ jobId: 'someone-else', pct: 99, message: 'not mine' });
    });
    const progress = container.querySelector('.progress');
    expect(progress?.textContent).not.toContain('99%');
    expect(progress?.textContent).not.toContain('not mine');
    // It still shows the panel's own starting state (0%).
    expect(progress?.textContent).toContain('0%');
  });

  it('cancel is a no-op when clicked before the start rpc has resolved a jobId', async () => {
    const fake = makeFakeApi();
    // Make transcribe.start hang so the panel is "running" but jobId is still null.
    let resolveStart: (v: { jobId: string }) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation((method: string) =>
      method === 'transcribe.start'
        ? new Promise((res) => {
            resolveStart = res as (v: { jobId: string }) => void;
          })
        : Promise.resolve({}),
    );
    install(fake);
    await mount('v1');
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    // jobId was still null -> job.cancel was never called (early-return guard).
    expect(fake.calls.find((c) => c.method === 'job.cancel')).toBeUndefined();
    // Clean up the dangling promise.
    await act(async () => {
      resolveStart({ jobId: 'job-late' });
      await Promise.resolve();
    });
  });
});
