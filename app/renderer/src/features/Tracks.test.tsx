// Tracks.test.tsx — tests for the subtitle-track management panel.
//
// The panel consumes the FROZEN window.api bridge via getApi(), so we install a
// fake on globalThis.api. Covers: list (empty + populated + error), rename/
// relabel-on-blur (incl. the no-op guards), add/remove/burn/strip ops (success +
// error), Remove's destructive confirm (cancel = no-op, approve = removes, and the
// raw-manifest row with no `cues` field), the burn long-job progress + job.done
// path, the available-tracks add, and refresh.

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

  // W04 — REVIEWED TEST CHANGE (not a weakening). Remove used to be gated by a
  // `window.confirm` stub. That stub is satisfied by the native OS confirm and by
  // a themed dialog alike, so it passed in BOTH states and could not have caught
  // W04 (native confirm is unthemeable, has no author-controlled accessible
  // name/description, and blocks the Electron renderer while open). These tests
  // now drive the themed gate. The two assertions that read the prompt STRING off
  // the spy — `confirmSpy.mock.calls[0][0]` containing "English" / "1 cue" /
  // "0 cue" — are preserved verbatim against the gate's rendered text, which is
  // the same copy on the same code path.
  function removeButton(): HTMLButtonElement {
    const btn = [...container.querySelectorAll('.track-row button')].find(
      (b) => b.textContent === 'Remove',
    );
    if (!btn) throw new Error('Remove button not found');
    return btn as HTMLButtonElement;
  }

  /** The open gate's full text, or null when no gate is up. */
  function gateText(): string | null {
    return container.querySelector('.confirm-dialog')?.textContent ?? null;
  }

  async function answerGate(approve: boolean): Promise<void> {
    const gate = container.querySelector('.confirm-dialog');
    if (!gate) throw new Error('themed confirm gate is not open');
    const sel = approve ? '.confirm-dialog-approve' : '.confirm-dialog-cancel';
    await act(async () => {
      gate.querySelector<HTMLButtonElement>(sel)?.click();
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  /** Press Remove on the single row and approve the themed gate it raises. */
  async function removeAndApprove(): Promise<void> {
    const btn = removeButton();
    await act(async () => {
      btn.click();
      await Promise.resolve();
    });
    await answerGate(true);
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

  it('Remove CONFIRMS first and is a no-op when the user cancels', async () => {
    // tracks.remove drops the whole soft-track ROW from the project manifest
    // (sidecar/media_studio/features/tracks.py:135) and project.save() overwrites
    // the manifest with no history. Cues live INLINE on that row, and there is no
    // import RPC, so every hand correction / translation / caption-polish layered
    // on the track dies with it — the transcript-derived base can be regenerated,
    // the edit delta cannot. This is the same class as the already-guarded
    // shorts.delete sites (views/Shorts.tsx:147, views/Library.tsx:461,
    // features/useShortsGallery.ts:99) and KeepCopyControl.tsx:21's standard:
    // "never a silent one-click destructive action".
    const fake = makeFakeApi({
      tracks: [track({ cues: [{ index: 1, start: 0, end: 1, text: 'hand-edited' }] })],
    });
    await mount(fake);
    const native = vi.spyOn(window, 'confirm');
    const removeBtn = removeButton();

    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    // The gate names the track AND the real loss (its cue count).
    expect(gateText()).toContain('English');
    expect(gateText()).toContain('1 cue');
    expect(fake.calls.find((c) => c.method === 'tracks.remove')).toBeUndefined();

    // Declining removes nothing and closes the gate.
    await answerGate(false);
    expect(fake.calls.find((c) => c.method === 'tracks.remove')).toBeUndefined();
    expect(gateText()).toBeNull();

    // Approving the same click removes for real (the guard must not break the
    // happy path).
    await removeAndApprove();
    expect(fake.calls.find((c) => c.method === 'tracks.remove')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
    });
    // The renderer-blocking native dialog is never reached on either path.
    expect(native).not.toHaveBeenCalled();
  });

  it('the Remove prompt reads 0 cues for a legacy row with no cues field', async () => {
    // tracks.list returns manifest rows RAW — list_tracks is `list(_tracks_of(project))`
    // (sidecar/media_studio/features/tracks.py:104-106) and normalization runs only on
    // WRITE (normalize_track, :157-180). So a legacy / hand-edited project.json row can
    // reach the renderer with no `cues` key at all, and an unguarded `t.cues.length`
    // inside the click handler would throw — turning "Remove has no confirmation" into
    // "Remove is a dead button". Timeline.tsx:136 guards the same field for the same
    // reason.
    const legacy = { id: 't1', lang: 'en', name: 'English', format: 'srt', kind: 'soft' };
    const fake = makeFakeApi({ tracks: [legacy as unknown as SubtitleTrack] });
    await mount(fake);
    const removeBtn = removeButton();
    await act(async () => {
      removeBtn.click();
      await Promise.resolve();
    });
    expect(gateText()).toContain('0 cue');
    await answerGate(true);
    expect(fake.calls.find((c) => c.method === 'tracks.remove')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
    });
  });

  it('Add (from the available section) / Remove (row) call the right method', async () => {
    // Attached rows no longer carry an `Add` button (re-adding an already-listed
    // track just persists a duplicate), so Add is exercised via the available
    // section and Remove via the row.
    const fake = makeFakeApi({ tracks: [track()] });
    await mount(fake, { availableTracks: [track({ id: 'avail-1' })] });
    // Remove now confirms first (see the CONFIRM test above); approve it below.
    const addBtn = container.querySelector('.available-tracks button') as HTMLButtonElement;
    await act(async () => {
      addBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'tracks.add')?.params).toEqual({
      videoId: 'v1',
      trackId: 'avail-1',
    });

    await removeAndApprove();
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
    await removeAndApprove();
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
    await removeAndApprove();
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
    await removeAndApprove();
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
    await removeAndApprove();
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
