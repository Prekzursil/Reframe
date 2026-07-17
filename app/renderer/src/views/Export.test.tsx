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
    expect(stageValue('Captions')).toBe('2 captions');
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
    expect(convertStartMock).toHaveBeenCalledWith(
      { videoId: 'v1' },
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

  it('cancels before the job id resolves (abort settles the pending wait)', async () => {
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
    // Cancel while there is no jobId yet: job.cancel is NOT called.
    act(() => q<HTMLButtonElement>('.export-progress__cancel')?.click());
    expect(jobCancelMock).not.toHaveBeenCalled();
    // Now the start resolves; the already-aborted wait settles to cancelled.
    await act(async () => {
      resolveStart({ jobId: 'late' });
      await flush();
    });
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
