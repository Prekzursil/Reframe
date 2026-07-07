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

// WU B3 proxy-build path: the Workspace subscribes to the main process's
// `proxy.state` pushes through lib/rpc's onProxyState. Mock it so the
// building/ready/error transitions can be driven deterministically (the real
// wrapper reads window.api, which is not present under jsdom).
type ProxyStateEvt = {
  videoId: string;
  state: 'building' | 'direct' | 'ready' | 'error';
  detail: string;
};
const onProxyStateMock = vi.fn<(cb: (e: ProxyStateEvt) => void) => () => void>();
vi.mock('../lib/rpc', () => ({
  onProxyState: (cb: (e: ProxyStateEvt) => void) => onProxyStateMock(cb),
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
vi.mock('../features/Refine', () => stubPanel('Refine'));
vi.mock('../features/Recipes', () => stubPanel('Recipes'));
vi.mock('../features/SemanticSearch', () => stubPanel('SemanticSearch'));

import { Workspace, WORKSPACE_TABS, WORKSPACE_TAB_GROUPS, DEFAULT_WORKSPACE_TAB } from './Workspace';
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
  onProxyStateMock.mockReset();
  onProxyStateMock.mockReturnValue(() => undefined);
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
      'Refine',
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
    // WU-3a2: the default tab is now Subtitles, but the Transcribe tab LABEL is
    // still present in the (grouped) strip — a body slot renders regardless.
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

  it('honours an initial tab deep-link (Task Hub) instead of the first tab', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} initialTab="subtitles" />);
    });
    await flush();

    const idx = WORKSPACE_TABS.findIndex((t) => t.id === 'subtitles');
    const tabs = container.querySelectorAll('[role="tab"]');
    expect(tabs[idx].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('aria-selected')).toBe('false');
    expect(container.querySelector('[data-panel="Subtitles"]')).not.toBeNull();
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
    ['refine', 'Refine'],
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

    // WU-3a2: tabs render in NAMED clusters, so DOM order no longer mirrors the
    // WORKSPACE_TABS array — locate the tab by its stable id, not a positional
    // index. Every tab stays a real role="tab" (Advanced/Deliver ones live in the
    // collapsed panel but remain in the DOM and reachable).
    const tab = container.querySelector(`[role="tab"][data-tab-id="${tabId}"]`);
    expect(tab).not.toBeNull();
    await act(async () => {
      (tab as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    const panel = container.querySelector(`[data-panel="${marker}"]`);
    expect(panel).not.toBeNull();
    // panels that receive videoId get the opened video's id
    if (marker !== 'Assets') {
      expect(panel?.getAttribute('data-videoid')).toBe('v1');
    }
  });

  // WU B3: the mstream resolver builds the proxy; the Workspace only REACTS to
  // the main process's `proxy.state` pushes. Drive the callback directly.
  async function renderAndCaptureProxyState(): Promise<(e: ProxyStateEvt) => void> {
    let cb: ((e: ProxyStateEvt) => void) | null = null;
    onProxyStateMock.mockImplementation((fn) => {
      cb = fn;
      return () => undefined;
    });
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(cb).not.toBeNull();
    return cb as unknown as (e: ProxyStateEvt) => void;
  }

  it('shows the building note while the proxy builds, then reloads the player on ready (shake-free)', async () => {
    const emit = await renderAndCaptureProxyState();

    // 'building' shows the reason note.
    await act(async () => emit({ videoId: 'v1', state: 'building', detail: 'needs proxy' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'needs proxy',
    );

    // capture the live <video> to prove it PERSISTS across the proxy swap.
    const videoBefore = container.querySelector('.workspace__player video');
    expect(videoBefore).not.toBeNull();
    loadMock.mockClear();

    // a proxy-state event for a DIFFERENT videoId is ignored (note stays).
    await act(async () => emit({ videoId: 'other', state: 'ready', detail: '' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')).not.toBeNull();

    // 'ready' clears the note and bumps the reloadToken: the SAME <video> stays
    // mounted and is re-fetched via load() (shake-free), NOT key-remounted.
    await act(async () => emit({ videoId: 'v1', state: 'ready', detail: '/proxies/v1.mp4' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    const videoAfter = container.querySelector('.workspace__player video');
    expect(videoAfter).toBe(videoBefore); // element persisted (no shake)
    expect(loadMock).toHaveBeenCalledTimes(1); // proxy re-fetched in place
  });

  it('shows a calm placeholder (NOT the loud error) for a raw <video> error BEFORE the resolver speaks', async () => {
    const emit = await renderAndCaptureProxyState();

    // Initial window: no proxy.state event yet. Chromium fires an `error` on the
    // still-undecodable raw source ("media error (code 4)"). This must surface as
    // a calm "Building preview…" placeholder note, NOT the loud red banner.
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')).toBeNull();
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'Building preview',
    );

    // once the proxy is ready, the reload clears the placeholder note.
    await act(async () => emit({ videoId: 'v1', state: 'ready', detail: '/proxies/v1.mp4' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
  });

  it('keeps the existing building note when the raw <video> errors DURING a proxy build', async () => {
    const emit = await renderAndCaptureProxyState();

    // The resolver is mid-build: its detail note is showing. A raw-source error
    // in this window must not replace that specific note nor go loud.
    await act(async () => emit({ videoId: 'v1', state: 'building', detail: 'needs proxy' }));
    await flush();
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')).toBeNull();
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain('needs proxy');
  });

  it('surfaces a raw <video> error LOUDLY once the proxy is ready (genuine decode failure, no silent fallback)', async () => {
    const emit = await renderAndCaptureProxyState();

    // After 'ready' the source is supposed to be decodable; if the <video> still
    // errors it is a genuine failure and must be surfaced loudly.
    await act(async () => emit({ videoId: 'v1', state: 'ready', detail: '/proxies/v1.mp4' }));
    await flush();
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'media failed to load',
    );
  });

  it('shows no note for a direct (already-playable) verdict, and does not reload the player', async () => {
    const emit = await renderAndCaptureProxyState();
    const videoBefore = container.querySelector('.workspace__player video');
    loadMock.mockClear();

    // WU-1e-fix: the resolver decided the source is directly playable (or a valid
    // cached proxy) WITHOUT a build. No building note, and NO reload (the source
    // is already correct — reloading would restart playback needlessly).
    await act(async () => emit({ videoId: 'v1', state: 'direct', detail: '/library/v1.mp4' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(container.querySelector('.workspace__player-error')).toBeNull();
    expect(container.querySelector('.workspace__player video')).toBe(videoBefore);
    expect(loadMock).not.toHaveBeenCalled();
  });

  it('surfaces a raw <video> error LOUDLY after a DIRECT verdict (resolver misjudged: corrupt moov / odd profile — never a silent "Building preview…" forever)', async () => {
    const emit = await renderAndCaptureProxyState();

    // The resolver said the source is directly playable, so it emits 'direct'
    // (advancing past 'initial'). If the <video> then genuinely fails to decode,
    // the resolver misjudged — this MUST go loud, not mask behind the calm
    // placeholder that (pre-fix) never resolved because no proxy.state ever fired.
    await act(async () => emit({ videoId: 'v1', state: 'direct', detail: '/library/v1.mp4' }));
    await flush();
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'media failed to load',
    );
  });

  it('does not overwrite a specific proxy build-failure reason with a raw <video> echo error', async () => {
    const emit = await renderAndCaptureProxyState();

    // A build failure surfaced its precise reason. A subsequent raw-source error
    // is a downstream echo of the same failure — the specific reason must stand.
    await act(async () => emit({ videoId: 'v1', state: 'error', detail: 'ffmpeg exited with code 1' }));
    await flush();
    const videoEl = container.querySelector('.workspace__player video') as HTMLVideoElement;
    await act(async () => {
      videoEl.dispatchEvent(new Event('error'));
    });
    await flush();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'ffmpeg exited with code 1',
    );
  });

  it('falls back to a default note when the building push carries no detail', async () => {
    const emit = await renderAndCaptureProxyState();
    await act(async () => emit({ videoId: 'v1', state: 'building', detail: '' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'building playback proxy',
    );
  });

  it('surfaces a proxy BUILD FAILURE loudly (no silent center-crop)', async () => {
    const emit = await renderAndCaptureProxyState();

    // 'error' with a reason surfaces it in the player-error banner + clears the note.
    await act(async () => emit({ videoId: 'v1', state: 'building', detail: 'needs proxy' }));
    await act(async () => emit({ videoId: 'v1', state: 'error', detail: 'ffmpeg exited with code 1' }));
    await flush();
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'ffmpeg exited with code 1',
    );
  });

  it('falls back to a default failure message when the error push carries no detail', async () => {
    const emit = await renderAndCaptureProxyState();
    await act(async () => emit({ videoId: 'v1', state: 'error', detail: '' }));
    await flush();
    expect(container.querySelector('.workspace__player-error')?.textContent).toContain(
      'playback proxy build failed',
    );
  });

  it('shows no player note when the source is already playable (no build events)', async () => {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();

    // the Workspace never kicks the build itself (the resolver does).
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(rpcMock).not.toHaveBeenCalledWith('media.playable', expect.anything());
    expect(rpcMock).not.toHaveBeenCalledWith('media.proxy.start', expect.anything());
  });

  it('unsubscribes from proxy-state on unmount', async () => {
    const off = vi.fn();
    onProxyStateMock.mockReturnValue(off);

    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
    expect(onProxyStateMock).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    expect(off).toHaveBeenCalledTimes(1);
    // re-render so afterEach's unmount is a no-op safe path
    root = createRoot(container);
  });
});

// WU-3a2: the 13 flat tabs are regrouped into 4 NAMED clusters behind
// progressive disclosure. ADDITIVE — every tab stays a real role="tab" and every
// panel reachable; only the visual grouping + the default tab change.
describe('Workspace tab clusters (WU-3a2)', () => {
  function groupLabels(): string[] {
    return Array.from(container.querySelectorAll('.tabbar__group-label')).map(
      (el) => el.textContent ?? '',
    );
  }

  async function mount(): Promise<void> {
    await act(async () => {
      root.render(<Workspace video={video} onBack={() => {}} />);
    });
    await flush();
  }

  it('defaults to the Subtitles tab (off Transcribe)', async () => {
    expect(DEFAULT_WORKSPACE_TAB).toBe('subtitles');
    await mount();

    const subtitles = container.querySelector('[role="tab"][data-tab-id="subtitles"]');
    const transcribe = container.querySelector('[role="tab"][data-tab-id="transcribe"]');
    expect(subtitles?.getAttribute('aria-selected')).toBe('true');
    expect(transcribe?.getAttribute('aria-selected')).toBe('false');
    expect(container.querySelector('[data-panel="Subtitles"]')).not.toBeNull();
  });

  it('renders the four named clusters as section labels', async () => {
    await mount();
    expect(groupLabels()).toEqual(WORKSPACE_TAB_GROUPS.map((g) => g.label));
    expect(groupLabels()).toEqual(['Speech & Text', 'Frame & Cut', 'Audio', 'Deliver']);
  });

  it('keeps every tab reachable: all 13 ids stay in the tablist across clusters', async () => {
    await mount();
    const ids = Array.from(container.querySelectorAll('[role="tab"]'))
      .map((t) => t.getAttribute('data-tab-id'))
      .sort();
    expect(ids).toEqual(WORKSPACE_TABS.map((t) => t.id).sort());
  });

  it('collapses the Deliver cluster behind Advanced by default and toggles it open/closed', async () => {
    await mount();

    const toggle = container.querySelector('.tabbar__advanced-toggle') as HTMLButtonElement;
    const panel = container.querySelector('.tabbar__advanced-panel') as HTMLElement;
    expect(toggle).not.toBeNull();
    // collapsed by default; the Deliver group lives inside the collapsed panel.
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(panel.hidden).toBe(true);
    expect(panel.querySelector('[data-tab-id="tracks"]')).not.toBeNull();

    // expand
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(panel.hidden).toBe(false);

    // collapse again (covers the toggle updater in both directions)
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(panel.hidden).toBe(true);
  });

  it('reaches an Advanced (Deliver) panel after expanding the disclosure', async () => {
    await mount();

    const toggle = container.querySelector('.tabbar__advanced-toggle') as HTMLButtonElement;
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();

    const tracks = container.querySelector(
      '[role="tab"][data-tab-id="tracks"]',
    ) as HTMLButtonElement;
    await act(async () => {
      tracks.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await flush();
    expect(tracks.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('[data-panel="Tracks"]')).not.toBeNull();
  });
});
