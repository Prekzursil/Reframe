// Edit.invariant.test.tsx — L5 G-7 INVARIANT 2, as a test:
// "The timeline is VISIBLE in Refine with ZERO navigation actions."
// (docs: L5-NAVIGATION-DECISIONS.md G-7, mechanical invariant 2.)
//
// WHY THIS FILE EXISTS, SEPARATELY FROM Edit.test.tsx
// Edit.test.tsx stubs <Workspace/>, so "Edit mounted the Workspace" is all it can
// ever assert there — a stub cannot prove a TIMELINE is on screen. This file
// mounts the REAL Workspace inside the REAL Edit and asserts the DOCK itself, so
// the claim is about the composition, not about a marker div. That is the exact
// blind spot Workspace.seam.test.tsx was created for on the other edge: both
// halves green while their composition was broken.
//
// WHAT "ZERO NAVIGATION ACTIONS" MEANS MECHANICALLY: between `root.render(...)`
// and the assertion there is no click, no key, no route change. A document-level
// click counter is asserted to be 0 so that a future edit cannot quietly "fix" a
// red run here by adding one — clicking to reach the timeline IS the defect.
//
// THE DEFECT THIS PINS (measured on origin/main f8cfbd6c, before this branch):
// Edit opened on its Task Hub — `useState<'hub'|'workspace'>('hub')` — and mounted
// the Workspace only after a card was picked, so the invariant held from the
// Workspace mount, NOT from a first open of the destination. Opening a video from
// the Library therefore cost one extra click before any timeline existed.
//
// @vitest-environment jsdom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom does not implement HTMLMediaElement playback and the real <Player> the
// Workspace mounts touches load()/play()/pause() (same backing as
// Workspace.test.tsx:11-25).
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

// Workspace's wire surface (Workspace.tsx:5).
const apiRpcMock = vi.fn();
vi.mock('../components/api', () => ({
  rpc: (...args: unknown[]) => apiRpcMock(...args),
  onProgress: () => () => {},
  hasApi: () => true,
}));

// Edit reads settings through lib/rpc (Edit.tsx:32); Workspace subscribes to
// proxy pushes from the same module (Workspace.tsx:6). ONE factory serves both.
const rpcMock = vi.fn();
vi.mock('../lib/rpc', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  hasApi: () => true,
  onProxyState: () => () => undefined,
}));

// The feature panels are lazily code-split and own their own suites; stub each to
// a deterministic marker (the same technique as Workspace.test.tsx:51-87) so this
// file measures the SHELL composition, not each panel's wiring. The dock element
// asserted below is rendered by Workspace itself, not by any of these.
function stubPanel(label: string) {
  return async () => {
    const React_ = await import('react');
    return {
      default: (props: Record<string, unknown>) =>
        React_.createElement(
          'div',
          { 'data-panel': label, 'data-videoid': String(props.videoId ?? '') },
          label,
        ),
    };
  };
}
vi.mock('../features/VideoTimeline', stubPanel('VideoTimeline'));
vi.mock('../features/Timeline', stubPanel('Timeline'));
vi.mock('../features/Transcribe', stubPanel('Transcribe'));
vi.mock('../features/Subtitles', stubPanel('Subtitles'));
vi.mock('../features/Tracks', stubPanel('Tracks'));
vi.mock('../features/Convert', stubPanel('Convert'));
vi.mock('../features/Dub', stubPanel('Dub'));
vi.mock('../features/AudioMix', stubPanel('AudioMix'));
vi.mock('../features/Assets', stubPanel('Assets'));
vi.mock('../features/NleExport', stubPanel('NleExport'));
vi.mock('../features/Diarize', stubPanel('Diarize'));
vi.mock('../features/Refine', stubPanel('Refine'));
vi.mock('../features/Stabilize', stubPanel('Stabilize'));
vi.mock('../features/TranscriptEditor', stubPanel('TranscriptEditor'));
vi.mock('../features/Recipes', stubPanel('Recipes'));
vi.mock('../features/SemanticSearch', stubPanel('SemanticSearch'));
vi.mock('../features/ReframeCorrect', stubPanel('ReframeCorrect'));
vi.mock('../features/Speed', stubPanel('Speed'));
vi.mock('../features/Gaze', stubPanel('Gaze'));
vi.mock('../features/BrollPanel', stubPanel('BrollPanel'));

import { Edit } from './Edit';
import { HUB_CHOICE_KEY } from '../lib/taskHub';
import type { Video } from '../lib/rpc';

const video: Video = {
  id: 'v1',
  path: '/movies/talk.mp4',
  title: 'Talk',
  addedAt: '2026-06-27T00:00:00Z',
  durationSec: 605,
  hasTranscript: false,
};

describe('L5 G-7 invariant 2 — the timeline is visible in Refine with zero navigation actions', () => {
  let container: HTMLDivElement;
  let root: Root;
  let clicks: number;
  const countClick = (): void => {
    clicks += 1;
  };

  beforeEach(() => {
    apiRpcMock.mockReset();
    apiRpcMock.mockResolvedValue({
      project: { id: 'v1', video, tracks: [], clips: [], settings: {} },
    });
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({}); // settings.get → no remembered choice
    clicks = 0;
    document.addEventListener('click', countClick, true);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    document.removeEventListener('click', countClick, true);
    act(() => root.unmount());
    container.remove();
  });

  async function open(): Promise<void> {
    await act(async () => {
      root.render(<Edit video={video} onBack={() => undefined} />);
    });
    await act(async () => {
      for (let i = 0; i < 8; i++) {
        // eslint-disable-next-line no-await-in-loop
        await Promise.resolve();
      }
    });
  }

  /** The dock is `<section class="workspace__dock" aria-label="Timeline">`. */
  function dock(): HTMLElement | null {
    return container.querySelector('.workspace__dock');
  }

  it('shows the docked timeline on a first open, with no interstitial and no clicks', async () => {
    await open();

    // (1) NOTHING stands between the destination and the editor.
    expect(container.querySelector('.task-hub')).toBeNull();

    // (2) The dock is on screen, and it is the TIMELINE dock (its accessible name).
    const el = dock();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('aria-label')).toBe('Timeline');

    // (3) It is a real timeline lane, not an empty shell: the video-clips lane
    //     mounted inside the dock body.
    expect(el!.querySelector('[data-panel="VideoTimeline"]')).not.toBeNull();
    expect(el!.querySelector('.workspace__dock-body[role="tabpanel"]')).not.toBeNull();

    // (4) ZERO navigation actions — asserted, not asserted-by-inspection.
    expect(clicks).toBe(0);
  });

  it('still lands on the docked timeline when a NAVIGATE-AWAY choice is remembered', async () => {
    // 'shorts' resumes as `{ kind: 'section' }` (lib/taskHub.ts:113-114): it is
    // MARKED as last-used and never auto-navigated to, because bouncing the user
    // out of the video they just opened is unescapable. Before this branch that
    // meant "stay on the hub"; the invariant does not admit that exception, so a
    // remembered section choice must still land on the timeline.
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'shorts' } });

    await open();

    expect(container.querySelector('.task-hub')).toBeNull();
    expect(dock()).not.toBeNull();
    expect(clicks).toBe(0);
  });
});
