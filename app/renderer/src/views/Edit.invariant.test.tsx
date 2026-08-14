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
// THE DEFECT THIS PINS: Edit opened on its Task Hub —
// `useState<'hub'|'workspace'>('hub')` — and mounted the Workspace only after a
// card was picked, so the invariant held from the Workspace MOUNT, not from a
// first open of the destination. Opening a video from the Library therefore cost
// one extra click before any timeline existed.
//
// BOTH-STATES CONTROL — RUN against THIS file as it now stands, all five cases.
// Checking the pre-branch Edit.tsx over this branch's (`git checkout 4c24700b --
// app/renderer/src/views/Edit.tsx`; byte-identical to f8cfbd6c for this path,
// `git diff f8cfbd6c 4c24700b --` on it is empty) and re-running THIS file gives,
// verbatim:
//   × shows the docked timeline on a first open, with no interstitial and no clicks
//       → expected <div class="task-hub" …(1)>…(3)</div> to be null   [:220]
//   × still lands on the docked timeline when a NAVIGATE-AWAY choice is remembered
//       → expected <div class="task-hub" …(1)>…(3)</div> to be null   [:256]
//   ✓ resumes a remembered workspace-scoped choice at its own tab, from the production seed
//   × mounts the editor ONCE on the invariant path — the player survives the settings read
//       → expected +0 to be 1 // Object.is equality                   [:364]
//   ✓ bounds the remembered-tab resume at ONE remount, and keeps the invariant
//   Tests  3 failed | 2 passed (5)
// Restoring this branch's Edit.tsx gives `Tests  5 passed (5)`. So three of the
// five DO fire in the known-broken state, which is the property that makes their
// green here mean anything.
//
// AN EARLIER REVISION OF THIS PARAGRAPH QUOTED A DIFFERENT RUN — "2 failed | 1
// passed (3)", anchored at :166 and :197. That run was real, but it was taken at
// commit 64a0ee52 when this file held THREE cases, and the two seam cases below
// were added in the SAME commit as the note without re-recording it. A transcript
// that describes a file which no longer exists is an evidence-integrity failure
// even when the underlying code is right, so it is replaced here rather than
// deleted quietly. If you change this file, RE-RUN the control and paste the new
// transcript; do not carry this one forward.
//
// EXACTLY WHICH CASES THE CONTROL COVERS, since "3 of 5" is not "all of them":
//   * the two `.task-hub` cases and the seam's control half discriminate — they
//     assert something the hub-first landing cannot satisfy.
//   * the two that PASS at the baseline do not, and neither is weakened by that:
//     the resume case passes because under the hub seed the remembered
//     `{kind:'workspace', tab}` arrived as a FIRST-MOUNT prop and worked, and the
//     remount-bound case passes because that same first-mount path costs exactly
//     one mount. They are guards on the regression this branch itself created,
//     not proofs of the landing.
//
// READ THE TWO PASSING LINES CAREFULLY — they are load-bearing and cut against
// this branch. Landing on the editor is what turned the remembered tab into a
// post-mount prop the Workspace cannot read, so the `key` in Edit.tsx repairs a
// regression this branch introduced — it does not add new surface. That also
// means dropping the resume instead of keying it would REGRESS a shipped
// destination (v1.4.1 carries the hub and the `taskHubChoiceByVideo` writer), not
// merely decline to invent one.
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

  /**
   * How many Workspace INSTANCES have existed: `project.open` is issued once per
   * mount (Workspace.tsx:380 via the `[reloadProject]` effect at :387-389), so
   * this counts mounts. 1 = the editor was built once.
   */
  function openCount(): number {
    return apiRpcMock.mock.calls.filter((call) => call[0] === 'project.open').length;
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
    //     mounted INSIDE the dock body. Asserted as ONE nested selector, not two
    //     independent `querySelector` calls — two calls prove only that both
    //     elements exist somewhere under the dock, which is satisfied by a body
    //     and a panel that are siblings. The nesting is the claim.
    expect(
      el!.querySelector('.workspace__dock-body[role="tabpanel"] [data-panel="VideoTimeline"]'),
    ).not.toBeNull();

    // (4) ZERO navigation actions — asserted, not asserted-by-inspection.
    expect(clicks).toBe(0);

    // (5) And it was built ONCE: the editor the user sees is the one that
    //     mounted, not a rebuild. See the dedicated seam case below for the
    //     player-identity half of this property.
    expect(openCount()).toBe(1);
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
    expect(openCount()).toBe(1);
  });

  // THE SEAM THE LANDING FIX OPENS, PINNED. Seeding 'workspace' means the real
  // Workspace MOUNTS on render 1, BEFORE the async `settings.get` that carries the
  // remembered choice resolves — and the real Workspace reads `initialTab` only in
  // two `useState` lazy initializers (Workspace.tsx:254-260, :270-274), which React
  // runs once per component INSTANCE. Without a remount the resumed tab lands on an
  // already-mounted child and is silently discarded.
  //
  // Neither sibling case above can see that: `{}` never calls setTab, and 'shorts'
  // resumes as `{ kind: 'section' }` which never calls setTab either. Nor can
  // Edit.test.tsx: it stubs Workspace with a component that re-reads `initialTab` on
  // EVERY render, so the stub reports success for a prop the real component ignores.
  // This case is the only place the production seed and a workspace-scoped
  // remembered choice are composed against the REAL Workspace.
  it('resumes a remembered workspace-scoped choice at its own tab, from the production seed', async () => {
    // `resumeFor('subtitles')` → `{ kind: 'workspace', tab: 'subtitles' }`
    // (lib/taskHub.ts:108-109). NOTE the absent `initialMode`: this is the seed a
    // production caller gets, which is the only seed a user can reach.
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'subtitles' } });

    await open();

    // (1) The invariant is NOT traded away to get the resume back: still no hub,
    //     still a timeline dock, still zero navigation actions.
    expect(container.querySelector('.task-hub')).toBeNull();
    const el = dock();
    expect(el).not.toBeNull();
    expect(clicks).toBe(0);

    // (2) The remembered tab actually reached the Workspace. `subtitles` lives in
    //     the 'cue' context (WORKSPACE_INSPECTOR_SECTIONS.cue), so the inspector
    //     opens on Subtitles and names its selection…
    expect(container.querySelector('[data-panel="Subtitles"]')).not.toBeNull();
    expect(container.querySelector('[data-role="selection"]')?.textContent).toBe('Caption cues');
    // …and the dock opens on the matching lane (captions → features/Timeline), not
    //     the default video lane. Both halves must move together: a lane that did
    //     not follow the context is the deep-link landing on a timeline that hides
    //     its own target.
    expect(
      el!.querySelector('.workspace__dock-body[role="tabpanel"] [data-panel="Timeline"]'),
    ).not.toBeNull();
    expect(el!.querySelector('[data-panel="VideoTimeline"]')).toBeNull();
  });

  /**
   * Open with the `settings.get` read still PENDING, snapshot the seam, then
   * release it — the only way to SEE the remount the resume costs.
   *
   * A simpler probe does not work and must not be reused: with an
   * already-resolved `mockResolvedValue`, BOTH mounts land inside the first
   * `act`, so a snapshot taken after it reports `sameNode: true` for the resume
   * case too. Measured: that shape returned `{opens: 2, sameNode: true}` — a
   * detector that reports "the element survived" while the element was in fact
   * replaced, i.e. one that cannot tell the two hypotheses apart. Splitting the
   * settle is what makes it discriminate, and the pair of cases below is its
   * both-states control: same probe, no-choice → preserved, choice → replaced.
   */
  async function openAcrossSettle(choice: string | null): Promise<{
    opensBeforeSettle: number;
    opensAfterSettle: number;
    playerBefore: HTMLVideoElement | null;
    playerAfter: HTMLVideoElement | null;
  }> {
    let release: (settings: unknown) => void = () => undefined;
    rpcMock.mockReset();
    rpcMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    await act(async () => {
      root.render(<Edit video={video} onBack={() => undefined} />);
    });
    const playerBefore = container.querySelector('video');
    const opensBeforeSettle = openCount();
    await act(async () => {
      release(choice === null ? {} : { [HUB_CHOICE_KEY]: { v1: choice } });
      for (let i = 0; i < 8; i++) {
        // eslint-disable-next-line no-await-in-loop
        await Promise.resolve();
      }
    });
    return {
      opensBeforeSettle,
      opensAfterSettle: openCount(),
      playerBefore,
      playerAfter: container.querySelector('video'),
    };
  }

  it('mounts the editor ONCE on the invariant path — the player survives the settings read', async () => {
    // THE CONTROL HALF, and a property in its own right: on every path except a
    // remembered workspace-scoped tab, the async `settings.get` must not disturb
    // the editor that is already on screen. `<Player>` is rendered UNCONDITIONALLY
    // inside Workspace (Workspace.tsx:591-597, single top-level return at :554),
    // so if this path ever acquired a keyed remount the <video> element would be
    // destroyed and recreated — which is precisely what Workspace.tsx:360-363 and
    // :588-590 forbid for the SAME video ("NOT a key-remount, which would visibly
    // restart the element mid-load — the 'shakiness' bug").
    const seam = await openAcrossSettle(null);

    expect(seam.opensBeforeSettle).toBe(1);
    expect(seam.opensAfterSettle).toBe(1);
    expect(seam.playerBefore).not.toBeNull();
    expect(seam.playerAfter).toBe(seam.playerBefore);
  });

  it('bounds the remembered-tab resume at ONE remount, and keeps the invariant', async () => {
    // THE COST OF THE `key`, MEASURED RATHER THAN ASSERTED IN PROSE. Against the
    // control above this same probe returns opens 1 → 2 and a DIFFERENT <video>
    // node: the resume tears the Workspace subtree down and rebuilds it, Player
    // included. That is a real cost and Edit.tsx now enumerates it honestly
    // instead of pricing it as "one extra project.get" (an RPC that does not
    // exist — `git grep project\.get -- app/renderer/src` hits only that comment;
    // Workspace's only rpc call is `project.open`, Workspace.tsx:380).
    //
    // The assertion is an UPPER BOUND, deliberately not `toBe(2)`: pinning the
    // exact count would make this suite go RED the day someone lands the durable
    // fix (Workspace consuming `initialTab` AFTER mount instead of only in its two
    // lazy `useState` initializers, Workspace.tsx:254-260/:270-274) — a gate that
    // punishes fixing the defect it documents. The bound still catches the
    // regression that matters: a key that flips more than once per open.
    const seam = await openAcrossSettle('subtitles');

    expect(seam.opensAfterSettle).toBeLessThanOrEqual(2);
    // And the invariant is not traded away to pay for it.
    expect(container.querySelector('.task-hub')).toBeNull();
    expect(dock()).not.toBeNull();
    expect(clicks).toBe(0);
  });
});
