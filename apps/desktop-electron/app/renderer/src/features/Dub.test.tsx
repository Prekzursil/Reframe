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
  doneErrorMessage,
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
  { id: 'a2', lang: 'de', name: 'Dub (kokoro, de)', kind: 'dub', voice: 'af_sarah', path: 'C:/d.m4a' },
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
    expect(voicesForEngine(VOICES, 'kokoro').map((v) => v.id)).toEqual([
      'af_sarah',
      'am_adam',
    ]);
    expect(voicesForEngine(VOICES, 'chatterbox').map((v) => v.id)).toEqual([
      'samp1234',
    ]);
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
    expect(url).toBe(
      `mstream://media/${encodeURIComponent('dub:C:\\dubs\\my dub.wav')}`,
    );
    expect(url.startsWith('mstream://media/dub%3A')).toBe(true);
    // a single path segment: no raw spaces, backslashes or extra slashes
    expect(url.split('/').length).toBe(4);
  });
});

describe('doneErrorMessage', () => {
  it('pulls the A3 error payload message', () => {
    expect(
      doneErrorMessage({ error: { message: 'synthesis exploded', type: 'DubError' } }),
    ).toBe('synthesis exploded');
  });
  it('null for success payloads', () => {
    expect(doneErrorMessage({ audioTrack: {}, path: 'x.wav' })).toBeNull();
    expect(doneErrorMessage(undefined)).toBeNull();
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
      tracks: [
        { id: 't1', lang: 'en', name: 'English', format: 'srt', kind: 'soft', cues: [] },
      ],
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

    const trackPicker = container.querySelector(
      '[data-picker="track"]',
    ) as HTMLSelectElement;
    await act(async () => {
      trackPicker.value = 't1';
      trackPicker.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const start = container.querySelector(
      '[data-action="start-dub"]',
    ) as HTMLButtonElement;
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
    const audio = container.querySelector(
      '[data-testid="dub-audio"]',
    ) as HTMLAudioElement;
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
    const trackPicker = container.querySelector(
      '[data-picker="track"]',
    ) as HTMLSelectElement;
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
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'synthesis exploded',
    );
    expect(container.querySelector('[data-testid="dub-audio"]')).toBeNull();
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
    const input = container.querySelector(
      '[data-input="sample-path"]',
    ) as HTMLInputElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
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
