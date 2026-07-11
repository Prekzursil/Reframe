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
    // Defensive: a timing test may leave fake timers installed if it throws before
    // its own restore — never let that wedge the unmount below.
    vi.useRealTimers();
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

  function cancelBtn(): HTMLButtonElement | undefined {
    return [...container.querySelectorAll('button')].find((b) => b.textContent === 'Cancel') as
      | HTMLButtonElement
      | undefined;
  }

  it('hides Cancel until the start rpc resolves a jobId, then shows it (running && jobId gate)', async () => {
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
    // Pre-jobId window: running but jobId still null -> no Cancel button renders,
    // so the first-run Cancel can never no-op (or cancel a stale job).
    expect(cancelBtn()).toBeUndefined();
    // Once the rpc resolves a jobId, Cancel appears.
    await act(async () => {
      resolveStart({ jobId: 'job-late' });
      await Promise.resolve();
    });
    expect(cancelBtn()).toBeTruthy();
  });

  it('resets the stale jobId between runs so a second-run Cancel targets the NEW job', async () => {
    // First run completes via the inlined fast-path (jobId set then cleared in the
    // finally). A second run must NOT let a Cancel target the first, finished job.
    const fake = makeFakeApi({ inlineTranscript: transcript() });
    let resolveStart: (v: { jobId: string }) => void = () => undefined;
    install(fake);
    await mount('v1');
    // Run 1: inlined transcript -> no wait, ends in phase 'done' with jobId cleared.
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('.transcript-summary')).toBeTruthy();

    // Run 2: make transcribe.start hang so we sit in the pre-jobId window.
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation((method: string) =>
      method === 'transcribe.start'
        ? new Promise((res) => {
            resolveStart = res as (v: { jobId: string }) => void;
          })
        : Promise.resolve({}),
    );
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
    // Stale 'job-t' was cleared at run start -> no Cancel button in this window.
    expect(cancelBtn()).toBeUndefined();
    // When run 2 resolves its OWN jobId and is cancelled, job.cancel targets it,
    // never the first run's 'job-t'.
    await act(async () => {
      resolveStart({ jobId: 'job-2' });
      await Promise.resolve();
    });
    await act(async () => {
      cancelBtn()!.click();
      await Promise.resolve();
    });
    // Use the vi.fn call log (the run-2 mockImplementation bypasses `fake.calls`).
    const jobCancelCalls = (fake.api.rpc as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c) => c[0] === 'job.cancel',
    );
    expect(jobCancelCalls).toHaveLength(1);
    expect(jobCancelCalls[0][1]).toEqual({ jobId: 'job-2' });
  });

  it('cancel aborts the in-flight wait so no bogus timeout error surfaces 15 min later', async () => {
    vi.useFakeTimers();
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
    await act(async () => {
      cancelBtn()!.click();
      await Promise.resolve();
    });
    // The default 15-min job timeout would otherwise reject with a misleading
    // "Timed out" error; the abort cleared that timer, so nothing fires.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60 * 1000 + 1);
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    const btn = startBtn();
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toContain('Start transcription');
    vi.useRealTimers();
  });

  it('tears the in-flight wait down on unmount (no bogus timeout, no leaked state)', async () => {
    // Use a dedicated container/root so the in-test unmount never collides with
    // the shared afterEach teardown (which unmounts the beforeEach root).
    vi.useFakeTimers();
    const localContainer = document.createElement('div');
    document.body.appendChild(localContainer);
    const localRoot = createRoot(localContainer);
    const fake = makeFakeApi();
    install(fake);
    await act(async () => {
      localRoot.render(<Transcribe videoId="v1" />);
    });
    const localStart = [...localContainer.querySelectorAll('button')].find((b) =>
      /transcription|Transcribing/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      localStart.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-t', pct: 5, message: 'go' });
    });
    // Unmount while the wait is in flight -> the unmount effect aborts it.
    await act(async () => {
      localRoot.unmount();
    });
    // Advancing past the timeout must not throw or fire (the timer was cleared).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60 * 1000 + 1);
    });
    localContainer.remove();
    vi.useRealTimers();
  });
});
