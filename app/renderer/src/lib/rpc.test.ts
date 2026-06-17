// rpc.test.ts — the typed `client` wrappers map to the FROZEN method names +
// param shapes (P4 §2 / C8). The bridge is mocked via a fake `window.api`, so
// these assert the exact wire calls (method string + params) the renderer makes
// for the P4 shorts gallery + captions.cues live-preview cues.

import { describe, it, expect, vi, afterEach } from 'vitest';

import {
  client,
  hasApi,
  rpc,
  onProgress,
  onJobDone,
  type Candidate,
  type ConvertOptions,
  type Project,
  type SavedRecipe,
  type ShortInfo,
  type ShortReexportHint,
  type Video,
} from './rpc';

// ---------------------------------------------------------------------------
// Install a fake preload bridge so `rpc()` resolves through a spy. The module
// reads `globalThis.window?.api` structurally (no Window augmentation), so we
// set it directly per test.
// ---------------------------------------------------------------------------
function installApi(): ReturnType<typeof vi.fn> {
  const rpc = vi.fn().mockResolvedValue({});
  (globalThis as { window?: { api?: unknown } }).window = {
    api: { rpc, onProgress: vi.fn(() => () => {}) },
  };
  return rpc;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe('client.shorts (P4 §2 / C6 / C8)', () => {
  it('list forwards {videoId} only when given', async () => {
    const rpc = installApi();
    await client.shorts.list('v1');
    expect(rpc).toHaveBeenCalledWith('shorts.list', { videoId: 'v1' });
  });

  it('list sends an empty params object when no videoId (lists all)', async () => {
    const rpc = installApi();
    await client.shorts.list();
    expect(rpc).toHaveBeenCalledWith('shorts.list', {});
  });

  it('thumbnail forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.thumbnail('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.thumbnail', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('delete forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.delete('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.delete', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('reexport forwards {path}', async () => {
    const rpc = installApi();
    await client.shorts.reexport('/out/shorts-v1/clip.mp4');
    expect(rpc).toHaveBeenCalledWith('shorts.reexport', { path: '/out/shorts-v1/clip.mp4' });
  });

  it('list resolves the {shorts} envelope it is typed for', async () => {
    const rpc = installApi();
    const info: ShortInfo = {
      id: 'abc',
      path: '/out/shorts-v1/clip.mp4',
      videoId: 'v1',
      sourceTitle: 'Talk',
      template: 'bold',
      viralityPct: 82,
      durationSec: 34,
      width: 1080,
      height: 1920,
      createdAt: 1700000000,
      thumbnailPath: '',
      hook: 'The big idea',
    };
    rpc.mockResolvedValueOnce({ shorts: [info] });
    const res = await client.shorts.list('v1');
    expect(res.shorts[0].viralityPct).toBe(82);
  });

  it('reexport resolves the reopen-in-short-maker hint shape', async () => {
    const rpc = installApi();
    const hint: ShortReexportHint = {
      videoId: 'v1',
      candidate: { hook: 'h', template: 'bold', viralityPct: null, durationSec: 30 },
    };
    rpc.mockResolvedValueOnce(hint);
    const res = await client.shorts.reexport('/out/shorts-v1/clip.mp4');
    expect(res.videoId).toBe('v1');
    expect(res.candidate.template).toBe('bold');
  });
});

describe('client.captions (P4 §2 / C7 / C8)', () => {
  it('cues forwards {videoId} and resolves the {cues} envelope (reuses Cue type)', async () => {
    const rpc = installApi();
    rpc.mockResolvedValueOnce({ cues: [{ index: 1, start: 1.0, end: 1.4, text: 'Hi' }] });
    const res = await client.captions.cues('v1');
    expect(rpc).toHaveBeenCalledWith('captions.cues', { videoId: 'v1' });
    expect(res.cues[0].text).toBe('Hi');
  });
});

// ---------------------------------------------------------------------------
// The bare bridge accessors (`rpc`, `hasApi`, `onProgress`, `onJobDone`) — the
// foundation surface every client wrapper sits on. Covers the bridge() guard
// (throws when no preload) plus the onJobDone unsupported-bridge no-op branch.
// ---------------------------------------------------------------------------
describe('bridge accessors', () => {
  it('hasApi is false when the preload bridge is absent', () => {
    expect(hasApi()).toBe(false);
  });

  it('hasApi is true once the bridge is installed', () => {
    installApi();
    expect(hasApi()).toBe(true);
  });

  it('rpc forwards method + params through the bridge and resolves the result', async () => {
    const spy = installApi();
    spy.mockResolvedValueOnce({ pong: true });
    const res = await rpc<{ pong: boolean }>('ping', { x: 1 });
    expect(spy).toHaveBeenCalledWith('ping', { x: 1 });
    expect(res.pong).toBe(true);
  });

  it('rpc throws a clear error when the preload bridge is not loaded', () => {
    // No installApi() — globalThis.window is unset.
    expect(() => rpc('ping')).toThrow(/window\.api bridge is not available/);
  });

  it('onProgress subscribes through the bridge and returns its unsubscribe fn', () => {
    const off = vi.fn();
    const onProgressSpy = vi.fn(() => off);
    (globalThis as { window?: { api?: unknown } }).window = {
      api: { rpc: vi.fn(), onProgress: onProgressSpy },
    };
    const cb = vi.fn();
    const unsub = onProgress(cb);
    expect(onProgressSpy).toHaveBeenCalledWith(cb);
    unsub();
    expect(off).toHaveBeenCalledTimes(1);
  });

  it('onJobDone subscribes through the bridge when the preload supports it', () => {
    const off = vi.fn();
    const onJobDoneSpy = vi.fn(() => off);
    (globalThis as { window?: { api?: unknown } }).window = {
      api: { rpc: vi.fn(), onProgress: vi.fn(() => () => {}), onJobDone: onJobDoneSpy },
    };
    const cb = vi.fn();
    const unsub = onJobDone(cb);
    expect(onJobDoneSpy).toHaveBeenCalledWith(cb);
    unsub();
    expect(off).toHaveBeenCalledTimes(1);
  });

  it('onJobDone returns a no-op unsubscribe when the bridge lacks onJobDone', () => {
    installApi(); // bridge has rpc + onProgress, but NO onJobDone
    const cb = vi.fn();
    const unsub = onJobDone(cb);
    // The no-op unsubscribe must be callable and return undefined.
    expect(unsub()).toBeUndefined();
    expect(cb).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// The full method-typed `client` surface. Each wrapper must forward the EXACT
// frozen method name + param shape. These assert the wire contract for every
// group so the whole client object is exercised (functions coverage).
// ---------------------------------------------------------------------------
const CONVERT_OPTS: ConvertOptions = {
  container: 'mp4',
  vcodec: 'h264',
  acodec: 'aac',
  scale: '1280:-2',
  fps: '30',
  crf: '23',
  audioOnly: false,
  audioFormat: 'mp3',
};

function makeCandidate(): Candidate {
  return {
    rank: 1,
    start: 0,
    end: 30,
    durationSec: 30,
    hook: 'h',
    why: 'w',
    score: 90,
    sourceStart: 0,
  };
}

describe('client.ping / library / project', () => {
  it('ping calls the bare method', async () => {
    const r = installApi();
    await client.ping();
    // Bare methods forward only the method name (params left undefined).
    expect(r).toHaveBeenCalledWith('ping', undefined);
  });

  it('library.list / add / remove forward their params', async () => {
    const r = installApi();
    await client.library.list();
    expect(r).toHaveBeenCalledWith('library.list', undefined);
    await client.library.add('/a.mp4');
    expect(r).toHaveBeenCalledWith('library.add', { path: '/a.mp4' });
    await client.library.remove('v1');
    expect(r).toHaveBeenCalledWith('library.remove', { id: 'v1' });
  });

  it('project.open / save / consolidate forward their params', async () => {
    const r = installApi();
    const video: Video = {
      id: 'v1',
      path: '/a.mp4',
      title: 'A',
      addedAt: '2026-01-01',
      durationSec: 10,
      hasTranscript: false,
    };
    const project: Project = { id: 'p1', video, tracks: [], clips: [], settings: {} };
    await client.project.open('v1');
    expect(r).toHaveBeenCalledWith('project.open', { id: 'v1' });
    await client.project.save(project);
    expect(r).toHaveBeenCalledWith('project.save', { project });
    await client.project.consolidate('v1');
    expect(r).toHaveBeenCalledWith('project.consolidate', { id: 'v1' });
  });
});

describe('client.transcribe / diarize (optional-param branches)', () => {
  it('transcribe.start omits language when not given', async () => {
    const r = installApi();
    await client.transcribe.start('v1');
    expect(r).toHaveBeenCalledWith('transcribe.start', { videoId: 'v1' });
  });

  it('transcribe.start includes language when given', async () => {
    const r = installApi();
    await client.transcribe.start('v1', 'en');
    expect(r).toHaveBeenCalledWith('transcribe.start', { videoId: 'v1', language: 'en' });
  });

  it('diarize.start omits threshold when undefined', async () => {
    const r = installApi();
    await client.diarize.start('v1');
    expect(r).toHaveBeenCalledWith('diarize.start', { videoId: 'v1' });
  });

  it('diarize.start includes threshold when given (incl. 0)', async () => {
    const r = installApi();
    await client.diarize.start('v1', 0.5);
    expect(r).toHaveBeenCalledWith('diarize.start', { videoId: 'v1', threshold: 0.5 });
    await client.diarize.start('v1', 0);
    expect(r).toHaveBeenCalledWith('diarize.start', { videoId: 'v1', threshold: 0 });
  });
});

describe('client.subtitles (spread-opts branches)', () => {
  it('generate / edit / export forward their params', async () => {
    const r = installApi();
    await client.subtitles.generate('v1');
    expect(r).toHaveBeenCalledWith('subtitles.generate', { videoId: 'v1' });
    await client.subtitles.edit('t1', [{ index: 1, start: 0, end: 1, text: 'hi' }]);
    expect(r).toHaveBeenCalledWith('subtitles.edit', {
      trackId: 't1',
      cues: [{ index: 1, start: 0, end: 1, text: 'hi' }],
    });
    await client.subtitles.export('t1', 'srt');
    expect(r).toHaveBeenCalledWith('subtitles.export', { trackId: 't1', format: 'srt' });
  });

  it('translate spreads opts when given and defaults to {} when omitted', async () => {
    const r = installApi();
    await client.subtitles.translate('t1', 'es');
    expect(r).toHaveBeenCalledWith('subtitles.translate', { trackId: 't1', targetLang: 'es' });
    await client.subtitles.translate('t1', 'es', { bilingual: true, order: 'translation-first' });
    expect(r).toHaveBeenCalledWith('subtitles.translate', {
      trackId: 't1',
      targetLang: 'es',
      bilingual: true,
      order: 'translation-first',
    });
  });
});

describe('client.tracks / tracksAudio', () => {
  it('tracks.* forward their params', async () => {
    const r = installApi();
    await client.tracks.list('v1');
    expect(r).toHaveBeenCalledWith('tracks.list', { videoId: 'v1' });
    await client.tracks.rename('t1', 'Name');
    expect(r).toHaveBeenCalledWith('tracks.rename', { trackId: 't1', name: 'Name' });
    await client.tracks.relabel('t1', 'en');
    expect(r).toHaveBeenCalledWith('tracks.relabel', { trackId: 't1', lang: 'en' });
    await client.tracks.add('v1', 't1');
    expect(r).toHaveBeenCalledWith('tracks.add', { videoId: 'v1', trackId: 't1' });
    await client.tracks.remove('v1', 't1');
    expect(r).toHaveBeenCalledWith('tracks.remove', { videoId: 'v1', trackId: 't1' });
    await client.tracks.burn('v1', 't1');
    expect(r).toHaveBeenCalledWith('tracks.burn', { videoId: 'v1', trackId: 't1' });
    await client.tracks.strip('v1', 't1');
    expect(r).toHaveBeenCalledWith('tracks.strip', { videoId: 'v1', trackId: 't1' });
  });

  it('tracksAudio.* forward their params', async () => {
    const r = installApi();
    await client.tracksAudio.list('v1');
    expect(r).toHaveBeenCalledWith('tracks.audio.list', { videoId: 'v1' });
    await client.tracksAudio.mux({
      videoId: 'v1',
      path: '/a.m4a',
      lang: 'en',
      name: 'Dub',
      kind: 'dub',
    });
    expect(r).toHaveBeenCalledWith('tracks.audio.mux', {
      videoId: 'v1',
      path: '/a.m4a',
      lang: 'en',
      name: 'Dub',
      kind: 'dub',
    });
    await client.tracksAudio.replace({ videoId: 'v1', audioTrackId: 'a1', path: '/a.m4a' });
    expect(r).toHaveBeenCalledWith('tracks.audio.replace', {
      videoId: 'v1',
      audioTrackId: 'a1',
      path: '/a.m4a',
    });
    await client.tracksAudio.strip({ videoId: 'v1', audioTrackId: 'a1' });
    expect(r).toHaveBeenCalledWith('tracks.audio.strip', { videoId: 'v1', audioTrackId: 'a1' });
  });
});

describe('client.convert / shortmaker (spread-opts branches)', () => {
  it('convert.start / batch forward target + options', async () => {
    const r = installApi();
    await client.convert.start({ videoId: 'v1' }, CONVERT_OPTS);
    expect(r).toHaveBeenCalledWith('convert.start', { videoId: 'v1', options: CONVERT_OPTS });
    await client.convert.batch([{ path: '/a.mp4', options: CONVERT_OPTS }]);
    expect(r).toHaveBeenCalledWith('convert.batch', {
      items: [{ path: '/a.mp4', options: CONVERT_OPTS }],
    });
  });

  it('shortmaker.select forwards controls; export spreads opts (and {} default)', async () => {
    const r = installApi();
    await client.shortmaker.select('v1', 'find the best moments', { topK: 3 });
    expect(r).toHaveBeenCalledWith('shortmaker.select', {
      videoId: 'v1',
      prompt: 'find the best moments',
      controls: { topK: 3 },
    });
    await client.shortmaker.export('v1', ['c1', 'c2']);
    expect(r).toHaveBeenCalledWith('shortmaker.export', {
      videoId: 'v1',
      candidateIds: ['c1', 'c2'],
    });
    await client.shortmaker.export('v1', ['c1'], { captionStyle: 'neon', hookTitle: true });
    expect(r).toHaveBeenCalledWith('shortmaker.export', {
      videoId: 'v1',
      candidateIds: ['c1'],
      captionStyle: 'neon',
      hookTitle: true,
    });
  });
});

describe('client.nle / package (spread + conditional branches)', () => {
  it('nle.export spreads opts when given and defaults to {} when omitted', async () => {
    const r = installApi();
    await client.nle.export('v1');
    expect(r).toHaveBeenCalledWith('nle.export', { videoId: 'v1' });
    await client.nle.export('v1', { format: 'edl', fps: 30, title: 'T' });
    expect(r).toHaveBeenCalledWith('nle.export', {
      videoId: 'v1',
      format: 'edl',
      fps: 30,
      title: 'T',
    });
  });

  it('package.export omits suggestion when not given, includes it when given', async () => {
    const r = installApi();
    await client.package.export('/out/clip.mp4');
    expect(r).toHaveBeenCalledWith('package.export', { path: '/out/clip.mp4' });
    await client.package.export('/out/clip.mp4', { title: 'Hi', tags: ['a', 'b'] });
    expect(r).toHaveBeenCalledWith('package.export', {
      path: '/out/clip.mp4',
      suggestion: { title: 'Hi', tags: ['a', 'b'] },
    });
  });
});

describe('client.feedback / media / timeline / tts', () => {
  it('feedback.record / stats forward their params', async () => {
    const r = installApi();
    const candidate = makeCandidate();
    await client.feedback.record({ videoId: 'v1', candidate, action: 'approved' });
    expect(r).toHaveBeenCalledWith('feedback.record', {
      videoId: 'v1',
      candidate,
      action: 'approved',
    });
    await client.feedback.stats();
    expect(r).toHaveBeenCalledWith('feedback.stats', undefined);
  });

  it('media.playable / proxyStart forward their params', async () => {
    const r = installApi();
    await client.media.playable('v1');
    expect(r).toHaveBeenCalledWith('media.playable', { videoId: 'v1' });
    await client.media.proxyStart('v1');
    expect(r).toHaveBeenCalledWith('media.proxy.start', { videoId: 'v1' });
  });

  it('timeline.peaks forwards {videoId}', async () => {
    const r = installApi();
    await client.timeline.peaks('v1');
    expect(r).toHaveBeenCalledWith('timeline.peaks', { videoId: 'v1' });
  });

  it('tts.voices / sampleAdd / dubStart forward their params', async () => {
    const r = installApi();
    await client.tts.voices();
    expect(r).toHaveBeenCalledWith('tts.voices', undefined);
    await client.tts.sampleAdd('/sample.wav');
    expect(r).toHaveBeenCalledWith('tts.sample.add', { path: '/sample.wav' });
    await client.tts.dubStart({ videoId: 'v1', trackId: 't1', engine: 'xtts', voice: 'a' });
    expect(r).toHaveBeenCalledWith('tts.dub.start', {
      videoId: 'v1',
      trackId: 't1',
      engine: 'xtts',
      voice: 'a',
    });
  });
});

describe('client.assets / job / settings', () => {
  it('assets.* forward their params', async () => {
    const r = installApi();
    await client.assets.list();
    expect(r).toHaveBeenCalledWith('assets.list', undefined);
    await client.assets.ensure(['whisper', 'ffmpeg']);
    expect(r).toHaveBeenCalledWith('assets.ensure', { names: ['whisper', 'ffmpeg'] });
    await client.assets.cancel('j1');
    expect(r).toHaveBeenCalledWith('assets.cancel', { jobId: 'j1' });
  });

  it('job.* forward their params', async () => {
    const r = installApi();
    await client.job.cancel('j1');
    expect(r).toHaveBeenCalledWith('job.cancel', { jobId: 'j1' });
    await client.job.status('j1');
    expect(r).toHaveBeenCalledWith('job.status', { jobId: 'j1' });
    await client.job.list();
    expect(r).toHaveBeenCalledWith('job.list', undefined);
    await client.job.retry('j1');
    expect(r).toHaveBeenCalledWith('job.retry', { jobId: 'j1' });
  });

  it('settings.get / set forward their params', async () => {
    const r = installApi();
    await client.settings.get();
    expect(r).toHaveBeenCalledWith('settings.get', undefined);
    await client.settings.set({ useCloud: true });
    expect(r).toHaveBeenCalledWith('settings.set', { useCloud: true });
  });
});

describe('client.system / recipes', () => {
  it('system.health calls the bare method', async () => {
    const r = installApi();
    await client.system.health();
    expect(r).toHaveBeenCalledWith('system.health', undefined);
  });

  it('system.probe calls the bare method', async () => {
    const r = installApi();
    await client.system.probe();
    expect(r).toHaveBeenCalledWith('system.probe', undefined);
  });

  it('system.advisor sends an empty params object when commercial is omitted', async () => {
    const r = installApi();
    await client.system.advisor();
    expect(r).toHaveBeenCalledWith('system.advisor', {});
    await client.system.advisor({});
    expect(r).toHaveBeenCalledWith('system.advisor', {});
  });

  it('system.advisor forwards {commercial} when provided (both boolean values)', async () => {
    const r = installApi();
    await client.system.advisor({ commercial: true });
    expect(r).toHaveBeenCalledWith('system.advisor', { commercial: true });
    await client.system.advisor({ commercial: false });
    expect(r).toHaveBeenCalledWith('system.advisor', { commercial: false });
  });

  it('asr.engines calls the bare method', async () => {
    const r = installApi();
    await client.asr.engines();
    expect(r).toHaveBeenCalledWith('asr.engines', undefined);
  });

  it('providers.usage calls the bare method (WU-usage-ui)', async () => {
    const r = installApi();
    await client.providers.usage();
    expect(r).toHaveBeenCalledWith('providers.usage', undefined);
  });

  it('providers.* presets forward their params (WU-presets)', async () => {
    const r = installApi();
    await client.providers.catalog();
    expect(r).toHaveBeenCalledWith('providers.catalog', undefined);
    await client.providers.applyPreset('privacy');
    expect(r).toHaveBeenCalledWith('providers.applyPreset', { name: 'privacy' });
    await client.providers.setFunctionModel('select', 'groq-x');
    expect(r).toHaveBeenCalledWith('providers.setFunctionModel', {
      function: 'select',
      provider: 'groq-x',
    });
    // firstRun: bare READ vs choice-applied (the conditional-param branch).
    await client.providers.firstRun();
    expect(r).toHaveBeenCalledWith('providers.firstRun', {});
    await client.providers.firstRun('bestFreeCloud');
    expect(r).toHaveBeenCalledWith('providers.firstRun', { choice: 'bestFreeCloud' });
  });

  it('recipes.* forward their params', async () => {
    const r = installApi();
    const recipe: SavedRecipe = {
      id: 'r1',
      name: 'My recipe',
      steps: [{ method: 'transcribe.start', params: { videoId: 'v1' }, label: 'Transcribe' }],
    };
    await client.recipes.list();
    expect(r).toHaveBeenCalledWith('recipes.list', undefined);
    await client.recipes.save(recipe);
    expect(r).toHaveBeenCalledWith('recipes.save', { recipe });
    await client.recipes.delete('r1');
    expect(r).toHaveBeenCalledWith('recipes.delete', { id: 'r1' });
    await client.recipes.run('r1');
    expect(r).toHaveBeenCalledWith('recipes.run', { id: 'r1' });
  });
});
