// Convert.test.tsx — tests for the Convert (ffmpeg options) feature panel.
//
// Consumes the FROZEN window.api bridge via getApi(); we install a fake on
// globalThis.api. Covers: render + source label fallbacks, the video-options
// form vs the audio-only branch, option edits, convert.start (progress +
// job.done path + inline fast path + error), convert.batch (success + early
// guard), cancel, and the path-vs-videoId param selection.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Convert from './Convert';
import type { ConvertBatchItem, DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(opts: { startInline?: string; batchInline?: string[] } = {}): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'convert.start') return { jobId: 'job-c', path: opts.startInline } as T;
      if (method === 'convert.batch') return { jobId: 'job-cb', paths: opts.batchInline } as T;
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

describe('<Convert />', () => {
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
    props: { videoId?: string; path?: string; batchItems?: ConvertBatchItem[] } = {},
  ) {
    (globalThis as { api?: unknown }).api = fake.api;
    await act(async () => {
      root.render(<Convert {...props} />);
    });
  }

  function submit() {
    const form = container.querySelector('form')!;
    return act(async () => {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
  }

  it('shows the videoId as the source and disables convert with no source', async () => {
    const fake = makeFakeApi();
    await mount(fake, {});
    expect(container.querySelector('.source-label code')?.textContent).toBe('(no source)');
    expect((container.querySelector('button[type="submit"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('shows the path as the source when no videoId is given', async () => {
    const fake = makeFakeApi();
    await mount(fake, { path: '/in/clip.mov' });
    expect(container.querySelector('.source-label code')?.textContent).toBe('/in/clip.mov');
  });

  it('renders the video options by default and swaps to audio format when audio-only is toggled', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });
    expect(container.querySelector('#convert-container')).toBeTruthy();
    expect(container.querySelector('#convert-audio-format')).toBeNull();

    const audioOnly = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => {
      audioOnly.click();
    });
    expect(container.querySelector('#convert-audio-format')).toBeTruthy();
    expect(container.querySelector('#convert-container')).toBeNull();
  });

  it('start sends the edited options and resolves the output via job.done', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });

    const setSelect = (id: string, value: string) => {
      const el = container.querySelector(id) as HTMLSelectElement;
      act(() => {
        el.value = value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
      });
    };
    setSelect('#convert-container', 'mkv');
    setSelect('#convert-vcodec', 'libx265');
    setSelect('#convert-acodec', 'libopus');
    setSelect('#convert-scale', '1280:-2');

    const setInput = (id: string, value: string) => {
      const el = container.querySelector(id) as HTMLInputElement;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
      act(() => {
        setter.call(el, value);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      });
    };
    setInput('#convert-fps', '30');
    setInput('#convert-crf', '20');

    await submit();
    const startCall = fake.calls.find((c) => c.method === 'convert.start')!;
    expect(startCall.params).toEqual({
      videoId: 'v1',
      options: expect.objectContaining({
        container: 'mkv',
        vcodec: 'libx265',
        acodec: 'libopus',
        scale: '1280:-2',
        fps: '30',
        crf: '20',
      }),
    });

    await act(async () => {
      fake.fireProgress({ jobId: 'job-c', pct: 70, message: 'encoding' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('70%');

    await act(async () => {
      fake.fireDone({ jobId: 'job-c', result: { path: '/out/done.mkv' } });
      await Promise.resolve();
    });
    expect(container.querySelector('.output-paths')?.textContent).toContain('/out/done.mkv');
  });

  it('sends path (not videoId) when only a path source is given', async () => {
    const fake = makeFakeApi({ startInline: '/out/x.mp4' });
    await mount(fake, { path: '/in/a.mov' });
    await submit();
    await act(async () => {
      await Promise.resolve();
    });
    const startCall = fake.calls.find((c) => c.method === 'convert.start')!;
    expect(startCall.params).toMatchObject({ path: '/in/a.mov' });
    expect((startCall.params as { videoId?: string }).videoId).toBeUndefined();
    expect(container.querySelector('.output-paths')?.textContent).toContain('/out/x.mp4');
  });

  it('surfaces an rpc rejection from convert.start', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('ffmpeg crashed'));
    await mount(fake, { videoId: 'v1' });
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ffmpeg crashed');
  });

  it('runs a batch convert over the supplied items', async () => {
    const items: ConvertBatchItem[] = [
      { videoId: 'v1', options: undefined as never },
      { path: '/in/b.mov', options: { container: 'mp4' } as never },
    ];
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1', batchItems: items });
    const batchBtn = [...container.querySelectorAll('button')].find((b) =>
      /Convert batch/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    expect(batchBtn.textContent).toContain('(2)');
    await act(async () => {
      batchBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'convert.batch')).toBeTruthy();
    await act(async () => {
      fake.fireDone({ jobId: 'job-cb', result: { paths: ['/out/1.mp4', '/out/2.mp4'] } });
      await Promise.resolve();
    });
    expect(container.querySelectorAll('.output-paths li').length).toBe(2);
  });

  it('does not show the batch button without batch items', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });
    expect(
      [...container.querySelectorAll('button')].find((b) =>
        /Convert batch/.test(b.textContent ?? ''),
      ),
    ).toBeUndefined();
  });

  it('surfaces an rpc rejection from convert.batch', async () => {
    const items: ConvertBatchItem[] = [{ videoId: 'v1', options: { container: 'mp4' } as never }];
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1', batchItems: items });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('batch boom');
    const batchBtn = [...container.querySelectorAll('button')].find((b) =>
      /Convert batch/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      batchBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('batch boom');
  });

  it('uses String(err) when convert.start rejects with a non-Error value', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain start error');
    await mount(fake, { videoId: 'v1' });
    await submit();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain start error');
  });

  it('uses Error.message when convert.batch rejects with an Error instance', async () => {
    const items: ConvertBatchItem[] = [{ videoId: 'v1', options: { container: 'mp4' } as never }];
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1', batchItems: items });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('batch error obj'));
    const batchBtn = [...container.querySelectorAll('button')].find((b) =>
      /Convert batch/.test(b.textContent ?? ''),
    ) as HTMLButtonElement;
    await act(async () => {
      batchBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('batch error obj');
  });

  it('edits the audio format in the audio-only branch', async () => {
    const fake = makeFakeApi({ startInline: '/out/a.mp3' });
    await mount(fake, { videoId: 'v1' });
    const audioOnly = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    await act(async () => {
      audioOnly.click();
    });
    const fmt = container.querySelector('#convert-audio-format') as HTMLSelectElement;
    await act(async () => {
      fmt.value = 'flac';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await submit();
    const startCall = fake.calls.find((c) => c.method === 'convert.start')!;
    expect(startCall.params).toMatchObject({
      options: expect.objectContaining({ audioOnly: true, audioFormat: 'flac' }),
    });
  });

  it('ignores progress notifications for a different job', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });
    await submit();
    await act(async () => {
      fake.fireProgress({ jobId: 'job-c', pct: 20, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'someone-else', pct: 88, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('88%');
    expect(container.querySelector('.progress')?.textContent).toContain('20%');
  });

  it('cancel swallows a job.cancel rejection (best-effort)', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });
    await submit();
    await act(async () => {
      fake.fireProgress({ jobId: 'job-c', pct: 5, message: 'go' });
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    // Cancellation failures are silent — no error banner.
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('cancel calls job.cancel once a jobId is known', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: 'v1' });
    await submit();
    await act(async () => {
      fake.fireProgress({ jobId: 'job-c', pct: 5, message: 'go' });
    });
    const cancel = [...container.querySelectorAll('button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-c' });
  });
});
