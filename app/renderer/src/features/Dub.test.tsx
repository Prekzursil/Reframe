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
  CONSENT_ATTESTATION_TEXT,
  ENGINES,
  IMPORTED_AUDIO_TRACK_KIND,
  type AudioTrack,
  type TtsVoice,
  buildDubParams,
  buildSampleAddParams,
  canEditAudioTrack,
  canImportAudioTrack,
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

describe('buildSampleAddParams', () => {
  it('always carries consentAttested:true and trims the path', () => {
    expect(buildSampleAddParams({ path: '  C:/me.wav  ' })).toEqual({
      path: 'C:/me.wav',
      consentAttested: true,
    });
  });

  it('includes a trimmed note and omits a blank one', () => {
    expect(buildSampleAddParams({ path: 'p', consentNote: '  ok  ' })).toEqual({
      path: 'p',
      consentAttested: true,
      consentNote: 'ok',
    });
    expect(buildSampleAddParams({ path: 'p', consentNote: '   ' })).not.toHaveProperty(
      'consentNote',
    );
  });
});

describe('CONSENT_ATTESTATION_TEXT', () => {
  it('is the exact sentence the sidecar records and quotes back on refusal', () => {
    // Mirrors voices.CONSENT_ATTESTATION_TEXT — a drift here would promise the
    // user something different from what the backend enforces.
    expect(CONSENT_ATTESTATION_TEXT).toBe(
      "I own this voice or have the speaker's documented permission to clone it.",
    );
  });
});

// W62 — the audio-track EDIT gate. `tracks.audio.replace` / `.strip` are offered
// only for a dub, because their ORIGINAL branch re-muxes the whole container into
// a derived file that is returned but never written back to the project
// (`sidecar/media_studio/features/tracks_audio.py:533-554` / `:578-588`), so the
// app would keep resolving the untouched source while the manifest row vanished.
describe('canEditAudioTrack', () => {
  it('permits a dub and refuses the source recording', () => {
    expect(canEditAudioTrack({ kind: 'dub' })).toBe(true);
    expect(canEditAudioTrack({ kind: 'original' })).toBe(false);
  });
});

describe('canImportAudioTrack', () => {
  it('requires all three fields tracks.audio.mux declares required', () => {
    expect(canImportAudioTrack({ path: 'C:/vo.wav', lang: 'en', name: 'VO' })).toBe(true);
    // Each of the three is independently blocking — `mux` _require_str's all of
    // them (`sidecar/media_studio/features/tracks_audio.py:494-497`), so a blank
    // one must never reach the wire as an INVALID_PARAMS round-trip.
    expect(canImportAudioTrack({ path: '', lang: 'en', name: 'VO' })).toBe(false);
    expect(canImportAudioTrack({ path: 'C:/vo.wav', lang: '', name: 'VO' })).toBe(false);
    expect(canImportAudioTrack({ path: 'C:/vo.wav', lang: 'en', name: '' })).toBe(false);
    // Whitespace-only is blank.
    expect(canImportAudioTrack({ path: '  ', lang: ' en ', name: ' VO ' })).toBe(false);
    expect(canImportAudioTrack({ path: 'C:/vo.wav', lang: '   ', name: 'VO' })).toBe(false);
    expect(canImportAudioTrack({ path: 'C:/vo.wav', lang: 'en', name: '   ' })).toBe(false);
  });
});

describe('IMPORTED_AUDIO_TRACK_KIND', () => {
  it('is "dub" — an imported track is never registered as the original', () => {
    // The AI-disclosure badge is withheld ONLY for kind "original"
    // (AiDisclosure.isAiGeneratedAudioTrack), so letting a user pick the kind
    // would let them suppress the label. Over-labelling an imported human
    // recording is the disclosed, recoverable direction (AiDisclosure.tsx:45-58).
    expect(IMPORTED_AUDIO_TRACK_KIND).toBe('dub');
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

  /** Toggle the WU-A2 blocking consent checkbox (a real click, as a user would). */
  function attest() {
    const box = container.querySelector('[data-input="consent-attest"]') as HTMLInputElement;
    act(() => {
      box.click();
    });
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
    attest();
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
    attest();
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
        sample: {
          id: 's9',
          name: 'me',
          path: 'C:/voices/s9.wav',
          durationSec: 4,
          consentAttested: true,
          consentAt: '2026-08-08T10:20:30Z',
          consentNote: null,
        },
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
    attest();
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
    });
    await flush();
    const call = calls.find((c) => c.method === 'tts.sample.add');
    expect(call?.params).toEqual({ path: 'C:/me.wav', consentAttested: true });
    expect(container.textContent).toContain('Added sample "me"');
  });

  // ------------------------------------------------------------------------
  // WU-A2 — the voice-clone consent gate in the UI (the BLOCKING attestation).
  // docs/plans/v1.5/flagship-lip-sync-dub.md §4 WU-A2 / §5.1: "the checkbox is
  // a first-class gate; add is refused without it".
  // ------------------------------------------------------------------------
  it('keeps add-sample disabled until the consent box is ticked, even with a path', async () => {
    const { api } = makeBridge();
    await mount(api);
    const button = () => container.querySelector('[data-action="add-sample"]') as HTMLButtonElement;
    pick('[data-input="sample-path"]', 'C:/me.wav');
    // path alone is NOT enough — the attestation is the gate
    expect(button().disabled).toBe(true);
    attest();
    expect(button().disabled).toBe(false);
    // untick -> refused again (the gate is not one-way)
    attest();
    expect(button().disabled).toBe(true);
  });

  it('shows the same attestation sentence the sidecar enforces', async () => {
    const { api } = makeBridge();
    await mount(api);
    const label = container.querySelector('[data-testid="consent-attest-label"]');
    expect(label?.textContent).toContain(
      "I own this voice or have the speaker's documented permission to clone it.",
    );
  });

  it('forwards consentAttested + a trimmed consentNote to tts.sample.add', async () => {
    const { api, calls } = makeBridge({
      'tts.sample.add': {
        sample: {
          id: 's1',
          name: 'ann',
          path: 'C:/voices/s1.wav',
          durationSec: 3,
          consentAttested: true,
          consentAt: '2026-08-08T10:20:30Z',
          consentNote: 'signed release',
        },
      },
    });
    await mount(api);
    pick('[data-input="sample-path"]', '  C:/ann.wav  ');
    pick('[data-input="consent-note"]', '  signed release  ');
    attest();
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
    });
    await flush();
    expect(calls.find((c) => c.method === 'tts.sample.add')?.params).toEqual({
      path: 'C:/ann.wav',
      consentAttested: true,
      consentNote: 'signed release',
    });
  });

  it('omits a whitespace-only consentNote', async () => {
    const { api, calls } = makeBridge({
      'tts.sample.add': {
        sample: {
          id: 's2',
          name: 'bo',
          path: 'C:/voices/s2.wav',
          durationSec: 3,
          consentAttested: true,
          consentAt: '2026-08-08T10:20:30Z',
          consentNote: null,
        },
      },
    });
    await mount(api);
    pick('[data-input="sample-path"]', 'C:/bo.wav');
    pick('[data-input="consent-note"]', '    ');
    attest();
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
    });
    await flush();
    expect(calls.find((c) => c.method === 'tts.sample.add')?.params).toEqual({
      path: 'C:/bo.wav',
      consentAttested: true,
    });
  });

  it('clears the attestation after a successful add (a fresh tick per clone)', async () => {
    const { api } = makeBridge({
      'tts.sample.add': {
        sample: {
          id: 's3',
          name: 'cy',
          path: 'C:/voices/s3.wav',
          durationSec: 3,
          consentAttested: true,
          consentAt: '2026-08-08T10:20:30Z',
          consentNote: 'note',
        },
      },
    });
    await mount(api);
    pick('[data-input="sample-path"]', 'C:/cy.wav');
    pick('[data-input="consent-note"]', 'note');
    attest();
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
    });
    await flush();
    const box = container.querySelector('[data-input="consent-attest"]') as HTMLInputElement;
    const note = container.querySelector('[data-input="consent-note"]') as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(note.value).toBe('');
    // and the button is disabled again — one tick can never cover a second clone
    expect(
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('keeps the attestation ticked when the add FAILS so the user can retry', async () => {
    const { api } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(async (method: string) => {
      if (method === 'tts.sample.add') throw new Error('unsupported sample format');
      if (method === 'tts.voices') return { voices: VOICES };
      if (method === 'tracks.list') return { tracks: [] };
      if (method === 'tracks.audio.list') return { audioTracks: [] };
      return {};
    });
    await mount(api);
    pick('[data-input="sample-path"]', 'C:/bad.txt');
    attest();
    await act(async () => {
      (container.querySelector('[data-action="add-sample"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(
      (container.querySelector('[data-input="consent-attest"]') as HTMLInputElement).checked,
    ).toBe(true);
    expect(container.querySelector('.dub-sample-message')?.textContent).toContain(
      'unsupported sample format',
    );
  });

  // ------------------------------------------------------------------------
  // W21 — the AI-content disclosure surface (consent gate 3).
  // docs/plans/v1.5/flagship-lip-sync-dub.md:165/188 — "AI-content label on the
  // dub track + export-time C2PA + surface Chatterbox's Perth watermark".
  // ------------------------------------------------------------------------
  it('labels the dub row — and ONLY the dub row — with the AI-generated badge', async () => {
    const { api } = makeBridge();
    await mount(api);
    // AUDIO_TRACKS = [a1 kind:'original', a2 kind:'dub'] -> exactly one badge.
    expect(container.querySelectorAll('[data-testid="ai-audio-badge"]')).toHaveLength(1);
    const dubRow = container.querySelector('[data-audio-track="a2"]');
    const originalRow = container.querySelector('[data-audio-track="a1"]');
    expect(dubRow?.querySelector('[data-testid="ai-audio-badge"]')).toBeTruthy();
    expect(originalRow?.querySelector('[data-testid="ai-audio-badge"]')).toBeNull();
    expect(dubRow?.textContent).toContain('AI-generated audio');
  });

  it('labels the finished dub result with the AI-generated badge', async () => {
    const { api, doneCbs } = makeBridge({ 'tracks.audio.list': { audioTracks: [] } });
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
    const result = container.querySelector('[data-testid="dub-result"]');
    expect(result?.querySelector('[data-testid="ai-audio-badge"]')).toBeTruthy();
  });

  it('renders the disclosure block and surfaces Perth only for chatterbox', async () => {
    const { api } = makeBridge();
    await mount(api);
    expect(container.querySelector('[data-testid="ai-disclosure"]')).toBeTruthy();
    // kokoro (the default engine) does not watermark.
    expect(container.querySelector('[data-testid="perth-note"]')).toBeNull();
    pick('[data-picker="engine"]', 'chatterbox');
    expect(container.querySelector('[data-testid="perth-note"]')?.textContent).toContain('Perth');
  });

  it('shows the labelling-direction caveat as visible panel text, not only as a tooltip', async () => {
    const { api } = makeBridge();
    await mount(api);
    const note = container.querySelector('[data-testid="ai-disclosure-direction"]');
    expect(note?.textContent).toContain('errs toward marking');
  });

  it('states the C2PA export gap instead of offering a toggle that signs nothing', async () => {
    const { api } = makeBridge();
    await mount(api);
    const row = container.querySelector('[data-testid="c2pa-status"]');
    expect(row?.textContent).toContain('Not available');
    expect(row?.textContent).toContain('signing identity');
  });

  // W20 — the ONLY entry point to `tts.lipsync.start`, which was registered
  // unconditionally (`features/tts/__init__.py:141`) and frozen into the RPC surface
  // but had no caller: this file's subject was 519 lines with ZERO `lipsync`
  // references before this lane. Its own gates/params/job flow are tested in
  // LipSync.test.tsx; what THIS test pins is reachability — that the section is
  // mounted in the dub surface and is handed the audio tracks Dub already fetched,
  // so lip-sync needs no second `tracks.audio.list` call.
  it('mounts the lip-sync section in the dub surface, fed by the tracks Dub already fetched', async () => {
    const { api, calls } = makeBridge();
    await mount(api);
    const section = container.querySelector('[aria-label="Lip-sync"]');
    expect(section).not.toBeNull();
    // The dub track from AUDIO_TRACKS is offerable; the `original` one is not.
    const options = Array.from(
      section!.querySelectorAll('[data-picker="lipsync-track"] option'),
    ).map((o) => (o as HTMLOptionElement).value);
    expect(options).toContain('a2');
    expect(options).not.toContain('a1');
    // Exactly one tracks.audio.list on mount — the child reuses Dub's list.
    expect(calls.filter((c) => c.method === 'tracks.audio.list')).toHaveLength(1);
  });

  // ------------------------------------------------------------------------
  // W62 — `tracks.audio.mux` / `.replace` / `.strip` were registered sidecar-side
  // and wrapped in the typed client but had NO caller anywhere in the renderer,
  // so the Audio-tracks list was read-only display. These tests pin the three
  // user actions that make them reachable.
  // ------------------------------------------------------------------------
  const rowFor = (id: string): HTMLElement =>
    container.querySelector(`li[data-audio-track="${id}"]`) as HTMLElement;
  const rowBtn = (id: string, action: string): HTMLButtonElement =>
    rowFor(id).querySelector(`[data-action="${action}"]`) as HTMLButtonElement;

  it('offers Remove + Replace on a dub row and neither on the source recording', async () => {
    const { api } = makeBridge();
    await mount(api);
    // AUDIO_TRACKS = [a1 kind:'original', a2 kind:'dub'].
    expect(rowBtn('a2', 'strip-audio')).not.toBeNull();
    expect(rowBtn('a2', 'replace-audio')).not.toBeNull();
    expect(rowFor('a1').querySelector('[data-action="strip-audio"]')).toBeNull();
    expect(rowFor('a1').querySelector('[data-action="replace-audio"]')).toBeNull();
    // The original row says WHY instead of silently omitting the controls.
    expect(rowFor('a1').textContent).toContain('Source audio');
  });

  it('removes a dub track via tracks.audio.strip and re-reads the list', async () => {
    const { api, calls } = makeBridge({ 'tracks.audio.strip': { path: 'C:/v.mkv' } });
    await mount(api);
    await act(async () => rowBtn('a2', 'strip-audio').click());
    await flush();
    expect(calls.filter((c) => c.method === 'tracks.audio.strip')).toEqual([
      { method: 'tracks.audio.strip', params: { videoId: 'v1', audioTrackId: 'a2' } },
    ]);
    // The list is re-read so the removed row disappears (mount + post-op refresh).
    expect(calls.filter((c) => c.method === 'tracks.audio.list')).toHaveLength(2);
    expect(container.querySelector('.audio-track-message')?.textContent).toContain('Removed');
  });

  it('surfaces a failed strip and does NOT re-read the list', async () => {
    const { api, calls } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        calls.push({ method, params });
        if (method === 'tracks.audio.strip') throw new Error('ffmpeg exit 1');
        if (method === 'tts.voices') return { voices: VOICES };
        if (method === 'tracks.list') return { tracks: [] };
        if (method === 'tracks.audio.list') return { audioTracks: AUDIO_TRACKS };
        return {};
      },
    );
    await mount(api);
    await act(async () => rowBtn('a2', 'strip-audio').click());
    await flush();
    expect(container.querySelector('.audio-track-message')?.textContent).toContain('ffmpeg exit 1');
    expect(calls.filter((c) => c.method === 'tracks.audio.list')).toHaveLength(1);
  });

  it('replaces a dub track audio via tracks.audio.replace and closes the editor', async () => {
    const { api, calls } = makeBridge({
      'tracks.audio.replace': { audioTrack: AUDIO_TRACKS[1] },
    });
    await mount(api);
    // The editor is closed until the disclosure is opened.
    expect(rowFor('a2').querySelector('[data-input="replace-audio-path"]')).toBeNull();
    await act(async () => rowBtn('a2', 'replace-audio').click());
    expect(rowFor('a2').querySelector('[data-input="replace-audio-path"]')).not.toBeNull();
    // Save is gated on a non-blank path.
    expect(rowBtn('a2', 'replace-audio-save').disabled).toBe(true);
    pick('[data-input="replace-audio-path"]', '  C:/better-dub.wav  ');
    expect(rowBtn('a2', 'replace-audio-save').disabled).toBe(false);
    await act(async () => rowBtn('a2', 'replace-audio-save').click());
    await flush();
    expect(calls.filter((c) => c.method === 'tracks.audio.replace')).toEqual([
      {
        method: 'tracks.audio.replace',
        params: { videoId: 'v1', audioTrackId: 'a2', path: 'C:/better-dub.wav' },
      },
    ]);
    // Success closes the editor and clears the field.
    expect(rowFor('a2').querySelector('[data-input="replace-audio-path"]')).toBeNull();
  });

  // W62 follow-up — the replace DRAFT must not follow the user from one dub row to another.
  //
  // `replacePath` is ONE component-level state shared by every row, the input is controlled by
  // it, and the only reset lived inside the SUCCESS branch. So typing a path for row A and then
  // opening row B pre-filled B with A's path and armed its Save — one click sent A's audio file
  // to B's audioTrackId. The sidecar assigns `track.path = audio_path` and keeps no record of
  // the previous value, so the pointer to B's correct audio is destroyed and the export plays
  // A's language under B's label.
  //
  // Invisible to every other test here because the shared fixture has exactly ONE dub (a2), so
  // there is no second row to bleed into. 100% branch coverage cannot see it either: the gap is
  // a missing STATE COMBINATION, not a missing branch.
  it('does not carry a typed replace path from one dub row to another', async () => {
    const twoDubs: AudioTrack[] = [
      AUDIO_TRACKS[0],
      AUDIO_TRACKS[1], // a2 — de
      {
        id: 'a3',
        lang: 'ro',
        name: 'Dub (kokoro, ro)',
        kind: 'dub',
        voice: 'af_sarah',
        path: 'C:/ro.m4a',
      },
    ];
    const { api, calls } = makeBridge({ 'tracks.audio.list': { audioTracks: twoDubs } });
    await mount(api);

    await act(async () => rowBtn('a2', 'replace-audio').click());
    pick('[data-input="replace-audio-path"]', 'C:/german-only.wav');
    expect(rowBtn('a2', 'replace-audio-save').disabled).toBe(false);

    // Switch to the OTHER dub. Its editor must open empty and disarmed.
    await act(async () => rowBtn('a3', 'replace-audio').click());
    const input = rowFor('a3').querySelector(
      '[data-input="replace-audio-path"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.value).toBe('');
    expect(rowBtn('a3', 'replace-audio-save').disabled).toBe(true);

    // And nothing was sent while switching.
    expect(calls.filter((c) => c.method === 'tracks.audio.replace')).toEqual([]);
  });

  it('keeps the replace editor open with the typed path when the replace fails', async () => {
    const { api, calls } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        calls.push({ method, params });
        if (method === 'tracks.audio.replace') throw new Error('audio file not found');
        if (method === 'tts.voices') return { voices: VOICES };
        if (method === 'tracks.list') return { tracks: [] };
        if (method === 'tracks.audio.list') return { audioTracks: AUDIO_TRACKS };
        return {};
      },
    );
    await mount(api);
    await act(async () => rowBtn('a2', 'replace-audio').click());
    pick('[data-input="replace-audio-path"]', 'C:/missing.wav');
    await act(async () => rowBtn('a2', 'replace-audio-save').click());
    await flush();
    expect(container.querySelector('.audio-track-message')?.textContent).toContain(
      'audio file not found',
    );
    const input = rowFor('a2').querySelector(
      '[data-input="replace-audio-path"]',
    ) as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(input.value).toBe('C:/missing.wav');
  });

  it('closes the replace editor when the disclosure is toggled off', async () => {
    const { api } = makeBridge();
    await mount(api);
    await act(async () => rowBtn('a2', 'replace-audio').click());
    expect(rowFor('a2').querySelector('[data-input="replace-audio-path"]')).not.toBeNull();
    await act(async () => rowBtn('a2', 'replace-audio').click());
    expect(rowFor('a2').querySelector('[data-input="replace-audio-path"]')).toBeNull();
  });

  it('imports an audio file as a dub track via tracks.audio.mux', async () => {
    const { api, calls } = makeBridge({
      'tracks.audio.mux': { audioTrack: AUDIO_TRACKS[1] },
    });
    await mount(api);
    const importBtn = () =>
      container.querySelector('[data-action="import-audio"]') as HTMLButtonElement;
    // Gated until ALL THREE required params are present (mux _require_str's each).
    expect(importBtn().disabled).toBe(true);
    pick('[data-input="import-audio-path"]', '  C:/my-vo.wav  ');
    expect(importBtn().disabled).toBe(true);
    pick('[data-input="import-audio-lang"]', ' ro ');
    expect(importBtn().disabled).toBe(true);
    pick('[data-input="import-audio-name"]', ' My voiceover ');
    expect(importBtn().disabled).toBe(false);

    await act(async () => importBtn().click());
    await flush();
    expect(calls.filter((c) => c.method === 'tracks.audio.mux')).toEqual([
      {
        method: 'tracks.audio.mux',
        params: {
          videoId: 'v1',
          path: 'C:/my-vo.wav',
          lang: 'ro',
          name: 'My voiceover',
          // NEVER 'original': that would suppress the AI-generated badge.
          kind: 'dub',
        },
      },
    ]);
    // A successful import clears the row and re-reads the list.
    expect(
      (container.querySelector('[data-input="import-audio-path"]') as HTMLInputElement).value,
    ).toBe('');
    expect(calls.filter((c) => c.method === 'tracks.audio.list')).toHaveLength(2);
  });

  it('keeps the import fields on failure and surfaces a non-Error rejection', async () => {
    const { api, calls } = makeBridge();
    (api.rpc as ReturnType<typeof vi.fn>).mockImplementation(
      async (method: string, params?: Record<string, unknown>) => {
        calls.push({ method, params });
        if (method === 'tracks.audio.mux') throw 'plain mux error';
        if (method === 'tts.voices') return { voices: VOICES };
        if (method === 'tracks.list') return { tracks: [] };
        if (method === 'tracks.audio.list') return { audioTracks: AUDIO_TRACKS };
        return {};
      },
    );
    await mount(api);
    pick('[data-input="import-audio-path"]', 'C:/my-vo.wav');
    pick('[data-input="import-audio-lang"]', 'ro');
    pick('[data-input="import-audio-name"]', 'My voiceover');
    await act(async () => {
      (container.querySelector('[data-action="import-audio"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('.audio-track-message')?.textContent).toContain(
      'plain mux error',
    );
    expect(
      (container.querySelector('[data-input="import-audio-path"]') as HTMLInputElement).value,
    ).toBe('C:/my-vo.wav');
  });

  it('locks every audio-track control while a dub job is running', async () => {
    const { api } = makeBridge();
    await mount(api);
    // Open the replace editor and fill it BEFORE the job starts, so the Save
    // button's only remaining reason to be disabled is the job itself.
    await act(async () => rowBtn('a2', 'replace-audio').click());
    pick('[data-input="replace-audio-path"]', 'C:/other.wav');
    expect(rowBtn('a2', 'replace-audio-save').disabled).toBe(false);

    pick('[data-picker="track"]', 't1');
    await act(async () => {
      (container.querySelector('[data-action="start-dub"]') as HTMLButtonElement).click();
    });
    await flush();
    expect(rowBtn('a2', 'strip-audio').disabled).toBe(true);
    expect(rowBtn('a2', 'replace-audio').disabled).toBe(true);
    // A concurrent replace would race the dub job's own track append, so Save is
    // locked too even though its path is valid.
    expect(rowBtn('a2', 'replace-audio-save').disabled).toBe(true);
    expect(
      (container.querySelector('[data-input="replace-audio-path"]') as HTMLInputElement).disabled,
    ).toBe(true);
    expect(
      (container.querySelector('[data-action="import-audio"]') as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
