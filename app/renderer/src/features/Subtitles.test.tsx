// Subtitles.test.tsx — tests for the Subtitles feature panel.
//
// Consumes the FROZEN window.api bridge via getApi(); we install a fake on
// globalThis.api. Covers: generate, the track meta + cue editor, in-place cue
// edit + save-on-blur, translate (progress + job.done + inline + bilingual +
// error + cancel), export (success + error), and the no-track guards.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Subtitles from './Subtitles';
import type { DoneEvent, MediaStudioApi, ProgressEvent, SubtitleTrack } from './_api';

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function track(over: Partial<SubtitleTrack> = {}): SubtitleTrack {
  return {
    id: 'tr1',
    lang: 'en',
    name: 'English',
    format: 'srt',
    kind: 'soft',
    cues: [
      { index: 2, start: 5, end: 7, text: 'second' },
      { index: 1, start: 0, end: 2, text: 'first' },
    ],
    ...over,
  };
}

function makeFakeApi(
  opts: { generated?: SubtitleTrack; translateInline?: SubtitleTrack; exportPath?: string } = {},
): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'subtitles.generate') return { track: opts.generated ?? track() } as T;
      if (method === 'subtitles.edit') return { track: track() } as T;
      if (method === 'subtitles.translate') {
        return { jobId: 'job-tr', track: opts.translateInline } as T;
      }
      if (method === 'subtitles.export') return { path: opts.exportPath ?? '/out/sub.srt' } as T;
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

describe('<Subtitles />', () => {
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
    props: { videoId?: string; initialTrack?: SubtitleTrack | null; onTrackChange?: (t: SubtitleTrack) => void } = {},
  ) {
    (globalThis as { api?: unknown }).api = fake.api;
    await act(async () => {
      root.render(
        <Subtitles
          videoId={props.videoId ?? 'v1'}
          initialTrack={props.initialTrack ?? null}
          onTrackChange={props.onTrackChange}
        />,
      );
    });
  }

  function genBtn(): HTMLButtonElement {
    return [...container.querySelectorAll('.actions button')][0] as HTMLButtonElement;
  }

  it('shows only the generate button (no track) until subtitles are generated', async () => {
    const fake = makeFakeApi();
    await mount(fake);
    expect(container.querySelector('.track-meta')).toBeNull();
    expect(genBtn().disabled).toBe(false);
  });

  it('generate calls subtitles.generate, renders the track meta + sorted cues', async () => {
    const fake = makeFakeApi();
    const onTrackChange = vi.fn();
    await mount(fake, { onTrackChange });
    await act(async () => {
      genBtn().click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'subtitles.generate')?.params).toEqual({
      videoId: 'v1',
    });
    expect(container.querySelector('.track-meta')?.textContent).toContain('English');
    // Cues sorted by start: 'first' before 'second'.
    const cues = [...container.querySelectorAll('.cue-text')] as HTMLInputElement[];
    expect(cues.map((c) => c.value)).toEqual(['first', 'second']);
    expect(onTrackChange).toHaveBeenCalled();
  });

  it('disables generate when there is no videoId', async () => {
    const fake = makeFakeApi();
    await mount(fake, { videoId: '' });
    expect(genBtn().disabled).toBe(true);
  });

  it('surfaces an rpc rejection from generate', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('asr down'));
    await mount(fake);
    await act(async () => {
      genBtn().click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('asr down');
  });

  it('edits a cue locally and persists on blur via subtitles.edit', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    const cue = container.querySelector('[aria-label="Cue 1 text"]') as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    await act(async () => {
      setter.call(cue, 'edited first');
      cue.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect((container.querySelector('[aria-label="Cue 1 text"]') as HTMLInputElement).value).toBe(
      'edited first',
    );
    await act(async () => {
      cue.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'subtitles.edit')?.params).toMatchObject({
      trackId: 'tr1',
    });
    expect(container.querySelector('.status')?.textContent).toContain('Saved');
  });

  it('surfaces an rpc rejection from subtitles.edit', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('edit boom');
    const cue = container.querySelector('[aria-label="Cue 1 text"]') as HTMLInputElement;
    await act(async () => {
      cue.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('edit boom');
  });

  it('translate streams progress and applies the job.done track', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    const langSel = container.querySelector('#subtitles-target-lang') as HTMLSelectElement;
    await act(async () => {
      langSel.value = 'fr';
      langSel.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'subtitles.translate')?.params).toEqual({
      trackId: 'tr1',
      targetLang: 'fr',
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-tr', pct: 40, message: 'translating' });
    });
    expect(container.querySelector('.progress')?.textContent).toContain('40%');
    await act(async () => {
      fake.fireDone({ jobId: 'job-tr', result: { track: track({ lang: 'fr', name: 'French' }) } });
      await Promise.resolve();
    });
    expect(container.querySelector('.track-meta')?.textContent).toContain('French');
  });

  it('translate sends bilingual params when the bilingual toggle is on', async () => {
    const fake = makeFakeApi({ translateInline: track({ lang: 'es' }) });
    await mount(fake, { initialTrack: track() });
    const bilingual = container.querySelector('.bilingual-toggle input') as HTMLInputElement;
    await act(async () => {
      bilingual.click();
    });
    // The order select appears only when bilingual is on.
    const order = container.querySelector('[aria-label="Bilingual line order"]') as HTMLSelectElement;
    expect(order).toBeTruthy();
    await act(async () => {
      order.value = 'translation-first';
      order.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'subtitles.translate')?.params).toEqual({
      trackId: 'tr1',
      targetLang: 'en',
      bilingual: true,
      order: 'translation-first',
    });
  });

  it('translate cancel calls job.cancel for the active job', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    // jobId is set after the rpc resolves; while still translating a Cancel shows.
    await act(async () => {
      fake.fireProgress({ jobId: 'job-tr', pct: 10, message: 'go' });
    });
    const cancel = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-tr' });
  });

  it('surfaces an rpc rejection from translate', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('mt down'));
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('mt down');
  });

  it('export calls subtitles.export with the chosen format and shows the saved path', async () => {
    const fake = makeFakeApi({ exportPath: '/out/final.vtt' });
    await mount(fake, { initialTrack: track() });
    const fmt = container.querySelector('#subtitles-export-format') as HTMLSelectElement;
    await act(async () => {
      fmt.value = 'vtt';
      fmt.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const exportBtn = [...container.querySelectorAll('.export-row button')].find(
      (b) => b.textContent === 'Export',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'subtitles.export')?.params).toEqual({
      trackId: 'tr1',
      format: 'vtt',
    });
    expect(container.querySelector('.export-path')?.textContent).toContain('/out/final.vtt');
  });

  it('surfaces an rpc rejection from export', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('export boom');
    const exportBtn = [...container.querySelectorAll('.export-row button')].find(
      (b) => b.textContent === 'Export',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('export boom');
  });

  // --- both arms of each `instanceof Error ? message : String(err)` ternary ---

  it('uses String(err) when generate rejects with a non-Error value', async () => {
    const fake = makeFakeApi();
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain generate error');
    await mount(fake);
    await act(async () => {
      genBtn().click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain generate error');
  });

  it('uses Error.message when subtitles.edit rejects with an Error instance', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('edit error obj'));
    const cue = container.querySelector('[aria-label="Cue 1 text"]') as HTMLInputElement;
    await act(async () => {
      cue.dispatchEvent(new Event('focusout', { bubbles: true }));
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('edit error obj');
  });

  it('uses String(err) when translate rejects with a non-Error value', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain translate error');
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain translate error');
  });

  it('uses Error.message when export rejects with an Error instance', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('export error obj'));
    const exportBtn = [...container.querySelectorAll('.export-row button')].find(
      (b) => b.textContent === 'Export',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('export error obj');
  });

  // --- progress targeting, cancel best-effort, label + meta branches ---

  it('ignores translate progress for a different job', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-tr', pct: 15, message: 'mine' });
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'other-job', pct: 99, message: 'not mine' });
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
    expect(container.querySelector('.progress')?.textContent).toContain('15%');
  });

  it('translate cancel swallows a job.cancel rejection (best-effort)', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track() });
    const translateBtn = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Translate',
    ) as HTMLButtonElement;
    await act(async () => {
      translateBtn.click();
      await Promise.resolve();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-tr', pct: 10, message: 'go' });
    });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    const cancel = [...container.querySelectorAll('.translate-row button')].find(
      (b) => b.textContent === 'Cancel',
    ) as HTMLButtonElement;
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('.status')?.textContent).toContain('Cancelled');
  });

  it('falls back from track name to track id in the meta line', async () => {
    const fake = makeFakeApi();
    await mount(fake, { initialTrack: track({ name: '', id: 'bare-id' }) });
    expect(container.querySelector('.track-meta')?.textContent).toContain('bare-id');
  });

  it('shows the in-flight "Generating…" label while generate is running', async () => {
    const fake = makeFakeApi();
    let resolveGen: (v: { track: SubtitleTrack }) => void = () => undefined;
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      (method: string) =>
        method === 'subtitles.generate'
          ? new Promise((res) => {
              resolveGen = res as (v: { track: SubtitleTrack }) => void;
            })
          : Promise.resolve({}),
    );
    await mount(fake);
    await act(async () => {
      genBtn().click();
      await Promise.resolve();
    });
    expect(genBtn().textContent).toBe('Generating…');
    await act(async () => {
      resolveGen({ track: track() });
      await Promise.resolve();
    });
  });

  it('shows the in-flight "Exporting…" label while export is running', async () => {
    const fake = makeFakeApi();
    let resolveExp: (v: { path: string }) => void = () => undefined;
    await mount(fake, { initialTrack: track() });
    (fake.api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      (method: string) =>
        method === 'subtitles.export'
          ? new Promise((res) => {
              resolveExp = res as (v: { path: string }) => void;
            })
          : Promise.resolve({}),
    );
    const exportBtn = [...container.querySelectorAll('.export-row button')].find(
      (b) => b.textContent === 'Export',
    ) as HTMLButtonElement;
    await act(async () => {
      exportBtn.click();
      await Promise.resolve();
    });
    const liveExportBtn = [...container.querySelectorAll('.export-row button')].find((b) =>
      /Exporting/.test(b.textContent ?? ''),
    );
    expect(liveExportBtn).toBeTruthy();
    await act(async () => {
      resolveExp({ path: '/out/x.srt' });
      await Promise.resolve();
    });
  });
});
