// LipSync.test.tsx — tests for the lip-sync section of the Dub surface (W20).
//
// MEASURED GAP. `tts.lipsync.start` is registered UNCONDITIONALLY
// (`sidecar/media_studio/features/tts/__init__.py:141`) and frozen into the
// authoritative method list, but it had NO caller. Measured on the host tree:
// `features/Dub.tsx` was 519 lines with ZERO `lipSync`/`lipsync` references, and
// the only renderer matches for "lipsync" were `AiDisclosure.tsx` and
// `ThirdPartyNotices.tsx` — neither of which calls anything. So this is new UI in
// the dub surface, not a wiring tweak.
//
// WIRE: tts.lipsync.start({videoId, audioTrackId, engine?, quality?,
//                          likenessConsentAttested}) -> {jobId}
//         -> job.done {path, engine, syncConfidence}
//
// FOUR GATES, all FAIL CLOSED, and this file pins each one on the renderer side:
//  1. BUILD FLAG. `require_enabled` refuses unless the `lipSyncEnabled` setting is
//     the LITERAL `true` (`lipsync.py:197-215`; default `False`,
//     `settings_store.py:178`). A truthy string or 1 is NOT an opt-in, and
//     `lipSyncEnabledFrom` mirrors that exactly.
//  2. LIKENESS CONSENT. `likenessConsentAttested` must be the literal `true`
//     (`lipsync.py:218-225`). The UI never synthesizes it.
//  3. THE TRACK MUST BE A DUB. `lipsync_start` rejects a non-dub audio track
//     (`lipsync.py:672-677`) — re-lipping to the ORIGINAL audio is meaningless —
//     so the picker only offers `kind === 'dub'` rows.
//  4. ENGINE. `wav2lip` is in DENIED_ENGINES permanently (genuinely
//     non-commercial, `lipsync.py:120-126`), so it is not offerable at all.
//
// AND ONE DISCLOSED RESIDUAL THAT IS NOT MINE TO FIX (`handlers/composition.py`
// belongs to another live lane): `_tts.register(...)` at `composition.py:327-336`
// passes NO `lipsync_face_boxes_probe`, so `face_boxes_probe` is `None` in the real
// app and `require_face_boxes` (`lipsync.py:239-254`, called at `:699`) raises
// INSIDE the job. A run therefore refuses at job time today.
//
// How that is tested, after review narrowed the claim: the panel states the RULE up
// front (true of every build — "discloses the face-box rule in BOTH flag states"),
// asserts NOTHING about this build's wiring before a click, and after an OBSERVED
// refusal disables the control quoting the sidecar ("after an OBSERVED face-box
// refusal…"), while a DIFFERENT failure leaves it usable. So this file no longer
// pins a sentence that would become false the moment the sibling lane wires the
// probe — the previous version did, and a green test pinning it would have forced
// that lane to delete a passing test.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import LipSync, {
  buildLipsyncParams,
  dubAudioTracks,
  isFaceBoxRefusal,
  lipSyncEnabledFrom,
  lipsyncOutcome,
  DEFAULT_LIPSYNC_ENGINE,
  DEFAULT_LIPSYNC_QUALITY,
  LIPSYNC_ENGINES,
  LIPSYNC_FACE_BOX_MARKER,
  LIPSYNC_NO_IN_APP_SETTER,
  LIPSYNC_DISABLED_REASON,
} from './LipSync';
import type { AudioTrack } from './Dub';
import type { DoneEvent, MediaStudioApi, ProgressEvent } from './_api';

const ORIGINAL: AudioTrack = {
  id: 'a-orig',
  lang: 'en',
  name: 'Original',
  kind: 'original',
  path: '/m/orig.m4a',
};
const DUB_CLONE: AudioTrack = {
  id: 'a-dub-1',
  lang: 'de',
  name: 'Dub (chatterbox, de)',
  kind: 'dub',
  voice: 'sample-7',
  path: '/m/dub-de.m4a',
};
const DUB_PLAIN: AudioTrack = {
  id: 'a-dub-2',
  lang: 'fr',
  name: 'Dub (kokoro, fr)',
  kind: 'dub',
  path: '/m/dub-fr.m4a',
};

interface FakeApi {
  api: MediaStudioApi;
  calls: Array<{ method: string; params?: Record<string, unknown> }>;
  fireProgress: (ev: ProgressEvent) => void;
  fireDone: (ev: DoneEvent) => void;
}

function makeFakeApi(
  overrides: { settings?: unknown; settingsError?: Error; startError?: unknown } = {},
): FakeApi {
  const calls: FakeApi['calls'] = [];
  let progressCbs: Array<(ev: ProgressEvent) => void> = [];
  let doneCbs: Array<(ev: DoneEvent) => void> = [];
  const api: MediaStudioApi = {
    rpc: vi.fn(async <T,>(method: string, params?: Record<string, unknown>) => {
      calls.push({ method, params });
      if (method === 'settings.get') {
        if (overrides.settingsError) throw overrides.settingsError;
        return (overrides.settings ?? { lipSyncEnabled: true }) as T;
      }
      if (method === 'tts.lipsync.start') {
        if (overrides.startError) throw overrides.startError;
        return { jobId: 'job-l' } as T;
      }
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

describe('lipSyncEnabledFrom', () => {
  it('true ONLY for the literal boolean true', () => {
    expect(lipSyncEnabledFrom({ lipSyncEnabled: true })).toBe(true);
  });

  it('a truthy non-boolean is NOT an opt-in — it guards a face-manipulation path', () => {
    // Mirrors `lipsync.lipsync_enabled`: "a truthy string/int is NOT an opt-in".
    expect(lipSyncEnabledFrom({ lipSyncEnabled: 'true' })).toBe(false);
    expect(lipSyncEnabledFrom({ lipSyncEnabled: 1 })).toBe(false);
    expect(lipSyncEnabledFrom({ lipSyncEnabled: false })).toBe(false);
    expect(lipSyncEnabledFrom({})).toBe(false);
    expect(lipSyncEnabledFrom(null)).toBe(false);
    expect(lipSyncEnabledFrom('nope')).toBe(false);
  });
});

describe('isFaceBoxRefusal', () => {
  it('recognises the sidecar own unwired-probe refusal', () => {
    // The real message, `require_face_boxes` (`lipsync.py:249-254`). A sidecar test
    // asserts LIPSYNC_FACE_BOX_MARKER is still a substring of it, so this pair
    // cannot drift apart silently.
    expect(
      isFaceBoxRefusal(
        'no face-box provider is wired: lip-sync must be driven with boxes from ' +
          'the vendored MIT YuNet detector, because letting the engine detect faces ' +
          'itself pulls the unlicensed S3FD weight. Inject a face_boxes_probe',
      ),
    ).toBe(true);
  });

  it('is FALSE for every other failure — a transient error must not disable the control', () => {
    expect(isFaceBoxRefusal('ffmpeg exploded')).toBe(false);
    expect(isFaceBoxRefusal('')).toBe(false);
    // Near-misses matter: the detector keys off the sidecar's exact phrase, not the
    // word "face", so an unrelated detector error is not mistaken for the wiring gap.
    expect(isFaceBoxRefusal('the face detector found no faces in /m/clip.mp4')).toBe(false);
  });
});

// ─── the claim the DISABLED copy makes about `app/`, held by a test ──────────
// REFUTED IN REVIEW: the first wording said "set the lipSyncEnabled setting to
// true", naming a setting the user cannot reach — there is no settings UI for it.
// The copy now says so outright, and this scan is what keeps that honest: if a
// setter ever lands, this goes red and the sentence must be rewritten rather than
// quietly becoming a lie. Scanning the SOURCE is the only way to check it; the
// running renderer cannot see its own tree.
describe('LIPSYNC_DISABLED_REASON is honest about there being no in-app setter', () => {
  // `process.cwd()` is the vitest root (`app/`, see vitest.config.ts). NOT
  // `import.meta.url`: under the vite-node runner it is not a file: URL and
  // `fileURLToPath` throws "The URL must be of scheme file" — measured here.
  // The walk finding THIS file is the control that the root resolved correctly.
  const SRC_ROOT = join(process.cwd(), 'renderer', 'src');

  function walk(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === 'generated' ? [] : walk(full);
      if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];
      return [full];
    });
  }

  const sources = walk(SRC_ROOT).map((path) => ({ path, text: readFileSync(path, 'utf8') }));

  /** Files that pass `key` INTO a settings.set call (a write, not a mention). */
  const writersOf = (key: string): string[] =>
    sources
      .filter(({ text }) => new RegExp(`settings\\.set[\\s\\S]{0,120}?${key}`).test(text))
      .map(({ path }) => path);

  it('finds a REAL settings.set write for a user-settable key (detector control)', () => {
    // Without this control an empty result below would be indistinguishable from a
    // broken walk or a regex that matches nothing at all.
    expect(sources.length).toBeGreaterThan(50);
    expect(sources.some(({ path }) => path.endsWith(join('features', 'LipSync.tsx')))).toBe(true);
    expect(writersOf('useCloud').some((p) => p.endsWith('App.tsx'))).toBe(true);
    expect(writersOf('directorOnboardingSeen').length).toBeGreaterThan(0);
  });

  it('finds NO write of lipSyncEnabled anywhere in the renderer', () => {
    expect(writersOf('lipSyncEnabled')).toEqual([]);
    // Stronger, and the part that will actually fire: only these two files may
    // even MENTION the flag. A new toggle in Settings.tsx trips this immediately.
    const mentions = sources
      .filter(({ text }) => text.includes('lipSyncEnabled'))
      .map(({ path }) => path.replace(SRC_ROOT, '').replace(/\\/g, '/').replace(/^\//, ''));
    expect(mentions.sort()).toEqual(['features/LipSync.tsx', 'features/ThirdPartyNotices.tsx']);
  });

  it('states that in the copy the user actually reads, and names where the flag lives', () => {
    expect(LIPSYNC_DISABLED_REASON).toContain(LIPSYNC_NO_IN_APP_SETTER);
    expect(LIPSYNC_DISABLED_REASON).toContain('lipSyncEnabled');
    expect(LIPSYNC_DISABLED_REASON).toContain('settings.json');
  });
});

describe('dubAudioTracks', () => {
  it('offers only dub tracks — re-lipping to the original audio is meaningless', () => {
    expect(dubAudioTracks([ORIGINAL, DUB_CLONE, DUB_PLAIN])).toEqual([DUB_CLONE, DUB_PLAIN]);
  });

  it('empty when the video has no dub yet', () => {
    expect(dubAudioTracks([ORIGINAL])).toEqual([]);
    expect(dubAudioTracks([])).toEqual([]);
  });
});

describe('buildLipsyncParams', () => {
  it('carries the attestation when the user ticked it', () => {
    expect(
      buildLipsyncParams({
        videoId: 'v1',
        audioTrackId: 'a-dub-1',
        engine: 'musetalk',
        quality: 'fast',
        consentAttested: true,
      }),
    ).toEqual({
      videoId: 'v1',
      audioTrackId: 'a-dub-1',
      engine: 'musetalk',
      quality: 'fast',
      likenessConsentAttested: true,
    });
  });

  it('OMITS likenessConsentAttested when unticked — never mints consent', () => {
    const params = buildLipsyncParams({
      videoId: 'v1',
      audioTrackId: 'a-dub-1',
      engine: DEFAULT_LIPSYNC_ENGINE,
      quality: DEFAULT_LIPSYNC_QUALITY,
      consentAttested: false,
    });
    expect('likenessConsentAttested' in params).toBe(false);
  });
});

describe('LIPSYNC_ENGINES', () => {
  it('offers latentsync + musetalk and NEVER wav2lip (permanently denied)', () => {
    expect(LIPSYNC_ENGINES.map((e) => e.id)).toEqual(['latentsync', 'musetalk']);
    expect(LIPSYNC_ENGINES.map((e) => e.id)).not.toContain('wav2lip');
  });

  it('every offered engine states its weights licence', () => {
    // OpenRAIL permits commercial use but attaches behavioural use-restrictions
    // that must be passed downstream (`lipsync.py:23-30`), so the licence is a
    // user-facing fact, not an internal detail.
    for (const engine of LIPSYNC_ENGINES) {
      expect(engine.weightsLicense).toMatch(/openrail/i);
      expect(engine.notice.length).toBeGreaterThan(0);
    }
  });
});

describe('lipsyncOutcome', () => {
  it('reads a finished relip', () => {
    expect(
      lipsyncOutcome({ path: '/out/lipsync/clip.mp4', engine: 'latentsync', syncConfidence: 0.87 }),
    ).toEqual({ path: '/out/lipsync/clip.mp4', engine: 'latentsync', syncConfidence: 0.87 });
  });

  it('null without a usable path', () => {
    expect(lipsyncOutcome({})).toBeNull();
    expect(lipsyncOutcome(null)).toBeNull();
    expect(lipsyncOutcome({ path: '' })).toBeNull();
    expect(lipsyncOutcome({ path: 7 })).toBeNull();
  });

  it('null confidence and empty engine rather than invented values', () => {
    const out = lipsyncOutcome({ path: '/p.mp4' });
    expect(out?.syncConfidence).toBeNull();
    expect(out?.engine).toBe('');
    expect(lipsyncOutcome({ path: '/p.mp4', syncConfidence: 'high' })?.syncConfidence).toBeNull();
    expect(lipsyncOutcome({ path: '/p.mp4', engine: 42 })?.engine).toBe('');
  });
});

describe('<LipSync />', () => {
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
  });

  const flush = async (): Promise<void> => {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  };

  async function mount(
    api: MediaStudioApi,
    tracks: AudioTrack[] = [ORIGINAL, DUB_CLONE],
  ): Promise<void> {
    await act(async () => {
      root.render(<LipSync videoId="v1" audioTracks={tracks} api={api} />);
    });
    await flush();
  }

  function pick(selector: string, value: string): void {
    const el = container.querySelector(selector) as HTMLSelectElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(el, value);
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  function consent(): void {
    const box = container.querySelector('[data-input="lipsync-consent"]') as HTMLInputElement;
    act(() => {
      box.click();
    });
  }

  const startButton = (): HTMLButtonElement =>
    container.querySelector('[data-action="start-lipsync"]') as HTMLButtonElement;

  async function clickStart(): Promise<void> {
    await act(async () => {
      startButton().click();
      await Promise.resolve();
    });
    await flush();
  }

  /** The only state that can dispatch: a dub track picked and consent given. */
  function fillReady(trackId = DUB_CLONE.id): void {
    pick('[data-picker="lipsync-track"]', trackId);
    consent();
  }

  it('reads the build flag from settings.get on mount', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(fake.calls.some((c) => c.method === 'settings.get')).toBe(true);
  });

  // MUTATION NOTE — this test FILLS IN a complete, consented request before
  // asserting `disabled`, so the flag is the only remaining reason the button can
  // be disabled. Without that, the assertion would silently be measuring the
  // consent gate instead (the mistake that let a mutant survive in Gaze.test.tsx).
  it('DISABLES the control with the honest reason when lipSyncEnabled is off', async () => {
    const fake = makeFakeApi({ settings: { lipSyncEnabled: false } });
    await mount(fake.api);
    fillReady();
    expect(startButton().disabled).toBe(true);
    const reason = container.querySelector('[data-section="disabled"]');
    // Names the SETTING, so the disabled state is searchable rather than mysterious…
    expect(reason?.textContent).toContain('lipSyncEnabled');
    // …and says plainly that this app has no switch for it, instead of sending the
    // user hunting for a preference that does not exist (refuted in review).
    expect(reason?.textContent).toContain(LIPSYNC_NO_IN_APP_SETTER);
  });

  // MUTATION-DRIVEN (this one SURVIVED an adversarial mutation run): `enabled ===
  // true` -> `enabled !== false` left all 36 tests green, because nothing exercised
  // the NULL window — `settings.get` in flight. That window is the file's own
  // fail-closed claim ("null while settings.get is in flight — the control is
  // disabled until it answers"), so it needs a test, not a comment.
  it('fails CLOSED while settings.get is still in flight (the null window)', async () => {
    const api: MediaStudioApi = {
      // Never resolves: the panel stays in `enabled === null` for the whole test.
      rpc: vi.fn((method: string) =>
        method === 'settings.get' ? new Promise(() => {}) : Promise.resolve({ jobId: 'job-l' }),
      ) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(api);
    fillReady(); // everything else satisfied, so the flag is the only gate left
    expect(startButton().disabled).toBe(true);
    // ...and it is the IN-FLIGHT state, not the answered-false one: no disabled
    // reason is rendered yet, so this is distinguishable from `lipSyncEnabled:false`.
    expect(container.querySelector('[data-section="disabled"]')).toBeNull();
  });

  it('fails CLOSED when settings.get itself throws', async () => {
    const fake = makeFakeApi({ settingsError: new Error('settings unreadable') });
    await mount(fake.api);
    fillReady();
    expect(startButton().disabled).toBe(true);
    expect(container.querySelector('[data-section="disabled"]')).not.toBeNull();
  });

  it('enables the control once the flag, a dub track AND consent are all present', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    expect(startButton().disabled).toBe(true); // no track, no consent yet
    pick('[data-picker="lipsync-track"]', DUB_CLONE.id);
    expect(startButton().disabled).toBe(true); // still no consent
    consent();
    expect(startButton().disabled).toBe(false);
  });

  it('offers ONLY dub tracks in the picker and says so when there are none', async () => {
    const fake = makeFakeApi();
    await mount(fake.api, [ORIGINAL]);
    const options = Array.from(
      container.querySelectorAll('[data-picker="lipsync-track"] option'),
    ).map((o) => (o as HTMLOptionElement).value);
    expect(options).not.toContain(ORIGINAL.id);
    expect(container.querySelector('[data-section="no-dub"]')).not.toBeNull();
  });

  it('never offers wav2lip in the engine picker', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const options = Array.from(
      container.querySelectorAll('[data-picker="lipsync-engine"] option'),
    ).map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(['latentsync', 'musetalk']);
  });

  it('shows the selected engine licence obligation, and it changes with the engine', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const licence = (): string => container.querySelector('[data-section="licence"]')!.textContent!;
    expect(licence()).toContain('openrail++');
    pick('[data-picker="lipsync-engine"]', 'musetalk');
    expect(licence()).toContain('creativeml-openrail-m');
  });

  // The pre-click disclosure. This is the difference between "disabled with a
  // reason" and "silently broken": the user is told before clicking that a build
  // without a face-box provider refuses, and why that refusal is correct.
  //
  // It states the RULE, not a verdict about THIS build — see the next test. The
  // first version asserted the verdict as present-tense fact, which an adversarial
  // review correctly refuted: the renderer cannot observe `composition.py`, and the
  // sentence would invert into "a working feature is broken" the moment the sibling
  // lane wires the probe.
  it('discloses the face-box rule in BOTH flag states, before any click', async () => {
    const on = makeFakeApi();
    await mount(on.api);
    expect(container.querySelector('[data-section="unwired"]')?.textContent).toContain('S3FD');
    // ...and claims NOTHING about this build until something is measured.
    expect(container.querySelector('[data-section="face-box-refused"]')).toBeNull();
    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
    const off = makeFakeApi({ settings: { lipSyncEnabled: false } });
    await mount(off.api);
    expect(container.querySelector('[data-section="unwired"]')?.textContent).toContain('S3FD');
    expect(container.querySelector('[data-section="face-box-refused"]')).toBeNull();
  });

  it('after an OBSERVED face-box refusal it disables the control and quotes the sidecar', async () => {
    // This is the shape the brief asked for — disabled WITH A REASON — reached the
    // only honest way: from a refusal the sidecar actually returned. `probe is None`
    // cannot fix itself mid-session, so a second identical click is a guaranteed
    // failure and must not be offered.
    const refusal = new Error(
      `${LIPSYNC_FACE_BOX_MARKER}: lip-sync must be driven with boxes from the ` +
        'vendored MIT YuNet detector. Inject a face_boxes_probe',
    );
    const fake = makeFakeApi({ startError: refusal });
    await mount(fake.api);
    fillReady();
    expect(startButton().disabled).toBe(false); // enabled BEFORE the click
    await clickStart();
    const observed = container.querySelector('[data-section="face-box-refused"]');
    expect(observed?.textContent).toContain(LIPSYNC_FACE_BOX_MARKER);
    expect(observed?.textContent).toContain('Measured on this build');
    // and the control is now shut, with the failure also surfaced as an alert
    expect(startButton().disabled).toBe(true);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      LIPSYNC_FACE_BOX_MARKER,
    );
  });

  it('a DIFFERENT failure leaves the control usable — one bad run is not a verdict', async () => {
    // The both-states half of the test above: without this, "disabled after a
    // refusal" could just be "disabled after any error", which would strand the
    // user on a transient ffmpeg failure.
    const fake = makeFakeApi({ startError: new Error('ffmpeg exploded') });
    await mount(fake.api);
    fillReady();
    await clickStart();
    expect(container.querySelector('[data-section="face-box-refused"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('ffmpeg exploded');
    expect(startButton().disabled).toBe(false);
  });

  it('discloses that the output is synthetic video and carries no embedded provenance', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    const note = container.querySelector('[data-section="ai-disclosure"]');
    expect(note?.textContent).toMatch(/synthetic|synthesi/i);
    // Reuses the SHARED C2PA status constant rather than restating it, so there is
    // one source for "no provenance manifest is written".
    expect(note?.textContent).toContain('C2PA');
    expect(note?.textContent).toContain('not available');
  });

  it('reports C2PA as available if a signing identity ever lands (the other state)', async () => {
    // The shipped constant is a hardcoded `available: false`, so without this seam
    // the "available" wording could never be exercised — the same reason
    // `AiDisclosurePanel` takes an injectable `c2pa`.
    const fake = makeFakeApi();
    await act(async () => {
      root.render(
        <LipSync
          videoId="v1"
          audioTracks={[DUB_CLONE]}
          api={fake.api}
          c2pa={{ available: true, reason: '' }}
        />,
      );
    });
    await flush();
    expect(container.querySelector('[data-section="ai-disclosure"]')?.textContent).toContain(
      'Available',
    );
  });

  it('sends tts.lipsync.start with the exact frozen params', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    pick('[data-picker="lipsync-quality"]', 'fast');
    await clickStart();
    expect(fake.calls.find((c) => c.method === 'tts.lipsync.start')?.params).toEqual({
      videoId: 'v1',
      audioTrackId: DUB_CLONE.id,
      engine: DEFAULT_LIPSYNC_ENGINE,
      quality: 'fast',
      likenessConsentAttested: true,
    });
  });

  it('streams progress for its own job and ignores another', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireProgress({ jobId: 'job-l', pct: 30, message: 're-lipping' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).toContain('30');
    await act(async () => {
      fake.fireProgress({ jobId: 'other', pct: 99, message: 'nope' });
      await Promise.resolve();
    });
    expect(container.querySelector('.progress-pct')?.textContent).not.toContain('99');
  });

  it('renders the relipped path and the sync confidence on job.done', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-l',
        result: { path: '/out/lipsync/v1/clip.mp4', engine: 'latentsync', syncConfidence: 0.87 },
      });
      await Promise.resolve();
    });
    await flush();
    const out = container.querySelector('[data-section="lipsync-result"]');
    expect(out?.textContent).toContain('/out/lipsync/v1/clip.mp4');
    expect(out?.textContent).toContain('0.87');
  });

  it('renders a result whose confidence the sidecar could not measure without inventing one', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-l', result: { path: '/out/x.mp4', engine: 'musetalk' } });
      await Promise.resolve();
    });
    await flush();
    const out = container.querySelector('[data-section="lipsync-result"]');
    expect(out?.textContent).toContain('/out/x.mp4');
    expect(out?.textContent).toMatch(/not measured/i);
  });

  it('surfaces the job-time face-box refusal LOUDLY as an alert', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireDone({
        jobId: 'job-l',
        result: {
          error: {
            message:
              'no face-box provider is wired: lip-sync must be driven with boxes from the vendored MIT YuNet detector',
            type: 'LipSyncError',
          },
        },
      });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'no face-box provider is wired',
    );
    expect(container.querySelector('[data-section="lipsync-result"]')).toBeNull();
  });

  it('surfaces an rpc-time refusal as an alert', async () => {
    const fake = makeFakeApi({ startError: new Error('likenessConsentAttested must be true') });
    await mount(fake.api);
    fillReady();
    await clickStart();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'likenessConsentAttested',
    );
  });

  it('surfaces a non-Error rejection as a string', async () => {
    const fake = makeFakeApi({ startError: 'plain string boom' });
    await mount(fake.api);
    fillReady();
    await clickStart();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('plain string boom');
  });

  it('CLEARS the consent tick after a successful relip', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-l', result: { path: '/out/x.mp4', engine: 'latentsync' } });
      await Promise.resolve();
    });
    await flush();
    expect(
      (container.querySelector('[data-input="lipsync-consent"]') as HTMLInputElement).checked,
    ).toBe(false);
  });

  it('KEEPS the consent tick after a failure so a retry need not re-attest', async () => {
    const fake = makeFakeApi({ startError: new Error('boom') });
    await mount(fake.api);
    fillReady();
    await clickStart();
    expect(
      (container.querySelector('[data-input="lipsync-consent"]') as HTMLInputElement).checked,
    ).toBe(true);
  });

  it('cancels the in-flight job via job.cancel (the happy path)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      (container.querySelector('[data-action="lipsync-cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(fake.calls.find((c) => c.method === 'job.cancel')?.params).toEqual({ jobId: 'job-l' });
    expect(container.querySelector('.progress-message')?.textContent).toContain('Cancelling');
  });

  it('cancels the in-flight job via job.cancel, and a failing cancel is not a panel error', async () => {
    let doneCbs: Array<(ev: DoneEvent) => void> = [];
    const calls: FakeApi['calls'] = [];
    const api: MediaStudioApi = {
      rpc: vi.fn(async <T,>(method: string) => {
        calls.push({ method });
        if (method === 'settings.get') return { lipSyncEnabled: true } as T;
        if (method === 'job.cancel') throw new Error('cancel failed');
        return { jobId: 'job-l' } as T;
      }) as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: (cb) => {
        doneCbs.push(cb);
        return () => {
          doneCbs = doneCbs.filter((c) => c !== cb);
        };
      },
    };
    await mount(api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      (container.querySelector('[data-action="lipsync-cancel"]') as HTMLButtonElement).click();
      await Promise.resolve();
    });
    expect(calls.some((c) => c.method === 'job.cancel')).toBe(true);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('does not hang without a job.done channel, and renders nothing without a jobId', async () => {
    const noDone: MediaStudioApi = {
      rpc: vi.fn(async (method: string) =>
        method === 'settings.get' ? { lipSyncEnabled: true } : { jobId: 'job-l' },
      ) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
    };
    await mount(noDone);
    fillReady();
    await clickStart();
    expect(container.querySelector('[data-section="lipsync-result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();

    await act(async () => {
      root.unmount();
    });
    root = createRoot(container);
    const noJob: MediaStudioApi = {
      rpc: vi.fn(async (method: string) =>
        method === 'settings.get' ? { lipSyncEnabled: true } : {},
      ) as unknown as MediaStudioApi['rpc'],
      onProgress: () => () => {},
      onJobDone: () => () => {},
    };
    await mount(noJob);
    fillReady();
    await clickStart();
    expect(container.querySelector('[data-section="lipsync-result"]')).toBeNull();
  });

  it('settles cleanly on a job.done with no result field', async () => {
    const fake = makeFakeApi();
    await mount(fake.api);
    fillReady();
    await act(async () => {
      startButton().click();
    });
    await act(async () => {
      fake.fireDone({ jobId: 'job-l' });
      await Promise.resolve();
    });
    await flush();
    expect(container.querySelector('[data-section="lipsync-result"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });

  it('falls back to the global window.api bridge when no api prop is given', async () => {
    const fake = makeFakeApi();
    (globalThis as { api?: unknown }).api = fake.api;
    try {
      await act(async () => {
        root.render(<LipSync videoId="v1" audioTracks={[DUB_CLONE]} />);
      });
      await flush();
      fillReady();
      await clickStart();
      expect(fake.calls.find((c) => c.method === 'tts.lipsync.start')?.params).toMatchObject({
        videoId: 'v1',
        likenessConsentAttested: true,
      });
    } finally {
      delete (globalThis as { api?: unknown }).api;
    }
  });

  it('drops a selected track that disappears from the list (a re-picked dub cannot go stale)', async () => {
    const fake = makeFakeApi();
    await mount(fake.api, [ORIGINAL, DUB_CLONE, DUB_PLAIN]);
    pick('[data-picker="lipsync-track"]', DUB_PLAIN.id);
    consent();
    expect(startButton().disabled).toBe(false);
    // The dub track is removed (e.g. tracks.audio.strip) and Dub re-renders us.
    await act(async () => {
      root.render(<LipSync videoId="v1" audioTracks={[ORIGINAL, DUB_CLONE]} api={fake.api} />);
    });
    await flush();
    expect(startButton().disabled).toBe(true);
  });
});
