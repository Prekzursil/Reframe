// Workspace.seam.test.tsx — the Workspace ↔ Subtitles COMPOSITION seam (F19).
//
// This is a SEPARATE file from Workspace.test.tsx on purpose: that suite's
// file-wide `vi.mock('../features/Subtitles')` (Workspace.test.tsx:62) is hoisted
// and replaces the panel with a marker div, so it can never observe how the real
// panel treats a LATE `initialTrack`. Here the REAL panel renders.
//
// The defect this pins: `Workspace.renderPanel()` passes
// `initialTrack={tracks[0] ?? null}` derived from `project.tracks`, but
// `project.open` is fired from a POST-COMMIT effect (Workspace.tsx:173-176) while
// the lazy panel chunk is already in flight. When the chunk wins that race the
// panel mounts with `initialTrack === null`, and `useState(initialTrack)`
// (Subtitles.tsx:52) captures the null once — so the track that arrives moments
// later is ignored for the panel's whole lifetime.
//
// Scaffolding required for the REAL Workspace under jsdom (without these the test
// throws before reaching its assertion, i.e. it would be red in BOTH states and
// measure nothing):
//   * `../lib/rpc` must be mocked — Workspace.tsx:207-212 subscribes via
//     onProxyState, whose bridge() (lib/rpc/client.ts:96-102) THROWS when
//     window.api is absent;
//   * HTMLMediaElement load/play/pause must be backed — Workspace.tsx:317 mounts
//     the real <Player>, and jsdom does not implement media playback.

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'load', {
    configurable: true,
    value: vi.fn(),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: vi.fn(() => Promise.resolve()),
  });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value: vi.fn(),
  });
});

const rpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

type ProxyStateEvt = {
  videoId: string;
  state: 'building' | 'direct' | 'ready' | 'error';
  detail: string;
};
const onProxyStateMock = vi.fn<(cb: (e: ProxyStateEvt) => void) => () => void>();
vi.mock('../lib/rpc', () => ({
  onProxyState: (cb: (e: ProxyStateEvt) => void) => onProxyStateMock(cb),
}));

// NOTE: ../features/Subtitles is deliberately NOT mocked here.
//
// ../features/TranscriptEditor IS mocked: this suite pins the Subtitles seam, it
// never selects the Transcript-edit tab, and leaving that panel real only adds
// its module graph to the race this test is already timing. Measured: with the
// panel real the case intermittently trips the 5s default (2/5 full-suite runs)
// while passing in isolation at ~2.2s of test time, i.e. a transform-cost cliff
// under parallel load, not a behaviour change. UNVERIFIED whether CI's Linux
// runner ever crosses that cliff — settled by dropping this mock and reading the
// gate-tests-coverage vitest step; the stub is correct either way.
vi.mock('../features/TranscriptEditor', () => ({ default: () => <div /> }));

import { Workspace } from './Workspace';
import type { Project, SubtitleTrack, Video } from '../components/api';

const video: Video = {
  id: 'v1',
  path: '/movies/talk.mp4',
  title: 'Talk',
  addedAt: '2026-06-11T00:00:00Z',
  durationSec: 605,
  hasTranscript: true,
};

const project: Project = { id: 'v1', video, tracks: [], clips: [], settings: {} };

// Mirrors the WIRE, not the declaration: tracks inside a persisted project pass
// through tracks._normalise (sidecar/media_studio/features/tracks.py:157-180),
// which guarantees all six frozen fields with `cues` a real list; a cue is
// {index, start, end, text} (features/subtitles.py:110).
const wireTrack: SubtitleTrack = {
  id: 'tr1',
  lang: 'en',
  name: 'English',
  format: 'srt',
  kind: 'soft',
  cues: [
    { index: 1, start: 0, end: 2, text: 'first' },
    { index: 2, start: 5, end: 7, text: 'second' },
  ],
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  onProxyStateMock.mockReset();
  onProxyStateMock.mockReturnValue(() => undefined);
  // The real panel reads the frozen bridge through getApi() (features/_api.ts:99)
  // inside effects/callbacks only; install a fake so any later interaction has one.
  (globalThis as { api?: unknown }).api = {
    rpc: vi.fn(async () => ({})),
    onProgress: () => () => {},
    onJobDone: () => () => {},
  };
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (globalThis as { api?: unknown }).api;
});

// Real macrotask turns (not just microtasks): the lazy chunk is a genuine dynamic
// import, so a microtask-only drain can leave the Suspense fallback mounted.
async function flush(turns = 10): Promise<void> {
  for (let i = 0; i < turns; i++) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
    });
  }
}

describe('Workspace ↔ Subtitles seam', () => {
  it('adopts project.tracks[0] when project.open resolves AFTER the panel mounts', async () => {
    // Warm the chunk so the losing-race ordering (panel mounts first) is pinned
    // deterministically instead of left to transform timing.
    await import('../features/Subtitles');

    let resolveOpen: (value: { project: Project }) => void = () => undefined;
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') {
        return new Promise<{ project: Project }>((resolve) => {
          resolveOpen = resolve;
        });
      }
      return Promise.resolve({});
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    // Preconditions — these are what make the assertion below a genuine red for
    // the DEFECT rather than a setup error: the REAL panel is mounted (not the
    // Suspense fallback) and it currently has no track.
    expect(container.querySelector('.subtitles-panel')).not.toBeNull();
    expect(container.querySelector('.track-meta')).toBeNull();

    await act(async () => {
      resolveOpen({ project: { ...project, tracks: [wireTrack] } });
    });
    await flush();

    expect(container.querySelector('.track-meta')).not.toBeNull();
    expect(container.querySelector('.track-meta')?.textContent).toContain('English');
    expect([...container.querySelectorAll('.cue-text')]).toHaveLength(2);
  });
});

// ─── W19 / W20: the seam tests the lane's reachability claim actually needs ──
// REFUTED IN REVIEW, twice and correctly: the lane offered
// `Workspace.test.tsx`'s "renders the gaze panel for its tab" as "the actual
// reachability test", but that file does `vi.mock('../features/Gaze', () =>
// stubPanel('Gaze'))` — it mounts a STUB. It proves the TabBar + `renderPanel()`
// switch and the props handed down; it cannot prove that
// `lazy(() => import('../features/Gaze'))` resolves or that the real panel mounts.
// That was resting on `tsc --noEmit`. These two cases close it in the file whose
// whole purpose is real lazy panel mounts, so the claim is now executable rather
// than narrowed away.
describe('Workspace ↔ Gaze seam (W19)', () => {
  it('mounts the REAL Gaze panel on the eye-contact tab', async () => {
    await import('../features/Gaze'); // warm the lazy chunk (same idiom as above)
    rpcMock.mockResolvedValue({ project });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="gaze" />);
    });
    await flush();

    // The real panel, not the Suspense fallback and not a marker div: its own
    // section class plus the ethics gate that only the real component renders.
    expect(container.querySelector('.gaze-panel')).not.toBeNull();
    expect(container.querySelector('[data-testid="gaze-consent"]')).not.toBeNull();
    expect(container.querySelector('[data-input="likeness-attest"]')).not.toBeNull();
    // Fail-closed on this scaffold: the fake bridge answers `gaze.probe` with `{}`,
    // so the panel treats the model as unavailable and the Run button stays shut.
    // That IS the shipped behaviour for a machine without the YuNet asset.
    expect((container.querySelector('[data-action="run"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});

describe('Workspace ↔ Dub/LipSync seam (W20)', () => {
  it('mounts the REAL lip-sync section inside the Dub tab, disabled by default', async () => {
    await import('../features/Dub'); // Dub hosts the LipSync section
    rpcMock.mockResolvedValue({ project });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="dub" />);
    });
    await flush();

    // The reachability half that IS true for W20: the control exists on a surface a
    // user can open. It is DISABLED here — the fake bridge answers `settings.get`
    // with `{}`, so `lipSyncEnabled` is not the literal true, exactly as every stock
    // build behaves. See the LipSync header: this is a call site, not a runnable
    // feature, and this test pins that distinction rather than papering over it.
    expect(container.querySelector('.lipsync-section')).not.toBeNull();
    const start = container.querySelector('[data-action="start-lipsync"]') as HTMLButtonElement;
    expect(start).not.toBeNull();
    expect(start.disabled).toBe(true);
    expect(container.querySelector('[data-section="disabled"]')?.textContent).toContain(
      'lipSyncEnabled',
    );
  });
});

// W16-UI. Same reason the Gaze block above exists, and the reachability claim here
// is the whole point of the lane: `Workspace.test.tsx` mocks
// `../features/BrollPanel` to a marker div, so it proves the TabBar + the
// `renderPanel()` switch and nothing about whether
// `lazy(() => import('../features/BrollPanel'))` resolves. Only a REAL mount can
// show that a user clicking "Auto B-roll" actually reaches the seven `broll.*`
// RPCs — the claim this lane is making — so it is asserted here, executably,
// rather than narrowed away or rested on `tsc --noEmit`.
describe('Workspace ↔ BrollPanel seam (W16-UI)', () => {
  it('mounts the REAL b-roll panel on its tab, with its honesty surfaces present', async () => {
    await import('../features/BrollPanel'); // warm the lazy chunk (same idiom as above)
    rpcMock.mockResolvedValue({ project });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="broll" />);
    });
    await flush();

    // The real panel, not the Suspense fallback and not a marker div: its own
    // section class plus the two disclosures only the real component renders.
    expect(container.querySelector('.broll-panel')).not.toBeNull();
    expect(container.querySelector('[data-section="threshold-disclosure"]')?.textContent).toContain(
      'UNCALIBRATED',
    );
    expect(container.querySelector('[data-section="limits"]')).not.toBeNull();
    // The threshold really is a control the user can move, not a fixed constant.
    expect(container.querySelector('[data-input="threshold"]')).not.toBeNull();
    // Fail-closed on this scaffold: the fake bridge answers `broll.assets` with
    // `{}`, so the library reads EMPTY and the register control stays shut until a
    // path is typed. That IS the shipped first-run behaviour.
    expect(container.querySelector('[data-section="grid"]')).toBeNull();
    expect((container.querySelector('[data-action="add"]') as HTMLButtonElement).disabled).toBe(
      true,
    );
    // …and the same `{}` must NOT paint a freshness snapshot. A reviewer caught
    // this scaffold doing exactly that: `readBrollStatus` only rejected NON-objects,
    // so `{}` returned a full row of zeros and THIS test — the one offered as proof
    // of reachability — rendered "In library 0" as though it were a measurement.
    // Fixed in the panel; pinned here so the scaffold can never fabricate again.
    expect(container.querySelector('[data-section="status"]')).toBeNull();
    // The prerequisites are the first thing a user on a fresh video needs, so they
    // must survive the real lazy mount, not just the unit harness.
    //
    // THIS ASSERTION WAS CHANGED, and the reason matters: it used to pin the phrase
    // 'transcribe THIS video first'. That wording was itself the defect. The sidecar
    // enforces `require_model` (broll_ops.py:403) BEFORE the transcript raise (:408),
    // so transcribing is the THIRD prerequisite, not the first — and the omitted one
    // is a 4.5 GB SigLIP-2 download that no copy mentioned. Pinning "first" therefore
    // locked in a false ordering. The replacement is STRICTER, not looser: it keeps
    // the transcript pin and adds the matcher pin, so the seam now proves both halves
    // survive the real lazy mount.
    const prereq = container.querySelector('[data-section="prerequisites"]')?.textContent;
    expect(prereq).toContain('transcribe THIS video');
    expect(prereq).toContain('Assets tab');
  });
});

describe('Workspace ↔ Speed seam', () => {
  it('mounts the REAL Speed panel on the speed tab, threaded with the video duration', async () => {
    // The point of this test: before v1.5 the re-time engine had no control in
    // ANY panel. Asserting the real panel (not the Suspense fallback) is what
    // proves the door is genuinely reachable from the Workspace.
    await import('../features/Speed'); // warm the lazy chunk (same idiom as above)
    rpcMock.mockResolvedValue({ project });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="speed" />);
    });
    await flush();

    const panel = container.querySelector('.speed-panel');
    expect(panel).not.toBeNull();
    // `video.durationSec` is threaded through, so the before/after prediction is
    // real rather than a dash: 2x on this source halves it.
    expect(container.querySelector('[data-field="sourceDuration"]')?.textContent).not.toBe('—');
    expect(container.querySelector('[data-field="newDuration"]')?.textContent).not.toBe('—');
  });
});
