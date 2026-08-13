// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Video } from '../lib/rpc';

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// The Workspace is the heavy per-video body (owns its own tests); stub it, but
// expose the initialTab Edit threads in (the Task Hub deep-link).
vi.mock('./Workspace', () => ({
  Workspace: ({
    video,
    onBack,
    initialTab,
  }: {
    video: Video;
    onBack: () => void;
    initialTab?: string;
  }) => (
    <div data-testid="workspace" data-video-id={video.id} data-initial-tab={initialTab ?? ''}>
      <button type="button" onClick={onBack}>
        back
      </button>
    </div>
  ),
}));

// The Task Hub owns its own tests; stub it to expose the choices Edit routes on.
vi.mock('./TaskHub', () => ({
  TaskHub: ({
    video,
    lastChoice,
    onChoose,
  }: {
    video: Video;
    lastChoice: string | null;
    onChoose: (c: string) => void;
  }) => (
    <div data-testid="taskhub" data-video-id={video.id} data-last={lastChoice ?? ''}>
      {['reframe', 'subtitles', 'shorts', 'director', 'advanced'].map((c) => (
        <button key={c} type="button" onClick={() => onChoose(c)}>
          {c}
        </button>
      ))}
    </div>
  ),
}));

// Control the persistence surface (hasApi gate + the settings.get/set RPC).
const rpcMock = vi.fn();
let hasApiReturn = true;
vi.mock('../lib/rpc', () => ({
  rpc: (...args: unknown[]) => rpcMock(...args),
  hasApi: () => hasApiReturn,
}));

import { Edit } from './Edit';
import { HUB_CARDS, HUB_CHOICE_KEY, REDIRECT_ONLY_WORKSPACE_TABS } from '../lib/taskHub';

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    id: 'v1',
    path: '/m/a.mp4',
    title: 'A',
    addedAt: '2026-06-27T00:00:00Z',
    durationSec: 100,
    hasTranscript: false,
    ...over,
  };
}

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('<Edit />', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({}); // settings.get → no remembered choice
    hasApiReturn = true;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function hub(): HTMLElement {
    return container.querySelector('[data-testid="taskhub"]') as HTMLElement;
  }
  function workspace(): HTMLElement | null {
    return container.querySelector('[data-testid="workspace"]');
  }
  function pick(choice: string): void {
    const btn = Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === choice,
    );
    if (!btn) throw new Error(`hub choice "${choice}" not found`);
    act(() => btn.click());
  }

  it('shows the empty state when no video is open', () => {
    act(() => root.render(<Edit video={null} onBack={() => undefined} />));
    expect(container.querySelector('.edit--empty')).toBeTruthy();
    expect(container.querySelector('.edit__empty-title')?.textContent).toBe('No video open');
    // WU-D3: the empty carries the shared ghost-poster anchor (poster + glyph),
    // not the old bare sentence.
    expect(container.querySelector('.edit__empty-poster')).toBeTruthy();
    expect(container.querySelector('.edit__empty-glyph')).toBeTruthy();
    expect(hub()).toBeNull();
    expect(workspace()).toBeNull();
  });

  // C3 (docs/plans/v1.5/uiux-qol-audit-2026-08.md §5) — the empty state PROMISED
  // "trim, cut, join, reframe, caption, and more — every edit tool lives here".
  // The merged editing-surface audit measures the opposite for the first three:
  // docs/plans/v1.5/editing-surface-audit-2026-08.md:44 — "no trim, no cut, no
  // join tab"; :45-48 — those engines are reachable "only through" the AI
  // Director, and "a user cannot drag a cut"; rows 1-3 (:82-84) mark trim, cut
  // and split "engine BUILT ... UI MISSING". Nothing named in this copy may be a
  // verb the user cannot reach from here.
  it('does not promise editing verbs the app cannot deliver', () => {
    act(() => root.render(<Edit video={null} onBack={() => undefined} />));
    const hint = container.querySelector('.edit__empty-hint')!.textContent!;
    // Guard the guard: the copy must actually be present, or the absence checks
    // below would pass over an empty string.
    expect(hint.length).toBeGreaterThan(20);
    for (const unreachable of ['trim', 'cut', 'join']) {
      expect(hint.toLowerCase()).not.toContain(unreachable);
    }
    // ...and it must still say something true about what IS reachable.
    expect(hint.toLowerCase()).toContain('subtitle');
  });

  // M2 — Edit was the only one of eight empty states with no way forward. The
  // sibling views already ship this affordance (views/Caption.tsx:102-104,
  // views/Export.tsx:251-253); Edit did not.
  it('offers a way forward to the Library', () => {
    const onBack = vi.fn();
    act(() => root.render(<Edit video={null} onBack={onBack} />));
    const back = container.querySelector<HTMLButtonElement>('.edit__empty-back');
    expect(back).not.toBeNull();
    act(() => back!.click());
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  // SPEC CHANGE, not a weakened test. This case used to read "lands on the Task
  // Hub (not the Workspace) when a video is opened" and asserted the hub. That
  // pinned the behaviour L5 G-7 invariant 2 forbids — "the timeline is VISIBLE in
  // Refine with ZERO navigation actions" — which the owner locked and which was
  // the last of the five still failing. The assertions are inverted, not dropped:
  // the same three facts (which surface mounted, for which video, and that the
  // remembered-choice read still runs) are still pinned, now against the editor.
  // The invariant itself — a real DOCK, not this stubbed marker — is proven in
  // Edit.invariant.test.tsx against the REAL Workspace.
  it('lands on the Workspace (not the Task Hub) when a video is opened', async () => {
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    await flush();
    expect(workspace()).toBeTruthy();
    expect(workspace()!.getAttribute('data-video-id')).toBe('v1');
    expect(hub()).toBeNull();
    expect(rpcMock).toHaveBeenCalledWith('settings.get');
  });

  // ...and the Task Hub is NOT deleted by that landing change. It is a designed
  // surface; a caller that wants the job chooser asks for it, and every card and
  // the advanced escape below still route from it.
  it('opens the Task Hub when a caller asks for it', async () => {
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-video-id')).toBe('v1');
    expect(workspace()).toBeNull();
  });

  it('routes the reframe card STRAIGHT to the Make Shorts owner (never via Workspace) + persists', async () => {
    // REVISED: this previously asserted the card mounted `Workspace` with
    // `data-initial-tab='shortmaker'`. WU-3a4 moved ShortMaker OUT of the Workspace,
    // so that tab is a mount-time redirect — mounting Workspace only to be bounced
    // out of it is what made Edit permanently unreachable for the video (the
    // remembered choice re-triggered the bounce on every mount, across restarts,
    // with no UI to clear it). The card must deep-link to the single owner directly.
    const onMakeShortsForVideo = vi.fn();
    act(() =>
      root.render(
        <Edit
          video={makeVideo()}
          onBack={() => undefined}
          onMakeShortsForVideo={onMakeShortsForVideo}
          initialMode="hub"
        />,
      ),
    );
    await flush();
    pick('reframe');
    expect(onMakeShortsForVideo).toHaveBeenCalledWith('v1');
    // and it does NOT detour through the Workspace at all
    expect(workspace()).toBeNull();
    expect(rpcMock).toHaveBeenCalledWith('settings.set', {
      [HUB_CHOICE_KEY]: { v1: 'reframe' },
    });
  });

  // SEAM INVARIANT — closes the gap that let the soft-lock ship. Edit's own tests stub
  // Workspace and Workspace's tests exercise the mount-redirect in isolation, so BOTH
  // halves were green while their COMPOSITION was broken. This asserts the contract at
  // the boundary between them: whatever Edit hands Workspace as `initialTab` must be a
  // tab Workspace actually renders, never one it redirects away from on mount.
  // Covers every card + the advanced escape, so a future redirect-only tab cannot
  // silently reintroduce the bounce loop.
  it('never hands Workspace a redirect-only initialTab, for ANY choice', async () => {
    for (const choice of [...HUB_CARDS.map((c) => c.id), 'advanced']) {
      // A DISTINCT video id per iteration: `root.render` of the same element type reuses
      // the React instance, so `mode` would stay 'workspace' from a previous iteration
      // and the hub would no longer be rendered. Changing `video.id` goes through Edit's
      // documented reset-on-reopen effect (Edit.tsx: setMode('hub') on [videoId]).
      act(() =>
        root.render(
          <Edit
            video={makeVideo({ id: `seam-${choice}` })}
            onBack={() => undefined}
            onMakeShorts={() => undefined}
            onMakeShortsForVideo={() => undefined}
            onDirector={() => undefined}
            initialMode="hub"
          />,
        ),
      );
      await flush();
      pick(choice);
      const ws = workspace();
      if (ws) {
        const initial = ws.getAttribute('data-initial-tab') ?? '';
        expect(
          REDIRECT_ONLY_WORKSPACE_TABS,
          `choice '${choice}' mounted Workspace with initialTab='${initial}', which redirects away on mount`,
        ).not.toContain(initial);
      }
    }
  });

  it('routes the subtitles card into the Workspace at the Subtitles tab', async () => {
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    pick('subtitles');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('routes the advanced escape into the Workspace default tab (no initial tab)', async () => {
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    pick('advanced');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('');
  });

  it('routes the section cards to the App callbacks and stays on the hub', async () => {
    const onMakeShorts = vi.fn();
    const onDirector = vi.fn();
    act(() =>
      root.render(
        <Edit
          video={makeVideo()}
          onBack={() => undefined}
          onMakeShorts={onMakeShorts}
          onDirector={onDirector}
          initialMode="hub"
        />,
      ),
    );
    await flush();
    pick('shorts');
    expect(onMakeShorts).toHaveBeenCalledTimes(1);
    pick('director');
    expect(onDirector).toHaveBeenCalledTimes(1);
    // section cards do not switch to the Workspace (they leave via the App shell).
    expect(workspace()).toBeNull();
  });

  it('tolerates section cards when no App callbacks are wired', async () => {
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    pick('shorts');
    pick('director');
    expect(hub()).toBeTruthy();
  });

  // STRENGTHENED: the seed is 'hub' here, so this now proves the remembered
  // workspace-scoped choice OVERRIDES an explicit hub request, not merely that it
  // agrees with a hub default.
  it('resumes a workspace-scoped remembered choice in place (skips the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'subtitles' } });
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(hub()).toBeNull();
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('marks a remembered section choice but stays on the hub', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue({ [HUB_CHOICE_KEY]: { v1: 'shorts' } });
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-last')).toBe('shorts');
  });

  it('tolerates a null settings payload (stays on the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockResolvedValue(null);
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(hub()).toBeTruthy();
    expect(hub().getAttribute('data-last')).toBe('');
  });

  it('tolerates a settings.get rejection (stays on the hub)', async () => {
    rpcMock.mockReset();
    rpcMock.mockRejectedValue(new Error('read failed'));
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(hub()).toBeTruthy();
  });

  it('does not touch settings when the preload bridge is absent', async () => {
    hasApiReturn = false;
    act(() =>
      root.render(<Edit video={makeVideo()} onBack={() => undefined} initialMode="hub" />),
    );
    await flush();
    expect(rpcMock).not.toHaveBeenCalled();
    // a choice still routes (in-memory), just without a settings.set. Use the
    // in-place 'subtitles' card so this test measures the BRIDGE-ABSENT behaviour and
    // not reframe's routing (which now deep-links out and mounts no Workspace).
    pick('subtitles');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
    expect(rpcMock).not.toHaveBeenCalled();
  });

  it('re-reads the remembered choice when the opened video changes', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ [HUB_CHOICE_KEY]: { v1: 'reframe', v2: 'subtitles' } });
      }
      return Promise.resolve({});
    });
    const onMakeShortsForVideo = vi.fn();
    act(() =>
      root.render(
        <Edit
          video={makeVideo({ id: 'v1' })}
          onBack={() => undefined}
          onMakeShortsForVideo={onMakeShortsForVideo}
          initialMode="hub"
        />,
      ),
    );
    await flush();
    // v1's remembered choice is 'reframe' — a NAVIGATE-AWAY choice, so it is only
    // MARKED, never auto-resumed. Auto-resuming it is the soft-lock: it would bounce
    // the user out of the video they just opened, on every mount, forever.
    expect(workspace()).toBeNull();
    expect(onMakeShortsForVideo).not.toHaveBeenCalled();
    // switch to a different video: the effect re-runs and resumes v2's choice.
    act(() =>
      root.render(
        <Edit video={makeVideo({ id: 'v2' })} onBack={() => undefined} initialMode="hub" />,
      ),
    );
    await flush();
    expect(workspace()!.getAttribute('data-video-id')).toBe('v2');
    expect(workspace()!.getAttribute('data-initial-tab')).toBe('subtitles');
  });

  it('preserves other videos when persisting a choice (read-modify-write)', async () => {
    rpcMock.mockReset();
    rpcMock.mockImplementation((method: string) => {
      if (method === 'settings.get') {
        return Promise.resolve({ [HUB_CHOICE_KEY]: { v2: 'director' } });
      }
      return Promise.resolve({});
    });
    act(() =>
      root.render(
        <Edit video={makeVideo({ id: 'v1' })} onBack={() => undefined} initialMode="hub" />,
      ),
    );
    await flush();
    pick('reframe');
    expect(rpcMock).toHaveBeenCalledWith('settings.set', {
      [HUB_CHOICE_KEY]: { v2: 'director', v1: 'reframe' },
    });
  });

  it('ignores a settings.get that resolves after unmount', async () => {
    let resolveGet: (v: unknown) => void = () => undefined;
    rpcMock.mockReset();
    rpcMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        }),
    );
    act(() => root.render(<Edit video={makeVideo()} onBack={() => undefined} />));
    // unmount BEFORE the settings.get resolves → the late result must be ignored.
    act(() => root.unmount());
    await act(async () => {
      resolveGet({ [HUB_CHOICE_KEY]: { v1: 'subtitles' } });
      await Promise.resolve();
    });
    // nothing rendered (still unmounted); no throw.
    expect(container.querySelector('[data-testid="workspace"]')).toBeNull();
    // re-mount so afterEach's unmount is a safe no-op.
    root = createRoot(container);
  });

  // No `pick` here any more: the Workspace is what the destination lands on, so
  // this measures the back control on the PRODUCTION path rather than behind a
  // hub click.
  it('forwards the Workspace back control', async () => {
    const onBack = vi.fn();
    act(() => root.render(<Edit video={makeVideo()} onBack={onBack} />));
    await flush();
    act(() =>
      (container.querySelector('[data-testid="workspace"] button') as HTMLButtonElement).click(),
    );
    expect(onBack).toHaveBeenCalled();
  });
});
