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
