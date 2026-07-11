// Tracks.test.tsx — tests for the subtitle-track management panel.
//
// The panel consumes the FROZEN window.api bridge via getApi(), so we install a
// fake on globalThis.api. Covers: list (empty + populated + error), rename/
// relabel-on-blur (incl. the no-op guards), add/remove/burn/strip ops (success +
// error), the burn long-job progress + job.done path, the available-tracks add,
// and refresh.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Tracks from './Tracks';
import type { DoneEvent, MediaStudioApi, ProgressEvent, SubtitleTrack } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function track(over: Partial<SubtitleTrack> = {}): SubtitleTrack {
  return { id: 't1', lang: 'en', name: 'English', format: 'srt', kind: 'soft', cues: [], ...over };
}

function makeFakeApi(opts: { tracks?: SubtitleTrack[]; burnInline?: string } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'tracks.list') return { tracks: opts.tracks ?? [] } as T;
      if (method === 'tracks.strip') return { path: '/out/stripped.mp4' } as T;
      if (method === 'tracks.burn') return { jobId: 'job-burn', path: opts.burnInline } as T;
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

describe('<Tracks />', () => {
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

  async function mount(
    fake: FakeApi,
    props: { videoId?: string; availableTracks?: SubtitleTrack[] } = {},
  ) {
    (globalThis as { api?: unknown }).api = fake.api;
    await act(async () => {
      root.render(
        <Tracks videoId={props.videoId ?? 'v1'} availableTracks={props.availableTracks} />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  it('lists tracks on mount and renders the empty state when there are none', async () => {
    const fake = makeFakeApi({ tracks: [] });
    await mount(fake);
    expect(fake.calls.find((c) => c.method === 'tracks.list')?.params).toEqual({ videoId: 'v1' });
    expect(container.querySelector('.empty')?.textContent).toContain('No subtitle tracks');
  });

  it('renders a row per track with name/lang/kind/format', async () => {
    const fake = makeFakeApi({
      tracks: [track(), track({ id: 't2', lang: 'es', name: 'Spanish' })],
    });
    await mount(fake);
    expect(container.querySelectorAll('.track-row').length).toBe(2);
    expect(container.querySelector('.track-format')?.textContent).toBe('SRT');
  });

  it('surfaces a tracks.list rejection', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('list down'));
    await mount(fake);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('list down');
  });

  it('does not list when there is no videoId', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: '' });
    expect(fake.calls.find((c) => c.method === 'tracks.list')).toBeUndefined();
  });

  it('rename on blur calls tracks.rename only when the value changed and is non-empty', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const name = container.querySelector('[aria-label="Track t1 name"]') as HTMLInputElement;

    // Unchanged value -> no rpc.
    await act(async () => {
      name.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.rename')).toBeUndefined();

    // Changed value -> rpc with trimmed value.
    await act(async () => {
      name.value = '  New name  ';
      name.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.rename')?.params).toEqual({
      trackId: 't1',
      name: 'New name',
    });
  });

  it('relabel on blur calls tracks.relabel with the trimmed language', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const lang = container.querySelector('[aria-label="Track t1 language"]') as HTMLInputElement;
    await act(async () => {
      lang.value = 'es';
      lang.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.relabel')?.params).toEqual({
      trackId: 't1',
      lang: 'es',
    });
    expect(container.querySelector('.status')?.textContent).toContain('Relabelled');
  });

  it('Add (from the available section) / Remove (row) call the right method', async () => {
    // Attached rows no longer carry an `Add` button (re-adding an already-listed
    // track just persists a duplicate), so Add is exercised via the available
    // section and Remove via the row.
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake, { availableTracks: [track({ id: 'avail-1' })] });

    const addBtn = container.querySelector('.available-tracks button') as HTMLButtonElement;
    await act(async () => {
      addBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.add')?.params).toEqual({
      videoId: 'v1',
      trackId: 'avail-1',
    });

    const removeBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.remove')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
    });
  });

  it('attached-track rows expose no Add button (re-adding would duplicate the track)', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const row = container.querySelector('.track-row')!;
    expect([...row.querySelectorAll('button')].some((b) => b.textContent === 'Add')).toBe(false);
  });

  it('surfaces an error when a mutation op rejects', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('remove failed'));
    const removeBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('remove failed');
  });

  it('Strip op calls tracks.strip and shows the output path', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const stripBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Strip',
    ) as HTMLButtonElement;
    await act(async () => {
      stripBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.strip')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
    });
    expect(container.querySelector('.status')?.textContent).toContain('/out/stripped.mp4');
  });

  it('surfaces an error when strip rejects', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('strip boom');
    const stripBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Strip',
    ) as HTMLButtonElement;
    await act(async () => {
      stripBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('strip boom');
  });

  it('Burn streams progress and resolves the output via job.done', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-burn', pct: 50, message: 'burning' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('50%');
    await act(async () => {
      fake.fireDone({ jobId: 'job-burn', result: { path: '/out/burned.mp4' } });
      await Promise.resolve();
    });
    expect(container.querySelector('.status')?.textContent).toContain('/out/burned.mp4');
  });

  it('Burn honors an inlined path on the rpc resolution (fast path)', async () => {
    const fake = makeFakeApi({ tracks: [track()], burnInline: '/out/inline-burn.mp4' });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.querySelector('.status')?.textContent).toContain('/out/inline-burn.mp4');
  });

  it('surfaces an error when burn rejects', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('burn failed'));
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('burn failed');
  });

  it('burn shows a Cancel button and cancel calls job.cancel with the burn jobId', async () => {
    // burnInline undefined → the rpc resolves {jobId} only, so burn stays in
    // flight on waitForJobDone (Cancel stays offered).
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    const cancelBtn = [...container.querySelectorAll('.track-ops button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancelBtn).toBeTruthy();
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({
      jobId: 'job-burn',
    });
    expect(container.querySelector('.status')?.textContent).toContain('Cancelled');
    // Cancel drops the panel back to idle, so the progress bar + Cancel are gone.
    expect(container.querySelector('.progress')).toBeNull();
    expect(
      [...container.querySelectorAll('.track-ops button')].some((b) => b.textContent === 'Cancel'),
    ).toBe(false);
  });

  it('cancel swallows a job.cancel rejection (best-effort) and still returns to idle', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    // Make the job.cancel rpc reject; cancel must swallow it (no unhandled rejection).
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('cancel boom'));
    const cancelBtn = [...container.querySelectorAll('.track-ops button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    await act(async () => {
      cancelBtn.click();
      await Promise.resolve();
    });
    // No error banner (best-effort), and the panel is back to idle/Cancelled.
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.status')?.textContent).toContain('Cancelled');
  });

  it('clears the burn progress bar when the job fails via a job.done error', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-burn', pct: 50, message: 'burning' });
    });
    // In flight → the bar is shown at 50%.
    expect(container.querySelector('.progress')?.textContent).toContain('50%');
    await act(async () => {
      fake.fireDone({
        jobId: 'job-burn',
        result: { error: { message: 'ffmpeg failed', type: 'BurnError' } },
      });
      await Promise.resolve();
    });
    // Failure → the stale bar is gone and the error is surfaced loudly.
    expect(container.querySelector('.progress')).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ffmpeg failed');
  });

  it('refresh re-lists when the Refresh button is clicked', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const refreshBtn = [...container.querySelectorAll('.actions button')].find(
      (b) => b.textContent === 'Refresh',
    ) as HTMLButtonElement;
    const before = fake.calls.filter((c) => c.method === 'tracks.list').length;
    await act(async () => {
      refreshBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.filter((c) => c.method === 'tracks.list').length).toBe(before + 1);
  });

  it('coerces an absent tracks field to an empty list', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockResolvedValueOnce({}); // no `tracks` key
    await mount(fake);
    expect(container.querySelector('.empty')).toBeTruthy();
  });

  it('uses String(err) when tracks.list rejects with a non-Error value', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain list error');
    await mount(fake);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain list error');
  });

  it('uses String(err) when a mutation op rejects with a non-Error value', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain remove error');
    const removeBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain remove error');
  });

  it('uses Error.message when strip rejects with an Error instance', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('strip error obj'));
    const stripBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Strip',
    ) as HTMLButtonElement;
    await act(async () => {
      stripBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('strip error obj');
  });

  it('uses String(err) when burn rejects with a non-Error value', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain burn error');
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain burn error');
  });

  it('ignores burn progress for a different job', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    const burnBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Burn in',
    ) as HTMLButtonElement;
    await act(async () => {
      burnBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-burn', pct: 33, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'other-job', pct: 99, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
    expect(container.querySelector('.progress')?.textContent).toContain('33%');
  });

  it('shows the in-flight op label (…) while a mutation op is running', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    // Hang the next op so the busy label renders.
    let release: (v: unknown) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((res) => (release = res)),
    );
    const removeBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    expect(
      [...container.querySelectorAll('.track-ops button')].some((b) => b.textContent === '…'),
    ).toBe(true);
    await act(async () => {
      release({});
      await Promise.resolve();
    });
  });

  it('shows the … label on the Remove button while a remove op is running', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    let release: (v: unknown) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((res) => (release = res)),
    );
    const removeBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    ) as HTMLButtonElement;
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    // The Remove button (1st op button now the row Add is gone) shows the ellipsis.
    const opButtons = [...container.querySelectorAll('.track-ops button')];
    expect(opButtons[0].textContent).toBe('…'); // Remove is the 1st op button
    await act(async () => {
      release({});
      await Promise.resolve();
    });
  });

  it('shows the Stripping… label while a strip op is running', async () => {
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake);
    let release: (v: unknown) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementationOnce(
      () => new Promise((res) => (release = res)),
    );
    const stripBtn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Strip',
    ) as HTMLButtonElement;
    await act(async () => {
      stripBtn.click();
      await Promise.resolve();
    });
    expect(
      [...container.querySelectorAll('.track-ops button')].some(
        (b) => b.textContent === 'Stripping…',
      ),
    ).toBe(true);
    await act(async () => {
      release({ path: '/x.mp4' });
      await Promise.resolve();
    });
  });

  it('renders the available-tracks section and adds an existing track', async () => {
    const fake = makeFakeApi({ tracks: [] });
    await mount(fake, { availableTracks: [track({ id: 'avail-1', name: '', lang: 'de' })] });
    const section = container.querySelector('.available-tracks')!;
    expect(section).toBeTruthy();
    // name falls back to id when blank.
    expect(section.textContent).toContain('avail-1');
    const addBtn = section.querySelector('button') as HTMLButtonElement;
    await act(async () => {
      addBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.add')?.params).toEqual({
      videoId: 'v1',
      trackId: 'avail-1',
    });
  });
});
