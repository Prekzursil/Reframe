// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

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

// The feature panels are lazily code-split. Mock each to a deterministic marker
// so switching sections renders something assertable WITHOUT pulling each real
// panel's own rpc wiring into this shell test (they have their own suites).
function stubPanel(label: string) {
  return {
    default: (props: Record<string, unknown>) => {
      const React_ = require('react');
      return React_.createElement(
        'div',
        {
          'data-panel': label,
          'data-videoid': String(props.videoId ?? ''),
        },
        label,
      );
    },
  };
}
vi.mock('../features/Transcribe', () => stubPanel('Transcribe'));
vi.mock('../features/Subtitles', () => stubPanel('Subtitles'));
vi.mock('../features/Tracks', () => stubPanel('Tracks'));
vi.mock('../features/Convert', () => stubPanel('Convert'));
vi.mock('../features/Timeline', () => stubPanel('Timeline'));
vi.mock('../features/Dub', () => stubPanel('Dub'));
vi.mock('../features/AudioMix', () => stubPanel('AudioMix'));
vi.mock('../features/Assets', () => stubPanel('Assets'));
vi.mock('../features/NleExport', () => stubPanel('NleExport'));
vi.mock('../features/Diarize', () => stubPanel('Diarize'));
vi.mock('../features/Refine', () => stubPanel('Refine'));
vi.mock('../features/Stabilize', () => stubPanel('Stabilize'));
vi.mock('../features/TranscriptEditor', () => stubPanel('TranscriptEditor'));
vi.mock('../features/Recipes', () => stubPanel('Recipes'));
vi.mock('../features/SemanticSearch', () => stubPanel('SemanticSearch'));
vi.mock('../features/ReframeCorrect', () => stubPanel('ReframeCorrect'));
// W19 / W16-UI: same STUB caveat as every other panel here — this file proves the
// inspector mapping and the props handed down, NOT that the lazy chunk resolves.
// The real lazy mounts are asserted in `Workspace.seam.test.tsx`.
vi.mock('../features/Speed', () => stubPanel('Speed'));
vi.mock('../features/Gaze', () => stubPanel('Gaze'));
vi.mock('../features/BrollPanel', () => stubPanel('BrollPanel'));

// The DOCKED video timeline is not a passive marker: the inspector follows the
// clip it reports (Q7 `onSelectClip`) and the dock shows the file it produced
// (Q7 `onRendered`). The stub exposes both edges as buttons so those wires can be
// driven from a test without mounting the real editor.
// ASYNC factory with a real `import`, unlike the marker stubs above: this stub uses
// a HOOK, and `require('react')` hands back the CJS copy of React whose hook
// dispatcher is null under the ESM renderer ("Cannot read properties of null
// (reading 'useEffect')"). `createElement` is a pure function and survives the
// duplicate copy; `useEffect` does not.
vi.mock('../features/VideoTimeline', async () => {
  const React_ = await import('react');
  return {
    default: (props: Record<string, unknown>) => {
      const select = props.onSelectClip as ((id: string | null) => void) | undefined;
      const rendered = props.onRendered as ((path: string) => void) | undefined;
      // FIDELITY, not decoration. The real panel holds `selected` internally
      // (VideoTimeline.tsx:135) and publishes it from an effect (:145-147), so
      // EVERY mount reports `null` before the user has touched anything —
      // including the remount a lane switch causes, because `renderLane()` returns
      // a different element TYPE per lane (Workspace.tsx:474-505). A stub without
      // this effect cannot reproduce that report, and the Export-after-a-lane-
      // switch defect below shipped under exactly that blind spot.
      React_.useEffect(() => {
        select?.(null);
      }, [select]);
      return React_.createElement(
        'div',
        {
          'data-panel': 'VideoTimeline',
          'data-videoid': String(props.videoId ?? ''),
          'data-sourcepath': String(props.sourcePath ?? ''),
          'data-duration': String(props.sourceDurationSec ?? ''),
        },
        React_.createElement(
          'button',
          { type: 'button', 'data-action': 'select-clip', onClick: () => select?.('c1') },
          'select clip',
        ),
        React_.createElement(
          'button',
          { type: 'button', 'data-action': 'clear-clip', onClick: () => select?.(null) },
          'clear clip',
        ),
        React_.createElement(
          'button',
          {
            type: 'button',
            'data-action': 'finish-render',
            onClick: () => rendered?.('D:/out/timeline.mp4'),
          },
          'finish render',
        ),
      );
    },
  };
});

import {
  Workspace,
  WORKSPACE_TABS,
  WORKSPACE_DOCK_LANES,
  WORKSPACE_DOCK_PANELS,
  WORKSPACE_INSPECTOR_SECTIONS,
  WORKSPACE_PANELS_ELSEWHERE,
  WORKSPACE_EXPORT_TAB,
  workspacePanelHome,
} from './Workspace';
import type { Video, Project } from '../components/api';

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

async function render(props: Record<string, unknown> = {}): Promise<void> {
  await act(async () => {
    root.render(<Workspace video={video} onBack={() => {}} {...props} />);
  });
  await flush();
}

async function clickEl(el: Element | null): Promise<void> {
  expect(el).not.toBeNull();
  await act(async () => {
    (el as HTMLElement).dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  await flush();
}

/** A tab button anywhere in the workspace (dock lane heads + inspector sections). */
const tabEl = (id: string): Element | null =>
  container.querySelector(`[role="tab"][data-tab-id="${id}"]`);
/** The inspector's own tab buttons only. */
const inspectorTabIds = (): string[] =>
  Array.from(container.querySelectorAll('.workspace__inspector [role="tab"]')).map(
    (t) => t.getAttribute('data-tab-id') ?? '',
  );
const dockAction = (action: string): Element | null =>
  container.querySelector(`.workspace__dock [data-action="${action}"]`);
const selectionLabel = (): string =>
  container.querySelector('[data-role="selection"]')?.textContent ?? '';

/**
 * Read the workspace stylesheet from disk. `import.meta.url` is NOT a file URL
 * under the vitest transform (fileURLToPath rejects it), and `__dirname` does not
 * exist in the ESM output, so resolve from the runner's cwd and FAIL LOUDLY if
 * the file is not where we expect — a silently-empty read would make every CSS
 * assertion below vacuous.
 */
function readWorkspaceCss(): string {
  const candidates = [
    resolve(process.cwd(), 'renderer/src/views/workspace.css'),
    resolve(process.cwd(), 'app/renderer/src/views/workspace.css'),
  ];
  const found = candidates.find((p) => existsSync(p));
  expect(found).toBeDefined();
  return readFileSync(found as string, 'utf8').replace(/\r\n/g, '\n');
}

describe('Workspace', () => {
  // THE PANEL REGISTRY, pinned exactly and in order. Two labels changed with the
  // L5 rebuild and nothing else moved:
  //   'Subtitle timeline' -> 'Caption cues'   (features/Timeline.tsx: subtitle CUES)
  //   'Video timeline'    -> 'Video clips'    (features/VideoTimeline.tsx: CLIPS)
  // Those two panels used to sit two tabs apart in one strip while sharing the
  // word "timeline" for two different document models — work item 6. They are now
  // the two named LANES of one dock, and the labels say which model each holds.
  //
  // WIDENED/NARROWED: neither. All 21 entries and their order are unchanged.
  it('exposes all 21 panels in the registry, in order, with the two timeline labels disambiguated', () => {
    expect(WORKSPACE_TABS.map((t) => t.label)).toEqual([
      'Transcribe',
      'Search',
      'Subtitles',
      'Transcript edit',
      'Diarize',
      'Refine',
      'Tracks',
      'Convert',
      'Short-maker',
      'Fix framing',
      'Caption cues',
      'Video clips',
      'Auto B-roll',
      'Stabilize',
      'Eye contact',
      'Speed',
      'Dub',
      'Audio mix',
      'NLE export',
      'Recipes',
      'Assets',
    ]);
    expect(WORKSPACE_TABS).toHaveLength(21);
  });

  // The naming invariant, pinned per-id so it survives a panel being inserted or
  // reordered by another lane. Neither of these two panels may claim the bare word
  // "Timeline", and — the part that is new — they may not be confusable with each
  // other, because they are two different models (cues vs clips).
  it('never lets the caption-cue editor and the clip editor share one word', () => {
    const byId = (id: string): string | undefined => WORKSPACE_TABS.find((t) => t.id === id)?.label;
    expect(byId('timeline')).toBe('Caption cues');
    expect(byId('videoTimeline')).toBe('Video clips');
    // features/NleExport.tsx = CMX3600 EDL / CSV handoff for Premiere/Resolve.
    expect(byId('nle')).toBe('NLE export');
    const labels = WORKSPACE_TABS.map((t) => t.label);
    expect(labels).not.toContain('Timeline');
    expect(labels).not.toContain('Timeline export');
    // Both are dock LANES now, and the lane heads carry the same disambiguated
    // names — so the two models are never presented as interchangeable tabs.
    expect(WORKSPACE_DOCK_LANES.map((l) => l.label)).toEqual([
      'Video clips',
      'Caption cues',
      'Program audio',
    ]);
  });

  // A constant saying "Caption cues" is not the same signal as a BUTTON showing
  // it — the two tests above read the arrays directly. This one goes through the
  // real TabBar and reads the DOM, which is what a user sees.
  it('renders the disambiguated lane names on the real dock buttons, not just in the array', async () => {
    await render();
    expect(tabEl('video')?.textContent).toBe('Video clips');
    expect(tabEl('captions')?.textContent).toBe('Caption cues');
    expect(tabEl('audio')?.textContent).toBe('Program audio');
  });

  it('opens the project via project.open and shows the title', async () => {
    await render();
    expect(rpcMock).toHaveBeenCalledWith('project.open', { id: 'v1' });
    expect(container.textContent).toContain('Talk');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.project]);
  });

  it('mounts a feature panel slot for the default (project) selection', async () => {
    await render();
    expect(container.querySelector('.workspace__body')).not.toBeNull();
    expect(container.querySelector('[data-panel="Transcribe"]')).not.toBeNull();
  });

  it('switches the active inspector section when a section is clicked', async () => {
    await render();
    await clickEl(tabEl('diarize'));
    expect(tabEl('diarize')?.getAttribute('aria-selected')).toBe('true');
    expect(tabEl('transcribe')?.getAttribute('aria-selected')).toBe('false');
    expect(container.querySelector('[data-panel="Diarize"]')).not.toBeNull();
  });

  it('honours an initial deep-link (Task Hub) instead of the default selection', async () => {
    await render({ initialTab: 'subtitles' });
    // 'subtitles' is a CUE-context tool, so the deep-link also opens the caption
    // lane — otherwise the link would land on a section its own context hides.
    expect(selectionLabel()).toBe('Caption cues');
    expect(tabEl('subtitles')?.getAttribute('aria-selected')).toBe('true');
    expect(container.querySelector('[data-panel="Subtitles"]')).not.toBeNull();
    expect(container.querySelector('[data-panel="Timeline"]')).not.toBeNull();
  });

  it('ignores an unrecognised deep-link rather than rendering an empty inspector', async () => {
    await render({ initialTab: 'no-such-panel' });
    expect(selectionLabel()).toBe('Project');
    expect(container.querySelector('[data-panel="Transcribe"]')).not.toBeNull();
  });

  it('calls onBack when the back button is pressed', async () => {
    const onBack = vi.fn();
    await render({ onBack });
    await clickEl(container.querySelector('button.workspace__back'));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('surfaces a project.open error', async () => {
    rpcMock.mockReset();
    rpcMock.mockRejectedValue(new Error('open failed'));
    await render();
    expect(container.textContent).toContain('open failed');
  });

  it('stringifies a non-Error project.open rejection', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.reject('boom-string');
      return Promise.resolve({ playable: true });
    });
    await render();
    expect(container.querySelector('.workspace__error')?.textContent).toContain('boom-string');
  });

  it('tolerates a null/absent project payload (no throw, no error banner)', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'project.open') return Promise.resolve(null);
      return Promise.resolve({ playable: true });
    });
    await render();
    expect(container.querySelector('.workspace__error')).toBeNull();
    // the shell does not depend on `project` to show its navigation
    expect(inspectorTabIds().length).toBeGreaterThan(0);
  });

  it("wires the inspector tabpanel's id + aria-labelledby to the active section", async () => {
    await render();
    const panel = container.querySelector('.workspace__body[role="tabpanel"]');
    expect(panel).not.toBeNull();
    const activeTab = container.querySelector(
      '.workspace__inspector [role="tab"][aria-selected="true"]',
    );
    expect(activeTab).not.toBeNull();
    expect(panel?.getAttribute('id')).toBe(activeTab?.getAttribute('aria-controls'));
    expect(panel?.getAttribute('aria-labelledby')).toBe(activeTab?.getAttribute('id'));

    await clickEl(tabEl('diarize'));
    expect(panel?.getAttribute('id')).toBe('tabpanel-diarize');
    expect(panel?.getAttribute('aria-labelledby')).toBe('tab-diarize');
  });

  it('wires the dock tabpanel to the selected lane', async () => {
    await render();
    const dockPanel = container.querySelector('.workspace__dock-body[role="tabpanel"]');
    expect(dockPanel?.getAttribute('id')).toBe('tabpanel-video');
    expect(dockPanel?.getAttribute('aria-labelledby')).toBe('tab-video');
    await clickEl(tabEl('captions'));
    expect(dockPanel?.getAttribute('id')).toBe('tabpanel-captions');
  });

  // WU B3: the mstream resolver builds the proxy; the Workspace only REACTS to
  // the main process's `proxy.state` pushes. Drive the callback directly.
  async function renderAndCaptureProxyState(): Promise<(e: ProxyStateEvt) => void> {
    let cb: ((e: ProxyStateEvt) => void) | null = null;
    onProxyStateMock.mockImplementation((fn) => {
      cb = fn;
      return () => undefined;
    });
    await render();
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
    const note = container.querySelector('.workspace__player-note');
    expect(note?.textContent).toContain('Building preview');
    // The transient status is announced to assistive tech (polite live region),
    // mirroring every other status note in the app (not color/text-only).
    expect(note?.getAttribute('role')).toBe('status');
    expect(note?.getAttribute('aria-live')).toBe('polite');

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
    expect(container.querySelector('.workspace__player-note')?.textContent).toContain(
      'needs proxy',
    );
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
    await act(async () =>
      emit({ videoId: 'v1', state: 'error', detail: 'ffmpeg exited with code 1' }),
    );
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
    await act(async () =>
      emit({ videoId: 'v1', state: 'error', detail: 'ffmpeg exited with code 1' }),
    );
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
    await render();
    // the Workspace never kicks the build itself (the resolver does).
    expect(container.querySelector('.workspace__player-note')).toBeNull();
    expect(rpcMock).not.toHaveBeenCalledWith('media.playable', expect.anything());
    expect(rpcMock).not.toHaveBeenCalledWith('media.proxy.start', expect.anything());
  });

  it('unsubscribes from proxy-state on unmount', async () => {
    const off = vi.fn();
    onProxyStateMock.mockReturnValue(off);
    await render();
    expect(onProxyStateMock).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    expect(off).toHaveBeenCalledTimes(1);
    // re-render so afterEach's unmount is a no-op safe path
    root = createRoot(container);
  });
});

// ---------------------------------------------------------------------------
// THE L5 ACCEPTANCE GATE. Four of the five mechanical invariants live here (the
// fifth — the rail has exactly 5 entries — is asserted in App.test.tsx, which
// owns the rail). Each is a real test, not a claim.
// ---------------------------------------------------------------------------

describe('L5 invariant: all 21 panels stay reachable (reconcile, never drop)', () => {
  // INVARIANT 5, the mechanical half. A reorganisation cannot silently delete a
  // feature: every registry id must have exactly one home, and every home entry
  // must name a real registry id (so the mapping cannot drift into ghosts either).
  it('partitions every registry id across inspector / dock / elsewhere exactly once', () => {
    const homes = WORKSPACE_TABS.map((t) => workspacePanelHome(t.id));
    expect(homes.filter((h) => h === null)).toEqual([]);

    const claimed = [
      ...WORKSPACE_INSPECTOR_SECTIONS.clip,
      ...WORKSPACE_INSPECTOR_SECTIONS.cue,
      ...WORKSPACE_INSPECTOR_SECTIONS.audio,
      ...WORKSPACE_INSPECTOR_SECTIONS.project,
      ...Object.keys(WORKSPACE_DOCK_PANELS),
      ...WORKSPACE_PANELS_ELSEWHERE,
    ];
    expect(claimed).toHaveLength(21);
    expect([...new Set(claimed)].sort()).toEqual(WORKSPACE_TABS.map((t) => t.id).sort());
  });

  // The owner's L5 G-5 table, transcribed. Pinned literally so a later lane
  // cannot quietly re-home a consent surface (gaze / broll) out of the context
  // where its tool is used.
  it('matches the owner-locked selection mapping', () => {
    expect(WORKSPACE_INSPECTOR_SECTIONS.clip).toEqual([
      'reframeFix',
      'speed',
      'stabilize',
      'gaze',
      'broll',
    ]);
    expect(WORKSPACE_INSPECTOR_SECTIONS.cue).toEqual(['subtitles', 'transcriptEdit']);
    expect(WORKSPACE_INSPECTOR_SECTIONS.audio).toEqual(['audiomix', 'dub']);
    expect(WORKSPACE_INSPECTOR_SECTIONS.project).toEqual([
      'transcribe',
      'search',
      'diarize',
      'refine',
      'recipes',
      'convert',
      'nle',
      'tracks',
      'assets',
    ]);
    expect(WORKSPACE_DOCK_PANELS).toEqual({ videoTimeline: 'video', timeline: 'captions' });
    expect(WORKSPACE_PANELS_ELSEWHERE).toEqual(['shortmaker']);
  });

  // INVARIANT 5, the behavioural half: an ENUMERATED WALK. Every inspector panel
  // is opened for real, through its own selection context, and its marker asserted
  // in the DOM. Deleting a `case` from renderPanel(), or dropping an id from the
  // mapping, turns exactly one of these red.
  const inspectorPanels: Array<[string, string]> = [
    ['transcribe', 'Transcribe'],
    ['search', 'SemanticSearch'],
    ['diarize', 'Diarize'],
    ['refine', 'Refine'],
    ['recipes', 'Recipes'],
    ['convert', 'Convert'],
    ['nle', 'NleExport'],
    ['tracks', 'Tracks'],
    ['assets', 'Assets'],
    ['subtitles', 'Subtitles'],
    ['transcriptEdit', 'TranscriptEditor'],
    ['audiomix', 'AudioMix'],
    ['dub', 'Dub'],
    ['reframeFix', 'ReframeCorrect'],
    ['speed', 'Speed'],
    ['stabilize', 'Stabilize'],
    ['gaze', 'Gaze'],
    ['broll', 'BrollPanel'],
  ];

  it.each(inspectorPanels)('reaches the %s panel through its selection', async (id, marker) => {
    const home = workspacePanelHome(id);
    await render();
    // Put the workspace into the context that owns this panel, the way a user
    // would: pick the lane, and for clip tools pick a clip inside the video lane.
    if (home === 'cue') await clickEl(tabEl('captions'));
    if (home === 'audio') await clickEl(tabEl('audio'));
    if (home === 'clip') await clickEl(dockAction('select-clip'));
    await clickEl(tabEl(id));

    const panel = container.querySelector(`[data-panel="${marker}"]`);
    expect(panel).not.toBeNull();
    if (marker !== 'Assets') {
      expect(panel?.getAttribute('data-videoid')).toBe('v1');
    }
  });

  it('reaches both dock panels with no navigation beyond picking the lane', async () => {
    await render();
    // videoTimeline: ZERO actions (invariant 4, asserted again below).
    expect(container.querySelector('[data-panel="VideoTimeline"]')).not.toBeNull();
    await clickEl(tabEl('captions'));
    expect(container.querySelector('[data-panel="Timeline"]')).not.toBeNull();
  });

  it('routes the one panel another destination owns instead of dropping it', async () => {
    // `shortmaker` moved to the Produce rail destination (L5 G-6). It must not be
    // an inspector section here, and the deep-link must still reach its owner.
    expect(workspacePanelHome('shortmaker')).toBe('elsewhere');
    const onOpenMakeShorts = vi.fn();
    await render({ initialTab: 'shortmaker', onOpenMakeShorts });
    expect(onOpenMakeShorts).toHaveBeenCalledTimes(1);
    expect(onOpenMakeShorts).toHaveBeenCalledWith('v1');
    expect(container.querySelector('[data-panel="ShortMaker"]')).toBeNull();
    expect(inspectorTabIds()).not.toContain('shortmaker');
  });

  it('does not crash on a shortmaker deep-link with no owner wired', async () => {
    // Without the callback there is nothing to redirect to; the workspace opens on
    // its default rather than mounting a second ShortMaker copy (WU-3a4's
    // single-owner rule, now enforced by the rail rather than by a fallback).
    await render({ initialTab: 'shortmaker' });
    expect(container.querySelector('[data-panel="ShortMaker"]')).toBeNull();
    expect(selectionLabel()).toBe('Project');
  });
});

describe('L5 invariant: the timeline is docked, not navigated to', () => {
  // INVARIANT 4. The video timeline used to be tab #12 of 21. It is now visible
  // the moment the workspace opens, with ZERO clicks, keystrokes or deep-links.
  //
  // SCOPE OF WHAT THIS FILE PROVES, stated so the row in the PR table cannot be
  // read wider than the evidence: `render()` mounts the WORKSPACE COMPONENT. The
  // Refine DESTINATION reaches it through views/Edit.tsx, which still opens on its
  // Task Hub (Edit.tsx:69 `useState('hub')`, :163) unless a remembered choice
  // resumes into the workspace (lib/taskHub.ts:109, :111). So the destination-level
  // invariant is NOT met on a first open, Edit.tsx is outside this lane's file
  // scope, and no App-level suite closes the gap — measured: zero hits for
  // `workspace__dock|VideoTimeline|TaskHub` across App.test.tsx and its three
  // App.*.test.tsx siblings, which follows from App.test.tsx:59 mocking
  // `./views/Edit` outright, so neither the real hub nor the real workspace is ever
  // mounted beside the rail. The settling test, for whoever owns
  // Edit.tsx next: assert `.workspace__dock [data-panel="VideoTimeline"]` after
  // Library → open video with no intervening click.
  it('shows the video timeline with zero navigation actions', async () => {
    await render();
    const dock = container.querySelector('.workspace__dock');
    expect(dock).not.toBeNull();
    const panel = dock?.querySelector('[data-panel="VideoTimeline"]');
    expect(panel).not.toBeNull();
    // and it is threaded with what `tracks.video.addClip` needs (W18).
    expect(panel?.getAttribute('data-sourcepath')).toBe('/movies/talk.mp4');
    expect(panel?.getAttribute('data-duration')).toBe('605');
  });

  it('keeps the preview mounted alongside it (coexisting, not swapped)', async () => {
    await render();
    expect(container.querySelector('.workspace__player video')).not.toBeNull();
    expect(container.querySelector('.workspace__dock [data-panel="VideoTimeline"]')).not.toBeNull();
  });

  it('opens the caption-cue lane on a dock deep-link, and the inspector follows it', async () => {
    await render({ initialTab: 'timeline' });
    expect(container.querySelector('[data-panel="Timeline"]')).not.toBeNull();
    // A dock panel is not an inspector SECTION, so nothing is pinned — but the
    // lane is now the selection, and the inspector follows the selection. That is
    // the rule working, not an exception to it.
    expect(selectionLabel()).toBe('Caption cues');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.cue]);
  });

  it('renders the program-audio lane when it is selected', async () => {
    await render();
    await clickEl(tabEl('audio'));
    const laneEl = container.querySelector('[data-role="program-audio"]');
    expect(laneEl).not.toBeNull();
    expect(laneEl?.textContent).toContain('Program audio');
    expect(laneEl?.textContent).toContain('Talk');
  });
});

describe('L5 invariant: navigation cannot overflow the fixed 1280px window', () => {
  // INVARIANT 1, made structural rather than eyeballed.
  //
  // SCOPE OF THIS CLAIM, stated plainly: jsdom performs NO layout, so no unit
  // test in this suite can measure pixels. What it CAN do is assert the two
  // structural properties that made overflow possible, and which a future lane
  // would have to undo to bring it back:
  //   (a) the number of items in a horizontal navigation is BOUNDED and small;
  //   (b) the unbounded list — the inspector's sections, which is where a new
  //       feature lands — runs VERTICALLY, so it cannot grow sideways at all.
  // The true pixel assertion at 1280x820 belongs to the Playwright e2e spec,
  // which this lane does not own. UNVERIFIED here, by construction.
  it('leaves exactly one horizontal navigation in the workspace, capped at 3 lanes', async () => {
    await render();
    expect(WORKSPACE_DOCK_LANES).toHaveLength(3);
    const dockTabs = container.querySelectorAll('.workspace__dock [role="tab"]');
    expect(dockTabs).toHaveLength(3);
    // The 16-painted-tab strip and its scrollport are gone, not merely hidden.
    expect(container.querySelector('.tabbar--grouped')).toBeNull();
    expect(container.querySelector('.tabbar__tablist')).toBeNull();
  });

  it('grows a context vertically: the inspector list is a column in the stylesheet', () => {
    // Reading the sheet is the only way to assert a CSS decision from jsdom, and
    // it is a real detector: flipping this rule back to a row turns it red.
    // USE-vs-MENTION: the sheet's header comment NAMES `overflow-x: auto` while
    // explaining why the scrollport was removed, so the last assertion must read
    // DECLARATIONS only. Measured: without this strip it fails on the prose.
    const css = readWorkspaceCss().replace(/\/\*[\s\S]*?\*\//g, '');
    // CONTROL first: the selector must actually exist, or the slice below would be
    // the whole file and `toContain` could pass by accident.
    expect(css).toContain('.workspace .workspace__inspector .tabbar {');
    const rule = css.slice(css.indexOf('.workspace .workspace__inspector .tabbar {'));
    const block = rule.slice(0, rule.indexOf('}'));
    expect(block).toContain('flex-direction: column');
    // And no rule in this sheet re-creates a horizontally scrolling tab strip.
    expect(css).not.toContain('overflow-x: auto');
  });

  it('has no "Advanced" trapdoor left to hide a surface behind', async () => {
    await render();
    // The two-level IA (painted-forever vs a one-way Advanced hatch) is the
    // measured root cause. Selection-driven disclosure replaces it; if either of
    // these comes back, the growth pressure comes back with it.
    expect(container.querySelector('.tabbar__advanced-toggle')).toBeNull();
    expect(container.querySelector('.tabbar__advanced-panel')).toBeNull();
  });

  // The consent/honesty surfaces are the reason the old strip could only grow.
  // They must now appear WITH their tool, at the moment of use — not behind a
  // disclosure, and not painted forever.
  it.each([
    ['gaze'],
    ['broll'],
  ])('surfaces the %s consent/honesty tool on selection, never behind a disclosure', async (id) => {
    await render();
    expect(inspectorTabIds()).not.toContain(id);
    await clickEl(dockAction('select-clip'));
    expect(inspectorTabIds()).toContain(id);
    expect(tabEl(id)?.closest('[hidden]')).toBeNull();
  });
});

describe('the inspector follows the selection (L5 G-5)', () => {
  it('opens on the project context with nothing selected', async () => {
    await render();
    expect(selectionLabel()).toBe('Project');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.project]);
  });

  it('swaps to clip tools when a clip is selected in the docked timeline', async () => {
    await render();
    await clickEl(dockAction('select-clip'));
    expect(selectionLabel()).toBe('Selected clip');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.clip]);
    expect(container.querySelector('[data-panel="ReframeCorrect"]')).not.toBeNull();
  });

  it('returns to project tools when the clip selection is cleared', async () => {
    await render();
    await clickEl(dockAction('select-clip'));
    await clickEl(dockAction('clear-clip'));
    expect(selectionLabel()).toBe('Project');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.project]);
  });

  it('ignores a repeated report of the SAME selection (the mount-time null)', async () => {
    // The panel reports its initial `null` on mount. That is state, not a user
    // action, so it must not clear a pinned deep-link the user has not touched.
    await render({ initialTab: 'gaze' });
    expect(selectionLabel()).toBe('Selected clip');
    await clickEl(dockAction('clear-clip'));
    expect(selectionLabel()).toBe('Selected clip');
    expect(tabEl('gaze')?.getAttribute('aria-selected')).toBe('true');
  });

  it('drops a CLIP-scoped pin when the clip it belongs to goes away', async () => {
    // The other half of the rule: a vanished clip invalidates a pin that only
    // makes sense WITH a clip, and nothing else. (A project pin surviving the same
    // report is what the Export-from-the-caption-lane test asserts.)
    await render();
    await clickEl(dockAction('select-clip'));
    await clickEl(tabEl('speed'));
    expect(container.querySelector('[data-panel="Speed"]')).not.toBeNull();

    await clickEl(dockAction('clear-clip'));
    expect(selectionLabel()).toBe('Project');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.project]);
  });

  it('lets a real selection change take over from a pinned deep-link', async () => {
    await render({ initialTab: 'gaze' });
    await clickEl(tabEl('captions'));
    expect(selectionLabel()).toBe('Caption cues');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.cue]);
  });

  it('reads audio tools off the program-audio lane', async () => {
    await render();
    await clickEl(tabEl('audio'));
    expect(selectionLabel()).toBe('Program audio');
    expect(inspectorTabIds()).toEqual([...WORKSPACE_INSPECTOR_SECTIONS.audio]);
    expect(container.querySelector('[data-panel="AudioMix"]')).not.toBeNull();
  });

  it('keeps a chosen section active while its context holds', async () => {
    await render();
    await clickEl(tabEl('search'));
    expect(container.querySelector('[data-panel="SemanticSearch"]')).not.toBeNull();
    // switching lanes is a selection change, so the pin drops
    await clickEl(tabEl('captions'));
    expect(container.querySelector('[data-panel="Subtitles"]')).not.toBeNull();
  });
});

describe('Q7: the docked render is no longer an orphan', () => {
  it('reports the rendered file to the workspace as a live region', async () => {
    await render();
    expect(container.querySelector('.workspace__dock-note')).toBeNull();
    await clickEl(dockAction('finish-render'));
    const note = container.querySelector('.workspace__dock-note');
    expect(note?.textContent).toContain('D:/out/timeline.mp4');
    expect(note?.getAttribute('role')).toBe('status');
  });
});

describe('Workspace Export affordance (design-review P1)', () => {
  it('targets a real project-scoped panel as the export destination', () => {
    expect(WORKSPACE_EXPORT_TAB).toBe('convert');
    expect(workspacePanelHome(WORKSPACE_EXPORT_TAB)).toBe('project');
    expect(WORKSPACE_TABS.some((t) => t.id === WORKSPACE_EXPORT_TAB)).toBe(true);
  });

  it('surfaces a persistent Export action in the header, outside any scrollport', async () => {
    await render();
    const exportBtn = container.querySelector('.workspace__header button.workspace__export');
    expect(exportBtn).not.toBeNull();
    expect(exportBtn?.textContent).toContain('Export');
    expect(container.querySelector('[data-panel="Convert"]')).toBeNull();
  });

  it('jumps to the Convert export panel on click, from any selection', async () => {
    await render();
    // start somewhere else entirely: a clip selected, clip tools showing
    await clickEl(dockAction('select-clip'));
    expect(selectionLabel()).toBe('Selected clip');

    await clickEl(container.querySelector('button.workspace__export'));
    expect(container.querySelector('[data-panel="Convert"]')).not.toBeNull();
    expect(tabEl('convert')?.getAttribute('aria-selected')).toBe('true');
    expect(selectionLabel()).toBe('Project');
  });

  // The test above starts on the video lane, which is the ONE case where Export
  // does not remount the timeline — so "from any selection" was one case, not any.
  it('lands on Convert from the caption lane too, where Export remounts the dock', async () => {
    await render();
    await clickEl(dockAction('select-clip'));
    // Leave the video lane: `renderLane()` swaps the element type, unmounting the
    // timeline. Export switches the lane BACK, so a fresh panel mounts and reports
    // `null` — a report that used to clear the pin the same click had just set and
    // dropped the inspector onto `sections[0]`, Transcribe.
    await clickEl(tabEl('captions'));
    expect(selectionLabel()).toBe('Caption cues');

    await clickEl(container.querySelector('button.workspace__export'));
    expect(container.querySelector('[data-panel="Convert"]')).not.toBeNull();
    expect(container.querySelector('[data-panel="Transcribe"]')).toBeNull();
    expect(tabEl('convert')?.getAttribute('aria-selected')).toBe('true');
  });

  it('gives the clip inspector back when the same clip is picked again', async () => {
    // Export pins a PROJECT panel while the clip stays selected in the timeline
    // (`tracks.video.list` auto-seeds ONE whole-source clip, so "pick a different
    // clip" is usually not even available). Re-picking that clip is the gesture a
    // user reaches for, so a report of the SAME id must drop a pin belonging to
    // another context instead of being swallowed as "no change".
    await render();
    await clickEl(dockAction('select-clip'));
    await clickEl(container.querySelector('button.workspace__export'));
    expect(selectionLabel()).toBe('Project');

    await clickEl(dockAction('select-clip'));
    expect(selectionLabel()).toBe('Selected clip');
    expect(container.querySelector('[data-panel="ReframeCorrect"]')).not.toBeNull();
  });
});
