// Transcribe.rerun.test.tsx — W11 remediation: a re-run that does NOT produce a
// transcript must not destroy the one already on disk.
//
// Transcribe.rehydrate.test.tsx proves the mount-time `project.open` read. It
// stops there: none of its 13 cases drives the panel PAST the hydrate, so the
// interaction between the hydrate and `start()` was unpinned.
//
// The hole it left: `start()` opened with `setTranscript(null)`. That was
// harmless while the run was the only writer of `transcript`, but once the
// hydrate made the panel responsible for showing DISK-BACKED state, the same
// line destroyed it — and nothing re-reads. So hydrate -> "Re-run
// transcription" -> fail/cancel put the panel back in the exact state W11
// exists to remove: the muted "No transcript yet — run a transcription to
// create one." note about a video whose manifest still holds a transcript, plus
// the accent primary action re-offering a multi-minute GPU job.
//
// Every case below is RED against `setTranscript(null)` in `start()` and GREEN
// without it. They are written as assertions about what the USER IS TOLD (the
// empty note, the button's word and rank, the rendered summary), not about
// component state variables — "transcript === null" and "no transcript exists"
// are different facts, and conflating them is the defect.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Transcribe from './Transcribe';
import type { DoneEvent, MediaStudioApi, Transcript } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireDone: (ev: DoneEvent) => void;
}

function savedTranscript(over: Partial<Transcript> = {}): Transcript {
  return {
    language: 'ro',
    durationSec: 42.5,
    segments: [
      { start: 0, end: 2, text: 'Buna ziua', words: [{ text: 'Buna', start: 0, end: 1 }] },
      { start: 2, end: 4, text: 'ce faci', words: [{ text: 'ce', start: 2, end: 3 }] },
    ],
    ...over,
  };
}

/**
 * A bridge that hydrates `openResult` from `project.open` and runs a real
 * job-shaped `transcribe.start` ({jobId} now, `job.done` later).
 */
function makeFakeApi(openResult: unknown): FakeApi {
  const calls: FakeApi['calls'] = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'project.open') return openResult as T;
      if (method === 'transcribe.start') return { jobId: 'job-t' } as T;
      return {} as T;
    }) as MediaStudioApi['rpc'],
    onProgress: () => () => undefined,
    onJobDone: (cb) => {
      doneCbs.push(cb);
      return () => {
        doneCbs = doneCbs.filter((c) => c !== cb);
      };
    },
  };
  return { api, calls, fireDone: (ev) => doneCbs.slice().forEach((cb) => cb(ev)) };
}

describe('<Transcribe /> a failed / cancelled RE-RUN must not erase the saved transcript (W11)', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    vi.useRealTimers();
    await act(async () => {
      root.unmount();
    });
    container.remove();
    delete (globalThis as { api?: unknown }).api;
    vi.restoreAllMocks();
  });

  function install(fake: FakeApi): void {
    (globalThis as { api?: unknown }).api = fake.api;
  }

  /** Mount already hydrated with a saved transcript, and assert that baseline. */
  async function mountHydrated(fake: FakeApi): Promise<void> {
    install(fake);
    await act(async () => {
      root.render(<Transcribe videoId="v1" />);
    });
    expect(container.querySelector('.transcript-summary')).toBeTruthy();
    expect(startBtn().textContent).toContain('Re-run transcription');
  }

  function startBtn(): HTMLButtonElement {
    return [...container.querySelectorAll('button')].find((b) =>
      /transcription|Transcribing/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
  }

  function cancelBtn(): HTMLButtonElement | undefined {
    return [...container.querySelectorAll('button')].find((b) => b.textContent === 'Cancel') as
      | HTMLButtonElement
      | undefined;
  }

  async function clickPrimary(): Promise<void> {
    await act(async () => {
      startBtn().click();
      await Promise.resolve();
    });
  }

  /**
   * The whole point, in one place: the panel must still be TELLING THE TRUTH —
   * the saved transcript is rendered, the "No transcript yet" claim is absent,
   * and the primary action stays the demoted "Re-run transcription".
   */
  function expectSavedTranscriptStillClaimed(): void {
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('ro');
    expect(container.querySelectorAll('.transcript-segments li').length).toBe(2);
    expect(container.querySelector('[data-state="empty"]')).toBeNull();
    const btn = startBtn();
    expect(btn.textContent).toContain('Re-run transcription');
    expect(btn.textContent).not.toContain('Start transcription');
    expect(btn.className).toContain('secondary');
  }

  it('keeps it when the re-run START rpc rejects', async () => {
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('whisper crashed'));

    await clickPrimary();

    // The RUN failure is surfaced...
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('whisper crashed');
    // ...but it says nothing about the transcript that is still on disk.
    expectSavedTranscriptStillClaimed();
  });

  it('keeps it when the re-run JOB fails (job.done carries an error)', async () => {
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();

    await act(async () => {
      fake.fireDone({
        jobId: 'job-t',
        result: { error: { message: 'ffmpeg exited 1', type: 'RuntimeError' } },
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ffmpeg exited 1');
    expectSavedTranscriptStillClaimed();
  });

  it('keeps it when the re-run is CANCELLED', async () => {
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();

    await act(async () => {
      cancelBtn()!.click();
      await Promise.resolve();
    });

    // A cancel is a clean escape — no error banner, and nothing was lost.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expectSavedTranscriptStillClaimed();
  });

  it('keeps it when the re-run finishes carrying neither a transcript nor an error', async () => {
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();

    await act(async () => {
      fake.fireDone({ jobId: 'job-t', result: {} });
      await Promise.resolve();
    });

    expect(container.querySelector('[role="alert"]')).toBeNull();
    expectSavedTranscriptStillClaimed();
  });

  it('labels the still-visible summary as the SAVED one while the re-run is in flight', async () => {
    // Keeping the transcript on screen must not let it read as this run's
    // output: the progress rail is live right next to it.
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();

    const note = container.querySelector('[data-state="saved-during-run"]');
    expect(note?.textContent).toContain('Showing the saved transcript');
    expect(container.querySelector('.progress')).toBeTruthy();
    expect(container.querySelector('[data-state="empty"]')).toBeNull();
    expect(container.querySelector('.transcript-summary')?.textContent).toContain('ro');
  });

  it('drops the saved-transcript note once the re-run settles', async () => {
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();
    expect(container.querySelector('[data-state="saved-during-run"]')).toBeTruthy();

    await act(async () => {
      fake.fireDone({
        jobId: 'job-t',
        result: { transcript: savedTranscript({ language: 'sv' }) },
      });
      await Promise.resolve();
    });

    expect(container.querySelector('[data-state="saved-during-run"]')).toBeNull();
  });

  it('REPLACES it when the re-run actually succeeds', async () => {
    // The other direction — "never clear" must not become "never update".
    const fake = makeFakeApi({ project: { transcript: savedTranscript() } });
    await mountHydrated(fake);
    await clickPrimary();

    await act(async () => {
      fake.fireDone({
        jobId: 'job-t',
        result: { transcript: savedTranscript({ language: 'sv', durationSec: 7.5 }) },
      });
      await Promise.resolve();
    });

    const summary = container.querySelector('.transcript-summary');
    expect(summary?.textContent).toContain('sv');
    expect(summary?.textContent).toContain('7.5s');
    expect(summary?.textContent).not.toContain('42.5s');
  });

  it('still shows the empty note when a FIRST run fails and nothing is on disk', async () => {
    // The genuinely-empty case: here "No transcript yet" is TRUE, so it must
    // still render alongside the run error. The fix narrows a false claim; it
    // must not suppress the true one.
    const fake = makeFakeApi({ project: {} });
    install(fake);
    await act(async () => {
      root.render(<Transcribe videoId="v1" />);
    });
    expect(startBtn().textContent).toContain('Start transcription');
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('no audio stream'));

    await clickPrimary();

    expect(container.querySelector('[role="alert"]')?.textContent).toContain('no audio stream');
    expect(container.querySelector('[data-state="empty"]')).toBeTruthy();
    expect(container.querySelector('.transcript-summary')).toBeNull();
    expect(startBtn().textContent).toContain('Start transcription');
  });
});
