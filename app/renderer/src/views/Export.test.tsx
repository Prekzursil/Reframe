// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Export } from './Export';
import type { DoneEvent, ProgressEvent, Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

let hasApiReturn = true;
let progressCb: ((event: ProgressEvent) => void) | null = null;
let doneCb: ((event: DoneEvent) => void) | null = null;
const cuesMock = vi.fn();
const convertStartMock = vi.fn();
const jobCancelMock = vi.fn();

vi.mock('../lib/rpc', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/rpc')>();
  return {
    ...actual,
    hasApi: () => hasApiReturn,
    onProgress: (cb: (event: ProgressEvent) => void) => {
      progressCb = cb;
      return () => {
        progressCb = null;
      };
    },
    onJobDone: (cb: (event: DoneEvent) => void) => {
      doneCb = cb;
      return () => {
        doneCb = null;
      };
    },
    client: {
      ...actual.client,
      captions: { cues: (...args: unknown[]) => cuesMock(...args) },
      convert: {
        ...actual.client.convert,
        start: (...args: unknown[]) => convertStartMock(...args),
      },
      job: { ...actual.client.job, cancel: (...args: unknown[]) => jobCancelMock(...args) },
    },
  };
});

const VIDEO: Video = {
  id: 'v1',
  path: '/clips/x.mp4',
  title: 'My Clip',
  addedAt: '2026-01-01',
  durationSec: 40,
  hasTranscript: true,
};

let container: HTMLDivElement;
let root: Root;
const onBack = vi.fn();
const onDeliver = vi.fn();

beforeEach(() => {
  hasApiReturn = true;
  progressCb = null;
  doneCb = null;
  cuesMock.mockReset().mockResolvedValue({ cues: [] });
  convertStartMock.mockReset();
  jobCancelMock.mockReset().mockResolvedValue({ ok: true });
  onBack.mockReset();
  onDeliver.mockReset();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (globalThis as { window?: { api?: unknown } }).window?.api;
  vi.restoreAllMocks();
});

const q = <T extends Element>(sel: string): T | null => container.querySelector<T>(sel);

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function render(video: Video | null): void {
  act(() => {
    root.render(<Export video={video} onBack={onBack} onDeliver={onDeliver} />);
  });
}

/** Drive the two-step guarded commit: open the confirm gate, then approve. */
async function commit(): Promise<void> {
  act(() => q<HTMLButtonElement>('.export-inspector__primary')?.click());
  act(() => q<HTMLButtonElement>('.export-inspector__confirm-approve')?.click());
  await flush();
}

const stageValue = (label: string): string | undefined => {
  const items = Array.from(container.querySelectorAll('.export-stage__item'));
  return (
    items
      .find((el) => el.querySelector('.export-stage__label')?.textContent === label)
      ?.querySelector('.export-stage__value')?.textContent ?? undefined
  );
};

describe('Export view', () => {
  it('shows a no-video empty state that routes back to the Library', () => {
    render(null);
    expect(q('.export-view__empty-title')?.textContent).toBe('Open a video to export');
    act(() => q<HTMLButtonElement>('.export-view__back')?.click());
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(cuesMock).not.toHaveBeenCalled();
  });

  it('seeds the stage and loads the cues being exported', async () => {
    cuesMock.mockResolvedValue({
      cues: [
        { index: 1, start: 1, end: 2, text: 'Hi' },
        { index: 2, start: 3, end: 4, text: 'there' },
      ],
    });
    render(VIDEO);
    await flush();
    expect(cuesMock).toHaveBeenCalledWith('v1');
    expect(q('.export-view__title')?.textContent).toBe('My Clip');
    expect(stageValue('Captions')).toBe('2 words');
    // Idle: the guarded inspector is shown with a default fitting destination.
    expect(q('.export-inspector__primary')?.textContent).toBe('Export to TikTok');
  });

  it('tolerates a missing cue list and a cue-load failure', async () => {
    cuesMock.mockResolvedValueOnce({});
    render(VIDEO);
    await flush();
    expect(stageValue('Captions')).toBe('No captions');
    // A rejecting cue load is silently non-blocking.
    act(() => root.unmount());
    cuesMock.mockReset().mockRejectedValue(new Error('no cues'));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    render(VIDEO);
    await flush();
    expect(q('.export-view__title')?.textContent).toBe('My Clip');
    expect(stageValue('Captions')).toBe('No captions');
  });

  it('no-ops the whole flow when the bridge is unavailable', async () => {
    hasApiReturn = false;
    render(VIDEO);
    await flush();
    expect(cuesMock).not.toHaveBeenCalled();
    await commit();
    expect(convertStartMock).not.toHaveBeenCalled();
    // Still idle — the inspector is shown, no progress.
    expect(q('.export-inspector')).not.toBeNull();
    expect(q('.export-progress')).toBeNull();
  });

  it('runs the guarded commit → determinate progress → terminal success (deferred file)', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1' });
    render(VIDEO);
    await flush();
    await commit();
    // SCOPE FIX (v1.5 aspect-matrix): the target now carries an explicit `out`.
    // Without a per-aspect name every fan-out target derives the same
    // `<stem>.mp4` and the renders overwrite each other; `out` is long-standing
    // sidecar surface (convert.start_handler reads params["out"], confined by
    // convert._confined_output) that the renderer's TYPE simply did not expose.
    expect(convertStartMock).toHaveBeenCalledWith(
      { videoId: 'v1', out: '/clips/x.9x16.mp4' },
      expect.objectContaining({ container: 'mp4', vcodec: 'libx264' }),
    );
    // Determinate progress.
    act(() => progressCb?.({ jobId: 'j1', pct: 60, message: 'Rendering frames…' }));
    expect(q('.export-progress__pct')?.textContent).toBe('60%');
    expect(q('.export-progress__message')?.textContent).toBe('Rendering frames…');
    // A foreign job's progress is ignored.
    act(() => progressCb?.({ jobId: 'other', pct: 99, message: 'nope' }));
    expect(q('.export-progress__pct')?.textContent).toBe('60%');
    // Terminal file arrives via job.done.
    await act(async () => {
      doneCb?.({ jobId: 'j1', result: { path: '/exports/final.mp4' } });
      await flush();
    });
    expect(q('.export-result')?.className).toContain('is-done');
    expect(q('.export-result__path')?.textContent).toBe('/exports/final.mp4');
  });

  it('fans ONE source out to a file per DISTINCT aspect, each with its own name', async () => {
    // Check Square (1:1) alongside the default TikTok (9:16) -> two aspects, two
    // renders, two distinctly-named files from a single guarded commit.
    convertStartMock
      .mockResolvedValueOnce({ jobId: 'j1', path: '/clips/x.9x16.mp4' })
      .mockResolvedValueOnce({ jobId: 'j2', path: '/clips/x.1x1.mp4' });
    render(VIDEO);
    await flush();
    act(() => q<HTMLButtonElement>('[data-preset="square"]')?.click());
    await commit();
    expect(convertStartMock).toHaveBeenCalledTimes(2);
    expect(convertStartMock.mock.calls[0][0]).toEqual({ videoId: 'v1', out: '/clips/x.9x16.mp4' });
    expect(convertStartMock.mock.calls[1][0]).toEqual({ videoId: 'v1', out: '/clips/x.1x1.mp4' });
    expect(q('.export-result')?.className).toContain('is-done');
    const paths = Array.from(container.querySelectorAll('.export-result__path')).map(
      (el) => el.textContent,
    );
    expect(paths).toEqual(['/clips/x.9x16.mp4', '/clips/x.1x1.mp4']);
  });

  it('collapses same-aspect destinations to ONE render (no duplicate files)', async () => {
    // TikTok + Reels + Shorts are three destinations but all 9:16 — the fan-out
    // plan dedupes, so exactly one render runs. This is the assertion that stops
    // the matrix from shipping three byte-identical copies.
    convertStartMock.mockResolvedValue({ jobId: 'j1', path: '/clips/x.9x16.mp4' });
    render(VIDEO);
    await flush();
    act(() => q<HTMLButtonElement>('[data-preset="reels"]')?.click());
    act(() => q<HTMLButtonElement>('[data-preset="shorts"]')?.click());
    await commit();
    expect(convertStartMock).toHaveBeenCalledTimes(1);
  });

  it('spreads fan-out progress across the whole run and counts the files', async () => {
    convertStartMock.mockResolvedValueOnce({ jobId: 'j1' }).mockResolvedValueOnce({ jobId: 'j2' });
    render(VIDEO);
    await flush();
    act(() => q<HTMLButtonElement>('[data-preset="square"]')?.click());
    await commit();
    // File 1 at 60% is 30% of a two-file fan-out, and the message is counted.
    act(() => progressCb?.({ jobId: 'j1', pct: 60, message: 'Rendering frames…' }));
    expect(q('.export-progress__pct')?.textContent).toBe('30%');
    expect(q('.export-progress__message')?.textContent).toBe('[1/2] Rendering frames…');
    await act(async () => {
      doneCb?.({ jobId: 'j1', result: { path: '/clips/x.9x16.mp4' } });
      await flush();
    });
    act(() => progressCb?.({ jobId: 'j2', pct: 50, message: 'Rendering frames…' }));
    expect(q('.export-progress__pct')?.textContent).toBe('75%');
    expect(q('.export-progress__message')?.textContent).toBe('[2/2] Rendering frames…');
    await act(async () => {
      doneCb?.({ jobId: 'j2', result: { path: '/clips/x.1x1.mp4' } });
      await flush();
    });
    expect(q('.export-result')?.className).toContain('is-done');
  });

  it('stops the fan-out on the first target that produces no file', async () => {
    // A partial success would hide the missing file behind a green result.
    convertStartMock.mockResolvedValueOnce({ jobId: 'j1' }).mockResolvedValueOnce({ jobId: 'j2' });
    render(VIDEO);
    await flush();
    act(() => q<HTMLButtonElement>('[data-preset="square"]')?.click());
    await commit();
    await act(async () => {
      doneCb?.({ jobId: 'j1', result: {} });
      await flush();
    });
    expect(convertStartMock).toHaveBeenCalledTimes(1);
    expect(q('.export-result')?.className).toContain('is-failed');
  });

  it('accepts an immediate output path (fast direct-return)', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1', path: '/exports/fast.mp4' });
    render(VIDEO);
    await flush();
    await commit();
    expect(q('.export-result')?.className).toContain('is-done');
    expect(q('.export-result__path')?.textContent).toBe('/exports/fast.mp4');
  });

  it('treats a finish with no file as a failure', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1' });
    render(VIDEO);
    await flush();
    await commit();
    await act(async () => {
      doneCb?.({ jobId: 'j1', result: {} });
      await flush();
    });
    expect(q('.export-result')?.className).toContain('is-failed');
    expect(q('.export-result__error')?.textContent).toBe(
      'The export finished without producing a file.',
    );
  });

  it('surfaces a start failure as a terminal failure with a retry', async () => {
    convertStartMock.mockRejectedValue(new Error('ffmpeg missing'));
    render(VIDEO);
    await flush();
    await commit();
    expect(q('.export-result')?.className).toContain('is-failed');
    expect(q('.export-result__error')?.textContent).toBe('ffmpeg missing');
    // Retry returns to the idle inspector.
    act(() => q<HTMLButtonElement>('.export-result__again')?.click());
    expect(q('.export-inspector')).not.toBeNull();
  });

  it('stringifies a non-Error start rejection', async () => {
    convertStartMock.mockRejectedValue('weird failure');
    render(VIDEO);
    await flush();
    await commit();
    expect(q('.export-result')?.className).toContain('is-failed');
    expect(q('.export-result__error')?.textContent).toBe('weird failure');
  });

  it('cancels an in-flight export (abort + job.cancel) → terminal cancelled', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1' });
    render(VIDEO);
    await flush();
    await commit();
    expect(q('.export-progress')).not.toBeNull();
    await act(async () => {
      q<HTMLButtonElement>('.export-progress__cancel')?.click();
      await flush();
    });
    expect(jobCancelMock).toHaveBeenCalledWith('j1');
    expect(q('.export-result')?.className).toContain('is-cancelled');
  });

  it('cancels cleanly even when job.cancel rejects', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1' });
    jobCancelMock.mockRejectedValue(new Error('cancel boom'));
    render(VIDEO);
    await flush();
    await commit();
    await act(async () => {
      q<HTMLButtonElement>('.export-progress__cancel')?.click();
      await flush();
    });
    expect(q('.export-result')?.className).toContain('is-cancelled');
  });

  // F23 — the cancel LATCH must not survive into the next export. `cancel` sets
  // `cancelRequested.current = true` on every press and the drain at
  // `Export.tsx:126` is TERMINAL: a stale latch makes the SECOND commit cancel a
  // healthy job and paint "Export cancelled — a partial file may remain."
  //
  // This test exists because the behaviour was previously protected by exactly one
  // unasserted line: deleting `onCommit`'s `cancelRequested.current = false` left
  // all 3577 tests green. It is a mutation guard, so it is written against the
  // OBSERVABLE contract (no cancel for the second id, real terminal success) rather
  // than against either clearing site — either one alone must satisfy it.
  it('does not carry a cancel latch into the next export (F23)', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1' });
    render(VIDEO);
    await flush();
    await commit();
    await act(async () => {
      q<HTMLButtonElement>('.export-progress__cancel')?.click();
      await flush();
    });
    expect(q('.export-result')?.className).toContain('is-cancelled');
    expect(jobCancelMock).toHaveBeenCalledWith('j1');

    // "Export again" -> a second, healthy export carrying a FRESH jobId.
    jobCancelMock.mockClear();
    convertStartMock.mockResolvedValue({ jobId: 'j2' });
    act(() => q<HTMLButtonElement>('.export-result__again')?.click());
    await commit();
    await act(async () => {
      doneCb?.({ jobId: 'j2', result: { path: '/exports/second.mp4' } });
      await flush();
    });

    // The stale latch must not have cancelled the second job...
    expect(jobCancelMock).not.toHaveBeenCalled();
    // ...and it must reach a genuine terminal success, not 'cancelled'.
    expect(q('.export-result')?.className).toContain('is-done');
    expect(q('.export-result__path')?.textContent).toBe('/exports/second.mp4');
  });

  // A cancel pressed while `convert.start`'s round-trip is still in flight has no
  // jobId to cancel YET, but the sidecar has already started the job. The latch
  // must drain the moment the id lands, or the job is orphaned (F23).
  it('cancels the job once a late jobId arrives (pre-jobId cancel latch)', async () => {
    let resolveStart!: (value: { jobId: string }) => void;
    convertStartMock.mockReturnValue(
      new Promise<{ jobId: string }>((resolve) => {
        resolveStart = resolve;
      }),
    );
    render(VIDEO);
    await flush();
    await commit(); // convert.start is still pending here
    expect(q('.export-progress')).not.toBeNull();
    // Cancel while there is no jobId yet: nothing is on the wire to cancel.
    act(() => q<HTMLButtonElement>('.export-progress__cancel')?.click());
    expect(jobCancelMock).not.toHaveBeenCalled();
    // The start resolves. The latch must now stop the job the sidecar DID start.
    await act(async () => {
      resolveStart({ jobId: 'late' });
      await flush();
    });
    expect(jobCancelMock).toHaveBeenCalledWith('late');
    // Setup discriminator: this assertion already passed pre-fix, so a failure
    // HERE means the harness is wrong, not the product.
    expect(q('.export-result')?.className).toContain('is-cancelled');
  });

  it('keeps the late cancel terminal even when the start returns a path', async () => {
    let resolveStart!: (value: { jobId: string; path: string }) => void;
    convertStartMock.mockReturnValue(
      new Promise<{ jobId: string; path: string }>((resolve) => {
        resolveStart = resolve;
      }),
    );
    render(VIDEO);
    await flush();
    await commit();
    act(() => q<HTMLButtonElement>('.export-progress__cancel')?.click());
    await act(async () => {
      resolveStart({ jobId: 'late', path: '/exports/fast.mp4' });
      await flush();
    });
    expect(jobCancelMock).toHaveBeenCalledWith('late');
    // A cancelled job must NEVER render a terminal SUCCESS with "Show in folder".
    // Mutation-proved: with the latch removed this renders `is-done`.
    expect(q('.export-result')?.className).toContain('is-cancelled');
    expect(q('.export-result__path')).toBeNull();
  });

  it('swallows a rejected late cancel and still settles to cancelled', async () => {
    jobCancelMock.mockRejectedValue(new Error('cancel boom'));
    let resolveStart!: (value: { jobId: string }) => void;
    convertStartMock.mockReturnValue(
      new Promise<{ jobId: string }>((resolve) => {
        resolveStart = resolve;
      }),
    );
    render(VIDEO);
    await flush();
    await commit();
    act(() => q<HTMLButtonElement>('.export-progress__cancel')?.click());
    await act(async () => {
      resolveStart({ jobId: 'late' });
      await flush();
    });
    expect(jobCancelMock).toHaveBeenCalledWith('late');
    expect(q('.export-result')?.className).toContain('is-cancelled');
  });

  it('reveals the output file and continues into Deliver on success', async () => {
    const openInFolderMock = vi.fn().mockResolvedValue(true);
    (globalThis as { window: { api?: unknown } }).window.api = { openInFolder: openInFolderMock };
    convertStartMock.mockResolvedValue({ jobId: 'j1', path: '/exports/final.mp4' });
    render(VIDEO);
    await flush();
    await commit();
    act(() => q<HTMLButtonElement>('.export-result__reveal')?.click());
    expect(openInFolderMock).toHaveBeenCalledWith('/exports/final.mp4');
    act(() => q<HTMLButtonElement>('.export-result__deliver')?.click());
    expect(onDeliver).toHaveBeenCalledTimes(1);
  });

  it('keeps reveal best-effort when the folder bridge rejects', async () => {
    const openInFolderMock = vi.fn().mockRejectedValue(new Error('explorer crashed'));
    (globalThis as { window: { api?: unknown } }).window.api = { openInFolder: openInFolderMock };
    convertStartMock.mockResolvedValue({ jobId: 'j1', path: '/exports/final.mp4' });
    render(VIDEO);
    await flush();
    await commit();
    await act(async () => {
      q<HTMLButtonElement>('.export-result__reveal')?.click();
      await flush();
    });
    expect(openInFolderMock).toHaveBeenCalled();
    // No crash; the result still stands.
    expect(q('.export-result')?.className).toContain('is-done');
  });

  it('hides the reveal control when no folder bridge is available', async () => {
    convertStartMock.mockResolvedValue({ jobId: 'j1', path: '/exports/final.mp4' });
    render(VIDEO);
    await flush();
    await commit();
    expect(q('.export-result__path')?.textContent).toBe('/exports/final.mp4');
    expect(q('.export-result__reveal')).toBeNull();
  });
});
