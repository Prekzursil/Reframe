// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// jsdom does not implement HTMLMediaElement playback; the real <Player> the
// Workspace mounts touches load()/play()/pause() (and reads error). Back them so
// the proxy-swap reload (video.load() via reloadToken) does not warn/throw.
const loadMock = vi.fn();
beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'load', {
    configurable: true,
    value: loadMock,
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

// U1 proxy-build path: the Workspace subscribes to job.done through lib/rpc's
// onJobDone. Mock it so the deferred-remount branch can be driven deterministically
// (the real wrapper reads window.api, which is not present under jsdom).
const onJobDoneMock = vi.fn<(cb: (e: { jobId: string; result?: unknown }) => void) => () => void>();
vi.mock('../lib/rpc', () => ({
  onJobDone: (cb: (e: { jobId: string; result?: unknown }) => void) => onJobDoneMock(cb),
}));

// The 11 feature panels are lazily code-split. Mock each to a deterministic
// marker so tab-switching renders something assertable WITHOUT pulling each
// real panel's own rpc wiring into this shell test (they have their own suites).
function stubPanel(label: string) {
  return {
    default: (props: Record<string, unknown>) => {
      const React_ = require('react');
      return React_.createElement(
        'div',
        { 'data-panel': label, 'data-videoid': String(props.videoId ?? '') },
        label,
      );
    },
  };
}
vi.mock('../features/Transcribe', () => stubPanel('Transcribe'));
vi.mock('../features/Subtitles', () => stubPanel('Subtitles'));
vi.mock('../features/Tracks', () => stubPanel('Tracks'));
vi.mock('../features/Convert', () => stubPanel('Convert'));
vi.mock('../features/ShortMaker', () => stubPanel('ShortMaker'));
vi.mock('../features/Timeline', () => stubPanel('Timeline'));
vi.mock('../features/Dub', () => stubPanel('Dub'));
vi.mock('../features/Assets', () => stubPanel('Assets'));
vi.mock('../features/NleExport', () => stubPanel('NleExport'));
vi.mock('../features/Diarize', () => stubPanel('Diarize'));
vi.mock('../features/Recipes', () => stubPanel('Recipes'));
vi.mock('../features/SemanticSearch', () => stubPanel('SemanticSearch'));

import { Workspace, WORKSPACE_TABS } from './Workspace';
import type { Video, Project } from '../components/api';

// CONTRACT-NOTE: the feature panels (../features/*) are authored by a sibling unit
// and do not exist on disk when this shell is tested in isolation. The Workspace
// loads them lazily and falls back to a "panel is not available" placeholder when
// the dynamic import fails — that fallback is what these tests assert. Once the
// feature modules land, the real panels render in their place (covered by their
// own unit tests). This keeps the shell's tests independent of sibling units.

const video: Video = {
  id: 'v1',
  path: '/movies/talk.mp4',
  title: 'Talk',
  addedAt: '2026-06-11T00:00:00Z',
  durationSec: 605,
  hasTranscript: false,
};

const project: Project = {
  id: 'v1',
  video,
  tracks: [],
  clips: [],
  settings: {},
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  rpcMock.mockReset();
  rpcMock.mockResolvedValue({ project });
  onJobDoneMock.mockReset();
  onJobDoneMock.mockReturnValue(() => undefined);
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    for (let i = 0; i < 8; i++) {
      // eslint-disable-next-line no-await-in-loop
      await Promise.resolve();
    }
  });
}

describe('Workspace', () => {
  it('exposes the contract tabs in order (P2: +Timeline/Dub/Assets; captions-export: +Timeline export; system-advanced: +Diarize/Recipes)', () => {
    expect(WORKSPACE_TABS.map((t) => t.label)).toEqual([
      'Transcribe',
      'Search',
      'Subtitles',
      'Diarize',
      'Tracks',
      'Convert',
      'Short-maker',
      'Timeline',
      'Dub',
      'Timeline export',
      'Recipes',
      'Assets',
    ]);
  });

  it('opens the project via project.open and shows the title + tabs', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    expect(rpcMock).toHaveBeenCalledWith('project.open', { id: 'v1' });
    expect(container.textContent).toContain('Talk');
    expect(container.querySelectorAll('[role="tab"]').length).toBe(WORKSPACE_TABS.length);
  });

  it('mounts a feature panel slot (placeholder until the panel module exists)', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    // The default (Transcribe) tab renders either the real panel or the fallback.
    expect(container.querySelector('.workspace__body')).not.toBeNull();
    expect(container.textContent).toContain('Transcribe');
  });

  it('switches the active tab when clicked', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    const tabs = container.querySelectorAll('[role="tab"]');
    // index 1 = Subtitles
    await act(async () => {
      (tabs[1] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('aria-selected')).toBe('false');
  });

  it('calls onBack when the back button is pressed', async () => {
    const onBack = vi.fn();
    await act(async () => {
      root.render(<Workspace video={video} onBack={onBack} />);
    });
    await flush();

    const back = container.querySelector('button.workspace__back') as HTMLButtonElement;
    await act(async () => {
      back.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('surfaces a project.open error', async () => {
    rpcMock.mockReset();
    rpcMock.mockRejectedValue(new Error('open failed'));
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(container.textContent).toContain('open failed');
  });

  it('stringifies a non-Error project.open rejection', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.reject('boom-string');
      return Promise.resolve({ playable: true });
    });
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(container.querySelector('.workspace__error')?.textContent).toContain('boom-string');
  });

  it('tolerates a null/absent project payload (no throw, no error banner)', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.resolve(null);
      return Promise.resolve({ playable: true });
    });
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(container.querySelector('.workspace__error')).toBeNull();
    // tabs still render (the shell does not depend on project to show tabs)
    expect(container.querySelectorAll('[role="tab"]').length).toBe(WORKSPACE_TABS.length);
  });

  // Each tab id -> the marker its mocked panel renders. Exercises every case of
  // renderPanel() (the switch) including the 'transcribe'/default fall-through.
  const tabPanels: Array<[string, string]> = [
    ['transcribe', 'Transcribe'],
    ['search', 'SemanticSearch'],
    ['subtitles', 'Subtitles'],
    ['diarize', 'Diarize'],
    ['tracks', 'Tracks'],
    ['convert', 'Convert'],
    ['shortmaker', 'ShortMaker'],
    ['timeline', 'Timeline'],
    ['dub', 'Dub'],
    ['nle', 'NleExport'],
    ['recipes', 'Recipes'],
    ['assets', 'Assets'],
  ];

  it.each(tabPanels)('renders the %s panel for its tab', async (tabId, marker) => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    const idx = WORKSPACE_TABS.findIndex((t) => t.id === tabId);
    const tabs = container.querySelectorAll('[role="tab"]');
    await act(async () => {
      (tabs[idx] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    const panel = container.querySelector(`[data-panel="${marker}"]`);
    expect(panel).not.toBeNull();
    // panels that receive videoId get the opened video's id
    if (marker !== 'Assets') {
      expect(panel?.getAttribute('data-videoid')).toBe('v1');
    }
  });

  it('builds a playback proxy when the source is not directly playable, then remounts the Player on job.done', async () => {
    let doneCb: ((e: { jobId: string; result?: unknown }) => void) | null = null;
    onJobDoneMock.mockImplementation((cb) => {
      doneCb = cb;
      return () => undefined;
    });
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      switch (method) {
        case 'project.open':
          return Promise.resolve({ project });
        case 'media.playable':
          return Promise.resolve({ playable: false, reason: 'needs proxy' });
        case 'media.proxy.start':
          return Promise.resolve({ jobId: 'job-proxy-1' });
        default:
          return Promise.resolve({});
      }
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    // the reason note is shown while the proxy builds
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'needs proxy',
    );
    expect(rpcMock).toHaveBeenCalledWith('media.proxy.start', { videoId: 'v1' });
    expect(onJobDoneMock).toHaveBeenCalledTimes(1);

    // G1 shake fix: capture the live <video> so we can prove it PERSISTS across
    // the proxy swap (no key-remount). The element identity must be stable.
    const videoBefore = container.querySelector('.workspace__player video');
    expect(videoBefore).not.toBeNull();
    loadMock.mockClear();

    // an unrelated job.done is ignored (no note clear)
    await act(async () => {
      doneCb?.({ jobId: 'some-other-job' });
    });
    await flush();
    expect(container.querySelector('.workspace__player-note')).not.toBeNull();

    // our proxy job's done clears the note and bumps the reloadToken: the SAME
    // <video> stays mounted and is re-fetched via load() (shake-free), NOT
    // remounted via a key change.
    await act(async () => {
      doneCb?.({ jobId: 'job-proxy-1' });
    });
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    const videoAfter = container.querySelector('.workspace__player video');
    expect(videoAfter).toBe(videoBefore); // element persisted (no shake)
    expect(loadMock).toHaveBeenCalledTimes(1); // proxy re-fetched in place
  });

  it('surfaces a <video> load error (onError) and clears it on the proxy-ready reload', async () => {
    let doneCb: ((e: { jobId: string; result?: unknown }) => void) | null = null;
    onJobDoneMock.mockImplementation((cb) => {
      doneCb = cb;
      return () => undefined;
    });
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      switch (method) {
        case 'project.open':
          return Promise.resolve({ project });
        case 'media.playable':
          return Promise.resolve({ playable: false, reason: 'needs proxy' });
        case 'media.proxy.start':
          return Promise.resolve({ jobId: 'job-proxy-2' });
        default:
          return Promise.resolve({});
      }
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    // the <video> fails to load (mstream 404 / undecodable) -> error surfaces.
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'media failed to load',
    );

    // once the proxy is ready, the job.done reload clears the stale error.
    await act(async () => {
      doneCb?.({ jobId: 'job-proxy-2' });
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')).toBeNull();
  });

  it('falls back to a default note when media.playable gives no reason', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      switch (method) {
        case 'project.open':
          return Promise.resolve({ project });
        case 'media.playable':
          return Promise.resolve({ playable: false });
        case 'media.proxy.start':
          // no jobId -> the onJobDone subscription is skipped (early return branch)
          return Promise.resolve({});
        default:
          return Promise.resolve({});
      }
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'building playback proxy',
    );
    expect(onJobDoneMock).not.toHaveBeenCalled();
  });

  it('skips the proxy build entirely when the source is already playable', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.resolve({ project });
      if (method === 'media.playable') return Promise.resolve({ playable: true });
      return Promise.resolve({});
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(rpcMock).not.toHaveBeenCalledWith('media.proxy.start', expect.anything());
  });

  it('swallows a media.playable probe failure (best-effort proxy build)', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.resolve({ project });
      if (method === 'media.playable') return Promise.reject(new Error('probe failed'));
      return Promise.resolve({});
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    // no crash, no note, no error banner — the probe failure is caught
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(container.querySelector('.workspace__error')).toBeNull();
  });

  it('unsubscribes from job.done on unmount after a proxy build starts', async () => {
    const off = vi.fn();
    onJobDoneMock.mockReturnValue(off);
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      switch (method) {
        case 'project.open':
          return Promise.resolve({ project });
        case 'media.playable':
          return Promise.resolve({ playable: false, reason: 'x' });
        case 'media.proxy.start':
          return Promise.resolve({ jobId: 'job-9' });
        default:
          return Promise.resolve({});
      }
    });

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(onJobDoneMock).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    expect(off).toHaveBeenCalledTimes(1);
    // re-render so afterEach's unmount is a no-op safe path
    root = createRoot(container);
  });
});
