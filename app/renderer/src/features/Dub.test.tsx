// Dub.test.tsx — tests for the Dub panel (unit: T2).
//
// Strategy mirrors Assets.test.tsx: pure helpers tested with no render;
// component tests use React 18's react-dom/client + act under jsdom with the
// RPC bridge mocked (a fake `MediaStudioApi`) — no real sidecar, no network.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import Dub, {
  ENGINES,
  type AudioTrack,
  type TtsVoice,
  buildDubParams,
  dubMediaUrl,
  voicesForEngine,
} from './Dub';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

const VOICES: TtsVoice[] = [
  { id: 'af_sarah', engine: 'kokoro', lang: 'en-us', name: 'Sarah' },
  { id: 'am_adam', engine: 'kokoro', lang: 'en-us', name: 'Adam' },
  { id: 'en-US-AriaNeural', engine: 'edgetts', lang: 'en-US', name: 'Aria — ONLINE' },
  { id: 'samp1234', engine: 'chatterbox', lang: 'und', name: 'My voice (cloned sample)' },
];

const AUDIO_TRACKS: AudioTrack[] = [
  { id: 'a1', lang: 'eng', name: 'Audio 1', kind: 'original', path: 'C:/v.mkv' },
  {
    id: 'a2',
    lang: 'de',
    name: 'Dub (kokoro, de)',
    kind: 'dub',
    voice: 'af_sarah',
    path: 'C:/d.m4a',
  },
];

// ---------------------------------------------------------------------------
// pure helpers
// ---------------------------------------------------------------------------

describe('ENGINES', () => {
  it('ships exactly the three A4 engines, edgetts labeled ONLINE', () => {
    expect(ENGINES.map((e) => e.id)).toEqual(['kokoro', 'edgetts', 'chatterbox']);
    const edge = ENGINES.find((e) => e.id === 'edgetts')!;
    expect(edge.online).toBe(true);
    expect(edge.label).toContain('ONLINE');
    expect(ENGINES.find((e) => e.id === 'chatterbox')!.voiceClone).toBe(true);
  });
});

describe('voicesForEngine', () => {
  it('filters the catalog to one engine', () => {
    expect(voicesForEngine(VOICES, 'kokoro').map((v) => v.id)).toEqual(['af_sarah', 'am_adam']);
    expect(voicesForEngine(VOICES, 'chatterbox').map((v) => v.id)).toEqual(['samp1234']);
    expect(voicesForEngine(VOICES, 'nope')).toEqual([]);
  });
});

describe('buildDubParams', () => {
  it('uses voice for named-voice engines and omits sampleId', () => {
    const params = buildDubParams({
      videoId: 'v1',
      trackId: 't1',
      engine: 'kokoro',
      voice: 'af_sarah',
      sampleId: 'should-not-appear',
    });
    expect(params).toEqual({
      videoId: 'v1',
      trackId: 't1',
      engine: 'kokoro',
      voice: 'af_sarah',
    });
  });

  it('uses sampleId for the clone engine and omits voice', () => {
    const params = buildDubParams({
      videoId: 'v1',
      trackId: 't1',
      engine: 'chatterbox',
      voice: 'samp1234',
      sampleId: 'samp1234',
    });
    expect(params).toEqual({
      videoId: 'v1',
      trackId: 't1',
      engine: 'chatterbox',
      sampleId: 'samp1234',
    });
  });

  it('treats an unknown engine as non-cloning (uses voice, no sampleId)', () => {
    const params = buildDubParams({
      videoId: 'v',
      trackId: 't',
      engine: 'mystery-engine',
      voice: 'x',
      sampleId: 's',
    });
    expect(params).toMatchObject({ engine: 'mystery-engine', voice: 'x' });
    expect(params).not.toHaveProperty('sampleId');
  });

  it('includes targetLang only when non-blank (trimmed)', () => {
    expect(
      buildDubParams({
        videoId: 'v',
        trackId: 't',
        engine: 'kokoro',
        voice: 'x',
        targetLang: '  de  ',
      }).targetLang,
    ).toBe('de');
    expect(
      buildDubParams({
        videoId: 'v',
        trackId: 't',
        engine: 'kokoro',
        voice: 'x',
        targetLang: '   ',
      }),
    ).not.toHaveProperty('targetLang');
  });
});

describe('dubMediaUrl', () => {
  it('rides mstream:// with the dub:<path> id form, fully encoded', () => {
    const url = dubMediaUrl('C:\\dubs\\my dub.wav');
    expect(url).toBe(`mstream://media/${encodeURIComponent('dub:C:\\dubs\\my dub.wav')}`);
    expect(url.startsWith('mstream://media/dub%3A')).toBe(true);
    // a single path segment: no raw spaces, backslashes or extra slashes
    expect(url.split('/').length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// component (jsdom + mocked bridge)
// ---------------------------------------------------------------------------

type ProgressCb = (ev: ProgressEvent) => void;
type DoneCb = (ev: DoneEvent) => void;

function makeBridge(overrides: Partial<Record<string, unknown>> = {}) {
  const progressCbs: ProgressCb[] = [];
  const doneCbs: DoneCb[] = [];
  const calls: { method: string; params?: Record<string, unknown> }[] = [];
  const responses: Record<string, unknown> = {
    'tts.voices': { voices: VOICES },
    'tracks.list': {
      tracks: [{ id: 't1', lang: 'en', name: 'English', format: 'srt', kind: 'soft', cues: [] }],
    },
    'tracks.audio.list': { audioTracks: AUDIO_TRACKS },
    'tts.dub.start': { jobId: 'job-9' },
    'job.cancel': { ok: true },
    ...overrides,
  };
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (!(method in responses)) throw new Error(`unexpected rpc: ${method}`);
      return responses[method] as T;
    }) as MediaStudioApi['rpc'],
    onProgress: (cb: ProgressCb) => {
      progressCbs.push(cb);
      return () => undefined;
    },
    onJobDone: (cb: DoneCb) => {
      doneCbs.push(cb);
      return () => undefined;
    },
  };
  return { api, calls, progressCbs, doneCbs };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
  });
}

describe('<Dub />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('loads voices, tracks and audio tracks on mount', async () => {
    const { api, calls } = makeBridge();
    await act(async () => {
      root = createRoot(container);
      root.render(<Dub videoId="v1" api={api} />);
    });
    await flush();
    const methods = calls.map((c) => c.method);
    expect(methods).toContain('tts.voices');
    expect(methods).toContain('tracks.list');
    expect(methods).toContain('tracks.audio.list');
    // the A3 audio-track list renders both rows
    expect(container.querySelectorAll('.audio-track-row')).toHaveLength(2);
    expect(container.textContent).toContain('Dub (kokoro, de)');
  });

  it('starts a dub job and renders the WAV audition on job.done', async () => {
    const { api, calls, doneCbs } = makeBridge();
    await act(async () => {
      root = createRoot(container);
      root.render(<Dub videoId="v1" api={api} />);
    });
    await flush();

    const trackPicker = container.querySelector('[data-picker="track"]') as HTMLSelectElement;
    await act(async () => {
      trackPicker.value = 't1';
      trackPicker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const start = container.querySelector('[data-action="start-dub"]') as HTMLButtonElement;
    expect(start.disabled).toBe(false);
    await act(async () => {
      start.click();
    });
    await flush();

    const dubCall = calls.find((c) => c.method === 'tts.dub.start');
    expect(dubCall?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
      engine: 'kokoro',
      voice: 'af_sarah',
    });

    // job.done resolves the audition player with the dub WAV
    await act(async () => {
      doneCbs.forEach((cb) =>
        cb({
          jobId: 'job-9',
          result: {
            audioTrack: {
              id: 'a3',
              lang: 'en',
              name: 'Dub (kokoro, en)',
              kind: 'dub',
              voice: 'af_sarah',
              path: 'C:/dubs/dub.m4a',
            },
            path: 'C:/dubs/dub.wav',
          },
        }),
      );
    });
    await flush();
    const audio = container.querySelector('[data-testid="dub-audio"]') as HTMLAudioElement;
    expect(audio).toBeTruthy();
    expect(audio.getAttribute('src')).toBe(dubMediaUrl('C:/dubs/dub.wav'));
  });

  it('surfaces the A3 job.done error payload', async () => {
    const { api, doneCbs } = makeBridge();
    await act(async () => {
      root = createRoot(container);
      root.render(<Dub videoId="v1" api={api} />);
    });
    await flush();
    const trackPicker = container.querySelector('[data-picker="track"]') as HTMLSelectElement;
    await act(async () => {
      trackPicker.value = 't1';
      trackPicker.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    await act(async () => {
      doneCbs.forEach((cb) =>
        cb({
          jobId: 'job-9',
          result: { error: { message: 'synthesis exploded', type: 'DubError' } },
        }),
      );
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('synthesis exploded');
    expect(container.querySelector('[data-testid="dub-audio"]')).toBeNull();
  });

  async function mount(api: MediaStudioApi, videoId = 'v1'): Promise<void> {
    await act(async () => {
      root = createRoot(container);
      root.render(<Dub videoId={videoId} api={api} />);
    });
    await flush();
  }

  function pick(selector: string, value: string) {
    const el = container.querySelector(selector) as HTMLSelectElement | HTMLInputElement;
    const proto =
      el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(
        new Event(el instanceof HTMLSelectElement ? 'change' : 'input', {
          bubbles: true,
        }),
      );
    });
  }

  it('streams progress for the active dub job and renders the bar', async () => {
    const { api, progressCbs } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    await act(async () => {
      progressCbs.forEach((cb) => cb({ jobId: 'job-9', pct: 55, message: 'synthesizing' }));
    });
    expect(container.querySelector('.progress')?.textContent).toContain('55%');
    expect(container.querySelector('.progress-message')?.textContent).toContain('synthesizing');
    // A progress event for a different job is ignored.
    await act(async () => {
      progressCbs.forEach((cb) => cb({ jobId: 'other', pct: 99, message: 'not mine' }));
    });
    expect(container.querySelector('.progress')?.textContent).not.toContain('99%');
  });

  it('cancels the active dub job via job.cancel', async () => {
    const { api, calls } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    const cancel = container.querySelector('[data-action="cancel"]') as HTMLButtonElement;
    expect(cancel).toBeTruthy();
    await act(async () => {
      cancel.click();
      await Promise.resolve();
    });
    expect(calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-9' });
    expect(container.querySelector('.progress-message')?.textContent).toContain('Cancelling…');
  });

  it('cancel swallows a job.cancel rejection (best-effort)', async () => {
    const { api } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    (api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('already done'));
    await act(async () => {
      (container.querySelector('[data-action="cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('switching to the clone engine sends sampleId (and shows the voice-sample label)', async () => {
    const { api, calls } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    pick('[data-picker="engine"]', 'chatterbox');
    await flush();
    // The voice label flips to "Voice sample" for the clone engine.
    expect(container.textContent).toContain('Voice sample');
    // The single chatterbox voice (samp1234) auto-selects.
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    expect(calls.find((c) => c.method === 'tts.dub.start')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
      engine: 'chatterbox',
      sampleId: 'samp1234',
    });
  });

  it('carries the engine + voice + target language picks into tts.dub.start', async () => {
    const { api, calls } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    pick('[data-picker="engine"]', 'edgetts');
    await flush();
    pick('[data-picker="voice"]', 'en-US-AriaNeural');
    pick('[data-picker="lang"]', 'de');
    // edgetts is ONLINE -> the button shows the ONLINE label.
    expect(
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).textContent,
    ).toContain('ONLINE');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    expect(calls.find((c) => c.method === 'tts.dub.start')?.params).toEqual({
      videoId: 'v1',
      trackId: 't1',
      engine: 'edgetts',
      voice: 'en-US-AriaNeural',
      targetLang: 'de',
    });
  });

  it('prompts to add a sample when the clone engine has no voices', async () => {
    // No chatterbox voices in the catalog.
    const { api } = makeBridge({
      'tts.voices': {
        voices: [{ id: 'af_sarah', engine: 'kokoro', lang: 'en-us', name: 'Sarah' }],
      },
    });
    await mount(api);
    pick('[data-picker="engine"]', 'chatterbox');
    await flush();
    expect(container.textContent).toContain('add a voice sample below');
  });

  it('the Refresh button re-fetches the catalog', async () => {
    const { api, calls } = makeBridge();
    await mount(api);
    const before = calls.filter((c) => c.method === 'tts.voices').length;
    await act(async () => {
      (container.querySelector('[data-action="refresh"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(calls.filter((c) => c.method === 'tts.voices').length).toBe(before + 1);
  });

  it('surfaces a non-Error refresh rejection via String(err)', async () => {
    const { api } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue('plain catalog error');
    await mount(api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain catalog error');
  });

  it('coerces non-array catalog payloads to empty lists', async () => {
    const { api } = makeBridge({
      'tts.voices': { voices: 'nope' },
      'tracks.list': { tracks: 'nope' },
      'tracks.audio.list': { audioTracks: 'nope' },
    });
    await mount(api);
    expect(container.querySelector('.audio-track-empty')).toBeTruthy();
    // No voices for the default engine -> the "no voices" option shows.
    expect(container.textContent).toContain('no voices');
  });

  it('skips the per-video lists when there is no videoId', async () => {
    const { api, calls } = makeBridge();
    await mount(api, '');
    expect(calls.some((c) => c.method === 'tracks.list')).toBe(false);
    expect(calls.some((c) => c.method === 'tracks.audio.list')).toBe(false);
    expect(calls.some((c) => c.method === 'tts.voices')).toBe(true);
  });

  it('renders an audio track without a voice (no voice chip)', async () => {
    const { api } = makeBridge({
      'tracks.audio.list': {
        audioTracks: [
          { id: 'a1', lang: 'eng', name: 'Original', kind: 'original', path: 'C:/v.mkv' },
        ],
      },
    });
    await mount(api);
    const row = container.querySelector('[data-audio-track="a1"]')!;
    expect(row.querySelector('.audio-track-voice')).toBeNull();
  });

  it('renders the dub result without a voice line when the track has no voice', async () => {
    const { api, doneCbs } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    await act(async () => {
      doneCbs.forEach((cb) =>
        cb({
          jobId: 'job-9',
          result: {
            audioTrack: { id: 'a3', lang: 'en', name: 'Dub', kind: 'dub', path: 'C:/d.m4a' },
            path: 'C:/dubs/dub.wav',
          },
        }),
      );
    });
    await flush();
    const name = container.querySelector('.dub-result-name')!;
    expect(name.textContent).not.toContain('voice ');
  });

  it('surfaces a non-Error dub rejection via String(err)', async () => {
    const { api } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    (api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce('plain dub error');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain dub error');
  });

  it('handles a dub start with no jobId (no job.done wait)', async () => {
    const { api } = makeBridge({ 'tts.dub.start': {} });
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-testid="dub-audio"]')).toBeNull();
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const { api, calls } = makeBridge();
    (globalThis as { api?: unknown }).api = api;
    try {
      await act(async () => {
        root = createRoot(container);
        root.render(<Dub videoId="v1" />);
      });
      await flush();
      expect(calls.some((c) => c.method === 'tts.voices')).toBe(true);
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });

  it('surfaces an Error refresh rejection via its message', async () => {
    const { api } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('catalog error obj'));
    await mount(api);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('catalog error obj');
  });

  it('surfaces an Error dub rejection via its message', async () => {
    const { api } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    (api.rpc as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('dub error obj'));
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('dub error obj');
  });

  it('treats a null dub job.done payload as a no-op (extract ?? null)', async () => {
    const { api, doneCbs } = makeBridge();
    await mount(api);
    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    await act(async () => {
      doneCbs.forEach((cb) => cb({ jobId: 'job-9', result: undefined }));
    });
    await flush();
    expect(container.querySelector('[data-testid="dub-audio"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('reports a non-Error tts.sample.add rejection via String(err)', async () => {
    const { api } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tts.sample.add') throw 'plain sample error';
      if (method === 'tts.voices') return { voices: VOICES };
      if (method === 'tracks.list') return { tracks: [] };
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      return {};
    });
    await mount(api);
    pick('[data-input="sample-path"]', 'C:/x.wav');
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.dub-sample-message')?.textContent).toContain(
      'plain sample error',
    );
  });

  it('add-sample is disabled with a blank path and reports tts.sample.add errors', async () => {
    const { api } = makeBridge({ 'tts.sample.add': new Error('bad sample') as never });
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tts.sample.add') throw new Error('bad sample file');
      if (method === 'tts.voices') return { voices: VOICES };
      if (method === 'tracks.list') return { tracks: [] };
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      return {};
    });
    await mount(api);
    // Blank path -> button disabled.
    expect(
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).disabled,
    ).toBe(true);
    pick('[data-input="sample-path"]', 'C:/bad.wav');
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.dub-sample-message')?.textContent).toContain(
      'bad sample file',
    );
  });

  it('adds a voice sample through tts.sample.add', async () => {
    const { api, calls } = makeBridge({
      'tts.sample.add': {
        sample: { id: 's9', name: 'me', path: 'C:/voices/s9.wav', durationSec: 4 },
      },
    });
    await act(async () => {
      root = createRoot(container);
      root.render(<Dub videoId="v1" api={api} />);
    });
    await flush();
    const input = container.querySelector('[data-input="sample-path"]') as HTMLInputElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
      setter.call(input, 'C:/me.wav');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
    });
    await flush();
    const call = calls.find((c) => c.method === 'tts.sample.add');
    expect(call?.params).toEqual({ path: 'C:/me.wav' });
    expect(container.textContent).toContain('Added sample "me"');
  });
});
